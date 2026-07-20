"""Offline-only ACE-Step v1 adapter ported from the frozen old-repo binding.

The port carries operational API shape and native sampler settings only. It
does not carry old prompts, seeds, results, cost measurements, or decisions.
Model and source acquisition are intentionally absent: callers must supply an
exact local checkpoint and the exact clean upstream source revision.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from backbones.contracts import (
    DEFAULT_ACE_CONFIG,
    BackboneConfigurationError,
    BackbonePreflight,
    GenerationMeasurement,
    GenerationRequest,
    PipelineFactory,
    load_backbone_config,
)
from backbones.io import copy_file_exclusive, temporary_output_path, verify_checkpoint_files
from backbones.runtime import CudaTelemetry, count_method_calls, verify_clean_git_revision


def _canonical_manifest_sha256(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        records,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_exact_checkpoint_tree(
    root: str | Path,
    required_files: list[dict[str, Any]],
    expected_tree_sha256: str,
) -> dict[str, Any]:
    """Hash every regular checkpoint file and reject extras, links, or omissions."""

    checkpoint_root = Path(root).resolve()
    configured = sorted(required_files, key=lambda row: str(row.get("path", "")))
    configured_paths = [str(row.get("path", "")) for row in configured]
    if configured_paths != sorted(set(configured_paths)):
        raise BackboneConfigurationError("checkpoint manifest paths must be unique and sorted")
    if _canonical_manifest_sha256(configured) != expected_tree_sha256:
        raise BackboneConfigurationError("configured checkpoint tree SHA-256 is inconsistent")

    observed_paths: list[str] = []
    forbidden_entries: list[str] = []
    for candidate in sorted(checkpoint_root.rglob("*")):
        relative = candidate.relative_to(checkpoint_root).as_posix()
        if candidate.is_symlink():
            forbidden_entries.append(relative)
        elif candidate.is_file():
            observed_paths.append(relative)
        elif not candidate.is_dir():
            forbidden_entries.append(relative)
    if forbidden_entries:
        raise BackboneConfigurationError(
            f"checkpoint tree contains symlink or non-file entries: {forbidden_entries}"
        )
    if observed_paths != configured_paths:
        missing = sorted(set(configured_paths) - set(observed_paths))
        extra = sorted(set(observed_paths) - set(configured_paths))
        raise BackboneConfigurationError(
            f"checkpoint tree differs from exact manifest: missing={missing}, extra={extra}"
        )
    observed = verify_checkpoint_files(checkpoint_root, configured, hash_files=True)
    normalized = [
        {
            "path": row["path"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
        }
        for row in observed
    ]
    observed_tree_sha256 = _canonical_manifest_sha256(normalized)
    if observed_tree_sha256 != expected_tree_sha256:
        raise BackboneConfigurationError("observed checkpoint tree SHA-256 mismatch")
    return {
        "file_count": len(normalized),
        "files": observed,
        "tree_sha256": observed_tree_sha256,
        "tree_rule": "SHA256(canonical JSON of lexicographically sorted path/sha256/size rows)",
        "exact_tree_no_exclusions": True,
    }


class AceStepV1Adapter:
    """Exact local ACE-Step v1 inference binding with measured call metadata."""

    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_ACE_CONFIG,
        evidence_dir: str | Path | None = None,
        checkpoint_dir: str | Path | None = None,
        source_dir: str | Path | None = None,
        device: str = "cuda",
        pipeline_factory: PipelineFactory | None = None,
        telemetry_factory: PipelineFactory = CudaTelemetry,
    ) -> None:
        self.config, self.config_sha256 = load_backbone_config(config_path)
        if self.config["logical_name"] != "ACE-Step v1":
            raise BackboneConfigurationError("ACE adapter received a different model config")
        self.logical_name = self.config["logical_name"]
        self.model_id = self.config["model_id"]
        self.license_identifier = self.config["license_identifier"]
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        checkpoint_env = self.config["adapter"]["local_checkpoint_environment_variable"]
        source_env = self.config["adapter"]["local_source_environment_variable"]
        checkpoint_value = checkpoint_dir or os.environ.get(checkpoint_env)
        source_value = source_dir or os.environ.get(source_env)
        self.checkpoint_dir = Path(checkpoint_value) if checkpoint_value else None
        self.source_dir = Path(source_value) if source_value else None
        self.device = device
        self._device_id = self._parse_device(device)
        self._pipeline_factory = pipeline_factory
        self._telemetry_factory = telemetry_factory
        self._pipeline: Any | None = None
        self._preflight: BackbonePreflight | None = None
        self._load_wall_seconds: float | None = None

    @staticmethod
    def _parse_device(device: str) -> int:
        if device == "cuda":
            return 0
        if device.startswith("cuda:"):
            suffix = device.split(":", 1)[1]
            if suffix.isdigit():
                return int(suffix)
        raise ValueError("ACE-Step v1 requires device='cuda' or 'cuda:N'")

    def preflight(self) -> BackbonePreflight:
        """Verify content-pinned local weights and exact source, without loading CUDA."""

        if self._preflight is not None:
            return self._preflight
        checkpoint = self.config.get("checkpoint")
        if not isinstance(checkpoint, dict) or not isinstance(
            checkpoint.get("required_files"), list
        ):
            raise BackboneConfigurationError("ACE config lacks checkpoint.required_files")
        if self.checkpoint_dir is None:
            raise BackboneConfigurationError(
                "ACE_STEP_V1_CHECKPOINT_DIR or checkpoint_dir is required; "
                "auto-download is forbidden"
            )
        exact_tree_sha256 = checkpoint.get("exact_tree_sha256")
        if not isinstance(exact_tree_sha256, str):
            raise BackboneConfigurationError("ACE config lacks checkpoint.exact_tree_sha256")
        checkpoint_tree = verify_exact_checkpoint_tree(
            self.checkpoint_dir,
            checkpoint["required_files"],
            exact_tree_sha256,
        )
        provenance = self.config.get("provenance")
        if not isinstance(provenance, dict):
            raise BackboneConfigurationError("ACE config lacks provenance")
        expected_source_revision = provenance.get("upstream_code_revision")
        if not isinstance(expected_source_revision, str):
            raise BackboneConfigurationError("ACE upstream code revision is absent")
        expected_source_tree = provenance.get("upstream_code_tree")
        if not isinstance(expected_source_tree, str):
            raise BackboneConfigurationError("ACE upstream code tree is absent")
        if self._pipeline_factory is None:
            if self.source_dir is None:
                raise BackboneConfigurationError(
                    "ACE_STEP_V1_SOURCE_DIR or source_dir is required; source fallback is forbidden"
                )
            source = verify_clean_git_revision(
                self.source_dir,
                expected_source_revision,
                expected_tree=expected_source_tree,
            )
        else:
            source = {
                "source_dir": "INJECTED_TEST_FACTORY",
                "revision": expected_source_revision,
                "tree": expected_source_tree,
                "tracked_worktree": "NOT_APPLICABLE_TEST_FACTORY",
            }
        self._preflight = BackbonePreflight(
            status="READY_FOR_MINI_SMOKE",
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={
                "checkpoint_dir": str(self.checkpoint_dir.resolve()),
                "checkpoint_tree": checkpoint_tree,
                "source": source,
                "network_downloads_allowed": False,
            },
        )
        return self._preflight

    def _ensure_loaded(self) -> None:
        if self._pipeline is not None:
            return
        self.preflight()
        started = time.perf_counter()
        if self._pipeline_factory is None:
            try:
                from acestep.pipeline_ace_step import ACEStepPipeline
            except ImportError as exc:
                raise ImportError(
                    "exact ACE-Step v1 upstream package is not importable from the verified source"
                ) from exc
            factory: PipelineFactory = ACEStepPipeline
        else:
            factory = self._pipeline_factory
        generation = self.config["generation"]
        pipeline = factory(
            checkpoint_dir=str(self.checkpoint_dir.resolve()),
            device_id=self._device_id,
            dtype=generation["dtype"],
        )
        if not hasattr(pipeline, "load_checkpoint"):
            raise RuntimeError("ACE-Step pipeline lacks load_checkpoint")
        pipeline.load_checkpoint(str(self.checkpoint_dir.resolve()))
        if not hasattr(pipeline, "ace_step_transformer"):
            raise RuntimeError("ACE-Step pipeline lacks the measurable transformer surface")
        self._pipeline = pipeline
        self._load_wall_seconds = time.perf_counter() - started

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        """Run one official call, count transformer decodes, and retain WAV exclusively."""

        if os.path.lexists(request.output_path):
            raise FileExistsError(request.output_path)
        max_duration = float(self.config["mini_smoke_caps"]["max_clip_seconds"])
        if request.duration_seconds > max_duration:
            raise ValueError(f"request exceeds {max_duration}-second ACE mini-smoke cap")
        self._ensure_loaded()
        generation = self.config["generation"]
        telemetry = self._telemetry_factory(self.device)
        with temporary_output_path() as temporary:
            kwargs = {
                "format": generation["format"],
                "audio_duration": request.duration_seconds,
                "prompt": request.prompt,
                "lyrics": request.lyrics,
                "infer_step": generation["inference_steps"],
                "guidance_scale": generation["guidance_scale"],
                "manual_seeds": [request.seed],
                "scheduler_type": generation["scheduler_type"],
                "cfg_type": generation["cfg_type"],
                "guidance_interval": generation["guidance_interval"],
                "use_erg_tag": generation["use_erg_tag"],
                "use_erg_lyric": generation["use_erg_lyric"],
                "use_erg_diffusion": generation["use_erg_diffusion"],
                "save_path": str(temporary),
            }
            with (
                telemetry.measured() as measured,
                count_method_calls(self._pipeline.ace_step_transformer, "decode") as nfe,
            ):
                self._pipeline(**kwargs)
            if not temporary.is_file():
                raise RuntimeError("ACE-Step pipeline returned without the requested WAV")
            copy_file_exclusive(temporary, request.output_path)
        if nfe["calls"] <= 0:
            raise RuntimeError("ACE-Step call produced no measured transformer forwards")
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=int(generation["sample_rate"]),
            requested_steps=int(generation["inference_steps"]),
            actual_nfe=nfe["calls"],
            wall_seconds=float(measured["wall_seconds"]),
            peak_allocated_bytes=int(measured["peak_allocated_bytes"]),
            peak_reserved_bytes=int(measured["peak_reserved_bytes"]),
            metadata={
                "load_wall_seconds": self._load_wall_seconds,
                "config_sha256": self.config_sha256,
                "scheduler_shift": generation["scheduler_shift"],
                "upstream_kwargs": kwargs,
            },
        )

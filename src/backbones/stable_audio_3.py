"""Benchmark adapter for the verified Stable Audio 3 Medium Base snapshot."""

from __future__ import annotations

import importlib.metadata
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from backbones.contracts import (
    REPOSITORY_ROOT,
    BackboneConfigurationError,
    BackbonePreflight,
    GenerationMeasurement,
    GenerationRequest,
    load_backbone_config,
    sha256_file,
    strict_json_object,
)
from backbones.io import verify_checkpoint_files
from backbones.runtime import CudaTelemetry
from sa3_smoke.audio import save_float_wav_exclusive
from sa3_smoke.environment_validation import collect_runtime_probe
from sa3_smoke.model_runtime import load_local_model, resolve_local_model_config

DEFAULT_SA3_CONFIG = REPOSITORY_ROOT / "configs" / "backbones" / "stable_audio_3_medium_base.json"
FOUNDATION_BUDGET_ENVIRONMENT = (
    "SA3_FOUNDATION_BUDGET_STATE",
    "SA3_FOUNDATION_GENERATION_LEDGER",
    "SA3_FOUNDATION_BUDGET_LOCK",
    "SA3_FOUNDATION_EXECUTION_CLAIM",
    "SA3_FOUNDATION_CURRENT_SMOKE",
)


class StableAudio3MediumBaseAdapter:
    """Network-free wrapper around the official ``StableAudioModel.generate`` path."""

    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_SA3_CONFIG,
        snapshot_dir: str | Path | None = None,
        config_resolution_dir: str | Path | None = None,
        device: str = "cuda",
        validate_environment: bool = True,
    ) -> None:
        self.config, self.config_sha256 = load_backbone_config(config_path)
        if self.config["logical_name"] != "stable-audio-3-medium-base":
            raise BackboneConfigurationError("SA3 adapter received a different model config")
        self.logical_name = self.config["logical_name"]
        self.model_id = self.config["model_id"]
        self.license_identifier = self.config["license_identifier"]
        adapter = self.config["adapter"]
        snapshot_env = adapter["local_snapshot_environment_variable"]
        selected_snapshot = snapshot_dir or os.environ.get(snapshot_env) or adapter[
            "frozen_default_snapshot"
        ]
        self.snapshot_dir = Path(selected_snapshot)
        self.config_resolution_dir = (
            Path(config_resolution_dir) if config_resolution_dir is not None else None
        )
        if device != "cuda" and not (device.startswith("cuda:") and device[5:].isdigit()):
            raise ValueError("SA3 requires device='cuda' or 'cuda:N'")
        self.device = device
        self.validate_environment = validate_environment
        self._preflight: BackbonePreflight | None = None
        self._runtime: Any | None = None
        self._load_wall_seconds: float | None = None

    def _validate_committed_provenance(self) -> dict[str, Any]:
        provenance = self.config["provenance"]
        records: dict[str, Any] = {}
        for key in (
            "foundation_config",
            "foundation_report",
            "model_runtime_source",
            "weights_manifest",
            "cross_provider_verification",
        ):
            source = provenance[key]
            path = REPOSITORY_ROOT / source["path"]
            observed = sha256_file(path)
            if observed != source["sha256"]:
                raise BackboneConfigurationError(
                    f"committed SA3 provenance drift for {source['path']}: {observed}"
                )
            records[key] = {"path": str(path), "sha256": observed}
        cross = strict_json_object(records["cross_provider_verification"]["path"])
        if cross.get("status") != "PASS":
            raise BackboneConfigurationError("SA3 cross-provider verification is not PASS")
        if cross.get("huggingface", {}).get("revision") != provenance["huggingface_revision"]:
            raise BackboneConfigurationError("SA3 Hugging Face revision drift")
        if cross.get("modelscope", {}).get("revision") != provenance["modelscope_revision"]:
            raise BackboneConfigurationError("SA3 ModelScope revision drift")
        return records

    def _validate_benchmark_runtime(self) -> dict[str, Any]:
        """Validate frozen dependencies without reusing the source-tree freeze gate.

        The foundation validator intentionally pins the old ``pyproject.toml``.
        Benchmark packaging adds this adapter package, so this narrower gate
        verifies the unchanged environment artifacts, live versions, and
        import locations while reporting that source-packaging boundary.
        """

        runtime = self.config["runtime"]
        committed_files: dict[str, Any] = {}
        failures: list[str] = []
        for key in ("package_freeze", "runtime_record", "licenses"):
            record = runtime[key]
            path = REPOSITORY_ROOT / record["path"]
            observed = sha256_file(path)
            committed_files[key] = {
                "path": str(path),
                "expected_sha256": record["sha256"],
                "observed_sha256": observed,
            }
            if observed != record["sha256"]:
                failures.append(f"{record['path']} hash drift")

        probe = collect_runtime_probe()
        if probe.get("python_version") != runtime["python"]:
            failures.append(
                f"Python drift: {probe.get('python_version')} != {runtime['python']}"
            )
        if probe.get("torch_cuda_version") != runtime["cuda_build"]:
            failures.append(
                f"CUDA build drift: {probe.get('torch_cuda_version')} != {runtime['cuda_build']}"
            )
        expected_prefix = Path(runtime["environment_path"]).resolve()
        observed_prefix = Path(str(probe.get("sys_prefix", ""))).resolve()
        if observed_prefix != expected_prefix:
            failures.append(f"environment prefix drift: {observed_prefix} != {expected_prefix}")

        module_locations: dict[str, str | None] = {}
        modules = probe.get("modules", {})
        for name in ("torch", "torchaudio", "flash_attn", "stable_audio_3", "stable_audio_tools"):
            record = modules.get(name, {}) if isinstance(modules, dict) else {}
            location = record.get("file") if isinstance(record, dict) else None
            module_locations[name] = location
            try:
                Path(str(location)).resolve().relative_to(expected_prefix)
            except ValueError:
                failures.append(f"{name} import is outside the frozen environment: {location}")
        sa3_record = modules.get("sa3_smoke", {}) if isinstance(modules, dict) else {}
        sa3_location = sa3_record.get("file") if isinstance(sa3_record, dict) else None
        module_locations["sa3_smoke"] = sa3_location
        try:
            Path(str(sa3_location)).resolve().relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            failures.append(f"sa3_smoke import is outside this repository: {sa3_location}")

        distributions: dict[str, str | None] = {}
        for name, expected in runtime["distributions"].items():
            try:
                observed = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                observed = None
            distributions[name] = observed
            if observed != expected:
                failures.append(f"{name} drift: {observed} != {expected}")
        if failures:
            raise BackboneConfigurationError("SA3 benchmark runtime drift: " + "; ".join(failures))
        return {
            "passed": True,
            "committed_files": committed_files,
            "python_version": probe["python_version"],
            "torch_cuda_version": probe["torch_cuda_version"],
            "environment_prefix": str(observed_prefix),
            "module_locations": module_locations,
            "distributions": distributions,
            "source_packaging_boundary": runtime["source_packaging_boundary"],
        }

    def preflight(self) -> BackbonePreflight:
        """Verify project records, full runtime snapshot content, and live environment."""

        if self._preflight is not None:
            return self._preflight
        inherited_foundation_budget = [
            name for name in FOUNDATION_BUDGET_ENVIRONMENT if os.environ.get(name) is not None
        ]
        if inherited_foundation_budget:
            raise BackboneConfigurationError(
                "benchmark adapter refuses inherited foundation-smoke budget state: "
                + ", ".join(inherited_foundation_budget)
            )
        records = self._validate_committed_provenance()
        checkpoint = self.config["checkpoint"]
        files = verify_checkpoint_files(
            self.snapshot_dir,
            checkpoint["required_files"],
            hash_files=True,
        )
        if self.validate_environment:
            environment = self._validate_benchmark_runtime()
        else:
            environment = {"passed": None, "reason": "disabled only for injected CPU tests"}
        self._preflight = BackbonePreflight(
            status="READY_FOR_MINI_SMOKE",
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={
                "snapshot_dir": str(self.snapshot_dir.resolve()),
                "checkpoint_files": files,
                "committed_provenance": records,
                "environment": environment,
                "resolved_provider_revision": self.config["provenance"][
                    "huggingface_revision"
                ],
                "network_downloads_allowed": False,
                "state_capability": self.config["provenance"]["state_capability"],
            },
        )
        return self._preflight

    def _ensure_loaded(self) -> None:
        if self._runtime is not None:
            return
        self.preflight()
        if self.config_resolution_dir is None:
            raise BackboneConfigurationError(
                "config_resolution_dir must name a fresh run-local evidence directory"
            )
        if os.path.lexists(self.config_resolution_dir):
            raise FileExistsError(self.config_resolution_dir)
        started = time.perf_counter()
        resolution = resolve_local_model_config(
            self.snapshot_dir / "model_config.json",
            self.snapshot_dir / "t5gemma-b-b-ul2",
            self.config_resolution_dir,
        )
        model_file = self.snapshot_dir / "model.safetensors"
        expected_sha = next(
            item["sha256"]
            for item in self.config["checkpoint"]["required_files"]
            if item["path"] == "model.safetensors"
        )
        self._runtime = load_local_model(
            resolution,
            model_file,
            device=self.device,
            model_half=bool(self.config["generation"]["model_half"]),
            expected_checkpoint_sha256=expected_sha,
        )
        self._load_wall_seconds = time.perf_counter() - started

    @staticmethod
    def _channels_first_batch_one(output: Any) -> np.ndarray:
        if hasattr(output, "detach"):
            output = output.detach().float().cpu().numpy()
        array = np.asarray(output, dtype=np.float32)
        if array.ndim == 2:
            array = array[None, ...]
        if array.ndim != 3 or array.shape[0] != 1 or array.shape[1] != 2:
            raise RuntimeError(f"SA3 expected batch-one stereo output, got shape {array.shape}")
        return np.ascontiguousarray(array[0])

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        """Execute one measured official call and retain the decoded waveform exclusively."""

        if os.path.lexists(request.output_path):
            raise FileExistsError(request.output_path)
        if request.lyrics:
            raise ValueError("SA3 has no separate lyrics field; encode requested lyrics in prompt")
        max_duration = float(self.config["mini_smoke_caps"]["max_clip_seconds"])
        if request.duration_seconds > max_duration:
            raise ValueError(f"request exceeds {max_duration}-second SA3 mini-smoke cap")
        self._ensure_loaded()
        generation = self.config["generation"]
        official = self._runtime.stable_audio_model
        backbone = getattr(official, "dit", None)
        if backbone is None or not hasattr(backbone, "register_forward_pre_hook"):
            raise RuntimeError("cannot measure SA3 NFE: official DiT hook surface is absent")
        counts = {"nfe": 0, "sampler_callbacks": 0}

        def count_forward(_module: Any, _inputs: Any) -> None:
            counts["nfe"] += 1

        def count_callback(_info: Any) -> None:
            counts["sampler_callbacks"] += 1

        hook = backbone.register_forward_pre_hook(count_forward)
        telemetry = CudaTelemetry(self.device)
        sample_size = official.model_config.get("sample_size")
        kwargs: dict[str, Any] = {
            "prompt": request.prompt,
            "negative_prompt": generation["negative_prompt"],
            "duration": request.duration_seconds,
            "steps": generation["inference_steps"],
            "cfg_scale": generation["cfg_scale"],
            "seed": request.seed,
            "batch_size": 1,
            "truncate_output_to_duration": generation["truncate_output_to_duration"],
            "duration_padding_sec": generation["duration_padding_sec"],
            "sampler_type": generation["sampler_type"],
            "disable_tqdm": generation["disable_tqdm"],
            "chunked_decode": generation["chunked_decode"],
        }
        if isinstance(sample_size, int) and sample_size > 0:
            kwargs["sample_size"] = sample_size
        try:
            with telemetry.measured() as measured:
                output = official.generate(**kwargs, callback=count_callback)
        finally:
            hook.remove()
        if counts["nfe"] <= 0 or counts["sampler_callbacks"] <= 0:
            raise RuntimeError(f"SA3 call yielded invalid measured counts: {counts}")
        waveform = self._channels_first_batch_one(output)
        save_float_wav_exclusive(
            request.output_path,
            waveform,
            int(generation["sample_rate"]),
            channels_first=True,
        )
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=int(generation["sample_rate"]),
            requested_steps=int(generation["inference_steps"]),
            actual_nfe=counts["nfe"],
            wall_seconds=float(measured["wall_seconds"]),
            peak_allocated_bytes=int(measured["peak_allocated_bytes"]),
            peak_reserved_bytes=int(measured["peak_reserved_bytes"]),
            metadata={
                "load_wall_seconds": self._load_wall_seconds,
                "sampler_callback_calls": counts["sampler_callbacks"],
                "config_sha256": self.config_sha256,
                "config_resolution": self._runtime.config_resolution.to_dict(),
                "official_api": "stable_audio_3.model.StableAudioModel.generate",
                "generation_parameters": kwargs,
            },
        )

"""License-gated, offline-only Stable Audio Open 1.0 adapter."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from backbones.contracts import (
    DEFAULT_SAO_CONFIG,
    BackboneConfigurationError,
    BackbonePreflight,
    GenerationMeasurement,
    GenerationRequest,
    load_backbone_config,
    sha256_file,
    strict_json_object,
)
from backbones.license_gate import (
    license_block_from_config,
    validate_access_receipt,
    validate_core_authorization,
    validate_runtime_authorization,
)
from backbones.runtime import CudaTelemetry
from backbones.sao_mini_smoke import validate_sao_mini_smoke_evidence
from sa3_smoke.audio import save_float_wav_exclusive


class StableAudioOpenAdapter:
    """SAO adapter that cannot reach loading without two explicit offline gate records."""

    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_SAO_CONFIG,
        evidence_dir: str | Path | None = None,
        snapshot_dir: str | Path | None = None,
        access_receipt_path: str | Path | None = None,
        runtime_authorization_path: str | Path | None = None,
        execution_scope: str = "MINI_SMOKE",
        mini_smoke_result_path: str | Path | None = None,
        mini_smoke_result_sha256: str | None = None,
        device: str = "cuda",
    ) -> None:
        self.config, self.config_sha256 = load_backbone_config(config_path)
        if self.config["logical_name"] != "stable-audio-open-1.0":
            raise BackboneConfigurationError("SAO adapter received a different model config")
        self.logical_name = self.config["logical_name"]
        self.model_id = self.config["model_id"]
        self.license_identifier = self.config["license_identifier"]
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        snapshot_env = self.config["adapter"]["local_snapshot_environment_variable"]
        snapshot_value = snapshot_dir or os.environ.get(snapshot_env)
        self.snapshot_dir = Path(snapshot_value) if snapshot_value else None
        self.access_receipt_path = Path(access_receipt_path) if access_receipt_path else None
        self.runtime_authorization_path = (
            Path(runtime_authorization_path) if runtime_authorization_path else None
        )
        if execution_scope not in {"MINI_SMOKE", "BENCHMARK_CORE"}:
            raise ValueError("SAO execution_scope must be MINI_SMOKE or BENCHMARK_CORE")
        self.execution_scope = execution_scope
        self.mini_smoke_result_path = (
            Path(mini_smoke_result_path) if mini_smoke_result_path is not None else None
        )
        self.mini_smoke_result_sha256 = mini_smoke_result_sha256
        if device != "cuda" and not (device.startswith("cuda:") and device[5:].isdigit()):
            raise ValueError("Stable Audio Open requires device='cuda' or 'cuda:N'")
        self.device = device
        self._preflight: BackbonePreflight | None = None
        self._model: Any | None = None
        self._load_wall_seconds: float | None = None
        self._weight_file_sha256: str | None = None

    def preflight(self) -> BackbonePreflight:
        """Return the adjudicated blocker or verify both later offline gate records."""

        if self._preflight is not None:
            return self._preflight
        blocker = license_block_from_config(self.config)
        if (
            self.access_receipt_path is None
            or self.runtime_authorization_path is None
            or self.snapshot_dir is None
        ):
            raise blocker
        receipt = validate_access_receipt(
            self.access_receipt_path,
            expected_model_id=self.model_id,
            expected_snapshot_dir=self.snapshot_dir,
        )
        if self.execution_scope == "MINI_SMOKE":
            authorization = validate_runtime_authorization(
                self.runtime_authorization_path,
                expected_config_sha256=self.config_sha256,
                expected_receipt_sha256=receipt["receipt_sha256"],
                expected_decision_id="D-0037",
                expected_generations=3,
            )
            status = "READY_FOR_MINI_SMOKE"
        else:
            if self.mini_smoke_result_path is None or self.mini_smoke_result_sha256 is None:
                raise BackboneConfigurationError(
                    "SAO core preflight requires a measured mini-smoke result path and SHA-256"
                )
            if sha256_file(self.mini_smoke_result_path) != self.mini_smoke_result_sha256:
                raise BackboneConfigurationError("SAO core mini-smoke result hash mismatch")
            validate_sao_mini_smoke_evidence(
                self.mini_smoke_result_path,
                expected_config_sha256=self.config_sha256,
                expected_receipt=receipt,
                expected_snapshot_dir=self.snapshot_dir,
            )
            authorization = validate_core_authorization(
                self.runtime_authorization_path,
                expected_config_sha256=self.config_sha256,
                expected_receipt_sha256=receipt["receipt_sha256"],
                expected_mini_smoke_result_sha256=self.mini_smoke_result_sha256,
            )
            status = "READY_FOR_CORE"
        self.license_identifier = receipt["license_identifier"]
        self._preflight = BackbonePreflight(
            status=status,
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={
                "receipt": receipt,
                "runtime_authorization": authorization,
                "runtime_authorization_path": str(self.runtime_authorization_path.resolve()),
                "runtime_authorization_sha256": sha256_file(self.runtime_authorization_path),
                "snapshot_dir": str(self.snapshot_dir.resolve()),
                "network_downloads_allowed": False,
            },
        )
        return self._preflight

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self.preflight()
        assert self.snapshot_dir is not None
        started = time.perf_counter()
        snapshot = self.snapshot_dir.resolve()
        config_path = snapshot / "model_config.json"
        safetensors_path = snapshot / "model.safetensors"
        checkpoint_path = snapshot / "model.ckpt"
        if not config_path.is_file():
            raise BackboneConfigurationError("SAO snapshot lacks model_config.json")
        candidates = [path for path in (safetensors_path, checkpoint_path) if path.is_file()]
        if len(candidates) != 1:
            raise BackboneConfigurationError(
                "SAO snapshot must contain exactly one of model.safetensors or model.ckpt"
            )
        try:
            from stable_audio_tools.models.factory import create_model_from_config
            from stable_audio_tools.models.utils import load_ckpt_state_dict
        except ImportError as exc:
            raise ImportError(
                "stable-audio-tools local model factory is required after the license gate clears"
            ) from exc
        model_config = strict_json_object(config_path)
        model = create_model_from_config(model_config)
        model.load_state_dict(load_ckpt_state_dict(str(candidates[0])))
        expected_sample_rate = int(self.config["generation"]["sample_rate"])
        if getattr(model, "sample_rate", None) != expected_sample_rate:
            raise BackboneConfigurationError("SAO local model sample rate differs from config")
        weight_relative = candidates[0].relative_to(snapshot).as_posix()
        verified_files = self._preflight.details["receipt"]["verified_files"]
        weight_rows = [row for row in verified_files if row["path"] == weight_relative]
        if len(weight_rows) != 1:
            raise BackboneConfigurationError("SAO weight is not uniquely bound by receipt")
        self._weight_file_sha256 = str(weight_rows[0]["sha256"])
        self._model = model.to(self.device).eval()
        self._load_wall_seconds = time.perf_counter() - started

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        """Run one official offline SAO call and retain its waveform without clobbering."""

        if os.path.lexists(request.output_path):
            raise FileExistsError(request.output_path)
        max_duration = float(self.config["mini_smoke_caps"]["max_clip_seconds"])
        if request.duration_seconds > max_duration:
            raise ValueError(f"request exceeds {max_duration}-second SAO mini-smoke cap")
        if request.duration_seconds != 30.0:
            raise ValueError("SAO v2 execution is frozen to exactly 30-second requests")
        self._ensure_loaded()
        try:
            from stable_audio_tools.inference.generation import generate_diffusion_cond
        except ImportError as exc:
            raise ImportError("stable-audio-tools generation helper is unavailable") from exc
        diffusion = getattr(self._model, "model", None)
        if diffusion is None or not hasattr(diffusion, "register_forward_hook"):
            raise RuntimeError("cannot measure SAO NFE: diffusion forward-hook surface is absent")
        nfe = {"calls": 0}

        def count_forward(_module: Any, _inputs: Any, _output: Any) -> None:
            nfe["calls"] += 1

        hook = diffusion.register_forward_hook(count_forward)
        generation = self.config["generation"]
        telemetry = CudaTelemetry(self.device)
        try:
            import torch

            with telemetry.measured() as measured:
                output = generate_diffusion_cond(
                    self._model,
                    steps=int(generation["inference_steps"]),
                    cfg_scale=float(generation["cfg_scale"]),
                    conditioning=[
                        {
                            "prompt": request.prompt,
                            "seconds_start": 0,
                            "seconds_total": request.duration_seconds,
                        }
                    ],
                    batch_size=1,
                    sample_size=1_323_000,
                    sample_rate=int(generation["sample_rate"]),
                    seed=request.seed,
                    device=self.device,
                    adapt_duration_to_conditioning=False,
                    sampler_type=generation["sampler_type"],
                )
        finally:
            hook.remove()
        if nfe["calls"] <= 0:
            raise RuntimeError("SAO call produced no measured diffusion forwards")
        waveform = output.audio if hasattr(output, "audio") else output
        if hasattr(waveform, "detach"):
            waveform = waveform.detach().to("cpu", dtype=torch.float32).numpy()
        array = np.asarray(waveform, dtype=np.float32)
        while array.ndim > 2:
            if array.shape[0] != 1:
                raise RuntimeError(f"SAO mini-smoke expected batch one, got shape {array.shape}")
            array = array[0]
        if array.ndim != 2:
            raise RuntimeError(f"SAO output must be channels x frames, got shape {array.shape}")
        save_float_wav_exclusive(
            request.output_path,
            array,
            int(generation["sample_rate"]),
            channels_first=True,
        )
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
                "execution_scope": self.execution_scope,
                "requested_sample_size": 1_323_000,
                "weight_file_sha256": self._weight_file_sha256,
                "resolved_provider_revision": self._preflight.details["receipt"][
                    "resolved_provider_revision"
                ],
                "sampler_type": generation["sampler_type"],
            },
        )

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
)
from backbones.license_gate import (
    license_block_from_config,
    validate_access_receipt,
    validate_runtime_authorization,
)
from backbones.runtime import CudaTelemetry
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
        if device != "cuda" and not (device.startswith("cuda:") and device[5:].isdigit()):
            raise ValueError("Stable Audio Open requires device='cuda' or 'cuda:N'")
        self.device = device
        self._preflight: BackbonePreflight | None = None
        self._model: Any | None = None
        self._load_wall_seconds: float | None = None

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
        authorization = validate_runtime_authorization(
            self.runtime_authorization_path,
            expected_config_sha256=self.config_sha256,
            expected_receipt_sha256=receipt["receipt_sha256"],
        )
        self.license_identifier = receipt["license_identifier"]
        self._preflight = BackbonePreflight(
            status="READY_FOR_MINI_SMOKE",
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={
                "receipt": receipt,
                "runtime_authorization": authorization,
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
        try:
            from stable_audio_tools import get_pretrained_model
        except ImportError as exc:
            raise ImportError(
                "stable-audio-tools is required after the license gate clears"
            ) from exc
        model, _model_config = get_pretrained_model(str(self.snapshot_dir.resolve()))
        self._model = model.to(self.device).eval()
        self._load_wall_seconds = time.perf_counter() - started

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        """Run one official offline SAO call and retain its waveform without clobbering."""

        if os.path.lexists(request.output_path):
            raise FileExistsError(request.output_path)
        max_duration = float(self.config["mini_smoke_caps"]["max_clip_seconds"])
        if request.duration_seconds > max_duration:
            raise ValueError(f"request exceeds {max_duration}-second SAO mini-smoke cap")
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

            generator = torch.Generator(device=self.device).manual_seed(request.seed)
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
                    generator=generator,
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
                "resolved_provider_revision": self._preflight.details["receipt"][
                    "resolved_provider_revision"
                ],
                "sampler_type": generation["sampler_type"],
            },
        )

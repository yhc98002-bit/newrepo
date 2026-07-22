"""Production bridge from frozen B2 adapters to the ordinary core worker."""

from __future__ import annotations

import importlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backbones.contracts import GenerationMeasurement, GenerationRequest
from benchmark_core.artifacts import StagedGeneration
from benchmark_core.config import ModelExecutionConfig, strict_json


class BackboneCoreBridge:
    """Harmonize the B2 adapter contract without enabling formal state calls."""

    def __init__(
        self,
        backbone: Any,
        *,
        expected_sample_rate: int,
        expected_channels: int,
    ) -> None:
        self.backbone = backbone
        self.model_id = str(backbone.model_id)
        self.expected_sample_rate = expected_sample_rate
        self.expected_channels = expected_channels
        self._loaded = False

    def preflight(self) -> Mapping[str, Any]:
        result = self.backbone.preflight()
        status = getattr(result, "status", None)
        model_id = getattr(result, "model_id", None)
        expected_status = (
            "READY_FOR_CORE"
            if self.model_id == "stabilityai/stable-audio-open-1.0"
            else "READY_FOR_MINI_SMOKE"
        )
        if status != expected_status or model_id != self.model_id:
            raise RuntimeError("B2 adapter preflight is not ready for ordinary core generation")
        return {
            "adapter_config_sha256": getattr(result, "config_sha256", None),
            "details": dict(getattr(result, "details", {})),
            "model_id": model_id,
            "source_status": status,
            "status": "READY",
        }

    def load(self) -> Mapping[str, Any]:
        if self._loaded:
            raise RuntimeError("core bridge load may occur only once per resident worker")
        loader = getattr(self.backbone, "_ensure_loaded", None)
        if not callable(loader):
            raise RuntimeError("B2 adapter lacks the verified resident-load boundary")
        started = time.perf_counter()
        loader()
        observed = time.perf_counter() - started
        self._loaded = True
        record = {
            "bridge_load_wall_seconds": observed,
            "model_id": self.model_id,
            "source_adapter_load_wall_seconds": getattr(self.backbone, "_load_wall_seconds", None),
        }
        json.dumps(record, allow_nan=False, sort_keys=True)
        return record

    def generate(
        self,
        request: Mapping[str, Any],
        staging_dir: Path,
        state_contracts: Sequence[Mapping[str, Any]],
    ) -> StagedGeneration:
        if not self._loaded:
            raise RuntimeError("adapter must be resident before a core call")
        if state_contracts:
            raise RuntimeError(
                "ordinary core bridge refuses formal state contracts; use the separately "
                "authorized state queue"
            )
        destination = staging_dir / "waveform.wav"
        adapter_request = GenerationRequest(
            prompt_id=str(request["prompt_id"]),
            prompt=str(request["prompt"]),
            seed_id=f"root-{int(request['root_index']):02d}",
            seed=int(request["seed"]),
            duration_seconds=float(request["duration_seconds"]),
            output_path=destination,
            lyrics="",
        )
        measurement = self.backbone.generate(adapter_request)
        if not isinstance(measurement, GenerationMeasurement):
            raise TypeError("B2 adapter did not return GenerationMeasurement")
        if measurement.output_path.resolve() != destination.resolve():
            raise RuntimeError("B2 adapter returned a different output path")
        if measurement.sample_rate != self.expected_sample_rate:
            raise RuntimeError("B2 adapter output sample rate drifted from core config")
        if measurement.peak_allocated_bytes is None or measurement.peak_reserved_bytes is None:
            raise RuntimeError("B2 adapter omitted required CUDA peak telemetry")
        return StagedGeneration(
            wav_path=measurement.output_path,
            actual_nfe=measurement.actual_nfe,
            synchronized_wall_seconds=measurement.wall_seconds,
            peak_allocated_bytes=measurement.peak_allocated_bytes,
            peak_reserved_bytes=measurement.peak_reserved_bytes,
            sample_rate=measurement.sample_rate,
            channels=self.expected_channels,
            provenance={
                "adapter_metadata": dict(measurement.metadata),
                "requested_steps": measurement.requested_steps,
            },
        )

    def close(self) -> None:
        closer = getattr(self.backbone, "close", None)
        if callable(closer):
            closer()


def build_production_bridge(
    model: ModelExecutionConfig,
    *,
    run_dir: Path,
) -> BackboneCoreBridge:
    """Instantiate only the exact class named by the content-pinned adapter config."""

    if (
        model.adapter_config_path is None
        or model.expected_sample_rate is None
        or model.expected_channels is None
    ):
        raise ValueError("READY model lacks adapter/audio configuration")
    config = strict_json(model.adapter_config_path)
    adapter = config.get("adapter")
    if not isinstance(adapter, dict):
        raise ValueError("adapter config lacks adapter object")
    class_name = adapter.get("class")
    if not isinstance(class_name, str) or class_name.count(".") < 1:
        raise ValueError("adapter class identity is invalid")
    allowed = {
        "backbones.stable_audio_3.StableAudio3MediumBaseAdapter",
        "backbones.stable_audio_open.StableAudioOpenAdapter",
        "backbones.ace_step_v1.AceStepV1Adapter",
    }
    if class_name not in allowed:
        raise ValueError(f"ordinary core bridge refuses unregistered adapter {class_name}")
    module_name, attribute = class_name.rsplit(".", 1)
    adapter_class = getattr(importlib.import_module(module_name), attribute)
    kwargs: dict[str, Any] = {
        "config_path": model.adapter_config_path,
        "device": "cuda:0",
    }
    if attribute == "StableAudio3MediumBaseAdapter":
        kwargs["config_resolution_dir"] = run_dir / "evidence" / model.slug / "config-resolution"
    elif attribute == "AceStepV1Adapter":
        kwargs["evidence_dir"] = run_dir / "evidence" / model.slug
    elif attribute == "StableAudioOpenAdapter":
        if model.sao_runtime is None:
            raise ValueError("SAO core bridge lacks its receipt/authorization binding")
        kwargs.update(
            {
                "evidence_dir": run_dir / "evidence" / model.slug,
                "snapshot_dir": model.sao_runtime.snapshot_dir,
                "access_receipt_path": model.sao_runtime.access_receipt_path,
                "runtime_authorization_path": model.sao_runtime.core_authorization_path,
                "execution_scope": "BENCHMARK_CORE",
                "mini_smoke_result_path": model.sao_runtime.mini_smoke_result_path,
                "mini_smoke_result_sha256": model.sao_runtime.mini_smoke_result_sha256,
            }
        )
    backbone = adapter_class(**kwargs)
    return BackboneCoreBridge(
        backbone,
        expected_sample_rate=model.expected_sample_rate,
        expected_channels=model.expected_channels,
    )

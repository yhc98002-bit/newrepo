"""Production SA3 prefix/export and separate-process resume backend."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from backbones.contracts import BackbonePreflight
from backbones.runtime import CudaTelemetry
from backbones.stable_audio_3 import StableAudio3MediumBaseAdapter
from benchmark_core.placement import PlacementUnavailable
from sa3_smoke.audio import save_float_wav_exclusive
from sa3_smoke.latent import (
    CheckpointArtifact,
    ResumeRuntime,
    load_euler_checkpoint,
    run_euler_transitions,
    run_resume_in_subprocess,
)
from state_capture.sa3_artifacts import (
    StagedCheckpointPreview,
    StagedPrefixGroup,
    StagedResume,
)
from state_capture.sa3_contract import SA3_MODEL_ID, SA3StateCaptureConfig, sha256_file

CHILD_FACTORY = "state_capture.sa3_engine:sa3_state_resume_runtime_factory"


def require_post_load_cuda_reserve(
    minimum_free_vram_bytes: int,
    *,
    device: str = "cuda:0",
    memory_info: Callable[[], tuple[int, int]] | None = None,
) -> dict[str, int]:
    """Synchronize and require real free memory after load, before inference."""

    if (
        isinstance(minimum_free_vram_bytes, bool)
        or not isinstance(minimum_free_vram_bytes, int)
        or minimum_free_vram_bytes <= 0
    ):
        raise ValueError("post-load reserve must be a positive integer")
    if memory_info is None:
        import torch

        torch.cuda.synchronize(device)

        def reader() -> tuple[int, int]:
            return torch.cuda.mem_get_info(device)

    else:
        reader = memory_info
    free_bytes, total_bytes = reader()
    if (
        isinstance(free_bytes, bool)
        or isinstance(total_bytes, bool)
        or not isinstance(free_bytes, int)
        or not isinstance(total_bytes, int)
        or free_bytes < 0
        or total_bytes <= 0
        or free_bytes > total_bytes
    ):
        raise RuntimeError("CUDA post-load memory observation is invalid")
    if free_bytes < minimum_free_vram_bytes:
        raise PlacementUnavailable(
            f"post-load CUDA free memory {free_bytes} is below required "
            f"{minimum_free_vram_bytes}; inference was not started"
        )
    return {
        "free_vram_bytes": free_bytes,
        "minimum_free_vram_bytes": minimum_free_vram_bytes,
        "total_vram_bytes": total_bytes,
    }


def _json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _generation_kwargs(
    row: Mapping[str, Any], generation: Mapping[str, Any], sample_size: int | None
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "prompt": row["prompt"],
        "negative_prompt": generation["negative_prompt"],
        "duration": float(row["duration_seconds"]),
        "steps": int(generation["inference_steps"]),
        "cfg_scale": float(generation["cfg_scale"]),
        "seed": int(row["seed"]),
        "batch_size": 1,
        "truncate_output_to_duration": bool(generation["truncate_output_to_duration"]),
        "duration_padding_sec": float(generation["duration_padding_sec"]),
        "sampler_type": generation["sampler_type"],
        "disable_tqdm": True,
        "chunked_decode": bool(generation["chunked_decode"]),
    }
    if sample_size is not None:
        kwargs["sample_size"] = sample_size
    return kwargs


def _conditioning_identity(kwargs: Mapping[str, Any]) -> str:
    return _json_sha256(
        {
            "official_api": "stable_audio_3.model.StableAudioModel.generate",
            "prompt": kwargs["prompt"],
            "negative_prompt": kwargs["negative_prompt"],
            "duration_seconds": kwargs["duration"],
            "steps": kwargs["steps"],
            "cfg_scale": kwargs["cfg_scale"],
            "seed": kwargs["seed"],
            "batch_size": 1,
            "sample_size": kwargs.get("sample_size"),
            "sampler_type": kwargs["sampler_type"],
            "duration_padding_seconds": kwargs["duration_padding_sec"],
            "truncate_output_to_duration": kwargs["truncate_output_to_duration"],
            "chunked_decode": kwargs["chunked_decode"],
        }
    )


def _channels_first(output: Any) -> np.ndarray:
    if hasattr(output, "detach"):
        output = output.detach().float().cpu().numpy()
    array = np.asarray(output, dtype=np.float32)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim != 3 or array.shape[0] != 1 or array.shape[1] != 2:
        raise RuntimeError(f"SA3 state decode expected (1,2,T), got {array.shape}")
    return np.ascontiguousarray(array[0])


class _CheckpointSampler:
    def __init__(
        self,
        *,
        checkpoint_dir: Path,
        prefix: str,
        completed_steps: tuple[int, ...],
        run_id: str,
        conditioning_sha256: str,
        config_sha256: str,
    ) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.prefix = prefix
        self.completed_steps = completed_steps
        self.run_id = run_id
        self.conditioning_sha256 = conditioning_sha256
        self.config_sha256 = config_sha256
        self.last_result: Any | None = None

    def __call__(
        self,
        model: Any,
        x: Any,
        sigmas: Any,
        callback: Any = None,
        disable_tqdm: bool = False,
        **extra_args: Any,
    ) -> Any:
        del disable_tqdm
        self.last_result = run_euler_transitions(
            model,
            x,
            sigmas,
            model_kwargs=extra_args,
            callback=callback,
            checkpoint_dir=self.checkpoint_dir,
            checkpoint_prefix=self.prefix,
            checkpoint_completed_steps=self.completed_steps,
            checkpoint_run_id=self.run_id,
            conditioning_sha256=self.conditioning_sha256,
            config_sha256=self.config_sha256,
            checkpoint_run_metadata={"lane": "sa3-state-capture-v2"},
        )
        return self.last_result.latent


def _offload_and_release(official: Any) -> dict[str, Any]:
    import torch

    official.model.to("cpu")
    official.device = "cpu"
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()
    remaining = sum(
        tensor.is_cuda
        for tensor in (*tuple(official.model.parameters()), *tuple(official.model.buffers()))
    )
    if remaining:
        raise RuntimeError("parent SA3 model retains CUDA tensors before child resumes")
    return {
        "parent_model_offloaded_before_children": True,
        "remaining_parent_cuda_tensors": remaining,
    }


class SA3StateEngine:
    """Each group mirrors D-0020: parent reference, offload, three child resumes."""

    model_id = SA3_MODEL_ID

    def __init__(self, config: SA3StateCaptureConfig, *, run_dir: Path) -> None:
        self.config = config
        self.run_dir = run_dir.resolve()
        adapter_path = config.repo_root / "configs/backbones/stable_audio_3_medium_base.json"
        self.adapter_config_path = adapter_path.resolve(strict=True)
        self._probe_adapter = StableAudio3MediumBaseAdapter(
            config_path=self.adapter_config_path,
            config_resolution_dir=self.run_dir / "unused-preflight-resolution",
            device="cuda:0",
        )
        self._preflight: BackbonePreflight | None = None

    def preflight(self) -> Mapping[str, Any]:
        result = self._probe_adapter.preflight()
        if result.status != "READY_FOR_MINI_SMOKE" or result.model_id != SA3_MODEL_ID:
            raise RuntimeError("SA3 state engine preflight is not READY")
        self._preflight = result
        return {
            "adapter_config_sha256": result.config_sha256,
            "model_id": result.model_id,
            "source_status": result.status,
            "state_capability": result.details.get("state_capability"),
            "status": "READY",
        }

    def load(self) -> Mapping[str, Any]:
        if self._preflight is None:
            raise RuntimeError("state engine must preflight before load boundary")
        # The D-0020-matched engine loads per prefix/child process.  This
        # resident boundary intentionally allocates no CUDA memory.
        return {"load_wall_seconds": 0.0, "mode": "D0020_GROUP_PROCESS_LIFECYCLE"}

    def capture_group(
        self,
        group: Mapping[str, Any],
        units: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> StagedPrefixGroup:
        if self._preflight is None:
            raise RuntimeError("state engine lacks verified preflight")
        import torch
        from stable_audio_3.inference import sampling as sampling_module

        staging_dir.mkdir(parents=True, exist_ok=False)
        adapter = StableAudio3MediumBaseAdapter(
            config_path=self.adapter_config_path,
            snapshot_dir=self._probe_adapter.snapshot_dir,
            config_resolution_dir=staging_dir / "parent-config-resolution",
            device="cuda:0",
        )
        adapter._preflight = self._preflight  # exact same config/snapshot, already content-verified
        started = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        adapter._ensure_loaded()
        post_load_headroom = require_post_load_cuda_reserve(
            self.config.placement.post_load_reserve_bytes
        )
        runtime = adapter._runtime
        if runtime is None:
            raise RuntimeError("SA3 parent runtime failed to load")
        official = runtime.stable_audio_model
        sample_size_value = official.model_config.get("sample_size")
        sample_size = sample_size_value if isinstance(sample_size_value, int) else None
        kwargs = _generation_kwargs(group, adapter.config["generation"], sample_size)
        if kwargs["steps"] != self.config.transformer_budget_nfe:
            raise RuntimeError("SA3 adapter transformer budget drift")
        conditioning_sha = _conditioning_identity(kwargs)
        sampler = _CheckpointSampler(
            checkpoint_dir=staging_dir / "checkpoints",
            prefix="root",
            completed_steps=self.config.checkpoint_completed_steps,
            run_id=str(group["group_request_sha256"]),
            conditioning_sha256=conditioning_sha,
            config_sha256=self.config.source_sha256,
        )
        counts = {"nfe": 0}

        def count_forward(_module: Any, _inputs: Any) -> None:
            counts["nfe"] += 1

        hook = official.dit.register_forward_pre_hook(count_forward)
        try:
            with patch.object(sampling_module, "sample_discrete_euler", sampler):
                reference_output = official.generate(**kwargs)
        finally:
            hook.remove()
        if sampler.last_result is None or counts["nfe"] != self.config.transformer_budget_nfe:
            raise RuntimeError("SA3 prefix sampler did not execute exact frozen NFE")
        reference_path = staging_dir / "reference-terminal.wav"
        save_float_wav_exclusive(
            reference_path,
            _channels_first(reference_output),
            int(adapter.config["generation"]["sample_rate"]),
            channels_first=True,
        )
        checkpoint_by_step: dict[int, CheckpointArtifact] = {
            artifact.completed_steps: artifact for artifact in sampler.last_result.checkpoints
        }
        checkpoint_previews: list[StagedCheckpointPreview] = []
        pretransform = official.model.pretransform
        for unit in units:
            step = int(unit["checkpoint_completed_steps"])
            artifact = checkpoint_by_step.get(step)
            if artifact is None:
                raise RuntimeError(f"SA3 prefix omitted checkpoint step {step}")
            state = load_euler_checkpoint(
                artifact.path,
                expected_conditioning_sha256=conditioning_sha,
                expected_config_sha256=self.config.source_sha256,
            )
            latent = state.latent.to(device="cuda:0", dtype=next(pretransform.parameters()).dtype)
            preview = pretransform.decode(
                latent, chunked=bool(adapter.config["generation"]["chunked_decode"])
            )
            preview = preview.to(torch.float32).clamp(-1, 1)
            frames = round(
                float(unit["duration_seconds"]) * int(adapter.config["generation"]["sample_rate"])
            )
            preview = preview[..., :frames]
            preview_path = staging_dir / f"preview-step-{step:03d}.wav"
            save_float_wav_exclusive(
                preview_path,
                _channels_first(preview),
                int(adapter.config["generation"]["sample_rate"]),
                channels_first=True,
            )
            checkpoint_previews.append(
                StagedCheckpointPreview(
                    lane_request_sha256=str(unit["lane_request_sha256"]),
                    checkpoint_path=artifact.path,
                    checkpoint_state_metadata_path=artifact.state_metadata_path,
                    preview_path=preview_path,
                )
            )
            del latent, preview
        del reference_output
        sampler.last_result = None
        release = _offload_and_release(official)
        elapsed = time.perf_counter() - started
        peak_allocated = int(torch.cuda.max_memory_allocated())
        peak_reserved = int(torch.cuda.max_memory_reserved())
        del adapter, runtime, official, sampler
        torch.cuda.empty_cache()
        gc.collect()
        return StagedPrefixGroup(
            reference_terminal_path=reference_path,
            checkpoint_previews=tuple(checkpoint_previews),
            actual_nfe=counts["nfe"],
            synchronized_gpu_seconds=elapsed,
            peak_allocated_bytes=peak_allocated,
            peak_reserved_bytes=peak_reserved,
            conditioning_sha256=conditioning_sha,
            provenance={
                "config_resolution": self._preflight.details.get("committed_provenance"),
                "generation_parameters": kwargs,
                "parent_release": release,
                "post_load_headroom": post_load_headroom,
                "process_id": os.getpid(),
            },
        )

    def resume(
        self,
        unit: Mapping[str, Any],
        checkpoint_path: Path,
        staging_dir: Path,
    ) -> StagedResume:
        if self._preflight is None:
            raise RuntimeError("state engine lacks verified preflight")
        staging_dir.mkdir(parents=True, exist_ok=False)
        adapter_config = json.loads(self.adapter_config_path.read_text(encoding="utf-8"))
        sample_size_value = json.loads(
            (self._probe_adapter.snapshot_dir / "model_config.json").read_text(encoding="utf-8")
        ).get("sample_size")
        sample_size = sample_size_value if isinstance(sample_size_value, int) else None
        kwargs = _generation_kwargs(unit, adapter_config["generation"], sample_size)
        conditioning_sha = _conditioning_identity(kwargs)
        result_path = staging_dir / "resume-result.pt"
        output_path = staging_dir / "resumed-terminal.wav"
        child_env = os.environ.copy()
        child_env.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            }
        )
        launched = run_resume_in_subprocess(
            request_path=staging_dir / "resume-request.json",
            checkpoint_path=checkpoint_path,
            result_path=result_path,
            runtime_factory=CHILD_FACTORY,
            conditioning_sha256=conditioning_sha,
            config_sha256=self.config.source_sha256,
            runtime_kwargs={
                "adapter_config_path": str(self.adapter_config_path),
                "adapter_config_sha256": sha256_file(self.adapter_config_path),
                "config_evidence_dir": str((staging_dir / "child-config-resolution").resolve()),
                "generation_kwargs": kwargs,
                "lane_config_sha256": self.config.source_sha256,
                "output_wav_path": str(output_path.resolve()),
                "post_load_reserve_bytes": self.config.placement.post_load_reserve_bytes,
                "parent_preflight": {
                    "config_sha256": self._preflight.config_sha256,
                    "details": dict(self._preflight.details),
                    "model_id": self._preflight.model_id,
                    "status": self._preflight.status,
                },
                "snapshot_dir": str(self._probe_adapter.snapshot_dir.resolve()),
            },
            request_metadata={
                "checkpoint_completed_steps": unit["checkpoint_completed_steps"],
                "lane_request_sha256": unit["lane_request_sha256"],
            },
            python_executable=sys.executable,
            timeout_seconds=900,
            cwd=self.config.repo_root,
            env=child_env,
        )
        metadata = launched.artifact.metadata
        finalize = metadata.get("finalize_metadata")
        if not isinstance(finalize, Mapping):
            raise RuntimeError("SA3 resume child omitted finalize telemetry")
        return StagedResume(
            resumed_terminal_path=output_path,
            actual_nfe=int(metadata["forward_calls"]),
            synchronized_gpu_seconds=float(finalize["synchronized_gpu_seconds"]),
            peak_allocated_bytes=int(finalize["peak_allocated_bytes"]),
            peak_reserved_bytes=int(finalize["peak_reserved_bytes"]),
            child_pid=int(metadata["child_pid"]),
            provenance={
                "child_execution_mode": metadata["execution_mode"],
                "child_result_sha256": launched.artifact.artifact_sha256,
                "fresh_initial_latent_dtype": metadata.get("fresh_initial_latent_dtype"),
                "post_load_headroom": finalize["post_load_headroom"],
                "runtime_schedule_validated": metadata.get("runtime_schedule_validated"),
                "resume_latent_dtype_preserved": metadata.get("resume_latent_dtype_preserved"),
            },
        )

    def close(self) -> None:
        self._probe_adapter._runtime = None


def sa3_state_resume_runtime_factory(request: Mapping[str, Any], checkpoint: Any) -> ResumeRuntime:
    """Fresh child factory that rebuilds the official path from local content only."""

    del checkpoint
    kwargs = request.get("runtime_kwargs")
    if not isinstance(kwargs, Mapping):
        raise ValueError("SA3 state resume runtime_kwargs are absent")
    config_path = Path(str(kwargs["adapter_config_path"])).resolve(strict=True)
    if sha256_file(config_path) != kwargs["adapter_config_sha256"]:
        raise ValueError("SA3 child adapter config hash drift")
    if request.get("config_sha256") != kwargs["lane_config_sha256"]:
        raise ValueError("SA3 child lane config identity drift")
    preflight_record = kwargs.get("parent_preflight")
    if not isinstance(preflight_record, Mapping):
        raise ValueError("SA3 child parent preflight binding is absent")
    adapter = StableAudio3MediumBaseAdapter(
        config_path=config_path,
        snapshot_dir=kwargs["snapshot_dir"],
        config_resolution_dir=kwargs["config_evidence_dir"],
        device="cuda:0",
    )
    adapter._preflight = BackbonePreflight(
        status=str(preflight_record["status"]),
        model_id=str(preflight_record["model_id"]),
        config_sha256=str(preflight_record["config_sha256"]),
        details=dict(preflight_record["details"]),
    )
    adapter._ensure_loaded()
    post_load_headroom = require_post_load_cuda_reserve(int(kwargs["post_load_reserve_bytes"]))
    runtime = adapter._runtime
    if runtime is None:
        raise RuntimeError("SA3 child runtime failed to load")
    official = runtime.stable_audio_model
    generation_kwargs = dict(kwargs["generation_kwargs"])
    conditioning_sha = _conditioning_identity(generation_kwargs)
    telemetry_result: dict[str, Any] = {}

    def invoke_generate(resume_sampler: Any) -> Any:
        from stable_audio_3.inference import sampling as sampling_module

        counts = {"nfe": 0}

        def count_forward(_module: Any, _inputs: Any) -> None:
            counts["nfe"] += 1

        hook = official.dit.register_forward_pre_hook(count_forward)
        telemetry = CudaTelemetry("cuda:0")
        try:
            with (
                telemetry.measured() as measured,
                patch.object(sampling_module, "sample_discrete_euler", resume_sampler),
            ):
                output = official.generate(**generation_kwargs)
        finally:
            hook.remove()
        telemetry_result.update(measured)
        telemetry_result["actual_nfe"] = counts["nfe"]
        return output

    def finalize(
        _latent: Any,
        generated_output: Any,
        _checkpoint: Any,
        _request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        output_path = Path(str(kwargs["output_wav_path"]))
        save_float_wav_exclusive(
            output_path,
            _channels_first(generated_output),
            int(adapter.config["generation"]["sample_rate"]),
            channels_first=True,
        )
        return {
            "actual_nfe": telemetry_result["actual_nfe"],
            "output_wav_path": str(output_path.resolve()),
            "output_wav_sha256": sha256_file(output_path),
            "peak_allocated_bytes": int(telemetry_result["peak_allocated_bytes"]),
            "peak_reserved_bytes": int(telemetry_result["peak_reserved_bytes"]),
            "post_load_headroom": post_load_headroom,
            "synchronized_gpu_seconds": float(telemetry_result["wall_seconds"]),
        }

    return ResumeRuntime(
        conditioning_sha256=conditioning_sha,
        config_sha256=str(kwargs["lane_config_sha256"]),
        invoke_generate=invoke_generate,
        finalize=finalize,
    )


__all__ = ["SA3StateEngine", "sa3_state_resume_runtime_factory"]

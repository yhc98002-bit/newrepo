"""High-level Stable Audio 3 latent checkpoint/reload smoke E.

The reference and every resumed waveform use the official
``StableAudioModel.generate`` path.  Only the pinned upstream Euler sampler is
injected: the reference injection exports post-transition state, while each
fresh child process injection validates the rebuilt full schedule and resumes
from that state.
"""

from __future__ import annotations

import gc
import importlib
import json
import math
import os
import sys
import traceback
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import numpy as np

from sa3_smoke.artifacts import (
    sha256_file,
    validate_adjacent_provenance,
    write_adjacent_provenance,
)
from sa3_smoke.audio import (
    EXPECTED_CHANNELS,
    EXPECTED_SAMPLE_RATE,
    audio_sanity,
    load_float_wav,
    save_float_wav_exclusive,
)
from sa3_smoke.budget import finalize_generated_audio, remaining_budget_seconds
from sa3_smoke.latent import (
    CHECKPOINT_COMPLETED_STEPS,
    CheckpointArtifact,
    CheckpointingEulerSampler,
    ResumeRuntime,
    json_sha256,
    run_resume_in_subprocess,
)
from sa3_smoke.model_runtime import (
    DEFAULT_REQUIRED_T5_FILES,
    ModelRuntime,
    ResolvedModelConfig,
    resolve_local_model_config,
)
from sa3_smoke.smokes import ProvenanceContext

SmokeEStatus = Literal["PASS", "FAIL"]

SMOKE_E_SEED = 73_193_007
SMOKE_E_STEPS = 50
SMOKE_E_DURATION_SECONDS = 30.0
SMOKE_E_CFG_SCALE = 7.0
SMOKE_E_SAMPLER = "euler"
SMOKE_E_DURATION_PADDING_SECONDS = 6.0
SMOKE_E_CHUNKED_DECODE = True
SMOKE_E_MAX_ABS_TOLERANCE = 1e-5
SMOKE_E_MIN_SNR_DB = 80.0
DEFAULT_CHILD_MODEL_LOADER = "sa3_smoke.model_runtime:load_local_model"
SMOKE_E_CHILD_FACTORY = "sa3_smoke.smoke_e:smoke_e_child_runtime_factory"


def _bounded_child_timeout(requested_seconds: float | None) -> float | None:
    """Reject a new child after the cap without interrupting an atomic subcase."""

    remaining = remaining_budget_seconds()
    if remaining is not None and remaining <= 0.0:
        raise RuntimeError("foundation GPU deadline reached before Smoke E child launch")
    # The original D-0013 run preserved atomic subcases. D-0019 instead binds a
    # strict outer cap, so its explicit child timeout is also clipped to the
    # claim-validated remaining residency allowance.
    if requested_seconds is None:
        return None
    if remaining is None:
        return requested_seconds
    return max(0.001, min(float(requested_seconds), remaining))


@dataclass(frozen=True)
class SmokeEResult:
    """Strict-JSON-compatible terminal result for smoke E."""

    smoke: str
    status: SmokeEStatus
    started_at_utc: str
    ended_at_utc: str
    parameters: Mapping[str, Any]
    checks: Mapping[str, Any]
    metrics: Mapping[str, Any]
    artifacts: Mapping[str, Any]
    error: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        json.dumps(result, allow_nan=False)
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_object(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid frozen JSON configuration {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"frozen configuration root must be an object: {source}")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _frozen_parameters(config: Mapping[str, Any]) -> dict[str, Any]:
    """Extract smoke E parameters and reject any drift from protocol v1."""

    try:
        sampling = config["sampling"]
        smoke_e = config["smokes"]["e"]
        audio = config["audio"]
    except (KeyError, TypeError) as exc:
        raise ValueError("frozen config is missing sampling/smokes.e/audio") from exc
    if not all(isinstance(value, Mapping) for value in (sampling, smoke_e, audio)):
        raise ValueError("sampling, smokes.e, and audio must be objects")

    prompt = sampling.get("prompt")
    negative_prompt = sampling.get("negative_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("frozen sampling.prompt must be a non-empty string")
    if not isinstance(negative_prompt, str) or not negative_prompt.strip():
        raise ValueError("frozen sampling.negative_prompt must be a non-empty string")

    parameters = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "duration_seconds": _number(sampling.get("duration_seconds"), "duration_seconds"),
        "steps": sampling.get("steps"),
        "cfg_scale": _number(sampling.get("cfg_scale"), "cfg_scale"),
        "sampler_type": sampling.get("sampler_type"),
        "duration_padding_seconds": _number(
            sampling.get("duration_padding_sec"), "duration_padding_sec"
        ),
        "chunked_decode": sampling.get("chunked_decode"),
        "seed": smoke_e.get("seed"),
        "seed_id": smoke_e.get("seed_id"),
        "checkpoint_completed_steps": smoke_e.get("checkpoint_completed_steps"),
        "waveform_max_abs_tolerance": _number(
            smoke_e.get("waveform_max_abs_tolerance"),
            "waveform_max_abs_tolerance",
        ),
        "waveform_min_snr_db": _number(smoke_e.get("waveform_min_snr_db"), "waveform_min_snr_db"),
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
    }
    expected = {
        "duration_seconds": SMOKE_E_DURATION_SECONDS,
        "steps": SMOKE_E_STEPS,
        "cfg_scale": SMOKE_E_CFG_SCALE,
        "sampler_type": SMOKE_E_SAMPLER,
        "duration_padding_seconds": SMOKE_E_DURATION_PADDING_SECONDS,
        "chunked_decode": SMOKE_E_CHUNKED_DECODE,
        "seed": SMOKE_E_SEED,
        "checkpoint_completed_steps": list(CHECKPOINT_COMPLETED_STEPS),
        "waveform_max_abs_tolerance": SMOKE_E_MAX_ABS_TOLERANCE,
        "waveform_min_snr_db": SMOKE_E_MIN_SNR_DB,
        "sample_rate": EXPECTED_SAMPLE_RATE,
        "channels": EXPECTED_CHANNELS,
    }
    mismatches = {
        key: {"expected": expected_value, "observed": parameters.get(key)}
        for key, expected_value in expected.items()
        if parameters.get(key) != expected_value
    }
    if parameters["seed_id"] != "S-0007":
        mismatches["seed_id"] = {
            "expected": "S-0007",
            "observed": parameters["seed_id"],
        }
    if mismatches:
        raise ValueError(f"frozen smoke E configuration drift: {mismatches}")
    return parameters


def _normalize_provenance(
    value: ProvenanceContext | Mapping[str, Any],
) -> ProvenanceContext:
    if isinstance(value, ProvenanceContext):
        return value
    try:
        raw_sources = value["source_ids"]
        if isinstance(raw_sources, (str, bytes)):
            raise ValueError("source_ids must be a sequence")
        return ProvenanceContext(
            creating_command=str(value["creating_command"]),
            run_id=str(value["run_id"]),
            source_ids=tuple(raw_sources),
            model_revision=str(value["model_revision"]),
            license_identifier=str(value["license_identifier"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid provenance context") from exc


def _provenance_dict(context: ProvenanceContext) -> dict[str, Any]:
    return {
        "creating_command": context.creating_command,
        "run_id": context.run_id,
        "source_ids": list(context.source_ids),
        "model_revision": context.model_revision,
        "license_identifier": context.license_identifier,
    }


def _artifact_source_id(path: str | os.PathLike[str]) -> str:
    artifact = Path(path).resolve()
    return f"{artifact}#sha256={sha256_file(artifact)}"


def _write_provenance(
    artifact: str | os.PathLike[str],
    *,
    label: str,
    context: ProvenanceContext,
    transformation: str,
    source_ids: Sequence[str] | None = None,
) -> Path:
    return write_adjacent_provenance(
        artifact,
        {
            "label": label,
            "created_at_utc": _utc_now(),
            "creating_command": context.creating_command,
            "run_id": context.run_id,
            "source_ids": list(source_ids or context.source_ids),
            "model_revision": context.model_revision,
            "license_identifier": context.license_identifier,
            "transformation": transformation,
        },
    )


def _official_model(model: Any) -> Any:
    official = getattr(model, "stable_audio_model", model)
    if not callable(getattr(official, "generate", None)):
        raise TypeError("smoke E requires a ModelRuntime/StableAudioModel with generate()")
    return official


def _sample_size(official: Any) -> int | None:
    config = getattr(official, "model_config", None)
    if isinstance(config, Mapping):
        value = config.get("sample_size")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _generation_identity(parameters: Mapping[str, Any], sample_size: int | None) -> str:
    return json_sha256(
        {
            "official_api": "stable_audio_3.model.StableAudioModel.generate",
            "prompt": parameters["prompt"],
            "negative_prompt": parameters["negative_prompt"],
            "duration_seconds": parameters["duration_seconds"],
            "steps": parameters["steps"],
            "cfg_scale": parameters["cfg_scale"],
            "seed": parameters["seed"],
            "batch_size": 1,
            "sample_size": sample_size,
            "sampler_type": parameters["sampler_type"],
            "duration_padding_seconds": parameters["duration_padding_seconds"],
            "truncate_output_to_duration": True,
            "chunked_decode": parameters["chunked_decode"],
        }
    )


def _official_generate_with_sampler(
    model: Any,
    parameters: Mapping[str, Any],
    sample_size: int | None,
    sampler: Callable[..., Any],
) -> Any:
    """Invoke official generate while replacing only its Euler loop."""

    official = _official_model(model)
    kwargs: dict[str, Any] = {
        "prompt": parameters["prompt"],
        "negative_prompt": parameters["negative_prompt"],
        "duration": parameters["duration_seconds"],
        "steps": parameters["steps"],
        "cfg_scale": parameters["cfg_scale"],
        "batch_size": 1,
        "seed": parameters["seed"],
        "duration_padding_sec": parameters["duration_padding_seconds"],
        "truncate_output_to_duration": True,
        "sampler_type": parameters["sampler_type"],
        "disable_tqdm": True,
        "chunked_decode": parameters["chunked_decode"],
    }
    if sample_size is not None:
        kwargs["sample_size"] = sample_size

    # sample_diffusion resolves sample_discrete_euler in this module's globals.
    from stable_audio_3.inference import sampling as sampling_module

    with patch.object(sampling_module, "sample_discrete_euler", sampler):
        return official.generate(**kwargs)


def _channels_first_audio(output: Any) -> np.ndarray:
    if hasattr(output, "detach"):
        output = output.detach()
    if hasattr(output, "float"):
        output = output.float()
    if hasattr(output, "cpu"):
        output = output.cpu()
    if hasattr(output, "numpy"):
        output = output.numpy()
    array = np.asarray(output, dtype=np.float32)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim != 3 or array.shape[0] != 1 or array.shape[1] != EXPECTED_CHANNELS:
        raise ValueError(
            f"official smoke E output must have shape (1, 2, frames), got {array.shape}"
        )
    return np.ascontiguousarray(array[0])


def _retain_wav(
    output: Any,
    path: str | os.PathLike[str],
    *,
    context: ProvenanceContext,
    transformation: str,
    source_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    destination = Path(path)
    samples = _channels_first_audio(output)
    save_float_wav_exclusive(
        destination,
        samples,
        EXPECTED_SAMPLE_RATE,
        channels_first=True,
    )
    provenance_path = _write_provenance(
        destination,
        label="synthetic_model_output",
        context=context,
        transformation=transformation,
        source_ids=source_ids,
    )
    sanity = audio_sanity(destination, SMOKE_E_DURATION_SECONDS)
    return {
        "path": str(destination.resolve()),
        "provenance_path": str(provenance_path.resolve()),
        "sanity": sanity,
    }


def _waveform_comparison(
    reference_path: str | os.PathLike[str],
    candidate_path: str | os.PathLike[str],
    *,
    max_abs_tolerance: float,
    min_snr_db: float,
) -> dict[str, Any]:
    reference, reference_rate = load_float_wav(reference_path)
    candidate, candidate_rate = load_float_wav(candidate_path)
    shape_match = bool(reference.shape == candidate.shape)
    sample_rate_match = bool(reference_rate == candidate_rate)
    if not shape_match or not sample_rate_match:
        return {
            "pass": False,
            "shape_match": shape_match,
            "sample_rate_match": sample_rate_match,
            "reference_shape": list(reference.shape),
            "candidate_shape": list(candidate.shape),
            "reference_sample_rate": reference_rate,
            "candidate_sample_rate": candidate_rate,
            "max_abs_error": None,
            "rms_error": None,
            "snr_db": None,
            "zero_error": False,
            "max_abs_tolerance": max_abs_tolerance,
            "min_snr_db": min_snr_db,
        }

    reference64 = reference.astype(np.float64, copy=False)
    candidate64 = candidate.astype(np.float64, copy=False)
    difference = candidate64 - reference64
    error_power = float(np.mean(np.square(difference)))
    signal_power = float(np.mean(np.square(reference64)))
    max_abs_error = float(np.max(np.abs(difference))) if difference.size else 0.0
    zero_error = bool(error_power == 0.0)
    if zero_error:
        snr_db = None
        snr_pass = True
        snr_interpretation = "infinite (zero error)"
    elif signal_power == 0.0:
        snr_db = None
        snr_pass = False
        snr_interpretation = "negative infinity (zero reference power)"
    else:
        snr_db = float(10.0 * math.log10(signal_power / error_power))
        snr_pass = bool(snr_db >= min_snr_db)
        snr_interpretation = "finite"
    max_abs_pass = bool(max_abs_error <= max_abs_tolerance)
    return {
        "pass": bool(max_abs_pass and snr_pass),
        "shape_match": True,
        "sample_rate_match": True,
        "reference_shape": list(reference.shape),
        "candidate_shape": list(candidate.shape),
        "reference_sample_rate": reference_rate,
        "candidate_sample_rate": candidate_rate,
        "exact_array_equal": bool(np.array_equal(reference, candidate)),
        "max_abs_error": max_abs_error,
        "rms_error": float(math.sqrt(error_power)),
        "snr_db": snr_db,
        "snr_interpretation": snr_interpretation,
        "zero_error": zero_error,
        "max_abs_tolerance": max_abs_tolerance,
        "min_snr_db": min_snr_db,
        "max_abs_pass": max_abs_pass,
        "snr_pass": snr_pass,
    }


def _resolve_callable(reference: str) -> Callable[..., Any]:
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise ValueError("callable reference must be 'module.path:function_name'")
    module_name, attribute_name = reference.split(":", 1)
    function = getattr(importlib.import_module(module_name), attribute_name)
    if not callable(function):
        raise TypeError(f"referenced object is not callable: {reference}")
    return function


def _resolution_outputs_exist(resolution: Mapping[str, Any]) -> bool:
    path_fields = (
        "original_copy_path",
        "resolved_config_path",
        "diff_path",
        "resolution_manifest_path",
    )
    return all(
        isinstance(resolution.get(field), str) and Path(resolution[field]).is_file()
        for field in path_fields
    )


def smoke_e_child_runtime_factory(
    request: Mapping[str, Any],
    checkpoint: Any,
) -> ResumeRuntime:
    """Importable child factory: resolve local config, load, generate, retain WAV.

    Every input arrives through JSON ``runtime_kwargs``.  There is no repository
    ID, token, or download fallback in this path.
    """

    runtime_kwargs = request.get("runtime_kwargs")
    if not isinstance(runtime_kwargs, Mapping):
        raise ValueError("smoke E runtime_kwargs must be an object")
    json.dumps(runtime_kwargs, allow_nan=False)

    # Defense in depth: the child is local-only even after model construction.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    frozen_config_path = Path(runtime_kwargs["frozen_config_path"]).resolve(strict=True)
    frozen_config_sha256 = sha256_file(frozen_config_path)
    if frozen_config_sha256 != runtime_kwargs["frozen_config_sha256"]:
        raise ValueError("child frozen foundation config SHA-256 mismatch")
    parameters = _frozen_parameters(_read_json_object(frozen_config_path))
    sample_size = runtime_kwargs.get("sample_size")
    if sample_size is not None and (
        isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size <= 0
    ):
        raise ValueError("child sample_size must be a positive integer or null")

    required_t5_files = runtime_kwargs.get("required_t5_files")
    if (
        isinstance(required_t5_files, (str, bytes))
        or not isinstance(required_t5_files, Sequence)
        or not required_t5_files
        or any(not isinstance(value, str) or not value for value in required_t5_files)
    ):
        raise ValueError("required_t5_files must be a non-empty JSON string list")
    resolution = resolve_local_model_config(
        runtime_kwargs["original_config_path"],
        runtime_kwargs["embedded_t5_snapshot_path"],
        runtime_kwargs["config_evidence_dir"],
        required_t5_files=tuple(required_t5_files),
    )
    expected_resolution_identity = runtime_kwargs.get("expected_resolution_identity")
    if not isinstance(expected_resolution_identity, Mapping):
        raise ValueError("expected_resolution_identity must be a JSON object")
    observed_resolution_identity = {
        "original_sha256": resolution.original_sha256,
        "resolved_sha256": resolution.resolved_sha256,
        "diff_sha256": resolution.diff_sha256,
        "t5_snapshot_file_sha256s": dict(resolution.t5_snapshot_file_sha256s),
    }
    if observed_resolution_identity != dict(expected_resolution_identity):
        raise ValueError(
            "child local config/snapshot identity drifted from the parent-verified files: "
            f"expected {dict(expected_resolution_identity)}, "
            f"observed {observed_resolution_identity}"
        )

    loader_reference = runtime_kwargs.get("model_loader_factory", DEFAULT_CHILD_MODEL_LOADER)
    loader = _resolve_callable(loader_reference)
    loaded = loader(
        resolution,
        runtime_kwargs["model_checkpoint_path"],
        device=runtime_kwargs["device"],
        model_half=runtime_kwargs["model_half"],
        expected_checkpoint_sha256=runtime_kwargs["model_checkpoint_sha256"],
    )
    if not callable(getattr(loaded, "generate", None)) and not callable(
        getattr(getattr(loaded, "stable_audio_model", None), "generate", None)
    ):
        raise TypeError("child model loader did not return a ModelRuntime-compatible object")

    conditioning_sha256 = _generation_identity(parameters, sample_size)
    context = _normalize_provenance(runtime_kwargs["provenance"])

    def invoke_generate(resume_sampler: Callable[..., Any]) -> Any:
        return _official_generate_with_sampler(
            loaded,
            parameters,
            sample_size,
            resume_sampler,
        )

    def finalize(
        _final_latent: Any,
        generated_output: Any,
        loaded_checkpoint: Any,
        _loaded_request: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        checkpoint_id = _artifact_source_id(loaded_checkpoint.path)
        wav = _retain_wav(
            generated_output,
            runtime_kwargs["output_wav_path"],
            context=context,
            transformation=(
                "official 50-step Euler decode after separate-process resume from "
                f"completed step {loaded_checkpoint.next_step_index}"
            ),
            source_ids=(*context.source_ids, checkpoint_id),
        )
        finalize_generated_audio((wav,), smoke="E")
        resolution_dict = resolution.to_dict()
        if not _resolution_outputs_exist(resolution_dict):
            raise RuntimeError("child local config resolution evidence was not retained")
        return {
            "wav": wav,
            "config_resolution": resolution_dict,
            "local_model_checkpoint_path": str(
                Path(runtime_kwargs["model_checkpoint_path"]).resolve()
            ),
            "local_model_checkpoint_sha256": runtime_kwargs["model_checkpoint_sha256"],
            "network_access": "disabled; local paths only",
            "generation_parameters": {
                **parameters,
                "sample_size": sample_size,
                "batch_size": 1,
                "truncate_output_to_duration": True,
                "disable_tqdm": True,
            },
        }

    return ResumeRuntime(
        conditioning_sha256=conditioning_sha256,
        config_sha256=frozen_config_sha256,
        invoke_generate=invoke_generate,
        finalize=finalize,
    )


def _runtime_evidence(model: Any) -> tuple[Any, ResolvedModelConfig, Path, str, str, bool]:
    if not isinstance(model, ModelRuntime):
        # A structural fallback keeps CPU contract tests small, while requiring
        # every field supplied by the real ModelRuntime.
        required = (
            "stable_audio_model",
            "config_resolution",
            "checkpoint_path",
            "checkpoint_sha256",
            "device",
            "model_half",
        )
        missing = [field for field in required if not hasattr(model, field)]
        if missing:
            raise TypeError(f"smoke E requires ModelRuntime fields; missing {missing}")
    official = _official_model(model)
    resolution = model.config_resolution
    if not isinstance(resolution, ResolvedModelConfig):
        raise TypeError("ModelRuntime.config_resolution must be ResolvedModelConfig")
    checkpoint_path = Path(model.checkpoint_path).resolve(strict=True)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    if model.checkpoint_sha256 != checkpoint_sha256:
        raise ValueError("ModelRuntime checkpoint identity no longer matches disk")
    return (
        official,
        resolution,
        checkpoint_path,
        checkpoint_sha256,
        str(model.device),
        bool(model.model_half),
    )


def _module_tensor_inventory(module: Any) -> dict[str, Any]:
    """Summarize registered parameter/buffer placement without retaining tensors."""

    if not callable(getattr(module, "named_parameters", None)) or not callable(
        getattr(module, "named_buffers", None)
    ):
        raise TypeError("official.model must expose named_parameters and named_buffers")

    device_tensor_counts: dict[str, int] = {}
    device_numel: dict[str, int] = {}
    cuda_parameter_names: list[str] = []
    cuda_buffer_names: list[str] = []
    parameter_count = 0
    buffer_count = 0
    parameter_numel = 0
    buffer_numel = 0

    for kind, iterator in (
        ("parameter", module.named_parameters(recurse=True)),
        ("buffer", module.named_buffers(recurse=True)),
    ):
        for name, tensor in iterator:
            device = getattr(tensor, "device", None)
            device_type = getattr(device, "type", None)
            device_name = str(device)
            numel = int(tensor.numel())
            device_tensor_counts[device_name] = device_tensor_counts.get(device_name, 0) + 1
            device_numel[device_name] = device_numel.get(device_name, 0) + numel
            if kind == "parameter":
                parameter_count += 1
                parameter_numel += numel
                if device_type == "cuda":
                    cuda_parameter_names.append(name)
            else:
                buffer_count += 1
                buffer_numel += numel
                if device_type == "cuda":
                    cuda_buffer_names.append(name)

    return {
        "parameter_count": parameter_count,
        "buffer_count": buffer_count,
        "parameter_numel": parameter_numel,
        "buffer_numel": buffer_numel,
        "device_tensor_counts": dict(sorted(device_tensor_counts.items())),
        "device_numel": dict(sorted(device_numel.items())),
        "cuda_parameter_count": len(cuda_parameter_names),
        "cuda_buffer_count": len(cuda_buffer_names),
        "cuda_parameter_name_sample": cuda_parameter_names[:20],
        "cuda_buffer_name_sample": cuda_buffer_names[:20],
    }


def _offload_parent_model_to_cpu(
    official: Any,
    *,
    torch_module: Any | None = None,
) -> dict[str, Any]:
    """Move the entire parent conditioned model off CUDA before child loading."""

    if torch_module is None:
        import torch as torch_module

    conditioned_model = getattr(official, "model", None)
    if conditioned_model is None or not callable(getattr(conditioned_model, "to", None)):
        raise TypeError("official StableAudioModel.model must support to('cpu')")
    component_presence = {
        "conditioner": hasattr(conditioned_model, "conditioner"),
        "dit": hasattr(conditioned_model, "model"),
        "pretransform": hasattr(conditioned_model, "pretransform"),
    }
    if not all(component_presence.values()):
        raise TypeError(
            "official conditioned model is missing conditioner/DiT/pretransform components: "
            f"{component_presence}"
        )

    before_inventory = _module_tensor_inventory(conditioned_model)
    configured_device = str(getattr(official, "device", "cpu"))
    cuda_device_names = [
        name for name in before_inventory["device_tensor_counts"] if name.startswith("cuda")
    ]
    configured_torch_device = torch_module.device(configured_device)
    cuda_monitoring_active = bool(
        torch_module.cuda.is_available()
        and (cuda_device_names or configured_torch_device.type == "cuda")
    )
    monitored_device = None
    before_allocated = None
    before_reserved = None
    synchronize_calls = 0
    if cuda_monitoring_active:
        monitored_device = torch_module.device(
            cuda_device_names[0] if cuda_device_names else configured_device
        )
        torch_module.cuda.synchronize(monitored_device)
        synchronize_calls += 1
        before_allocated = int(torch_module.cuda.memory_allocated(monitored_device))
        before_reserved = int(torch_module.cuda.memory_reserved(monitored_device))

    conditioned_model.to("cpu")
    # StableAudioModel is not itself an nn.Module; keep its routing device in
    # sync with the now-CPU conditioned model. ModelRuntime.device remains the
    # immutable original child-placement input captured before this teardown.
    official.device = "cpu"
    gc_collected_objects = int(gc.collect())

    empty_cache_called = False
    after_allocated = None
    after_reserved = None
    if cuda_monitoring_active:
        torch_module.cuda.empty_cache()
        empty_cache_called = True
        torch_module.cuda.synchronize(monitored_device)
        synchronize_calls += 1
        after_allocated = int(torch_module.cuda.memory_allocated(monitored_device))
        after_reserved = int(torch_module.cuda.memory_reserved(monitored_device))

    after_inventory = _module_tensor_inventory(conditioned_model)
    no_cuda_model_tensors = bool(
        after_inventory["cuda_parameter_count"] == 0 and after_inventory["cuda_buffer_count"] == 0
    )
    if not no_cuda_model_tensors:
        raise RuntimeError(f"parent model offload left registered CUDA tensors: {after_inventory}")
    if str(getattr(official, "device", None)) != "cpu":
        raise RuntimeError("parent StableAudioModel routing device was not changed to CPU")

    residual_note = (
        "CUDA was not active for the parent runtime; allocator fields are null."
        if not cuda_monitoring_active
        else (
            "No allocated or reserved CUDA bytes remain in the parent process."
            if after_allocated == 0 and after_reserved == 0
            else (
                "Registered parent model parameters/buffers are all on CPU; remaining "
                "allocator bytes are therefore recorded as non-model process residual/cache."
            )
        )
    )
    return {
        "offload_method": "official.model.to('cpu')",
        "original_official_device": configured_device,
        "final_official_device": str(official.device),
        "conditioned_model_components_present": component_presence,
        "before_tensor_inventory": before_inventory,
        "after_tensor_inventory": after_inventory,
        "no_parent_model_parameters_or_buffers_on_cuda": no_cuda_model_tensors,
        "cuda_monitoring_active": cuda_monitoring_active,
        "monitored_cuda_device": None if monitored_device is None else str(monitored_device),
        "cuda_allocated_bytes_before_offload": before_allocated,
        "cuda_reserved_bytes_before_offload": before_reserved,
        "cuda_allocated_bytes_after_offload": after_allocated,
        "cuda_reserved_bytes_after_offload": after_reserved,
        "non_model_cuda_allocated_residual_bytes": after_allocated,
        "non_model_cuda_reserved_residual_bytes": after_reserved,
        "cuda_empty_cache_called": empty_cache_called,
        "cuda_synchronize_calls": synchronize_calls,
        "gc_collected_objects": gc_collected_objects,
        "residual_interpretation": residual_note,
    }


def _failed_result(
    started_at: str,
    *,
    parameters: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    error: BaseException,
) -> SmokeEResult:
    result = SmokeEResult(
        smoke="E",
        status="FAIL",
        started_at_utc=started_at,
        ended_at_utc=_utc_now(),
        parameters=dict(parameters),
        checks={"execution_completed": False},
        metrics={},
        artifacts=dict(artifacts),
        error={
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        },
    )
    result.to_dict()
    return result


def run_smoke_e(
    model_runtime: ModelRuntime,
    output_dir: str | os.PathLike[str],
    *,
    frozen_config_path: str | os.PathLike[str],
    provenance: ProvenanceContext | Mapping[str, Any],
    python_executable: str | os.PathLike[str] | None = None,
    child_timeout_seconds: float | None = None,
    required_t5_files: Sequence[str] = DEFAULT_REQUIRED_T5_FILES,
    child_model_loader_factory: str = DEFAULT_CHILD_MODEL_LOADER,
) -> SmokeEResult:
    """Run reference export and three sequential official-API child resumes."""

    started = _utc_now()
    artifacts: dict[str, Any] = {
        "reference_wav": None,
        "checkpoints": [],
        "resumes": [],
    }
    parameters: dict[str, Any] = {}
    try:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        frozen_path = Path(frozen_config_path).resolve(strict=True)
        frozen_config_sha256 = sha256_file(frozen_path)
        parameters = _frozen_parameters(_read_json_object(frozen_path))
        context = _normalize_provenance(provenance)
        (
            official,
            parent_resolution,
            model_checkpoint_path,
            model_checkpoint_sha256,
            device,
            model_half,
        ) = _runtime_evidence(model_runtime)
        sample_size = _sample_size(official)
        conditioning_sha256 = _generation_identity(parameters, sample_size)
        parameters = {
            **parameters,
            "official_api": "stable_audio_3.model.StableAudioModel.generate",
            "sample_size": sample_size,
            "batch_size": 1,
            "truncate_output_to_duration": True,
            "disable_tqdm": True,
            "frozen_config_path": str(frozen_path),
            "frozen_config_sha256": frozen_config_sha256,
            "conditioning_sha256": conditioning_sha256,
            "model_checkpoint_path": str(model_checkpoint_path),
            "model_checkpoint_sha256": model_checkpoint_sha256,
            "device": device,
            "model_half": model_half,
            "child_runtime_factory": SMOKE_E_CHILD_FACTORY,
            "child_model_loader_factory": child_model_loader_factory,
        }

        checkpoint_dir = destination / "checkpoints"

        def retain_checkpoint_provenance(artifact: CheckpointArtifact) -> None:
            state_metadata = _read_json_object(artifact.state_metadata_path)
            provenance_path = _write_provenance(
                artifact.path,
                label="latent_checkpoint",
                context=context,
                transformation=(
                    "post-transition upstream Euler sampler state after "
                    f"{artifact.completed_steps} of 50 completed steps; includes latent, "
                    "full schedule, next index, identities, and hashes"
                ),
            )
            validated = validate_adjacent_provenance(artifact.path)
            artifacts["checkpoints"].append(
                {
                    "completed_steps": artifact.completed_steps,
                    "next_step_index": artifact.next_step_index,
                    "path": str(artifact.path.resolve()),
                    "state_metadata_path": str(artifact.state_metadata_path.resolve()),
                    "provenance_path": str(provenance_path.resolve()),
                    "checkpoint_sha256": artifact.checkpoint_sha256,
                    "latent_sha256": artifact.latent_sha256,
                    "schedule_sha256": artifact.schedule_sha256,
                    "latent_dtype": state_metadata.get("latent_dtype"),
                    "latent_shape": state_metadata.get("latent_shape"),
                    "latent_device_at_export": state_metadata.get("latent_device_at_export"),
                    "runtime_latent_dtype_recorded_at_export": bool(
                        isinstance(state_metadata.get("latent_dtype"), str)
                        and state_metadata.get("latent_dtype")
                    ),
                    "provenance_valid": bool(validated["label"] == "latent_checkpoint"),
                }
            )

        reference_sampler = CheckpointingEulerSampler(
            checkpoint_dir=checkpoint_dir,
            checkpoint_prefix="e_reference",
            run_id=context.run_id,
            conditioning_sha256=conditioning_sha256,
            config_sha256=frozen_config_sha256,
            run_metadata={
                "seed_id": parameters["seed_id"],
                "seed": parameters["seed"],
                "frozen_config_path": str(frozen_path),
                "frozen_config_sha256": frozen_config_sha256,
                "parent_config_resolution": parent_resolution.to_dict(),
                "model_checkpoint_path": str(model_checkpoint_path),
                "model_checkpoint_sha256": model_checkpoint_sha256,
            },
            checkpoint_callback=retain_checkpoint_provenance,
        )
        reference_output = _official_generate_with_sampler(
            model_runtime,
            parameters,
            sample_size,
            reference_sampler,
        )
        if reference_sampler.last_run_result is None:
            raise RuntimeError("official reference generation did not invoke Euler sampler")
        try:
            reference_output_weakref = weakref.ref(reference_output)
            reference_final_latent_weakref = weakref.ref(reference_sampler.last_run_result.latent)
        except TypeError as exc:
            raise RuntimeError(
                "reference output/final latent must support weak references for release proof"
            ) from exc
        reference_wav = _retain_wav(
            reference_output,
            destination / "e_reference_30s.wav",
            context=context,
            transformation=(
                "uninterrupted official 50-step Euler text-to-audio decode with latent exports"
            ),
        )
        finalize_generated_audio((reference_wav,), smoke="E")
        artifacts["reference_wav"] = reference_wav

        checkpoint_rows = sorted(artifacts["checkpoints"], key=lambda row: row["completed_steps"])
        if [row["completed_steps"] for row in checkpoint_rows] != list(CHECKPOINT_COMPLETED_STEPS):
            raise RuntimeError("reference did not retain exact 15/30/40 checkpoints")
        artifacts["checkpoints"] = checkpoint_rows

        # The reference sampler owns its final CUDA latent even after the WAV
        # has been retained. Release both it and the decoded output before the
        # child creates another full model process. Weak references prove that
        # no hidden Python owner kept either tensor/array alive.
        reference_sampler.last_run_result = None
        del reference_output
        del reference_sampler
        parent_runtime_release = _offload_parent_model_to_cpu(official)
        reference_output_released = reference_output_weakref() is None
        reference_final_latent_released = reference_final_latent_weakref() is None
        parent_runtime_release.update(
            {
                "reference_output_reference_released": reference_output_released,
                "reference_sampler_final_latent_reference_released": (
                    reference_final_latent_released
                ),
                "release_completed_before_first_child": True,
                "parent_model_intentionally_not_restored_to_cuda": True,
            }
        )
        if not reference_output_released or not reference_final_latent_released:
            raise RuntimeError(
                "reference output or sampler final latent remains referenced before child launch"
            )

        child_environment = os.environ.copy()
        child_environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            }
        )
        expected_forward_calls = {15: 35, 30: 20, 40: 10}
        execution_order: list[int] = []
        for checkpoint_row in checkpoint_rows:
            step = checkpoint_row["completed_steps"]
            execution_order.append(step)
            stem = f"e_resume_step_{step:03d}"
            request_path = destination / f"{stem}.request.json"
            result_path = destination / f"{stem}.result.pt"
            output_wav_path = destination / f"{stem}_30s.wav"
            evidence_dir = destination / f"{stem}.config-resolution"
            resume_row: dict[str, Any] = {
                "checkpoint_completed_steps": step,
                "request_path": str(request_path.resolve()),
                "result_path": str(result_path.resolve()),
                "expected_output_wav_path": str(output_wav_path.resolve()),
                "expected_remaining_forward_calls": expected_forward_calls[step],
                "status": "FAIL",
            }
            try:
                launched = run_resume_in_subprocess(
                    request_path=request_path,
                    checkpoint_path=checkpoint_row["path"],
                    result_path=result_path,
                    runtime_factory=SMOKE_E_CHILD_FACTORY,
                    conditioning_sha256=conditioning_sha256,
                    config_sha256=frozen_config_sha256,
                    runtime_kwargs={
                        "frozen_config_path": str(frozen_path),
                        "frozen_config_sha256": frozen_config_sha256,
                        "original_config_path": parent_resolution.original_source_path,
                        "embedded_t5_snapshot_path": parent_resolution.t5_snapshot_path,
                        "config_evidence_dir": str(evidence_dir.resolve()),
                        "required_t5_files": list(required_t5_files),
                        "expected_resolution_identity": {
                            "original_sha256": parent_resolution.original_sha256,
                            "resolved_sha256": parent_resolution.resolved_sha256,
                            "diff_sha256": parent_resolution.diff_sha256,
                            "t5_snapshot_file_sha256s": dict(
                                parent_resolution.t5_snapshot_file_sha256s
                            ),
                        },
                        "model_checkpoint_path": str(model_checkpoint_path),
                        "model_checkpoint_sha256": model_checkpoint_sha256,
                        "model_loader_factory": child_model_loader_factory,
                        "device": device,
                        "model_half": model_half,
                        "sample_size": sample_size,
                        "output_wav_path": str(output_wav_path.resolve()),
                        "provenance": _provenance_dict(context),
                    },
                    request_metadata={
                        "smoke": "E",
                        "checkpoint_completed_steps": step,
                        "seed_id": parameters["seed_id"],
                    },
                    python_executable=python_executable or sys.executable,
                    timeout_seconds=_bounded_child_timeout(child_timeout_seconds),
                    env=child_environment,
                )
                result_metadata = launched.artifact.metadata
                finalize_metadata = result_metadata["finalize_metadata"]
                wav = finalize_metadata["wav"]
                wav_sanity = audio_sanity(wav["path"], SMOKE_E_DURATION_SECONDS)
                comparison = _waveform_comparison(
                    reference_wav["path"],
                    wav["path"],
                    max_abs_tolerance=parameters["waveform_max_abs_tolerance"],
                    min_snr_db=parameters["waveform_min_snr_db"],
                )
                result_provenance_path = _write_provenance(
                    result_path,
                    label="latent_checkpoint",
                    context=context,
                    transformation=(
                        "terminal latent after separate-process Euler resume from "
                        f"completed step {step}"
                    ),
                    source_ids=(
                        *context.source_ids,
                        _artifact_source_id(checkpoint_row["path"]),
                    ),
                )
                result_provenance = validate_adjacent_provenance(result_path)
                row_checks = {
                    "child_pid_differs_from_reference_pid": bool(
                        result_metadata["child_pid"] != os.getpid()
                    ),
                    "remaining_forward_calls_exact": bool(
                        result_metadata["forward_calls"] == expected_forward_calls[step]
                    ),
                    "runtime_schedule_validated": bool(
                        result_metadata["runtime_schedule_validated"] is True
                    ),
                    "checkpoint_runtime_latent_dtype_preserved": bool(
                        result_metadata.get("checkpoint_latent_dtype")
                        == checkpoint_row["latent_dtype"]
                        and result_metadata.get("resume_latent_dtype_preserved") is True
                    ),
                    "official_generate_sampler_injection": bool(
                        result_metadata["execution_mode"] == "official_generate_sampler_injection"
                    ),
                    "resumed_wav_common_audio_checks_pass": bool(wav_sanity["pass"]),
                    "waveform_equivalence_within_tolerance": bool(comparison["pass"]),
                    "child_config_resolution_evidence_retained": bool(
                        _resolution_outputs_exist(finalize_metadata["config_resolution"])
                    ),
                    "resumed_wav_provenance_valid": bool(
                        validate_adjacent_provenance(wav["path"])["label"]
                        == "synthetic_model_output"
                    ),
                    "resume_result_provenance_valid": bool(
                        result_provenance["label"] == "latent_checkpoint"
                    ),
                }
                resume_row.update(
                    {
                        "status": "PASS" if all(row_checks.values()) else "FAIL",
                        "child_pid": result_metadata["child_pid"],
                        "reference_pid": os.getpid(),
                        "remaining_forward_calls": result_metadata["forward_calls"],
                        "execution_mode": result_metadata["execution_mode"],
                        "runtime_schedule_validated": result_metadata["runtime_schedule_validated"],
                        "fresh_initial_latent_dtype": result_metadata.get(
                            "fresh_initial_latent_dtype"
                        ),
                        "checkpoint_latent_dtype": result_metadata.get("checkpoint_latent_dtype"),
                        "resume_latent_dtype_preserved": result_metadata.get(
                            "resume_latent_dtype_preserved"
                        ),
                        "child_process": {
                            "args": (
                                list(launched.process.args)
                                if isinstance(launched.process.args, Sequence)
                                and not isinstance(launched.process.args, (str, bytes))
                                else str(launched.process.args)
                            ),
                            "returncode": launched.process.returncode,
                            "stdout": launched.process.stdout,
                            "stderr": launched.process.stderr,
                        },
                        "result_sha256": launched.artifact.artifact_sha256,
                        "result_provenance_path": str(result_provenance_path.resolve()),
                        "wav": {**wav, "sanity": wav_sanity},
                        "comparison_to_reference": comparison,
                        "config_resolution": finalize_metadata["config_resolution"],
                        "network_access": finalize_metadata["network_access"],
                        "generation_parameters": finalize_metadata["generation_parameters"],
                        "checks": row_checks,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - retain terminal row and continue
                resume_row["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            artifacts["resumes"].append(resume_row)

        resume_rows = artifacts["resumes"]
        checks = {
            "parent_reference_output_and_final_latent_released_before_children": bool(
                parent_runtime_release["reference_output_reference_released"]
                and parent_runtime_release["reference_sampler_final_latent_reference_released"]
                and parent_runtime_release["release_completed_before_first_child"]
            ),
            "parent_full_conditioned_model_offloaded_to_cpu_before_children": bool(
                parent_runtime_release["final_official_device"] == "cpu"
                and all(parent_runtime_release["conditioned_model_components_present"].values())
            ),
            "no_parent_model_parameters_or_buffers_remain_cuda": bool(
                parent_runtime_release["no_parent_model_parameters_or_buffers_on_cuda"]
            ),
            "parent_cuda_cache_cleared_before_children": bool(
                not parent_runtime_release["cuda_monitoring_active"]
                or (
                    parent_runtime_release["cuda_empty_cache_called"]
                    and parent_runtime_release["cuda_synchronize_calls"] >= 2
                )
            ),
            "reference_common_audio_checks_pass": bool(reference_wav["sanity"]["pass"]),
            "checkpoints_exported_after_15_30_40_steps": bool(
                [row["completed_steps"] for row in checkpoint_rows]
                == list(CHECKPOINT_COMPLETED_STEPS)
            ),
            "all_checkpoint_provenance_valid": bool(
                all(row["provenance_valid"] for row in checkpoint_rows)
            ),
            "all_checkpoints_record_runtime_dtype_at_export": bool(
                all(row["runtime_latent_dtype_recorded_at_export"] for row in checkpoint_rows)
            ),
            "three_children_launched_sequentially": bool(
                execution_order == list(CHECKPOINT_COMPLETED_STEPS) and len(resume_rows) == 3
            ),
            "three_unique_children_distinct_from_parent": bool(
                len(resume_rows) == 3
                and all(isinstance(row.get("child_pid"), int) for row in resume_rows)
                and len({row["child_pid"] for row in resume_rows}) == 3
                and all(row["child_pid"] != os.getpid() for row in resume_rows)
            ),
            "all_children_terminal_pass": bool(
                len(resume_rows) == 3 and all(row["status"] == "PASS" for row in resume_rows)
            ),
            "all_child_pids_differ_from_reference_pid": bool(
                len(resume_rows) == 3
                and all(row.get("child_pid") != os.getpid() for row in resume_rows)
            ),
            "remaining_forward_calls_are_35_20_10": bool(
                [row.get("remaining_forward_calls") for row in resume_rows] == [35, 20, 10]
            ),
            "all_resumed_wavs_pass_common_audio_checks": bool(
                len(resume_rows) == 3
                and all(row.get("wav", {}).get("sanity", {}).get("pass") for row in resume_rows)
            ),
            "all_waveform_equivalence_checks_pass": bool(
                len(resume_rows) == 3
                and all(row.get("comparison_to_reference", {}).get("pass") for row in resume_rows)
            ),
            "all_child_config_resolution_evidence_retained": bool(
                len(resume_rows) == 3
                and all(
                    _resolution_outputs_exist(row.get("config_resolution", {}))
                    for row in resume_rows
                )
            ),
        }
        result = SmokeEResult(
            smoke="E",
            status="PASS" if all(checks.values()) else "FAIL",
            started_at_utc=started,
            ended_at_utc=_utc_now(),
            parameters=parameters,
            checks=checks,
            metrics={
                "reference_pid": os.getpid(),
                "child_pids": [row.get("child_pid") for row in resume_rows],
                "remaining_forward_calls": [
                    row.get("remaining_forward_calls") for row in resume_rows
                ],
                "waveform_tolerance": {
                    "max_abs_lte": parameters["waveform_max_abs_tolerance"],
                    "snr_db_gte": parameters["waveform_min_snr_db"],
                },
                "parent_runtime_release_before_children": parent_runtime_release,
                "parent_config_resolution": parent_resolution.to_dict(),
            },
            artifacts=artifacts,
        )
        result.to_dict()
        return result
    except Exception as exc:  # noqa: BLE001 - smoke returns terminal failure evidence
        return _failed_result(
            started,
            parameters=parameters,
            artifacts=artifacts,
            error=exc,
        )


__all__ = [
    "SMOKE_E_CHILD_FACTORY",
    "SmokeEResult",
    "run_smoke_e",
    "smoke_e_child_runtime_factory",
]

"""Callable Stable Audio 3 foundation smokes A--D.

All generation calls route through the official ``StableAudioModel.generate``
method.  This module owns only engineering checks: retained audio integrity,
determinism, official continuation/inpainting argument paths, and measured
runtime/call-count instrumentation.  It does not contain model-quality scoring
or scientific acceptance logic.
"""

from __future__ import annotations

import math
import os
import time
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np

from sa3_smoke.artifacts import sha256_file, write_adjacent_provenance
from sa3_smoke.audio import (
    ACTIVE_MAGNITUDE_THRESHOLD,
    EXPECTED_CHANNELS,
    EXPECTED_SAMPLE_RATE,
    MIN_ACTIVE_FRACTION,
    PEAK_THRESHOLD,
    RMS_THRESHOLD,
    audio_sanity,
    load_float_wav,
    save_float_wav_exclusive,
    waveform_metrics,
)
from sa3_smoke.budget import finalize_generated_audio

SmokeStatus = Literal["PASS", "FAIL"]
Prompt = str | Sequence[str]

BASE_DURATION_SECONDS = 30.0
BASE_STEPS = 50
BASE_CFG_SCALE = 7.0
BASE_SAMPLER = "euler"
BASE_DURATION_PADDING_SECONDS = 6.0
BASE_NEGATIVE_PROMPT = "low quality, clipping, silence"
BASE_CHUNKED_DECODE = True
BASE_BATCH4_PROMPTS = (
    "Steady electronic drums and warm synthesizer, 100 BPM",
    "Clean acoustic guitar rhythm with light percussion, 110 BPM",
    "Ambient synthesizer pulse with a steady beat, 90 BPM",
    "Bright piano groove with bass and drums, 120 BPM",
)

SEED_A = 73_193_001
SEED_B = 73_193_002
SEED_C_SINGLE = 73_193_003
SEED_C_MULTI = 73_193_004
SEED_D_BATCH1 = 73_193_005
SEED_D_BATCH4 = 73_193_006

NONDETERMINISM_SOURCES = (
    "CUDA reduction order",
    "Flash Attention kernels",
    "PyTorch kernel selection",
    "hardware or driver changes",
    "half-precision arithmetic",
)


@dataclass(frozen=True)
class ProvenanceContext:
    """Run-level fields required by every adjacent provenance sidecar."""

    creating_command: str
    run_id: str
    source_ids: tuple[str, ...]
    model_revision: str
    license_identifier: str

    def __post_init__(self) -> None:
        string_fields = (
            self.creating_command,
            self.run_id,
            self.model_revision,
            self.license_identifier,
        )
        if any(not isinstance(value, str) or not value.strip() for value in string_fields):
            raise ValueError("provenance context string fields must be non-empty")
        if not self.source_ids or any(
            not isinstance(value, str) or not value.strip() for value in self.source_ids
        ):
            raise ValueError("provenance source_ids must contain non-empty strings")


@dataclass(frozen=True)
class AudioArtifact:
    """Retained WAV, adjacent provenance, and post-reload acceptance evidence."""

    path: str
    provenance_path: str
    label: str
    sanity: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmokeResult:
    """Strict-JSON-compatible terminal result for one smoke."""

    smoke: str
    status: SmokeStatus
    started_at_utc: str
    ended_at_utc: str
    parameters: Mapping[str, Any]
    checks: Mapping[str, Any]
    metrics: Mapping[str, Any]
    artifacts: tuple[AudioArtifact, ...]
    error: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_provenance_context(
    context: ProvenanceContext | Mapping[str, Any],
) -> ProvenanceContext:
    if isinstance(context, ProvenanceContext):
        return context
    try:
        raw_source_ids = context["source_ids"]
        if isinstance(raw_source_ids, (str, bytes)):
            raise ValueError("provenance source_ids must be a sequence, not a string")
        source_ids = tuple(raw_source_ids)
        return ProvenanceContext(
            creating_command=str(context["creating_command"]),
            run_id=str(context["run_id"]),
            source_ids=source_ids,
            model_revision=str(context["model_revision"]),
            license_identifier=str(context["license_identifier"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid provenance context mapping") from exc


def _official_model(model: Any) -> Any:
    official = getattr(model, "stable_audio_model", model)
    if not callable(getattr(official, "generate", None)):
        raise TypeError("model must expose official StableAudioModel.generate")
    return official


def _sample_size(official: Any, explicit: int | None) -> int | None:
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, int) or explicit <= 0:
            raise ValueError("sample_size must be a positive integer")
        return explicit
    config = getattr(official, "model_config", None)
    if isinstance(config, Mapping):
        value = config.get("sample_size")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _generation_parameters(
    *,
    prompt: Prompt,
    negative_prompt: str | None,
    duration: float,
    steps: int,
    cfg_scale: float,
    seed: int,
    batch_size: int,
    sample_size: int | None,
    chunked_decode: bool | None,
) -> dict[str, Any]:
    return {
        "official_api": "stable_audio_3.model.StableAudioModel.generate",
        "prompt": prompt if isinstance(prompt, str) else list(prompt),
        "negative_prompt": negative_prompt,
        "duration_seconds": float(duration),
        "steps": steps,
        "cfg_scale": float(cfg_scale),
        "seed": seed,
        "batch_size": batch_size,
        "sample_size": sample_size,
        "sampler_type": BASE_SAMPLER,
        "duration_padding_seconds": BASE_DURATION_PADDING_SECONDS,
        "truncate_output_to_duration": True,
        "chunked_decode": chunked_decode,
    }


def _generate(
    model: Any,
    *,
    prompt: Prompt,
    negative_prompt: str | None,
    duration: float,
    steps: int,
    cfg_scale: float,
    seed: int,
    batch_size: int,
    sample_size: int | None,
    chunked_decode: bool | None,
    **extra: Any,
) -> Any:
    official = _official_model(model)
    kwargs: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "duration": duration,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "seed": seed,
        "batch_size": batch_size,
        "truncate_output_to_duration": True,
        "duration_padding_sec": BASE_DURATION_PADDING_SECONDS,
        "sampler_type": BASE_SAMPLER,
        "disable_tqdm": True,
        "chunked_decode": chunked_decode,
    }
    resolved_sample_size = _sample_size(official, sample_size)
    if resolved_sample_size is not None:
        kwargs["sample_size"] = resolved_sample_size
    kwargs.update(extra)
    return official.generate(**kwargs)


def _as_batch_channels_first(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "float"):
        # Official output is a torch tensor; float32 fixes the retained
        # decoded-waveform representation before the CPU transfer.
        value = value.float()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    array = np.asarray(value, dtype=np.float32)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim != 3:
        raise ValueError(
            f"generated audio must have shape (batch, channels, frames), got {array.shape}"
        )
    if array.shape[1] != EXPECTED_CHANNELS:
        raise ValueError(
            f"generated audio must have {EXPECTED_CHANNELS} channels, got {array.shape[1]}"
        )
    return np.ascontiguousarray(array)


def _artifact_source_id(path: str | os.PathLike[str]) -> str:
    artifact = Path(path).resolve()
    return f"{artifact}#sha256={sha256_file(artifact)}"


def _write_audio_artifact(
    path: Path,
    channels_first_samples: np.ndarray,
    *,
    requested_seconds: float,
    label: str,
    provenance: ProvenanceContext,
    transformation: str,
    source_ids: Sequence[str] | None = None,
) -> AudioArtifact:
    save_float_wav_exclusive(
        path,
        channels_first_samples,
        EXPECTED_SAMPLE_RATE,
        channels_first=True,
    )
    record = {
        "label": label,
        "created_at_utc": _utc_now(),
        "creating_command": provenance.creating_command,
        "run_id": provenance.run_id,
        "source_ids": list(source_ids or provenance.source_ids),
        "model_revision": provenance.model_revision,
        "license_identifier": provenance.license_identifier,
        "transformation": transformation,
    }
    provenance_path = write_adjacent_provenance(path, record)
    sanity = audio_sanity(path, requested_seconds)
    return AudioArtifact(
        path=str(path.resolve()),
        provenance_path=str(provenance_path.resolve()),
        label=label,
        sanity=sanity,
    )


def _write_generated_batch(
    output: Any,
    *,
    output_dir: Path,
    stem: str,
    requested_seconds: float,
    expected_batch_size: int,
    provenance: ProvenanceContext,
    transformation: str,
    smoke: str,
    source_ids: Sequence[str] | None = None,
) -> list[AudioArtifact]:
    batch = _as_batch_channels_first(output)
    if batch.shape[0] != expected_batch_size:
        raise ValueError(
            f"official generation returned batch {batch.shape[0]}, expected {expected_batch_size}"
        )
    artifacts: list[AudioArtifact] = []
    for index, samples in enumerate(batch):
        suffix = f"_{index + 1}" if expected_batch_size > 1 else ""
        artifact = _write_audio_artifact(
            output_dir / f"{stem}{suffix}.wav",
            samples,
            requested_seconds=requested_seconds,
            label="synthetic_model_output",
            provenance=provenance,
            transformation=transformation,
            source_ids=source_ids,
        )
        artifacts.append(artifact)
    finalize_generated_audio(tuple(artifact.to_dict() for artifact in artifacts), smoke=smoke)
    return artifacts


def _error_metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, Any]:
    if reference.shape != candidate.shape:
        raise ValueError(f"waveform shape mismatch: {reference.shape} != {candidate.shape}")
    reference64 = np.asarray(reference, dtype=np.float64)
    candidate64 = np.asarray(candidate, dtype=np.float64)
    if not np.isfinite(reference64).all() or not np.isfinite(candidate64).all():
        raise ValueError("cannot compare non-finite waveforms")
    difference = candidate64 - reference64
    error_power = float(np.mean(np.square(difference)))
    signal_power = float(np.mean(np.square(reference64)))
    exact = bool(np.array_equal(reference, candidate))
    snr_db: float | None = None
    snr_interpretation: str | None = None
    if error_power == 0.0:
        snr_interpretation = "infinite (zero error)"
    elif signal_power == 0.0:
        snr_interpretation = "negative infinity (zero reference power)"
    else:
        snr_db = float(10.0 * math.log10(signal_power / error_power))
    return {
        "exact_array_equal": exact,
        "max_abs_error": float(np.max(np.abs(difference))) if difference.size else 0.0,
        "rms_error": float(math.sqrt(error_power)),
        "reference_rms": float(math.sqrt(signal_power)),
        "snr_db": snr_db,
        "snr_interpretation": snr_interpretation,
    }


def _segment_non_silence(samples: np.ndarray) -> dict[str, Any]:
    metrics = waveform_metrics(samples)
    failures: list[str] = []
    if not metrics["all_finite"]:
        failures.append("non-finite samples")
    if metrics["rms"] is None or not metrics["rms"] > RMS_THRESHOLD:
        failures.append(f"rms must be > {RMS_THRESHOLD}")
    if metrics["peak_abs"] is None or not metrics["peak_abs"] > PEAK_THRESHOLD:
        failures.append(f"peak_abs must be > {PEAK_THRESHOLD}")
    if metrics["active_fraction"] is None or metrics["active_fraction"] < MIN_ACTIVE_FRACTION:
        failures.append(
            "active_fraction must be >= "
            f"{MIN_ACTIVE_FRACTION} at magnitude > {ACTIVE_MAGNITUDE_THRESHOLD}"
        )
    return {"pass": not failures, "failures": failures, **metrics}


def _base_parameters(
    model: Any,
    *,
    prompt: Prompt,
    negative_prompt: str | None,
    duration: float,
    steps: int,
    cfg_scale: float,
    seed: int,
    batch_size: int,
    sample_size: int | None,
    chunked_decode: bool | None,
) -> dict[str, Any]:
    official = _official_model(model)
    return _generation_parameters(
        prompt=prompt,
        negative_prompt=negative_prompt,
        duration=duration,
        steps=steps,
        cfg_scale=cfg_scale,
        seed=seed,
        batch_size=batch_size,
        sample_size=_sample_size(official, sample_size),
        chunked_decode=chunked_decode,
    )


def _failed_result(
    smoke: str,
    started_at: str,
    *,
    parameters: Mapping[str, Any],
    artifacts: Sequence[AudioArtifact],
    error: BaseException,
) -> SmokeResult:
    return SmokeResult(
        smoke=smoke,
        status="FAIL",
        started_at_utc=started_at,
        ended_at_utc=_utc_now(),
        parameters=dict(parameters),
        checks={"execution_completed": False},
        metrics={},
        artifacts=tuple(artifacts),
        error={
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        },
    )


def run_smoke_a(
    model: Any,
    output_dir: str | os.PathLike[str],
    *,
    prompt: str,
    provenance: ProvenanceContext | Mapping[str, Any],
    negative_prompt: str | None = BASE_NEGATIVE_PROMPT,
    chunked_decode: bool | None = BASE_CHUNKED_DECODE,
    seed: int = SEED_A,
    duration: float = BASE_DURATION_SECONDS,
    steps: int = BASE_STEPS,
    cfg_scale: float = BASE_CFG_SCALE,
    sample_size: int | None = None,
) -> SmokeResult:
    """Run the fixed-seed base path twice and compare reloaded waveform hashes."""

    started = _utc_now()
    artifacts: list[AudioArtifact] = []
    parameters = _base_parameters(
        model,
        prompt=prompt,
        negative_prompt=negative_prompt,
        duration=duration,
        steps=steps,
        cfg_scale=cfg_scale,
        seed=seed,
        batch_size=1,
        sample_size=sample_size,
        chunked_decode=chunked_decode,
    )
    try:
        context = _normalize_provenance_context(provenance)
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        for repetition in (1, 2):
            output = _generate(
                model,
                prompt=prompt,
                negative_prompt=negative_prompt,
                duration=duration,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=seed,
                batch_size=1,
                sample_size=sample_size,
                chunked_decode=chunked_decode,
            )
            generated_artifacts = _write_generated_batch(
                output,
                output_dir=destination,
                stem=f"a_fixed_seed_run{repetition}",
                requested_seconds=duration,
                expected_batch_size=1,
                provenance=context,
                transformation=(
                    f"official fixed-seed text-to-audio decode; repetition {repetition} of 2"
                ),
                smoke="A",
            )
            artifacts.extend(generated_artifacts)
            del output

        first, first_sr = load_float_wav(artifacts[0].path)
        second, second_sr = load_float_wav(artifacts[1].path)
        if first_sr != second_sr:
            raise ValueError("reloaded fixed-seed WAV sample rates differ")
        comparison = _error_metrics(first, second)
        first_hash = artifacts[0].sanity["decoded_waveform_sha256"]
        second_hash = artifacts[1].sanity["decoded_waveform_sha256"]
        hashes_equal = bool(first_hash == second_hash)
        sanity_pass = all(bool(artifact.sanity["pass"]) for artifact in artifacts)
        checks = {
            "both_common_audio_checks_pass": sanity_pass,
            "decoded_waveform_hashes_equal": hashes_equal,
        }
        return SmokeResult(
            smoke="A",
            status="PASS" if all(checks.values()) else "FAIL",
            started_at_utc=started,
            ended_at_utc=_utc_now(),
            parameters=parameters,
            checks=checks,
            metrics={
                "first_decoded_waveform_sha256": first_hash,
                "second_decoded_waveform_sha256": second_hash,
                "waveform_comparison": comparison,
                "diagnostic_closeness_tolerance": {
                    "max_abs_error_lte": 1e-5,
                    "snr_db_gte": 80.0,
                    "hash_mismatch_remains_failure": True,
                },
                "documented_nondeterminism_sources": list(NONDETERMINISM_SOURCES),
            },
            artifacts=tuple(artifacts),
        )
    except Exception as exc:  # noqa: BLE001 - terminal smoke captures engineering failure
        return _failed_result("A", started, parameters=parameters, artifacts=artifacts, error=exc)


def run_smoke_b(
    model: Any,
    source_audio_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    prompt: str,
    provenance: ProvenanceContext | Mapping[str, Any],
    negative_prompt: str | None = BASE_NEGATIVE_PROMPT,
    chunked_decode: bool | None = BASE_CHUNKED_DECODE,
    seed: int = SEED_B,
    duration: float = BASE_DURATION_SECONDS,
    source_duration: float = 10.0,
    steps: int = BASE_STEPS,
    cfg_scale: float = BASE_CFG_SCALE,
    sample_size: int | None = None,
) -> SmokeResult:
    """Derive a 10-second source and exercise official continuation parameters."""

    started = _utc_now()
    artifacts: list[AudioArtifact] = []
    parameters = _base_parameters(
        model,
        prompt=prompt,
        negative_prompt=negative_prompt,
        duration=duration,
        steps=steps,
        cfg_scale=cfg_scale,
        seed=seed,
        batch_size=1,
        sample_size=sample_size,
        chunked_decode=chunked_decode,
    )
    parameters = {
        **parameters,
        "continuation_source_seconds": source_duration,
        "inpaint_mask_start_seconds": source_duration,
        "inpaint_mask_end_seconds": duration,
    }
    try:
        if source_duration <= 0 or source_duration >= duration:
            raise ValueError("source_duration must be positive and shorter than output duration")
        context = _normalize_provenance_context(provenance)
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        parent_path = Path(source_audio_path)
        parent_sanity = audio_sanity(parent_path, duration)
        if not parent_sanity["pass"]:
            raise ValueError("continuation parent failed common 30-second audio checks")
        parent, sample_rate = load_float_wav(parent_path)
        if sample_rate != EXPECTED_SAMPLE_RATE or parent.shape[1] != EXPECTED_CHANNELS:
            raise ValueError("continuation parent must be stereo 44.1 kHz")
        source_frames = round(source_duration * EXPECTED_SAMPLE_RATE)
        source = np.ascontiguousarray(parent[:source_frames])
        if source.shape[0] != source_frames:
            raise ValueError("continuation parent is shorter than the requested source clip")
        parent_id = _artifact_source_id(parent_path)
        source_artifact = _write_audio_artifact(
            destination / "b_source_10s.wav",
            source.T,
            requested_seconds=source_duration,
            label="derived_audio",
            provenance=context,
            transformation=(
                f"deterministic leading {source_duration:g}-second slice of parent WAV"
            ),
            source_ids=(parent_id,),
        )
        artifacts.append(source_artifact)

        import torch

        source_tensor = torch.from_numpy(np.ascontiguousarray(source.T))
        output = _generate(
            model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=duration,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            batch_size=1,
            sample_size=sample_size,
            chunked_decode=chunked_decode,
            inpaint_audio=(sample_rate, source_tensor),
            inpaint_mask_start_seconds=source_duration,
            inpaint_mask_end_seconds=duration,
        )
        continuation_artifacts = _write_generated_batch(
            output,
            output_dir=destination,
            stem="b_continuation_30s",
            requested_seconds=duration,
            expected_batch_size=1,
            provenance=context,
            transformation=(
                "official continuation through inpaint_audio with mask "
                f"[{source_duration:g}, {duration:g}] seconds"
            ),
            smoke="B",
            source_ids=(*context.source_ids, _artifact_source_id(source_artifact.path)),
        )
        artifacts.extend(continuation_artifacts)
        continued, continued_sr = load_float_wav(continuation_artifacts[0].path)
        if continued_sr != sample_rate:
            raise ValueError("continuation output sample rate differs from its source")
        continuation_region = continued[source_frames : round(duration * sample_rate)]
        continuation_sanity = _segment_non_silence(continuation_region)
        prefix_metrics = _error_metrics(source, continued[:source_frames])
        checks = {
            "parent_common_audio_checks_pass": bool(parent_sanity["pass"]),
            "derived_source_common_audio_checks_pass": bool(source_artifact.sanity["pass"]),
            "output_common_audio_checks_pass": bool(continuation_artifacts[0].sanity["pass"]),
            "continuation_region_non_silent": bool(continuation_sanity["pass"]),
            "official_continuation_mask_is_10_to_30_seconds": bool(
                source_duration == 10.0 and duration == 30.0
            ),
        }
        return SmokeResult(
            smoke="B",
            status="PASS" if all(checks.values()) else "FAIL",
            started_at_utc=started,
            ended_at_utc=_utc_now(),
            parameters=parameters,
            checks=checks,
            metrics={
                "continuation_region_sanity": continuation_sanity,
                "prefix_error_diagnostic_only": prefix_metrics,
            },
            artifacts=tuple(artifacts),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed_result("B", started, parameters=parameters, artifacts=artifacts, error=exc)


def _validate_mask_segments(
    segments: Sequence[tuple[float, float]], duration: float
) -> dict[str, Any]:
    failures: list[str] = []
    previous_end = 0.0
    for index, segment in enumerate(segments):
        if len(segment) != 2:
            failures.append(f"segment {index} does not contain start/end")
            continue
        start, end = float(segment[0]), float(segment[1])
        if not (math.isfinite(start) and math.isfinite(end)):
            failures.append(f"segment {index} is non-finite")
        elif not (0.0 <= start < end <= duration):
            failures.append(f"segment {index} is outside [0, {duration}]")
        elif index > 0 and start < previous_end:
            failures.append(f"segment {index} overlaps or is out of order")
        previous_end = end
    if not segments:
        failures.append("at least one segment is required")
    return {
        "pass": not failures,
        "failures": failures,
        "segments_seconds": [[float(start), float(end)] for start, end in segments],
    }


def _masked_error_diagnostics(
    source: np.ndarray,
    repaired: np.ndarray,
    segments: Sequence[tuple[float, float]],
    sample_rate: int,
) -> dict[str, Any]:
    if source.shape != repaired.shape:
        raise ValueError("source and repaired waveform shapes differ")
    masked = np.zeros(source.shape[0], dtype=bool)
    for start, end in segments:
        masked[round(start * sample_rate) : round(end * sample_rate)] = True
    return {
        "masked_region": _error_metrics(source[masked], repaired[masked]),
        "unmasked_region": _error_metrics(source[~masked], repaired[~masked]),
    }


def run_smoke_c(
    model: Any,
    source_audio_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    prompt: str,
    provenance: ProvenanceContext | Mapping[str, Any],
    negative_prompt: str | None = BASE_NEGATIVE_PROMPT,
    chunked_decode: bool | None = BASE_CHUNKED_DECODE,
    duration: float = BASE_DURATION_SECONDS,
    steps: int = BASE_STEPS,
    cfg_scale: float = BASE_CFG_SCALE,
    single_seed: int = SEED_C_SINGLE,
    multi_seed: int = SEED_C_MULTI,
    sample_size: int | None = None,
) -> SmokeResult:
    """Exercise scalar and list forms of the official inpainting API."""

    started = _utc_now()
    artifacts: list[AudioArtifact] = []
    single_segments = ((8.0, 12.0),)
    multi_segments = ((4.0, 6.0), (20.0, 23.0))
    parameters = {
        "official_api": "stable_audio_3.model.StableAudioModel.generate",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "duration_seconds": duration,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_type": BASE_SAMPLER,
        "single": {"seed": single_seed, "segments_seconds": [list(single_segments[0])]},
        "multi": {
            "seed": multi_seed,
            "segments_seconds": [list(segment) for segment in multi_segments],
        },
        "sample_size": _sample_size(_official_model(model), sample_size),
        "chunked_decode": chunked_decode,
    }
    try:
        context = _normalize_provenance_context(provenance)
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        source_path = Path(source_audio_path)
        source_sanity = audio_sanity(source_path, duration)
        if not source_sanity["pass"]:
            raise ValueError("inpainting source failed common audio checks")
        source, sample_rate = load_float_wav(source_path)
        expected_frames = round(duration * EXPECTED_SAMPLE_RATE)
        if sample_rate != EXPECTED_SAMPLE_RATE or source.shape != (
            expected_frames,
            EXPECTED_CHANNELS,
        ):
            raise ValueError("inpainting source must be exactly 30-second stereo 44.1 kHz")
        single_mask_check = _validate_mask_segments(single_segments, duration)
        multi_mask_check = _validate_mask_segments(multi_segments, duration)
        if not single_mask_check["pass"] or not multi_mask_check["pass"]:
            raise ValueError("frozen inpainting mask validation failed")

        import torch

        source_tensor = torch.from_numpy(np.ascontiguousarray(source.T))
        source_id = _artifact_source_id(source_path)
        single_output = _generate(
            model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=duration,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=single_seed,
            batch_size=1,
            sample_size=sample_size,
            chunked_decode=chunked_decode,
            inpaint_audio=(sample_rate, source_tensor),
            inpaint_mask_start_seconds=single_segments[0][0],
            inpaint_mask_end_seconds=single_segments[0][1],
        )
        single_artifacts = _write_generated_batch(
            single_output,
            output_dir=destination,
            stem="c_inpaint_single_8_12s",
            requested_seconds=duration,
            expected_batch_size=1,
            provenance=context,
            transformation="official single-segment inpaint over [8, 12] seconds",
            smoke="C",
            source_ids=(*context.source_ids, source_id),
        )
        artifacts.extend(single_artifacts)
        del single_output

        multi_output = _generate(
            model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=duration,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=multi_seed,
            batch_size=1,
            sample_size=sample_size,
            chunked_decode=chunked_decode,
            inpaint_audio=(sample_rate, source_tensor),
            inpaint_mask_start_seconds=[segment[0] for segment in multi_segments],
            inpaint_mask_end_seconds=[segment[1] for segment in multi_segments],
        )
        multi_artifacts = _write_generated_batch(
            multi_output,
            output_dir=destination,
            stem="c_inpaint_multi_4_6_20_23s",
            requested_seconds=duration,
            expected_batch_size=1,
            provenance=context,
            transformation=("official multi-segment inpaint over [4, 6] and [20, 23] seconds"),
            smoke="C",
            source_ids=(*context.source_ids, source_id),
        )
        artifacts.extend(multi_artifacts)

        single_reloaded, _ = load_float_wav(single_artifacts[0].path)
        multi_reloaded, _ = load_float_wav(multi_artifacts[0].path)
        checks = {
            "source_common_audio_checks_pass": bool(source_sanity["pass"]),
            "single_mask_valid": bool(single_mask_check["pass"]),
            "multi_mask_valid": bool(multi_mask_check["pass"]),
            "single_output_common_audio_checks_pass": bool(single_artifacts[0].sanity["pass"]),
            "multi_output_common_audio_checks_pass": bool(multi_artifacts[0].sanity["pass"]),
        }
        return SmokeResult(
            smoke="C",
            status="PASS" if all(checks.values()) else "FAIL",
            started_at_utc=started,
            ended_at_utc=_utc_now(),
            parameters=parameters,
            checks=checks,
            metrics={
                "single_mask_validation": single_mask_check,
                "multi_mask_validation": multi_mask_check,
                "single_error_diagnostic_only": _masked_error_diagnostics(
                    source, single_reloaded, single_segments, sample_rate
                ),
                "multi_error_diagnostic_only": _masked_error_diagnostics(
                    source, multi_reloaded, multi_segments, sample_rate
                ),
            },
            artifacts=tuple(artifacts),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed_result("C", started, parameters=parameters, artifacts=artifacts, error=exc)


def _cuda_device(official: Any, torch_module: Any) -> Any:
    configured = getattr(official, "device", "cuda")
    device = torch_module.device(configured)
    if device.type != "cuda":
        raise RuntimeError(f"cost smoke requires one CUDA GPU, got {device}")
    if not torch_module.cuda.is_available():
        raise RuntimeError("cost smoke requires CUDA, but torch.cuda.is_available() is false")
    return device


def _diffusion_backbone(official: Any) -> Any:
    backbone = getattr(official, "dit", None)
    if backbone is None:
        conditioned = getattr(official, "model", None)
        backbone = getattr(conditioned, "model", None)
    if not callable(getattr(backbone, "register_forward_pre_hook", None)):
        raise TypeError("could not locate the official diffusion backbone for NFE measurement")
    return backbone


def _measure_cuda_generation(
    model: Any,
    *,
    prompt: Prompt,
    negative_prompt: str | None,
    duration: float,
    steps: int,
    cfg_scale: float,
    seed: int,
    batch_size: int,
    sample_size: int | None,
    chunked_decode: bool | None,
) -> tuple[Any, dict[str, Any]]:
    import torch

    official = _official_model(model)
    device = _cuda_device(official, torch)
    backbone = _diffusion_backbone(official)
    counts = {"backbone_forward_calls": 0, "sampler_callback_calls": 0}
    callback_step_indices: list[int] = []

    def count_forward(_module: Any, _inputs: Any) -> None:
        counts["backbone_forward_calls"] += 1

    def count_callback(info: Mapping[str, Any]) -> None:
        counts["sampler_callback_calls"] += 1
        index = info.get("i")
        callback_step_indices.append(int(index) if index is not None else -1)

    hook = backbone.register_forward_pre_hook(count_forward)
    try:
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        baseline_allocated = int(torch.cuda.memory_allocated(device))
        baseline_reserved = int(torch.cuda.memory_reserved(device))
        start = time.perf_counter()
        output = _generate(
            official,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=duration,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            batch_size=batch_size,
            sample_size=sample_size,
            chunked_decode=chunked_decode,
            callback=count_callback,
        )
        torch.cuda.synchronize(device)
        wall_seconds = float(time.perf_counter() - start)
        peak_allocated = int(torch.cuda.max_memory_allocated(device))
        peak_reserved = int(torch.cuda.max_memory_reserved(device))
    finally:
        hook.remove()

    metrics = {
        **counts,
        "sampler_callback_step_indices": callback_step_indices,
        "wall_seconds": wall_seconds,
        "cuda_device": str(device),
        "cuda_device_name": str(torch.cuda.get_device_name(device)),
        "baseline_allocated_bytes": baseline_allocated,
        "baseline_reserved_bytes": baseline_reserved,
        "peak_allocated_bytes": peak_allocated,
        "peak_reserved_bytes": peak_reserved,
        "incremental_peak_allocated_bytes": max(0, peak_allocated - baseline_allocated),
        "incremental_peak_reserved_bytes": max(0, peak_reserved - baseline_reserved),
        "timing_scope": (
            "end-to-end StableAudioModel.generate on an already-loaded model, including "
            "conditioning, diffusion, and decode; CUDA synchronized at both boundaries"
        ),
        "nfe_count_scope": (
            "Python forward-pre-hooks on the DiTWrapper passed by StableAudioModel.generate "
            "to sample_diffusion"
        ),
    }
    return output, metrics


def _positive_measurement_fields(metrics: Mapping[str, Any]) -> bool:
    fields = (
        "backbone_forward_calls",
        "sampler_callback_calls",
        "wall_seconds",
        "peak_allocated_bytes",
        "peak_reserved_bytes",
    )
    return all(
        isinstance(metrics.get(field), (int, float))
        and not isinstance(metrics.get(field), bool)
        and metrics[field] > 0
        for field in fields
    )


def run_smoke_d(
    model: Any,
    output_dir: str | os.PathLike[str],
    *,
    prompt: str,
    provenance: ProvenanceContext | Mapping[str, Any],
    negative_prompt: str | None = BASE_NEGATIVE_PROMPT,
    chunked_decode: bool | None = BASE_CHUNKED_DECODE,
    batch4_prompts: Sequence[str] = BASE_BATCH4_PROMPTS,
    batch1_seed: int = SEED_D_BATCH1,
    batch4_seed: int = SEED_D_BATCH4,
    steps: int = BASE_STEPS,
    cfg_scale: float = BASE_CFG_SCALE,
    sample_size: int | None = None,
) -> SmokeResult:
    """Measure the D-0014 batch-one cost and batch-four throughput calls."""

    started = _utc_now()
    artifacts: list[AudioArtifact] = []
    parameters = {
        "official_api": "stable_audio_3.model.StableAudioModel.generate",
        "base_prompt": prompt,
        "negative_prompt": negative_prompt,
        "sampler_type": BASE_SAMPLER,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "batch1": {
            "seed": batch1_seed,
            "batch_size": 1,
            "duration_seconds": BASE_DURATION_SECONDS,
        },
        "batch4": {
            "seed": batch4_seed,
            "batch_size": 4,
            "duration_seconds": 10.0,
            "prompts": list(batch4_prompts),
        },
        "sample_size": _sample_size(_official_model(model), sample_size),
        "chunked_decode": chunked_decode,
    }
    try:
        context = _normalize_provenance_context(provenance)
        if (
            isinstance(batch4_prompts, (str, bytes))
            or len(batch4_prompts) != 4
            or any(not isinstance(value, str) or not value.strip() for value in batch4_prompts)
        ):
            raise ValueError("batch4_prompts must contain exactly four non-empty prompts")
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        batch1_output, batch1_metrics = _measure_cuda_generation(
            model,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration=BASE_DURATION_SECONDS,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=batch1_seed,
            batch_size=1,
            sample_size=sample_size,
            chunked_decode=chunked_decode,
        )
        batch1_artifacts = _write_generated_batch(
            batch1_output,
            output_dir=destination,
            stem="d_cost_batch1_30s",
            requested_seconds=BASE_DURATION_SECONDS,
            expected_batch_size=1,
            provenance=context,
            transformation="instrumented official 50-step Euler batch-one text-to-audio decode",
            smoke="D",
        )
        artifacts.extend(batch1_artifacts)
        del batch1_output

        batch4_output, batch4_metrics = _measure_cuda_generation(
            model,
            prompt=list(batch4_prompts),
            negative_prompt=negative_prompt,
            duration=10.0,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=batch4_seed,
            batch_size=4,
            sample_size=sample_size,
            chunked_decode=chunked_decode,
        )
        wall_seconds = batch4_metrics["wall_seconds"]
        batch4_metrics = {
            **batch4_metrics,
            "items_per_second": float(4.0 / wall_seconds),
            "generated_audio_seconds_per_second": float(40.0 / wall_seconds),
        }
        batch4_artifacts = _write_generated_batch(
            batch4_output,
            output_dir=destination,
            stem="d_throughput_batch4_10s",
            requested_seconds=10.0,
            expected_batch_size=4,
            provenance=context,
            transformation="instrumented official 50-step Euler batch-four text-to-audio decode",
            smoke="D",
        )
        artifacts.extend(batch4_artifacts)

        batch1_sanity = all(bool(item.sanity["pass"]) for item in batch1_artifacts)
        batch4_sanity = all(bool(item.sanity["pass"]) for item in batch4_artifacts)
        batch4_throughput_positive = bool(
            batch4_metrics["items_per_second"] > 0
            and batch4_metrics["generated_audio_seconds_per_second"] > 0
        )
        expected_step_indices = list(range(steps))
        checks = {
            "batch1_measured_fields_positive": _positive_measurement_fields(batch1_metrics),
            "batch1_backbone_forward_calls_equal_steps": bool(
                batch1_metrics["backbone_forward_calls"] == steps
            ),
            "batch1_sampler_callbacks_equal_steps": bool(
                batch1_metrics["sampler_callback_calls"] == steps
                and batch1_metrics["sampler_callback_step_indices"] == expected_step_indices
            ),
            "batch1_common_audio_checks_pass": batch1_sanity,
            "batch4_measured_fields_positive": _positive_measurement_fields(batch4_metrics),
            "batch4_backbone_forward_calls_equal_steps": bool(
                batch4_metrics["backbone_forward_calls"] == steps
            ),
            "batch4_sampler_callbacks_equal_steps": bool(
                batch4_metrics["sampler_callback_calls"] == steps
                and batch4_metrics["sampler_callback_step_indices"] == expected_step_indices
            ),
            "batch4_throughput_positive": batch4_throughput_positive,
            "batch4_has_four_valid_outputs": bool(len(batch4_artifacts) == 4 and batch4_sanity),
        }
        return SmokeResult(
            smoke="D",
            status="PASS" if all(checks.values()) else "FAIL",
            started_at_utc=started,
            ended_at_utc=_utc_now(),
            parameters=parameters,
            checks=checks,
            metrics={"batch1": batch1_metrics, "batch4": batch4_metrics},
            artifacts=tuple(artifacts),
        )
    except Exception as exc:  # noqa: BLE001
        return _failed_result("D", started, parameters=parameters, artifacts=artifacts, error=exc)


__all__ = [
    "AudioArtifact",
    "BASE_BATCH4_PROMPTS",
    "BASE_CHUNKED_DECODE",
    "BASE_CFG_SCALE",
    "BASE_DURATION_SECONDS",
    "BASE_NEGATIVE_PROMPT",
    "BASE_SAMPLER",
    "BASE_STEPS",
    "ProvenanceContext",
    "SmokeResult",
    "run_smoke_a",
    "run_smoke_b",
    "run_smoke_c",
    "run_smoke_d",
]

"""Canonical WAV retention, hashing, and frozen-protocol sanity checks."""

from __future__ import annotations

import io
import math
import os
import struct
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from sa3_smoke.artifacts import (
    ProvenanceValidationError,
    adjacent_provenance_path,
    exclusive_write_bytes,
    sha256_file,
    validate_adjacent_provenance,
)

EXPECTED_SAMPLE_RATE = 44_100
EXPECTED_CHANNELS = 2
RMS_THRESHOLD = 1e-5
PEAK_THRESHOLD = 1e-4
ACTIVE_MAGNITUDE_THRESHOLD = 1e-4
MIN_ACTIVE_FRACTION = 0.001
_WAVEFORM_HASH_DOMAIN = b"sa3-decoded-waveform-v1\0"


def _little_endian_float32(samples: np.ndarray | Any) -> np.ndarray:
    array = np.asarray(samples, dtype=np.dtype("<f4"))
    return np.ascontiguousarray(array)


def canonical_waveform_sha256(samples: np.ndarray | Any, sample_rate: int) -> str:
    """Hash sample rate, tensor shape, and contiguous little-endian float32 bytes.

    Shape is preserved exactly; callers should hash the frame-major array
    returned by :func:`load_float_wav` when comparing retained outputs.
    """

    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)):
        raise TypeError("sample_rate must be an integer")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    array = _little_endian_float32(samples)

    import hashlib

    digest = hashlib.sha256()
    digest.update(_WAVEFORM_HASH_DOMAIN)
    digest.update(struct.pack("<Q", int(sample_rate)))
    digest.update(struct.pack("<Q", array.ndim))
    for dimension in array.shape:
        digest.update(struct.pack("<Q", dimension))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def save_float_wav_exclusive(
    path: str | os.PathLike[str],
    samples: np.ndarray | Any,
    sample_rate: int = EXPECTED_SAMPLE_RATE,
    *,
    channels_first: bool = False,
) -> Path:
    """Retain a 32-bit float WAV without replacing an existing artifact.

    Inputs are frame-major by default (``frames, channels``), matching
    ``soundfile`` and :func:`load_float_wav`.  Set ``channels_first=True`` only
    for an explicit ``channels, frames`` array.  Serialization completes in
    memory before the destination is created, so encoder failures cannot leave
    a partial named artifact.
    """

    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)):
        raise TypeError("sample_rate must be an integer")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    array = _little_endian_float32(samples)
    if array.ndim not in (1, 2):
        raise ValueError("samples must have shape (frames,) or (frames, channels)")
    if channels_first:
        if array.ndim != 2:
            raise ValueError("channels_first requires a two-dimensional array")
        array = np.ascontiguousarray(array.T)
    if array.shape[0] == 0:
        raise ValueError("cannot write an empty WAV")

    buffer = io.BytesIO()
    sf.write(buffer, array, int(sample_rate), format="WAV", subtype="FLOAT")
    return exclusive_write_bytes(path, buffer.getvalue())


def load_float_wav(path: str | os.PathLike[str]) -> tuple[np.ndarray, int]:
    """Decode a WAV as frame-major contiguous float32 and return ``(data, sr)``."""

    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    return _little_endian_float32(samples), int(sample_rate)


def waveform_metrics(samples: np.ndarray | Any) -> dict[str, Any]:
    """Measure JSON-safe engineering metrics for a decoded waveform."""

    array = _little_endian_float32(samples)
    if array.ndim not in (1, 2):
        raise ValueError("samples must be one- or two-dimensional")
    flat = array.reshape(-1)
    finite = bool(np.isfinite(flat).all())

    result: dict[str, Any] = {
        "all_finite": finite,
        "rms": None,
        "peak_abs": None,
        "active_fraction": None,
        "clipping_fraction": None,
        "dc_offset": None,
        "dc_offset_per_channel": None,
    }
    if flat.size == 0 or not finite:
        return result

    values = flat.astype(np.float64, copy=False)
    absolute = np.abs(values)
    result.update(
        {
            "rms": float(math.sqrt(float(np.mean(np.square(values))))),
            "peak_abs": float(np.max(absolute)),
            "active_fraction": float(np.mean(absolute > ACTIVE_MAGNITUDE_THRESHOLD)),
            "clipping_fraction": float(np.mean(absolute >= 1.0)),
            "dc_offset": float(np.mean(values)),
        }
    )
    channel_view = array[:, None] if array.ndim == 1 else array
    result["dc_offset_per_channel"] = [
        float(value) for value in np.mean(channel_view.astype(np.float64), axis=0)
    ]
    return result


def _failure(check: str, expected: str, observed: Any) -> dict[str, Any]:
    return {"check": check, "expected": expected, "observed": observed}


def audio_sanity(
    path: str | os.PathLike[str],
    requested_seconds: float,
    *,
    expected_sample_rate: int = EXPECTED_SAMPLE_RATE,
    expected_channels: int = EXPECTED_CHANNELS,
    require_provenance: bool = True,
) -> dict[str, Any]:
    """Apply every common audio check frozen in ``SMOKE_PROTOCOL.md``.

    The named WAV is always decoded back from disk.  Validation failures are
    represented in the returned strict-JSON-compatible dictionary rather than
    raised; invalid function arguments still raise normally.
    """

    if isinstance(requested_seconds, bool) or not isinstance(
        requested_seconds, (int, float, np.integer, np.floating)
    ):
        raise TypeError("requested_seconds must be a finite positive number")
    requested_seconds_float = float(requested_seconds)
    if not math.isfinite(requested_seconds_float) or requested_seconds_float <= 0:
        raise ValueError("requested_seconds must be a finite positive number")
    if (
        isinstance(expected_sample_rate, bool)
        or not isinstance(expected_sample_rate, int)
        or expected_sample_rate <= 0
    ):
        raise ValueError("expected_sample_rate must be a positive integer")
    if (
        isinstance(expected_channels, bool)
        or not isinstance(expected_channels, int)
        or expected_channels <= 0
    ):
        raise ValueError("expected_channels must be a positive integer")

    artifact = Path(path)
    expected_sample_count = round(requested_seconds_float * expected_sample_rate)
    failures: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "path": str(artifact),
        "pass": False,
        "failures": failures,
        "requested_seconds": requested_seconds_float,
        "expected_sample_rate": expected_sample_rate,
        "expected_channels": expected_channels,
        "expected_sample_count": expected_sample_count,
        "sample_rate": None,
        "channels": None,
        "sample_count": None,
        "duration_seconds": None,
        "all_finite": None,
        "rms": None,
        "peak_abs": None,
        "active_fraction": None,
        "clipping_fraction": None,
        "dc_offset": None,
        "dc_offset_per_channel": None,
        "file_sha256": None,
        "decoded_waveform_sha256": None,
        "provenance": {
            "required": require_provenance,
            "path": str(adjacent_provenance_path(artifact)),
            "valid": None,
            "error": None,
        },
    }

    try:
        result["file_sha256"] = sha256_file(artifact)
    except (OSError, ValueError) as exc:
        failures.append(_failure("file_readable", "readable artifact file", str(exc)))

    try:
        samples, sample_rate = load_float_wav(artifact)
    except (OSError, RuntimeError, ValueError) as exc:
        failures.append(_failure("decoding", "successful WAV decode", str(exc)))
    else:
        sample_count, channels = samples.shape
        metrics = waveform_metrics(samples)
        result.update(metrics)
        result.update(
            {
                "sample_rate": sample_rate,
                "channels": channels,
                "sample_count": sample_count,
                "duration_seconds": float(sample_count / sample_rate) if sample_rate > 0 else None,
                "decoded_waveform_sha256": canonical_waveform_sha256(samples, sample_rate),
            }
        )

        if not metrics["all_finite"]:
            failures.append(_failure("all_finite", "all samples finite", False))
        if sample_rate != expected_sample_rate:
            failures.append(_failure("sample_rate", expected_sample_rate, sample_rate))
        if channels != expected_channels:
            failures.append(_failure("channels", expected_channels, channels))
        if sample_count != expected_sample_count:
            failures.append(_failure("sample_count", expected_sample_count, sample_count))

        rms = metrics["rms"]
        peak_abs = metrics["peak_abs"]
        active_fraction = metrics["active_fraction"]
        if rms is None or not rms > RMS_THRESHOLD:
            failures.append(_failure("rms", f"> {RMS_THRESHOLD}", rms))
        if peak_abs is None or not peak_abs > PEAK_THRESHOLD:
            failures.append(_failure("peak_abs", f"> {PEAK_THRESHOLD}", peak_abs))
        if active_fraction is None or active_fraction < MIN_ACTIVE_FRACTION:
            failures.append(
                _failure("active_fraction", f">= {MIN_ACTIVE_FRACTION}", active_fraction)
            )

    provenance_result = result["provenance"]
    if require_provenance:
        try:
            validate_adjacent_provenance(artifact)
        except (ProvenanceValidationError, OSError, ValueError) as exc:
            provenance_result["valid"] = False
            provenance_result["error"] = str(exc)
            failures.append(_failure("provenance", "valid adjacent provenance", str(exc)))
        else:
            provenance_result["valid"] = True
    else:
        provenance_result["valid"] = None

    result["pass"] = not failures
    return result

"""CPU-only tests for retained float WAVs and frozen audio acceptance checks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sa3_smoke.artifacts import write_adjacent_provenance
from sa3_smoke.audio import (
    EXPECTED_SAMPLE_RATE,
    audio_sanity,
    canonical_waveform_sha256,
    load_float_wav,
    save_float_wav_exclusive,
    waveform_metrics,
)


def stereo_tone(seconds: float, sample_rate: int = EXPECTED_SAMPLE_RATE) -> np.ndarray:
    frames = round(seconds * sample_rate)
    time = np.arange(frames, dtype=np.float64) / sample_rate
    left = 0.1 * np.sin(2 * np.pi * 440.0 * time)
    right = 0.08 * np.sin(2 * np.pi * 660.0 * time)
    return np.column_stack((left, right)).astype(np.float32)


def attach_provenance(path: Path) -> None:
    write_adjacent_provenance(
        path,
        {
            "label": "synthetic_model_output",
            "created_at_utc": "2026-07-19T12:00:00+00:00",
            "creating_command": "pytest fixture",
            "run_id": "unit-test-run",
            "source_ids": ["unit-test-model@fixed-revision"],
            "model_revision": "fixed-revision",
            "license_identifier": "test-only",
            "transformation": "deterministic test tone",
        },
    )


def test_canonical_hash_covers_rate_shape_and_canonical_float_bytes() -> None:
    base = np.arange(6, dtype=np.float32).reshape(2, 3)
    canonical = canonical_waveform_sha256(base, 44_100)

    assert canonical_waveform_sha256(base.astype(">f4"), 44_100) == canonical
    assert canonical_waveform_sha256(np.asfortranarray(base), 44_100) == canonical
    assert canonical_waveform_sha256(base.astype(np.float64), 44_100) == canonical
    assert canonical_waveform_sha256(base, 48_000) != canonical
    assert canonical_waveform_sha256(base.reshape(3, 2), 44_100) != canonical
    changed = base.copy()
    changed[0, 0] = 0.25
    assert canonical_waveform_sha256(changed, 44_100) != canonical
    with pytest.raises(ValueError, match="positive"):
        canonical_waveform_sha256(base, 0)


def test_float_wav_is_retained_reloaded_and_validated(tmp_path: Path) -> None:
    seconds = 0.02
    original = stereo_tone(seconds)
    wav = tmp_path / "tone.wav"
    save_float_wav_exclusive(wav, original)
    attach_provenance(wav)

    info = sf.info(wav)
    reloaded, sample_rate = load_float_wav(wav)
    result = audio_sanity(wav, seconds)

    assert info.format == "WAV"
    assert info.subtype == "FLOAT"
    assert sample_rate == EXPECTED_SAMPLE_RATE
    np.testing.assert_array_equal(reloaded, original)
    assert result["pass"] is True
    assert result["provenance"]["valid"] is True
    assert result["sample_count"] == round(seconds * EXPECTED_SAMPLE_RATE)
    assert result["channels"] == 2
    assert result["decoded_waveform_sha256"] == canonical_waveform_sha256(reloaded, sample_rate)
    assert result["clipping_fraction"] == 0.0
    assert isinstance(result["dc_offset_per_channel"], list)
    json.dumps(result, allow_nan=False)


def test_wav_writer_accepts_explicit_channels_first_and_never_clobbers(
    tmp_path: Path,
) -> None:
    frame_major = stereo_tone(0.01)
    wav = tmp_path / "channels-first.wav"
    save_float_wav_exclusive(wav, frame_major.T, channels_first=True)
    with pytest.raises(FileExistsError):
        save_float_wav_exclusive(wav, frame_major)
    reloaded, _ = load_float_wav(wav)
    np.testing.assert_array_equal(reloaded, frame_major)


def test_silence_wrong_layout_rate_and_duration_fail_exact_checks(tmp_path: Path) -> None:
    wav = tmp_path / "invalid.wav"
    save_float_wav_exclusive(wav, np.zeros((100, 1), dtype=np.float32), 48_000)
    result = audio_sanity(wav, 0.01, require_provenance=False)
    failed_checks = {failure["check"] for failure in result["failures"]}

    assert result["pass"] is False
    assert {
        "sample_rate",
        "channels",
        "sample_count",
        "rms",
        "peak_abs",
        "active_fraction",
    }.issubset(failed_checks)
    assert result["provenance"]["valid"] is None
    json.dumps(result, allow_nan=False)


def test_nonfinite_samples_and_missing_provenance_fail(tmp_path: Path) -> None:
    samples = stereo_tone(0.01)
    samples[3, 1] = np.nan
    wav = tmp_path / "nonfinite.wav"
    save_float_wav_exclusive(wav, samples)

    result = audio_sanity(wav, 0.01)
    failed_checks = {failure["check"] for failure in result["failures"]}
    assert "all_finite" in failed_checks
    assert "provenance" in failed_checks
    assert result["rms"] is None
    assert result["provenance"]["valid"] is False
    json.dumps(result, allow_nan=False)


def test_corrupt_wav_reports_decode_failure_as_json(tmp_path: Path) -> None:
    wav = tmp_path / "corrupt.wav"
    wav.write_bytes(b"not a wav")
    result = audio_sanity(wav, 0.01, require_provenance=False)

    assert result["pass"] is False
    assert "decoding" in {failure["check"] for failure in result["failures"]}
    assert result["file_sha256"] is not None
    json.dumps(result, allow_nan=False)


def test_waveform_metrics_measure_clipping_and_dc_without_acceptance_side_effects() -> None:
    samples = np.array([[1.0, -1.0], [0.5, -0.25]], dtype=np.float32)
    metrics = waveform_metrics(samples)
    assert metrics["all_finite"] is True
    assert metrics["clipping_fraction"] == 0.5
    assert metrics["dc_offset_per_channel"] == [0.75, -0.625]


@pytest.mark.parametrize("seconds", [0, -1.0, float("nan"), float("inf")])
def test_invalid_requested_duration_is_rejected(tmp_path: Path, seconds: float) -> None:
    with pytest.raises(ValueError):
        audio_sanity(tmp_path / "unused.wav", seconds)

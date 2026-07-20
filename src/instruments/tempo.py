"""Frozen Beat This!/librosa tempo aggregation and tolerance rules."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

BEAT_THIS_REPOSITORY = "https://github.com/CPJKU/beat_this"
BEAT_THIS_VERSION = "1.1.0"
BEAT_THIS_COMMIT = "ad7974846029835307ba19a3d5cefbf40b243041"
BEAT_THIS_CHECKPOINT_NAME = "final0"
BEAT_THIS_CHECKPOINT_SHA256 = "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"
BEAT_THIS_POSTPROCESSOR = "minimal"
LIBROSA_VERSION = "0.11.0"

OCTAVE_SHIFTS = (-2, -1, 0, 1, 2)
PRIMARY_TOLERANCE = 0.05
SENSITIVITY_TOLERANCE = 0.10
ESTIMATOR_DISAGREEMENT_TOLERANCE = 0.08
WINDOW_DRIFT_REPLAY_TOLERANCE = 0.08


@dataclass(frozen=True)
class TempoEstimate:
    estimator: str
    valid: bool
    bpm: float | None
    event_count: int
    median_interval_seconds: float | None
    interval_iqr_fraction: float | None
    invalid_reason: str | None


@dataclass(frozen=True)
class TempoResolution:
    status: str
    consensus_bpm: float | None
    beat_this_aligned_bpm: float | None
    librosa_aligned_bpm: float | None
    disagreement_octaves: float | None
    octave_invariant_error: float
    raw_absolute_percentage_error: float
    primary_5pct_success: bool
    sensitivity_10pct_success: bool


@dataclass(frozen=True)
class TempoWindowResolution:
    first_window: TempoResolution
    second_window: TempoResolution
    signed_drift_octaves: float
    octave_invariant_absolute_drift: float


@dataclass(frozen=True)
class WindowDrift:
    valid: bool
    first_window_bpm: float | None
    second_window_bpm: float | None
    second_aligned_to_first_bpm: float | None
    first_target_error: float
    second_target_error: float
    signed_drift_octaves: float
    between_window_octave_error: float
    between_window_fractional_drift: float
    replay_required: bool
    invalid_reason: str | None


def validate_evaluator_pins(
    *,
    beat_this_commit: str,
    beat_this_checkpoint_sha256: str,
    librosa_version: str,
) -> None:
    """Reject a runtime that does not match the frozen evaluator pair."""

    if beat_this_commit != BEAT_THIS_COMMIT:
        raise RuntimeError("Beat This! implementation commit does not match the frozen pin")
    if beat_this_checkpoint_sha256 != BEAT_THIS_CHECKPOINT_SHA256:
        raise RuntimeError("Beat This! checkpoint SHA-256 does not match the frozen pin")
    if librosa_version != LIBROSA_VERSION:
        raise RuntimeError("librosa version does not match the frozen pin")


def _invalid(estimator: str, event_count: int, reason: str) -> TempoEstimate:
    return TempoEstimate(estimator, False, None, event_count, None, None, reason)


def _validated_estimate(
    estimator: str,
    events_seconds: Iterable[float],
    *,
    candidate_bpm: float | None,
) -> TempoEstimate:
    events = np.asarray(tuple(events_seconds), dtype=np.float64)
    count = int(events.size)
    if events.ndim != 1:
        return _invalid(estimator, count, "EVENTS_NOT_ONE_DIMENSIONAL")
    if count < 8:
        return _invalid(estimator, count, "FEWER_THAN_8_EVENTS")
    if not np.isfinite(events).all():
        return _invalid(estimator, count, "NONFINITE_EVENT")
    intervals = np.diff(events)
    if (intervals <= 0.0).any():
        return _invalid(estimator, count, "EVENTS_NOT_STRICTLY_INCREASING")
    median_interval = float(np.median(intervals))
    quartiles = np.quantile(intervals, (0.25, 0.75), method="linear")
    iqr_fraction = float((quartiles[1] - quartiles[0]) / median_interval)
    bpm = 60.0 / median_interval if candidate_bpm is None else float(candidate_bpm)
    if not math.isfinite(bpm) or not 30.0 <= bpm <= 300.0:
        return _invalid(estimator, count, "BPM_OUTSIDE_30_300")
    if iqr_fraction > 0.25:
        return TempoEstimate(
            estimator,
            False,
            None,
            count,
            median_interval,
            iqr_fraction,
            "INTERVAL_IQR_EXCEEDS_25PCT_MEDIAN",
        )
    return TempoEstimate(
        estimator,
        True,
        bpm,
        count,
        median_interval,
        iqr_fraction,
        None,
    )


def beat_this_estimate(beat_times_seconds: Iterable[float]) -> TempoEstimate:
    """Derive Beat This! BPM from its minimal-postprocessor beat events."""

    return _validated_estimate("beat_this", beat_times_seconds, candidate_bpm=None)


def librosa_estimate(
    tempo_bpm: float,
    beat_frames: Iterable[int],
    *,
    sample_rate: int,
    hop_length: int,
) -> TempoEstimate:
    """Validate librosa's scalar tempo using its retained beat-frame sequence."""

    if sample_rate <= 0 or hop_length <= 0:
        raise ValueError("sample_rate and hop_length must be positive")
    frames = np.asarray(tuple(beat_frames), dtype=np.float64)
    events_seconds = frames * float(hop_length) / float(sample_rate)
    return _validated_estimate("librosa", events_seconds, candidate_bpm=tempo_bpm)


def octave_invariant_error(bpm: float, target_bpm: float) -> float:
    """Return the frozen five-shift octave-invariant absolute log2 error."""

    if not math.isfinite(bpm) or not math.isfinite(target_bpm) or bpm <= 0 or target_bpm <= 0:
        return math.inf
    ratio = math.log2(bpm / target_bpm)
    return min(abs(ratio - shift) for shift in OCTAVE_SHIFTS)


def align_to_target(bpm: float, target_bpm: float) -> tuple[float, int]:
    """Apply the frozen ``(error, |k|, k)`` deterministic tie break."""

    ratio = math.log2(bpm / target_bpm)
    shift = min(OCTAVE_SHIFTS, key=lambda value: (abs(ratio - value), abs(value), value))
    return bpm / (2.0**shift), shift


def _unresolved(status: str, disagreement: float | None) -> TempoResolution:
    return TempoResolution(
        status=status,
        consensus_bpm=None,
        beat_this_aligned_bpm=None,
        librosa_aligned_bpm=None,
        disagreement_octaves=disagreement,
        octave_invariant_error=math.inf,
        raw_absolute_percentage_error=math.inf,
        primary_5pct_success=False,
        sensitivity_10pct_success=False,
    )


def resolve_tempo(
    target_bpm: float,
    beat_this: TempoEstimate,
    librosa: TempoEstimate,
) -> TempoResolution:
    """Apply the frozen disagreement rule, then both preregistered bands."""

    target = float(target_bpm)
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError("target_bpm must be finite and positive")
    if not beat_this.valid or not librosa.valid:
        return _unresolved("ESTIMATOR_INVALID", None)
    assert beat_this.bpm is not None
    assert librosa.bpm is not None
    disagreement = octave_invariant_error(beat_this.bpm, librosa.bpm)
    if disagreement > math.log2(1.0 + ESTIMATOR_DISAGREEMENT_TOLERANCE):
        return _unresolved("ESTIMATOR_DISAGREEMENT", disagreement)
    aligned_bt, _ = align_to_target(beat_this.bpm, target)
    aligned_librosa, _ = align_to_target(librosa.bpm, target)
    consensus = math.sqrt(aligned_bt * aligned_librosa)
    error = octave_invariant_error(consensus, target)
    raw_ape = abs(consensus / target - 1.0)
    return TempoResolution(
        status="RESOLVED",
        consensus_bpm=consensus,
        beat_this_aligned_bpm=aligned_bt,
        librosa_aligned_bpm=aligned_librosa,
        disagreement_octaves=disagreement,
        octave_invariant_error=error,
        raw_absolute_percentage_error=raw_ape,
        primary_5pct_success=error <= math.log2(1.0 + PRIMARY_TOLERANCE),
        sensitivity_10pct_success=error <= math.log2(1.0 + SENSITIVITY_TOLERANCE),
    )


def resolve_tempo_windows(
    target_bpm: float,
    *,
    first_beat_this: TempoEstimate,
    first_librosa: TempoEstimate,
    second_beat_this: TempoEstimate,
    second_librosa: TempoEstimate,
) -> TempoWindowResolution:
    """Resolve FIRST/SECOND estimator pairs without averaging away drift."""

    first = resolve_tempo(target_bpm, first_beat_this, first_librosa)
    second = resolve_tempo(target_bpm, second_beat_this, second_librosa)
    if first.consensus_bpm is None or second.consensus_bpm is None:
        return TempoWindowResolution(first, second, math.nan, math.inf)
    signed = math.log2(second.consensus_bpm / first.consensus_bpm)
    absolute = min(abs(signed - shift) for shift in OCTAVE_SHIFTS)
    return TempoWindowResolution(first, second, signed, absolute)


def evaluate_window_drift(
    target_bpm: float,
    first_window_taps_seconds: Iterable[float],
    second_window_taps_seconds: Iterable[float],
) -> WindowDrift:
    """Report the two tapping-window errors and their drift as separate fields."""

    target = float(target_bpm)
    if not math.isfinite(target) or target <= 0.0:
        raise ValueError("target_bpm must be finite and positive")
    first = _validated_estimate("human_first_window", first_window_taps_seconds, candidate_bpm=None)
    second = _validated_estimate(
        "human_second_window", second_window_taps_seconds, candidate_bpm=None
    )
    if not first.valid or not second.valid:
        reasons = [estimate.invalid_reason for estimate in (first, second) if not estimate.valid]
        return WindowDrift(
            False,
            first.bpm,
            second.bpm,
            None,
            octave_invariant_error(first.bpm or math.nan, target),
            octave_invariant_error(second.bpm or math.nan, target),
            math.nan,
            math.inf,
            math.inf,
            False,
            ";".join(str(reason) for reason in reasons),
        )
    assert first.bpm is not None
    assert second.bpm is not None
    aligned_second, _ = align_to_target(second.bpm, first.bpm)
    signed_drift = math.log2(second.bpm / first.bpm)
    between_error = octave_invariant_error(second.bpm, first.bpm)
    fractional_drift = abs(aligned_second / first.bpm - 1.0)
    return WindowDrift(
        True,
        first.bpm,
        second.bpm,
        aligned_second,
        octave_invariant_error(first.bpm, target),
        octave_invariant_error(second.bpm, target),
        signed_drift,
        between_error,
        fractional_drift,
        between_error > math.log2(1.0 + WINDOW_DRIFT_REPLAY_TOLERANCE),
        None,
    )

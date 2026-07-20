"""Objective acoustic-integrity DSP on decoded, unnormalized float audio."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.signal import resample_poly

DEFECT_NAMES = ("clipping", "dropout", "silence", "crackle")
TRUE_PEAK_OVERSAMPLE = 4
TRUE_PEAK_FILTER_HALF_LEN = 10 * TRUE_PEAK_OVERSAMPLE
HARD_CLIPPED_FRACTION_THRESHOLD = 0.001
HARD_CLIPPED_FRACTION_EFFECTIVE_THRESHOLD = math.nextafter(
    HARD_CLIPPED_FRACTION_THRESHOLD, math.inf
)
HARD_CLIP_RUN_THRESHOLD_SAMPLES = 3
TRUE_PEAK_THRESHOLD = 1.0
DROPOUT_DURATION_THRESHOLD_MS = 50.0
DROPOUT_BOUNDARY_THRESHOLD_MS = 250.0
DROPOUT_FLANK_LEVEL_THRESHOLD_DBFS = -40.0
DROPOUT_FLANK_LEVEL_EFFECTIVE_THRESHOLD_DBFS = math.nextafter(
    DROPOUT_FLANK_LEVEL_THRESHOLD_DBFS, math.inf
)
DROPOUT_DEPTH_THRESHOLD_DB = 30.0
SILENCE_RMS_THRESHOLD = 1e-5
SILENT_FRAME_FRACTION_THRESHOLD = 0.90
CRACKLE_COUNT_THRESHOLD = 3


@dataclass(frozen=True)
class DropoutCandidateMetrics:
    """Raw finite constraints for one below--80-dBFS frame run."""

    duration_ms: float
    left_boundary_ms: float
    right_boundary_ms: float
    left_level_dbfs: float
    right_level_dbfs: float
    low_level_dbfs: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class IntegrityResult:
    clipping: bool
    dropout: bool
    silence: bool
    crackle: bool
    integrity_pass: bool
    file_validity_failures: tuple[str, ...]
    hard_clipped_fraction: float | None
    longest_hard_clip_run_samples: int | None
    true_peak: float | None
    dropout_count: int | None
    longest_dropout_ms: float | None
    dropout_candidates: tuple[DropoutCandidateMetrics, ...]
    all_sample_rms: float | None
    silent_frame_fraction: float | None
    crackle_count: int | None
    maximum_channel_crackle_count: int | None
    crackle_sample_indices: tuple[int, ...]
    clipping_margin: float | None
    dropout_margin: float | None
    silence_margin: float | None
    crackle_margin: float | None
    sample_rate: int
    sample_count: int
    channel_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def dropout_candidate_margin(candidate: DropoutCandidateMetrics) -> float:
    """Return the frozen AND-gate margin for one possible dropout run."""

    return min(
        candidate.duration_ms / DROPOUT_DURATION_THRESHOLD_MS - 1.0,
        candidate.left_boundary_ms / DROPOUT_BOUNDARY_THRESHOLD_MS - 1.0,
        candidate.right_boundary_ms / DROPOUT_BOUNDARY_THRESHOLD_MS - 1.0,
        (candidate.left_level_dbfs - DROPOUT_FLANK_LEVEL_EFFECTIVE_THRESHOLD_DBFS)
        / abs(DROPOUT_FLANK_LEVEL_THRESHOLD_DBFS),
        (candidate.right_level_dbfs - DROPOUT_FLANK_LEVEL_EFFECTIVE_THRESHOLD_DBFS)
        / abs(DROPOUT_FLANK_LEVEL_THRESHOLD_DBFS),
        (candidate.left_level_dbfs - candidate.low_level_dbfs) / DROPOUT_DEPTH_THRESHOLD_DB - 1.0,
        (candidate.right_level_dbfs - candidate.low_level_dbfs) / DROPOUT_DEPTH_THRESHOLD_DB - 1.0,
    )


def _dropout_summary(
    candidates: Iterable[DropoutCandidateMetrics],
) -> tuple[bool, float, int, float]:
    rows = tuple(candidates)
    scored = [(row, dropout_candidate_margin(row)) for row in rows]
    accepted = [row for row, margin in scored if margin >= 0.0]
    margin = max((value for _, value in scored), default=-1.0)
    longest_ms = max((row.duration_ms for row in accepted), default=0.0)
    return bool(accepted), float(margin), len(accepted), float(longest_ms)


def score_integrity_raw_metrics(
    *,
    hard_clipped_fraction: float,
    longest_hard_clip_run_samples: int,
    true_peak: float,
    dropout_candidates: Iterable[DropoutCandidateMetrics],
    all_sample_rms: float,
    silent_frame_fraction: float,
    maximum_channel_crackle_count: int,
) -> dict[str, Any]:
    """Recompute every defect flag and normalized margin from scorer raw fields.

    OR gates use a maximum and AND gates use a minimum. Effective thresholds
    based on ``nextafter`` preserve the protocol's one strict comparison while
    making ``margin >= 0`` exactly equivalent to every Boolean flag.
    """

    clipping_margin = max(
        hard_clipped_fraction / HARD_CLIPPED_FRACTION_EFFECTIVE_THRESHOLD - 1.0,
        longest_hard_clip_run_samples / HARD_CLIP_RUN_THRESHOLD_SAMPLES - 1.0,
        true_peak / TRUE_PEAK_THRESHOLD - 1.0,
    )
    dropout, dropout_margin, dropout_count, longest_dropout_ms = _dropout_summary(
        dropout_candidates
    )
    silence_margin = max(
        1.0 - all_sample_rms / SILENCE_RMS_THRESHOLD,
        silent_frame_fraction / SILENT_FRAME_FRACTION_THRESHOLD - 1.0,
    )
    crackle_margin = maximum_channel_crackle_count / CRACKLE_COUNT_THRESHOLD - 1.0
    defects = {
        "clipping": {
            "flag": clipping_margin >= 0.0,
            "margin": float(clipping_margin),
        },
        "dropout": {"flag": dropout, "margin": float(dropout_margin)},
        "silence": {"flag": silence_margin >= 0.0, "margin": float(silence_margin)},
        "crackle": {"flag": crackle_margin >= 0.0, "margin": float(crackle_margin)},
    }
    return {
        "defects": defects,
        "dropout_count": dropout_count,
        "longest_dropout_ms": longest_dropout_ms,
    }


def integrity_raw_metrics(result: IntegrityResult) -> dict[str, object]:
    """Export only the finite scorer fields needed to recompute flags/margins."""

    if result.file_validity_failures:
        raise ValueError("invalid audio has no selector-eligible integrity raw metrics")
    required = (
        result.hard_clipped_fraction,
        result.longest_hard_clip_run_samples,
        result.true_peak,
        result.all_sample_rms,
        result.silent_frame_fraction,
        result.maximum_channel_crackle_count,
    )
    if any(value is None for value in required):
        raise ValueError("integrity result lacks selector raw metrics")
    return {
        "all_sample_rms": result.all_sample_rms,
        "dropout_candidates": [row.to_dict() for row in result.dropout_candidates],
        "hard_clipped_fraction": result.hard_clipped_fraction,
        "longest_hard_clip_run_samples": result.longest_hard_clip_run_samples,
        "maximum_channel_crackle_count": result.maximum_channel_crackle_count,
        "silent_frame_fraction": result.silent_frame_fraction,
        "true_peak": result.true_peak,
    }


def _dbfs(rms: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(rms, 1e-12))


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return true runs as half-open ``(start, end)`` pairs."""

    padded = np.pad(np.asarray(mask, dtype=np.int8), (1, 1))
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends, strict=True)]


def _frame_audio(audio: np.ndarray, frame_samples: int) -> tuple[np.ndarray, np.ndarray]:
    frame_count = math.ceil(audio.shape[0] / frame_samples)
    padded_count = frame_count * frame_samples
    padded = np.pad(audio, ((0, padded_count - audio.shape[0]), (0, 0)))
    frames = padded.reshape(frame_count, frame_samples, audio.shape[1])
    full = np.arange(frame_count) * frame_samples + frame_samples <= audio.shape[0]
    return frames, full


def _hard_clip_features(channel: np.ndarray) -> tuple[float, int]:
    hard = np.abs(channel) >= 1.0 - 2.0**-15
    fraction = float(np.mean(hard))
    longest = max((end - start for start, end in _runs(hard)), default=0)
    return fraction, longest


def _true_peak(channel: np.ndarray) -> float:
    oversampled = resample_poly(
        channel,
        TRUE_PEAK_OVERSAMPLE,
        1,
        window=("kaiser", 8.6),
        padtype="constant",
    )
    # SciPy removes the linear-phase delay, but its zero-padding assumption
    # still creates an edge transient over the symmetric FIR half-length.
    # The protocol excludes that padding region from the true-peak maximum.
    if oversampled.size > 2 * TRUE_PEAK_FILTER_HALF_LEN:
        oversampled = oversampled[TRUE_PEAK_FILTER_HALF_LEN:-TRUE_PEAK_FILTER_HALF_LEN]
    return float(np.max(np.abs(oversampled), initial=0.0))


def _dropout_features(channel: np.ndarray, sample_rate: int) -> tuple[DropoutCandidateMetrics, ...]:
    frame_samples = max(1, round(sample_rate * 0.010))
    frames, full = _frame_audio(channel[:, None], frame_samples)
    rms = np.sqrt(np.mean(np.square(frames[:, :, 0]), axis=1))
    levels = np.asarray(_dbfs(rms))
    full_count = int(np.count_nonzero(full))
    levels = levels[:full_count]
    low = levels < -80.0
    minimum_frames = math.ceil(0.050 * sample_rate / frame_samples)
    boundary_samples = math.ceil(0.250 * sample_rate)
    flank_frames = math.ceil(0.100 * sample_rate / frame_samples)
    candidates: list[DropoutCandidateMetrics] = []
    for start, end in _runs(low):
        start_sample = start * frame_samples
        end_sample = end * frame_samples
        left = levels[max(0, start - flank_frames) : start]
        right = levels[end : min(full_count, end + flank_frames)]
        left_level = float(np.max(left)) if left.size else -240.0
        right_level = float(np.max(right)) if right.size else -240.0
        low_level = float(np.max(levels[start:end]))
        candidates.append(
            DropoutCandidateMetrics(
                duration_ms=(end - start) * frame_samples * 1000.0 / sample_rate,
                left_boundary_ms=start_sample * 1000.0 / sample_rate,
                right_boundary_ms=(channel.size - end_sample) * 1000.0 / sample_rate,
                left_level_dbfs=left_level,
                right_level_dbfs=right_level,
                low_level_dbfs=low_level,
            )
        )

    # These are redundant implementation assertions for the frozen constraints;
    # the public normalized-margin function is the selector source of truth.
    for candidate in candidates:
        accepted_by_original_rules = (
            candidate.duration_ms >= minimum_frames * frame_samples * 1000.0 / sample_rate
            and candidate.left_boundary_ms >= boundary_samples * 1000.0 / sample_rate
            and candidate.right_boundary_ms >= boundary_samples * 1000.0 / sample_rate
            and candidate.left_level_dbfs > DROPOUT_FLANK_LEVEL_THRESHOLD_DBFS
            and candidate.right_level_dbfs > DROPOUT_FLANK_LEVEL_THRESHOLD_DBFS
            and candidate.left_level_dbfs - candidate.low_level_dbfs >= DROPOUT_DEPTH_THRESHOLD_DB
            and candidate.right_level_dbfs - candidate.low_level_dbfs >= DROPOUT_DEPTH_THRESHOLD_DB
        )
        if accepted_by_original_rules is not (dropout_candidate_margin(candidate) >= 0.0):
            raise RuntimeError("normalized dropout margin disagrees with frozen rule")
    return tuple(candidates)


def _robust_derivative_z(
    derivative: np.ndarray,
    transition_index: int,
    *,
    candidate_start: int,
    candidate_end: int,
    sample_rate: int,
) -> float:
    half_width = max(1, round(0.010 * sample_rate))
    left = max(0, transition_index - half_width)
    right = min(derivative.size, transition_index + half_width + 1)
    neighborhood_indices = np.arange(left, right)
    excluded_left = candidate_start - 3
    excluded_right = candidate_end + 3
    keep = (neighborhood_indices < excluded_left) | (neighborhood_indices > excluded_right)
    background = derivative[neighborhood_indices[keep]]
    if background.size == 0:
        return 0.0
    center = float(np.median(background))
    mad = float(np.median(np.abs(background - center)))
    scale = max(1.4826 * mad, 1e-6)
    return abs(float(derivative[transition_index]) - center) / scale


def _crackle_features(channel: np.ndarray, sample_rate: int) -> tuple[int, tuple[int, ...]]:
    derivative = np.diff(channel)
    strong = np.flatnonzero(np.abs(derivative) >= 0.20)
    strong_set = set(int(index) for index in strong)
    candidates: list[tuple[int, float]] = []
    for onset in strong:
        onset_index = int(onset)
        for excursion_samples in (1, 2, 3):
            offset_index = onset_index + excursion_samples
            if offset_index not in strong_set:
                continue
            if derivative[onset_index] * derivative[offset_index] >= 0.0:
                continue
            onset_z = _robust_derivative_z(
                derivative,
                onset_index,
                candidate_start=onset_index,
                candidate_end=offset_index,
                sample_rate=sample_rate,
            )
            offset_z = _robust_derivative_z(
                derivative,
                offset_index,
                candidate_start=onset_index,
                candidate_end=offset_index,
                sample_rate=sample_rate,
            )
            if onset_z >= 12.0 and offset_z >= 12.0:
                candidates.append((onset_index + 1, min(onset_z, offset_z)))

    # Collapse alternate detections within the required 10-ms isolation span,
    # retaining the strongest candidate with an earliest-index tie break.
    minimum_separation = max(1, math.ceil(0.010 * sample_rate))
    isolated: list[tuple[int, float]] = []
    for index, score in sorted(candidates):
        if not isolated or index - isolated[-1][0] >= minimum_separation:
            isolated.append((index, score))
        elif score > isolated[-1][1]:
            isolated[-1] = (index, score)
    indices = tuple(index for index, _ in isolated)
    return len(indices), indices


def _invalid_result(
    failures: list[str], sample_rate: int, sample_count: int, channel_count: int
) -> IntegrityResult:
    return IntegrityResult(
        clipping=False,
        dropout=False,
        silence=False,
        crackle=False,
        integrity_pass=False,
        file_validity_failures=tuple(failures),
        hard_clipped_fraction=None,
        longest_hard_clip_run_samples=None,
        true_peak=None,
        dropout_count=None,
        longest_dropout_ms=None,
        dropout_candidates=(),
        all_sample_rms=None,
        silent_frame_fraction=None,
        crackle_count=None,
        maximum_channel_crackle_count=None,
        crackle_sample_indices=(),
        clipping_margin=None,
        dropout_margin=None,
        silence_margin=None,
        crackle_margin=None,
        sample_rate=sample_rate,
        sample_count=sample_count,
        channel_count=channel_count,
    )


def analyze_integrity(
    decoded_audio: np.ndarray,
    sample_rate: int,
    *,
    expected_duration_seconds: float | None = 30.0,
    expected_channel_count: int | None = None,
) -> IntegrityResult:
    """Apply all four frozen defect rules to decoded float audio.

    Arrays are interpreted as ``samples`` or ``samples x channels``. No
    normalization, limiting, dither, or integer conversion is performed.
    """

    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    raw = np.asarray(decoded_audio)
    if raw.ndim == 1:
        raw = raw[:, None]
    if raw.ndim != 2 or raw.shape[0] == 0 or raw.shape[1] == 0:
        raise ValueError("decoded_audio must have shape samples or samples x channels")
    audio = raw.astype(np.float64, copy=False)
    sample_count, channel_count = audio.shape
    failures: list[str] = []
    if not np.isfinite(audio).all():
        failures.append("NONFINITE_AUDIO")
    if expected_channel_count is not None and channel_count != expected_channel_count:
        failures.append("CHANNEL_COUNT_MISMATCH")
    if expected_duration_seconds is not None:
        expected_samples = round(float(expected_duration_seconds) * sample_rate)
        if sample_count != expected_samples:
            failures.append("SAMPLE_COUNT_MISMATCH")
    if failures:
        return _invalid_result(failures, sample_rate, sample_count, channel_count)

    clip_features = [_hard_clip_features(audio[:, channel]) for channel in range(channel_count)]
    clipped_fraction = max(feature[0] for feature in clip_features)
    longest_clip_run = max(feature[1] for feature in clip_features)
    true_peak = max(_true_peak(audio[:, channel]) for channel in range(channel_count))
    clipping = (
        clipped_fraction > HARD_CLIPPED_FRACTION_THRESHOLD
        or longest_clip_run >= HARD_CLIP_RUN_THRESHOLD_SAMPLES
        or true_peak >= TRUE_PEAK_THRESHOLD
    )

    dropout_features = [
        _dropout_features(audio[:, channel], sample_rate) for channel in range(channel_count)
    ]
    dropout_candidates = tuple(
        candidate for channel_candidates in dropout_features for candidate in channel_candidates
    )

    all_sample_rms = float(np.sqrt(np.mean(np.square(audio))))
    silence_frame_samples = max(1, round(sample_rate * 0.050))
    silence_frames, _ = _frame_audio(audio, silence_frame_samples)
    silence_frame_rms = np.sqrt(np.mean(np.square(silence_frames), axis=(1, 2)))
    silent_frame_fraction = float(np.mean(np.asarray(_dbfs(silence_frame_rms)) < -60.0))
    silence = (
        all_sample_rms <= SILENCE_RMS_THRESHOLD
        or silent_frame_fraction >= SILENT_FRAME_FRACTION_THRESHOLD
    )

    crackle_features = [
        _crackle_features(audio[:, channel], sample_rate) for channel in range(channel_count)
    ]
    crackle_count = sum(feature[0] for feature in crackle_features)
    maximum_channel_crackle_count = max(feature[0] for feature in crackle_features)
    crackle_indices = tuple(
        sorted({index for _, channel_indices in crackle_features for index in channel_indices})
    )
    crackle = maximum_channel_crackle_count >= CRACKLE_COUNT_THRESHOLD
    raw_scores = score_integrity_raw_metrics(
        hard_clipped_fraction=clipped_fraction,
        longest_hard_clip_run_samples=longest_clip_run,
        true_peak=true_peak,
        dropout_candidates=dropout_candidates,
        all_sample_rms=all_sample_rms,
        silent_frame_fraction=silent_frame_fraction,
        maximum_channel_crackle_count=maximum_channel_crackle_count,
    )
    score_defects = raw_scores["defects"]
    if {
        "clipping": clipping,
        "dropout": bool(raw_scores["dropout_count"]),
        "silence": silence,
        "crackle": crackle,
    } != {name: bool(score_defects[name]["flag"]) for name in DEFECT_NAMES}:
        raise RuntimeError("normalized integrity margins disagree with frozen flags")
    dropout_count = int(raw_scores["dropout_count"])
    longest_dropout_ms = float(raw_scores["longest_dropout_ms"])
    dropout = bool(score_defects["dropout"]["flag"])
    integrity_pass = not any((clipping, dropout, silence, crackle))
    return IntegrityResult(
        clipping=clipping,
        dropout=dropout,
        silence=silence,
        crackle=crackle,
        integrity_pass=integrity_pass,
        file_validity_failures=(),
        hard_clipped_fraction=clipped_fraction,
        longest_hard_clip_run_samples=longest_clip_run,
        true_peak=true_peak,
        dropout_count=dropout_count,
        longest_dropout_ms=longest_dropout_ms,
        dropout_candidates=dropout_candidates,
        all_sample_rms=all_sample_rms,
        silent_frame_fraction=silent_frame_fraction,
        crackle_count=crackle_count,
        maximum_channel_crackle_count=maximum_channel_crackle_count,
        crackle_sample_indices=crackle_indices,
        clipping_margin=float(score_defects["clipping"]["margin"]),
        dropout_margin=float(score_defects["dropout"]["margin"]),
        silence_margin=float(score_defects["silence"]["margin"]),
        crackle_margin=float(score_defects["crackle"]["margin"]),
        sample_rate=sample_rate,
        sample_count=sample_count,
        channel_count=channel_count,
    )


def summarize_integrity(results: Iterable[IntegrityResult]) -> dict[str, object]:
    """Report every defect-specific count/rate, including zero-rate defects."""

    rows = tuple(results)
    total = len(rows)
    defect_rows: dict[str, dict[str, float | int]] = {}
    for defect in DEFECT_NAMES:
        count = sum(bool(getattr(row, defect)) for row in rows)
        defect_rows[defect] = {"count": count, "rate": count / total if total else math.nan}
    validity_failures = sum(bool(row.file_validity_failures) for row in rows)
    overall_failures = sum(not row.integrity_pass for row in rows)
    return {
        "clip_count": total,
        "defects": defect_rows,
        "file_validity_failure_count": validity_failures,
        "file_validity_failure_rate": validity_failures / total if total else math.nan,
        "overall_failure_count": overall_failures,
        "overall_failure_rate": overall_failures / total if total else math.nan,
    }

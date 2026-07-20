"""Synthetic integrity injections frozen before benchmark generation."""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 48_000
DURATION_SECONDS = 2.0
EXPECTED_DEFECTS = {
    "clean_side_control": frozenset(),
    "clipping_clean_side_control": frozenset(),
    "dropout_clean_side_control": frozenset(),
    "dropout_boundary_control": frozenset(),
    "silence_clean_side_control": frozenset(),
    "crackle_clean_side_control": frozenset(),
    "sharp_percussive_control": frozenset(),
    "clipping_injection": frozenset({"clipping"}),
    "dropout_injection": frozenset({"dropout"}),
    "silence_injection": frozenset({"silence"}),
    "crackle_injection": frozenset({"crackle"}),
}
SPECIAL_EXPECTATIONS = {
    "true_peak_edge_control_constant_0p90": (frozenset(), ()),
    "stereo_any_channel_crackle": (frozenset({"crackle"}), ()),
    "partial_final_frame_padding_control": (frozenset(), ()),
    "duration_mismatch_validity": (frozenset(), ("SAMPLE_COUNT_MISMATCH",)),
    "nan_inf_validity": (frozenset(), ("NONFINITE_AUDIO",)),
    "unexpected_channels_validity": (frozenset(), ("CHANNEL_COUNT_MISMATCH",)),
}


def _clean(sample_rate: int, duration_seconds: float) -> np.ndarray:
    time = np.arange(round(sample_rate * duration_seconds), dtype=np.float64) / sample_rate
    return 0.12 * np.sin(2.0 * np.pi * 220.0 * time) + 0.04 * np.sin(
        2.0 * np.pi * 440.0 * time + 0.3
    )


def build_integrity_injections(
    sample_rate: int = SAMPLE_RATE,
    duration_seconds: float = DURATION_SECONDS,
) -> dict[str, np.ndarray]:
    """Build defect-separated arrays plus clean and sharp controls in memory."""

    clean = _clean(sample_rate, duration_seconds)

    time = np.arange(clean.size, dtype=np.float64) / sample_rate
    clipping_clean_side = 0.95 * np.sin(2.0 * np.pi * 1000.0 * time)

    dropout_clean_side = clean.copy()
    dropout_clean_side[
        round(0.80 * sample_rate) : round(0.84 * sample_rate)
    ] = 0.0

    dropout_boundary = clean.copy()
    dropout_boundary[
        round(0.05 * sample_rate) : round(0.15 * sample_rate)
    ] = 0.0

    silence_clean_side = np.zeros_like(clean)
    silence_clean_side[round(1.75 * sample_rate) :] = clean[round(1.75 * sample_rate) :]

    crackle_clean_side = clean.copy()
    for seconds in (0.60, 1.20):
        crackle_clean_side[round(seconds * sample_rate)] += 0.60

    clipping = clean.copy()
    clipping[round(0.60 * sample_rate) : round(0.62 * sample_rate)] = 1.0

    dropout = clean.copy()
    dropout[round(0.80 * sample_rate) : round(0.90 * sample_rate)] = 0.0

    silence = np.zeros_like(clean)

    crackle = clean.copy()
    for seconds in (0.35, 0.75, 1.15, 1.55):
        crackle[round(seconds * sample_rate)] += 0.60

    sharp = clean.copy()
    decay_samples = round(0.040 * sample_rate)
    decay = 0.35 * np.exp(-np.arange(decay_samples) / (0.008 * sample_rate))
    for seconds in (0.40, 0.90, 1.40):
        start = round(seconds * sample_rate)
        sharp[start : start + decay_samples] += decay

    return {
        "clean_side_control": clean,
        "clipping_clean_side_control": clipping_clean_side,
        "dropout_clean_side_control": dropout_clean_side,
        "dropout_boundary_control": dropout_boundary,
        "silence_clean_side_control": silence_clean_side,
        "crackle_clean_side_control": crackle_clean_side,
        "sharp_percussive_control": sharp,
        "clipping_injection": clipping,
        "dropout_injection": dropout,
        "silence_injection": silence,
        "crackle_injection": crackle,
    }


def build_integrity_special_cases(
    sample_rate: int = SAMPLE_RATE,
    duration_seconds: float = DURATION_SECONDS,
) -> dict[str, tuple[np.ndarray, float | None, int]]:
    """Build stereo, padding, boundary-adjacent, and validity-vector cases."""

    fixtures = build_integrity_injections(sample_rate, duration_seconds)
    clean = fixtures["clean_side_control"]

    nonfinite = clean.copy()
    nonfinite[0] = np.nan
    nonfinite[1] = np.inf

    return {
        "true_peak_edge_control_constant_0p90": (
            np.full(clean.size, 0.90),
            duration_seconds,
            1,
        ),
        "stereo_any_channel_crackle": (
            np.column_stack((clean, fixtures["crackle_injection"])),
            duration_seconds,
            2,
        ),
        "partial_final_frame_padding_control": (
            np.concatenate((clean, np.zeros(1))),
            None,
            1,
        ),
        "duration_mismatch_validity": (clean[:-1], duration_seconds, 1),
        "nan_inf_validity": (nonfinite, duration_seconds, 1),
        "unexpected_channels_validity": (
            np.column_stack((clean, clean)),
            duration_seconds,
            1,
        ),
    }

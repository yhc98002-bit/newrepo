"""Duration-tolerant wrapper around the frozen legacy retained-audio sanity.

Every legacy check is preserved.  The sole adjudicated change is that the
legacy exact decoded-frame failure is evaluated as an inclusive decoded-time
tolerance instead.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from audio_duration_policy import duration_within_tolerance
from sa3_smoke.audio import EXPECTED_CHANNELS, EXPECTED_SAMPLE_RATE, audio_sanity

ACE_STEP_V1_DURATION_TOLERANCE_SECONDS = 0.25
SA3_DURATION_TOLERANCE_SECONDS = 0.25
MAX_DURATION_TOLERANCE_SECONDS = 0.25


def duration_tolerant_audio_sanity(
    path: str | Path,
    requested_seconds: float,
    *,
    duration_tolerance_seconds: float,
    expected_sample_rate: int = EXPECTED_SAMPLE_RATE,
    expected_channels: int = EXPECTED_CHANNELS,
    require_provenance: bool = True,
) -> dict[str, Any]:
    """Run legacy sanity while replacing only its exact-frame criterion."""

    # Validate the policy value even if the named artifact cannot be decoded.
    if isinstance(duration_tolerance_seconds, bool) or not isinstance(
        duration_tolerance_seconds, (int, float)
    ):
        raise TypeError("duration_tolerance_seconds must be a finite non-negative number")
    tolerance = float(duration_tolerance_seconds)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("duration_tolerance_seconds must be a finite non-negative number")
    if tolerance > MAX_DURATION_TOLERANCE_SECONDS:
        raise ValueError(
            f"duration_tolerance_seconds must not exceed {MAX_DURATION_TOLERANCE_SECONDS}"
        )

    legacy = audio_sanity(
        path,
        requested_seconds,
        expected_sample_rate=expected_sample_rate,
        expected_channels=expected_channels,
        require_provenance=require_provenance,
    )
    result = copy.deepcopy(legacy)
    failures = list(result["failures"])
    exact_frame_failures = [row for row in failures if row.get("check") == "sample_count"]
    failures = [row for row in failures if row.get("check") != "sample_count"]

    observed_duration = result.get("duration_seconds")
    absolute_error: float | None = None
    within_tolerance: bool | None = None
    if observed_duration is not None:
        absolute_error = abs(float(observed_duration) - float(requested_seconds))
        within_tolerance = duration_within_tolerance(
            float(observed_duration), float(requested_seconds), tolerance
        )

    if exact_frame_failures and within_tolerance is not True:
        failures.append(
            {
                "check": "duration_tolerance",
                "expected": f"absolute decoded-duration error <= {tolerance} seconds",
                "observed": absolute_error,
            }
        )

    result.update(
        {
            "legacy_exact_sample_count_pass": not exact_frame_failures,
            "duration_tolerance_seconds": tolerance,
            "absolute_duration_error_seconds": absolute_error,
            "duration_within_tolerance": within_tolerance,
            "failures": failures,
            "pass": not failures,
        }
    )
    return result

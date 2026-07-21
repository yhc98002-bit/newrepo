"""Shared, side-effect-free audio-duration tolerance policy.

The predicate in this module intentionally knows nothing about a backbone,
sample rate, codec, or file format.  Callers must supply the observed decoded
duration and the requested duration explicitly.
"""

from __future__ import annotations

import math
from numbers import Real


def _finite_non_boolean_real(value: Real, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field} must be a finite real number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field} must be a finite real number")
    return converted


def duration_within_tolerance(
    observed_seconds: Real,
    requested_seconds: Real,
    tolerance_seconds: Real,
) -> bool:
    """Return whether an observed duration is inclusively within tolerance.

    Requested and observed durations must be positive.  A tolerance of zero is
    valid, and the boundary is inclusive: an absolute deviation equal to the
    tolerance passes.
    """

    observed = _finite_non_boolean_real(observed_seconds, "observed_seconds")
    requested = _finite_non_boolean_real(requested_seconds, "requested_seconds")
    tolerance = _finite_non_boolean_real(tolerance_seconds, "tolerance_seconds")
    if observed <= 0:
        raise ValueError("observed_seconds must be positive")
    if requested <= 0:
        raise ValueError("requested_seconds must be positive")
    if tolerance < 0:
        raise ValueError("tolerance_seconds must be non-negative")
    return abs(observed - requested) <= tolerance

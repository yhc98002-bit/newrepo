from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from instruments.tempo import (
    BEAT_THIS_CHECKPOINT_SHA256,
    BEAT_THIS_COMMIT,
    LIBROSA_VERSION,
    TempoEstimate,
    beat_this_estimate,
    evaluate_window_drift,
    librosa_estimate,
    octave_invariant_error,
    resolve_tempo,
    resolve_tempo_windows,
    validate_evaluator_pins,
)

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "provenance" / "b1" / "tempo_evaluator_pins.json"


def _events(bpm: float, count: int = 24, start: float = 0.0) -> list[float]:
    return [start + index * 60.0 / bpm for index in range(count)]


def _valid(bpm: float, estimator: str) -> TempoEstimate:
    return TempoEstimate(estimator, True, bpm, 24, 60.0 / bpm, 0.0, None)


def test_evaluator_pair_and_checkpoint_are_pinned() -> None:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    assert pins["beat_this"]["commit"] == BEAT_THIS_COMMIT
    assert pins["beat_this"]["version"] == "1.1.0"
    assert pins["beat_this"]["checkpoint"]["name"] == "final0"
    assert pins["beat_this"]["checkpoint"]["sha256"] == BEAT_THIS_CHECKPOINT_SHA256
    assert pins["beat_this"]["postprocessor"] == "minimal"
    assert pins["librosa"]["version"] == LIBROSA_VERSION
    validate_evaluator_pins(
        beat_this_commit=BEAT_THIS_COMMIT,
        beat_this_checkpoint_sha256=BEAT_THIS_CHECKPOINT_SHA256,
        librosa_version=LIBROSA_VERSION,
    )
    with pytest.raises(RuntimeError, match="implementation commit"):
        validate_evaluator_pins(
            beat_this_commit="main",
            beat_this_checkpoint_sha256=BEAT_THIS_CHECKPOINT_SHA256,
            librosa_version=LIBROSA_VERSION,
        )


def test_event_validity_and_librosa_retained_frames() -> None:
    beat_this = beat_this_estimate(_events(120.0))
    assert beat_this.valid and beat_this.bpm == pytest.approx(120.0)
    assert not beat_this_estimate(_events(120.0, count=7)).valid

    librosa = librosa_estimate(
        120.0,
        range(0, 24 * 50, 50),
        sample_rate=1000,
        hop_length=10,
    )
    assert librosa.valid and librosa.bpm == 120.0

    irregular = beat_this_estimate((0.0, 0.3, 1.0, 1.3, 2.0, 2.3, 3.0, 3.3))
    assert irregular.invalid_reason == "INTERVAL_IQR_EXCEEDS_25PCT_MEDIAN"


def test_frozen_disagreement_rule_aligns_octaves_and_abstains() -> None:
    aligned = resolve_tempo(120.0, _valid(120.0, "beat_this"), _valid(60.0, "librosa"))
    assert aligned.status == "RESOLVED"
    assert aligned.beat_this_aligned_bpm == 120.0
    assert aligned.librosa_aligned_bpm == 120.0
    assert aligned.consensus_bpm == 120.0
    assert aligned.primary_5pct_success is True
    assert aligned.sensitivity_10pct_success is True

    disagreement = resolve_tempo(120.0, _valid(120.0, "beat_this"), _valid(100.0, "librosa"))
    assert disagreement.status == "ESTIMATOR_DISAGREEMENT"
    assert disagreement.consensus_bpm is None
    assert math.isinf(disagreement.octave_invariant_error)

    invalid = resolve_tempo(
        120.0,
        beat_this_estimate(_events(120.0, count=7)),
        _valid(120.0, "librosa"),
    )
    assert invalid.status == "ESTIMATOR_INVALID"


def test_primary_5pct_and_preregistered_10pct_sensitivity_are_both_returned() -> None:
    five = resolve_tempo(120.0, _valid(126.0, "beat_this"), _valid(126.0, "librosa"))
    assert five.primary_5pct_success is True
    assert five.sensitivity_10pct_success is True

    between = resolve_tempo(120.0, _valid(128.0, "beat_this"), _valid(128.0, "librosa"))
    assert between.primary_5pct_success is False
    assert between.sensitivity_10pct_success is True

    above = resolve_tempo(120.0, _valid(133.0, "beat_this"), _valid(133.0, "librosa"))
    assert above.sensitivity_10pct_success is False
    assert octave_invariant_error(60.0, 120.0) == 0.0


def test_first_and_second_tapping_window_drift_are_separate() -> None:
    stable = evaluate_window_drift(120.0, _events(120.0, start=2.0), _events(125.0, start=16.0))
    assert stable.valid is True
    assert stable.first_window_bpm == pytest.approx(120.0)
    assert stable.second_window_bpm == pytest.approx(125.0)
    assert stable.first_target_error == pytest.approx(0.0)
    assert stable.second_target_error > 0.0
    assert stable.signed_drift_octaves == pytest.approx(math.log2(125.0 / 120.0))
    assert stable.between_window_fractional_drift == pytest.approx(5.0 / 120.0)
    assert stable.replay_required is False

    lower_direction = evaluate_window_drift(
        120.0, _events(120.0, start=2.0), _events(111.0, start=16.0)
    )
    assert lower_direction.between_window_fractional_drift == pytest.approx(0.075)
    assert lower_direction.replay_required is True

    drifting = evaluate_window_drift(120.0, _events(120.0, start=2.0), _events(132.0, start=16.0))
    assert drifting.replay_required is True

    invalid = evaluate_window_drift(120.0, _events(120.0, count=7), _events(120.0, start=16.0))
    assert invalid.valid is False
    assert invalid.invalid_reason == "FEWER_THAN_8_EVENTS"


def test_automatic_first_second_windows_each_use_the_frozen_pair_rule() -> None:
    windows = resolve_tempo_windows(
        120.0,
        first_beat_this=_valid(120.0, "beat_this_first"),
        first_librosa=_valid(60.0, "librosa_first"),
        second_beat_this=_valid(128.0, "beat_this_second"),
        second_librosa=_valid(128.0, "librosa_second"),
    )
    assert windows.first_window.primary_5pct_success is True
    assert windows.first_window.sensitivity_10pct_success is True
    assert windows.second_window.primary_5pct_success is False
    assert windows.second_window.sensitivity_10pct_success is True
    assert windows.signed_drift_octaves == pytest.approx(math.log2(128.0 / 120.0))
    assert windows.octave_invariant_absolute_drift == pytest.approx(
        abs(windows.signed_drift_octaves)
    )

    abstaining = resolve_tempo_windows(
        120.0,
        first_beat_this=_valid(120.0, "beat_this_first"),
        first_librosa=_valid(100.0, "librosa_first"),
        second_beat_this=_valid(120.0, "beat_this_second"),
        second_librosa=_valid(120.0, "librosa_second"),
    )
    assert abstaining.first_window.status == "ESTIMATOR_DISAGREEMENT"
    assert math.isnan(abstaining.signed_drift_octaves)
    assert math.isinf(abstaining.octave_invariant_absolute_drift)

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from instruments.integrity import (
    DEFECT_NAMES,
    DropoutCandidateMetrics,
    analyze_integrity,
    integrity_raw_metrics,
    score_integrity_raw_metrics,
    summarize_integrity,
)
from tests.fixtures.integrity_injections import (
    DURATION_SECONDS,
    EXPECTED_DEFECTS,
    SAMPLE_RATE,
    SPECIAL_EXPECTATIONS,
    build_integrity_injections,
    build_integrity_special_cases,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SOURCE = ROOT / "tests" / "fixtures" / "integrity_injections.py"
FIXTURE_SPEC = ROOT / "provenance" / "b1" / "integrity_synthetic_fixture.json"
VALIDATION = ROOT / "provenance" / "b1" / "integrity_synthetic_validation.json"


def _observed_defects(result) -> frozenset[str]:
    return frozenset(defect for defect in DEFECT_NAMES if getattr(result, defect))


def test_synthetic_fixture_is_hash_bound_and_contains_no_audio_files() -> None:
    spec = json.loads(FIXTURE_SPEC.read_text(encoding="utf-8"))
    assert hashlib.sha256(FIXTURE_SOURCE.read_bytes()).hexdigest() == spec["fixture_source_sha256"]
    assert spec["fixture_kind"] == "deterministic_programmatic_arrays"
    assert spec["model_generation_calls"] == 0
    assert spec["benchmark_endpoints_scored"] == 0
    assert not list((ROOT / "tests" / "fixtures").glob("*.wav"))


def test_terminal_synthetic_validation_binds_code_and_exact_defect_sets() -> None:
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    bindings = validation["bindings"]
    integrity_source = ROOT / bindings["integrity_implementation"]
    assert validation["status"] == "PASS"
    assert validation["pre_generation_gate"] is True
    assert (
        hashlib.sha256(FIXTURE_SPEC.read_bytes()).hexdigest() == bindings["fixture_manifest_sha256"]
    )
    assert (
        hashlib.sha256(FIXTURE_SOURCE.read_bytes()).hexdigest() == bindings["fixture_source_sha256"]
    )
    assert (
        hashlib.sha256(integrity_source.read_bytes()).hexdigest()
        == bindings["integrity_implementation_sha256"]
    )
    expected_rows = {fixture: sorted(defects) for fixture, defects in EXPECTED_DEFECTS.items()}
    reported_rows = {
        row["fixture"]: row for row in validation["results"] if row["fixture"] in expected_rows
    }
    assert set(reported_rows) == set(expected_rows)
    for fixture, expected in expected_rows.items():
        assert reported_rows[fixture]["expected_defects"] == expected
        assert reported_rows[fixture]["observed_defects"] == expected
        assert reported_rows[fixture]["status"] == "PASS"

    special_cases = build_integrity_special_cases()
    special_rows = {
        row["fixture"]: row
        for row in validation["results"]
        if row["fixture"] in SPECIAL_EXPECTATIONS
    }
    assert set(special_rows) == set(SPECIAL_EXPECTATIONS)
    for fixture, (expected_defects, expected_validity) in SPECIAL_EXPECTATIONS.items():
        audio, expected_duration, expected_channels = special_cases[fixture]
        actual = analyze_integrity(
            audio,
            SAMPLE_RATE,
            expected_duration_seconds=expected_duration,
            expected_channel_count=expected_channels,
        )
        expected_defect_list = sorted(expected_defects)
        expected_validity_list = list(expected_validity)
        assert special_rows[fixture]["expected_defects"] == expected_defect_list
        assert special_rows[fixture]["observed_defects"] == expected_defect_list
        assert special_rows[fixture]["expected_validity_failures"] == expected_validity_list
        assert special_rows[fixture]["observed_validity_failures"] == expected_validity_list
        assert _observed_defects(actual) == expected_defects
        assert list(actual.file_validity_failures) == expected_validity_list
        assert special_rows[fixture]["status"] == "PASS"
    assert validation["model_generation_calls"] == 0
    assert validation["benchmark_endpoints_scored"] == 0


@pytest.mark.parametrize("fixture_name", tuple(EXPECTED_DEFECTS))
def test_each_injection_and_control_has_exact_defect_separation(fixture_name: str) -> None:
    fixtures = build_integrity_injections()
    result = analyze_integrity(
        fixtures[fixture_name],
        SAMPLE_RATE,
        expected_duration_seconds=DURATION_SECONDS,
        expected_channel_count=1,
    )
    assert result.file_validity_failures == ()
    assert _observed_defects(result) == EXPECTED_DEFECTS[fixture_name]
    assert result.integrity_pass is (not EXPECTED_DEFECTS[fixture_name])


def test_any_channel_triggers_non_silence_defects() -> None:
    fixtures = build_integrity_injections()
    stereo = np.column_stack((fixtures["clean_side_control"], fixtures["crackle_injection"]))
    result = analyze_integrity(
        stereo,
        SAMPLE_RATE,
        expected_duration_seconds=DURATION_SECONDS,
        expected_channel_count=2,
    )
    assert result.crackle is True
    assert result.integrity_pass is False


def test_true_peak_trims_zero_padding_edge_transients() -> None:
    constant = np.full(round(SAMPLE_RATE * DURATION_SECONDS), 0.90)
    result = analyze_integrity(
        constant,
        SAMPLE_RATE,
        expected_duration_seconds=DURATION_SECONDS,
        expected_channel_count=1,
    )
    assert result.true_peak == pytest.approx(0.90, abs=1e-4)
    assert result.clipping is False


@pytest.mark.parametrize("fixture_name", tuple(SPECIAL_EXPECTATIONS))
def test_special_padding_stereo_and_validity_vectors(fixture_name: str) -> None:
    audio, expected_duration, expected_channels = build_integrity_special_cases()[fixture_name]
    expected_defects, expected_validity = SPECIAL_EXPECTATIONS[fixture_name]
    result = analyze_integrity(
        audio,
        SAMPLE_RATE,
        expected_duration_seconds=expected_duration,
        expected_channel_count=expected_channels,
    )
    assert _observed_defects(result) == expected_defects
    assert result.file_validity_failures == expected_validity


def test_file_validity_failures_are_above_defect_categories() -> None:
    fixtures = build_integrity_injections()
    wrong = fixtures["clean_side_control"][:-1].copy()
    wrong[0] = np.nan
    result = analyze_integrity(
        wrong,
        SAMPLE_RATE,
        expected_duration_seconds=DURATION_SECONDS,
        expected_channel_count=2,
    )
    assert set(result.file_validity_failures) == {
        "NONFINITE_AUDIO",
        "CHANNEL_COUNT_MISMATCH",
        "SAMPLE_COUNT_MISMATCH",
    }
    assert result.integrity_pass is False
    assert _observed_defects(result) == frozenset()
    assert result.true_peak is None


def test_defect_specific_rates_are_always_reported() -> None:
    fixtures = build_integrity_injections()
    results = [
        analyze_integrity(
            audio,
            SAMPLE_RATE,
            expected_duration_seconds=DURATION_SECONDS,
            expected_channel_count=1,
        )
        for audio in fixtures.values()
    ]
    summary = summarize_integrity(results)
    assert tuple(summary["defects"]) == DEFECT_NAMES
    for defect in DEFECT_NAMES:
        assert summary["defects"][defect] == {
            "count": 1,
            "rate": pytest.approx(1.0 / len(results)),
        }
    assert summary["overall_failure_count"] == 4


@pytest.mark.parametrize("fixture_name", tuple(EXPECTED_DEFECTS))
def test_defect_flags_and_margins_recompute_from_exported_raw_metrics(
    fixture_name: str,
) -> None:
    result = analyze_integrity(
        build_integrity_injections()[fixture_name],
        SAMPLE_RATE,
        expected_duration_seconds=DURATION_SECONDS,
        expected_channel_count=1,
    )
    raw = integrity_raw_metrics(result)
    raw["dropout_candidates"] = tuple(
        DropoutCandidateMetrics(**row) for row in raw["dropout_candidates"]
    )
    recomputed = score_integrity_raw_metrics(**raw)
    for defect in DEFECT_NAMES:
        expected_flag = getattr(result, defect)
        expected_margin = getattr(result, f"{defect}_margin")
        assert recomputed["defects"][defect]["flag"] is expected_flag
        assert recomputed["defects"][defect]["margin"] == pytest.approx(expected_margin)
        assert expected_flag is (expected_margin >= 0.0)


def test_dropout_margin_uses_all_frozen_and_gate_constraints() -> None:
    passing = DropoutCandidateMetrics(
        duration_ms=50.0,
        left_boundary_ms=250.0,
        right_boundary_ms=250.0,
        left_level_dbfs=-39.0,
        right_level_dbfs=-39.0,
        low_level_dbfs=-80.0,
    )
    almost = DropoutCandidateMetrics(
        duration_ms=49.0,
        left_boundary_ms=250.0,
        right_boundary_ms=250.0,
        left_level_dbfs=-39.0,
        right_level_dbfs=-39.0,
        low_level_dbfs=-80.0,
    )
    common = {
        "all_sample_rms": 0.1,
        "hard_clipped_fraction": 0.0,
        "longest_hard_clip_run_samples": 0,
        "maximum_channel_crackle_count": 0,
        "silent_frame_fraction": 0.0,
        "true_peak": 0.5,
    }
    passed = score_integrity_raw_metrics(dropout_candidates=[passing], **common)
    failed = score_integrity_raw_metrics(dropout_candidates=[almost], **common)
    assert passed["defects"]["dropout"]["flag"] is True
    assert passed["defects"]["dropout"]["margin"] == pytest.approx(0.0)
    assert failed["defects"]["dropout"]["flag"] is False
    assert failed["defects"]["dropout"]["margin"] == pytest.approx(-0.02)

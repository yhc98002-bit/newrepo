from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scoring.common import sha256_json
from scoring.decision_grade import (
    COMPLETE_SOURCE_STATUS,
    FROZEN_CONFIRMATORY_CELL_ROWS,
    PARTIAL_SOURCE_STATUS,
    REGISTERED_BACKBONES,
    SOURCE_BINDING_STATUS,
    WATERMARK,
    build_decision_grade_tables,
    load_bound_decision_grade_source,
    validate_output_language,
)

SA3 = "stable-audio-3-medium-base"
SAO = "stable-audio-open-1.0"
ACE = "ACE-Step v1"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _row(
    backbone: str,
    axis: str,
    cluster_index: int,
    root_index: int,
    *,
    condition: str | None = None,
) -> dict:
    alternating = (cluster_index + root_index) % 2 == 0
    active_condition = condition or ("BASE" if root_index == 0 else "FIXED")
    identity = f"{backbone}|{axis}|{cluster_index}|{root_index}|{active_condition}"
    common = {
        "audio_path": f"/immutable/{_digest(identity)}.wav",
        "audio_sha256": _digest(f"audio|{identity}"),
        "automatic_result": {},
        "axis": axis,
        "backbone": backbone,
        "cluster_id": f"{axis}-cluster-{cluster_index}",
        "condition": active_condition,
        "metrics": {},
        "prompt_id": f"{axis}-prompt-{cluster_index}",
        "prompt_metadata": {},
        "request_sha256": _digest(f"request|{identity}"),
        "root_index": root_index,
        "source_run_id": f"core-run-{_digest(backbone)[:12]}",
        "stratum": "all",
    }
    if axis == "vocal_instrumental":
        demucs = alternating
        panns = cluster_index == 0
        request = "instrumental" if active_condition == "NEGATION_DIAGNOSTIC" else (
            "vocal" if cluster_index == 0 else "instrumental"
        )
        common["prompt_metadata"] = {"request": request}
        common["metrics"] = {
            "automatic_instrument_success": alternating,
            "automatic_voice_presence": demucs or panns,
            "demucs_present": demucs,
            "panns_present": panns,
        }
    elif axis == "tempo":
        estimator_disagreement = cluster_index == 1 and root_index == 1
        common["prompt_metadata"] = {
            "salience": "percussive_regular" if cluster_index == 0 else "syncopated"
        }
        common["stratum"] = common["prompt_metadata"]["salience"]
        common["metrics"] = {
            "beat_this_primary_5pct_success": alternating,
            "first_window_primary_5pct_success": alternating,
            "first_window_sensitivity_10pct_success": True,
            "full_clip_abstention": estimator_disagreement,
            "full_clip_primary_5pct_success": alternating and not estimator_disagreement,
            "full_clip_sensitivity_10pct_success": not estimator_disagreement,
            "librosa_primary_5pct_success": cluster_index == 0,
            "second_window_primary_5pct_success": not alternating,
            "second_window_sensitivity_10pct_success": True,
            "window_drift_resolved": True,
        }
        common["automatic_result"] = {
            "full_clip": {
                "status": ("ESTIMATOR_DISAGREEMENT" if estimator_disagreement else "RESOLVED")
            },
            "raw_estimator_audit": {
                "full_clip": {
                    "beat_this": {"valid": True},
                    "librosa": {"valid": True},
                }
            },
            "window_drift": {
                "octave_invariant_absolute_drift": 0.01 * (cluster_index + root_index),
                "signed_drift_octaves": 0.01 * (cluster_index - root_index),
                "status": "RESOLVED",
            },
        }
    else:
        clipping = cluster_index == 0 and root_index == 0
        dropout = cluster_index == 1 and root_index == 1
        silence = cluster_index == 0 and root_index == 1
        crackle = False
        common["prompt_metadata"] = {
            "profile": "dense_loud" if cluster_index == 0 else "soft_sustained"
        }
        common["stratum"] = common["prompt_metadata"]["profile"]
        common["metrics"] = {
            "clipping_defect": clipping,
            "crackle_defect": crackle,
            "dropout_defect": dropout,
            "file_validity_failure": False,
            "integrity_failure": clipping or dropout or silence or crackle,
            "silence_defect": silence,
        }
    return common


def _fixture(backbones: tuple[str, ...]) -> list[dict]:
    primary = [
        _row(backbone, axis, cluster_index, root_index)
        for backbone in backbones
        for axis in ("vocal_instrumental", "tempo", "integrity")
        for cluster_index in range(2)
        for root_index in range(2)
    ]
    diagnostics = [
        _row(
            backbone,
            "vocal_instrumental",
            cluster_index,
            cluster_index,
            condition="NEGATION_DIAGNOSTIC",
        )
        for backbone in backbones
        for cluster_index in range(2)
    ]
    return primary + diagnostics


def _full_confirmatory_fixture(backbones: tuple[str, ...]) -> list[dict]:
    rows: list[dict] = []
    for backbone in backbones:
        for (axis, condition), count in FROZEN_CONFIRMATORY_CELL_ROWS.items():
            for index in range(count):
                root_index = index % 8
                cluster_index = index // 8
                row = _row(
                    backbone,
                    axis,
                    cluster_index,
                    root_index,
                    condition=condition,
                )
                identity = f"full|{backbone}|{axis}|{condition}|{index}"
                row.update(
                    {
                        "audio_path": f"/immutable/{_digest(identity)}.wav",
                        "audio_sha256": _digest(f"audio|{identity}"),
                        "request_sha256": _digest(f"request|{identity}"),
                    }
                )
                rows.append(row)
    return rows


def _cell_counts(rows: list[dict], backbone: str) -> dict[str, int]:
    return {
        f"{axis}|{condition}": sum(
            row["backbone"] == backbone
            and row["axis"] == axis
            and row["condition"] == condition
            for row in rows
        )
        for axis, condition in FROZEN_CONFIRMATORY_CELL_ROWS
    }


def _partial_binding(rows: list[dict]) -> dict:
    records = []
    for backbone in REGISTERED_BACKBONES:
        observed = sum(row["backbone"] == backbone for row in rows)
        records.append(
            {
                "backbone": backbone,
                "core_completion": (
                    "COMPLETED_SHARD_PREFIX_ONLY"
                    if observed
                    else "MISSING_REGISTERED_BACKBONE"
                ),
                "expected_completed_core_rows": observed or None,
                "expected_core_rows": 1536 if observed else None,
                "observed_confirmatory_cells": _cell_counts(rows, backbone),
                "observed_confirmatory_rows": observed,
                "scoring_backbone_status": (
                    "AUTOMATIC_ENDPOINTS_SCORED_PREFIX" if observed else "MISSING_SOURCE"
                ),
                "snapshot_core_rows": observed or None,
                "source_completion_mode": "INCREMENTAL_PREFIX" if observed else None,
                "source_run_id": f"core-run-{_digest(backbone)[:12]}" if observed else None,
            }
        )
    return {
        "all_registered_backbones_complete": False,
        "backbones": records,
        "binding_status": SOURCE_BINDING_STATUS,
        "normalized_rows_sha256": sha256_json({"rows": rows}),
        "registered_backbones": list(REGISTERED_BACKBONES),
        "source_completeness": PARTIAL_SOURCE_STATUS,
    }


def _build(backbones: tuple[str, ...]) -> dict:
    rows = _fixture(backbones)
    return build_decision_grade_tables(
        rows,
        source_binding=_partial_binding(rows),
        replicates=64,
        seed=2026072001,
        confidence_level=0.95,
    )


def test_primary_prevalence_is_condition_specific_at_both_tempo_bands() -> None:
    tables = _build((SA3, ACE))
    assert tables["included_backbones"] == [SA3, ACE]
    assert tables["missing_registered_backbones"] == [SAO]
    assert tables["source_completeness"] == PARTIAL_SOURCE_STATUS
    assert tables["status"] == "DECISION_GRADE_AUTOMATIC_TABLES_PARTIAL_VERIFIED_SOURCES"
    assert {row["condition"] for row in tables["prevalence"]} == {"BASE", "FIXED"}
    assert all(row["slice"] == "ALL" for row in tables["prevalence"])
    assert all(row["condition"] != "ALL" for row in tables["prevalence"])
    assert {
        (row["axis"], row["backbone"], row["condition"])
        for row in tables["prevalence"]
    } == {
        (axis, backbone, condition)
        for axis in ("vocal_instrumental", "tempo", "integrity")
        for backbone in (SA3, ACE)
        for condition in ("BASE", "FIXED")
    }
    for condition in ("BASE", "FIXED"):
        tempo_metrics = {
            row["metric"]
            for row in tables["prevalence"]
            if row["axis"] == "tempo" and row["condition"] == condition
        }
        assert {
            "full_clip_primary_5pct_success",
            "full_clip_sensitivity_10pct_success",
            "first_window_primary_5pct_success",
            "first_window_sensitivity_10pct_success",
            "second_window_primary_5pct_success",
            "second_window_sensitivity_10pct_success",
        } <= tempo_metrics


def test_negation_is_a_separate_diagnostic_and_cannot_change_primary_tables() -> None:
    rows = _fixture((SA3, ACE))
    before = build_decision_grade_tables(
        rows,
        source_binding=_partial_binding(rows),
        replicates=32,
        seed=7,
    )
    altered = json.loads(json.dumps(rows))
    for row in altered:
        if row["condition"] == "NEGATION_DIAGNOSTIC":
            row["metrics"]["automatic_instrument_success"] = not row["metrics"][
                "automatic_instrument_success"
            ]
            row["metrics"]["demucs_present"] = not row["metrics"]["demucs_present"]
    after = build_decision_grade_tables(
        altered,
        source_binding=_partial_binding(altered),
        replicates=32,
        seed=7,
    )
    for name in ("prevalence", "instrument_disagreement", "tempo_window_drift"):
        assert after[name] == before[name]
    assert after["negation_diagnostic_prevalence"] != before[
        "negation_diagnostic_prevalence"
    ]
    for row in after["negation_diagnostic_prevalence"]:
        assert row["axis"] == "vocal_instrumental"
        assert row["condition"] == "NEGATION_DIAGNOSTIC"
        assert row["analysis_role"] == "ESTIMATE_ONLY_DIAGNOSTIC"
        assert row["table_scope"] == "NEGATION_DIAGNOSTIC_PREVALENCE_SEPARATE_FROM_PRIMARY"


def test_drift_and_disagreement_are_condition_specific_and_watermarked() -> None:
    tables = _build((SA3, ACE))
    assert len(tables["tempo_window_drift"]) == 8
    assert {row["condition"] for row in tables["tempo_window_drift"]} == {"BASE", "FIXED"}
    assert {row["metric"] for row in tables["tempo_window_drift"]} == {
        "second_minus_first_signed_drift_octaves",
        "second_vs_first_octave_invariant_absolute_drift",
    }
    assert len(tables["instrument_disagreement"]) == 28
    assert {row["condition"] for row in tables["instrument_disagreement"]} == {
        "BASE",
        "FIXED",
    }
    assert len(tables["negation_diagnostic_instrument_disagreement"]) == 2
    comparisons = {row["comparison"] for row in tables["instrument_disagreement"]}
    assert "demucs_vs_panns_presence" in comparisons
    assert "beat_this_vs_librosa_estimator_disagreement" in comparisons
    assert "beat_this_vs_librosa_5pct_target_label" in comparisons
    assert {
        f"{defect}_defect_vs_four_defect_or"
        for defect in ("clipping", "dropout", "silence", "crackle")
    } <= comparisons
    for table_name in (
        "prevalence",
        "tempo_window_drift",
        "instrument_disagreement",
        "negation_diagnostic_prevalence",
        "negation_diagnostic_instrument_disagreement",
    ):
        assert tables[table_name]
        for row in tables[table_name]:
            assert row["watermark"] == WATERMARK
            assert row["source_completeness"] == PARTIAL_SOURCE_STATUS
            assert row["resampling_unit"] == "PROMPT_CLUSTER_THEN_MATCHED_SEED"
            assert row["cluster_count"] == 2
            assert row["ci_low"] is not None
            assert row["ci_high"] is not None


def test_sao_rows_expand_tables_without_changing_existing_backbone_rows() -> None:
    two = _build((SA3, ACE))
    three = _build((SA3, SAO, ACE))
    assert three["included_backbones"] == [SA3, SAO, ACE]
    assert three["missing_registered_backbones"] == []
    assert len(three["tempo_window_drift"]) == 12
    assert len(three["instrument_disagreement"]) == 42
    assert {row["backbone"] for row in three["prevalence"]} == {SA3, SAO, ACE}
    for table_name in (
        "prevalence",
        "tempo_window_drift",
        "instrument_disagreement",
        "negation_diagnostic_prevalence",
        "negation_diagnostic_instrument_disagreement",
    ):
        two_rows = {json.dumps(row, allow_nan=False, sort_keys=True) for row in two[table_name]}
        retained = [row for row in three[table_name] if row["backbone"] in {SA3, ACE}]
        assert {json.dumps(row, allow_nan=False, sort_keys=True) for row in retained} == two_rows


def test_output_language_is_fail_closed_and_contains_no_prohibited_claims() -> None:
    tables = _build((SA3, ACE))
    payload = json.dumps(tables, allow_nan=False, sort_keys=True).lower()
    assert WATERMARK.lower() in payload
    for token in ("accuracy", "human_gold", "human-gold", "human gold"):
        assert token not in payload
    altered = {**tables, "accuracy": "forbidden"}
    with pytest.raises(ValueError, match="prohibited token"):
        validate_output_language(altered)


def test_input_contract_requires_unique_request_and_source_identities() -> None:
    rows = _fixture((SA3,))
    rows[0]["backbone"] = "unregistered-fourth-backbone"
    with pytest.raises(ValueError, match="unregistered backbone"):
        build_decision_grade_tables(
            rows, source_binding=_partial_binding(rows), replicates=8, seed=1
        )

    rows = _fixture((SA3,))
    rows[1]["request_sha256"] = rows[0]["request_sha256"]
    with pytest.raises(ValueError, match="duplicate request"):
        build_decision_grade_tables(
            rows, source_binding=_partial_binding(rows), replicates=8, seed=1
        )

    rows = _fixture((SA3,))
    del rows[0]["source_run_id"]
    with pytest.raises(ValueError, match="source_run_id"):
        build_decision_grade_tables(
            rows, source_binding=_partial_binding(rows), replicates=8, seed=1
        )


def test_binding_is_required_and_cannot_make_tiny_input_complete() -> None:
    rows = _fixture((SA3, SAO, ACE))
    with pytest.raises(ValueError, match="verified source binding is required"):
        build_decision_grade_tables(rows, replicates=8, seed=1)

    forged = _partial_binding(rows)
    forged["all_registered_backbones_complete"] = True
    forged["source_completeness"] = COMPLETE_SOURCE_STATUS
    for record in forged["backbones"]:
        record.update(
            {
                "core_completion": "COMPLETE_FROZEN_CORE",
                "expected_completed_core_rows": 1536,
                "expected_core_rows": 1536,
                "scoring_backbone_status": "AUTOMATIC_ENDPOINTS_SCORED",
                "snapshot_core_rows": 1536,
            }
        )
    with pytest.raises(ValueError, match="invalid completeness claim"):
        build_decision_grade_tables(
            rows, source_binding=forged, replicates=8, seed=1
        )


def _write_bound_source_artifacts(
    tmp_path: Path, rows: list[dict], *, complete_core: bool = False
) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    input_path = tmp_path / "automatic-endpoint-outcomes.jsonl"
    input_path.write_text(
        "".join(json.dumps(row, allow_nan=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    observed_backbones = [
        backbone
        for backbone in REGISTERED_BACKBONES
        if any(row["backbone"] == backbone for row in rows)
    ]
    config_sources = []
    snapshot_sources = []
    for backbone in observed_backbones:
        run_id = f"core-run-{_digest(backbone)[:12]}"
        count = sum(row["backbone"] == backbone for row in rows)
        source_count = 1536 if complete_core else count
        config_sources.append(
            {
                "backbone": backbone,
                "completion_mode": "FULL" if complete_core else "INCREMENTAL_PREFIX",
                "expected_completed_rows": source_count,
                "expected_queue_rows": 1536,
                "run_id": run_id,
            }
        )
        snapshot_sources.append(
            {
                "backbone": backbone,
                "completion_mode": "FULL" if complete_core else "INCREMENTAL_PREFIX",
                "row_count": source_count,
                "run_id": run_id,
            }
        )
    config = {
        "primary_backbones": list(REGISTERED_BACKBONES),
        "run_id": "automatic-scoring-test",
        "schema_version": 2,
        "sources": config_sources,
    }
    config_path = tmp_path / "scoring-config.json"
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")

    source_ledger = _digest("source-ledger")
    snapshot_rows = [
        {
            key: row[key]
            for key in (
                "audio_sha256",
                "axis",
                "backbone",
                "cluster_id",
                "condition",
                "prompt_id",
                "request_sha256",
                "root_index",
                "source_run_id",
            )
        }
        for row in rows
    ]
    if complete_core:
        for backbone in observed_backbones:
            run_id = f"core-run-{_digest(backbone)[:12]}"
            for index in range(1536 - sum(FROZEN_CONFIRMATORY_CELL_ROWS.values())):
                snapshot_rows.append(
                    {
                        "axis": "structure_exploratory",
                        "backbone": backbone,
                        "request_sha256": _digest(f"structure|{backbone}|{index}"),
                        "source_run_id": run_id,
                    }
                )
    snapshot = {
        "rows": snapshot_rows,
        "schema_version": 1,
        "source_ledger_sha256": source_ledger,
        "sources": snapshot_sources,
    }
    snapshot["snapshot_sha256"] = sha256_json(snapshot)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")

    missing = [backbone for backbone in REGISTERED_BACKBONES if backbone not in observed_backbones]
    status_rows = []
    for backbone in REGISTERED_BACKBONES:
        observed = sum(row["backbone"] == backbone for row in rows)
        status_rows.append(
            {
                "backbone": backbone,
                "scored_rows": observed,
                "status": (
                    "AUTOMATIC_ENDPOINTS_SCORED"
                    if observed and complete_core
                    else (
                        "AUTOMATIC_ENDPOINTS_SCORED_PREFIX" if observed else "MISSING_SOURCE"
                    )
                ),
            }
        )
    status = {
        "backbones": status_rows,
        "incomplete_primary_backbones": [] if complete_core else observed_backbones,
        "missing_primary_backbones": missing,
        "schema_version": 1,
        "source_ledger_sha256": source_ledger,
        "status": (
            "SCORING_COMPLETE_ALL_PRIMARY_BACKBONES"
            if complete_core and not missing
            else "SCORING_INCREMENTAL_PRIMARY_PREFIX"
        ),
    }
    status_path = tmp_path / "scoring-status.json"
    status_path.write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    return {
        "config": config_path,
        "input": input_path,
        "snapshot": snapshot_path,
        "status": status_path,
    }


def test_loader_binds_exact_snapshot_rows_and_labels_partial_sources(tmp_path: Path) -> None:
    rows = _fixture((SA3,))
    paths = _write_bound_source_artifacts(tmp_path, rows)
    loaded, binding = load_bound_decision_grade_source(
        paths["input"],
        scoring_config_path=paths["config"],
        scoring_status_path=paths["status"],
        source_snapshot_path=paths["snapshot"],
    )
    assert loaded == rows
    assert binding["source_completeness"] == PARTIAL_SOURCE_STATUS
    assert binding["all_registered_backbones_complete"] is False
    tables = build_decision_grade_tables(
        loaded, source_binding=binding, replicates=8, seed=1
    )
    assert tables["status"] == "DECISION_GRADE_AUTOMATIC_TABLES_PARTIAL_VERIFIED_SOURCES"


def test_loader_allows_complete_only_for_exact_three_backbone_frozen_cells(
    tmp_path: Path,
) -> None:
    rows = _full_confirmatory_fixture((SA3, SAO, ACE))
    paths = _write_bound_source_artifacts(tmp_path, rows, complete_core=True)
    loaded, binding = load_bound_decision_grade_source(
        paths["input"],
        scoring_config_path=paths["config"],
        scoring_status_path=paths["status"],
        source_snapshot_path=paths["snapshot"],
    )
    assert loaded == rows
    assert binding["all_registered_backbones_complete"] is True
    assert binding["source_completeness"] == COMPLETE_SOURCE_STATUS
    assert {row["core_completion"] for row in binding["backbones"]} == {
        "COMPLETE_FROZEN_CORE"
    }
    tables = build_decision_grade_tables(
        loaded, source_binding=binding, replicates=2, seed=11
    )
    assert tables["status"] == (
        "DECISION_GRADE_AUTOMATIC_TABLES_COMPLETE_ALL_THREE_PRIMARY_BACKBONES"
    )
    assert tables["source_completeness"] == COMPLETE_SOURCE_STATUS


def test_loader_rejects_truncated_input_and_mismatched_source_ledger(tmp_path: Path) -> None:
    rows = _fixture((SA3,))
    paths = _write_bound_source_artifacts(tmp_path, rows)
    paths["input"].write_text(
        "".join(
            json.dumps(row, allow_nan=False, sort_keys=True) + "\n" for row in rows[:-1]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="differs from completed-snapshot"):
        load_bound_decision_grade_source(
            paths["input"],
            scoring_config_path=paths["config"],
            scoring_status_path=paths["status"],
            source_snapshot_path=paths["snapshot"],
        )

    paths = _write_bound_source_artifacts(tmp_path / "second", rows)
    status = json.loads(paths["status"].read_text(encoding="utf-8"))
    status["source_ledger_sha256"] = _digest("different-ledger")
    paths["status"].write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="source ledgers differ"):
        load_bound_decision_grade_source(
            paths["input"],
            scoring_config_path=paths["config"],
            scoring_status_path=paths["status"],
            source_snapshot_path=paths["snapshot"],
        )


def test_cli_loader_rejects_one_row_complete_claim(tmp_path: Path) -> None:
    rows = [_row(SA3, "tempo", 0, 0)]
    paths = _write_bound_source_artifacts(tmp_path, rows)
    status = json.loads(paths["status"].read_text(encoding="utf-8"))
    status["backbones"][0]["status"] = "AUTOMATIC_ENDPOINTS_SCORED"
    status["incomplete_primary_backbones"] = []
    paths["status"].write_text(json.dumps(status, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="claims complete automatic endpoints"):
        load_bound_decision_grade_source(
            paths["input"],
            scoring_config_path=paths["config"],
            scoring_status_path=paths["status"],
            source_snapshot_path=paths["snapshot"],
        )


def test_generator_module_does_not_bind_a_live_scored_input_path() -> None:
    source = Path("src/scoring/decision_grade.py").read_text(encoding="utf-8")
    assert "benchmark_v2_runtime/runs/scoring" not in source

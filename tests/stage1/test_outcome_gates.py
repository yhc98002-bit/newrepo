from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scoring.common import load_json, sha256_file
from stage1.gates import (
    AXES,
    BACKBONES,
    GATE_RULE,
    GatePolicy,
    Stage1SpecificationError,
    compute_gate_results,
    load_gate_policy,
    plan_cancellations,
    write_stage1_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]


def _statistics() -> dict[str, object]:
    return {
        "eligibility": {
            "prompt_selection": {
                "axis_prompt_ids": {
                    axis: [f"{axis}-prompt-{index:02d}" for index in range(12)]
                    for axis in AXES
                }
            }
        }
    }


def _rows() -> list[dict[str, object]]:
    stopped = {
        ("stable-audio-3-medium-base", "integrity"),
        ("ACE-Step v1", "tempo"),
    }
    rows: list[dict[str, object]] = []
    prompt_ids = _statistics()["eligibility"]["prompt_selection"]["axis_prompt_ids"]
    for backbone in BACKBONES:
        for axis in AXES:
            for prompt_index, prompt_id in enumerate(prompt_ids[axis]):
                for root in range(8):
                    failure = False if (backbone, axis) in stopped else root % 2 == 0
                    if axis == "integrity":
                        metrics = {
                            "file_validity_failure": False,
                            "integrity_failure": failure,
                        }
                    elif axis == "tempo":
                        metrics = {"full_clip_primary_5pct_success": not failure}
                    else:
                        metrics = {"automatic_instrument_success": not failure}
                    rows.append(
                        {
                            "axis": axis,
                            "backbone": backbone,
                            "condition": "BASE",
                            "metrics": metrics,
                            "prompt_id": prompt_id,
                            "root_index": root,
                            "stratum": (
                                "all"
                                if axis == "vocal_instrumental"
                                else f"s{prompt_index % 3}"
                            ),
                        }
                    )
    return rows


def _policy() -> GatePolicy:
    return GatePolicy(
        decision_id="D-TEST",
        baseline_failure_rate_minimum=0.25,
        mixed_outcome_prompt_share_minimum=0.25,
        bootstrap_replicates=50,
        bootstrap_seed=123,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _queue_bindings(tmp_path: Path) -> list[dict[str, str]]:
    prompt_ids = _statistics()["eligibility"]["prompt_selection"]["axis_prompt_ids"]
    bindings: list[dict[str, str]] = []
    for backbone in BACKBONES:
        path = tmp_path / f"{backbone.replace(' ', '-')}.jsonl"
        queue_rows = []
        for axis in AXES:
            for prompt in prompt_ids[axis]:
                for root in range(4):
                    for checkpoint in (0.25, 0.5, 0.75):
                        identity = f"{backbone}|{axis}|{prompt}|{root}|{checkpoint}"
                        queue_rows.append(
                            {
                                "axis": axis,
                                "eligibility_unit": {
                                    "checkpoint": checkpoint,
                                    "prompt": prompt,
                                    "root": root,
                                },
                                "lane_request_sha256": hashlib.sha256(
                                    identity.encode()
                                ).hexdigest(),
                            }
                        )
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in queue_rows),
            encoding="utf-8",
        )
        bindings.append(
            {"backbone": backbone, "path": str(path), "sha256": sha256_file(path)}
        )
    return bindings


def test_committed_configuration_is_deliberately_fail_closed() -> None:
    path = ROOT / "configs" / "stage1_outcome_gates_v2.json"
    value = load_json(path)
    assert value["status"] == "BLOCKED_MISSING_FROZEN_THRESHOLDS"
    assert value["decision_id"] is None
    assert set(value["thresholds"].values()) == {None}
    with pytest.raises(Stage1SpecificationError, match="not frozen"):
        load_gate_policy(path)


def test_policy_requires_both_explicit_frozen_thresholds(tmp_path: Path) -> None:
    value = load_json(ROOT / "configs" / "stage1_outcome_gates_v2.json")
    value["status"] = "FROZEN"
    value["decision_id"] = "D-TEST"
    path = tmp_path / "policy.json"
    _write_json(path, value)
    with pytest.raises(Stage1SpecificationError, match="must be numeric"):
        load_gate_policy(path)

    value["thresholds"] = {
        "baseline_failure_rate_minimum": 0.25,
        "mixed_outcome_prompt_share_minimum": 0.5,
    }
    _write_json(path, value)
    policy = load_gate_policy(path)
    assert policy.decision_id == "D-TEST"
    assert policy.baseline_failure_rate_minimum == 0.25
    assert policy.mixed_outcome_prompt_share_minimum == 0.5
    assert value["gate_rule"] == GATE_RULE


def test_six_cells_are_deterministic_and_use_selected_base_rows_only() -> None:
    rows = _rows()
    # Non-BASE and non-selected rows may exist but cannot influence the gate.
    rows.extend(
        [
            {**rows[0], "condition": "FIXED"},
            {**rows[0], "prompt_id": "not-selected"},
        ]
    )
    first = compute_gate_results(rows, _statistics(), _policy())
    second = compute_gate_results(rows, _statistics(), _policy())
    assert first == second
    assert len(first) == 6
    stopped = {
        (row["backbone"], row["axis"])
        for row in first
        if row["verdict"] == "STOP_AXIS_STAGE1"
    }
    assert stopped == {
        ("stable-audio-3-medium-base", "integrity"),
        ("ACE-Step v1", "tempo"),
    }
    for row in first:
        assert row["watermark"] == "AUTOMATIC-INSTRUMENT OUTCOMES"
        assert row["human_gold_claims"] is False
        assert row["prompt_count"] == 12
        assert row["root_count_per_prompt"] == 8
        if (row["backbone"], row["axis"]) in stopped:
            assert row["baseline_failure_rate"]["point"] == 0.0
            assert row["mixed_outcome_prompt_share"]["point"] == 0.0
        else:
            assert row["baseline_failure_rate"]["point"] == 0.5
            assert row["mixed_outcome_prompt_share"]["point"] == 1.0


def test_missing_or_duplicate_selected_rows_are_fatal() -> None:
    rows = _rows()
    with pytest.raises(ValueError, match="expected 96"):
        compute_gate_results(rows[:-1], _statistics(), _policy())
    duplicate = [*rows, dict(rows[0])]
    with pytest.raises(ValueError, match="expected 96"):
        compute_gate_results(duplicate, _statistics(), _policy())


def test_integrity_invalid_file_is_counted_as_failure_not_dropped() -> None:
    rows = _rows()
    target = next(
        row
        for row in rows
        if row["backbone"] == "stable-audio-3-medium-base"
        and row["axis"] == "integrity"
        and row["root_index"] == 0
    )
    target["metrics"] = {
        "file_validity_failure": True,
        "integrity_failure": None,
    }
    results = compute_gate_results(rows, _statistics(), _policy())
    cell = next(
        row
        for row in results
        if row["backbone"] == "stable-audio-3-medium-base"
        and row["axis"] == "integrity"
    )
    assert cell["baseline_failure_rate"]["point"] == pytest.approx(1 / 96)


def test_stop_units_form_exact_no_execute_no_score_plan(tmp_path: Path) -> None:
    results = compute_gate_results(_rows(), _statistics(), _policy())
    cancellations = plan_cancellations(results, _queue_bindings(tmp_path))
    assert len(cancellations) == 288
    assert all(row["status"] == "CANCELLED_STAGE1" for row in cancellations)
    assert all(row["prohibited_operations"] == ["EXECUTE", "SCORE"] for row in cancellations)
    identities = {
        (
            row["backbone"],
            row["axis"],
            row["eligibility_unit"]["prompt"],
            row["eligibility_unit"]["root"],
            row["eligibility_unit"]["checkpoint"],
        )
        for row in cancellations
    }
    assert len(identities) == len(cancellations)


def test_artifacts_are_no_clobber_and_cancellations_are_hash_chained(tmp_path: Path) -> None:
    results = compute_gate_results(_rows(), _statistics(), _policy())
    cancellations = plan_cancellations(results, _queue_bindings(tmp_path))[:2]
    output = tmp_path / "stage1"
    summary = write_stage1_artifacts(
        output,
        results=results,
        cancellations=cancellations,
        provenance={"fixture": True},
    )
    assert summary["cancelled_unit_count"] == 2
    events = sorted((output / "cancellations" / "events").glob("[0-9]*-*.json"))
    assert len(events) == 2
    first = load_json(events[0])
    second = load_json(events[1])
    assert first["previous_event_sha256"] == "0" * 64
    assert second["previous_event_sha256"] == first["event_sha256"]
    with pytest.raises(FileExistsError):
        write_stage1_artifacts(
            output,
            results=results,
            cancellations=[],
            provenance={"fixture": True},
        )


def test_report_and_readiness_do_not_claim_obtained_verdicts() -> None:
    report = (ROOT / "STAGE1_OUTCOME_GATES.md").read_text(encoding="utf-8")
    readiness = load_json(ROOT / "provenance" / "stage1" / "stage1_outcome_gate_readiness.json")
    assert readiness["status"] == "BLOCKED_MISSING_FROZEN_THRESHOLDS"
    assert readiness["verdicts_computed"] is False
    assert readiness["cancellation_ledger_created"] is False
    assert "No Stage-1 cell verdict has been computed" in report
    assert "No cancellation ledger has been created" in report

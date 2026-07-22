from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scoring.common import load_json, sha256_file
from scripts import run_stage1_outcome_gates
from stage1.gates import (
    AXES,
    BACKBONES,
    FROZEN_BASELINE_FAILURE_MAXIMUM,
    FROZEN_BASELINE_FAILURE_MINIMUM,
    FROZEN_MIXED_PROMPT_MINIMUM,
    GATE_RULE,
    MIXED_OUTCOME_PROMPT_DEFINITION,
    POLICY_SCHEMA_SHA256,
    GatePolicy,
    Stage1SpecificationError,
    compute_gate_results,
    gate_verdict,
    load_gate_policy,
    plan_cancellations,
    plan_survivors,
    policy_decision_assignments,
    verify_policy_decision,
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
        baseline_failure_rate_maximum=0.75,
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


def test_committed_configuration_is_frozen_before_outcome_execution() -> None:
    path = ROOT / "configs" / "stage1_outcome_gates_v2.json"
    value = load_json(path)
    assert value["status"] == "FROZEN"
    assert value["decision_id"] == "D-0046"
    assert value["schema_version"] == 2
    assert value["schema_binding"]["sha256"] == POLICY_SCHEMA_SHA256
    assert value["thresholds"] == {
        "baseline_failure_rate_maximum": FROZEN_BASELINE_FAILURE_MAXIMUM,
        "baseline_failure_rate_minimum": FROZEN_BASELINE_FAILURE_MINIMUM,
        "mixed_outcome_prompt_share_minimum": FROZEN_MIXED_PROMPT_MINIMUM,
    }
    policy = load_gate_policy(path)
    assert policy.baseline_failure_rate_minimum == 0.10
    assert policy.baseline_failure_rate_maximum == 0.60
    assert policy.mixed_outcome_prompt_share_minimum == 0.20


def test_policy_json_schema_freezes_the_same_complete_rule() -> None:
    schema_path = ROOT / "configs" / "stage1_outcome_gates_v2.schema.json"
    schema = load_json(schema_path)
    assert sha256_file(schema_path) == POLICY_SCHEMA_SHA256
    assert schema["properties"]["decision_id"]["const"] == "D-0046"
    assert schema["properties"]["thresholds"]["const"] == {
        "baseline_failure_rate_maximum": 0.60,
        "baseline_failure_rate_minimum": 0.10,
        "mixed_outcome_prompt_share_minimum": 0.20,
    }
    assert schema["properties"]["gate_rule"]["const"] == GATE_RULE


def test_policy_rejects_an_incomplete_or_changed_frozen_policy(tmp_path: Path) -> None:
    value = load_json(ROOT / "configs" / "stage1_outcome_gates_v2.json")
    path = tmp_path / "policy.json"
    value["thresholds"]["baseline_failure_rate_maximum"] = None
    _write_json(path, value)
    with pytest.raises(Stage1SpecificationError, match="must be numeric"):
        load_gate_policy(path)

    value["thresholds"] = {
        "baseline_failure_rate_maximum": 0.61,
        "baseline_failure_rate_minimum": 0.10,
        "mixed_outcome_prompt_share_minimum": 0.20,
    }
    _write_json(path, value)
    with pytest.raises(Stage1SpecificationError, match="D-0046 freeze"):
        load_gate_policy(path)


def test_gate_boundaries_are_inclusive_and_upper_excess_stops() -> None:
    policy = GatePolicy(
        decision_id="D-0046",
        baseline_failure_rate_minimum=0.10,
        baseline_failure_rate_maximum=0.60,
        mixed_outcome_prompt_share_minimum=0.20,
    )
    assert gate_verdict(0.10, 0.20, policy) == "OUTCOME_SCREEN_PASS"
    assert gate_verdict(0.60, 0.20, policy) == "OUTCOME_SCREEN_PASS"
    assert gate_verdict(0.099999, 1.0, policy) == "STOP_AXIS_STAGE1"
    assert gate_verdict(0.600001, 1.0, policy) == "STOP_AXIS_STAGE1"
    assert gate_verdict(0.50, 0.199999, policy) == "STOP_AXIS_STAGE1"


def test_runner_validates_policy_before_any_input_binding_or_outcome_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def reject_policy(path: Path) -> GatePolicy:
        calls.append(f"policy:{path.name}")
        raise Stage1SpecificationError("sentinel invalid policy")

    def forbidden_bindings(path: Path) -> dict[str, object]:
        calls.append(f"bindings:{path.name}")
        raise AssertionError("bindings and outcome files must not be touched")

    monkeypatch.setattr(run_stage1_outcome_gates, "load_gate_policy", reject_policy)
    monkeypatch.setattr(run_stage1_outcome_gates, "validated_bindings", forbidden_bindings)
    with pytest.raises(Stage1SpecificationError, match="sentinel"):
        run_stage1_outcome_gates.run(
            tmp_path / "invalid.json",
            tmp_path / "output",
            decisions_path=tmp_path / "DECISIONS.md",
        )
    assert calls == ["policy:invalid.json"]


def test_runner_verifies_decision_before_any_input_binding_or_outcome_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def frozen_policy(path: Path) -> GatePolicy:
        calls.append("policy")
        return _policy()

    def reject_decision(
        config_path: Path, decisions_path: Path, *, policy: GatePolicy
    ) -> dict[str, str]:
        calls.append("decision")
        raise Stage1SpecificationError("sentinel missing decision")

    def forbidden_bindings(path: Path) -> dict[str, object]:
        calls.append("bindings")
        raise AssertionError("outcome bindings must not be touched")

    monkeypatch.setattr(run_stage1_outcome_gates, "load_gate_policy", frozen_policy)
    monkeypatch.setattr(run_stage1_outcome_gates, "verify_policy_decision", reject_decision)
    monkeypatch.setattr(run_stage1_outcome_gates, "validated_bindings", forbidden_bindings)
    with pytest.raises(Stage1SpecificationError, match="sentinel missing decision"):
        run_stage1_outcome_gates.run(
            tmp_path / "config.json",
            tmp_path / "output",
            decisions_path=tmp_path / "DECISIONS.md",
        )
    assert calls == ["policy", "decision"]


def test_policy_decision_binds_exact_config_before_outcome_read(tmp_path: Path) -> None:
    config_path = ROOT / "configs" / "stage1_outcome_gates_v2.json"
    decisions_path = tmp_path / "DECISIONS.md"
    assignments = policy_decision_assignments(config_path)
    decisions_path.write_text(
        "## D-0046 — Stage-1 outcome-screen policy freeze\n\n"
        + "\n".join(assignments)
        + "\n",
        encoding="utf-8",
    )
    receipt = verify_policy_decision(config_path, decisions_path)
    assert receipt["decision_id"] == "D-0046"
    decisions_path.write_text(
        decisions_path.read_text(encoding="utf-8").replace(
            "STAGE1_BASELINE_FAILURE_RATE_MAXIMUM = 0.60",
            "STAGE1_BASELINE_FAILURE_RATE_MAXIMUM = 0.61",
        ),
        encoding="utf-8",
    )
    with pytest.raises(Stage1SpecificationError, match="complete frozen config"):
        verify_policy_decision(config_path, decisions_path)


def test_policy_decision_hash_survives_append_only_suffix(tmp_path: Path) -> None:
    config_path = ROOT / "configs" / "stage1_outcome_gates_v2.json"
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(
        "## D-0046 — Stage-1 outcome-screen policy freeze\n\n"
        + "\n".join(policy_decision_assignments(config_path))
        + "\n",
        encoding="utf-8",
    )
    before = verify_policy_decision(config_path, decisions_path)
    with decisions_path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n## D-0047 — Later append-only decision\n\nLater evidence.\n")
    after = verify_policy_decision(config_path, decisions_path)
    assert after["decision_block_sha256"] == before["decision_block_sha256"]


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
        assert row["baseline_failure_rate"]["maximum"] == 0.75
        assert (
            row["mixed_outcome_prompt_share"]["definition"]
            == MIXED_OUTCOME_PROMPT_DEFINITION
        )
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
    bindings = _queue_bindings(tmp_path)
    results = compute_gate_results(_rows(), _statistics(), _policy())
    cancellations = plan_cancellations(results, bindings)
    survivors = plan_survivors(results, bindings)
    assert len(cancellations) == 288
    assert sum(len(rows) for rows in survivors.values()) == 576
    assert all(len(rows) == 288 for rows in survivors.values())
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
    bindings = _queue_bindings(tmp_path)
    results = compute_gate_results(_rows(), _statistics(), _policy())
    cancellations = plan_cancellations(results, bindings)
    survivors = plan_survivors(results, bindings)
    output = tmp_path / "stage1"
    summary = write_stage1_artifacts(
        output,
        results=results,
        cancellations=cancellations,
        survivors=survivors,
        queue_bindings=bindings,
        provenance={"fixture": True},
    )
    assert summary["cancelled_unit_count"] == 288
    events = sorted((output / "cancellations" / "events").glob("[0-9]*-*.json"))
    assert len(events) == 288
    first = load_json(events[0])
    second = load_json(events[1])
    assert first["previous_event_sha256"] == "0" * 64
    assert second["previous_event_sha256"] == first["event_sha256"]
    with pytest.raises(FileExistsError):
        write_stage1_artifacts(
            output,
            results=results,
            cancellations=cancellations,
            survivors=survivors,
            queue_bindings=bindings,
            provenance={"fixture": True},
        )


def test_survivor_manifests_are_exact_and_hash_bound(tmp_path: Path) -> None:
    bindings = _queue_bindings(tmp_path)
    results = compute_gate_results(_rows(), _statistics(), _policy())
    survivors = plan_survivors(results, bindings)
    output = tmp_path / "stage1"
    write_stage1_artifacts(
        output,
        results=results,
        cancellations=plan_cancellations(results, bindings),
        survivors=survivors,
        queue_bindings=bindings,
        provenance={"fixture": True},
    )
    for backbone, slug in {
        "ACE-Step v1": "ace-step-v1",
        "stable-audio-3-medium-base": "stable-audio-3-medium-base",
    }.items():
        manifest = load_json(output / "survivors" / slug / "manifest.json")
        units_path = Path(manifest["units_path"])
        assert manifest["backbone"] == backbone
        assert manifest["unit_count"] == len(survivors[backbone])
        assert manifest["units_sha256"] == sha256_file(units_path)
        assert units_path.stat().st_mode & 0o222 == 0


def test_report_seals_obtained_verdicts_and_preserves_historical_readiness() -> None:
    report = (ROOT / "STAGE1_OUTCOME_GATES.md").read_text(encoding="utf-8")
    readiness = load_json(ROOT / "provenance" / "stage1" / "stage1_outcome_gate_readiness.json")
    terminal = load_json(
        ROOT / "provenance" / "stage1" / "stage1_outcome_gates_terminal_v2.json"
    )
    assert readiness["status"] == "BLOCKED_MISSING_FROZEN_THRESHOLDS"
    assert readiness["verdicts_computed"] is False
    assert readiness["cancellation_ledger_created"] is False
    assert terminal["status"] == "STAGE1_OUTCOME_GATES_COMPLETE"
    assert terminal["stop_cell_count"] == 4
    assert terminal["cancelled_unit_count"] == 576
    assert terminal["human_gold_claims"] is False
    assert terminal["watermark"] == "AUTOMATIC-INSTRUMENT OUTCOMES"
    assert "STAGE1_OUTCOME_GATES_COMPLETE" in report
    assert "OUTCOME_SCREEN_PASS" in report
    assert "STOP_AXIS_STAGE1" in report
    assert "automatic-instrument outcome screens" in report

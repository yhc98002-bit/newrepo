from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmark_core.queue import canonical_json
from state_capture.ace_queue import (
    ACTIONS,
    CONFIG_CLOSED,
    EXPECTED_ACTION_ROWS,
    EXPECTED_GROUPS,
    EXPECTED_UNITS,
    MODEL_ID,
    PREVIEW_SOURCE,
    RESTART_LABEL,
    RESTART_ROOTS,
    AceStateQueueError,
    build_rows,
    load_queue_config,
    sha256_file,
    validate_d0033_opening,
    validate_preflight_pass,
    validate_rows,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "ace_state_capture_v2.json"


@pytest.fixture(scope="module")
def config() -> Any:
    return load_queue_config(CONFIG, repo_root=ROOT)


@pytest.fixture(scope="module")
def rows(config: Any) -> tuple[list[dict[str, Any]], ...]:
    return build_rows(config)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n")


def _with_identity(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = hashlib.sha256(canonical_json(result).encode()).hexdigest()
    return result


def test_static_config_is_closed_and_explicitly_rejects_wrong_legacy_queue(config: Any) -> None:
    assert config.raw["execution_status"] == CONFIG_CLOSED
    assert (
        config.raw["authorization_contract"]["execution_authorized_by_this_config_alone"]
        is False
    )
    assert config.raw["authorization_contract"]["automatic_retry_allowed"] is False
    assert config.raw["source_core_run"]["legacy_initial_state_queue"]["disposition"] == (
        "REJECT_MODEL_ID_IS_SA3_NOT_ACE"
    )
    first = json.loads(config.legacy_state_queue_path.read_text().splitlines()[0])
    assert first["model_id"] == "stabilityai/stable-audio-3-medium-base"
    assert first["model_id"] != MODEL_ID
    assert config.raw["placement"]["allowed_nodes"] == ["an12"]
    assert config.raw["placement"]["allowed_physical_gpu_ids"] == [4, 5, 6, 7]
    assert config.raw["placement"]["tp_width"] == 1


def test_fresh_ace_queue_has_exact_initial_units_and_base_root_local_previews(
    rows: tuple[list[dict[str, Any]], ...],
) -> None:
    units, groups, actions, folds = rows
    assert len(units) == EXPECTED_UNITS == 432
    assert len(groups) == EXPECTED_GROUPS == 144
    assert len(actions) == EXPECTED_ACTION_ROWS == 1296
    assert len(folds["rows"]) == 36
    assert {unit["model_id"] for unit in units} == {MODEL_ID}
    assert {unit["condition"] for unit in units} == {"BASE"}
    assert {unit["source_queue_derivation"] for unit in units} == {
        "FRESH_ACE_CORE_GENERATION_QUEUE"
    }
    assert all(
        unit["preview_source"] == PREVIEW_SOURCE
        and unit["preview_source_request_sha256"] == unit["parent_request_sha256"]
        and unit["feature_contract"]["root_local_only"] is True
        for unit in units
    )
    assert Counter(unit["axis"] for unit in units) == {
        "vocal_instrumental": 144,
        "tempo": 144,
        "integrity": 144,
    }
    assert {
        (
            unit["eligibility_unit"]["prompt"],
            unit["eligibility_unit"]["root"],
            unit["eligibility_unit"]["checkpoint"],
        )
        for unit in units
    } == {
        (unit["prompt_id"], unit["root_index"], unit["checkpoint_fraction"])
        for unit in units
    }


def test_replicated_actions_use_all_prompt_pool_roots_and_never_single_draw(
    rows: tuple[list[dict[str, Any]], ...],
) -> None:
    units, _groups, actions, _folds = rows
    by_unit: defaultdict[str, set[str]] = defaultdict(set)
    pool_usage: defaultdict[tuple[str, float, str], list[int]] = defaultdict(list)
    for action in actions:
        by_unit[action["lane_request_sha256"]].add(action["action"])
        if action["action"].startswith("RESTART_"):
            assert action["outcome_label"] == RESTART_LABEL
            assert action["outcome_source"] == "FROZEN_PROMPT_LEVEL_CORE_TERMINAL_POOL"
            assert action["restart_pool_root_indices"] == list(RESTART_ROOTS)
            pool_usage[
                (
                    action["prompt_id"],
                    action["checkpoint_fraction"],
                    action["action"],
                )
            ].append(action["outcome_source_root_index"])
    assert set(by_unit) == {unit["lane_request_sha256"] for unit in units}
    assert all(value == set(ACTIONS) for value in by_unit.values())
    assert len(pool_usage) == 36 * 3 * 2
    assert all(sorted(value) == list(RESTART_ROOTS) for value in pool_usage.values())


def test_folds_are_whole_prompt_grouped_two_per_axis_and_supplemental_is_not_built(
    rows: tuple[list[dict[str, Any]], ...],
    config: Any,
) -> None:
    units, _groups, _actions, folds = rows
    prompt_folds = {
        (row["axis"], row["prompt_id"]): row["fold_id"] for row in folds["rows"]
    }
    assert Counter((axis, fold) for (axis, _prompt), fold in prompt_folds.items()) == {
        (axis, fold): 2
        for axis in ("vocal_instrumental", "tempo", "integrity")
        for fold in range(6)
    }
    assert all(unit["fold_id"] == prompt_folds[(unit["axis"], unit["prompt_id"])] for unit in units)
    assert config.raw["authorization_contract"]["supplemental_queue_status"].startswith(
        "LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
    )
    assert {unit["root_index"] for unit in units} == {0, 1, 2, 3}


def test_row_revalidation_rejects_nonlocal_preview(
    rows: tuple[list[dict[str, Any]], ...],
) -> None:
    units, groups, actions, folds = rows
    changed = [dict(row) for row in units]
    changed[0] = {**changed[0], "preview_source_request_sha256": "0" * 64}
    with pytest.raises(AceStateQueueError, match="identity hash mismatch|root-local"):
        validate_rows(changed, groups, actions, folds)


def test_pass_gate_fails_closed_when_the_sole_terminal_does_not_exist(
    config: Any, tmp_path: Path
) -> None:
    absent = tmp_path / "ace-state-preflight-v2-one-attempt.terminal.json"
    with pytest.raises((AceStateQueueError, FileNotFoundError)):
        validate_preflight_pass(
            config,
            terminal_path=absent,
            expected_terminal_sha256="0" * 64,
        )


def test_synthetic_pass_chain_binds_claim_result_ledger_and_preflight_config(
    config: Any, tmp_path: Path
) -> None:
    claim_root = tmp_path / "claims"
    claim_root.mkdir()
    claim_path = claim_root / "ace-state-preflight-v2-one-attempt.claim.json"
    terminal_path = claim_root / "ace-state-preflight-v2-one-attempt.terminal.json"
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text("fixture immutable ledger\n")
    result_path = tmp_path / "result.json"
    preflight_config = ROOT / "configs" / "ace_state_preflight_v2.json"
    claim = _with_identity(
        {
            "attempt_id": "ace-state-preflight-v2-attempt-001",
            "claim_type": "SOLE_ACE_STATE_PREFLIGHT_AUTHORIZED_ATTEMPT",
            "config_path": str(preflight_config.resolve()),
            "config_sha256": sha256_file(preflight_config),
            "retry_allowed": False,
            "run_id": "ace-state-preflight-v2-001",
        },
        "claim_identity_sha256",
    )
    _write_json(claim_path, claim)
    ledger_sha = sha256_file(ledger_path)
    ledger_tail = "5" * 64
    result = {
        "attempt_id": "ace-state-preflight-v2-attempt-001",
        "capability_status": "PASS",
        "checkpoint_export_count": 3,
        "equivalence": [{"status": "PASS"} for _ in range(3)],
        "generated_output_count": 4,
        "ledger_path": str(ledger_path.resolve()),
        "ledger_sha256": ledger_sha,
        "ledger_tail_sha256": ledger_tail,
        "model_call_count": 4,
        "resume_child_process_count": 3,
        "retry_allowed": False,
        "run_id": "ace-state-preflight-v2-001",
        "scientific_claim": "TECHNICAL_CAPABILITY_ONLY",
        "state_queue_accessed": False,
        "status": "PASS",
    }
    _write_json(result_path, result)
    terminal = _with_identity(
        {
            "attempt_claim_path": str(claim_path.resolve()),
            "attempt_claim_sha256": sha256_file(claim_path),
            "attempt_id": "ace-state-preflight-v2-attempt-001",
            "ledger_path": str(ledger_path.resolve()),
            "ledger_sha256": ledger_sha,
            "ledger_tail_sha256": ledger_tail,
            "payload": {
                "capability_status": "PASS",
                "generated_output_count": 4,
                "model_call_count": 4,
                "run_result_path": str(result_path.resolve()),
                "run_result_sha256": sha256_file(result_path),
                "scientific_claim": "TECHNICAL_CAPABILITY_ONLY",
            },
            "retry_allowed": False,
            "run_id": "ace-state-preflight-v2-001",
            "schema_version": 1,
            "status": "PASS",
        },
        "terminal_identity_sha256",
    )
    _write_json(terminal_path, terminal)
    fixture_config = replace(
        config,
        preflight_claim_root=claim_root,
        preflight_terminal_path=terminal_path,
    )
    observed = validate_preflight_pass(
        fixture_config,
        terminal_path=terminal_path,
        expected_terminal_sha256=sha256_file(terminal_path),
    )
    assert observed["result_sha256"] == sha256_file(result_path)
    assert observed["preflight_config_sha256"] == sha256_file(preflight_config)

    with pytest.raises(AceStateQueueError, match="supplied PASS hash"):
        validate_preflight_pass(
            fixture_config,
            terminal_path=terminal_path,
            expected_terminal_sha256="0" * 64,
        )


def test_d0033_requires_exact_dynamic_hash_and_gpu_cap_assignments(
    config: Any, tmp_path: Path
) -> None:
    preflight = {
        "terminal_sha256": "1" * 64,
        "result_sha256": "2" * 64,
        "preflight_config_sha256": "3" * 64,
    }
    core = config.raw["source_core_run"]
    assignments = {
        "ACE_STATE_CAPABILITY": "PASS",
        "ACE_STATE_CAPTURE_INITIAL_AUTHORIZED": "YES",
        "ACE_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED": "NO",
        "NO_AUTOMATIC_RETRY": "YES",
        "ACE_STATE_CAPTURE_CONFIG": "configs/ace_state_capture_v2.json",
        "ACE_STATE_CAPTURE_CONFIG_SHA256": config.sha256,
        "ACE_STATE_PREFLIGHT_TERMINAL": str(config.preflight_terminal_path),
        "ACE_STATE_PREFLIGHT_TERMINAL_SHA256": preflight["terminal_sha256"],
        "ACE_STATE_PREFLIGHT_RESULT_SHA256": preflight["result_sha256"],
        "ACE_STATE_PREFLIGHT_CONFIG_SHA256": preflight["preflight_config_sha256"],
        "ACE_STATE_CAPTURE_CORE_QUEUE_SHA256": core["generation_queue"]["sha256"],
        "ACE_STATE_CAPTURE_CORE_LEDGER_SHA256": core["ledger"]["sha256"],
        "ACE_STATE_CAPTURE_INITIAL_GPU_SECONDS_CAP": "1234.5",
    }
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "## D-0033 — fixture opening\n\n"
        + "\n\n".join(f"`{key} = {value}`" for key, value in assignments.items())
        + "\n"
    )
    result = validate_d0033_opening(
        config,
        decisions_path=decisions,
        decision_id="D-0033",
        preflight=preflight,
    )
    assert result["initial_gpu_seconds_cap"] == 1234.5

    assignments["ACE_STATE_PREFLIGHT_TERMINAL_SHA256"] = "4" * 64
    decisions.write_text(
        "## D-0033 — fixture opening\n\n"
        + "\n\n".join(f"`{key} = {value}`" for key, value in assignments.items())
        + "\n"
    )
    with pytest.raises(AceStateQueueError, match="exact ACE state assignments"):
        validate_d0033_opening(
            config,
            decisions_path=decisions,
            decision_id="D-0033",
            preflight=preflight,
        )


def test_config_cannot_be_changed_to_self_authorize(tmp_path: Path) -> None:
    value = json.loads(CONFIG.read_text())
    value["execution_status"] = "OPEN"
    changed = tmp_path / "changed.json"
    _write_json(changed, value)
    with pytest.raises(AceStateQueueError, match="identity or closed status"):
        load_queue_config(changed, repo_root=ROOT)

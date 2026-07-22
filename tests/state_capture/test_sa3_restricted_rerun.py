from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import state_capture.sa3_restricted_rerun as rerun_module
from benchmark_core.ledger import HashChainedLedger
from scoring.common import sha256_file
from stage1.gates import AXES
from state_capture.sa3_restricted_rerun import (
    RestrictedExecutionScope,
    RestrictedRerunError,
    audit_original_source,
    load_execution_scope,
    load_restricted_rerun_config,
    mark_validation_pass,
    prepare_restricted_rerun,
    verify_rerun_decision,
)
from tests.stage1.terminal_support import build_terminal, queue_binding, write_jsonl

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "sa3_state_restricted_rerun_v2.json"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _fake_bundle() -> dict[str, list[dict[str, Any]]]:
    units: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    sequence = 0
    for axis in AXES:
        for prompt_number in range(12):
            prompt = f"{axis}-prompt-{prompt_number:02d}"
            for root in range(4):
                sequence += 1
                unit_ids: list[str] = []
                for checkpoint in (0.25, 0.5, 0.75):
                    identity = _digest(f"unit|{axis}|{prompt}|{root}|{checkpoint}")
                    unit_ids.append(identity)
                    units.append(
                        {
                            "axis": axis,
                            "eligibility_unit": {
                                "checkpoint": checkpoint,
                                "prompt": prompt,
                                "root": root,
                            },
                            "lane_request_sha256": identity,
                        }
                    )
                    for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED"):
                        actions.append(
                            {
                                "action": action,
                                "axis": axis,
                                "lane_request_sha256": identity,
                            }
                        )
                groups.append(
                    {
                        "axis": axis,
                        "group_request_sha256": _digest(f"group|{axis}|{prompt}|{root}"),
                        "group_sequence": sequence,
                        "lane_request_sha256s": unit_ids,
                    }
                )
    return {"action_map": actions, "prefix_groups": groups, "units": units}


def _stage1_fixture(tmp_path: Path) -> tuple[Any, dict[str, Any], Path]:
    bundle = _fake_bundle()
    sa3_queue = tmp_path / "queues" / "sa3.jsonl"
    ace_queue = tmp_path / "queues" / "ace.jsonl"
    write_jsonl(sa3_queue, bundle["units"])
    write_jsonl(ace_queue, [])
    result_path, summary_path, gate_config_path = build_terminal(
        tmp_path,
        queue_bindings=[
            queue_binding(ace_queue, "ACE-Step v1"),
            queue_binding(sa3_queue, "stable-audio-3-medium-base"),
        ],
        stopped_cells={("stable-audio-3-medium-base", "tempo")},
    )
    stage1_root = result_path.parent
    failed_group = bundle["prefix_groups"][0]
    config = SimpleNamespace(
        raw={
            "original_failure": {
                "failed_group_request_sha256": failed_group["group_request_sha256"],
                "failed_lane_request_sha256": failed_group["lane_request_sha256s"][0],
            },
            "source_run": {
                "queue": {
                    name: {"sha256": _digest(name)}
                    for name in ("action_map", "folds", "prefix_groups", "units")
                }
            },
        },
        stage1_config_path=gate_config_path,
        stage1_result_path=result_path,
        stage1_summary_path=summary_path,
    )
    return config, bundle, stage1_root


def test_static_config_audits_exact_original_queue_failure_and_fix() -> None:
    config = load_restricted_rerun_config(CONFIG, repo_root=ROOT)
    assert config.run_id == "sa3-state-v2-restricted-rerun-001"
    assert config.raw["metadata_filename_fix"]["commit"] == (
        "61ddecf457ad5902fd9bf529a121411dd41ac043"
    )
    audit = audit_original_source(CONFIG, repo_root=ROOT)
    assert audit == {
        "action_rows": 1296,
        "failure_ledger_sha256": (
            "68ddc4f56dbbb9518c5f8ba8a91fa4d757acb8d18c80da31be1f99d60f3011a5"
        ),
        "failed_lane_request_sha256": (
            "8d21cb321f6cc8be963fa8cf387303a508617ba3dec84475ee09d54f540ec27e"
        ),
        "groups": 144,
        "queue_manifest_sha256": (
            "5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3"
        ),
        "status": "ORIGINAL_FAILURE_AUDIT_PASS",
        "units": 432,
    }


def test_prepare_fails_before_run_or_claim_when_stage1_is_not_terminal(
    tmp_path: Path,
) -> None:
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw["execution"] = {
        "attempt_claim_path": str(tmp_path / "claims" / "attempt.json"),
        "run_id": "sa3-state-v2-restricted-rerun-001",
        "run_root": str(tmp_path / "runs"),
    }
    raw["stage1"]["result_path"] = str(tmp_path / "missing" / "result.json")
    raw["stage1"]["cancellation_summary_path"] = str(tmp_path / "missing" / "summary.json")
    config_path = tmp_path / "sa3_state_restricted_rerun_v2.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RestrictedRerunError, match="Stage-1 terminal validation failed"):
        prepare_restricted_rerun(
            config_path,
            decisions_path=tmp_path / "DECISIONS.md",
            decision_id="D-0035",
            repo_root=ROOT,
        )
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "claims" / "attempt.json").exists()


def test_d0035_uses_prospective_stage1_paths_and_no_third_repair(tmp_path: Path) -> None:
    config = load_restricted_rerun_config(CONFIG, repo_root=ROOT)
    source = config.raw["source_run"]
    failure = config.raw["original_failure"]
    fix = config.raw["metadata_filename_fix"]
    block = "\n".join(
        (
            "## D-0035 — restricted SA3 rerun",
            "SA3_STATE_RESTRICTED_RERUN_AUTHORIZED = YES",
            "SURVIVORS_ONLY = YES",
            "ONE_ROOT_VALIDATION_REQUIRED = YES",
            "NO_THIRD_REPAIR = YES",
            f"RERUN_CONFIG = configs/{config.source_path.name}",
            f"RERUN_CONFIG_SHA256 = {config.source_sha256}",
            f"RERUN_RUN_ID = {config.run_id}",
            f"SOURCE_STATE_MANIFEST_SHA256 = {source['queue']['manifest']['sha256']}",
            f"ORIGINAL_FAILED_REQUEST_SHA256 = {failure['failed_lane_request_sha256']}",
            f"ORIGINAL_FAILURE_LEDGER_SHA256 = {source['ledger']['sha256']}",
            f"METADATA_FILENAME_FIX_COMMIT = {fix['commit']}",
            f"STAGE1_RESULT_PATH = {config.stage1_result_path}",
            f"STAGE1_CANCELLATION_SUMMARY_PATH = {config.stage1_summary_path}",
            "STAGE1_RUNTIME_SHA256_BINDING = VERIFIED_AND_RECORDED_AT_LAUNCH",
        )
    )
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(block + "\n", encoding="utf-8")
    observed, digest = verify_rerun_decision(
        decisions,
        decision_id="D-0035",
        config=config,
    )
    assert observed == block + "\n"
    assert len(digest) == 64
    assert "STAGE1_RESULT_SHA256" not in observed
    assert "STAGE1_CANCELLATION_SUMMARY_SHA256" not in observed

    decisions.write_text(
        block + "\nSTAGE1_RESULT_SHA256 = " + "a" * 64 + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RestrictedRerunError, match="must not predeclare"):
        verify_rerun_decision(
            decisions,
            decision_id="D-0035",
            config=config,
        )

    decisions.write_text(block.replace("NO_THIRD_REPAIR = YES", "NO_THIRD_REPAIR = NO"))
    with pytest.raises(RestrictedRerunError, match="exact restricted-rerun bindings"):
        verify_rerun_decision(
            decisions,
            decision_id="D-0035",
            config=config,
        )


def test_stage1_plan_exactly_cancels_stop_axis_and_selects_failed_root(tmp_path: Path) -> None:
    config, bundle, _ = _stage1_fixture(tmp_path)
    plan = rerun_module._stage1_plan(config, bundle)
    assert plan["survivor_axes"] == ["integrity", "vocal_instrumental"]
    assert plan["stop_axes"] == ["tempo"]
    assert len(plan["cancelled_lane_request_sha256s"]) == 144
    assert len(plan["survivor_lane_request_sha256s"]) == 288
    assert len(plan["cancelled_group_request_sha256s"]) == 48
    assert len(plan["survivor_group_request_sha256s"]) == 96
    assert plan["failed_unit_disposition"] == "AUTHORIZED_VERBATIM_RERUN_ONCE"
    assert (
        plan["validation_group_request_sha256"]
        == (config.raw["original_failure"]["failed_group_request_sha256"])
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    scope = RestrictedExecutionScope(phase="validation", run_dir=run_dir, plan=plan)
    owner = (
        next(
            row
            for row in bundle["prefix_groups"]
            if row["group_request_sha256"] == plan["validation_group_request_sha256"]
        )["group_sequence"]
        - 1
    ) % 4
    selected = scope.select(
        units=bundle["units"],
        groups=bundle["prefix_groups"],
        replica_index=owner,
        replica_count=4,
    )
    assert len(selected) == 1
    assert set(selected[0]["lane_request_sha256s"]).isdisjoint(
        plan["cancelled_lane_request_sha256s"]
    )
    scope.require_scoreable(selected[0]["lane_request_sha256s"][0])
    with pytest.raises(RestrictedRerunError, match="never be scored"):
        scope.require_scoreable(plan["cancelled_lane_request_sha256s"][0])
    with pytest.raises(RestrictedRerunError, match="single static-shard owner"):
        scope.select(
            units=bundle["units"],
            groups=bundle["prefix_groups"],
            replica_index=(owner + 1) % 4,
            replica_count=4,
        )


def test_cancellation_chain_tamper_is_rejected(tmp_path: Path) -> None:
    config, bundle, stage1_root = _stage1_fixture(tmp_path)
    event = sorted((stage1_root / "cancellations" / "events").glob("[0-9]*-*.json"))[0]
    value = json.loads(event.read_text(encoding="utf-8"))
    value["payload"]["prohibited_operations"] = ["SCORE"]
    event.chmod(0o644)
    event.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RestrictedRerunError, match="immutable no-clobber"):
        rerun_module._stage1_plan(config, bundle)


def test_continuation_requires_full_one_root_success_and_failure_is_permanent(
    tmp_path: Path,
) -> None:
    config, bundle, _ = _stage1_fixture(tmp_path)
    plan = rerun_module._stage1_plan(config, bundle)
    run_dir = tmp_path / "run"
    control = run_dir / "control"
    control.mkdir(parents=True)
    plan_path = control / "stage1-survivor-execution-plan.json"
    plan_path.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_execution_scope(run_dir, plan=plan, phase="continuation")

    validation_group = next(
        row
        for row in bundle["prefix_groups"]
        if row["group_request_sha256"] == plan["validation_group_request_sha256"]
    )
    ledger = HashChainedLedger(run_dir / "state-ledger.jsonl")
    for identity in (
        validation_group["group_request_sha256"],
        *validation_group["lane_request_sha256s"],
    ):
        ledger.transition(identity, "CLAIMED")
        ledger.transition(identity, "CALL_STARTED")
        ledger.transition(identity, "SUCCEEDED")
    marker = mark_validation_pass(run_dir, plan, bundle["prefix_groups"])
    assert marker["status"] == "ONE_ROOT_VALIDATION_PASS"
    continuation = load_execution_scope(run_dir, plan=plan, phase="continuation")
    assert continuation.phase == "continuation"
    with pytest.raises(FileExistsError):
        mark_validation_pass(run_dir, plan, bundle["prefix_groups"])

    continuation.record_failure(
        identity=validation_group["lane_request_sha256s"][0],
        kind="RESUME_UNIT",
        error=RuntimeError("new failure class"),
    )
    terminal = json.loads(
        (control / "restricted-rerun-failure.terminal.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "FAILED_STOPPED"
    assert terminal["no_third_repair"] is True
    with pytest.raises(RestrictedRerunError, match="permanently FAILED_STOPPED"):
        continuation.require_open()


def test_failure_latch_is_atomic_against_publication_and_blocks_later_work(
    tmp_path: Path,
) -> None:
    config, bundle, _ = _stage1_fixture(tmp_path)
    plan = rerun_module._stage1_plan(config, bundle)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    scope = RestrictedExecutionScope(phase="continuation", run_dir=run_dir, plan=plan)
    published = run_dir / "publication"
    publication_entered = threading.Event()
    allow_publication = threading.Event()
    failure_returned = threading.Event()

    def publish_before_failure() -> None:
        with scope.atomic_open():
            publication_entered.set()
            assert allow_publication.wait(timeout=5)
            published.write_text("committed\n", encoding="utf-8")

    def latch_failure() -> None:
        assert publication_entered.wait(timeout=5)
        scope.record_failure(
            identity=_digest("concurrent-failure"),
            kind="RESUME_UNIT",
            error=RuntimeError("new failure class"),
        )
        failure_returned.set()

    publisher = threading.Thread(target=publish_before_failure)
    failure = threading.Thread(target=latch_failure)
    publisher.start()
    failure.start()
    assert publication_entered.wait(timeout=5)
    assert not failure_returned.wait(timeout=0.05)
    assert not (run_dir / "control" / "restricted-rerun-failure.terminal.json").exists()
    allow_publication.set()
    publisher.join(timeout=5)
    failure.join(timeout=5)
    assert not publisher.is_alive()
    assert not failure.is_alive()
    assert published.read_text(encoding="utf-8") == "committed\n"
    assert failure_returned.is_set()

    prohibited = run_dir / "post-failure-publication"
    with (
        pytest.raises(RestrictedRerunError, match="permanently FAILED_STOPPED"),
        scope.atomic_open(),
    ):
        prohibited.write_text("must not exist", encoding="utf-8")
    assert not prohibited.exists()


def test_plan_source_hash_fields_are_not_rewritten(tmp_path: Path) -> None:
    config, bundle, _ = _stage1_fixture(tmp_path)
    plan = rerun_module._stage1_plan(config, bundle)
    for name in ("action_map", "folds", "prefix_groups", "units"):
        assert plan[f"{name}_sha256"] == config.raw["source_run"]["queue"][name]["sha256"]
    assert plan["original_queue_bytes_reused_without_rewrite"] is True
    assert sha256_file(CONFIG) == load_restricted_rerun_config(CONFIG, repo_root=ROOT).source_sha256

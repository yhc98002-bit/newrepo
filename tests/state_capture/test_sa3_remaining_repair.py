from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import state_capture.sa3_remaining_repair as remaining_module
import state_capture.sa3_restricted_rerun as rerun_module
from benchmark_core.ledger import HashChainedLedger
from scoring.common import sha256_file
from state_capture.sa3_restricted_rerun import RestrictedExecutionScope, RestrictedRerunError


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _repair_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SimpleNamespace, dict[str, Any], dict[str, Any], Path]:
    groups: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for group_sequence in range(1, 49):
        group_id = _digest(f"group-{group_sequence}")
        unit_ids: list[str] = []
        for checkpoint in (25, 50, 75):
            unit_id = _digest(f"unit-{group_sequence}-{checkpoint}")
            unit_ids.append(unit_id)
            units.append(
                {
                    "checkpoint": checkpoint / 100,
                    "lane_request_sha256": unit_id,
                    "root_index": group_sequence - 1,
                }
            )
            for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED"):
                actions.append({"action": action, "lane_request_sha256": unit_id})
        groups.append(
            {
                "group_request_sha256": group_id,
                "group_sequence": group_sequence,
                "lane_request_sha256s": unit_ids,
                "reference_terminal_relpath": (
                    f"fixture/prompt/root-{group_sequence - 1:02d}/reference-terminal.wav"
                ),
            }
        )
    bundle = {"action_map": actions, "prefix_groups": groups, "units": units}
    plan = {
        "action_map_sha256": _digest("actions"),
        "cancelled_group_request_sha256s": [],
        "cancelled_lane_request_sha256s": [],
        "folds_sha256": _digest("folds"),
        "prefix_groups_sha256": _digest("groups"),
        "survivor_group_request_sha256s": sorted(row["group_request_sha256"] for row in groups),
        "survivor_lane_request_sha256s": sorted(row["lane_request_sha256"] for row in units),
        "units_sha256": _digest("units"),
        "validation_group_request_sha256": groups[0]["group_request_sha256"],
    }
    config = SimpleNamespace(
        queue_manifest_path=tmp_path / "unused-manifest.json",
        raw={"source_run": {"queue": {"manifest": {"sha256": _digest("manifest")}}}},
        source_sha256=_digest("config"),
        state_config=object(),
    )
    monkeypatch.setattr(remaining_module, "load_restricted_rerun_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        remaining_module,
        "load_sa3_state_capture_bundle",
        lambda *_a, **_k: bundle,
    )

    run_id = "sa3-state-v2-restricted-rerun-002"
    run_dir = tmp_path / "runs" / run_id
    plan_path = run_dir / "control" / "stage1-survivor-execution-plan.json"
    _write_json(plan_path, plan)
    claim_path = tmp_path / "claims" / f"{run_id}.claim.json"
    _write_json(claim_path, {"config_sha256": config.source_sha256, "run_id": run_id})
    completed_group = groups[0]
    completed_ids = {
        completed_group["group_request_sha256"],
        *completed_group["lane_request_sha256s"],
    }
    marker_path = run_dir / "control" / "one-root-validation.pass.json"
    _write_json(
        marker_path,
        {
            "stage1_plan_sha256": sha256_file(plan_path),
            "status": "ONE_ROOT_VALIDATION_PASS",
            "succeeded_request_sha256s": sorted(completed_ids),
            "validation_group_request_sha256": completed_group["group_request_sha256"],
        },
    )
    manifest_path = run_dir / "run-manifest.json"
    _write_json(
        manifest_path,
        {
            "attempt_claim_path": str(claim_path),
            "attempt_claim_sha256": sha256_file(claim_path),
            "config_sha256": config.source_sha256,
            "run_id": run_id,
            "stage1_plan_path": str(plan_path),
            "stage1_plan_sha256": sha256_file(plan_path),
        },
    )
    ledger = HashChainedLedger(run_dir / "state-ledger.jsonl")
    for identity in sorted(completed_ids):
        ledger.transition(identity, "CLAIMED")
        ledger.transition(identity, "CALL_STARTED")
        ledger.transition(identity, "SUCCEEDED")
    artifact_root = (
        run_dir / "artifacts" / Path(completed_group["reference_terminal_relpath"]).parent
    )
    artifact_root.mkdir(parents=True)
    (artifact_root / "reference-terminal.wav").write_bytes(b"RIFF-fixture")
    _write_json(
        artifact_root / "reference-terminal.commit.json",
        {
            "group_request_sha256": completed_group["group_request_sha256"],
            "status": "COMMITTED",
        },
    )
    for index, unit_id in enumerate(completed_group["lane_request_sha256s"]):
        _write_json(
            artifact_root / f"unit-{index}.commit.json",
            {"lane_request_sha256": unit_id, "status": "COMMITTED"},
        )
    return config, bundle, plan, run_dir


def test_remaining_package_excludes_completed_validation_and_preserves_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, bundle, source_plan, run_dir = _repair_fixture(tmp_path, monkeypatch)
    package_dir = tmp_path / "repair"
    result = remaining_module.materialize_remaining_repair_package(
        tmp_path / "unused-config.json",
        repo_root=tmp_path,
        predecessor_run_dir=run_dir,
        predecessor_run_id=run_dir.name,
        output_dir=package_dir,
    )
    repair = remaining_module.validate_remaining_repair_package(
        Path(result["remaining_manifest_path"]),
        exclusion_path=Path(result["completed_exclusion_path"]),
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    assert len(repair["completed_group_request_sha256s"]) == 1
    assert len(repair["completed_lane_request_sha256s"]) == 3
    assert len(repair["remaining_group_request_sha256s"]) == 47
    assert len(repair["remaining_lane_request_sha256s"]) == 141

    predecessor = {"remaining_repair": repair}
    plan = rerun_module._plan_for_attempt(source_plan, predecessor)
    scope = RestrictedExecutionScope(phase="continuation", run_dir=run_dir, plan=plan)
    selected = scope.select(
        units=bundle["units"],
        groups=bundle["prefix_groups"],
        replica_index=0,
        replica_count=1,
    )
    assert len(selected) == 47
    assert repair["completed_group_request_sha256s"][0] not in {
        row["group_request_sha256"] for row in selected
    }
    with pytest.raises(RestrictedRerunError, match="completed predecessor unit"):
        scope.require_scoreable(repair["completed_lane_request_sha256s"][0])
    with pytest.raises(RestrictedRerunError, match="may not be rerun"):
        RestrictedExecutionScope(phase="validation", run_dir=run_dir, plan=plan).select(
            units=bundle["units"],
            groups=bundle["prefix_groups"],
            replica_index=0,
            replica_count=1,
        )


def test_remaining_package_rejects_incomplete_completed_artifact_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, bundle, source_plan, run_dir = _repair_fixture(tmp_path, monkeypatch)
    package_dir = tmp_path / "repair"
    result = remaining_module.materialize_remaining_repair_package(
        tmp_path / "unused-config.json",
        repo_root=tmp_path,
        predecessor_run_dir=run_dir,
        predecessor_run_id=run_dir.name,
        output_dir=package_dir,
    )
    exclusion_path = Path(result["completed_exclusion_path"])
    manifest_path = Path(result["remaining_manifest_path"])
    exclusion = json.loads(exclusion_path.read_text(encoding="utf-8"))
    exclusion["artifact_files"].pop()
    exclusion_path.chmod(0o644)
    _write_json(exclusion_path, exclusion)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completed_exclusion"]["sha256"] = sha256_file(exclusion_path)
    manifest_path.chmod(0o644)
    _write_json(manifest_path, manifest)
    with pytest.raises(RestrictedRerunError, match="artifact inventory"):
        remaining_module.validate_remaining_repair_package(
            manifest_path,
            exclusion_path=exclusion_path,
            config=config,
            bundle=bundle,
            source_plan=source_plan,
        )


def test_remaining_repair_decision_binds_exact_scope_and_placement(tmp_path: Path) -> None:
    repair = {
        "completed_exclusion_sha256": "a" * 64,
        "remaining_manifest_sha256": "b" * 64,
    }
    predecessor = {"remaining_repair": repair, "sha256": "c" * 64}
    science = {
        "config_sha256": "d" * 64,
        "queue_manifest_sha256": "e" * 64,
        "stage1_result_sha256": "f" * 64,
        "stage1_summary_sha256": "0" * 64,
    }
    run_id = "sa3-state-v2-restricted-rerun-003"
    lines = [
        "## D-0099 — exact remaining repair",
        "SA3_STATE_REMAINING_REPAIR_AUTHORIZED = YES",
        f"SA3_STATE_REMAINING_REPAIR_RUN_ID = {run_id}",
        f"SA3_STATE_REMAINING_REPAIR_PREDECESSOR_SHA256 = {predecessor['sha256']}",
        (
            "SA3_STATE_REMAINING_REPAIR_COMPLETED_EXCLUSION_SHA256 = "
            f"{repair['completed_exclusion_sha256']}"
        ),
        f"SA3_STATE_REMAINING_REPAIR_MANIFEST_SHA256 = {repair['remaining_manifest_sha256']}",
        "SA3_STATE_REMAINING_REPAIR_PLACEMENT = an12:[4];TP1;R1",
        "SA3_STATE_REMAINING_REPAIR_COMPLETED_GROUP_COUNT = 1",
        "SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_COUNT = 3",
        "SA3_STATE_REMAINING_REPAIR_REMAINING_GROUP_COUNT = 47",
        "SA3_STATE_REMAINING_REPAIR_REMAINING_UNIT_COUNT = 141",
        "SA3_STATE_REMAINING_REPAIR_REMAINING_ACTION_COUNT = 423",
        "SA3_STATE_REMAINING_REPAIR_VALIDATION_RERUN = NO",
        "SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_RERUN = NO",
        "SA3_STATE_REMAINING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO",
        "SA3_STATE_REMAINING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO",
        f"SA3_STATE_REMAINING_REPAIR_CONFIG_SHA256 = {science['config_sha256']}",
        f"SA3_STATE_REMAINING_REPAIR_QUEUE_MANIFEST_SHA256 = {science['queue_manifest_sha256']}",
        f"SA3_STATE_REMAINING_REPAIR_STAGE1_RESULT_SHA256 = {science['stage1_result_sha256']}",
        f"SA3_STATE_REMAINING_REPAIR_STAGE1_SUMMARY_SHA256 = {science['stage1_summary_sha256']}",
    ]
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text("\n".join(lines) + "\n", encoding="utf-8")
    block, digest = rerun_module.verify_remaining_repair_decision(
        decisions,
        decision_id="D-0099",
        run_id=run_id,
        predecessor=predecessor,
        placement={
            "node": "an12",
            "physical_gpu_ids": [4],
            "replica_count": 1,
            "tensor_parallel_width": 1,
        },
        scientific_bindings=science,
    )
    assert block == decisions.read_text(encoding="utf-8")
    assert len(digest) == 64
    decisions.write_text(
        decisions.read_text(encoding="utf-8").replace(
            "SA3_STATE_REMAINING_REPAIR_VALIDATION_RERUN = NO",
            "SA3_STATE_REMAINING_REPAIR_VALIDATION_RERUN = YES",
        ),
        encoding="utf-8",
    )
    with pytest.raises(RestrictedRerunError, match="exact remaining-repair bindings"):
        rerun_module.verify_remaining_repair_decision(
            decisions,
            decision_id="D-0099",
            run_id=run_id,
            predecessor=predecessor,
            placement={
                "node": "an12",
                "physical_gpu_ids": [4],
                "replica_count": 1,
                "tensor_parallel_width": 1,
            },
            scientific_bindings=science,
        )

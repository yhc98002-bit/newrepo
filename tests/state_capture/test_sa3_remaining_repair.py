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
from state_capture.sa3_contract import SA3_MODEL_ID
from state_capture.sa3_restricted_rerun import RestrictedExecutionScope, RestrictedRerunError
from state_capture.sa3_worker import SA3StateWorker


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


def test_zero_call_attempt_carries_exact_remaining_scope_into_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, bundle, source_plan, run_002 = _repair_fixture(tmp_path, monkeypatch)
    package = remaining_module.materialize_remaining_repair_package(
        tmp_path / "unused-config.json",
        repo_root=tmp_path,
        predecessor_run_dir=run_002,
        predecessor_run_id=run_002.name,
        output_dir=tmp_path / "repair",
    )
    repair = remaining_module.validate_remaining_repair_package(
        Path(package["remaining_manifest_path"]),
        exclusion_path=Path(package["completed_exclusion_path"]),
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    science = {
        "config_sha256": config.source_sha256,
        "queue_manifest_sha256": config.raw["source_run"]["queue"]["manifest"]["sha256"],
        "stage1_result_sha256": _digest("stage1-result"),
        "stage1_summary_sha256": _digest("stage1-summary"),
    }
    old_predecessor = {
        "path": str(tmp_path / "run-002-failure.json"),
        "remaining_repair": repair,
        "sha256": _digest("run-002-failure"),
        "status": "FAILED_ENGINEERING_ATTEMPT",
    }
    run_003 = tmp_path / "runs" / "sa3-state-v2-restricted-rerun-003"
    plan_path = run_003 / "control" / "stage1-survivor-execution-plan.json"
    carried_plan = rerun_module._plan_for_attempt(
        source_plan,
        {"remaining_repair": repair},
    )
    _write_json(plan_path, carried_plan)
    placement = {
        "node": "an12",
        "physical_gpu_ids": [4],
        "placement_justification": (
            "1 independent TP1 SA3 state replica(s) on exact an12 GPU IDs [4]; "
            "every worker retains live idle/headroom and cooperative-lock checks."
        ),
        "replica_count": 1,
        "tensor_parallel_width": 1,
    }
    repair_decision = {"block_sha256": _digest("D-0099"), "decision_id": "D-0099"}
    claim_path = tmp_path / "claims" / "sa3-state-v2-restricted-rerun-003.claim.json"
    _write_json(
        claim_path,
        {
            "engineering_governance_decisions_path": str(tmp_path / "DECISIONS.md"),
            "one_root_validation_required": False,
            "placement": placement,
            "predecessor_failure": old_predecessor,
            "remaining_repair_decision": repair_decision,
            "run_id": run_003.name,
            "scientific_bindings": science,
            "stage1_plan_path": str(plan_path),
            "stage1_plan_sha256": sha256_file(plan_path),
        },
    )
    manifest_path = run_003 / "run-manifest.json"
    _write_json(
        manifest_path,
        {
            "attempt_claim_path": str(claim_path),
            "attempt_claim_sha256": sha256_file(claim_path),
            "placement": placement,
            "predecessor_failure": old_predecessor,
            "remaining_repair_decision": repair_decision,
            "run_id": run_003.name,
            "scientific_bindings": science,
            "stage1_plan_path": str(plan_path),
            "stage1_plan_sha256": sha256_file(plan_path),
        },
    )
    receipt_path = run_003 / "control" / "pre-model-engineering-failure.terminal.json"
    _write_json(
        receipt_path,
        {
            "attempt_claim_path": str(claim_path),
            "attempt_claim_sha256": sha256_file(claim_path),
            "completed_exclusion_path": repair["completed_exclusion_path"],
            "completed_exclusion_sha256": repair["completed_exclusion_sha256"],
            "failed_attempt_immutable": True,
            "failure_classification": "ENGINEERING_BUG",
            "failure_kind": "EXECUTION_REPLICA_COUNT_NOT_PROPAGATED",
            "generated_outputs": 0,
            "gpu_seconds": 0,
            "model_calls": 0,
            "placement": {
                "authorized_execution_replica_count": 1,
                "node": "an12",
                "physical_gpu_ids": [4],
                "tensor_parallel_width": 1,
            },
            "remaining_manifest_path": repair["remaining_manifest_path"],
            "remaining_manifest_sha256": repair["remaining_manifest_sha256"],
            "remaining_repair_carried_forward": True,
            "repair": {
                "scientific_configuration_changed": False,
                "thresholds_changed": False,
            },
            "repair_requires_new_claim": True,
            "repair_requires_new_run_id": True,
            "run_id": run_003.name,
            "run_manifest_path": str(manifest_path),
            "run_manifest_sha256": sha256_file(manifest_path),
            "schema_version": 1,
            "scientific_bindings": science,
            "scientific_design_changed": False,
            "scientific_outputs_retained": True,
            "stage1_execution_plan_path": str(plan_path),
            "stage1_execution_plan_sha256": sha256_file(plan_path),
            "status": "FAILED_PRE_MODEL_ENGINEERING",
            "valid_completed_units_rerun": False,
            "worker_started": False,
        },
    )
    monkeypatch.setattr(
        rerun_module,
        "verify_remaining_repair_decision",
        lambda *_args, **_kwargs: ("fixture", repair_decision["block_sha256"]),
    )
    predecessor = rerun_module._repair_predecessor(
        receipt_path,
        base_run_id="sa3-state-v2-restricted-rerun-001",
        next_run_id="sa3-state-v2-restricted-rerun-004",
        expected_scientific_bindings=science,
        completed_exclusion_path=Path(repair["completed_exclusion_path"]),
        remaining_manifest_path=Path(repair["remaining_manifest_path"]),
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    assert predecessor is not None
    assert predecessor["remaining_repair"] == repair
    next_plan = rerun_module._plan_for_attempt(source_plan, predecessor)
    assert next_plan["validation_rerun_authorized"] is False
    assert len(next_plan["remaining_group_request_sha256s"]) == 47
    assert len(next_plan["remaining_lane_request_sha256s"]) == 141
    selected = RestrictedExecutionScope(
        phase="continuation",
        run_dir=run_003,
        plan=next_plan,
    ).select(
        units=bundle["units"],
        groups=bundle["prefix_groups"],
        replica_index=0,
        replica_count=1,
    )
    assert len(selected) == 47
    (run_003 / "workers").mkdir()
    with pytest.raises(RestrictedRerunError, match="worker/model artifacts"):
        rerun_module._repair_predecessor(
            receipt_path,
            base_run_id="sa3-state-v2-restricted-rerun-001",
            next_run_id="sa3-state-v2-restricted-rerun-004",
            expected_scientific_bindings=science,
            completed_exclusion_path=Path(repair["completed_exclusion_path"]),
            remaining_manifest_path=Path(repair["remaining_manifest_path"]),
            config=config,
            bundle=bundle,
            source_plan=source_plan,
        )


def test_restricted_worker_uses_exact_attempt_replica_count(tmp_path: Path) -> None:
    placement = SimpleNamespace(
        allowed_physical_gpu_ids=(4, 5, 6, 7),
        maximum_idle_utilization_percent=5,
        maximum_parallel_replicas=4,
        minimum_free_vram_bytes=1,
        post_load_reserve_bytes=1,
        required_gpu_name_substring="A800",
        shared_core_lock_root=tmp_path / "locks",
    )
    config = SimpleNamespace(
        heartbeat_interval_seconds=1,
        heartbeat_stale_after_seconds=5,
        initial_gpu_seconds_cap=720.0,
        placement=placement,
        prefix_group_reservation_seconds=2.0,
        resume_unit_reservation_seconds=1.0,
        source_sha256="1" * 64,
    )

    class _Engine:
        model_id = SA3_MODEL_ID

        def preflight(self) -> dict[str, str]:
            return {"status": "READY"}

        def load(self) -> dict[str, str]:
            return {"status": "READY"}

        def close(self) -> None:
            return None

    class _Probe:
        def require_safe(self, **_kwargs: Any) -> object:
            return object()

    class _Lease:
        def acquire(self) -> _Lease:
            return self

        def release(self) -> None:
            return None

        def __enter__(self) -> _Lease:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class _RecordingScope:
        def __init__(self) -> None:
            self.observed_replica_count: int | None = None

        def select(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.observed_replica_count = kwargs["replica_count"]
            return []

        def require_open(self) -> None:
            return None

        def atomic_open(self) -> Any:
            raise AssertionError("empty selected scope must not publish")

        def record_failure(self, **_kwargs: Any) -> None:
            raise AssertionError("empty selected scope must not fail")

    def worker(run_dir: Path) -> SA3StateWorker:
        return SA3StateWorker(
            config=config,
            run_dir=run_dir,
            run_id="sa3-state-v2-restricted-test",
            git_commit="1" * 40,
            bundle_manifest_sha256="2" * 64,
            replica_index=0,
            physical_gpu_id=4,
            engine=_Engine(),  # type: ignore[arg-type]
            execution_replica_count=1,
            probe=_Probe(),  # type: ignore[arg-type]
            lease=_Lease(),  # type: ignore[arg-type]
            placement_poll_seconds=0,
        )

    scope = _RecordingScope()
    result = worker(tmp_path / "restricted").run(
        units=[],
        groups=[],
        execution_scope=scope,  # type: ignore[arg-type]
    )
    assert result["status"] == "COMPLETE"
    assert scope.observed_replica_count == 1
    with pytest.raises(ValueError, match="separately authorized scope"):
        worker(tmp_path / "unrestricted").run(units=[], groups=[])

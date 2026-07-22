"""Fail-closed Stage-1 filter and one-attempt SA3 restricted-rerun control plane.

This module is deliberately CPU-only.  It validates the immutable first run,
the Stage-1 terminal result, and its cancellation chain before it materializes
an execution scope.  Model construction remains in the existing SA3 worker.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_core.launcher import GitLaunchState, observe_clean_origin_main
from benchmark_core.ledger import validate_ledger, validate_request_state_machine
from scoring.common import load_json, require_sha256, sha256_file
from stage1.gates import AXES
from stage1.terminal import Stage1TerminalError, validate_stage1_terminal
from state_capture.sa3_contract import (
    SA3StateCaptureConfig,
    load_sa3_state_capture_bundle,
    load_sa3_state_capture_config,
)

AUTHORIZATION_STATUS = "AUTHORIZED_D0035_STAGE1_SURVIVORS_ONLY"
PREPARED_STATUS = "PREPARED_RESTRICTED_RERUN_NO_MODEL_CALLS"
SA3_BACKBONE = "stable-audio-3-medium-base"


class RestrictedRerunError(RuntimeError):
    """A frozen input, cancellation, phase, or one-attempt boundary is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _decision_block(text: str, decision_id: str) -> str:
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(decision_id)}\b.*?(?=^##\s+D-\d+\b|\Z)")
    match = pattern.search(text)
    if match is None:
        raise RestrictedRerunError(f"decision block is absent: {decision_id}")
    return match.group(0)


def _resolve(repo_root: Path, value: Any, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RestrictedRerunError(f"{context} path is absent")
    path = Path(value)
    return (path if path.is_absolute() else repo_root / path).resolve(strict=True)


def _binding(repo_root: Path, raw: Any, context: str) -> tuple[Path, str]:
    if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
        raise RestrictedRerunError(f"{context} binding shape drifted")
    path = _resolve(repo_root, raw["path"], context)
    expected = require_sha256(raw["sha256"], f"{context}.sha256")
    if sha256_file(path) != expected:
        raise RestrictedRerunError(f"{context} bytes drifted")
    return path, expected


@dataclass(frozen=True)
class RestrictedRerunConfig:
    source_path: Path
    source_sha256: str
    raw: dict[str, Any]
    repo_root: Path
    run_id: str
    run_root: Path
    attempt_claim_path: Path
    stage1_config_path: Path
    stage1_result_path: Path
    stage1_summary_path: Path
    state_config_path: Path
    state_config: SA3StateCaptureConfig
    queue_manifest_path: Path


def load_restricted_rerun_config(path: Path, *, repo_root: Path) -> RestrictedRerunConfig:
    """Load the static D-0035 input bindings; no runtime directory is created."""

    source = path.resolve(strict=True)
    raw = load_json(source)
    if set(raw) != {
        "execution",
        "lane_id",
        "metadata_filename_fix",
        "original_failure",
        "schema_version",
        "source_run",
        "stage1",
    }:
        raise RestrictedRerunError("restricted-rerun config keys drifted")
    if raw["schema_version"] != 1 or raw["lane_id"] != "sa3-state-capture-v2-restricted-rerun":
        raise RestrictedRerunError("restricted-rerun config identity drifted")
    execution = raw["execution"]
    if not isinstance(execution, dict) or set(execution) != {
        "attempt_claim_path",
        "run_id",
        "run_root",
    }:
        raise RestrictedRerunError("restricted-rerun execution contract drifted")
    run_id = execution["run_id"]
    if run_id != "sa3-state-v2-restricted-rerun-001":
        raise RestrictedRerunError("D-0035 permits exactly one fixed rerun ID")

    fix = raw["metadata_filename_fix"]
    if not isinstance(fix, dict) or set(fix) != {"commit", "path", "sha256"}:
        raise RestrictedRerunError("metadata-filename fix binding drifted")
    if fix["commit"] != "61ddecf457ad5902fd9bf529a121411dd41ac043":
        raise RestrictedRerunError("metadata-filename fix commit drifted")
    _binding(repo_root, {"path": fix["path"], "sha256": fix["sha256"]}, "fix source")

    source_run = raw["source_run"]
    state_config_path, _ = _binding(repo_root, source_run["state_config"], "state config")
    state_config = load_sa3_state_capture_config(state_config_path, repo_root=repo_root)
    queue_manifest_path, _ = _binding(
        repo_root, source_run["queue"]["manifest"], "source queue manifest"
    )
    stage1 = raw["stage1"]
    if set(stage1) != {
        "backbone",
        "cancellation_summary_path",
        "gate_config_path",
        "result_path",
    } or stage1.get("backbone") != SA3_BACKBONE:
        raise RestrictedRerunError("Stage-1 backbone binding drifted")
    return RestrictedRerunConfig(
        source_path=source,
        source_sha256=sha256_file(source),
        raw=raw,
        repo_root=repo_root.resolve(strict=True),
        run_id=run_id,
        run_root=Path(execution["run_root"]).resolve(),
        attempt_claim_path=Path(execution["attempt_claim_path"]).resolve(),
        stage1_config_path=_resolve(repo_root, stage1["gate_config_path"], "Stage-1 config"),
        stage1_result_path=Path(stage1["result_path"]).resolve(),
        stage1_summary_path=Path(stage1["cancellation_summary_path"]).resolve(),
        state_config_path=state_config_path,
        state_config=state_config,
        queue_manifest_path=queue_manifest_path,
    )


def _audit_source_run(config: RestrictedRerunConfig) -> dict[str, Any]:
    source = config.raw["source_run"]
    if source.get("run_id") != "sa3-state-v2-001":
        raise RestrictedRerunError("source SA3 run ID drifted")
    for name in ("run_manifest", "launch_claim", "ledger", "heartbeat"):
        _binding(config.repo_root, source[name], f"source {name}")
    for name in ("units", "prefix_groups", "action_map", "folds", "manifest"):
        _binding(config.repo_root, source["queue"][name], f"source queue {name}")

    bundle = load_sa3_state_capture_bundle(config.queue_manifest_path, config=config.state_config)
    ledger_path = _resolve(config.repo_root, source["ledger"]["path"], "source ledger")
    rows = validate_ledger(ledger_path)
    failure = config.raw["original_failure"]
    failed_id = failure["failed_lane_request_sha256"]
    group_id = failure["failed_group_request_sha256"]
    latest = validate_request_state_machine(rows)
    if latest != {group_id: "SUCCEEDED", failed_id: "FAILED"}:
        raise RestrictedRerunError("source ledger has work beyond the adjudicated failure")
    failures = [row for row in rows if row.get("request_state") == "FAILED"]
    if len(failures) != 1:
        raise RestrictedRerunError("source ledger must contain exactly one failure")
    row = failures[0]
    if (
        row.get("request_sha256") != failed_id
        or row.get("ledger_row_sha256") != failure["failure_ledger_row_sha256"]
        or row.get("error_type") != failure["error_type"]
        or failure["error_message_substring"] not in str(row.get("error_message", ""))
    ):
        raise RestrictedRerunError("source failure class/identity drifted")
    heartbeat_path = _resolve(config.repo_root, source["heartbeat"]["path"], "heartbeat")
    heartbeat = load_json(heartbeat_path)
    if (
        heartbeat.get("state") != "FAILED_STOPPED"
        or heartbeat.get("failed") != 1
        or heartbeat.get("completed") != 0
        or heartbeat.get("last_ledger_sha256") != failure["failure_ledger_row_sha256"]
    ):
        raise RestrictedRerunError("source failure heartbeat drifted")
    return bundle


def audit_original_source(config_path: Path, *, repo_root: Path) -> dict[str, Any]:
    """Return obtained source counts only after every frozen failure binding passes."""

    config = load_restricted_rerun_config(config_path, repo_root=repo_root)
    bundle = _audit_source_run(config)
    return {
        "action_rows": len(bundle["action_map"]),
        "failure_ledger_sha256": config.raw["source_run"]["ledger"]["sha256"],
        "failed_lane_request_sha256": config.raw["original_failure"]["failed_lane_request_sha256"],
        "groups": len(bundle["prefix_groups"]),
        "queue_manifest_sha256": bundle["manifest_sha256"],
        "status": "ORIGINAL_FAILURE_AUDIT_PASS",
        "units": len(bundle["units"]),
    }


def verify_rerun_decision(
    decisions_path: Path,
    *,
    decision_id: str,
    config: RestrictedRerunConfig,
) -> tuple[str, str]:
    """Require prospective D-0035 paths; runtime hashes are bound only at launch."""

    decision_text = decisions_path.resolve(strict=True).read_text(encoding="utf-8")
    block = _decision_block(decision_text, decision_id)
    source = config.raw["source_run"]
    failure = config.raw["original_failure"]
    fix = config.raw["metadata_filename_fix"]
    required = (
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
    missing = [literal for literal in required if literal not in block]
    if missing:
        raise RestrictedRerunError(f"D-0035 lacks exact restricted-rerun bindings: {missing}")
    if re.search(
        r"STAGE1_(?:RESULT|CANCELLATION_SUMMARY)_SHA256\s*=",
        block,
    ):
        raise RestrictedRerunError("D-0035 must not predeclare future Stage-1 SHA values")
    if re.search(r"\b(?:PLACEHOLDER|PENDING|TBD|ESTIMATE|UNSET)\b", block, re.IGNORECASE):
        raise RestrictedRerunError("D-0035 contains unresolved text")
    return block, hashlib.sha256(block.encode()).hexdigest()


def _stage1_plan(config: RestrictedRerunConfig, bundle: dict[str, Any]) -> dict[str, Any]:
    try:
        terminal = validate_stage1_terminal(
            config.stage1_result_path,
            config.stage1_summary_path,
            expected_config_path=config.stage1_config_path,
        )
    except Stage1TerminalError as exc:
        raise RestrictedRerunError(f"Stage-1 terminal validation failed: {exc}") from exc
    result_path = terminal.result_path
    summary_path = terminal.summary_path
    rows = list(terminal.rows)
    cancellations = list(terminal.cancellations)
    sa3_rows = {row["axis"]: row for row in rows if row["backbone"] == SA3_BACKBONE}
    survivor_axes = sorted(
        axis for axis, row in sa3_rows.items() if row["verdict"] == "OUTCOME_SCREEN_PASS"
    )
    stop_axes = sorted(set(AXES) - set(survivor_axes))

    units = bundle["units"]
    groups = bundle["prefix_groups"]
    actions = bundle["action_map"]
    survivor_units = {
        str(row["lane_request_sha256"]) for row in units if row["axis"] in survivor_axes
    }
    cancelled_units = {str(row["lane_request_sha256"]) for row in units if row["axis"] in stop_axes}
    cancellation_ids = {
        str(row["lane_request_sha256"])
        for row in cancellations
        if row.get("backbone") == SA3_BACKBONE
    }
    if cancellation_ids != cancelled_units or survivor_units & cancelled_units:
        raise RestrictedRerunError("Stage-1 SA3 cancellation identities do not partition the queue")
    survivor_groups: list[str] = []
    cancelled_groups: list[str] = []
    for group in groups:
        member_ids = set(group["lane_request_sha256s"])
        identity = str(group["group_request_sha256"])
        if member_ids <= survivor_units:
            survivor_groups.append(identity)
        elif member_ids <= cancelled_units:
            cancelled_groups.append(identity)
        else:
            raise RestrictedRerunError("a prefix group crosses the Stage-1 survivor boundary")
    if any(
        (str(row["lane_request_sha256"]) in cancelled_units) == (row["axis"] not in stop_axes)
        for row in actions
    ):
        raise RestrictedRerunError("action-map cancellation partition drifted")
    failed_id = config.raw["original_failure"]["failed_lane_request_sha256"]
    failed_group = config.raw["original_failure"]["failed_group_request_sha256"]
    validation_group: str | None
    if not survivor_groups:
        validation_group = None
    elif failed_id in survivor_units:
        validation_group = failed_group
    else:
        sequence = {str(row["group_request_sha256"]): int(row["group_sequence"]) for row in groups}
        validation_group = min(survivor_groups, key=sequence.__getitem__)
    return {
        "action_map_sha256": config.raw["source_run"]["queue"]["action_map"]["sha256"],
        "cancelled_action_count": sum(
            str(row["lane_request_sha256"]) in cancelled_units for row in actions
        ),
        "cancelled_group_request_sha256s": sorted(cancelled_groups),
        "cancelled_lane_request_sha256s": sorted(cancelled_units),
        "failed_unit_disposition": (
            "AUTHORIZED_VERBATIM_RERUN_ONCE"
            if failed_id in survivor_units
            else "CANCELLED_STAGE1_NO_RERUN"
        ),
        "folds_sha256": config.raw["source_run"]["queue"]["folds"]["sha256"],
        "no_third_repair": True,
        "original_failed_lane_request_sha256": failed_id,
        "original_queue_bytes_reused_without_rewrite": True,
        "prefix_groups_sha256": config.raw["source_run"]["queue"]["prefix_groups"]["sha256"],
        "schema_version": 1,
        "stage1_result_sha256": sha256_file(result_path),
        "stage1_summary_sha256": sha256_file(summary_path),
        "status": "ALL_CANCELLED_NO_EXECUTION" if not survivor_groups else "SURVIVORS_SCOPED",
        "stop_axes": stop_axes,
        "survivor_action_count": sum(
            str(row["lane_request_sha256"]) in survivor_units for row in actions
        ),
        "survivor_axes": survivor_axes,
        "survivor_group_request_sha256s": sorted(survivor_groups),
        "survivor_lane_request_sha256s": sorted(survivor_units),
        "units_sha256": config.raw["source_run"]["queue"]["units"]["sha256"],
        "validation_group_request_sha256": validation_group,
    }


def prepare_restricted_rerun(
    config_path: Path,
    *,
    decisions_path: Path,
    decision_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Materialize the sole D-0035 rerun scope; never import a model or probe CUDA."""

    config = load_restricted_rerun_config(config_path, repo_root=repo_root)
    bundle = _audit_source_run(config)
    plan = _stage1_plan(config, bundle)
    block, block_sha = verify_rerun_decision(
        decisions_path,
        decision_id=decision_id,
        config=config,
    )
    git_state = observe_clean_origin_main(repo_root)
    run_dir = (config.run_root / config.run_id).resolve()
    if config.attempt_claim_path.exists() or run_dir.exists():
        raise RestrictedRerunError("D-0035 one-attempt run/claim already exists; no third repair")
    run_dir.mkdir(parents=True, exist_ok=False)
    _fsync_directory(run_dir.parent)
    plan_path = run_dir / "control" / "stage1-survivor-execution-plan.json"
    _write_json_exclusive(plan_path, plan)
    claim = {
        "authorization_status": AUTHORIZATION_STATUS,
        "authorized_at_utc": _utc_now(),
        "config_path": str(config.source_path),
        "config_sha256": config.source_sha256,
        "decision_block_sha256": block_sha,
        "decision_id": decision_id,
        "git_commit": git_state.head,
        "git_origin_main": git_state.origin_main,
        "no_third_repair": True,
        "one_root_validation_required": plan["validation_group_request_sha256"] is not None,
        "run_dir": str(run_dir),
        "run_id": config.run_id,
        "schema_version": 1,
        "stage1_cancellation_summary_path": str(config.stage1_summary_path),
        "stage1_cancellation_summary_sha256": plan["stage1_summary_sha256"],
        "stage1_plan_path": str(plan_path),
        "stage1_plan_sha256": sha256_file(plan_path),
        "stage1_result_path": str(config.stage1_result_path),
        "stage1_result_sha256": plan["stage1_result_sha256"],
        "stage1_runtime_sha256_binding": "VERIFIED_AND_RECORDED_AT_LAUNCH",
        "survivors_only": True,
    }
    _write_json_exclusive(config.attempt_claim_path, claim)
    manifest = {
        "authorization_status": AUTHORIZATION_STATUS,
        "attempt_claim_path": str(config.attempt_claim_path),
        "attempt_claim_sha256": sha256_file(config.attempt_claim_path),
        "config_sha256": config.source_sha256,
        "git_commit": git_state.head,
        "queue_manifest_path": str(config.queue_manifest_path),
        "queue_manifest_sha256": config.raw["source_run"]["queue"]["manifest"]["sha256"],
        "run_id": config.run_id,
        "schema_version": 1,
        "stage1_cancellation_summary_sha256": plan["stage1_summary_sha256"],
        "stage1_plan_path": str(plan_path),
        "stage1_plan_sha256": sha256_file(plan_path),
        "stage1_result_sha256": plan["stage1_result_sha256"],
        "status": PREPARED_STATUS,
    }
    manifest_path = run_dir / "run-manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    return {
        "run_dir": str(run_dir),
        "run_manifest_path": str(manifest_path),
        "run_manifest_sha256": sha256_file(manifest_path),
        "status": PREPARED_STATUS,
        "survivor_group_count": len(plan["survivor_group_request_sha256s"]),
        "validation_group_request_sha256": plan["validation_group_request_sha256"],
    }


def validate_restricted_run(
    run_dir: Path,
    *,
    config: RestrictedRerunConfig,
    git_state: GitLaunchState,
) -> dict[str, Any]:
    root = run_dir.resolve(strict=True)
    manifest = load_json(root / "run-manifest.json")
    if (
        manifest.get("status") != PREPARED_STATUS
        or manifest.get("authorization_status") != AUTHORIZATION_STATUS
        or manifest.get("config_sha256") != config.source_sha256
        or manifest.get("git_commit") != git_state.head
        or git_state.head != git_state.origin_main
        or manifest.get("run_id") != config.run_id
    ):
        raise RestrictedRerunError("restricted-rerun manifest/Git binding drifted")
    claim_path = Path(str(manifest.get("attempt_claim_path", ""))).resolve(strict=True)
    if claim_path != config.attempt_claim_path or sha256_file(claim_path) != manifest.get(
        "attempt_claim_sha256"
    ):
        raise RestrictedRerunError("restricted-rerun attempt claim drifted")
    claim = load_json(claim_path)
    if (
        claim.get("stage1_result_sha256") != sha256_file(config.stage1_result_path)
        or claim.get("stage1_cancellation_summary_sha256")
        != sha256_file(config.stage1_summary_path)
        or claim.get("stage1_runtime_sha256_binding") != "VERIFIED_AND_RECORDED_AT_LAUNCH"
    ):
        raise RestrictedRerunError("restricted-rerun Stage-1 launch binding drifted")
    plan_path = Path(str(manifest.get("stage1_plan_path", ""))).resolve(strict=True)
    try:
        plan_path.relative_to(root)
    except ValueError as exc:
        raise RestrictedRerunError("restricted-rerun plan escapes run directory") from exc
    if sha256_file(plan_path) != manifest.get("stage1_plan_sha256"):
        raise RestrictedRerunError("restricted-rerun plan bytes drifted")
    _audit_source_run(config)
    bundle = load_sa3_state_capture_bundle(config.queue_manifest_path, config=config.state_config)
    plan = _stage1_plan(config, bundle)
    if plan != load_json(plan_path):
        raise RestrictedRerunError("restricted-rerun survivor plan no longer matches Stage-1")
    return {"manifest": manifest, "plan": plan, "plan_path": plan_path}


@dataclass(frozen=True)
class RestrictedExecutionScope:
    """Worker-facing allowlist derived only from the validated immutable plan."""

    phase: str
    run_dir: Path
    plan: dict[str, Any]

    @property
    def _transition_lock_path(self) -> Path:
        return self.run_dir / "control" / "restricted-rerun-transition.lock"

    @contextmanager
    def _transition_lock(self, *, require_open: bool) -> Iterator[None]:
        """Serialize failure latching against claims and artifact publication."""

        path = self._transition_lock_path
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if require_open:
                self.require_open()
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @contextmanager
    def atomic_open(self) -> Iterator[None]:
        """Order a claim/start or publication atomically before FAILED_STOPPED."""

        with self._transition_lock(require_open=True):
            yield

    def require_open(self) -> None:
        if (self.run_dir / "control" / "restricted-rerun-failure.terminal.json").exists():
            raise RestrictedRerunError("restricted rerun is permanently FAILED_STOPPED")

    def require_scoreable(self, lane_request_sha256: str) -> None:
        """Reject STOP units at the state-result scoring boundary."""

        if lane_request_sha256 in set(self.plan["cancelled_lane_request_sha256s"]):
            raise RestrictedRerunError("CANCELLED_STAGE1 unit may never be scored")
        if lane_request_sha256 not in set(self.plan["survivor_lane_request_sha256s"]):
            raise RestrictedRerunError("state-result identity is outside the immutable queue")

    def select(
        self,
        *,
        units: Sequence[Mapping[str, Any]],
        groups: Sequence[Mapping[str, Any]],
        replica_index: int,
        replica_count: int,
    ) -> list[Mapping[str, Any]]:
        self.require_open()
        survivor_units = set(self.plan["survivor_lane_request_sha256s"])
        cancelled_units = set(self.plan["cancelled_lane_request_sha256s"])
        observed_units = {str(row["lane_request_sha256"]) for row in units}
        if survivor_units | cancelled_units != observed_units or survivor_units & cancelled_units:
            raise RestrictedRerunError("scope does not partition the exact immutable unit queue")
        survivor_groups = set(self.plan["survivor_group_request_sha256s"])
        cancelled_groups = set(self.plan["cancelled_group_request_sha256s"])
        observed_groups = {str(row["group_request_sha256"]) for row in groups}
        if (
            survivor_groups | cancelled_groups != observed_groups
            or survivor_groups & cancelled_groups
        ):
            raise RestrictedRerunError("scope does not partition the exact immutable group queue")
        selected_ids = survivor_groups
        if self.phase == "validation":
            validation = self.plan["validation_group_request_sha256"]
            if validation is None:
                raise RestrictedRerunError(
                    "all Stage-1 cells stopped; validation execution is forbidden"
                )
            selected_ids = {validation}
        elif self.phase == "continuation":
            validate_validation_pass(self.run_dir, self.plan)
        else:
            raise RestrictedRerunError("unsupported restricted-rerun phase")
        selected = [row for row in groups if str(row["group_request_sha256"]) in selected_ids]
        for group in selected:
            if not set(group["lane_request_sha256s"]) <= survivor_units:
                raise RestrictedRerunError("STOP unit reached the executable worker scope")
        assigned = [
            row
            for row in selected
            if (int(row["group_sequence"]) - 1) % replica_count == replica_index
        ]
        if self.phase == "validation" and len(assigned) != 1:
            raise RestrictedRerunError("validation must run on its single static-shard owner")
        return assigned

    def record_failure(self, *, identity: str | None, kind: str, error: BaseException) -> None:
        path = self.run_dir / "control" / "restricted-rerun-failure.terminal.json"
        payload = {
            "error_message": str(error)[:2000],
            "error_type": type(error).__name__,
            "failed_at_utc": _utc_now(),
            "identity": identity,
            "kind": kind,
            "no_third_repair": True,
            "phase": self.phase,
            "schema_version": 1,
            "status": "FAILED_STOPPED",
        }
        with self._transition_lock(require_open=False):
            try:
                _write_json_exclusive(path, payload)
            except FileExistsError as exc:
                existing = load_json(path)
                if (
                    existing.get("status") != "FAILED_STOPPED"
                    or existing.get("no_third_repair") is not True
                ):
                    raise RestrictedRerunError(
                        "restricted-rerun failure terminal is invalid"
                    ) from exc


def load_execution_scope(
    run_dir: Path, *, plan: dict[str, Any], phase: str
) -> RestrictedExecutionScope:
    scope = RestrictedExecutionScope(phase=phase, run_dir=run_dir.resolve(strict=True), plan=plan)
    scope.require_open()
    validation_marker = scope.run_dir / "control" / "one-root-validation.pass.json"
    if phase == "validation" and validation_marker.exists():
        raise RestrictedRerunError(
            "one-root validation already ran; a second validation is forbidden"
        )
    if phase == "continuation":
        validate_validation_pass(scope.run_dir, plan)
    return scope


def validate_validation_pass(run_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / "control" / "one-root-validation.pass.json"
    marker = load_json(path)
    if (
        marker.get("status") != "ONE_ROOT_VALIDATION_PASS"
        or marker.get("validation_group_request_sha256") != plan["validation_group_request_sha256"]
        or marker.get("stage1_plan_sha256")
        != sha256_file(run_dir / "control" / "stage1-survivor-execution-plan.json")
    ):
        raise RestrictedRerunError("one-root validation marker drifted")
    return marker


def mark_validation_pass(
    run_dir: Path,
    plan: dict[str, Any],
    groups: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Open continuation only after the validation group and its three units succeeded."""

    root = run_dir.resolve(strict=True)
    scope = RestrictedExecutionScope(phase="validation", run_dir=root, plan=plan)
    with scope.atomic_open():
        group_id = plan["validation_group_request_sha256"]
        if not isinstance(group_id, str):
            raise RestrictedRerunError("no validation group exists")
        group = next(
            (row for row in groups if row["group_request_sha256"] == group_id), None
        )
        if group is None:
            raise RestrictedRerunError("validation group is absent from immutable queue")
        states = validate_request_state_machine(validate_ledger(root / "state-ledger.jsonl"))
        required = {group_id, *group["lane_request_sha256s"]}
        if any(states.get(identity) != "SUCCEEDED" for identity in required):
            raise RestrictedRerunError(
                "one-root validation has not succeeded for all four requests"
            )
        marker = {
            "passed_at_utc": _utc_now(),
            "schema_version": 1,
            "stage1_plan_sha256": sha256_file(
                root / "control" / "stage1-survivor-execution-plan.json"
            ),
            "status": "ONE_ROOT_VALIDATION_PASS",
            "succeeded_request_sha256s": sorted(required),
            "validation_group_request_sha256": group_id,
        }
        _write_json_exclusive(root / "control" / "one-root-validation.pass.json", marker)
        return marker


__all__ = [
    "AUTHORIZATION_STATUS",
    "PREPARED_STATUS",
    "RestrictedExecutionScope",
    "RestrictedRerunConfig",
    "RestrictedRerunError",
    "audit_original_source",
    "load_execution_scope",
    "load_restricted_rerun_config",
    "mark_validation_pass",
    "prepare_restricted_rerun",
    "validate_restricted_run",
    "validate_validation_pass",
    "verify_rerun_decision",
]

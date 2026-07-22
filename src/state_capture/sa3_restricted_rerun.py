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
ENGINEERING_GOVERNANCE_DECISION_ID = "D-0045"
ENGINEERING_GOVERNANCE_ASSIGNMENTS = {
    "ENGINEERING_FAILURES_REPAIRABLE": "YES",
    "WITHIN_ATTEMPT_RETRY": "NO",
    "ENGINEERING_REPAIR_REQUIRES_NEW_RUN_ID": "YES",
    "ENGINEERING_REPAIR_REQUIRES_NEW_CLAIM": "YES",
    "SCIENTIFIC_RERUNS_FOR_WEAK_RESULTS": "NO",
    "FROZEN_SCIENTIFIC_DESIGN_CHANGES_AUTHORIZED": "NO",
    "FAILED_ATTEMPTS_IMMUTABLE": "YES",
    "STOP_AXIS_UNITS_EXECUTABLE": "NO",
}
SA3_ATTEMPT_ID_PATTERN = re.compile(r"^sa3-state-v2-restricted-rerun-(\d{3})$")


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


def _semantic_decision_block_sha256(block: str) -> str:
    """Hash decision semantics without the append-only boundary newline."""

    return hashlib.sha256((block.rstrip() + "\n").encode()).hexdigest()


def verify_engineering_governance(decisions_path: Path) -> tuple[str, str]:
    """Bind D-0045 without weakening any D-0035 scientific restriction."""

    text = decisions_path.resolve(strict=True).read_text(encoding="utf-8")
    block = _decision_block(text, ENGINEERING_GOVERNANCE_DECISION_ID)
    assignments: dict[str, str] = {}
    for key, value in re.findall(r"`?([A-Z0-9_]+)\s*=\s*([^`\n]+?)`?(?=\n|$)", block):
        if key in assignments:
            raise RestrictedRerunError(f"duplicate D-0045 assignment: {key}")
        assignments[key] = value.strip()
    missing = [
        key
        for key, value in ENGINEERING_GOVERNANCE_ASSIGNMENTS.items()
        if assignments.get(key) != value
    ]
    if missing:
        raise RestrictedRerunError(f"D-0045 lacks exact engineering assignments: {missing}")
    d0035 = text.find("## D-0035")
    d0045 = text.find("## D-0045")
    if d0035 < 0 or d0045 <= d0035:
        raise RestrictedRerunError("D-0045 must append after the D-0035 scientific opening")
    return block, hashlib.sha256(block.encode()).hexdigest()


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


def _attempt_placement(
    config: RestrictedRerunConfig,
    *,
    physical_gpu_ids: Sequence[int],
) -> dict[str, Any]:
    ids = tuple(physical_gpu_ids)
    allowed = config.state_config.placement.allowed_physical_gpu_ids
    if not ids or len(ids) != len(set(ids)) or any(value not in allowed for value in ids):
        raise RestrictedRerunError("SA3 attempt GPU IDs must be a unique nonempty allowed subset")
    return {
        "node": "an12",
        "physical_gpu_ids": list(ids),
        "replica_count": len(ids),
        "tensor_parallel_width": 1,
        "placement_justification": (
            f"{len(ids)} independent TP1 SA3 state replica(s) on exact an12 GPU IDs "
            f"{list(ids)}; every worker retains live idle/headroom and cooperative-lock checks."
        ),
    }


def _receipt_file_binding(
    record: Mapping[str, Any],
    *,
    prefix: str,
    context: str,
) -> Path:
    path_value = record.get(f"{prefix}_path")
    expected_sha = record.get(f"{prefix}_sha256")
    if not isinstance(path_value, str) or not isinstance(expected_sha, str):
        raise RestrictedRerunError(f"{context} binding is absent")
    unresolved = Path(path_value)
    if unresolved.is_symlink():
        raise RestrictedRerunError(f"{context} must not be a symlink")
    source = unresolved.resolve(strict=True)
    if not source.is_file() or sha256_file(source) != require_sha256(expected_sha, context):
        raise RestrictedRerunError(f"{context} binding drifted")
    return source


def _validate_zero_call_carried_repair(
    record: Mapping[str, Any],
    *,
    predecessor_run_id: str,
    expected_scientific_bindings: Mapping[str, str],
    completed_exclusion_path: Path | None,
    remaining_manifest_path: Path | None,
    config: RestrictedRerunConfig | None,
    bundle: Mapping[str, Any] | None,
    source_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Revalidate a remaining-only package carried through a zero-call attempt."""

    if (
        completed_exclusion_path is None
        or remaining_manifest_path is None
        or config is None
        or bundle is None
        or source_plan is None
    ):
        raise RestrictedRerunError(
            "zero-call carried repair lacks the exact completed exclusion/remaining package"
        )
    from state_capture.sa3_remaining_repair import validate_remaining_repair_package

    repair = validate_remaining_repair_package(
        remaining_manifest_path,
        exclusion_path=completed_exclusion_path,
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    claim_path = _receipt_file_binding(
        record,
        prefix="attempt_claim",
        context="zero-call predecessor attempt claim",
    )
    manifest_path = _receipt_file_binding(
        record,
        prefix="run_manifest",
        context="zero-call predecessor run manifest",
    )
    plan_path = _receipt_file_binding(
        record,
        prefix="stage1_execution_plan",
        context="zero-call predecessor execution plan",
    )
    exclusion_source = _receipt_file_binding(
        record,
        prefix="completed_exclusion",
        context="zero-call predecessor completed exclusion",
    )
    remaining_source = _receipt_file_binding(
        record,
        prefix="remaining_manifest",
        context="zero-call predecessor remaining manifest",
    )
    run_root = manifest_path.parent
    claim = load_json(claim_path)
    manifest = load_json(manifest_path)
    claim_predecessor = claim.get("predecessor_failure")
    manifest_predecessor = manifest.get("predecessor_failure")
    claim_repair = (
        claim_predecessor.get("remaining_repair") if isinstance(claim_predecessor, dict) else None
    )
    manifest_repair = (
        manifest_predecessor.get("remaining_repair")
        if isinstance(manifest_predecessor, dict)
        else None
    )
    carried_plan = _plan_for_attempt(source_plan, {"remaining_repair": repair})
    placement = claim.get("placement")
    receipt_placement = {
        "authorized_execution_replica_count": 1,
        "node": "an12",
        "physical_gpu_ids": [4],
        "tensor_parallel_width": 1,
    }
    remaining_decision = claim.get("remaining_repair_decision")
    if (
        record.get("remaining_repair_carried_forward") is not True
        or record.get("valid_completed_units_rerun") is not False
        or record.get("worker_started") is not False
        or record.get("gpu_seconds") != 0
        or not isinstance(record.get("failure_kind"), str)
        or not record.get("failure_kind")
        or not isinstance(record.get("repair"), dict)
        or record["repair"].get("scientific_configuration_changed") is not False
        or record["repair"].get("thresholds_changed") is not False
        or record.get("placement") != receipt_placement
        or exclusion_source != Path(repair["completed_exclusion_path"])
        or remaining_source != Path(repair["remaining_manifest_path"])
        or run_root.name != predecessor_run_id
        or manifest_path != run_root / "run-manifest.json"
        or plan_path != run_root / "control" / "stage1-survivor-execution-plan.json"
        or manifest.get("run_id") != predecessor_run_id
        or claim.get("run_id") != predecessor_run_id
        or manifest.get("attempt_claim_path") != str(claim_path)
        or manifest.get("attempt_claim_sha256") != sha256_file(claim_path)
        or claim.get("scientific_bindings") != dict(expected_scientific_bindings)
        or manifest.get("scientific_bindings") != dict(expected_scientific_bindings)
        or claim_repair != repair
        or manifest_repair != repair
        or not isinstance(remaining_decision, dict)
        or manifest.get("remaining_repair_decision") != remaining_decision
        or claim.get("one_root_validation_required") is not False
        or placement
        != {
            "node": "an12",
            "physical_gpu_ids": [4],
            "placement_justification": (
                "1 independent TP1 SA3 state replica(s) on exact an12 GPU IDs [4]; "
                "every worker retains live idle/headroom and cooperative-lock checks."
            ),
            "replica_count": 1,
            "tensor_parallel_width": 1,
        }
        or manifest.get("placement") != placement
        or manifest.get("stage1_plan_path") != str(plan_path)
        or manifest.get("stage1_plan_sha256") != sha256_file(plan_path)
        or claim.get("stage1_plan_path") != str(plan_path)
        or claim.get("stage1_plan_sha256") != sha256_file(plan_path)
        or load_json(plan_path) != carried_plan
    ):
        raise RestrictedRerunError("zero-call predecessor carried-repair lineage drifted")
    prohibited_outputs = (
        run_root / "state-ledger.jsonl",
        run_root / "artifacts",
        run_root / "staging",
        run_root / "workers",
        run_root / "control" / "shared-state-claims",
    )
    if any(path.exists() for path in prohibited_outputs):
        raise RestrictedRerunError("zero-call predecessor contains worker/model artifacts")
    decision_id = remaining_decision.get("decision_id")
    decision_path = claim.get("engineering_governance_decisions_path")
    if not isinstance(decision_id, str) or not isinstance(decision_path, str):
        raise RestrictedRerunError("zero-call predecessor remaining-repair decision is absent")
    _, live_decision_sha = verify_remaining_repair_decision(
        Path(decision_path),
        decision_id=decision_id,
        run_id=predecessor_run_id,
        predecessor=claim_predecessor,
        placement=placement,
        scientific_bindings=expected_scientific_bindings,
    )
    if remaining_decision.get("block_sha256") != live_decision_sha:
        raise RestrictedRerunError("zero-call predecessor remaining-repair decision drifted")
    return repair


def _validate_preclaim_carried_repair(
    record: Mapping[str, Any],
    *,
    base_run_id: str,
    predecessor_run_id: str,
    expected_scientific_bindings: Mapping[str, str],
    completed_exclusion_path: Path | None,
    remaining_manifest_path: Path | None,
    config: RestrictedRerunConfig | None,
    bundle: Mapping[str, Any] | None,
    source_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Carry a validated package through a failure before claim publication."""

    if (
        completed_exclusion_path is None
        or remaining_manifest_path is None
        or config is None
        or bundle is None
        or source_plan is None
    ):
        raise RestrictedRerunError(
            "preclaim repair lacks the exact completed exclusion/remaining package"
        )
    source_failure_path = _receipt_file_binding(
        record,
        prefix="predecessor_failure",
        context="preclaim source predecessor failure",
    )
    source_predecessor = _repair_predecessor(
        source_failure_path,
        base_run_id=base_run_id,
        next_run_id=predecessor_run_id,
        expected_scientific_bindings=expected_scientific_bindings,
        completed_exclusion_path=completed_exclusion_path,
        remaining_manifest_path=remaining_manifest_path,
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    if source_predecessor is None or not isinstance(
        source_predecessor.get("remaining_repair"), dict
    ):
        raise RestrictedRerunError("preclaim source predecessor lacks remaining-work lineage")
    repair = source_predecessor["remaining_repair"]
    exclusion_source = _receipt_file_binding(
        record,
        prefix="completed_exclusion",
        context="preclaim completed exclusion",
    )
    remaining_source = _receipt_file_binding(
        record,
        prefix="remaining_manifest",
        context="preclaim remaining manifest",
    )
    repair_record = record.get("repair")
    if (
        record.get("attempt_id") != f"{predecessor_run_id}-preclaim-001"
        or record.get("claim_created") is not False
        or record.get("run_dir_created") is not False
        or record.get("worker_started") is not False
        or record.get("gpu_seconds") != 0
        or record.get("phase") != "PREDECESSOR_VALIDATION_BEFORE_CLAIM_RUN_PUBLICATION_OR_GPU_USE"
        or not isinstance(record.get("failure_kind"), str)
        or not record.get("failure_kind")
        or not isinstance(repair_record, dict)
        or repair_record.get("scientific_configuration_changed") is not False
        or repair_record.get("thresholds_changed") is not False
        or exclusion_source != Path(repair["completed_exclusion_path"])
        or remaining_source != Path(repair["remaining_manifest_path"])
    ):
        raise RestrictedRerunError("preclaim carried-repair evidence drifted")
    expected_claim_path = (
        config.attempt_claim_path.parent / f"{predecessor_run_id}.claim.json"
    ).resolve()
    expected_run_dir = (config.run_root / predecessor_run_id).resolve()
    if expected_claim_path.exists() or expected_run_dir.exists():
        raise RestrictedRerunError("preclaim failure unexpectedly published a claim or run")

    source_record = load_json(source_failure_path)
    source_claim_path = _receipt_file_binding(
        source_record,
        prefix="attempt_claim",
        context="preclaim source attempt claim",
    )
    source_claim = load_json(source_claim_path)
    source_decision = record.get("source_remaining_decision")
    source_claim_decision = source_claim.get("remaining_repair_decision")
    if (
        not isinstance(source_decision, dict)
        or not isinstance(source_claim_decision, dict)
        or source_decision.get("decision_id") != source_claim_decision.get("decision_id")
        or source_decision.get("canonical_block_sha256")
        != source_claim_decision.get("block_sha256")
    ):
        raise RestrictedRerunError("preclaim source decision lineage drifted")

    opening = record.get("opening_decision")
    if not isinstance(opening, dict) or not isinstance(opening.get("decision_id"), str):
        raise RestrictedRerunError("preclaim opening decision binding is absent")
    placement = _attempt_placement(config, physical_gpu_ids=(4,))
    _, opening_sha = verify_remaining_repair_decision(
        config.repo_root / "DECISIONS.md",
        decision_id=opening["decision_id"],
        run_id=predecessor_run_id,
        predecessor=source_predecessor,
        placement=placement,
        scientific_bindings=expected_scientific_bindings,
    )
    if opening.get("canonical_block_sha256") != opening_sha:
        raise RestrictedRerunError("preclaim opening decision drifted")
    return repair


def _repair_predecessor(
    path: Path | None,
    *,
    base_run_id: str,
    next_run_id: str,
    expected_scientific_bindings: Mapping[str, str],
    completed_exclusion_path: Path | None = None,
    remaining_manifest_path: Path | None = None,
    config: RestrictedRerunConfig | None = None,
    bundle: Mapping[str, Any] | None = None,
    source_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if next_run_id == base_run_id:
        if path is not None:
            raise RestrictedRerunError("base attempt may not name a repair predecessor")
        if completed_exclusion_path is not None or remaining_manifest_path is not None:
            raise RestrictedRerunError("base attempt may not name a remaining-work package")
        return None
    next_match = SA3_ATTEMPT_ID_PATTERN.fullmatch(next_run_id)
    base_match = SA3_ATTEMPT_ID_PATTERN.fullmatch(base_run_id)
    if base_match is None or next_match is None:
        raise RestrictedRerunError("SA3 engineering repair run ID is invalid")
    if path is None:
        raise RestrictedRerunError("SA3 engineering repair requires a predecessor failure receipt")
    source = path.resolve(strict=True)
    record = load_json(source)
    predecessor_run_id = record.get("run_id")
    predecessor_match = (
        SA3_ATTEMPT_ID_PATTERN.fullmatch(predecessor_run_id)
        if isinstance(predecessor_run_id, str)
        else None
    )
    common_invalid = (
        record.get("schema_version") != 1
        or predecessor_match is None
        or int(predecessor_match.group(1)) < int(base_match.group(1))
        or int(next_match.group(1)) != int(predecessor_match.group(1)) + 1
        or record.get("failure_classification") != "ENGINEERING_BUG"
        or record.get("scientific_design_changed") is not False
        or record.get("scientific_outputs_retained") is not True
        or record.get("failed_attempt_immutable") is not True
        or record.get("repair_requires_new_run_id") is not True
        or record.get("repair_requires_new_claim") is not True
        or record.get("scientific_bindings") != dict(expected_scientific_bindings)
    )
    if common_invalid:
        raise RestrictedRerunError(
            "SA3 predecessor is not the immediately prior immutable engineering failure "
            "with identical science bindings"
        )
    status = record.get("status")
    remaining_repair: dict[str, Any] | None = None
    if status == "FAILED_PRE_MODEL_ENGINEERING":
        if record.get("model_calls") != 0 or record.get("generated_outputs") != 0:
            raise RestrictedRerunError("pre-model predecessor is not zero-call")
        carries_repair = record.get("remaining_repair_carried_forward") is True
        package_named = completed_exclusion_path is not None or remaining_manifest_path is not None
        if carries_repair != package_named:
            raise RestrictedRerunError("zero-call predecessor carried-repair declaration drifted")
        if carries_repair:
            remaining_repair = _validate_zero_call_carried_repair(
                record,
                predecessor_run_id=str(predecessor_run_id),
                expected_scientific_bindings=expected_scientific_bindings,
                completed_exclusion_path=completed_exclusion_path,
                remaining_manifest_path=remaining_manifest_path,
                config=config,
                bundle=bundle,
                source_plan=source_plan,
            )
    elif status == "FAILED_PRE_CLAIM_ENGINEERING":
        if record.get("model_calls") != 0 or record.get("generated_outputs") != 0:
            raise RestrictedRerunError("preclaim predecessor is not zero-call")
        remaining_repair = _validate_preclaim_carried_repair(
            record,
            base_run_id=base_run_id,
            predecessor_run_id=str(predecessor_run_id),
            expected_scientific_bindings=expected_scientific_bindings,
            completed_exclusion_path=completed_exclusion_path,
            remaining_manifest_path=remaining_manifest_path,
            config=config,
            bundle=bundle,
            source_plan=source_plan,
        )
    elif status == "FAILED_ENGINEERING_ATTEMPT":
        if (
            record.get("model_calls") != 4
            or record.get("generated_outputs") != 4
            or record.get("valid_completed_units_rerun") is not False
            or config is None
            or bundle is None
            or source_plan is None
            or completed_exclusion_path is None
            or remaining_manifest_path is None
        ):
            raise RestrictedRerunError(
                "post-call predecessor lacks the exact completed exclusion/remaining package"
            )
        from state_capture.sa3_remaining_repair import validate_remaining_repair_package

        remaining_repair = validate_remaining_repair_package(
            remaining_manifest_path,
            exclusion_path=completed_exclusion_path,
            config=config,
            bundle=bundle,
            source_plan=source_plan,
        )
        if (
            remaining_repair["predecessor_run_id"] != predecessor_run_id
            or record.get("completed_exclusion_path")
            != remaining_repair["completed_exclusion_path"]
            or record.get("completed_exclusion_sha256")
            != remaining_repair["completed_exclusion_sha256"]
            or record.get("remaining_manifest_path") != remaining_repair["remaining_manifest_path"]
            or record.get("remaining_manifest_sha256")
            != remaining_repair["remaining_manifest_sha256"]
        ):
            raise RestrictedRerunError("post-call predecessor repair-package binding drifted")
    else:
        raise RestrictedRerunError("SA3 predecessor failure status is not repairable")
    result = {
        "path": str(source),
        "sha256": sha256_file(source),
        "status": status,
    }
    if remaining_repair is not None:
        result["remaining_repair"] = remaining_repair
    return result


def _plan_for_attempt(
    source_plan: Mapping[str, Any], predecessor: Mapping[str, Any] | None
) -> dict[str, Any]:
    plan = dict(source_plan)
    repair = predecessor.get("remaining_repair") if predecessor is not None else None
    if repair is None:
        return plan
    completed_groups = list(repair["completed_group_request_sha256s"])
    completed_units = list(repair["completed_lane_request_sha256s"])
    remaining_groups = list(repair["remaining_group_request_sha256s"])
    remaining_units = list(repair["remaining_lane_request_sha256s"])
    if (
        set(completed_groups) | set(remaining_groups) != set(plan["survivor_group_request_sha256s"])
        or set(completed_groups) & set(remaining_groups)
        or set(completed_units) | set(remaining_units) != set(plan["survivor_lane_request_sha256s"])
        or set(completed_units) & set(remaining_units)
    ):
        raise RestrictedRerunError("remaining-work plan does not partition Stage-1 survivors")
    plan.update(
        {
            "completed_excluded_group_request_sha256s": completed_groups,
            "completed_excluded_lane_request_sha256s": completed_units,
            "completed_units_score_from_predecessor_only": True,
            "failed_unit_disposition": "COMPLETED_IN_PREDECESSOR_EXCLUDED_FROM_RERUN",
            "remaining_group_request_sha256s": remaining_groups,
            "remaining_lane_request_sha256s": remaining_units,
            "remaining_repair_manifest_path": repair["remaining_manifest_path"],
            "remaining_repair_manifest_sha256": repair["remaining_manifest_sha256"],
            "status": "REMAINING_SURVIVORS_SCOPED",
            "validation_rerun_authorized": False,
            "validation_satisfied_by_predecessor": repair["validation_marker"],
        }
    )
    return plan


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
    if (
        set(stage1)
        != {
            "backbone",
            "cancellation_summary_path",
            "gate_config_path",
            "result_path",
        }
        or stage1.get("backbone") != SA3_BACKBONE
    ):
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


def verify_remaining_repair_decision(
    decisions_path: Path,
    *,
    decision_id: str,
    run_id: str,
    predecessor: Mapping[str, Any],
    placement: Mapping[str, Any],
    scientific_bindings: Mapping[str, str],
) -> tuple[str, str]:
    """Require an exact prospective opening for a post-call remaining-only repair."""

    repair = predecessor.get("remaining_repair")
    if not isinstance(repair, dict):
        raise RestrictedRerunError("remaining repair decision requires a post-call package")
    decision_text = decisions_path.resolve(strict=True).read_text(encoding="utf-8")
    block = _decision_block(decision_text, decision_id)
    required = (
        "SA3_STATE_REMAINING_REPAIR_AUTHORIZED = YES",
        f"SA3_STATE_REMAINING_REPAIR_RUN_ID = {run_id}",
        f"SA3_STATE_REMAINING_REPAIR_PREDECESSOR_SHA256 = {predecessor['sha256']}",
        (
            "SA3_STATE_REMAINING_REPAIR_COMPLETED_EXCLUSION_SHA256 = "
            f"{repair['completed_exclusion_sha256']}"
        ),
        (f"SA3_STATE_REMAINING_REPAIR_MANIFEST_SHA256 = {repair['remaining_manifest_sha256']}"),
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
        f"SA3_STATE_REMAINING_REPAIR_CONFIG_SHA256 = {scientific_bindings['config_sha256']}",
        (
            "SA3_STATE_REMAINING_REPAIR_QUEUE_MANIFEST_SHA256 = "
            f"{scientific_bindings['queue_manifest_sha256']}"
        ),
        (
            "SA3_STATE_REMAINING_REPAIR_STAGE1_RESULT_SHA256 = "
            f"{scientific_bindings['stage1_result_sha256']}"
        ),
        (
            "SA3_STATE_REMAINING_REPAIR_STAGE1_SUMMARY_SHA256 = "
            f"{scientific_bindings['stage1_summary_sha256']}"
        ),
    )
    missing = [literal for literal in required if literal not in block]
    if missing:
        raise RestrictedRerunError(
            f"{decision_id} lacks exact remaining-repair bindings: {missing}"
        )
    if (
        placement.get("node") != "an12"
        or placement.get("physical_gpu_ids") != [4]
        or placement.get("replica_count") != 1
        or placement.get("tensor_parallel_width") != 1
    ):
        raise RestrictedRerunError("remaining repair placement differs from D decision")
    if re.search(r"\b(?:PLACEHOLDER|PENDING|TBD|ESTIMATE|UNSET)\b", block, re.IGNORECASE):
        raise RestrictedRerunError("remaining repair decision contains unresolved text")
    return block, _semantic_decision_block_sha256(block)


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
        "engineering_failure_scope": "CURRENT_RUN_ATTEMPT_ONLY",
        "engineering_repair_requires_new_claim": True,
        "engineering_repair_requires_new_run_id": True,
        "within_attempt_retry": False,
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
    run_id: str | None = None,
    attempt_claim_path: Path | None = None,
    physical_gpu_ids: Sequence[int] = (4, 5, 6, 7),
    predecessor_failure_path: Path | None = None,
    completed_exclusion_path: Path | None = None,
    remaining_manifest_path: Path | None = None,
    repair_decision_id: str | None = None,
) -> dict[str, Any]:
    """Materialize one D-0035 execution attempt; never import a model or probe CUDA."""

    config = load_restricted_rerun_config(config_path, repo_root=repo_root)
    bundle = _audit_source_run(config)
    source_plan = _stage1_plan(config, bundle)
    block, block_sha = verify_rerun_decision(
        decisions_path,
        decision_id=decision_id,
        config=config,
    )
    _, engineering_block_sha = verify_engineering_governance(decisions_path)
    git_state = observe_clean_origin_main(repo_root)
    actual_run_id = run_id or config.run_id
    scientific_bindings = {
        "config_sha256": config.source_sha256,
        "queue_manifest_sha256": config.raw["source_run"]["queue"]["manifest"]["sha256"],
        "stage1_result_sha256": source_plan["stage1_result_sha256"],
        "stage1_summary_sha256": source_plan["stage1_summary_sha256"],
    }
    predecessor = _repair_predecessor(
        predecessor_failure_path,
        base_run_id=config.run_id,
        next_run_id=actual_run_id,
        expected_scientific_bindings=scientific_bindings,
        completed_exclusion_path=completed_exclusion_path,
        remaining_manifest_path=remaining_manifest_path,
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    plan = _plan_for_attempt(source_plan, predecessor)
    placement = _attempt_placement(config, physical_gpu_ids=physical_gpu_ids)
    remaining_decision: dict[str, Any] | None = None
    if predecessor is not None and predecessor.get("remaining_repair") is not None:
        if repair_decision_id is None:
            raise RestrictedRerunError("post-call repair requires its exact opening decision")
        repair_block, repair_block_sha = verify_remaining_repair_decision(
            decisions_path,
            decision_id=repair_decision_id,
            run_id=actual_run_id,
            predecessor=predecessor,
            placement=placement,
            scientific_bindings=scientific_bindings,
        )
        remaining_decision = {
            "block_sha256": repair_block_sha,
            "decision_id": repair_decision_id,
        }
        del repair_block
    elif repair_decision_id is not None:
        raise RestrictedRerunError("zero-call repair may not name a remaining-work decision")
    claim_path = (
        attempt_claim_path.resolve()
        if attempt_claim_path is not None
        else config.attempt_claim_path
    )
    if actual_run_id != config.run_id:
        expected_claim = config.attempt_claim_path.parent / f"{actual_run_id}.claim.json"
        if claim_path != expected_claim:
            raise RestrictedRerunError("SA3 repair claim path is not the canonical new-run path")
    elif claim_path != config.attempt_claim_path:
        raise RestrictedRerunError("base SA3 attempt claim path drifted")
    run_dir = (config.run_root / actual_run_id).resolve()
    if claim_path.exists() or run_dir.exists():
        raise RestrictedRerunError(
            "this immutable SA3 attempt run/claim already exists; an engineering repair "
            "requires a new run ID and claim"
        )
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
        "engineering_governance_block_sha256": engineering_block_sha,
        "engineering_governance_decision_id": ENGINEERING_GOVERNANCE_DECISION_ID,
        "engineering_governance_decisions_path": str(decisions_path.resolve(strict=True)),
        "engineering_repair_requires_new_claim": True,
        "engineering_repair_requires_new_run_id": True,
        "failed_attempts_immutable": True,
        "git_commit": git_state.head,
        "git_origin_main": git_state.origin_main,
        "one_root_validation_required": (
            plan["validation_group_request_sha256"] is not None
            and (predecessor is None or predecessor.get("remaining_repair") is None)
        ),
        "placement": placement,
        "predecessor_failure": predecessor,
        "run_dir": str(run_dir),
        "run_id": actual_run_id,
        "schema_version": 1,
        "scientific_bindings": scientific_bindings,
        "remaining_repair_decision": remaining_decision,
        "stage1_cancellation_summary_path": str(config.stage1_summary_path),
        "stage1_cancellation_summary_sha256": plan["stage1_summary_sha256"],
        "stage1_plan_path": str(plan_path),
        "stage1_plan_sha256": sha256_file(plan_path),
        "stage1_result_path": str(config.stage1_result_path),
        "stage1_result_sha256": plan["stage1_result_sha256"],
        "stage1_runtime_sha256_binding": "VERIFIED_AND_RECORDED_AT_LAUNCH",
        "survivors_only": True,
        "within_attempt_retry": False,
    }
    _write_json_exclusive(claim_path, claim)
    manifest = {
        "authorization_status": AUTHORIZATION_STATUS,
        "attempt_claim_path": str(claim_path),
        "attempt_claim_sha256": sha256_file(claim_path),
        "config_sha256": config.source_sha256,
        "engineering_governance_block_sha256": engineering_block_sha,
        "git_commit": git_state.head,
        "placement": placement,
        "predecessor_failure": predecessor,
        "queue_manifest_path": str(config.queue_manifest_path),
        "queue_manifest_sha256": config.raw["source_run"]["queue"]["manifest"]["sha256"],
        "run_id": actual_run_id,
        "schema_version": 1,
        "scientific_bindings": scientific_bindings,
        "remaining_repair_decision": remaining_decision,
        "stage1_cancellation_summary_sha256": plan["stage1_summary_sha256"],
        "stage1_plan_path": str(plan_path),
        "stage1_plan_sha256": sha256_file(plan_path),
        "stage1_result_sha256": plan["stage1_result_sha256"],
        "status": PREPARED_STATUS,
    }
    manifest_path = run_dir / "run-manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    validate_restricted_run(run_dir, config=config, git_state=git_state)
    return {
        "run_dir": str(run_dir),
        "run_manifest_path": str(manifest_path),
        "run_manifest_sha256": sha256_file(manifest_path),
        "status": PREPARED_STATUS,
        "survivor_group_count": len(plan["survivor_group_request_sha256s"]),
        "remaining_group_count": len(
            plan.get(
                "remaining_group_request_sha256s",
                plan["survivor_group_request_sha256s"],
            )
        ),
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
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or SA3_ATTEMPT_ID_PATTERN.fullmatch(run_id) is None:
        raise RestrictedRerunError("restricted-rerun manifest has an invalid attempt run ID")
    if (
        manifest.get("status") != PREPARED_STATUS
        or manifest.get("authorization_status") != AUTHORIZATION_STATUS
        or manifest.get("config_sha256") != config.source_sha256
        or manifest.get("git_commit") != git_state.head
        or git_state.head != git_state.origin_main
        or root.name != run_id
    ):
        raise RestrictedRerunError("restricted-rerun manifest/Git binding drifted")
    claim_path = Path(str(manifest.get("attempt_claim_path", ""))).resolve(strict=True)
    expected_claim_path = (
        config.attempt_claim_path
        if run_id == config.run_id
        else config.attempt_claim_path.parent / f"{run_id}.claim.json"
    )
    if claim_path != expected_claim_path or sha256_file(claim_path) != manifest.get(
        "attempt_claim_sha256"
    ):
        raise RestrictedRerunError("restricted-rerun attempt claim drifted")
    claim = load_json(claim_path)
    scientific_bindings = {
        "config_sha256": config.source_sha256,
        "queue_manifest_sha256": config.raw["source_run"]["queue"]["manifest"]["sha256"],
        "stage1_result_sha256": sha256_file(config.stage1_result_path),
        "stage1_summary_sha256": sha256_file(config.stage1_summary_path),
    }
    placement_raw = claim.get("placement")
    if not isinstance(placement_raw, dict):
        raise RestrictedRerunError("restricted-rerun exact placement is absent")
    gpu_ids = placement_raw.get("physical_gpu_ids")
    if not isinstance(gpu_ids, list):
        raise RestrictedRerunError("restricted-rerun exact GPU list is absent")
    placement = _attempt_placement(config, physical_gpu_ids=gpu_ids)
    if (
        placement_raw != placement
        or manifest.get("placement") != placement
        or claim.get("run_id") != run_id
    ):
        raise RestrictedRerunError("restricted-rerun exact placement/run identity drifted")
    predecessor_path = None
    predecessor_raw = claim.get("predecessor_failure")
    if isinstance(predecessor_raw, dict) and isinstance(predecessor_raw.get("path"), str):
        predecessor_path = Path(predecessor_raw["path"])
    bundle = _audit_source_run(config)
    source_plan = _stage1_plan(config, bundle)
    repair_raw = (
        predecessor_raw.get("remaining_repair") if isinstance(predecessor_raw, dict) else None
    )
    completed_exclusion_path = None
    remaining_manifest_path = None
    if isinstance(repair_raw, dict):
        if isinstance(repair_raw.get("completed_exclusion_path"), str):
            completed_exclusion_path = Path(repair_raw["completed_exclusion_path"])
        if isinstance(repair_raw.get("remaining_manifest_path"), str):
            remaining_manifest_path = Path(repair_raw["remaining_manifest_path"])
    predecessor = _repair_predecessor(
        predecessor_path,
        base_run_id=config.run_id,
        next_run_id=run_id,
        expected_scientific_bindings=scientific_bindings,
        completed_exclusion_path=completed_exclusion_path,
        remaining_manifest_path=remaining_manifest_path,
        config=config,
        bundle=bundle,
        source_plan=source_plan,
    )
    plan = _plan_for_attempt(source_plan, predecessor)
    if (
        predecessor_raw != predecessor
        or manifest.get("predecessor_failure") != predecessor
        or claim.get("scientific_bindings") != scientific_bindings
        or manifest.get("scientific_bindings") != scientific_bindings
    ):
        raise RestrictedRerunError("restricted-rerun predecessor binding drifted")
    remaining_decision = claim.get("remaining_repair_decision")
    if predecessor is not None and predecessor.get("remaining_repair") is not None:
        if not isinstance(remaining_decision, dict) or not isinstance(
            remaining_decision.get("decision_id"), str
        ):
            raise RestrictedRerunError("remaining repair decision binding is absent")
        _, live_repair_block_sha = verify_remaining_repair_decision(
            Path(str(claim["engineering_governance_decisions_path"])),
            decision_id=remaining_decision["decision_id"],
            run_id=run_id,
            predecessor=predecessor,
            placement=placement,
            scientific_bindings=scientific_bindings,
        )
        if (
            remaining_decision.get("block_sha256") != live_repair_block_sha
            or manifest.get("remaining_repair_decision") != remaining_decision
        ):
            raise RestrictedRerunError("remaining repair live decision bytes drifted")
    elif remaining_decision is not None or manifest.get("remaining_repair_decision") is not None:
        raise RestrictedRerunError("nonremaining attempt names a remaining repair decision")
    _, live_engineering_block_sha = verify_engineering_governance(
        Path(
            str(
                claim.get(
                    "engineering_governance_decisions_path",
                    config.repo_root / "DECISIONS.md",
                )
            )
        )
    )
    if (
        claim.get("stage1_result_sha256") != sha256_file(config.stage1_result_path)
        or claim.get("stage1_cancellation_summary_sha256")
        != sha256_file(config.stage1_summary_path)
        or claim.get("stage1_runtime_sha256_binding") != "VERIFIED_AND_RECORDED_AT_LAUNCH"
        or claim.get("engineering_governance_decision_id") != ENGINEERING_GOVERNANCE_DECISION_ID
        or claim.get("engineering_governance_block_sha256") != live_engineering_block_sha
        or manifest.get("engineering_governance_block_sha256") != live_engineering_block_sha
        or claim.get("engineering_repair_requires_new_run_id") is not True
        or claim.get("engineering_repair_requires_new_claim") is not True
        or claim.get("failed_attempts_immutable") is not True
        or claim.get("within_attempt_retry") is not False
        or claim.get("one_root_validation_required")
        is not (
            plan["validation_group_request_sha256"] is not None
            and (predecessor is None or predecessor.get("remaining_repair") is None)
        )
    ):
        raise RestrictedRerunError("restricted-rerun Stage-1/governance launch binding drifted")
    plan_path = Path(str(manifest.get("stage1_plan_path", ""))).resolve(strict=True)
    try:
        plan_path.relative_to(root)
    except ValueError as exc:
        raise RestrictedRerunError("restricted-rerun plan escapes run directory") from exc
    if sha256_file(plan_path) != manifest.get("stage1_plan_sha256"):
        raise RestrictedRerunError("restricted-rerun plan bytes drifted")
    if plan != load_json(plan_path):
        raise RestrictedRerunError("restricted-rerun survivor plan no longer matches Stage-1")
    return {
        "claim": claim,
        "manifest": manifest,
        "placement": placement,
        "plan": plan,
        "plan_path": plan_path,
    }


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
            raise RestrictedRerunError(
                "this restricted-rerun attempt is FAILED_STOPPED; repair requires a new "
                "run ID and claim"
            )

    def require_scoreable(self, lane_request_sha256: str) -> None:
        """Reject STOP units at the state-result scoring boundary."""

        if lane_request_sha256 in set(self.plan["cancelled_lane_request_sha256s"]):
            raise RestrictedRerunError("CANCELLED_STAGE1 unit may never be scored")
        if lane_request_sha256 not in set(self.plan["survivor_lane_request_sha256s"]):
            raise RestrictedRerunError("state-result identity is outside the immutable queue")
        if lane_request_sha256 in set(self.plan.get("completed_excluded_lane_request_sha256s", [])):
            raise RestrictedRerunError(
                "completed predecessor unit must be scored from its bound predecessor artifact"
            )

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
        completed_groups = set(self.plan.get("completed_excluded_group_request_sha256s", []))
        completed_units = set(self.plan.get("completed_excluded_lane_request_sha256s", []))
        remaining_groups = set(self.plan.get("remaining_group_request_sha256s", survivor_groups))
        remaining_units = set(self.plan.get("remaining_lane_request_sha256s", survivor_units))
        if (
            completed_groups | remaining_groups != survivor_groups
            or completed_groups & remaining_groups
            or completed_units | remaining_units != survivor_units
            or completed_units & remaining_units
        ):
            raise RestrictedRerunError("scope remaining/completed survivor partition drifted")
        selected_ids = remaining_groups
        if self.phase == "validation":
            if completed_groups:
                raise RestrictedRerunError(
                    "completed predecessor validation may not be rerun in a repair attempt"
                )
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
            "engineering_failure_repairable": True,
            "engineering_failure_scope": "CURRENT_RUN_ATTEMPT_ONLY",
            "engineering_repair_requires_new_claim": True,
            "engineering_repair_requires_new_run_id": True,
            "error_message": str(error)[:2000],
            "error_type": type(error).__name__,
            "failed_attempt_immutable": True,
            "failed_at_utc": _utc_now(),
            "identity": identity,
            "kind": kind,
            "phase": self.phase,
            "scientific_rerun_for_weak_result_allowed": False,
            "schema_version": 1,
            "status": "FAILED_STOPPED",
            "within_attempt_retry": False,
        }
        with self._transition_lock(require_open=False):
            try:
                _write_json_exclusive(path, payload)
            except FileExistsError as exc:
                existing = load_json(path)
                if (
                    existing.get("status") != "FAILED_STOPPED"
                    or existing.get("failed_attempt_immutable") is not True
                    or existing.get("within_attempt_retry") is not False
                    or existing.get("engineering_repair_requires_new_run_id") is not True
                    or existing.get("engineering_repair_requires_new_claim") is not True
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
    predecessor_marker = plan.get("validation_satisfied_by_predecessor")
    if isinstance(predecessor_marker, dict):
        path = Path(str(predecessor_marker.get("path", ""))).resolve(strict=True)
        marker = load_json(path)
        if (
            sha256_file(path) != predecessor_marker.get("sha256")
            or marker.get("status") != "ONE_ROOT_VALIDATION_PASS"
            or marker.get("validation_group_request_sha256")
            != plan["validation_group_request_sha256"]
            or set(marker.get("succeeded_request_sha256s", []))
            != {
                *plan["completed_excluded_group_request_sha256s"],
                *plan["completed_excluded_lane_request_sha256s"],
            }
        ):
            raise RestrictedRerunError("predecessor one-root validation marker drifted")
        return marker
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
        group = next((row for row in groups if row["group_request_sha256"] == group_id), None)
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
    "verify_engineering_governance",
    "verify_remaining_repair_decision",
]

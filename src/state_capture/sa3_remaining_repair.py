"""Materialize and validate an exact SA3 remaining-work repair package.

The package is identity-only engineering evidence.  It reads no evaluator
outcome and never constructs a model.  A completed validation group is bound
to its successful ledger transitions and retained artifacts, then removed
from the executable queue without renumbering any remaining row.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from benchmark_core.ledger import validate_ledger, validate_request_state_machine
from scoring.common import canonical_json, load_json, load_jsonl, sha256_file
from scoring.storage import write_json_exclusive, write_jsonl_exclusive
from state_capture.sa3_contract import load_sa3_state_capture_bundle
from state_capture.sa3_restricted_rerun import (
    RestrictedRerunError,
    load_restricted_rerun_config,
)

PACKAGE_STATUS = "SA3_REMAINING_REPAIR_PACKAGE_COMPLETE"
EXCLUSION_STATUS = "COMPLETED_VALIDATION_EXCLUDED_FROM_RERUN"


def _regular_file(path: Path, label: str) -> Path:
    source = path.resolve(strict=True)
    mode = source.stat().st_mode
    if not stat.S_ISREG(mode) or source.is_symlink():
        raise RestrictedRerunError(f"{label} must be a nonsymlink regular file")
    return source


def _binding(path: Path, *, row_count: int | None = None) -> dict[str, Any]:
    source = _regular_file(path, "repair package binding")
    result: dict[str, Any] = {"path": str(source), "sha256": sha256_file(source)}
    if row_count is not None:
        result["row_count"] = row_count
    return result


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    source = root.resolve(strict=True)
    rows: list[dict[str, Any]] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise RestrictedRerunError("completed validation artifact tree contains a symlink")
        if not path.is_file():
            continue
        rows.append(
            {
                "path": str(path.resolve(strict=True)),
                "relative_path": str(path.relative_to(source)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    if not rows:
        raise RestrictedRerunError("completed validation artifact tree is empty")
    return rows


def _commit_bindings(
    artifact_root: Path,
    *,
    group: Mapping[str, Any],
    units: list[Mapping[str, Any]],
) -> dict[str, Any]:
    commits = sorted(artifact_root.rglob("*.commit.json"))
    group_commits: list[dict[str, Any]] = []
    unit_commits: dict[str, dict[str, Any]] = {}
    for path in commits:
        record = load_json(path)
        if record.get("status") != "COMMITTED":
            raise RestrictedRerunError("completed validation has a noncommitted artifact")
        binding = _binding(path)
        if record.get("group_request_sha256") == group["group_request_sha256"]:
            group_commits.append(binding)
        lane_id = record.get("lane_request_sha256")
        if isinstance(lane_id, str):
            if lane_id in unit_commits:
                raise RestrictedRerunError("completed validation has duplicate unit commits")
            unit_commits[lane_id] = binding
    unit_ids = {str(row["lane_request_sha256"]) for row in units}
    if len(group_commits) != 1 or set(unit_commits) != unit_ids:
        raise RestrictedRerunError("completed validation commit identities are incomplete")
    return {
        "group_commit": group_commits[0],
        "unit_commits": [unit_commits[str(row["lane_request_sha256"])] for row in units],
    }


def _validate_predecessor_identity(
    predecessor_run_dir: Path,
    *,
    expected_run_id: str,
    config_sha256: str,
    plan_sha256: str,
) -> dict[str, Any]:
    root = predecessor_run_dir.resolve(strict=True)
    manifest_path = _regular_file(root / "run-manifest.json", "predecessor manifest")
    manifest = load_json(manifest_path)
    claim_path = _regular_file(
        Path(str(manifest.get("attempt_claim_path", ""))), "predecessor claim"
    )
    claim = load_json(claim_path)
    plan_path = _regular_file(Path(str(manifest.get("stage1_plan_path", ""))), "predecessor plan")
    marker_path = _regular_file(
        root / "control" / "one-root-validation.pass.json", "validation marker"
    )
    if (
        manifest.get("run_id") != expected_run_id
        or claim.get("run_id") != expected_run_id
        or manifest.get("config_sha256") != config_sha256
        or claim.get("config_sha256") != config_sha256
        or plan_path != root / "control" / "stage1-survivor-execution-plan.json"
        or sha256_file(claim_path) != manifest.get("attempt_claim_sha256")
        or sha256_file(plan_path) != plan_sha256
        or manifest.get("stage1_plan_sha256") != plan_sha256
    ):
        raise RestrictedRerunError("predecessor run/claim/plan identity drifted")
    return {
        "claim": _binding(claim_path),
        "manifest": _binding(manifest_path),
        "marker": _binding(marker_path),
        "plan": _binding(plan_path),
    }


def materialize_remaining_repair_package(
    config_path: Path,
    *,
    repo_root: Path,
    predecessor_run_dir: Path,
    predecessor_run_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Write an immutable completed exclusion and the exact remaining rows."""

    config = load_restricted_rerun_config(config_path, repo_root=repo_root)
    bundle = load_sa3_state_capture_bundle(config.queue_manifest_path, config=config.state_config)
    predecessor_root = predecessor_run_dir.resolve(strict=True)
    source_plan_path = predecessor_root / "control" / "stage1-survivor-execution-plan.json"
    source_plan = load_json(source_plan_path)
    source_plan_sha = sha256_file(source_plan_path)
    predecessor = _validate_predecessor_identity(
        predecessor_root,
        expected_run_id=predecessor_run_id,
        config_sha256=config.source_sha256,
        plan_sha256=source_plan_sha,
    )
    validation_group_id = source_plan.get("validation_group_request_sha256")
    groups = list(bundle["prefix_groups"])
    units = list(bundle["units"])
    actions = list(bundle["action_map"])
    group = next(
        (row for row in groups if row.get("group_request_sha256") == validation_group_id),
        None,
    )
    if group is None or validation_group_id not in set(
        source_plan.get("survivor_group_request_sha256s", [])
    ):
        raise RestrictedRerunError("predecessor validation group is not a Stage-1 survivor")
    completed_unit_ids = tuple(str(value) for value in group["lane_request_sha256s"])
    completed_units_by_id = {
        str(row["lane_request_sha256"]): row
        for row in units
        if str(row["lane_request_sha256"]) in set(completed_unit_ids)
    }
    if set(completed_units_by_id) != set(completed_unit_ids):
        raise RestrictedRerunError("predecessor validation unit membership is incomplete")
    completed_units = [completed_units_by_id[value] for value in completed_unit_ids]
    marker = load_json(Path(predecessor["marker"]["path"]))
    completed_request_ids = {validation_group_id, *completed_unit_ids}
    if (
        marker.get("status") != "ONE_ROOT_VALIDATION_PASS"
        or marker.get("validation_group_request_sha256") != validation_group_id
        or set(marker.get("succeeded_request_sha256s", [])) != completed_request_ids
        or marker.get("stage1_plan_sha256") != source_plan_sha
    ):
        raise RestrictedRerunError("predecessor validation marker is not exact")
    ledger_path = _regular_file(predecessor_root / "state-ledger.jsonl", "predecessor ledger")
    ledger = validate_ledger(ledger_path)
    states = validate_request_state_machine(ledger)
    if (
        len(ledger) != 3 * len(completed_request_ids)
        or set(states) != completed_request_ids
        or set(states.values()) != {"SUCCEEDED"}
    ):
        raise RestrictedRerunError("predecessor validation ledger is not exactly four successes")

    artifact_root = (
        predecessor_root / "artifacts" / Path(str(group["reference_terminal_relpath"])).parent
    ).resolve(strict=True)
    artifact_files = _artifact_inventory(artifact_root)
    commits = _commit_bindings(artifact_root, group=group, units=completed_units)

    survivor_group_ids = set(source_plan["survivor_group_request_sha256s"])
    survivor_unit_ids = set(source_plan["survivor_lane_request_sha256s"])
    remaining_groups = [
        row
        for row in groups
        if row["group_request_sha256"] in survivor_group_ids
        and row["group_request_sha256"] != validation_group_id
    ]
    remaining_unit_ids = survivor_unit_ids - set(completed_unit_ids)
    remaining_units = [row for row in units if row["lane_request_sha256"] in remaining_unit_ids]
    remaining_actions = [row for row in actions if row["lane_request_sha256"] in remaining_unit_ids]
    if (
        len(remaining_groups) != 47
        or len(remaining_units) != 141
        or len(remaining_actions) != 423
        or {row["group_request_sha256"] for row in remaining_groups} | {validation_group_id}
        != survivor_group_ids
        or {row["lane_request_sha256"] for row in remaining_units} | set(completed_unit_ids)
        != survivor_unit_ids
        or any(set(row["lane_request_sha256s"]) - remaining_unit_ids for row in remaining_groups)
    ):
        raise RestrictedRerunError("remaining rows do not exactly partition Stage-1 survivors")
    if [int(row["group_sequence"]) for row in remaining_groups] != sorted(
        int(row["group_sequence"]) for row in remaining_groups
    ):
        raise RestrictedRerunError("remaining groups changed their original sequence order")

    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    _fsync_directory(destination.parent)
    exclusion_path = destination / "completed-validation-exclusion.json"
    exclusion = {
        "artifact_files": artifact_files,
        "completed_group": dict(group),
        "completed_group_commit": commits["group_commit"],
        "completed_group_count": 1,
        "completed_request_sha256s": sorted(completed_request_ids),
        "completed_unit_commits": commits["unit_commits"],
        "completed_units": [dict(row) for row in completed_units],
        "completed_unit_count": 3,
        "generated_outputs": 4,
        "ledger": _binding(ledger_path, row_count=len(ledger)),
        "model_calls": 4,
        "predecessor": predecessor,
        "predecessor_run_id": predecessor_run_id,
        "rerun_prohibited": True,
        "schema_version": 1,
        "scientific_outputs_retained": True,
        "source_stage1_plan_sha256": source_plan_sha,
        "status": EXCLUSION_STATUS,
        "validation_marker": predecessor["marker"],
    }
    write_json_exclusive(exclusion_path, exclusion)
    groups_path = destination / "remaining-prefix-groups.jsonl"
    units_path = destination / "remaining-units.jsonl"
    actions_path = destination / "remaining-action-map.jsonl"
    write_jsonl_exclusive(groups_path, remaining_groups)
    write_jsonl_exclusive(units_path, remaining_units)
    write_jsonl_exclusive(actions_path, remaining_actions)
    manifest_path = destination / "remaining-manifest.json"
    manifest = {
        "completed_exclusion": _binding(exclusion_path),
        "completed_group_request_sha256s": [validation_group_id],
        "completed_lane_request_sha256s": sorted(completed_unit_ids),
        "predecessor_run_id": predecessor_run_id,
        "remaining_action_map": _binding(actions_path, row_count=len(remaining_actions)),
        "remaining_group_count": len(remaining_groups),
        "remaining_lane_request_sha256s": sorted(remaining_unit_ids),
        "remaining_prefix_groups": _binding(groups_path, row_count=len(remaining_groups)),
        "remaining_unit_count": len(remaining_units),
        "remaining_units": _binding(units_path, row_count=len(remaining_units)),
        "schema_version": 1,
        "source_action_map_sha256": source_plan["action_map_sha256"],
        "source_folds_sha256": source_plan["folds_sha256"],
        "source_prefix_groups_sha256": source_plan["prefix_groups_sha256"],
        "source_queue_manifest_sha256": config.raw["source_run"]["queue"]["manifest"]["sha256"],
        "source_stage1_plan_sha256": source_plan_sha,
        "source_units_sha256": source_plan["units_sha256"],
        "status": PACKAGE_STATUS,
        "supplemental_authorized": False,
        "validation_rerun_authorized": False,
    }
    write_json_exclusive(manifest_path, manifest)
    return {
        "completed_exclusion_path": str(exclusion_path),
        "completed_exclusion_sha256": sha256_file(exclusion_path),
        "remaining_manifest_path": str(manifest_path),
        "remaining_manifest_sha256": sha256_file(manifest_path),
        "status": PACKAGE_STATUS,
    }


def validate_remaining_repair_package(
    manifest_path: Path,
    *,
    exclusion_path: Path,
    config: Any,
    bundle: Mapping[str, Any],
    source_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the survivor partition and return bound repair metadata."""

    manifest_source = _regular_file(manifest_path, "remaining manifest")
    exclusion_source = _regular_file(exclusion_path, "completed exclusion")
    manifest = load_json(manifest_source)
    exclusion = load_json(exclusion_source)
    expected_manifest_keys = {
        "completed_exclusion",
        "completed_group_request_sha256s",
        "completed_lane_request_sha256s",
        "predecessor_run_id",
        "remaining_action_map",
        "remaining_group_count",
        "remaining_lane_request_sha256s",
        "remaining_prefix_groups",
        "remaining_unit_count",
        "remaining_units",
        "schema_version",
        "source_action_map_sha256",
        "source_folds_sha256",
        "source_prefix_groups_sha256",
        "source_queue_manifest_sha256",
        "source_stage1_plan_sha256",
        "source_units_sha256",
        "status",
        "supplemental_authorized",
        "validation_rerun_authorized",
    }
    expected_exclusion_keys = {
        "artifact_files",
        "completed_group",
        "completed_group_commit",
        "completed_group_count",
        "completed_request_sha256s",
        "completed_unit_commits",
        "completed_unit_count",
        "completed_units",
        "generated_outputs",
        "ledger",
        "model_calls",
        "predecessor",
        "predecessor_run_id",
        "rerun_prohibited",
        "schema_version",
        "scientific_outputs_retained",
        "source_stage1_plan_sha256",
        "status",
        "validation_marker",
    }
    predecessor = exclusion.get("predecessor")
    if not isinstance(predecessor, dict):
        raise RestrictedRerunError("completed exclusion predecessor binding is absent")
    for field in ("claim", "manifest", "marker", "plan"):
        binding = predecessor.get(field)
        if not isinstance(binding, dict):
            raise RestrictedRerunError(f"completed predecessor binding is absent: {field}")
        path = _regular_file(Path(str(binding.get("path", ""))), f"predecessor {field}")
        if binding != _binding(path):
            raise RestrictedRerunError(f"completed predecessor binding drifted: {field}")
    predecessor_plan_path = Path(str(predecessor["plan"]["path"]))
    predecessor_plan = load_json(predecessor_plan_path)
    source_plan_sha = sha256_file(predecessor_plan_path)
    predecessor_root = Path(str(predecessor["manifest"]["path"])).parent
    validated_predecessor = _validate_predecessor_identity(
        predecessor_root,
        expected_run_id=str(manifest.get("predecessor_run_id", "")),
        config_sha256=config.source_sha256,
        plan_sha256=source_plan_sha,
    )
    if (
        set(manifest) != expected_manifest_keys
        or set(exclusion) != expected_exclusion_keys
        or not isinstance(manifest.get("completed_group_request_sha256s"), list)
        or not isinstance(manifest.get("completed_lane_request_sha256s"), list)
        or not isinstance(manifest.get("remaining_lane_request_sha256s"), list)
        or not isinstance(exclusion.get("artifact_files"), list)
        or not isinstance(exclusion.get("completed_request_sha256s"), list)
        or not isinstance(exclusion.get("completed_units"), list)
        or manifest.get("schema_version") != 1
        or manifest.get("status") != PACKAGE_STATUS
        or exclusion.get("schema_version") != 1
        or exclusion.get("status") != EXCLUSION_STATUS
        or manifest.get("completed_exclusion") != _binding(exclusion_source)
        or manifest.get("source_queue_manifest_sha256")
        != config.raw["source_run"]["queue"]["manifest"]["sha256"]
        or manifest.get("source_stage1_plan_sha256") != source_plan_sha
        or exclusion.get("source_stage1_plan_sha256") != source_plan_sha
        or predecessor_plan != dict(source_plan)
        or predecessor != validated_predecessor
        or manifest.get("predecessor_run_id") != exclusion.get("predecessor_run_id")
        or manifest.get("source_action_map_sha256") != source_plan["action_map_sha256"]
        or manifest.get("source_folds_sha256") != source_plan["folds_sha256"]
        or manifest.get("source_prefix_groups_sha256") != source_plan["prefix_groups_sha256"]
        or manifest.get("source_units_sha256") != source_plan["units_sha256"]
        or manifest.get("supplemental_authorized") is not False
        or manifest.get("validation_rerun_authorized") is not False
        or exclusion.get("rerun_prohibited") is not True
        or exclusion.get("scientific_outputs_retained") is not True
        or exclusion.get("completed_group_count") != 1
        or exclusion.get("completed_unit_count") != 3
        or exclusion.get("model_calls") != 4
        or exclusion.get("generated_outputs") != 4
    ):
        raise RestrictedRerunError("remaining repair package identity drifted")
    bound_rows: dict[str, list[dict[str, Any]]] = {}
    for field, expected_count in (
        ("remaining_prefix_groups", 47),
        ("remaining_units", 141),
        ("remaining_action_map", 423),
    ):
        binding = manifest.get(field)
        if not isinstance(binding, dict):
            raise RestrictedRerunError(f"remaining repair binding is absent: {field}")
        path = _regular_file(Path(str(binding.get("path", ""))), field)
        rows = load_jsonl(path)
        if binding != _binding(path, row_count=len(rows)) or len(rows) != expected_count:
            raise RestrictedRerunError(f"remaining repair rows drifted: {field}")
        bound_rows[field] = rows
    if manifest.get("remaining_group_count") != 47 or manifest.get("remaining_unit_count") != 141:
        raise RestrictedRerunError("remaining repair manifest counts drifted")
    completed_groups = set(manifest.get("completed_group_request_sha256s", []))
    completed_units = set(manifest.get("completed_lane_request_sha256s", []))
    remaining_groups = {
        str(row["group_request_sha256"]) for row in bound_rows["remaining_prefix_groups"]
    }
    remaining_units = {str(row["lane_request_sha256"]) for row in bound_rows["remaining_units"]}
    bundle_groups = {str(row["group_request_sha256"]): row for row in bundle["prefix_groups"]}
    bundle_units = {str(row["lane_request_sha256"]): row for row in bundle["units"]}
    try:
        completed_group_rows = [bundle_groups[value] for value in sorted(completed_groups)]
        completed_group = completed_group_rows[0]
        completed_unit_rows = [
            bundle_units[str(value)] for value in completed_group["lane_request_sha256s"]
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise RestrictedRerunError(
            "completed repair identities are absent from source queue"
        ) from exc
    if (
        len(completed_groups) != 1
        or len(completed_units) != 3
        or completed_groups & remaining_groups
        or completed_units & remaining_units
        or completed_groups | remaining_groups != set(source_plan["survivor_group_request_sha256s"])
        or completed_units | remaining_units != set(source_plan["survivor_lane_request_sha256s"])
        or manifest.get("remaining_lane_request_sha256s") != sorted(remaining_units)
        or canonical_json(exclusion.get("completed_group"))
        != canonical_json(completed_group_rows[0])
        or [canonical_json(row) for row in exclusion.get("completed_units", [])]
        != [canonical_json(row) for row in completed_unit_rows]
        or set(exclusion.get("completed_request_sha256s", [])) != completed_groups | completed_units
        or [canonical_json(row) for row in bound_rows["remaining_prefix_groups"]]
        != [
            canonical_json(row)
            for row in bundle["prefix_groups"]
            if row["group_request_sha256"] in remaining_groups
        ]
        or [canonical_json(row) for row in bound_rows["remaining_units"]]
        != [
            canonical_json(row)
            for row in bundle["units"]
            if row["lane_request_sha256"] in remaining_units
        ]
        or [canonical_json(row) for row in bound_rows["remaining_action_map"]]
        != [
            canonical_json(row)
            for row in bundle["action_map"]
            if row["lane_request_sha256"] in remaining_units
        ]
    ):
        raise RestrictedRerunError("remaining repair package does not exactly partition survivors")
    artifact_root = (
        predecessor_root
        / "artifacts"
        / Path(str(completed_group["reference_terminal_relpath"])).parent
    ).resolve(strict=True)
    artifact_files = exclusion.get("artifact_files")
    if not isinstance(artifact_files, list) or artifact_files != _artifact_inventory(artifact_root):
        raise RestrictedRerunError("completed validation artifact inventory drifted")
    for row in artifact_files:
        if not isinstance(row, dict):
            raise RestrictedRerunError("completed exclusion artifact binding is invalid")
        path = _regular_file(Path(str(row.get("path", ""))), "completed artifact")
        if sha256_file(path) != row.get("sha256") or path.stat().st_size != row.get("size_bytes"):
            raise RestrictedRerunError("completed validation artifact drifted")
    expected_commits = _commit_bindings(
        artifact_root,
        group=completed_group,
        units=completed_unit_rows,
    )
    if (
        exclusion.get("completed_group_commit") != expected_commits["group_commit"]
        or exclusion.get("completed_unit_commits") != expected_commits["unit_commits"]
    ):
        raise RestrictedRerunError("completed validation commit bindings drifted")
    marker_binding = exclusion.get("validation_marker")
    if not isinstance(marker_binding, dict) or marker_binding != predecessor["marker"]:
        raise RestrictedRerunError("completed validation marker binding drifted")
    marker = load_json(Path(str(marker_binding["path"])))
    completed_requests = completed_groups | completed_units
    if (
        marker.get("status") != "ONE_ROOT_VALIDATION_PASS"
        or marker.get("validation_group_request_sha256") != next(iter(completed_groups))
        or set(marker.get("succeeded_request_sha256s", [])) != completed_requests
        or marker.get("stage1_plan_sha256") != source_plan_sha
    ):
        raise RestrictedRerunError("completed validation marker evidence drifted")
    ledger_binding = exclusion.get("ledger")
    if not isinstance(ledger_binding, dict):
        raise RestrictedRerunError("completed exclusion ledger binding is absent")
    ledger_path = _regular_file(Path(str(ledger_binding.get("path", ""))), "completed ledger")
    ledger = validate_ledger(ledger_path)
    states = validate_request_state_machine(ledger)
    if (
        ledger_binding != _binding(ledger_path, row_count=len(ledger))
        or len(ledger) != 3 * len(completed_requests)
        or set(states) != completed_requests
        or set(states.values()) != {"SUCCEEDED"}
    ):
        raise RestrictedRerunError("completed exclusion success evidence drifted")
    return {
        "completed_exclusion_path": str(exclusion_source),
        "completed_exclusion_sha256": sha256_file(exclusion_source),
        "completed_group_request_sha256s": sorted(completed_groups),
        "completed_lane_request_sha256s": sorted(completed_units),
        "predecessor_run_id": manifest["predecessor_run_id"],
        "remaining_group_request_sha256s": sorted(remaining_groups),
        "remaining_lane_request_sha256s": sorted(remaining_units),
        "remaining_manifest_path": str(manifest_source),
        "remaining_manifest_sha256": sha256_file(manifest_source),
        "validation_marker": exclusion["validation_marker"],
    }


__all__ = [
    "EXCLUSION_STATUS",
    "PACKAGE_STATUS",
    "materialize_remaining_repair_package",
    "validate_remaining_repair_package",
]

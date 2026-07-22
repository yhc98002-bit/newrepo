"""CPU-only preparation and revalidation of the D-0036 ACE formal run."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_core.launcher import GitLaunchState, observe_clean_origin_main
from scoring.common import load_json, load_jsonl, sha256_file
from scoring.storage import write_json_exclusive, write_jsonl_exclusive
from state_capture.ace_formal_contract import (
    LANE_ID,
    MODEL_ID,
    RUN_ID,
    AceFormalConfig,
    AceFormalContractError,
    load_formal_config,
    load_source_bundle,
    package_hashes,
    survivor_bundle,
    verify_d0036,
)

PREPARED_STATUS = "PREPARED_D0036_SURVIVORS_ONLY_NO_MODEL_CALLS"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _binding(path: Path, row_count: int) -> dict[str, Any]:
    return {"path": str(path.resolve()), "row_count": row_count, "sha256": sha256_file(path)}


def prepare_formal_run(
    config_path: Path,
    *,
    decisions_path: Path,
    repo_root: Path,
    git_state: GitLaunchState | None = None,
) -> dict[str, Any]:
    """Materialize only Stage-1 survivors; never import ACE, probe CUDA, or claim work."""

    config = load_formal_config(config_path, repo_root=repo_root)
    observed_git = git_state or observe_clean_origin_main(repo_root)
    if observed_git.head != observed_git.origin_main:
        raise AceFormalContractError("ACE formal preparation requires clean origin/main")
    source = load_source_bundle(config)
    authorization = verify_d0036(config, decisions_path=decisions_path, bundle=source)
    filtered = survivor_bundle(source, authorization.stage1)
    run_dir = (config.run_root / RUN_ID).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    _fsync_directory(run_dir.parent)
    queue_dir = run_dir / "queues" / "initial-survivors"
    units_path = queue_dir / "initial-units.jsonl"
    groups_path = queue_dir / "prefix-groups.jsonl"
    actions_path = queue_dir / "replicated-action-map.jsonl"
    write_jsonl_exclusive(units_path, filtered["units"])
    write_jsonl_exclusive(groups_path, filtered["groups"])
    write_jsonl_exclusive(actions_path, filtered["actions"])
    queue_bindings = {
        "actions": _binding(actions_path, len(filtered["actions"])),
        "groups": _binding(groups_path, len(filtered["groups"])),
        "units": _binding(units_path, len(filtered["units"])),
    }
    queue_manifest = {
        "authorization_decision": "D-0036",
        "execution_started": False,
        "model_calls": 0,
        "schema_version": 1,
        "source_fresh_queue_manifest_sha256": config.raw["source_queue"]["manifest"]["sha256"],
        "source_initial_units_sha256": config.raw["source_queue"]["units"]["sha256"],
        "stage1_result_sha256": authorization.stage1.result_sha256,
        "stage1_summary_sha256": authorization.stage1.summary_sha256,
        "status": PREPARED_STATUS,
        "stopped_axes": list(authorization.stage1.stopped_axes),
        "supplemental_authorized": False,
        "survivor_axes": list(authorization.stage1.survivor_axes),
        **queue_bindings,
    }
    queue_manifest_path = queue_dir / "manifest.json"
    write_json_exclusive(queue_manifest_path, queue_manifest)
    launch_claim = {
        "authorization_status": "D0036_FORMAL_INITIAL_SURVIVORS_ONLY",
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "decision_block_sha256": authorization.decision_block_sha256,
        "decisions_path": str(authorization.decisions_path),
        "decisions_sha256": authorization.decisions_sha256,
        "engineering_governance_block_sha256": (
            authorization.engineering_governance_block_sha256
        ),
        "engineering_governance_decision_id": "D-0045",
        "engineering_repair_requires_new_claim": True,
        "engineering_repair_requires_new_run_id": True,
        "failed_attempts_immutable": True,
        "git_commit": observed_git.head,
        "git_origin_main": observed_git.origin_main,
        "lane_id": LANE_ID,
        "model_id": MODEL_ID,
        "no_automatic_retry": True,
        "package_sha256": package_hashes(config),
        "placement": {
            "gpu_ids": [4, 5, 6, 7],
            "node": "an12",
            "replica_count": 4,
            "tensor_parallel_width": 1,
        },
        "queue_manifest_path": str(queue_manifest_path),
        "queue_manifest_sha256": sha256_file(queue_manifest_path),
        "run_dir": str(run_dir),
        "run_id": RUN_ID,
        "schema_version": 1,
        "stage1": {
            "result_path": str(authorization.stage1.result_path),
            "result_sha256": authorization.stage1.result_sha256,
            "stopped_axes": list(authorization.stage1.stopped_axes),
            "summary_path": str(authorization.stage1.summary_path),
            "summary_sha256": authorization.stage1.summary_sha256,
            "survivor_axes": list(authorization.stage1.survivor_axes),
        },
        "stop_units_prohibited": ["EXECUTE", "SCORE"],
        "supplemental_authorized": False,
        "within_attempt_retry": False,
    }
    claim_path = run_dir / "control" / "formal-launch-claim.json"
    write_json_exclusive(claim_path, launch_claim)
    manifest = {
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "engineering_governance_block_sha256": (
            authorization.engineering_governance_block_sha256
        ),
        "formal_launch_claim_path": str(claim_path),
        "formal_launch_claim_sha256": sha256_file(claim_path),
        "git_commit": observed_git.head,
        "lane_id": LANE_ID,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "queue_manifest_path": str(queue_manifest_path),
        "queue_manifest_sha256": sha256_file(queue_manifest_path),
        "run_id": RUN_ID,
        "schema_version": 1,
        "status": PREPARED_STATUS,
    }
    manifest_path = run_dir / "run-manifest.json"
    write_json_exclusive(manifest_path, manifest)
    validate_formal_run(run_dir, config=config, git_state=observed_git)
    return {
        "run_dir": str(run_dir),
        "run_manifest_path": str(manifest_path),
        "run_manifest_sha256": sha256_file(manifest_path),
        "status": PREPARED_STATUS,
        "stopped_axes": list(authorization.stage1.stopped_axes),
        "survivor_axes": list(authorization.stage1.survivor_axes),
    }


def validate_formal_run(
    run_dir: Path,
    *,
    config: AceFormalConfig,
    git_state: GitLaunchState,
) -> dict[str, Any]:
    root = run_dir.resolve(strict=True)
    manifest = load_json(root / "run-manifest.json")
    if (
        manifest.get("status") != PREPARED_STATUS
        or manifest.get("run_id") != RUN_ID
        or manifest.get("config_sha256") != config.sha256
        or manifest.get("git_commit") != git_state.head
        or git_state.head != git_state.origin_main
    ):
        raise AceFormalContractError("formal run manifest/Git identity drifted")
    claim_path = Path(str(manifest.get("formal_launch_claim_path"))).resolve(strict=True)
    queue_manifest_path = Path(str(manifest.get("queue_manifest_path"))).resolve(strict=True)
    for path in (claim_path, queue_manifest_path):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AceFormalContractError("formal control artifact escapes run directory") from exc
    if sha256_file(claim_path) != manifest.get("formal_launch_claim_sha256") or sha256_file(
        queue_manifest_path
    ) != manifest.get("queue_manifest_sha256"):
        raise AceFormalContractError("formal launch/queue binding drifted")
    claim = load_json(claim_path)
    queue_manifest = load_json(queue_manifest_path)
    if (
        claim.get("authorization_status") != "D0036_FORMAL_INITIAL_SURVIVORS_ONLY"
        or claim.get("no_automatic_retry") is not True
        or claim.get("within_attempt_retry") is not False
        or claim.get("engineering_governance_decision_id") != "D-0045"
        or claim.get("engineering_repair_requires_new_run_id") is not True
        or claim.get("engineering_repair_requires_new_claim") is not True
        or claim.get("failed_attempts_immutable") is not True
        or claim.get("supplemental_authorized") is not False
        or claim.get("stop_units_prohibited") != ["EXECUTE", "SCORE"]
        or claim.get("package_sha256") != package_hashes(config)
        or queue_manifest.get("status") != PREPARED_STATUS
        or queue_manifest.get("execution_started") is not False
        or queue_manifest.get("model_calls") != 0
        or queue_manifest.get("supplemental_authorized") is not False
    ):
        raise AceFormalContractError("formal launch claim boundary drifted")
    bundle: dict[str, list[dict[str, Any]]] = {}
    for name in ("actions", "groups", "units"):
        record = queue_manifest.get(name)
        if not isinstance(record, dict):
            raise AceFormalContractError(f"formal survivor binding missing: {name}")
        path = Path(str(record.get("path"))).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise AceFormalContractError("formal survivor queue escapes run directory") from exc
        rows = load_jsonl(path)
        if sha256_file(path) != record.get("sha256") or len(rows) != record.get("row_count"):
            raise AceFormalContractError(f"formal survivor queue drifted: {name}")
        bundle[name] = rows
    survivors = tuple(claim["stage1"]["survivor_axes"])
    if tuple(queue_manifest.get("survivor_axes", [])) != survivors or any(
        row.get("axis") not in survivors for rows in bundle.values() for row in rows
    ):
        raise AceFormalContractError("STOP rows entered the formal survivor package")
    authorization = verify_d0036(
        config,
        decisions_path=Path(str(claim["decisions_path"])),
        bundle=load_source_bundle(config),
    )
    if (
        authorization.decision_block_sha256 != claim["decision_block_sha256"]
        or authorization.decisions_sha256 != claim["decisions_sha256"]
        or authorization.engineering_governance_block_sha256
        != claim["engineering_governance_block_sha256"]
        or manifest.get("engineering_governance_block_sha256")
        != claim["engineering_governance_block_sha256"]
        or authorization.stage1.result_sha256 != claim["stage1"]["result_sha256"]
        or authorization.stage1.summary_sha256 != claim["stage1"]["summary_sha256"]
    ):
        raise AceFormalContractError("live D-0036/Stage-1 bytes differ from launch claim")
    return {
        "authorization": authorization,
        "bundle": bundle,
        "claim": claim,
        "manifest": manifest,
        "queue_manifest": queue_manifest,
    }


__all__ = ["PREPARED_STATUS", "prepare_formal_run", "validate_formal_run"]

"""CPU-only preparation and authorization validation for the SA3 state lane."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_core.launcher import GitLaunchState, observe_clean_origin_main
from state_capture.sa3_contract import (
    EXPECTED_ACTION_ROWS,
    EXPECTED_GROUPS,
    EXPECTED_UNITS,
    INITIAL_TIER,
    LANE_ID,
    SA3_MODEL_ID,
    SA3StateCaptureConfig,
    build_sa3_state_capture_bundle,
    load_sa3_state_capture_bundle,
    load_sa3_state_capture_config,
    sha256_file,
    strict_json,
)

AUTHORIZATION_STATUS = "AUTHORIZED_SEPARATE_SA3_STATE_CAPTURE_INITIAL"
PREPARED_STATUS = "PREPARED_AUTHORIZED_NO_MODEL_CALLS"


class StateLaunchAuthorizationError(RuntimeError):
    """The immutable decision, queue, Git state, or launch claim is invalid."""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
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
        raise StateLaunchAuthorizationError(f"decision block is absent: {decision_id}")
    return match.group(0)


def verify_state_decision(
    decisions_path: Path,
    *,
    decision_id: str,
    config: SA3StateCaptureConfig,
) -> tuple[str, str]:
    """Require an explicit D-0030-style state-only opening with bound hashes."""

    text = decisions_path.resolve(strict=True).read_text(encoding="utf-8")
    block = _decision_block(text, decision_id)
    raw_cap = config.raw["execution"]["state_gpu_budget"]["initial_gpu_seconds_cap"]
    required_literals = (
        "SA3_STATE_CAPTURE_INITIAL_AUTHORIZED = YES",
        "NO_AUTOMATIC_RETRY = YES",
        "SA3_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED = NO",
        f"STATE_CONFIG = configs/{config.source_path.name}",
        f"STATE_CONFIG_SHA256 = {config.source_sha256}",
        f"INITIAL_STATE_GPU_SECONDS_CAP = {json.dumps(raw_cap, allow_nan=False)}",
        f"D0020_RESULT_SHA256 = {config.d0020_result_sha256}",
        "STATE_PLACEMENT = an12:[4,5,6,7]",
        "STATE_MAX_PARALLEL_REPLICAS = 4",
    )
    missing = [literal for literal in required_literals if literal not in block]
    if missing:
        raise StateLaunchAuthorizationError(
            f"state authorization decision lacks exact bindings: {missing}"
        )
    if re.search(r"\b(?:PLACEHOLDER|PENDING|TBD|ESTIMATE|UNSET)\b", block, re.IGNORECASE):
        raise StateLaunchAuthorizationError("state authorization decision contains unresolved text")
    return block, hashlib.sha256(block.encode()).hexdigest()


def _binding(record: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(record["path"])).resolve(strict=True)
    observed = sha256_file(path)
    if observed != record["sha256"]:
        raise StateLaunchAuthorizationError("queue artifact drifted before launch claim")
    return {
        "path": str(path),
        "row_count": record["row_count"],
        "sha256": observed,
    }


def prepare_state_run(
    config_path: Path,
    *,
    run_id: str,
    decisions_path: Path,
    decision_id: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Prepare the authorized queue and claim; never import a model or probe CUDA."""

    if not re.fullmatch(r"sa3-state-v2-[0-9a-z][0-9a-z.-]{0,95}", run_id):
        raise StateLaunchAuthorizationError("run_id must use the sa3-state-v2-* namespace")
    config = load_sa3_state_capture_config(config_path, repo_root=repo_root)
    git_state = observe_clean_origin_main(repo_root)
    block, block_sha = verify_state_decision(decisions_path, decision_id=decision_id, config=config)
    run_dir = (config.run_root / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    _fsync_directory(run_dir.parent)
    bundle = build_sa3_state_capture_bundle(
        config, run_dir / "queues" / "initial", git_commit=git_state.head
    )
    bindings = {
        name: _binding(bundle[name]) for name in ("units", "prefix_groups", "action_map", "folds")
    }
    claim = {
        "authorization_status": AUTHORIZATION_STATUS,
        "authorized_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config.source_path),
        "config_sha256": config.source_sha256,
        "decision_block_sha256": block_sha,
        "decision_id": decision_id,
        "decisions_path": str(decisions_path.resolve(strict=True)),
        "decisions_sha256": sha256_file(decisions_path.resolve(strict=True)),
        "git_commit": git_state.head,
        "git_origin_main": git_state.origin_main,
        "lane_id": LANE_ID,
        "manifest_path": bundle["manifest_path"],
        "manifest_sha256": bundle["manifest_sha256"],
        "model_id": SA3_MODEL_ID,
        "no_automatic_retry": True,
        "queue_bindings": bindings,
        "replica_contract": {
            "assignment": "STATIC_GROUP_SEQUENCE_MODULO_REPLICA_COUNT",
            "maximum_parallel_replicas": config.placement.maximum_parallel_replicas,
            "node": "an12",
            "replica_count_per_worker": 1,
            "shared_claims_and_ledger": True,
            "tp_width": 1,
        },
        "run_dir": str(run_dir),
        "run_id": run_id,
        "schema_version": 1,
        "state_gpu_budget": {
            "initial_gpu_seconds_cap": config.initial_gpu_seconds_cap,
            "prefix_group_reservation_seconds": config.prefix_group_reservation_seconds,
            "resume_unit_reservation_seconds": config.resume_unit_reservation_seconds,
        },
        "supplemental_authorized": False,
        "tier": INITIAL_TIER,
    }
    claim_path = run_dir / "control" / "state-launch-claim.json"
    _write_json_exclusive(claim_path, claim)
    manifest = {
        "authorization_status": AUTHORIZATION_STATUS,
        "config_path": str(config.source_path),
        "config_sha256": config.source_sha256,
        "git_commit": git_state.head,
        "lane_id": LANE_ID,
        "queue_manifest_path": bundle["manifest_path"],
        "queue_manifest_sha256": bundle["manifest_sha256"],
        "run_id": run_id,
        "schema_version": 1,
        "state_launch_claim_path": str(claim_path),
        "state_launch_claim_sha256": sha256_file(claim_path),
        "status": PREPARED_STATUS,
        "tier": INITIAL_TIER,
    }
    run_manifest_path = run_dir / "run-manifest.json"
    _write_json_exclusive(run_manifest_path, manifest)
    validate_state_run(run_dir, config=config, git_state=git_state)
    return {
        "run_dir": str(run_dir),
        "run_manifest_path": str(run_manifest_path),
        "run_manifest_sha256": sha256_file(run_manifest_path),
        "state_launch_claim_path": str(claim_path),
        "state_launch_claim_sha256": sha256_file(claim_path),
        "status": PREPARED_STATUS,
    }


def validate_state_run(
    run_dir: Path,
    *,
    config: SA3StateCaptureConfig,
    git_state: GitLaunchState,
) -> dict[str, Any]:
    root = run_dir.resolve(strict=True)
    manifest = strict_json(root / "run-manifest.json")
    if (
        manifest.get("status") != PREPARED_STATUS
        or manifest.get("authorization_status") != AUTHORIZATION_STATUS
        or manifest.get("config_sha256") != config.source_sha256
        or manifest.get("git_commit") != git_state.head
        or git_state.head != git_state.origin_main
    ):
        raise StateLaunchAuthorizationError("state run manifest/Git identity mismatch")
    claim_path = Path(str(manifest.get("state_launch_claim_path", ""))).resolve(strict=True)
    try:
        claim_path.relative_to(root)
    except ValueError as exc:
        raise StateLaunchAuthorizationError("state launch claim escapes run directory") from exc
    if sha256_file(claim_path) != manifest.get("state_launch_claim_sha256"):
        raise StateLaunchAuthorizationError("state launch claim hash mismatch")
    claim = strict_json(claim_path)
    expected = {
        "authorization_status": AUTHORIZATION_STATUS,
        "config_sha256": config.source_sha256,
        "git_commit": git_state.head,
        "git_origin_main": git_state.origin_main,
        "lane_id": LANE_ID,
        "model_id": SA3_MODEL_ID,
        "run_dir": str(root),
        "run_id": manifest.get("run_id"),
        "supplemental_authorized": False,
        "tier": INITIAL_TIER,
    }
    for key, value in expected.items():
        if claim.get(key) != value:
            raise StateLaunchAuthorizationError(f"state launch claim mismatch: {key}")
    if claim.get("no_automatic_retry") is not True:
        raise StateLaunchAuthorizationError("state launch claim permits retry")
    budget = claim.get("state_gpu_budget")
    expected_budget = {
        "initial_gpu_seconds_cap": config.initial_gpu_seconds_cap,
        "prefix_group_reservation_seconds": config.prefix_group_reservation_seconds,
        "resume_unit_reservation_seconds": config.resume_unit_reservation_seconds,
    }
    if budget != expected_budget:
        raise StateLaunchAuthorizationError("state launch claim budget drift")
    bundle_path = Path(str(claim.get("manifest_path", ""))).resolve(strict=True)
    try:
        bundle_path.relative_to(root)
    except ValueError as exc:
        raise StateLaunchAuthorizationError("state queue manifest escapes run directory") from exc
    if sha256_file(bundle_path) != claim.get("manifest_sha256"):
        raise StateLaunchAuthorizationError("state queue manifest hash mismatch")
    bundle = load_sa3_state_capture_bundle(bundle_path, config=config)
    expected_counts = {
        "units": EXPECTED_UNITS,
        "prefix_groups": EXPECTED_GROUPS,
        "action_map": EXPECTED_ACTION_ROWS,
        "folds": 36,
    }
    bindings = claim.get("queue_bindings")
    if not isinstance(bindings, dict):
        raise StateLaunchAuthorizationError("state queue bindings are absent")
    for name, count in expected_counts.items():
        binding = bindings.get(name)
        record = bundle["manifest"].get(name)
        if not isinstance(binding, dict) or not isinstance(record, dict):
            raise StateLaunchAuthorizationError(f"state queue binding absent: {name}")
        if binding.get("row_count") != count or binding.get("sha256") != record.get("sha256"):
            raise StateLaunchAuthorizationError(f"state queue binding drift: {name}")
    return {"bundle": bundle, "claim": claim, "manifest": manifest}


__all__ = [
    "AUTHORIZATION_STATUS",
    "PREPARED_STATUS",
    "StateLaunchAuthorizationError",
    "prepare_state_run",
    "validate_state_run",
    "verify_state_decision",
]

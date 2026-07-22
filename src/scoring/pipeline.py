"""Staged, immutable automatic-scoring orchestration."""

from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from rater.build_human_packet import validate_candidate_index
from scoring.common import load_json, sha256_file, sha256_json
from scoring.config import load_config
from scoring.endpoints import (
    build_candidate_index,
    evaluator_audit_table,
    normalize_feature_bundle,
)
from scoring.feature_worker import (
    PostLoadHeadroomBlocked,
    extract_axis_shard,
    merge_feature_shards,
    runtime_identity,
)
from scoring.gpu_guard import acquire_idle_gpu
from scoring.snapshot import build_completed_snapshot
from scoring.statistics import prevalence_table
from scoring.storage import ImmutableRun, write_json_exclusive

LAUNCH_ACK = "I_ACKNOWLEDGE_AUTOMATIC_SCORING_V2_LAUNCH_NO_GENERATION"


def _git(repo_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _git_identity(repo_root: Path, *, require_clean_main: bool) -> dict[str, Any]:
    head = _git(repo_root, "rev-parse", "HEAD")
    branch = _git(repo_root, "branch", "--show-current")
    dirty = _git(repo_root, "status", "--porcelain")
    origin_main = _git(repo_root, "rev-parse", "origin/main")
    if require_clean_main and (dirty or branch != "main" or head != origin_main):
        raise RuntimeError("scoring launch requires a clean local main equal to origin/main")
    return {
        "branch": branch,
        "clean": not bool(dirty),
        "git_commit": head,
        "origin_main": origin_main,
    }


def _decision_block(text: str, decision_id: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(decision_id)}\b.*?(?=^## D-\d+\b|\Z)",
        text,
    )
    if match is None:
        raise RuntimeError(f"required scoring-opening decision is absent: {decision_id}")
    return match.group(0)


def _verify_scoring_decision(
    config: dict[str, Any], config_path: Path, repo_root: Path
) -> dict[str, Any]:
    authorization = config["execution"]["authorization"]
    block = _decision_block(
        (repo_root / "DECISIONS.md").read_text(encoding="utf-8"),
        authorization["decision_id"],
    )
    for assignment in authorization["required_assignments"]:
        if f"`{assignment}`" not in block and assignment not in block:
            raise RuntimeError(f"scoring decision lacks required assignment: {assignment}")
    config_sha = sha256_file(config_path.resolve())
    config_assignment = f"AUTOMATIC_ENDPOINT_SCORING_CONFIG_SHA256 = {config_sha}"
    if config_assignment not in block:
        raise RuntimeError("scoring decision is not bound to the live config SHA-256")
    if re.search(r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE)\b", block, re.IGNORECASE):
        raise RuntimeError("scoring-opening decision contains an unresolved marker")
    return {
        "decision_block_sha256": sha256_json({"decision_block": block}),
        "decision_id": authorization["decision_id"],
        "live_config_sha256": config_sha,
    }


def _source_counts(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot["rows"]
    return {
        "axis_backbone_rows": {
            f"{backbone}|{axis}": count
            for (backbone, axis), count in sorted(
                Counter((row["backbone"], row["axis"]) for row in rows).items()
            )
        },
        "row_count": len(rows),
        "source_ledger_sha256": snapshot["source_ledger_sha256"],
        "sources": snapshot["sources"],
    }


def _primary_progress(
    config: dict[str, Any], snapshot: dict[str, Any]
) -> tuple[list[str], list[str]]:
    source_by_backbone = {source["backbone"]: source for source in config["sources"]}
    observed_by_backbone = {source["backbone"]: source for source in snapshot["sources"]}
    missing = [
        backbone for backbone in config["primary_backbones"] if backbone not in source_by_backbone
    ]
    incomplete: list[str] = []
    for backbone in config["primary_backbones"]:
        if backbone in missing:
            continue
        declared = source_by_backbone[backbone]
        observed = observed_by_backbone.get(backbone, {})
        if (
            declared["expected_completed_rows"] != declared["expected_queue_rows"]
            or observed.get("row_count") != declared["expected_queue_rows"]
        ):
            incomplete.append(backbone)
    return missing, incomplete


def dry_run(config_path: Path, repo_root: Path) -> dict[str, Any]:
    """Perform every read-only preclaim check without GPU probing or writes."""

    config = load_config(config_path, repo_root=repo_root)
    snapshot = build_completed_snapshot(config, repo_root, verify_audio_bytes=False)
    missing, incomplete = _primary_progress(config, snapshot)
    runtime = runtime_identity(config, require_interpreter=False)
    return {
        "candidate_index_path": config["output"]["candidate_index"],
        "execution_performed": False,
        "feature_binding_status": config["feature_contract"]["binding_status"],
        "gpu_probe_performed": False,
        "human_gold_claims": False,
        "missing_primary_backbones": missing,
        "incomplete_primary_backbones": incomplete,
        "planned_gpu_policy": config["gpu_guard"]["policy"],
        "runtime_identity": runtime,
        "schema_version": 1,
        "snapshot": _source_counts(snapshot),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "status": "DRY_RUN_PASS_NO_WRITES_NO_GPU_EXECUTION",
    }


def prepare_run(
    config_path: Path,
    repo_root: Path,
    *,
    launch_ack: str,
) -> dict[str, Any]:
    """Materialize the immutable snapshot/preclaim; score no endpoint."""

    if launch_ack != LAUNCH_ACK:
        raise RuntimeError("missing exact automatic-scoring launch acknowledgement")
    config = load_config(config_path, repo_root=repo_root)
    decision = _verify_scoring_decision(config, config_path, repo_root)
    git = _git_identity(repo_root, require_clean_main=True)
    runtime = runtime_identity(config, require_interpreter=True)
    snapshot = build_completed_snapshot(config, repo_root, verify_audio_bytes=False)
    run = ImmutableRun(Path(config["output"]["root"]), create=True)
    preclaim = {
        "authorization_scope": "AUTOMATIC_ENDPOINT_SCORING_ONLY_NO_AUDIO_GENERATION",
        "config_path": str(config_path.resolve()),
        "config_sha256": sha256_file(config_path.resolve()),
        "decision": decision,
        "git": git,
        "human_gold_claims": False,
        "runtime_identity": runtime,
        "schema_version": 1,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "status": "PREPARED_NO_ENDPOINTS_SCORED",
    }
    run.write_json("preclaim.json", preclaim)
    run.write_json("snapshot.json", snapshot)
    run.write_json(
        "run-manifest.json",
        {
            "axis_shards": config["execution"]["axis_shards"],
            "human_gold_claims": False,
            "placement": config["execution"]["placement"],
            "run_id": config["run_id"],
            "schema_version": 1,
            "source_snapshot": _source_counts(snapshot),
            "status": "PREPARED_NO_ENDPOINTS_SCORED",
        },
    )
    run.ledger.append("RUN_PREPARED", preclaim)
    heartbeat = run.heartbeat(
        "PREPARED_NO_ENDPOINTS_SCORED",
        {"completed_feature_shards": 0, "snapshot_sha256": snapshot["snapshot_sha256"]},
    )
    return {"heartbeat": heartbeat, "preclaim": preclaim}


def _load_snapshot(run: ImmutableRun) -> dict[str, Any]:
    snapshot = load_json(run.path("snapshot.json"))
    claimed = snapshot.pop("snapshot_sha256", None)
    if sha256_json(snapshot) != claimed:
        raise ValueError("stored completed-shard snapshot hash mismatch")
    snapshot["snapshot_sha256"] = claimed
    return snapshot


def extract_feature_shard(
    config_path: Path,
    repo_root: Path,
    *,
    axis: str,
    part_index: int,
) -> dict[str, Any]:
    """Run one no-clobber CPU or guarded-GPU feature shard."""

    config = load_config(config_path, repo_root=repo_root)
    _verify_scoring_decision(config, config_path, repo_root)
    run = ImmutableRun(Path(config["output"]["root"]), create=False)
    snapshot = _load_snapshot(run)
    part_count = int(config["execution"]["axis_shards"][axis])
    runtime_identity(config, require_interpreter=True)
    relative = f"feature-shards/{axis}/part-{part_index:03d}-of-{part_count:03d}.json"
    destination = run.path(relative)
    if destination.exists():
        raise FileExistsError(destination)
    requires_gpu = axis in {"vocal_instrumental", "tempo"}
    lease = None
    observation: dict[str, Any] | None = None
    if requires_gpu:
        lease, observation = acquire_idle_gpu(config["gpu_guard"])
        if lease is None:
            run.heartbeat(
                observation["status"],
                {"axis": axis, "part_count": part_count, "part_index": part_index},
            )
            return observation
        os.environ["CUDA_VISIBLE_DEVICES"] = str(observation["selected_gpu_id"])
    try:
        run.ledger.append(
            "FEATURE_SHARD_STARTED",
            {
                "axis": axis,
                "gpu_observation": observation,
                "part_count": part_count,
                "part_index": part_index,
            },
        )
        run.heartbeat(
            "FEATURE_SHARD_RUNNING",
            {"axis": axis, "part_count": part_count, "part_index": part_index},
        )
        try:
            shard = extract_axis_shard(
                snapshot,
                config,
                axis=axis,
                part_index=part_index,
                part_count=part_count,
            )
        except PostLoadHeadroomBlocked as exc:
            blocked = {
                "axis": axis,
                "free_vram_bytes_after_load": exc.free_bytes,
                "part_count": part_count,
                "part_index": part_index,
                "required_reserve_bytes": exc.required_bytes,
                "row_count": 0,
                "status": "QUEUED_PLACEMENT_HEADROOM_BLOCKED",
                "total_vram_bytes": exc.total_bytes,
            }
            run.ledger.append("FEATURE_SHARD_POST_LOAD_HEADROOM_BLOCKED", blocked)
            run.heartbeat("QUEUED_PLACEMENT_HEADROOM_BLOCKED", blocked)
            return blocked
        write_json_exclusive(destination, shard)
        event = run.ledger.append(
            "FEATURE_SHARD_COMPLETE",
            {
                "axis": axis,
                "artifact_path": str(destination),
                "artifact_sha256": sha256_file(destination),
                "part_count": part_count,
                "part_index": part_index,
                "row_count": shard["row_count"],
            },
        )
        run.heartbeat(
            "FEATURE_SHARD_COMPLETE",
            {"axis": axis, "part_count": part_count, "part_index": part_index},
        )
        return {"event": event, "shard": shard}
    finally:
        if lease is not None:
            lease.release()


def _feature_shards(run: ImmutableRun, axes: set[str]) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    for axis in sorted(axes):
        paths = sorted(run.path(f"feature-shards/{axis}").glob("part-*.json"))
        shards.extend(load_json(path) for path in paths)
    return shards


def _statistics_config(repo_root: Path) -> dict[str, Any]:
    return load_json(repo_root / "configs" / "statistics_v2.json")["bootstrap"]


def finalize_integrity_first(
    config_path: Path, repo_root: Path
) -> dict[str, Any]:
    """Emit the CPU-only first prevalence table before GPU axes finish."""

    config = load_config(config_path, repo_root=repo_root)
    _verify_scoring_decision(config, config_path, repo_root)
    run = ImmutableRun(Path(config["output"]["root"]), create=False)
    snapshot = _load_snapshot(run)
    bundle = merge_feature_shards(
        snapshot,
        _feature_shards(run, {"integrity"}),
        required_axes={"integrity"},
    )
    rows = normalize_feature_bundle(
        snapshot,
        bundle,
        expected_evaluator_identities=config["feature_contract"][
            "expected_evaluator_identities"
        ],
        voice_manifest_path=repo_root / "provenance" / "b1" / "voice_source_manifest.json",
        axes={"integrity"},
    )
    bootstrap = _statistics_config(repo_root)
    table = {
        "human_gold_claims": False,
        "rows": prevalence_table(
            rows,
            replicates=int(bootstrap["replicates"]),
            seed=int(bootstrap["seed"]),
            confidence_level=float(bootstrap["confidence_level"]),
            headline_only=True,
        ),
        "schema_version": 1,
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "status": "INTEGRITY_FIRST_PREVALENCE_COMPLETE_AUTOMATIC_DSP_ONLY",
    }
    path = run.write_json("tables/integrity-prevalence-first.json", table)
    run.ledger.append(
        "INTEGRITY_FIRST_TABLE_COMPLETE",
        {"path": str(path), "sha256": sha256_file(path)},
    )
    run.heartbeat(
        "INTEGRITY_FIRST_TABLE_COMPLETE",
        {"human_gold_claims": False, "table_path": str(path)},
    )
    return table


def finalize_all(config_path: Path, repo_root: Path) -> dict[str, Any]:
    """Merge all features, score endpoints, and write immutable final tables."""

    config = load_config(config_path, repo_root=repo_root)
    _verify_scoring_decision(config, config_path, repo_root)
    run = ImmutableRun(Path(config["output"]["root"]), create=False)
    snapshot = _load_snapshot(run)
    axes = {"vocal_instrumental", "tempo", "integrity"}
    shards = _feature_shards(run, axes)
    bundle = merge_feature_shards(snapshot, shards, required_axes=axes)
    rows = normalize_feature_bundle(
        snapshot,
        bundle,
        expected_evaluator_identities=config["feature_contract"][
            "expected_evaluator_identities"
        ],
        voice_manifest_path=repo_root / "provenance" / "b1" / "voice_source_manifest.json",
    )
    bootstrap = _statistics_config(repo_root)
    prevalence = prevalence_table(
        rows,
        replicates=int(bootstrap["replicates"]),
        seed=int(bootstrap["seed"]),
        confidence_level=float(bootstrap["confidence_level"]),
    )
    audits = evaluator_audit_table(rows)
    candidate = build_candidate_index(
        rows,
        config["primary_backbones"],
        snapshot["source_ledger_sha256"],
    )
    schema = load_json(repo_root / "rater" / "schema_v2.json")
    validate_candidate_index(candidate, schema)
    backbone_counts = Counter(row["backbone"] for row in rows)
    missing, incomplete = _primary_progress(config, snapshot)
    if missing:
        overall_status = "SCORING_COMPLETE_MISSING_PRIMARY_BACKBONE"
        candidate_status = "INCOMPLETE_FROZEN_PRIMARY_BACKBONE_STRATA"
    elif incomplete:
        overall_status = "SCORING_INCREMENTAL_PRIMARY_PREFIX"
        candidate_status = "INCOMPLETE_FROZEN_PRIMARY_BACKBONE_STRATA"
    else:
        overall_status = "SCORING_COMPLETE_ALL_PRIMARY_BACKBONES"
        candidate_status = "COMPLETE_FROZEN_PRIMARY_BACKBONE_STRATA"
    status = {
        "backbones": [
            {
                "backbone": backbone,
                "candidate_rows": sum(
                    row["backbone"] == backbone for row in candidate["rows"]
                ),
                "scored_rows": backbone_counts.get(backbone, 0),
                "status": (
                    "MISSING_BLOCKED_ON_LICENSE"
                    if backbone in missing
                    else (
                        "AUTOMATIC_ENDPOINTS_SCORED_PREFIX"
                        if backbone in incomplete
                        else "AUTOMATIC_ENDPOINTS_SCORED"
                    )
                ),
            }
            for backbone in config["primary_backbones"]
        ],
        "candidate_index_status": candidate_status,
        "human_gold_claims": False,
        "missing_primary_backbones": missing,
        "incomplete_primary_backbones": incomplete,
        "schema_version": 1,
        "source_ledger_sha256": snapshot["source_ledger_sha256"],
        "status": overall_status,
    }
    run.write_jsonl("rows/automatic-endpoint-outcomes.jsonl", rows)
    run.write_json(
        "tables/prevalence.json",
        {
            "human_gold_claims": False,
            "rows": prevalence,
            "schema_version": 1,
            "status": "AUTOMATIC_PREVALENCE_COMPLETE",
        },
    )
    run.write_json(
        "tables/evaluator-audit.json",
        {
            "accuracy_claim_authorized": False,
            "human_gold_claims": False,
            "rows": audits,
            "schema_version": 1,
            "status": "FRESH_OUTPUT_OPERATIONALIZATION_DISCORDANCE_ONLY",
        },
    )
    candidate_path = run.write_json("tables/human-audit-candidate-index.json", candidate)
    status_path = run.write_json("scoring-status.json", status)
    event = run.ledger.append(
        "AUTOMATIC_SCORING_FINALIZED",
        {
            "candidate_index_path": str(candidate_path),
            "candidate_index_sha256": sha256_file(candidate_path),
            "scoring_status_path": str(status_path),
            "scoring_status_sha256": sha256_file(status_path),
        },
    )
    run.heartbeat(
        overall_status,
        {
            "human_gold_claims": False,
            "missing_primary_backbones": missing,
            "incomplete_primary_backbones": incomplete,
        },
    )
    return {"candidate_index": candidate, "event": event, "scoring_status": status}

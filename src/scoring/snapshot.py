"""Create read-only snapshots from immutable completed core shard records."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from benchmark_core.heartbeat import validate_heartbeat
from benchmark_core.ledger import validate_ledger
from scoring.common import (
    load_json,
    load_jsonl,
    require_exact_keys,
    safe_child,
    sha256_file,
    sha256_json,
)

SHARD_KEYS = {
    "completed_at_utc",
    "first_batch",
    "heartbeat_snapshot",
    "ledger_tail_sha256",
    "model_id",
    "rows",
    "schema_version",
    "shard_index",
    "status",
}
QUEUE_KEYS = {
    "axis",
    "cluster_id",
    "condition",
    "duration_seconds",
    "model_id",
    "model_slug",
    "output_relpath",
    "prompt",
    "prompt_id",
    "request_sha256",
    "root_index",
    "seed",
    "sequence",
}
CONFIRMATORY_AXES = {"vocal_instrumental", "tempo", "integrity"}
ALL_AXES = CONFIRMATORY_AXES | {"structure_exploratory"}


def load_prompt_catalog(repo_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in (
        "vocal_instrumental.json",
        "tempo.json",
        "integrity.json",
        "structure_exploratory.json",
    ):
        document = load_json(repo_root / "prompts" / "v2" / name)
        rows = document.get("rows")
        if not isinstance(rows, list):
            raise ValueError(f"prompt file lacks rows: {name}")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("prompt_id"), str):
                raise ValueError(f"invalid prompt row in {name}")
            prompt_id = row["prompt_id"]
            if prompt_id in result:
                raise ValueError(f"duplicate prompt_id: {prompt_id}")
            result[prompt_id] = dict(row)
    return result


def _hash_matches(path: Path, expected: str, context: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"{context} hash mismatch: expected {expected}, got {observed}")


def _completed_shards(source: dict[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    worker_dir = run_dir / "workers" / source["worker_slug"]
    shard_dir = worker_dir / "shards"
    paths = sorted(shard_dir.glob("shard-*.json"))
    expected_count = int(source["expected_completed_shards"])
    if source["completion_mode"] == "INCREMENTAL_PREFIX":
        if len(paths) < expected_count:
            raise ValueError(
                f"{source['backbone']} completed shard prefix is shorter: "
                f"{len(paths)} < {expected_count}"
            )
        paths = paths[:expected_count]
    elif len(paths) != expected_count:
        raise ValueError(
            f"{source['backbone']} completed shard count differs: {len(paths)} != {expected_count}"
        )
    result: list[dict[str, Any]] = []
    for expected_index, path in enumerate(paths):
        if path.name != f"shard-{expected_index:06d}.json":
            raise ValueError("completed shard records are not a contiguous prefix")
        shard = require_exact_keys(load_json(path), SHARD_KEYS, f"shard {expected_index}")
        if shard["schema_version"] != 1 or shard["shard_index"] != expected_index:
            raise ValueError("completed shard identity is invalid")
        expected_status = "FIRST_LEDGERED_BATCH" if expected_index == 0 else "SHARD_COMPLETE"
        if shard["status"] != expected_status or shard["first_batch"] is (expected_index != 0):
            raise ValueError("completed shard status is invalid")
        if shard["model_id"] != source["model_id"]:
            raise ValueError("completed shard model_id mismatch")
        rows = shard["rows"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("completed shard must contain at least one row")
        for row in rows:
            if set(row) != {"request_sha256", "state"} or row["state"] != "SUCCEEDED":
                raise ValueError("only SUCCEEDED rows may enter a completed-shard snapshot")

        heartbeat_path = Path(shard["heartbeat_snapshot"]).resolve()
        expected_hb_root = (worker_dir / "heartbeat-snapshots").resolve()
        try:
            heartbeat_path.relative_to(expected_hb_root)
        except ValueError as exc:
            raise ValueError("shard heartbeat snapshot escapes its immutable directory") from exc
        raw = heartbeat_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if heartbeat_path.name != f"shard-{expected_index:06d}-{digest}.json":
            raise ValueError("heartbeat snapshot filename/content binding is invalid")
        heartbeat = validate_heartbeat(load_json(heartbeat_path))
        if (
            heartbeat["current_shard"] != expected_index
            or heartbeat["completed"] != sum(len(item["rows"]) for item in result) + len(rows)
            or heartbeat["failed"] != 0
            or heartbeat["last_ledger_sha256"] != shard["ledger_tail_sha256"]
        ):
            raise ValueError("completed shard heartbeat snapshot is inconsistent")
        result.append(shard)
    return result


def snapshot_source(
    source: dict[str, Any],
    prompt_catalog: dict[str, dict[str, Any]],
    *,
    verify_audio_bytes: bool = False,
) -> dict[str, Any]:
    """Validate one source and include exactly rows named by completed shards."""

    run_dir = Path(source["run_dir"]).resolve()
    expected = source["expected_hashes"]
    paths = {
        "run_manifest": run_dir / "run-manifest.json",
        "queue": run_dir / "queues" / "generation" / "queue.jsonl",
        "ledger": run_dir / "ledger.jsonl",
        "heartbeat": run_dir / "workers" / source["worker_slug"] / "heartbeat.json",
    }
    if source["completion_mode"] == "INCREMENTAL_PREFIX":
        for key in ("run_manifest", "queue"):
            _hash_matches(paths[key], expected[key], f"{source['backbone']} {key}")
    else:
        for key, path in paths.items():
            _hash_matches(path, expected[key], f"{source['backbone']} {key}")

    manifest = load_json(paths["run_manifest"])
    if manifest.get("run_id") != source["run_id"]:
        raise ValueError("source run manifest ID mismatch")
    queue = load_jsonl(paths["queue"])
    if len(queue) != source["expected_queue_rows"]:
        raise ValueError("source queue row count mismatch")
    queue_by_request: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(queue, start=1):
        require_exact_keys(row, QUEUE_KEYS, f"queue row {index}")
        if row["sequence"] != index or row["model_id"] != source["model_id"]:
            raise ValueError("source queue sequence/model binding is invalid")
        if row["axis"] not in ALL_AXES or row["prompt_id"] not in prompt_catalog:
            raise ValueError("source queue has an unregistered axis/prompt")
        if row["request_sha256"] in queue_by_request:
            raise ValueError("source queue request SHA is not unique")
        queue_by_request[row["request_sha256"]] = row

    ledger = validate_ledger(paths["ledger"])
    succeeded = {
        row["request_sha256"]: row
        for row in ledger
        if row.get("event_kind") == "REQUEST_STATE" and row.get("request_state") == "SUCCEEDED"
    }
    shards = _completed_shards(source, run_dir)
    if source["completion_mode"] == "INCREMENTAL_PREFIX":
        if not shards or shards[-1]["ledger_tail_sha256"] != expected["ledger_tail"]:
            raise ValueError("incremental source ledger tip differs from its completed shard")
    else:
        terminal = validate_heartbeat(load_json(paths["heartbeat"]))
        if (
            terminal["state"] != "COMPLETE"
            or terminal["completed"] < source["expected_completed_rows"]
            or terminal["failed"] != 0
            or terminal["last_ledger_sha256"] != expected["ledger_tail"]
        ):
            raise ValueError("source terminal heartbeat is not a clean completion")
    selected_requests = [row["request_sha256"] for shard in shards for row in shard["rows"]]
    if len(selected_requests) != source["expected_completed_rows"]:
        raise ValueError("completed shard row count differs from the declared completion")
    if len(set(selected_requests)) != len(selected_requests):
        raise ValueError("a request appears in more than one completed shard")

    rows: list[dict[str, Any]] = []
    for request_sha in selected_requests:
        if request_sha not in queue_by_request or request_sha not in succeeded:
            raise ValueError("completed shard request lacks queue or SUCCEEDED ledger record")
        queue_row = queue_by_request[request_sha]
        ledger_row = succeeded[request_sha]
        commit = ledger_row.get("commit")
        if not isinstance(commit, dict) or commit.get("request_sha256") != request_sha:
            raise ValueError("SUCCEEDED row lacks its committed artifact binding")
        if commit.get("output_relpath") != queue_row["output_relpath"]:
            raise ValueError("queue and committed output paths disagree")
        artifact_root = run_dir / "artifacts"
        audio_path = safe_child(artifact_root, queue_row["output_relpath"], "output_relpath")
        commit_path = audio_path.with_suffix(".commit.json")
        provenance_path = audio_path.with_suffix(".provenance.json")
        sanity_path = audio_path.with_suffix(".sanity.json")
        if load_json(commit_path) != commit:
            raise ValueError("retained commit sidecar differs from the ledger commit")
        _hash_matches(provenance_path, commit["provenance_sha256"], "provenance sidecar")
        _hash_matches(sanity_path, commit["sanity_sha256"], "sanity sidecar")
        if not audio_path.is_file():
            raise ValueError(f"retained audio is missing: {audio_path}")
        if verify_audio_bytes:
            _hash_matches(audio_path, commit["wav_sha256"], "retained audio")
        prompt_meta = prompt_catalog[queue_row["prompt_id"]]
        rows.append(
            {
                "audio_path": str(audio_path),
                "audio_sha256": commit["wav_sha256"],
                "axis": queue_row["axis"],
                "backbone": source["backbone"],
                "cluster_id": queue_row["cluster_id"],
                "condition": queue_row["condition"],
                "duration_seconds": queue_row["duration_seconds"],
                "model_id": queue_row["model_id"],
                "model_slug": queue_row["model_slug"],
                "prompt": queue_row["prompt"],
                "prompt_id": queue_row["prompt_id"],
                "prompt_metadata": prompt_meta,
                "request_sha256": request_sha,
                "root_index": queue_row["root_index"],
                "seed": queue_row["seed"],
                "source_run_id": source["run_id"],
            }
        )
    ledger_sha = (
        sha256_json(
            {
                "mode": "INCREMENTAL_PREFIX",
                "ledger_tail_sha256": expected["ledger_tail"],
                "selected_requests": selected_requests,
            }
        )
        if source["completion_mode"] == "INCREMENTAL_PREFIX"
        else expected["ledger"]
    )
    return {
        "backbone": source["backbone"],
        "completion_mode": source["completion_mode"],
        "completed_shards": len(shards),
        "ledger_sha256": ledger_sha,
        "ledger_tail_sha256": expected["ledger_tail"],
        "model_id": source["model_id"],
        "row_count": len(rows),
        "rows": rows,
        "run_id": source["run_id"],
        "source_status": "COMPLETED_SHARDS_SNAPSHOTTED",
    }


def build_completed_snapshot(
    config: dict[str, Any], repo_root: Path, *, verify_audio_bytes: bool = False
) -> dict[str, Any]:
    catalog = load_prompt_catalog(repo_root)
    sources = [
        snapshot_source(source, catalog, verify_audio_bytes=verify_audio_bytes)
        for source in config["sources"]
    ]
    rows = [row for source in sources for row in source.pop("rows")]
    ledger_identity = [
        {
            "backbone": source["backbone"],
            "ledger_sha256": source["ledger_sha256"],
            "ledger_tail_sha256": source["ledger_tail_sha256"],
            "run_id": source["run_id"],
        }
        for source in sources
    ]
    snapshot = {
        "audio_bytes_verified_at_snapshot": verify_audio_bytes,
        "inclusion_rule": "COMPLETED_SHARD_RECORDS_ONLY",
        "rows": rows,
        "schema_version": 1,
        "source_ledger_sha256": sha256_json({"source_ledgers": ledger_identity}),
        "sources": sources,
        "structure_endpoint_status": "EXPLORATORY_ONLY_NO_FROZEN_BINARY_THRESHOLD",
    }
    snapshot["snapshot_sha256"] = sha256_json(snapshot)
    return snapshot

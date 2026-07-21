from __future__ import annotations

import json
from pathlib import Path

from benchmark_core.heartbeat import snapshot_heartbeat, utc_now, write_heartbeat
from benchmark_core.ledger import HashChainedLedger
from scoring.common import canonical_json, sha256_file
from scoring.config import CANONICAL_CANDIDATE_INDEX, load_config
from scoring.snapshot import snapshot_source

ROOT = Path(__file__).resolve().parents[2]


def _heartbeat(run_id: str, completed: int, tail: str, state: str) -> dict[str, object]:
    return {
        "completed": completed,
        "config_sha256": "a" * 64,
        "cumulative_synchronized_gpu_seconds": 1.0,
        "current_request_sha256": None,
        "current_shard": 0,
        "failed": 0,
        "git_commit": "b" * 40,
        "last_ledger_sha256": tail,
        "logical_gpu_id": 0,
        "node": "an12",
        "peak_allocated_bytes": 1,
        "peak_reserved_bytes": 2,
        "physical_gpu_id": 4,
        "pid": 123,
        "prompt_manifest_sha256": "c" * 64,
        "run_id": run_id,
        "schema_version": 1,
        "state": state,
        "updated_at_utc": utc_now(),
    }


def _queue_row(request: str, sequence: int, output: str) -> dict[str, object]:
    return {
        "axis": "integrity",
        "cluster_id": "cluster",
        "condition": "BASE",
        "duration_seconds": 30.0,
        "model_id": "model-id",
        "model_slug": "model-slug",
        "output_relpath": output,
        "prompt": "prompt",
        "prompt_id": "prompt-id",
        "request_sha256": request,
        "root_index": sequence - 1,
        "seed": sequence,
        "sequence": sequence,
    }


def test_production_config_is_no_launch_and_candidate_path_is_canonical() -> None:
    config = load_config(ROOT / "configs" / "automatic_scoring_v2.json", repo_root=ROOT)
    assert config["status"] == "IMPLEMENTED_NOT_LAUNCHED"
    assert Path(config["output"]["candidate_index"]) == CANONICAL_CANDIDATE_INDEX
    assert config["execution"]["placement"]["node"] == "an12"
    assert config["execution"]["placement"]["maximum_parallel_gpu_workers"] == 4


def test_snapshot_includes_only_completed_shard_rows(tmp_path: Path) -> None:
    run = tmp_path / "run"
    worker = run / "workers" / "model-slug"
    artifacts = run / "artifacts" / "model-slug" / "integrity" / "prompt" / "base"
    artifacts.mkdir(parents=True)
    (run / "queues" / "generation").mkdir(parents=True)
    (worker / "shards").mkdir(parents=True)
    run_id = "fixture-run"
    (run / "run-manifest.json").write_text(
        json.dumps({"run_id": run_id}) + "\n", encoding="utf-8"
    )
    first_request = "1" * 64
    second_request = "2" * 64
    queue = [
        _queue_row(first_request, 1, "model-slug/integrity/prompt/base/root-00.wav"),
        _queue_row(second_request, 2, "model-slug/integrity/prompt/base/root-01.wav"),
    ]
    queue_path = run / "queues" / "generation" / "queue.jsonl"
    queue_path.write_text("".join(canonical_json(row) + "\n" for row in queue), encoding="utf-8")

    wav = artifacts / "root-00.wav"
    wav.write_bytes(b"fixture-wave")
    provenance = artifacts / "root-00.provenance.json"
    sanity = artifacts / "root-00.sanity.json"
    provenance.write_text('{"status":"PASS"}\n', encoding="utf-8")
    sanity.write_text('{"status":"PASS"}\n', encoding="utf-8")
    commit = {
        "output_relpath": queue[0]["output_relpath"],
        "provenance_sha256": sha256_file(provenance),
        "request_sha256": first_request,
        "sanity_sha256": sha256_file(sanity),
        "schema_version": 1,
        "state_artifact_count": 0,
        "status": "COMMITTED",
        "wav_sha256": sha256_file(wav),
    }
    (artifacts / "root-00.commit.json").write_text(
        json.dumps(commit, sort_keys=True) + "\n", encoding="utf-8"
    )

    ledger = HashChainedLedger(run / "ledger.jsonl")
    ledger.transition(first_request, "CLAIMED")
    ledger.transition(first_request, "CALL_STARTED")
    first_terminal = ledger.transition(first_request, "SUCCEEDED", {"commit": commit})
    running_path = worker / "heartbeat.json"
    write_heartbeat(
        running_path,
        _heartbeat(run_id, 1, first_terminal["ledger_row_sha256"], "RUNNING"),
    )
    snapshot_path = snapshot_heartbeat(running_path, worker / "heartbeat-snapshots", 0)
    shard = {
        "completed_at_utc": utc_now(),
        "first_batch": True,
        "heartbeat_snapshot": str(snapshot_path),
        "ledger_tail_sha256": first_terminal["ledger_row_sha256"],
        "model_id": "model-id",
        "rows": [{"request_sha256": first_request, "state": "SUCCEEDED"}],
        "schema_version": 1,
        "shard_index": 0,
        "status": "FIRST_LEDGERED_BATCH",
    }
    (worker / "shards" / "shard-000000.json").write_text(
        json.dumps(shard, sort_keys=True) + "\n", encoding="utf-8"
    )
    ledger.transition(second_request, "CLAIMED")
    ledger.transition(second_request, "CALL_STARTED")
    second_terminal = ledger.transition(second_request, "SUCCEEDED", {"commit": {}})
    write_heartbeat(
        running_path,
        _heartbeat(run_id, 2, second_terminal["ledger_row_sha256"], "COMPLETE"),
    )
    source = {
        "backbone": "stable-audio-3-medium-base",
        "completion_mode": "FULL",
        "expected_completed_rows": 1,
        "expected_completed_shards": 1,
        "expected_queue_rows": 2,
        "expected_hashes": {
            "heartbeat": sha256_file(running_path),
            "ledger": sha256_file(run / "ledger.jsonl"),
            "ledger_tail": second_terminal["ledger_row_sha256"],
            "queue": sha256_file(queue_path),
            "run_manifest": sha256_file(run / "run-manifest.json"),
        },
        "model_id": "model-id",
        "model_slug": "model-slug",
        "run_dir": str(run),
        "run_id": run_id,
        "worker_slug": "model-slug",
    }
    catalog = {
        "prompt-id": {
            "axis": "integrity",
            "profile": "soft_sustained",
            "prompt_id": "prompt-id",
        }
    }
    result = snapshot_source(source, catalog, verify_audio_bytes=True)
    assert result["row_count"] == 1
    assert [row["request_sha256"] for row in result["rows"]] == [first_request]

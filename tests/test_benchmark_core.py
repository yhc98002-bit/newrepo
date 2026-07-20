from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmark_core.heartbeat import SHA256_ZERO, utc_now, write_heartbeat
from benchmark_core.ledger import HashChainedLedger, validate_ledger
from benchmark_core.queue import build_queue, derive_seed, load_queue

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> Path:
    prompt_root = ROOT / "prompts" / "v2"
    hashes = {
        name: hashlib.sha256((prompt_root / name).read_bytes()).hexdigest()
        for name in (
            "vocal_instrumental.json",
            "tempo.json",
            "integrity.json",
            "structure_exploratory.json",
            "seed_registry.json",
        )
    }
    config = {
        "models": [
            {
                "model_id": "stabilityai/stable-audio-3-medium-base",
                "queue_status": "READY",
                "slug": "sa3-medium-base",
            },
            {
                "model_id": "stabilityai/stable-audio-open-1.0",
                "queue_status": "BLOCKED_ON_LICENSE",
                "slug": "stable-audio-open-1-0",
            },
        ],
        "prompt_root": str(prompt_root),
        "prompt_sha256": hashes,
        "schema_version": 2,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config) + "\n", encoding="utf-8")
    return path


def test_queue_has_exact_v2_rows_and_seed(tmp_path: Path) -> None:
    manifest = build_queue(_config(tmp_path), tmp_path / "queue")
    assert manifest["row_count"] == 1_536
    rows = load_queue(Path(manifest["queue_path"]))
    assert rows[0]["condition"] == "BASE"
    assert rows[0]["seed"] == 378480600
    assert rows[0]["output_relpath"].endswith("root-00.wav")
    diagnostic = [row for row in rows if row["condition"] == "NEGATION_DIAGNOSTIC"]
    assert len(diagnostic) == 96
    assert all("no singing" in row["prompt"] for row in diagnostic)


def test_queue_is_no_clobber_and_hash_checked(tmp_path: Path) -> None:
    config = _config(tmp_path)
    output = tmp_path / "queue"
    build_queue(config, output)
    with pytest.raises(FileExistsError):
        build_queue(config, output)
    queue = output / "queue.jsonl"
    lines = queue.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["seed"] += 1
    lines[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    queue.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row hash mismatch"):
        load_queue(queue)


def test_seed_derivation_rejects_unregistered_root() -> None:
    with pytest.raises(ValueError, match="0..7"):
        derive_seed("namespace", "model", "prompt", 8)


def test_hash_chained_ledger_and_atomic_heartbeat(tmp_path: Path) -> None:
    ledger = HashChainedLedger(tmp_path / "ledger.jsonl")
    first = ledger.append({"request_sha256": "a" * 64, "status": "PASS"})
    second = ledger.append({"request_sha256": "b" * 64, "status": "FAIL"})
    assert second["previous_row_sha256"] == first["ledger_row_sha256"]
    assert validate_ledger(ledger.path) == [first, second]
    heartbeat = tmp_path / "heartbeat.json"
    payload = {
        "completed": 1,
        "config_sha256": "a" * 64,
        "cumulative_synchronized_gpu_seconds": 1.0,
        "current_request_sha256": None,
        "current_shard": 0,
        "failed": 0,
        "git_commit": "b" * 40,
        "last_ledger_sha256": SHA256_ZERO,
        "logical_gpu_id": 0,
        "node": "an12",
        "peak_allocated_bytes": 1,
        "peak_reserved_bytes": 2,
        "physical_gpu_id": 3,
        "pid": 123,
        "prompt_manifest_sha256": "c" * 64,
        "run_id": "test-run",
        "schema_version": 1,
        "state": "RUNNING",
        "updated_at_utc": utc_now(),
    }
    write_heartbeat(heartbeat, payload)
    payload["completed"] = 2
    payload["updated_at_utc"] = utc_now()
    write_heartbeat(heartbeat, payload)
    assert json.loads(heartbeat.read_text(encoding="utf-8"))["completed"] == 2

#!/usr/bin/env python3
"""Build a no-clobber three-backbone scoring config from completed SAO shards."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from benchmark_core.config import (  # noqa: E402
    SAO_MODEL_ID,
    load_core_execution_config,
    sha256_file,
)
from benchmark_core.heartbeat import validate_heartbeat  # noqa: E402
from scoring.common import load_json  # noqa: E402
from scoring.snapshot import completed_shard_prefix_sha256  # noqa: E402

BASE_SCORING = ROOT / "configs" / "automatic_scoring_v2.json"
SCORING_ROOT = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "runs/scoring-v2"
)


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _completed_shard_tip(
    run_dir: Path, worker_slug: str, count: int
) -> tuple[list[Path], dict]:
    shard_dir = run_dir / "workers" / worker_slug / "shards"
    paths = sorted(shard_dir.glob("shard-*.json"))
    if not 1 <= count <= 384 or len(paths) < count:
        raise ValueError("requested SAO scoring prefix is not a completed 1..384 shard prefix")
    selected = paths[:count]
    for index, path in enumerate(selected):
        if path.name != f"shard-{index:06d}.json":
            raise ValueError("SAO completed shard prefix is not contiguous")
    tip = load_json(selected[-1])
    if tip.get("shard_index") != count - 1 or len(tip.get("rows", [])) != 4:
        raise ValueError("SAO completed shard tip identity is invalid")
    heartbeat_snapshot = Path(tip["heartbeat_snapshot"]).resolve()
    heartbeat = validate_heartbeat(load_json(heartbeat_snapshot))
    if (
        heartbeat["completed"] != count * 4
        or heartbeat["failed"] != 0
        or heartbeat["last_ledger_sha256"] != tip["ledger_tail_sha256"]
    ):
        raise ValueError("SAO completed shard tip heartbeat is inconsistent")
    return selected, tip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-config", type=Path, required=True)
    parser.add_argument("--core-run-dir", type=Path, required=True)
    parser.add_argument("--completed-shards", type=int, required=True)
    parser.add_argument("--scoring-decision-id", required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    args = parser.parse_args()
    if args.output_config.exists():
        raise FileExistsError(args.output_config)

    core = load_core_execution_config(args.core_config, repo_root=ROOT)
    sao_models = [model for model in core.models if model.model_id == SAO_MODEL_ID]
    if len(sao_models) != 1 or sao_models[0].sao_runtime is None:
        raise ValueError("core config lacks one verified SAO runtime binding")
    sao = sao_models[0]
    run_dir = args.core_run_dir.resolve()
    run_manifest_path = run_dir / "run-manifest.json"
    queue_path = run_dir / "queues" / "generation" / "queue.jsonl"
    run_manifest = load_json(run_manifest_path)
    if run_manifest.get("config_sha256") != sha256_file(args.core_config):
        raise ValueError("SAO core run/config identity mismatch")
    run_id = str(run_manifest["run_id"])
    selected_shards, tip = _completed_shard_tip(
        run_dir, sao.slug, args.completed_shards
    )
    scoring_run_id = (
        "automatic-scoring-v2-sao-final-001"
        if args.completed_shards == 384
        else f"automatic-scoring-v2-sao-{run_id}-shards-{args.completed_shards:03d}"
    )
    output_root = SCORING_ROOT / scoring_run_id

    value = copy.deepcopy(load_json(BASE_SCORING))
    value["schema_version"] = 2
    value["run_id"] = scoring_run_id
    value["execution"]["authorization"] = {
        "decision_id": args.scoring_decision_id,
        "exact_cli_ack_required": True,
        "requires_live_config_sha256": True,
        "required_assignments": [
            "SAO_AUTOMATIC_SCORING_AUTHORIZED = YES",
            f"AUTOMATIC_ENDPOINT_SCORING_RUN_ID = {scoring_run_id}",
            "AUDIO_GENERATION_AUTHORIZED_BY_SCORING = NO",
            "QUEUE_DO_NOT_PREEMPT = YES",
        ],
    }
    value["output"] = {
        "root": str(output_root),
        "candidate_index": str(output_root / "tables" / "human-audit-candidate-index.json"),
        "scoring_status": str(output_root / "scoring-status.json"),
    }
    complete = args.completed_shards == 384
    value["backbones"][1] = {
        "backbone": "stable-audio-open-1.0",
        "model_id": SAO_MODEL_ID,
        "source_mode": "INCREMENTAL_ADDITION" if complete else "INCREMENTAL_PREFIX",
        "status": "COMPLETED_SOURCE_READY" if complete else "INCREMENTAL_SOURCE_READY",
    }
    if complete:
        heartbeat_path = run_dir / "workers" / sao.slug / "heartbeat.json"
        ledger_path = run_dir / "ledger.jsonl"
        heartbeat = validate_heartbeat(load_json(heartbeat_path))
        if heartbeat["state"] != "COMPLETE" or heartbeat["completed"] != 1536:
            raise ValueError("384 SAO shards exist but the worker is not cleanly COMPLETE")
        expected_hashes = {
            "run_manifest": sha256_file(run_manifest_path),
            "queue": sha256_file(queue_path),
            "heartbeat": sha256_file(heartbeat_path),
            "ledger": sha256_file(ledger_path),
            "ledger_tail": tip["ledger_tail_sha256"],
        }
        completion_mode = "INCREMENTAL_ADDITION"
    else:
        expected_hashes = {
            "completed_shard_prefix": completed_shard_prefix_sha256(selected_shards),
            "run_manifest": sha256_file(run_manifest_path),
            "queue": sha256_file(queue_path),
            "ledger_tail": tip["ledger_tail_sha256"],
        }
        completion_mode = "INCREMENTAL_PREFIX"
    value["sources"].append(
        {
            "backbone": "stable-audio-open-1.0",
            "completion_mode": completion_mode,
            "expected_completed_rows": args.completed_shards * 4,
            "expected_completed_shards": args.completed_shards,
            "expected_queue_rows": 1536,
            "expected_hashes": expected_hashes,
            "model_id": SAO_MODEL_ID,
            "model_slug": sao.slug,
            "run_dir": str(run_dir),
            "run_id": run_id,
            "worker_slug": sao.slug,
        }
    )
    value["sao_gate"] = {
        "decision_id": "D-0037",
        "access_receipt_path": str(sao.sao_runtime.access_receipt_path),
        "access_receipt_sha256": sao.sao_runtime.access_receipt_sha256,
        "core_authorization_path": str(sao.sao_runtime.core_authorization_path),
        "core_authorization_sha256": sao.sao_runtime.core_authorization_sha256,
        "core_config_path": str(args.core_config.resolve()),
        "core_config_sha256": sha256_file(args.core_config),
        "state_capability": "NOT_ATTEMPTED",
        "eligibility_scope_expanded": False,
    }
    _write_json_exclusive(args.output_config, value)
    print(
        json.dumps(
            {
                "status": "SCORING_CONFIG_PREPARED_NO_ENDPOINTS_SCORED",
                "config_path": str(args.output_config.resolve()),
                "config_sha256": sha256_file(args.output_config),
                "completed_sao_shards": args.completed_shards,
                "completed_sao_rows": args.completed_shards * 4,
                "output_root": str(output_root),
                "audio_generated": 0,
            },
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

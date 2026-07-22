#!/usr/bin/env python3
"""Run one D-0036 ACE formal survivor shard on its assigned an12 TP1 GPU."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))


def _event(handle: object, value: dict[str, object]) -> None:
    handle.write(json.dumps(value, allow_nan=False, sort_keys=True) + "\n")  # type: ignore[attr-defined]
    handle.flush()  # type: ignore[attr-defined]
    os.fsync(handle.fileno())  # type: ignore[attr-defined]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--replica-index", type=int, required=True)
    parser.add_argument("--physical-gpu-id", type=int, required=True)
    parser.add_argument("--max-new-groups", type=int)
    args = parser.parse_args()
    hostname = socket.gethostname().split(".", 1)[0]
    if hostname != "an12":
        raise RuntimeError(f"ACE formal worker requires an12, observed {hostname}")
    if args.physical_gpu_id not in {4, 5, 6, 7}:
        raise RuntimeError("ACE formal worker refuses all GPUs except an12:4..7")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != str(args.physical_gpu_id):
        raise RuntimeError("CUDA_VISIBLE_DEVICES must name only the assigned physical GPU")

    from benchmark_core.launcher import observe_clean_origin_main
    from scoring.common import load_json
    from state_capture.ace_formal_contract import load_formal_config
    from state_capture.ace_formal_engine import ProductionAceFormalGroupEngine
    from state_capture.ace_formal_launcher import validate_formal_run
    from state_capture.ace_formal_worker import AceFormalWorker

    config = load_formal_config(args.config, repo_root=REPOSITORY)
    git_state = observe_clean_origin_main(REPOSITORY)
    run_dir = args.run_dir.resolve(strict=True)
    validated = validate_formal_run(run_dir, config=config, git_state=git_state)
    placement = validated["placement"]
    assignment = load_json(run_dir / "control" / "formal-supervisor-assignment.json")
    rows = assignment.get("assignments")
    if (
        assignment.get("config_sha256") != config.sha256
        or assignment.get("git_commit") != git_state.head
        or assignment.get("run_id") != validated["manifest"]["run_id"]
        or not isinstance(rows, list)
        or len(rows) != placement["replica_count"]
    ):
        raise RuntimeError("formal supervisor assignment binding drifted")
    assigned = {
        int(row["replica_index"]): int(row["physical_gpu_id"])
        for row in rows
        if isinstance(row, dict)
    }
    if (
        set(assigned) != set(range(placement["replica_count"]))
        or list(assigned.values()) != placement["physical_gpu_ids"]
    ):
        raise RuntimeError("formal supervisor assignment differs from exact attempt placement")
    if assigned.get(args.replica_index) != args.physical_gpu_id:
        raise RuntimeError("formal worker does not match its immutable GPU assignment")
    engine = ProductionAceFormalGroupEngine(config, run_dir=run_dir)
    worker = AceFormalWorker(
        config=config,
        authorization=validated["authorization"],
        run_dir=run_dir,
        run_id=validated["manifest"]["run_id"],
        git_commit=git_state.head,
        queue_manifest_sha256=validated["manifest"]["queue_manifest_sha256"],
        replica_index=args.replica_index,
        replica_count=placement["replica_count"],
        physical_gpu_id=args.physical_gpu_id,
        engine=engine,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_path = run_dir / "logs" / f"ace-formal-replica-{args.replica_index:02d}-{stamp}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        log_path.open("x", encoding="utf-8") as log,
        contextlib.redirect_stdout(log),
        contextlib.redirect_stderr(log),
    ):
        _event(
            log,
            {
                "event": "ACE_FORMAL_WORKER_STARTED",
                "physical_gpu_id": args.physical_gpu_id,
                "pid": os.getpid(),
                "replica_index": args.replica_index,
            },
        )
        try:
            result = worker.run(
                groups=validated["bundle"]["groups"],
                units=validated["bundle"]["units"],
                max_new_groups=args.max_new_groups,
            )
        except BaseException as exc:
            _event(
                log,
                {
                    "error_class": type(exc).__name__,
                    "error_message": str(exc)[:2000],
                    "event": "ACE_FORMAL_WORKER_FAILED_STOPPED",
                },
            )
            raise
        _event(log, {"event": "ACE_FORMAL_WORKER_TERMINAL", "result": result})
    print(json.dumps({"log_path": str(log_path), "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

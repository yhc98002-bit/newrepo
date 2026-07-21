#!/usr/bin/env python3
"""Run one supervisor-assigned, statically sharded SA3 initial-state worker."""

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
SOURCE_ROOT = REPOSITORY / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


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
        raise RuntimeError(f"SA3 state worker requires an12, observed {hostname}")
    if args.physical_gpu_id not in {4, 5, 6, 7}:
        raise RuntimeError("SA3 state worker refuses all GPUs except an12:4..7")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != str(args.physical_gpu_id):
        raise RuntimeError("CUDA_VISIBLE_DEVICES must name exactly the supervisor-assigned GPU")

    from benchmark_core.launcher import observe_clean_origin_main
    from state_capture.sa3_contract import load_sa3_state_capture_config
    from state_capture.sa3_engine import SA3StateEngine
    from state_capture.sa3_launcher import validate_state_run
    from state_capture.sa3_worker import SA3StateWorker

    config = load_sa3_state_capture_config(args.config, repo_root=REPOSITORY)
    git_state = observe_clean_origin_main(REPOSITORY)
    run_dir = args.run_dir.resolve(strict=True)
    validated = validate_state_run(run_dir, config=config, git_state=git_state)
    manifest = validated["manifest"]
    bundle = validated["bundle"]
    assignment_path = run_dir / "control" / "supervisor-assignment.json"
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
    if (
        assignment.get("schema_version") != 1
        or assignment.get("config_sha256") != config.source_sha256
        or assignment.get("git_commit") != git_state.head
        or assignment.get("run_id") != manifest["run_id"]
        or assignment.get("assignment_rule") != "FOUR_DISJOINT_REALTIME_IDLE_AN12_GPUS"
    ):
        raise RuntimeError("immutable supervisor assignment binding drift")
    assignment_rows = assignment.get("assignments")
    if not isinstance(assignment_rows, list) or len(assignment_rows) != 4:
        raise RuntimeError("immutable supervisor assignment must contain four rows")
    assigned = {
        int(row["replica_index"]): int(row["physical_gpu_id"])
        for row in assignment_rows
        if isinstance(row, dict)
    }
    if set(assigned) != set(range(4)) or set(assigned.values()) != set(
        config.placement.allowed_physical_gpu_ids
    ):
        raise RuntimeError("immutable supervisor assignment replica/GPU set drift")
    if assigned.get(args.replica_index) != args.physical_gpu_id:
        raise RuntimeError("worker GPU does not match immutable supervisor assignment")

    engine = SA3StateEngine(config, run_dir=run_dir)
    worker = SA3StateWorker(
        config=config,
        run_dir=run_dir,
        run_id=str(manifest["run_id"]),
        git_commit=git_state.head,
        bundle_manifest_sha256=str(manifest["queue_manifest_sha256"]),
        replica_index=args.replica_index,
        physical_gpu_id=args.physical_gpu_id,
        engine=engine,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_path = run_dir / "logs" / f"state-replica-{args.replica_index:02d}-{stamp}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        log_path.open("x", encoding="utf-8") as log,
        contextlib.redirect_stdout(log),
        contextlib.redirect_stderr(log),
    ):
        _event(
            log,
            {
                "event": "SA3_STATE_WORKER_STARTED",
                "physical_gpu_id": args.physical_gpu_id,
                "pid": os.getpid(),
                "replica_index": args.replica_index,
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            result = worker.run(
                units=bundle["units"],
                groups=bundle["prefix_groups"],
                max_new_groups=args.max_new_groups,
            )
        except BaseException as exc:
            _event(
                log,
                {
                    "error_message": str(exc)[:2000],
                    "error_type": type(exc).__name__,
                    "event": "SA3_STATE_WORKER_STOPPED_WITH_ERROR",
                    "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise
        _event(
            log,
            {
                "event": "SA3_STATE_WORKER_TERMINAL",
                "result": result,
                "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
    print(json.dumps({"log_path": str(log_path), "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

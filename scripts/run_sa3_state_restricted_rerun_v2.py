#!/usr/bin/env python3
"""Run one D-0035 SA3 validation or survivor-continuation shard on an12."""

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
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "sa3_state_restricted_rerun_v2.json",
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=("validation", "continuation"), required=True)
    parser.add_argument("--replica-index", type=int, required=True)
    parser.add_argument("--physical-gpu-id", type=int, required=True)
    parser.add_argument("--max-new-groups", type=int)
    args = parser.parse_args()
    if args.max_new_groups is not None and args.max_new_groups <= 0:
        parser.error("--max-new-groups must be positive")
    hostname = socket.gethostname().split(".", 1)[0]
    if hostname != "an12":
        raise RuntimeError(f"restricted SA3 state worker requires an12, observed {hostname}")
    if args.physical_gpu_id not in {4, 5, 6, 7}:
        raise RuntimeError("restricted SA3 state worker refuses GPUs outside an12:4..7")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != str(args.physical_gpu_id):
        raise RuntimeError("CUDA_VISIBLE_DEVICES must name exactly the selected physical GPU")

    from benchmark_core.launcher import observe_clean_origin_main
    from state_capture.sa3_contract import load_sa3_state_capture_bundle
    from state_capture.sa3_engine import SA3StateEngine
    from state_capture.sa3_restricted_rerun import (
        load_execution_scope,
        load_restricted_rerun_config,
        mark_validation_pass,
        validate_restricted_run,
    )
    from state_capture.sa3_worker import SA3StateWorker

    config = load_restricted_rerun_config(args.config, repo_root=REPOSITORY)
    git_state = observe_clean_origin_main(REPOSITORY)
    run_dir = args.run_dir.resolve(strict=True)
    validated = validate_restricted_run(run_dir, config=config, git_state=git_state)
    bundle = load_sa3_state_capture_bundle(config.queue_manifest_path, config=config.state_config)
    scope = load_execution_scope(run_dir, plan=validated["plan"], phase=args.phase)
    # Select before engine construction so a wrong phase/shard cannot load a model.
    scope.select(
        units=bundle["units"],
        groups=bundle["prefix_groups"],
        replica_index=args.replica_index,
        replica_count=config.state_config.placement.maximum_parallel_replicas,
    )

    engine = SA3StateEngine(config.state_config, run_dir=run_dir)
    worker = SA3StateWorker(
        config=config.state_config,
        run_dir=run_dir,
        run_id=config.run_id,
        git_commit=git_state.head,
        bundle_manifest_sha256=str(validated["manifest"]["queue_manifest_sha256"]),
        replica_index=args.replica_index,
        physical_gpu_id=args.physical_gpu_id,
        engine=engine,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    log_name = f"restricted-{args.phase}-replica-{args.replica_index:02d}-{stamp}.jsonl"
    log_path = run_dir / "logs" / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        log_path.open("x", encoding="utf-8") as log,
        contextlib.redirect_stdout(log),
        contextlib.redirect_stderr(log),
    ):
        _event(
            log,
            {
                "event": "SA3_RESTRICTED_STATE_WORKER_STARTED",
                "phase": args.phase,
                "physical_gpu_id": args.physical_gpu_id,
                "replica_index": args.replica_index,
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            result = worker.run(
                units=bundle["units"],
                groups=bundle["prefix_groups"],
                execution_scope=scope,
                max_new_groups=args.max_new_groups,
            )
            validation_marker = None
            if args.phase == "validation":
                validation_marker = mark_validation_pass(
                    run_dir,
                    validated["plan"],
                    bundle["prefix_groups"],
                )
        except BaseException as exc:
            _event(
                log,
                {
                    "error_message": str(exc)[:2000],
                    "error_type": type(exc).__name__,
                    "event": "SA3_RESTRICTED_STATE_WORKER_STOPPED_WITH_ERROR",
                    "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise
        _event(
            log,
            {
                "event": "SA3_RESTRICTED_STATE_WORKER_TERMINAL",
                "result": result,
                "validation_marker": validation_marker,
                "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
    print(json.dumps({"log_path": str(log_path), "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assign disjoint an12:4..7 TP1 workers and optionally launch ACE formal shards."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from scoring.storage import write_json_exclusive  # noqa: E402


def _launch_replica_indices(
    *, launch: bool, launch_all: bool, requested: list[int]
) -> tuple[int, ...]:
    if not launch:
        if launch_all or requested:
            raise ValueError("launch selectors require --launch")
        return ()
    if launch_all == bool(requested):
        raise ValueError("--launch requires exactly one selector mode")
    result = tuple(range(4)) if launch_all else tuple(sorted(requested))
    if len(result) != len(set(result)) or any(index not in range(4) for index in result):
        raise ValueError("formal replica selectors must be unique values in 0..3")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--assign", action="store_true")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--launch-all", action="store_true")
    parser.add_argument("--launch-replica", action="append", default=[], type=int)
    parser.add_argument("--max-new-groups", type=int)
    args = parser.parse_args()
    if args.launch and not args.assign:
        parser.error("--launch requires --assign")
    try:
        launch_indices = _launch_replica_indices(
            launch=args.launch,
            launch_all=args.launch_all,
            requested=args.launch_replica,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if socket.gethostname().split(".", 1)[0] != "an12":
        raise RuntimeError("ACE formal supervisor requires an12")

    from benchmark_core.config import PlacementConfig
    from benchmark_core.launcher import observe_clean_origin_main
    from benchmark_core.placement import DeviceLease, NvidiaSmiProbe
    from benchmark_core.supervisor import inspect_worker
    from scoring.common import load_json
    from state_capture.ace_formal_contract import load_formal_config
    from state_capture.ace_formal_launcher import validate_formal_run

    config = load_formal_config(args.config, repo_root=REPOSITORY)
    git_state = observe_clean_origin_main(REPOSITORY)
    run_dir = args.run_dir.resolve(strict=True)
    validate_formal_run(run_dir, config=config, git_state=git_state)
    if (run_dir / "control" / "formal-terminal-failure.json").exists():
        raise RuntimeError(
            "this ACE formal attempt is FAILED_STOPPED; engineering repair requires "
            "a new run ID and claim"
        )
    assignment_path = run_dir / "control" / "formal-supervisor-assignment.json"
    assignments: list[dict[str, int]] = []
    probes: list[dict[str, object]] = []
    if args.assign:
        if assignment_path.exists():
            assignment = load_json(assignment_path)
            if (
                assignment.get("config_sha256") != config.sha256
                or assignment.get("git_commit") != git_state.head
            ):
                raise RuntimeError("formal supervisor assignment binding drifted")
            assignments = list(assignment["assignments"])
        else:
            placement_raw = config.raw["placement"]
            for gpu_id in (4, 5, 6, 7):
                placement = PlacementConfig(
                    node="an12",
                    physical_gpu_id=gpu_id,
                    logical_gpu_id=0,
                    tp_width=1,
                    replica_count=1,
                    minimum_free_vram_bytes=int(placement_raw["minimum_free_vram_bytes"]),
                    post_load_reserve_bytes=int(placement_raw["post_load_reserve_bytes"]),
                    lock_root=Path(placement_raw["cooperative_lock_root"]),
                    required_gpu_name_substring=str(
                        placement_raw["required_gpu_name_substring"]
                    ),
                    maximum_idle_utilization_percent=int(
                        placement_raw["maximum_idle_utilization_percent"]
                    ),
                )
                environment = dict(os.environ)
                environment["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
                with DeviceLease(placement):
                    observation = NvidiaSmiProbe(placement, environ=environment).require_safe(
                        minimum_free_vram_bytes=placement.minimum_free_vram_bytes,
                        maximum_utilization_percent=placement.maximum_idle_utilization_percent,
                    )
                probes.append(
                    {
                        "free_vram_bytes": observation.free_vram_bytes,
                        "gpu_uuid": observation.gpu_uuid,
                        "physical_gpu_id": gpu_id,
                        "status": "IDLE_LOCK_PROBE_PASS",
                        "utilization_percent": observation.utilization_percent,
                    }
                )
            assignments = [
                {"physical_gpu_id": gpu_id, "replica_index": index}
                for index, gpu_id in enumerate((4, 5, 6, 7))
            ]
            write_json_exclusive(
                assignment_path,
                {
                    "assigned_at_utc": datetime.now(timezone.utc).isoformat(),
                    "assignment_rule": "FOUR_DISJOINT_IDLE_AN12_TP1_REPLICAS",
                    "assignments": assignments,
                    "config_sha256": config.sha256,
                    "git_commit": git_state.head,
                    "probes": probes,
                    "run_id": config.raw["run"]["run_id"],
                    "schema_version": 1,
                },
            )
    if assignments and (
        {row["replica_index"] for row in assignments} != set(range(4))
        or {row["physical_gpu_id"] for row in assignments} != {4, 5, 6, 7}
    ):
        raise RuntimeError("formal supervisor requires exact four-way disjoint assignment")
    launched: list[dict[str, object]] = []
    for row in assignments:
        replica = int(row["replica_index"])
        if replica not in launch_indices:
            continue
        heartbeat = run_dir / "workers" / f"replica-{replica:02d}" / "heartbeat.json"
        if heartbeat.exists():
            decision = inspect_worker(
                heartbeat, stale_after_seconds=config.heartbeat_stale_after_seconds
            )
            record = load_json(heartbeat)
            if decision.assignment_allowed or record.get("state") != "COMPLETE":
                raise RuntimeError(f"formal replica {replica} is not safely continuable")
        gpu_id = int(row["physical_gpu_id"])
        command = [
            sys.executable,
            str(REPOSITORY / "scripts" / "run_ace_state_formal_worker_v2.py"),
            "--config",
            str(args.config.resolve()),
            "--run-dir",
            str(run_dir),
            "--replica-index",
            str(replica),
            "--physical-gpu-id",
            str(gpu_id),
        ]
        if args.max_new_groups is not None:
            command.extend(["--max-new-groups", str(args.max_new_groups)])
        environment = dict(os.environ)
        environment["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        log_path = run_dir / "logs" / f"ace-formal-launcher-{replica:02d}-{stamp}.out"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        output = log_path.open("x", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        output.close()
        launched.append(
            {
                "launcher_log": str(log_path),
                "physical_gpu_id": gpu_id,
                "pid": process.pid,
                "replica_index": replica,
            }
        )
    print(
        json.dumps(
            {
                "assignment_path": str(assignment_path) if assignment_path.exists() else None,
                "assignments": assignments,
                "launched": launched,
                "probes": probes,
                "status": "LAUNCHED" if launched else "INSPECTED",
            },
            allow_nan=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

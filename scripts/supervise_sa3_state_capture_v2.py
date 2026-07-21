#!/usr/bin/env python3
"""Assign only idle an12:4..7 cards, inspect heartbeats, and optionally launch workers."""

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
SOURCE_ROOT = REPOSITORY / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def _write_exclusive(path: Path, value: dict) -> None:
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


def _validate_assignments(
    assignment: dict,
    *,
    allowed_gpu_ids: tuple[int, ...],
    config_sha256: str,
    git_commit: str,
    run_id: str,
) -> list[dict]:
    if (
        assignment.get("config_sha256") != config_sha256
        or assignment.get("git_commit") != git_commit
        or assignment.get("run_id") != run_id
    ):
        raise RuntimeError("immutable state supervisor assignment binding drift")
    rows = assignment.get("assignments")
    if not isinstance(rows, list) or len(rows) != 4:
        raise RuntimeError("state supervisor assignment must contain four rows")
    normalized = [
        {
            "physical_gpu_id": int(row["physical_gpu_id"]),
            "replica_index": int(row["replica_index"]),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    if len(normalized) != 4:
        raise RuntimeError("state supervisor assignment row is invalid")
    if {row["replica_index"] for row in normalized} != set(range(4)):
        raise RuntimeError("state supervisor replicas must be exactly 0..3")
    if {row["physical_gpu_id"] for row in normalized} != set(allowed_gpu_ids):
        raise RuntimeError("state supervisor GPUs must be exactly the frozen an12 set")
    return sorted(normalized, key=lambda row: row["replica_index"])


def _launch_replica_indices(
    *,
    launch: bool,
    launch_all: bool,
    requested: list[int],
    maximum_parallel_replicas: int,
) -> tuple[int, ...]:
    if not launch:
        if launch_all or requested:
            raise ValueError("launch selectors require --launch")
        return ()
    if launch_all == bool(requested):
        raise ValueError("--launch requires exactly one of --launch-all or --launch-replica")
    if launch_all:
        return tuple(range(maximum_parallel_replicas))
    if len(requested) != len(set(requested)):
        raise ValueError("--launch-replica values must be unique")
    if any(index not in range(maximum_parallel_replicas) for index in requested):
        raise ValueError("--launch-replica is outside the frozen replica range")
    return tuple(sorted(requested))


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
    if args.max_new_groups is not None and args.max_new_groups <= 0:
        parser.error("--max-new-groups must be positive")
    hostname = socket.gethostname().split(".", 1)[0]
    if hostname != "an12":
        raise RuntimeError(f"SA3 state supervisor requires an12, observed {hostname}")

    from benchmark_core.config import PlacementConfig
    from benchmark_core.launcher import observe_clean_origin_main
    from benchmark_core.placement import DeviceLease, NvidiaSmiProbe, PlacementBlocked
    from benchmark_core.supervisor import inspect_worker
    from state_capture.sa3_contract import load_sa3_state_capture_config
    from state_capture.sa3_launcher import validate_state_run

    config = load_sa3_state_capture_config(args.config, repo_root=REPOSITORY)
    try:
        launch_indices = _launch_replica_indices(
            launch=args.launch,
            launch_all=args.launch_all,
            requested=args.launch_replica,
            maximum_parallel_replicas=config.placement.maximum_parallel_replicas,
        )
    except ValueError as exc:
        parser.error(str(exc))
    git_state = observe_clean_origin_main(REPOSITORY)
    run_dir = args.run_dir.resolve(strict=True)
    validated = validate_state_run(run_dir, config=config, git_state=git_state)
    assignment_path = run_dir / "control" / "supervisor-assignment.json"
    assignments: list[dict] = []
    probes: list[dict] = []
    if args.assign:
        if assignment_path.exists():
            assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
            assignments = _validate_assignments(
                assignment,
                allowed_gpu_ids=config.placement.allowed_physical_gpu_ids,
                config_sha256=config.source_sha256,
                git_commit=git_state.head,
                run_id=str(validated["manifest"]["run_id"]),
            )
        else:
            for gpu_id in config.placement.allowed_physical_gpu_ids:
                placement = PlacementConfig(
                    node="an12",
                    physical_gpu_id=gpu_id,
                    logical_gpu_id=0,
                    tp_width=1,
                    replica_count=1,
                    minimum_free_vram_bytes=config.placement.minimum_free_vram_bytes,
                    post_load_reserve_bytes=config.placement.post_load_reserve_bytes,
                    lock_root=config.placement.shared_core_lock_root,
                    required_gpu_name_substring=config.placement.required_gpu_name_substring,
                    maximum_idle_utilization_percent=(
                        config.placement.maximum_idle_utilization_percent
                    ),
                )
                lease = DeviceLease(placement)
                environment = os.environ.copy()
                environment["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
                probe = NvidiaSmiProbe(placement, environ=environment)
                try:
                    with lease:
                        observed = probe.require_safe(
                            minimum_free_vram_bytes=placement.minimum_free_vram_bytes,
                            maximum_utilization_percent=(
                                placement.maximum_idle_utilization_percent
                            ),
                        )
                    probes.append(
                        {
                            "free_vram_bytes": observed.free_vram_bytes,
                            "gpu_uuid": observed.gpu_uuid,
                            "physical_gpu_id": gpu_id,
                            "status": "IDLE_LOCK_PROBE_PASS",
                            "utilization_percent": observed.utilization_percent,
                        }
                    )
                except PlacementBlocked as exc:
                    probes.append(
                        {
                            "physical_gpu_id": gpu_id,
                            "reason": str(exc),
                            "status": "WAIT_NOT_ASSIGNED",
                        }
                    )
            idle = [row for row in probes if row["status"] == "IDLE_LOCK_PROBE_PASS"]
            if len(idle) < config.placement.maximum_parallel_replicas:
                raise RuntimeError("fewer than four frozen an12 state GPUs are safely idle")
            assignments = [
                {
                    "physical_gpu_id": int(row["physical_gpu_id"]),
                    "replica_index": replica_index,
                }
                for replica_index, row in enumerate(idle[:4])
            ]
            _write_exclusive(
                assignment_path,
                {
                    "assigned_at_utc": datetime.now(timezone.utc).isoformat(),
                    "assignment_rule": "FOUR_DISJOINT_REALTIME_IDLE_AN12_GPUS",
                    "assignments": assignments,
                    "config_sha256": config.source_sha256,
                    "git_commit": git_state.head,
                    "probes": probes,
                    "run_id": validated["manifest"]["run_id"],
                    "schema_version": 1,
                },
            )

    launched: list[dict] = []
    if args.launch:
        selected_assignments = [
            row for row in assignments if int(row["replica_index"]) in launch_indices
        ]
        for row in selected_assignments:
            replica = int(row["replica_index"])
            gpu = int(row["physical_gpu_id"])
            heartbeat = run_dir / "workers" / f"replica-{replica:02d}" / "heartbeat.json"
            if heartbeat.exists():
                decision = inspect_worker(
                    heartbeat,
                    stale_after_seconds=config.heartbeat_stale_after_seconds,
                )
                if decision.assignment_allowed:
                    raise RuntimeError(f"replica {replica} already has an active heartbeat")
                heartbeat_record = json.loads(heartbeat.read_text(encoding="utf-8"))
                if heartbeat_record.get("state") != "COMPLETE":
                    raise RuntimeError(
                        f"replica {replica} is not safely relaunchable: {decision.reason}"
                    )
            command = [
                sys.executable,
                str(REPOSITORY / "scripts" / "run_sa3_state_capture_v2.py"),
                "--config",
                str(args.config.resolve()),
                "--run-dir",
                str(run_dir),
                "--replica-index",
                str(replica),
                "--physical-gpu-id",
                str(gpu),
            ]
            if args.max_new_groups is not None:
                command.extend(["--max-new-groups", str(args.max_new_groups)])
            environment = os.environ.copy()
            environment["CUDA_VISIBLE_DEVICES"] = str(gpu)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            launcher_log = run_dir / "logs" / f"state-replica-{replica:02d}-launcher-{stamp}.out"
            launcher_log.parent.mkdir(parents=True, exist_ok=True)
            output = launcher_log.open("x", encoding="utf-8")
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
                    "command": command,
                    "launcher_log": str(launcher_log),
                    "physical_gpu_id": gpu,
                    "pid": process.pid,
                    "replica_index": replica,
                }
            )

    heartbeat_status: list[dict] = []
    for replica in range(config.placement.maximum_parallel_replicas):
        path = run_dir / "workers" / f"replica-{replica:02d}" / "heartbeat.json"
        if not path.exists():
            heartbeat_status.append({"replica_index": replica, "status": "ABSENT"})
            continue
        decision = inspect_worker(path, stale_after_seconds=config.heartbeat_stale_after_seconds)
        heartbeat_status.append(
            {
                "assignment_allowed": decision.assignment_allowed,
                "decision": decision.status,
                "reason": decision.reason,
                "replica_index": replica,
                "status": "PRESENT",
            }
        )
    print(
        json.dumps(
            {
                "assignment_path": str(assignment_path) if assignment_path.exists() else None,
                "assignments": assignments,
                "heartbeats": heartbeat_status,
                "launch_replica_indices": list(launch_indices),
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

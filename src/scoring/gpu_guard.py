"""Queue-only idle-GPU allocator that never preempts neighboring work."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CommandRunner = Callable[[Sequence[str]], str]


def _runner(command: Sequence[str]) -> str:
    return subprocess.run(
        list(command), check=True, capture_output=True, text=True, timeout=15
    ).stdout


@dataclass(frozen=True)
class Observation:
    compute_pids: tuple[int, ...]
    free_vram_bytes: int
    gpu_name: str
    gpu_uuid: str
    node: str
    physical_gpu_id: int
    total_vram_bytes: int
    utilization_percent: int


class CooperativeLease:
    """Hold all generator-compatible locks plus a scoring-specific lock."""

    def __init__(self, node: str, gpu_id: int, guard: dict[str, Any]) -> None:
        self.node = node
        self.gpu_id = gpu_id
        generation_roots = [Path(value) for value in guard["generation_lock_roots"]]
        scoring_root = Path(guard["scoring_lock_root"])
        self.paths = [
            *(root / f"benchmark-{node}-gpu-{gpu_id}.lock" for root in generation_roots),
            scoring_root / f"automatic-scoring-{node}-gpu-{gpu_id}.lock",
        ]
        self._handles: list[Any] = []

    def acquire(self) -> CooperativeLease:
        if self._handles:
            raise RuntimeError("GPU lease is already held")
        try:
            for path in sorted(self.paths):
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    handle.close()
                    raise RuntimeError(
                        f"cooperative GPU lock is occupied: {path}"
                    ) from exc
                self._handles.append(handle)
            scoring = self._handles[-1]
            scoring.seek(0)
            scoring.truncate()
            json.dump(
                {
                    "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
                    "node": self.node,
                    "physical_gpu_id": self.gpu_id,
                    "pid": os.getpid(),
                    "policy": "QUEUE_DONT_PREEMPT",
                },
                scoring,
                allow_nan=False,
                sort_keys=True,
            )
            scoring.write("\n")
            scoring.flush()
            os.fsync(scoring.fileno())
        except BaseException:
            self.release()
            raise
        return self

    def release(self) -> None:
        for handle in reversed(self._handles):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        self._handles.clear()

    def __enter__(self) -> CooperativeLease:
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


def _probe(node: str, gpu_id: int, runner: CommandRunner) -> Observation:
    gpu = runner(
        (
            "nvidia-smi",
            f"--id={gpu_id}",
            "--query-gpu=index,uuid,name,memory.free,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        )
    )
    lines = [line.strip() for line in gpu.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("nvidia-smi did not return exactly one GPU")
    fields = [field.strip() for field in lines[0].split(",")]
    if len(fields) != 6 or int(fields[0]) != gpu_id:
        raise ValueError("nvidia-smi GPU identity mismatch")
    free = int(fields[3]) * 1024 * 1024
    total = int(fields[4]) * 1024 * 1024
    utilization = int(fields[5])
    if not 0 <= free <= total or not 0 <= utilization <= 100:
        raise ValueError("nvidia-smi returned invalid utilization/headroom")
    processes = runner(
        (
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        )
    )
    pids: set[int] = set()
    for line in processes.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2 and parts[0] == fields[1]:
            try:
                pids.add(int(parts[1]))
            except ValueError as exc:
                raise ValueError("nvidia-smi returned an invalid compute PID") from exc
    return Observation(
        compute_pids=tuple(sorted(pids)),
        free_vram_bytes=free,
        gpu_name=fields[2],
        gpu_uuid=fields[1],
        node=node,
        physical_gpu_id=gpu_id,
        total_vram_bytes=total,
        utilization_percent=utilization,
    )


def inspect_idle_gpus(
    guard: dict[str, Any],
    *,
    runner: CommandRunner = _runner,
    hostname: str | None = None,
) -> dict[str, Any]:
    """Return an allocation decision; never signal, kill, or modify a process."""

    node = (hostname or socket.gethostname()).split(".", 1)[0]
    if guard.get("policy") != "QUEUE_DONT_PREEMPT":
        raise ValueError("GPU guard policy must be QUEUE_DONT_PREEMPT")
    candidate_rows = [row for row in guard["candidates"] if row["node"] == node]
    if not candidate_rows:
        return {
            "node": node,
            "observations": [],
            "policy": "QUEUE_DONT_PREEMPT",
            "selected_gpu_id": None,
            "status": "QUEUED_WRONG_NODE",
        }
    candidates = sorted({gpu for row in candidate_rows for gpu in row["physical_gpu_ids"]})
    excluded = {
        (row["node"], row["physical_gpu_id"]): row["allocation_id"]
        for row in guard["excluded_generation_allocations"]
    }
    observations: list[dict[str, Any]] = []
    selected: int | None = None
    for gpu_id in candidates:
        exclusion = excluded.get((node, gpu_id))
        if exclusion is not None:
            observations.append(
                {
                    "physical_gpu_id": gpu_id,
                    "reason": f"EXCLUDED_GENERATION_ALLOCATION:{exclusion}",
                    "safe": False,
                }
            )
            continue
        observed = _probe(node, gpu_id, runner)
        reason: str | None = None
        if guard["required_gpu_name_substring"] not in observed.gpu_name:
            reason = "GPU_IDENTITY_MISMATCH"
        elif observed.compute_pids:
            reason = "COMPUTE_NEIGHBORS_PRESENT"
        elif observed.free_vram_bytes < guard["minimum_free_vram_bytes"]:
            reason = "INSUFFICIENT_FREE_VRAM"
        elif observed.utilization_percent > guard["maximum_idle_utilization_percent"]:
            reason = "GPU_NOT_IDLE"
        observations.append({**asdict(observed), "reason": reason, "safe": reason is None})
        if reason is None and selected is None:
            selected = gpu_id
    return {
        "node": node,
        "observations": observations,
        "policy": "QUEUE_DONT_PREEMPT",
        "selected_gpu_id": selected,
        "status": "IDLE_GPU_AVAILABLE" if selected is not None else "QUEUED_WAITING_FOR_IDLE_GPU",
    }


def acquire_idle_gpu(
    guard: dict[str, Any],
    *,
    runner: CommandRunner = _runner,
    hostname: str | None = None,
) -> tuple[CooperativeLease | None, dict[str, Any]]:
    """Acquire, then recheck, a safe device or return a queue decision."""

    first = inspect_idle_gpus(guard, runner=runner, hostname=hostname)
    safe_ids = [
        row["physical_gpu_id"] for row in first["observations"] if row.get("safe") is True
    ]
    if not safe_ids:
        return None, first
    node = first["node"]
    lock_failures: list[str] = []
    for selected in safe_ids:
        lease = CooperativeLease(node, selected, guard)
        try:
            lease.acquire()
        except RuntimeError as exc:
            lock_failures.append(str(exc))
            continue
        observed = _probe(node, selected, runner)
        safe_after_lock = (
            guard["required_gpu_name_substring"] in observed.gpu_name
            and not observed.compute_pids
            and observed.free_vram_bytes >= guard["minimum_free_vram_bytes"]
            and observed.utilization_percent <= guard["maximum_idle_utilization_percent"]
        )
        if not safe_after_lock:
            lease.release()
            continue
        return lease, {
            **first,
            "post_lock_observation": asdict(observed),
            "selected_gpu_id": selected,
            "status": "IDLE_GPU_LEASED",
        }
    return None, {
        **first,
        "lock_failures": lock_failures,
        "selected_gpu_id": None,
        "status": "QUEUED_WAITING_FOR_COOPERATIVE_LOCK_OR_IDLE_HEADROOM",
    }

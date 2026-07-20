"""Read-only GPU/neighbor preflight plus cooperative per-device locking."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from benchmark_core.config import PlacementConfig


class PlacementBlocked(RuntimeError):
    """A safe device is unavailable; existing processes must remain untouched."""


class PlacementUnavailable(PlacementBlocked):
    """A transient lock, neighbor, utilization, or headroom condition."""


class PlacementConfigurationError(PlacementBlocked):
    """A permanent node/device mapping or identity error."""


CommandRunner = Callable[[Sequence[str]], str]


def _default_runner(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return completed.stdout


@dataclass(frozen=True)
class GpuObservation:
    node: str
    physical_gpu_id: int
    logical_gpu_id: int
    gpu_uuid: str
    gpu_name: str
    free_vram_bytes: int
    total_vram_bytes: int
    utilization_percent: int
    compute_pids: tuple[int, ...]


class DeviceLease:
    """Advisory exclusive lock retained for the complete worker lifetime."""

    def __init__(self, config: PlacementConfig) -> None:
        self.config = config
        self.path = config.lock_root / f"benchmark-{config.node}-gpu-{config.physical_gpu_id}.lock"
        self._handle: Any | None = None

    def acquire(self) -> DeviceLease:
        if self._handle is not None:
            raise RuntimeError("device lease is already held by this worker")
        self.config.lock_root.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise PlacementUnavailable(f"cooperative GPU lock is occupied: {self.path}") from exc
        handle.seek(0)
        handle.truncate()
        json.dump(
            {
                "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
                "node": self.config.node,
                "physical_gpu_id": self.config.physical_gpu_id,
                "pid": os.getpid(),
            },
            handle,
            allow_nan=False,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        directory = os.open(self.config.lock_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None

    def __enter__(self) -> DeviceLease:
        return self if self._handle is not None else self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


class NvidiaSmiProbe:
    """Observe one GPU without signaling, killing, or reconfiguring any process."""

    def __init__(
        self,
        placement: PlacementConfig,
        *,
        runner: CommandRunner = _default_runner,
        hostname: str | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.placement = placement
        self.runner = runner
        self.hostname = (hostname or socket.gethostname()).split(".", 1)[0]
        self.environ = dict(os.environ if environ is None else environ)

    def _verify_mapping(self) -> None:
        if self.hostname != self.placement.node:
            raise PlacementConfigurationError(
                f"worker is on {self.hostname}, expected {self.placement.node}"
            )
        visible = self.environ.get("CUDA_VISIBLE_DEVICES")
        if visible != str(self.placement.physical_gpu_id):
            raise PlacementConfigurationError(
                "CUDA_VISIBLE_DEVICES must name exactly the configured physical GPU"
            )

    @staticmethod
    def _parse_gpu_line(output: str, expected_index: int) -> tuple[str, str, int, int, int]:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) != 1:
            raise PlacementConfigurationError("nvidia-smi did not return exactly one GPU")
        fields = [field.strip() for field in lines[0].split(",")]
        if len(fields) != 6 or int(fields[0]) != expected_index:
            raise PlacementConfigurationError("nvidia-smi GPU identity mismatch")
        free_bytes = int(fields[3]) * 1024 * 1024
        total_bytes = int(fields[4]) * 1024 * 1024
        utilization = int(fields[5])
        if not 0 <= free_bytes <= total_bytes:
            raise PlacementConfigurationError("nvidia-smi returned invalid memory values")
        if not 0 <= utilization <= 100:
            raise PlacementConfigurationError("nvidia-smi returned invalid GPU utilization")
        return fields[1], fields[2], free_bytes, total_bytes, utilization

    @staticmethod
    def _compute_pids(output: str, gpu_uuid: str) -> tuple[int, ...]:
        pids: set[int] = set()
        for line in output.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) >= 2 and fields[0] == gpu_uuid:
                try:
                    pids.add(int(fields[1]))
                except ValueError as exc:
                    raise PlacementConfigurationError(
                        "nvidia-smi returned an invalid compute PID"
                    ) from exc
        return tuple(sorted(pids))

    def observe(self) -> GpuObservation:
        self._verify_mapping()
        index = self.placement.physical_gpu_id
        gpu_output = self.runner(
            (
                "nvidia-smi",
                f"--id={index}",
                "--query-gpu=index,uuid,name,memory.free,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            )
        )
        gpu_uuid, gpu_name, free_bytes, total_bytes, utilization = self._parse_gpu_line(
            gpu_output, index
        )
        process_output = self.runner(
            (
                "nvidia-smi",
                "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            )
        )
        return GpuObservation(
            node=self.hostname,
            physical_gpu_id=index,
            logical_gpu_id=self.placement.logical_gpu_id,
            gpu_uuid=gpu_uuid,
            gpu_name=gpu_name,
            free_vram_bytes=free_bytes,
            total_vram_bytes=total_bytes,
            utilization_percent=utilization,
            compute_pids=self._compute_pids(process_output, gpu_uuid),
        )

    def require_safe(
        self,
        *,
        minimum_free_vram_bytes: int,
        allowed_pids: Iterable[int] = (),
        maximum_utilization_percent: int | None = None,
    ) -> GpuObservation:
        observation = self.observe()
        if self.placement.required_gpu_name_substring not in observation.gpu_name:
            raise PlacementConfigurationError(
                f"GPU name {observation.gpu_name!r} does not contain required "
                f"{self.placement.required_gpu_name_substring!r}"
            )
        allowed = set(allowed_pids)
        neighbors = [pid for pid in observation.compute_pids if pid not in allowed]
        if neighbors:
            raise PlacementUnavailable(
                f"GPU {observation.physical_gpu_id} has compute neighbors "
                f"{neighbors}; no action taken"
            )
        if observation.free_vram_bytes < minimum_free_vram_bytes:
            raise PlacementUnavailable(
                f"GPU free memory {observation.free_vram_bytes} is below "
                f"required {minimum_free_vram_bytes}; no action taken"
            )
        if (
            maximum_utilization_percent is not None
            and observation.utilization_percent > maximum_utilization_percent
        ):
            raise PlacementUnavailable(
                f"GPU utilization {observation.utilization_percent}% exceeds idle threshold "
                f"{maximum_utilization_percent}%; no action taken"
            )
        return observation

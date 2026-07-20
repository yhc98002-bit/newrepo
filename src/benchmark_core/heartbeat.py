"""Schema-checked heartbeat loop with atomic refresh and immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEARTBEAT_STATES = frozenset(
    {
        "QUEUED_WAITING_FOR_SAFE_GPU",
        "LOADING",
        "RUNNING",
        "PLACEMENT_HEADROOM_BLOCKED",
        "HARD_CAP_REACHED",
        "FAILED_STOPPED",
        "COMPLETE",
    }
)
SHA256_ZERO = "0" * 64


class HeartbeatStaleError(RuntimeError):
    """The durable liveness record is absent, invalid, or too old for another claim."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: Any, *, length: int, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"heartbeat {name} is not a lowercase {length}-hex identity")
    return value


def _nonnegative_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"heartbeat {key} must be a non-negative integer")
    return value


def validate_heartbeat(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete liveness schema and return a detached copy."""

    result = dict(payload)
    required = {
        "schema_version",
        "run_id",
        "node",
        "physical_gpu_id",
        "logical_gpu_id",
        "pid",
        "git_commit",
        "config_sha256",
        "prompt_manifest_sha256",
        "current_shard",
        "current_request_sha256",
        "completed",
        "failed",
        "cumulative_synchronized_gpu_seconds",
        "peak_allocated_bytes",
        "peak_reserved_bytes",
        "last_ledger_sha256",
        "state",
        "updated_at_utc",
    }
    if set(result) != required:
        missing = sorted(required - set(result))
        extra = sorted(set(result) - required)
        raise ValueError(f"heartbeat schema mismatch; missing={missing}, extra={extra}")
    if result["schema_version"] != 1:
        raise ValueError("heartbeat schema_version must equal one")
    if not isinstance(result["run_id"], str) or not result["run_id"]:
        raise ValueError("heartbeat run_id must be non-empty")
    if result["node"] not in {"an12", "an29"}:
        raise ValueError("heartbeat node must be an12 or an29")
    physical = _nonnegative_int(result, "physical_gpu_id")
    if physical > 7 or result["logical_gpu_id"] != 0:
        raise ValueError("heartbeat GPU mapping must be physical 0..7 to logical zero")
    if _nonnegative_int(result, "pid") <= 0:
        raise ValueError("heartbeat pid must be positive")
    _sha(result["git_commit"], length=40, name="git_commit")
    _sha(result["config_sha256"], length=64, name="config_sha256")
    _sha(result["prompt_manifest_sha256"], length=64, name="prompt_manifest_sha256")
    shard = result["current_shard"]
    if shard is not None and (isinstance(shard, bool) or not isinstance(shard, int) or shard < 0):
        raise ValueError("heartbeat current_shard must be null or non-negative")
    request = result["current_request_sha256"]
    if request is not None:
        _sha(request, length=64, name="current_request_sha256")
    _nonnegative_int(result, "completed")
    _nonnegative_int(result, "failed")
    seconds = result["cumulative_synchronized_gpu_seconds"]
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError("heartbeat cumulative GPU seconds must be numeric")
    if not math.isfinite(float(seconds)) or float(seconds) < 0:
        raise ValueError("heartbeat cumulative GPU seconds must be finite and non-negative")
    _nonnegative_int(result, "peak_allocated_bytes")
    _nonnegative_int(result, "peak_reserved_bytes")
    _sha(result["last_ledger_sha256"], length=64, name="last_ledger_sha256")
    if result["state"] not in HEARTBEAT_STATES:
        raise ValueError("heartbeat state is not recognized")
    try:
        timestamp = datetime.fromisoformat(result["updated_at_utc"])
    except (TypeError, ValueError) as exc:
        raise ValueError("heartbeat timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError("heartbeat timestamp must carry UTC timezone")
    json.dumps(result, allow_nan=False, sort_keys=True)
    return result


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_heartbeat(path: Path, payload: Mapping[str, Any]) -> None:
    """Validate and atomically replace only the designated mutable heartbeat."""

    value = validate_heartbeat(payload)
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex}"
    )
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def snapshot_heartbeat(path: Path, snapshot_dir: Path, shard_index: int) -> Path:
    """Retain the exact heartbeat bytes under a content-hashed no-clobber name."""

    if isinstance(shard_index, bool) or not isinstance(shard_index, int) or shard_index < 0:
        raise ValueError("shard_index must be non-negative")
    raw = path.read_bytes()
    value = json.loads(raw)
    validate_heartbeat(value)
    digest = hashlib.sha256(raw).hexdigest()
    destination_dir = snapshot_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"shard-{shard_index:06d}-{digest}.json"
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(destination_dir)
    return destination


def heartbeat_is_stale(
    path: Path, stale_after_seconds: float, *, now: datetime | None = None
) -> bool:
    """Return whether a validated heartbeat exceeds the configured stale age."""

    if not math.isfinite(stale_after_seconds) or stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be finite and positive")
    value = validate_heartbeat(json.loads(path.read_text(encoding="utf-8")))
    updated = datetime.fromisoformat(value["updated_at_utc"])
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (observed_now - updated).total_seconds() > stale_after_seconds


class HeartbeatLoop:
    """Refresh a complete heartbeat during loading and calls in a daemon thread."""

    def __init__(self, path: Path, payload: Mapping[str, Any], interval_seconds: float) -> None:
        if not math.isfinite(interval_seconds) or not 0 < interval_seconds <= 60:
            raise ValueError("heartbeat interval must be in (0,60]")
        self.path = path
        self.interval_seconds = float(interval_seconds)
        self._payload = validate_heartbeat(payload)
        self._payload_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def _write_current(self) -> None:
        with self._write_lock:
            with self._payload_lock:
                value = dict(self._payload)
                value["updated_at_utc"] = utc_now()
                self._payload = value
            write_heartbeat(self.path, value)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._write_current()
                if self._stop.wait(self.interval_seconds):
                    break
        except BaseException as exc:  # pragma: no cover - exercised via raise_if_failed
            self._failure = exc
            self._stop.set()

    def start(self) -> HeartbeatLoop:
        if self._thread is not None:
            raise RuntimeError("heartbeat loop was already started")
        self._thread = threading.Thread(target=self._run, name="benchmark-heartbeat", daemon=True)
        self._thread.start()
        return self

    def update(self, **changes: Any) -> None:
        with self._payload_lock:
            candidate = dict(self._payload)
            candidate.update(changes)
            candidate["updated_at_utc"] = utc_now()
            self._payload = validate_heartbeat(candidate)
        self.raise_if_failed()

    def flush(self) -> None:
        self.raise_if_failed()
        self._write_current()
        self.raise_if_failed()

    def require_current(self, stale_after_seconds: float) -> dict[str, Any]:
        """Fail before assignment if the last durable heartbeat is not current."""

        self.raise_if_failed()
        if not self.path.is_file():
            raise HeartbeatStaleError("heartbeat is absent before request assignment")
        try:
            payload = validate_heartbeat(json.loads(self.path.read_text(encoding="utf-8")))
            stale = heartbeat_is_stale(self.path, stale_after_seconds)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HeartbeatStaleError("heartbeat is invalid before request assignment") from exc
        if stale:
            raise HeartbeatStaleError("heartbeat is stale before request assignment")
        return payload

    def snapshot(self, snapshot_dir: Path, shard_index: int) -> Path:
        self.flush()
        return snapshot_heartbeat(self.path, snapshot_dir, shard_index)

    def raise_if_failed(self) -> None:
        if self._failure is not None:
            raise RuntimeError("heartbeat writer failed") from self._failure

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(60.0, self.interval_seconds + 1.0))
            if self._thread.is_alive():
                raise RuntimeError("heartbeat thread did not stop")
        self.raise_if_failed()

    def __enter__(self) -> HeartbeatLoop:
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()

"""Durable no-retry claims and conservative GPU-time reservations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_core.queue import canonical_json


class AlreadyClaimed(RuntimeError):
    """The request has already crossed the no-retry boundary."""


class HardCapReached(RuntimeError):
    """A new reservation would exceed the frozen worker cap."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


class CallClaimStore:
    """One model worker's append-only load/call reservation store.

    Claim files are never updated or removed. Their O_EXCL creation is the
    durable boundary after which an automatic retry is forbidden, even if the
    process exits before a ledger transition can be appended.
    """

    def __init__(
        self,
        root: Path,
        *,
        model_id: str,
        gpu_seconds_cap: float,
        scheduled_calls: int,
        cold_plus_first_seconds: float,
        resident_unit_seconds: float,
    ) -> None:
        if not model_id:
            raise ValueError("model_id must be non-empty")
        if not math.isfinite(gpu_seconds_cap) or gpu_seconds_cap <= 0:
            raise ValueError("gpu_seconds_cap must be finite and positive")
        if not 1 <= scheduled_calls <= 1_536:
            raise ValueError("scheduled_calls must be in 1..1536")
        if (
            not math.isfinite(cold_plus_first_seconds)
            or not math.isfinite(resident_unit_seconds)
            or resident_unit_seconds <= 0
            or cold_plus_first_seconds < resident_unit_seconds
        ):
            raise ValueError("cold/first and resident-unit measurements are invalid")
        expected_cap = cold_plus_first_seconds + max(scheduled_calls - 1, 0) * (
            2 * resident_unit_seconds
        )
        if not math.isclose(gpu_seconds_cap, expected_cap, rel_tol=0, abs_tol=1e-9):
            raise ValueError("GPU cap does not equal the frozen c_m + (n_m-1)*2u_m formula")
        self.root = root.resolve()
        self.claims_dir = self.root / "request-claims"
        self.observations_dir = self.root / "observed-gpu-seconds"
        self.root.mkdir(parents=True, exist_ok=True)
        self.claims_dir.mkdir(exist_ok=True)
        self.observations_dir.mkdir(exist_ok=True)
        self.lock_path = self.root / "reservation.lock"
        self.lock_path.touch(exist_ok=True)
        self.model_id = model_id
        self.gpu_seconds_cap = float(gpu_seconds_cap)
        self.scheduled_calls = scheduled_calls
        self.cold_plus_first_seconds = float(cold_plus_first_seconds)
        self.resident_unit_seconds = float(resident_unit_seconds)
        self.load_reservation_seconds = self.cold_plus_first_seconds - self.resident_unit_seconds

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self.lock_path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"reservation is not an object: {path}")
        seconds = value.get("reserved_gpu_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError(f"reservation lacks numeric seconds: {path}")
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError(f"reservation seconds are invalid: {path}")
        if value.get("kind") == "REQUEST_CALL" and seconds <= 0:
            raise ValueError(f"request reservation must be positive: {path}")
        value["reserved_gpu_seconds"] = seconds
        return value

    def _records_locked(self) -> list[dict[str, Any]]:
        paths = list(self.claims_dir.glob("*.json"))
        load = self.root / "load-reservation.json"
        if load.exists():
            paths.append(load)
        return [self._read_record(path) for path in sorted(paths)]

    @staticmethod
    def _read_observation(path: Path) -> float:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"GPU observation is not an object: {path}")
        seconds = value.get("observed_gpu_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError(f"GPU observation lacks numeric seconds: {path}")
        result = float(seconds)
        if not math.isfinite(result) or result < 0:
            raise ValueError(f"GPU observation seconds are invalid: {path}")
        return result

    def _effective_seconds_locked(self, records: list[dict[str, Any]]) -> float:
        total = 0.0
        for record in records:
            reservation = float(record["reserved_gpu_seconds"])
            if record.get("kind") == "MODEL_LOAD":
                observation_path = self.observations_dir / "model-load.json"
            else:
                observation_path = self.observations_dir / f"{record['request_sha256']}.json"
            observed = (
                self._read_observation(observation_path) if observation_path.is_file() else 0.0
            )
            total += max(reservation, observed)
        return total

    def usage(self) -> dict[str, float | int]:
        with self._locked():
            records = self._records_locked()
            calls = sum(record.get("kind") == "REQUEST_CALL" for record in records)
            return {
                "claimed_calls": calls,
                "effective_gpu_seconds": self._effective_seconds_locked(records),
                "reserved_gpu_seconds": sum(record["reserved_gpu_seconds"] for record in records),
                "gpu_seconds_cap": self.gpu_seconds_cap,
            }

    def reserve_load(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        """Reserve cold-load occupancy once, before model loading begins."""

        seconds = self.load_reservation_seconds
        path = self.root / "load-reservation.json"
        with self._locked():
            if path.exists():
                raise AlreadyClaimed("model load has already been reserved")
            used = sum(row["reserved_gpu_seconds"] for row in self._records_locked())
            if used + seconds > self.gpu_seconds_cap + 1e-9:
                raise HardCapReached("model load reservation would exceed GPU-time cap")
            record = {
                "claimed_at_utc": _utc_now(),
                "kind": "MODEL_LOAD",
                "metadata": dict(metadata),
                "model_id": self.model_id,
                "reserved_gpu_seconds": seconds,
                "schema_version": 1,
            }
            _write_exclusive_json(path, record)
        return record

    def claim(
        self,
        request: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically reserve cap and claim exactly one request before adapter invocation."""

        claimed_hash = request.get("request_sha256")
        if not isinstance(claimed_hash, str) or len(claimed_hash) != 64:
            raise ValueError("request lacks a SHA-256 claim identity")
        unhashed = dict(request)
        unhashed.pop("request_sha256", None)
        observed_hash = hashlib.sha256(canonical_json(unhashed).encode()).hexdigest()
        if observed_hash != claimed_hash:
            raise ValueError("request hash mismatch at claim boundary")
        if request.get("model_id") != self.model_id:
            raise ValueError("request model does not match claim store")
        duration = request.get("duration_seconds")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not 0 < duration <= 30
        ):
            raise ValueError("request duration exceeds the 30-second hard cap")
        path = self.claims_dir / f"{claimed_hash}.json"
        with self._locked():
            if not (self.root / "load-reservation.json").is_file():
                raise RuntimeError("model load must be reserved before a request claim")
            if path.exists():
                raise AlreadyClaimed(f"request was already claimed: {claimed_hash}")
            records = self._records_locked()
            calls = sum(row.get("kind") == "REQUEST_CALL" for row in records)
            if calls >= self.scheduled_calls:
                raise HardCapReached("scheduled call count is exhausted")
            seconds = self.resident_unit_seconds if calls == 0 else 2 * self.resident_unit_seconds
            used = self._effective_seconds_locked(records)
            if used + seconds > self.gpu_seconds_cap + 1e-9:
                raise HardCapReached("request reservation would exceed GPU-time cap")
            record = {
                "claimed_at_utc": _utc_now(),
                "kind": "REQUEST_CALL",
                "metadata": dict(metadata),
                "model_id": self.model_id,
                "request_sha256": claimed_hash,
                "reserved_gpu_seconds": seconds,
                "schema_version": 1,
                "state": "CLAIMED_NO_AUTOMATIC_RETRY",
            }
            _write_exclusive_json(path, record)
        return record

    def assert_claimed(self, request_sha256: str) -> dict[str, Any]:
        path = self.claims_dir / f"{request_sha256}.json"
        if not path.is_file():
            raise RuntimeError("adapter invocation is forbidden without a durable claim")
        record = self._read_record(path)
        if record.get("request_sha256") != request_sha256:
            raise RuntimeError("claim identity mismatch")
        return record

    def _record_observation(
        self,
        path: Path,
        *,
        observed_gpu_seconds: float,
        kind: str,
        request_sha256: str | None = None,
    ) -> dict[str, Any]:
        seconds = float(observed_gpu_seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("observed GPU seconds must be finite and non-negative")
        record = {
            "kind": kind,
            "model_id": self.model_id,
            "observed_at_utc": _utc_now(),
            "observed_gpu_seconds": seconds,
            "request_sha256": request_sha256,
            "schema_version": 1,
        }
        with self._locked():
            _write_exclusive_json(path, record)
        return record

    def record_load_observed(self, observed_gpu_seconds: float) -> dict[str, Any]:
        if not (self.root / "load-reservation.json").is_file():
            raise RuntimeError("cannot observe an unreserved model load")
        return self._record_observation(
            self.observations_dir / "model-load.json",
            observed_gpu_seconds=observed_gpu_seconds,
            kind="MODEL_LOAD",
        )

    def record_call_observed(
        self, request_sha256: str, observed_gpu_seconds: float
    ) -> dict[str, Any]:
        self.assert_claimed(request_sha256)
        return self._record_observation(
            self.observations_dir / f"{request_sha256}.json",
            observed_gpu_seconds=observed_gpu_seconds,
            kind="REQUEST_CALL",
            request_sha256=request_sha256,
        )

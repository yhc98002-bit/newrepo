"""Shared no-retry claims and D-0020-grounded cap for parallel SA3 state workers."""

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
from state_capture.sa3_contract import EXPECTED_GROUPS, EXPECTED_UNITS, SA3_MODEL_ID


class StateAlreadyClaimed(RuntimeError):
    """A group or resume crossed the durable no-retry boundary."""


class StateHardCapReached(RuntimeError):
    """Another claim would exceed the prospectively frozen state cap."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


class StateClaimStore:
    """One shared reservation store used by up to four static an12 shards."""

    def __init__(
        self,
        root: Path,
        *,
        gpu_seconds_cap: float,
        prefix_group_reservation_seconds: float,
        resume_unit_reservation_seconds: float,
    ) -> None:
        expected = EXPECTED_GROUPS * (
            prefix_group_reservation_seconds + 3 * resume_unit_reservation_seconds
        )
        values = (
            gpu_seconds_cap,
            prefix_group_reservation_seconds,
            resume_unit_reservation_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("state cap/reservations must be finite and positive")
        if not math.isclose(gpu_seconds_cap, expected, rel_tol=0, abs_tol=1e-8):
            raise ValueError("state cap does not equal 144*(prefix+3*resume)")
        self.root = root.resolve()
        self.prefix_dir = self.root / "prefix-group-claims"
        self.resume_dir = self.root / "resume-unit-claims"
        self.observation_dir = self.root / "observed-gpu-seconds"
        for directory in (self.root, self.prefix_dir, self.resume_dir, self.observation_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / "state-reservation.lock"
        self.lock_path.touch(exist_ok=True)
        self.gpu_seconds_cap = float(gpu_seconds_cap)
        self.prefix_reservation = float(prefix_group_reservation_seconds)
        self.resume_reservation = float(resume_unit_reservation_seconds)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self.lock_path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _identity(row: Mapping[str, Any], kind: str) -> tuple[str, str]:
        field = "group_request_sha256" if kind == "PREFIX_GROUP" else "lane_request_sha256"
        identity = row.get(field)
        if (
            not isinstance(identity, str)
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError(f"state {kind} lacks {field}")
        unhashed = dict(row)
        unhashed.pop(field, None)
        observed = hashlib.sha256(canonical_json(unhashed).encode()).hexdigest()
        if observed != identity:
            raise ValueError(f"state {kind} hash mismatch")
        if row.get("model_id") != SA3_MODEL_ID:
            raise ValueError("state claim model identity mismatch")
        return field, identity

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"state claim is not an object: {path}")
        return value

    def _records_locked(self) -> list[dict[str, Any]]:
        return [
            self._read(path)
            for path in sorted((*self.prefix_dir.glob("*.json"), *self.resume_dir.glob("*.json")))
        ]

    def _observed(self, identity: str) -> float:
        path = self.observation_dir / f"{identity}.json"
        if not path.is_file():
            return 0.0
        record = self._read(path)
        value = record.get("observed_gpu_seconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("state GPU observation is not numeric")
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError("state GPU observation is invalid")
        return result

    def _effective_locked(self, records: list[dict[str, Any]]) -> float:
        return sum(
            max(float(record["reserved_gpu_seconds"]), self._observed(record["request_sha256"]))
            for record in records
        )

    def usage(self) -> dict[str, Any]:
        with self._locked():
            records = self._records_locked()
            return {
                "effective_gpu_seconds": self._effective_locked(records),
                "gpu_seconds_cap": self.gpu_seconds_cap,
                "prefix_group_claims": sum(row["kind"] == "PREFIX_GROUP" for row in records),
                "reserved_gpu_seconds": sum(float(row["reserved_gpu_seconds"]) for row in records),
                "resume_unit_claims": sum(row["kind"] == "RESUME_UNIT" for row in records),
            }

    def claim(
        self,
        row: Mapping[str, Any],
        *,
        kind: str,
        replica_index: int,
        physical_gpu_id: int,
    ) -> dict[str, Any]:
        if kind not in {"PREFIX_GROUP", "RESUME_UNIT"}:
            raise ValueError("unsupported state claim kind")
        _, identity = self._identity(row, kind)
        directory = self.prefix_dir if kind == "PREFIX_GROUP" else self.resume_dir
        reservation = self.prefix_reservation if kind == "PREFIX_GROUP" else self.resume_reservation
        path = directory / f"{identity}.json"
        with self._locked():
            if path.exists():
                raise StateAlreadyClaimed(f"state request was already claimed: {identity}")
            records = self._records_locked()
            prefix_count = sum(record["kind"] == "PREFIX_GROUP" for record in records)
            resume_count = sum(record["kind"] == "RESUME_UNIT" for record in records)
            if kind == "PREFIX_GROUP" and prefix_count >= EXPECTED_GROUPS:
                raise StateHardCapReached("all prefix-group claims are exhausted")
            if kind == "RESUME_UNIT" and resume_count >= EXPECTED_UNITS:
                raise StateHardCapReached("all resume-unit claims are exhausted")
            if self._effective_locked(records) + reservation > self.gpu_seconds_cap + 1e-8:
                raise StateHardCapReached("state claim would exceed D-0020-grounded cap")
            record = {
                "claimed_at_utc": _utc_now(),
                "kind": kind,
                "model_id": SA3_MODEL_ID,
                "physical_gpu_id": physical_gpu_id,
                "replica_index": replica_index,
                "request_sha256": identity,
                "reserved_gpu_seconds": reservation,
                "schema_version": 1,
                "state": "CLAIMED_NO_AUTOMATIC_RETRY",
            }
            _write_json_exclusive(path, record)
        return record

    def assert_claimed(self, identity: str, *, kind: str) -> dict[str, Any]:
        directory = self.prefix_dir if kind == "PREFIX_GROUP" else self.resume_dir
        path = directory / f"{identity}.json"
        if not path.is_file():
            raise RuntimeError("state backend invocation is forbidden without durable claim")
        record = self._read(path)
        if record.get("request_sha256") != identity or record.get("kind") != kind:
            raise RuntimeError("state claim identity/kind mismatch")
        return record

    def record_observed(self, identity: str, *, kind: str, observed_gpu_seconds: float) -> None:
        self.assert_claimed(identity, kind=kind)
        seconds = float(observed_gpu_seconds)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("observed state GPU seconds must be finite and positive")
        with self._locked():
            _write_json_exclusive(
                self.observation_dir / f"{identity}.json",
                {
                    "kind": kind,
                    "model_id": SA3_MODEL_ID,
                    "observed_at_utc": _utc_now(),
                    "observed_gpu_seconds": seconds,
                    "request_sha256": identity,
                    "schema_version": 1,
                },
            )


__all__ = [
    "StateAlreadyClaimed",
    "StateClaimStore",
    "StateHardCapReached",
]

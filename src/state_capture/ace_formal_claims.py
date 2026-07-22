"""Parallel-safe, no-retry ACE formal group claims under the D-0033 cap."""

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
from state_capture.ace_formal_contract import (
    GPU_IDS,
    GPU_SECONDS_CAP,
    GROUP_RESERVATION_SECONDS,
    MODEL_ID,
    PASS,
    AceFormalConfig,
    D0036Authorization,
    validate_formal_call_claim,
    validate_formal_engine_claim,
)


class AceFormalAlreadyClaimed(RuntimeError):
    """A survivor group crossed the durable no-retry boundary."""


class AceFormalHardCapReached(RuntimeError):
    """The next group reservation would exceed the formal initial cap."""


class AceFormalPeerFailed(RuntimeError):
    """Another replica durably terminalized the current formal attempt."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
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


class AceFormalClaimStore:
    """Share one group reservation namespace across four independent workers."""

    def __init__(self, root: Path, *, config: AceFormalConfig) -> None:
        self.root = root.resolve()
        self.claim_dir = self.root / "group-claims"
        self.prefix_call_dir = self.root / "prefix-call-claims"
        self.resume_call_dir = self.root / "resume-call-claims"
        self.observation_dir = self.root / "observed-gpu-seconds"
        for directory in (
            self.root,
            self.claim_dir,
            self.prefix_call_dir,
            self.resume_call_dir,
            self.observation_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / "reservation.lock"
        self.lock_path.touch(exist_ok=True)
        self.failure_latch_path = self.root.parent / "formal-terminal-failure.json"
        self.config = config

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self.lock_path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"formal claim is not an object: {path}")
        return value

    def _claims_locked(self) -> list[dict[str, Any]]:
        return [self._read(path) for path in sorted(self.claim_dir.glob("*.json"))]

    def _require_clear_locked(self) -> None:
        if self.failure_latch_path.exists():
            raise AceFormalPeerFailed(
                "ACE formal attempt has a FAILED_STOPPED latch; engineering repair "
                "requires a new run ID and claim"
            )

    def _latch_locked(
        self, *, identity: str, replica_index: int, exc: BaseException
    ) -> dict[str, Any]:
        record = {
            "engineering_failure_repairable": True,
            "engineering_failure_scope": "CURRENT_RUN_ATTEMPT_ONLY",
            "engineering_repair_requires_new_claim": True,
            "engineering_repair_requires_new_run_id": True,
            "error_class": type(exc).__name__,
            "error_message": str(exc)[:2000],
            "failed_attempt_immutable": True,
            "failed_at_utc": _utc_now(),
            "group_request_sha256": identity,
            "replica_index": replica_index,
            "retry_allowed": False,
            "schema_version": 1,
            "scientific_rerun_for_weak_result_allowed": False,
            "status": "FAILED_STOPPED",
            "within_attempt_retry": False,
        }
        if not self.failure_latch_path.exists():
            _write_exclusive(self.failure_latch_path, record)
        return self._read(self.failure_latch_path)

    def _observed(self, identity: str) -> float:
        path = self.observation_dir / f"{identity}.json"
        if not path.is_file():
            return 0.0
        value = self._read(path).get("observed_gpu_seconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("formal observed GPU seconds are invalid")
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError("formal observed GPU seconds are nonfinite or negative")
        return result

    def _effective_locked(self, claims: list[dict[str, Any]]) -> float:
        return sum(
            max(float(row["reserved_gpu_seconds"]), self._observed(row["group_request_sha256"]))
            for row in claims
        )

    @staticmethod
    def _validate_group(group: Mapping[str, Any], survivor_axes: tuple[str, ...]) -> str:
        identity = group.get("group_request_sha256")
        unhashed = dict(group)
        unhashed.pop("group_request_sha256", None)
        if (
            not isinstance(identity, str)
            or hashlib.sha256(canonical_json(unhashed).encode()).hexdigest() != identity
            or group.get("model_id") != MODEL_ID
            or group.get("axis") not in survivor_axes
            or group.get("source_queue_derivation") != "FRESH_ACE_CORE_GENERATION_QUEUE"
        ):
            raise ValueError("formal group is not an exact Stage-1 survivor queue row")
        return identity

    def reserve_group(
        self,
        group: Mapping[str, Any],
        *,
        authorization: D0036Authorization,
        git_commit: str,
        replica_index: int,
        physical_gpu_id: int,
    ) -> dict[str, Any]:
        identity = self._validate_group(group, authorization.stage1.survivor_axes)
        if replica_index not in range(4) or physical_gpu_id not in GPU_IDS:
            raise ValueError("formal claim placement is outside an12:4..7/replicas 0..3")
        path = self.claim_dir / f"{identity}.json"
        with self._locked():
            self._require_clear_locked()
            if path.exists():
                raise AceFormalAlreadyClaimed(identity)
            claims = self._claims_locked()
            if len(claims) >= 144:
                raise AceFormalHardCapReached("all formal group claims are exhausted")
            effective = self._effective_locked(claims)
            if effective + GROUP_RESERVATION_SECONDS > GPU_SECONDS_CAP + 1e-8:
                raise AceFormalHardCapReached("next ACE formal group exceeds the D-0033 cap")
            record: dict[str, Any] = {
                "axis": group["axis"],
                "claim_type": "ACE_FORMAL_INITIAL_SURVIVOR_GROUP",
                "claimed_at_utc": _utc_now(),
                "config_sha256": self.config.sha256,
                "decision_block_sha256": authorization.decision_block_sha256,
                "engineering_governance_block_sha256": (
                    authorization.engineering_governance_block_sha256
                ),
                "git_commit": git_commit,
                "group_request_sha256": identity,
                "lane_request_sha256s": list(group["lane_request_sha256s"]),
                "model_id": MODEL_ID,
                "node": "an12",
                "physical_gpu_id": physical_gpu_id,
                "preflight_config_sha256": self.config.raw["engine"]["preflight_config"]["sha256"],
                "replica_index": replica_index,
                "reserved_gpu_seconds": GROUP_RESERVATION_SECONDS,
                "retry_allowed": False,
                "schema_version": 1,
                "stage1_result_sha256": authorization.stage1.result_sha256,
                "stage1_summary_sha256": authorization.stage1.summary_sha256,
                "stage1_verdict": PASS,
                "state": "CLAIMED_NO_AUTOMATIC_RETRY",
            }
            record["claim_identity_sha256"] = hashlib.sha256(
                canonical_json(record).encode()
            ).hexdigest()
            _write_exclusive(path, record)
        return {**validate_formal_engine_claim(path), "path": str(path), "sha256": _sha(path)}

    def claim_call(
        self,
        row: Mapping[str, Any],
        *,
        kind: str,
        group_claim: Mapping[str, Any],
        survivor_axes: tuple[str, ...],
        replica_index: int,
        physical_gpu_id: int,
        start_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Claim one reference-prefix or one true-state resume before invocation."""

        if kind == "PREFIX_GROUP":
            identity = self._validate_group(row, survivor_axes)
            directory = self.prefix_call_dir
        elif kind == "RESUME_UNIT":
            identity = row.get("lane_request_sha256")
            unhashed = dict(row)
            unhashed.pop("lane_request_sha256", None)
            if (
                not isinstance(identity, str)
                or hashlib.sha256(canonical_json(unhashed).encode()).hexdigest() != identity
                or row.get("model_id") != MODEL_ID
                or row.get("axis") not in survivor_axes
                or row.get("source_queue_derivation") != "FRESH_ACE_CORE_GENERATION_QUEUE"
            ):
                raise ValueError("formal resume unit is not an exact Stage-1 survivor row")
            directory = self.resume_call_dir
        else:
            raise ValueError("formal call claim kind is unsupported")
        parent_path = Path(str(group_claim["path"]))
        parent = validate_formal_engine_claim(parent_path)
        if (
            _sha(parent_path) != group_claim.get("sha256")
            or parent["axis"] != row.get("axis")
            or replica_index != parent["replica_index"]
            or physical_gpu_id != parent["physical_gpu_id"]
        ):
            raise ValueError("formal call placement/axis differs from its group envelope")
        if kind == "PREFIX_GROUP" and identity != parent["group_request_sha256"]:
            raise ValueError("formal prefix call differs from its parent group")
        if kind == "RESUME_UNIT" and identity not in parent["lane_request_sha256s"]:
            raise ValueError("formal resume unit is not a member of its parent group")
        path = directory / f"{identity}.json"
        record: dict[str, Any] = {
            "axis": row["axis"],
            "call_kind": kind,
            "claim_type": "ACE_FORMAL_INITIAL_MODEL_CALL",
            "claimed_at_utc": _utc_now(),
            "group_claim_sha256": str(group_claim["sha256"]),
            "engineering_governance_block_sha256": parent[
                "engineering_governance_block_sha256"
            ],
            "group_request_sha256": parent["group_request_sha256"],
            "model_id": MODEL_ID,
            "physical_gpu_id": physical_gpu_id,
            "replica_index": replica_index,
            "request_sha256": identity,
            "retry_allowed": False,
            "schema_version": 1,
            "stage1_result_sha256": parent["stage1_result_sha256"],
            "state": "CLAIMED_NO_AUTOMATIC_RETRY",
        }
        record["claim_identity_sha256"] = hashlib.sha256(
            canonical_json(record).encode()
        ).hexdigest()
        with self._locked():
            self._require_clear_locked()
            if path.exists():
                raise AceFormalAlreadyClaimed(identity)
            _write_exclusive(path, record)
            claimed = {**record, "path": str(path), "sha256": _sha(path)}
            if start_callback is not None:
                try:
                    start_callback(claimed)
                except BaseException as exc:
                    self._latch_locked(
                        identity=parent["group_request_sha256"],
                        replica_index=replica_index,
                        exc=exc,
                    )
                    raise
        return claimed

    def assert_claimed(self, identity: str) -> dict[str, Any]:
        return validate_formal_engine_claim(self.claim_dir / f"{identity}.json")

    def assert_call_claimed(self, identity: str, *, kind: str) -> dict[str, Any]:
        if kind not in {"PREFIX_GROUP", "RESUME_UNIT"}:
            raise ValueError("formal call claim kind is unsupported")
        directory = self.prefix_call_dir if kind == "PREFIX_GROUP" else self.resume_call_dir
        return validate_formal_call_claim(
            directory / f"{identity}.json",
            expected_kind=kind,
            expected_request_sha256=identity,
        )

    def record_observed(self, identity: str, observed_gpu_seconds: float) -> None:
        self.assert_claimed(identity)
        value = float(observed_gpu_seconds)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("observed group GPU seconds must be finite and positive")
        if value > GROUP_RESERVATION_SECONDS + 1e-8:
            raise AceFormalHardCapReached(
                "observed ACE formal group exceeded its frozen GPU-seconds envelope"
            )
        with self._locked():
            self._require_clear_locked()
            _write_exclusive(
                self.observation_dir / f"{identity}.json",
                {
                    "group_request_sha256": identity,
                    "model_id": MODEL_ID,
                    "observed_at_utc": _utc_now(),
                    "observed_gpu_seconds": value,
                    "schema_version": 1,
                },
            )

    def require_lane_clear(self) -> None:
        with self._locked():
            self._require_clear_locked()

    @contextmanager
    def publish_guard(self) -> Iterator[None]:
        """Hold the shared terminal-ordering lock across an immutable publish."""

        with self._locked():
            self._require_clear_locked()
            yield

    def guarded(self, callback: Any) -> Any:
        """Run a short ledger transition atomically with the peer-failure check."""

        with self._locked():
            self._require_clear_locked()
            return callback()

    def latch_failure(
        self, *, identity: str, replica_index: int, exc: BaseException
    ) -> dict[str, Any]:
        with self._locked():
            return self._latch_locked(
                identity=identity,
                replica_index=replica_index,
                exc=exc,
            )

    def commit_group(
        self,
        identity: str,
        observed_gpu_seconds: float,
        callback: Any,
    ) -> Any:
        """Bind cap observation and final group ledger commit before peer failure."""

        self.assert_claimed(identity)
        value = float(observed_gpu_seconds)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("observed group GPU seconds must be finite and positive")
        if value > GROUP_RESERVATION_SECONDS + 1e-8:
            raise AceFormalHardCapReached(
                "observed ACE formal group exceeded its frozen GPU-seconds envelope"
            )
        with self._locked():
            self._require_clear_locked()
            _write_exclusive(
                self.observation_dir / f"{identity}.json",
                {
                    "group_request_sha256": identity,
                    "model_id": MODEL_ID,
                    "observed_at_utc": _utc_now(),
                    "observed_gpu_seconds": value,
                    "schema_version": 1,
                },
            )
            return callback()

    def usage(self) -> dict[str, Any]:
        with self._locked():
            claims = self._claims_locked()
            return {
                "effective_gpu_seconds": self._effective_locked(claims),
                "group_claims": len(claims),
                "gpu_seconds_cap": GPU_SECONDS_CAP,
                "reserved_gpu_seconds": sum(float(row["reserved_gpu_seconds"]) for row in claims),
            }


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AceFormalAlreadyClaimed",
    "AceFormalClaimStore",
    "AceFormalHardCapReached",
    "AceFormalPeerFailed",
]

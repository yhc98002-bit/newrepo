"""Four-way survivor-only ACE formal worker with terminal failure latching."""

from __future__ import annotations

import hashlib
import math
import os
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from benchmark_core.config import PlacementConfig
from benchmark_core.heartbeat import SHA256_ZERO, HeartbeatLoop, utc_now
from benchmark_core.ledger import HashChainedLedger
from benchmark_core.placement import (
    DeviceLease,
    NvidiaSmiProbe,
    PlacementBlocked,
    PlacementUnavailable,
)
from state_capture.ace_formal_claims import (
    AceFormalAlreadyClaimed,
    AceFormalClaimStore,
    AceFormalHardCapReached,
)
from state_capture.ace_formal_contract import (
    GPU_IDS,
    MODEL_ID,
    AceFormalConfig,
    D0036Authorization,
)


class AceFormalGroupEngine(Protocol):
    model_id: str

    def preflight(self) -> Mapping[str, Any]: ...

    def load(self) -> Mapping[str, Any]: ...

    def run_group(
        self,
        group: Mapping[str, Any],
        units: Sequence[Mapping[str, Any]],
        claim: Mapping[str, Any],
        boundary: DurableCallBoundary,
    ) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


class AceFormalWorkerStopped(RuntimeError):
    """A no-retry claim or failure stopped the current immutable attempt."""


class FailureLatch:
    """A single immutable new-failure terminal shared by all replicas."""

    def __init__(self, path: Path, *, claims: AceFormalClaimStore) -> None:
        self.path = path.resolve()
        self.claims = claims
        if self.path != claims.failure_latch_path.resolve():
            raise ValueError("formal failure latch does not share the claim coordination root")

    def require_clear(self) -> None:
        try:
            self.claims.require_lane_clear()
        except RuntimeError as exc:
            raise AceFormalWorkerStopped(
                "ACE formal attempt is FAILED_STOPPED; engineering repair requires "
                "a new run ID and claim"
            ) from exc

    def stop(self, *, identity: str, replica_index: int, exc: BaseException) -> dict[str, Any]:
        return self.claims.latch_failure(
            identity=identity,
            replica_index=replica_index,
            exc=exc,
        )


class DurableCallBoundary:
    """Own the four independent claim/ledger transitions for one root group."""

    def __init__(
        self,
        *,
        claims: AceFormalClaimStore,
        ledger: HashChainedLedger,
        group_claim: Mapping[str, Any],
        survivor_axes: tuple[str, ...],
        replica_index: int,
        physical_gpu_id: int,
    ) -> None:
        self.claims = claims
        self.ledger = ledger
        self.group_claim = group_claim
        self.survivor_axes = survivor_axes
        self.replica_index = replica_index
        self.physical_gpu_id = physical_gpu_id
        self.active: tuple[str, str] | None = None
        self.completed: set[str] = set()
        self.last_ledger_sha256 = SHA256_ZERO
        self.publish_guard_completed = False

    @staticmethod
    def _identity(row: Mapping[str, Any], kind: str) -> str:
        field = "group_request_sha256" if kind == "PREFIX_GROUP" else "lane_request_sha256"
        value = row.get(field)
        if not isinstance(value, str):
            raise ValueError(f"formal {kind} row lacks {field}")
        return value

    def start(self, kind: str, row: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.active is not None:
            raise RuntimeError("a formal model call is already active")
        identity = self._identity(row, kind)

        def ledger_start(claim: Mapping[str, Any]) -> None:
            self.ledger.transition(
                identity,
                "CLAIMED",
                {
                    "axis": row["axis"],
                    "call_claim_path": claim["path"],
                    "call_claim_sha256": claim["sha256"],
                    "call_kind": kind,
                    "group_claim_sha256": self.group_claim["sha256"],
                    "group_request_sha256": self.group_claim["group_request_sha256"],
                    "physical_gpu_id": self.physical_gpu_id,
                    "replica_index": self.replica_index,
                },
            )
            last = self.ledger.transition(
                identity,
                "CALL_STARTED",
                {"call_kind": kind, "started_at_utc": utc_now()},
            )
            self.last_ledger_sha256 = str(last["ledger_row_sha256"])

        claim = self.claims.claim_call(
            row,
            kind=kind,
            group_claim=self.group_claim,
            survivor_axes=self.survivor_axes,
            replica_index=self.replica_index,
            physical_gpu_id=self.physical_gpu_id,
            start_callback=ledger_start,
        )
        self.active = (identity, kind)
        return claim

    def succeed(self, kind: str, row: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        identity = self._identity(row, kind)
        if self.active != (identity, kind):
            raise RuntimeError("formal success does not match the active call")
        self.claims.assert_call_claimed(identity, kind=kind)
        last = self.claims.guarded(
            lambda: self.ledger.transition(
                identity,
                "SUCCEEDED",
                {"call_kind": kind, "finished_at_utc": utc_now(), **dict(payload)},
            )
        )
        self.last_ledger_sha256 = str(last["ledger_row_sha256"])
        self.completed.add(identity)
        self.active = None

    @contextmanager
    def publish_guard(self) -> Any:
        with self.claims.publish_guard():
            yield
        self.publish_guard_completed = True

    def fail_active(self, exc: BaseException) -> None:
        if self.active is None:
            return
        identity, kind = self.active
        last = self.ledger.transition(
            identity,
            "FAILED",
            {
                "call_kind": kind,
                "error_class": type(exc).__name__,
                "error_message": str(exc)[:2000],
                "failed_at_utc": utc_now(),
                "retry_allowed": False,
            },
        )
        self.last_ledger_sha256 = str(last["ledger_row_sha256"])
        self.active = None

    def require_complete(
        self, group: Mapping[str, Any], units: Sequence[Mapping[str, Any]]
    ) -> None:
        expected = {
            str(group["group_request_sha256"]),
            *(str(unit["lane_request_sha256"]) for unit in units),
        }
        if (
            self.active is not None
            or self.completed != expected
            or not self.publish_guard_completed
        ):
            raise RuntimeError("formal engine did not cross all four durable call boundaries")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_group_result(
    result: Mapping[str, Any], *, group: Mapping[str, Any]
) -> dict[str, Any]:
    value = dict(result)
    required = {
        "artifact_commit_path",
        "artifact_commit_sha256",
        "completed_units",
        "gpu_seconds",
        "group_request_sha256",
        "model_calls",
        "peak_allocated_bytes",
        "peak_reserved_bytes",
        "same_root_previews",
        "status",
    }
    if set(value) != required:
        raise ValueError("formal engine group result schema drifted")
    commit = Path(str(value["artifact_commit_path"])).resolve(strict=True)
    if (
        value["status"] != "PASS"
        or value["group_request_sha256"] != group["group_request_sha256"]
        or value["completed_units"] != 3
        or value["model_calls"] != 4
        or value["same_root_previews"] is not True
        or value["artifact_commit_sha256"] != _sha256_file(commit)
    ):
        raise ValueError("formal engine group result identity/counts drifted")
    seconds = value["gpu_seconds"]
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError("formal group GPU seconds are not numeric")
    if not math.isfinite(float(seconds)) or float(seconds) <= 0:
        raise ValueError("formal group GPU seconds must be finite and positive")
    for name in ("peak_allocated_bytes", "peak_reserved_bytes"):
        number = value[name]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ValueError(f"formal group {name} is invalid")
    return value


class AceFormalWorker:
    """Run one static modulo shard; STOP axes never reach a claim surface."""

    def __init__(
        self,
        *,
        config: AceFormalConfig,
        authorization: D0036Authorization,
        run_dir: Path,
        run_id: str,
        git_commit: str,
        queue_manifest_sha256: str,
        replica_index: int,
        replica_count: int,
        physical_gpu_id: int,
        engine: AceFormalGroupEngine,
        probe: NvidiaSmiProbe | None = None,
        lease: DeviceLease | None = None,
        placement_poll_seconds: float = 15.0,
    ) -> None:
        if engine.model_id != MODEL_ID:
            raise ValueError("ACE formal engine model identity mismatch")
        if (
            replica_count not in range(1, len(GPU_IDS) + 1)
            or replica_index not in range(replica_count)
            or physical_gpu_id not in GPU_IDS
        ):
            raise ValueError("ACE formal worker placement is outside an12:4..7")
        if not run_id:
            raise ValueError("ACE formal worker requires its attempt run ID")
        if not math.isfinite(placement_poll_seconds) or placement_poll_seconds < 0:
            raise ValueError("placement poll seconds must be finite and nonnegative")
        self.config = config
        self.authorization = authorization
        self.run_dir = run_dir.resolve()
        self.run_id = run_id
        self.git_commit = git_commit
        self.queue_manifest_sha256 = queue_manifest_sha256
        self.replica_index = replica_index
        self.replica_count = replica_count
        self.physical_gpu_id = physical_gpu_id
        self.engine = engine
        self.poll_seconds = float(placement_poll_seconds)
        placement = config.raw["placement"]
        self.placement = PlacementConfig(
            node="an12",
            physical_gpu_id=physical_gpu_id,
            logical_gpu_id=0,
            tp_width=1,
            replica_count=1,
            minimum_free_vram_bytes=int(placement["minimum_free_vram_bytes"]),
            post_load_reserve_bytes=int(placement["post_load_reserve_bytes"]),
            lock_root=Path(placement["cooperative_lock_root"]),
            required_gpu_name_substring=str(placement["required_gpu_name_substring"]),
            maximum_idle_utilization_percent=int(placement["maximum_idle_utilization_percent"]),
        )
        self.probe = probe or NvidiaSmiProbe(self.placement)
        self.lease = lease or DeviceLease(self.placement)
        self.claims = AceFormalClaimStore(
            self.run_dir / "control" / "shared-formal-claims", config=config
        )
        self.ledger = HashChainedLedger(self.run_dir / "formal-state-ledger.jsonl")
        self.latch = FailureLatch(
            self.run_dir / "control" / "formal-terminal-failure.json",
            claims=self.claims,
        )
        self.worker_root = self.run_dir / "workers" / f"replica-{replica_index:02d}"

    def _heartbeat_payload(self) -> dict[str, Any]:
        return {
            "completed": 0,
            "config_sha256": self.config.sha256,
            "cumulative_synchronized_gpu_seconds": 0.0,
            "current_request_sha256": None,
            "current_shard": self.replica_index,
            "failed": 0,
            "git_commit": self.git_commit,
            "last_ledger_sha256": SHA256_ZERO,
            "logical_gpu_id": 0,
            "node": "an12",
            "peak_allocated_bytes": 0,
            "peak_reserved_bytes": 0,
            "physical_gpu_id": self.physical_gpu_id,
            "pid": os.getpid(),
            "prompt_manifest_sha256": self.queue_manifest_sha256,
            "run_id": self.run_id,
            "schema_version": 1,
            "state": "QUEUED_WAITING_FOR_SAFE_GPU",
            "updated_at_utc": utc_now(),
        }

    def _acquire_safe(
        self, heartbeat: HeartbeatLoop, *, test_only_max_wait_cycles: int | None
    ) -> None:
        waits = 0
        while True:
            heartbeat.require_current(self.config.heartbeat_stale_after_seconds)
            heartbeat.update(state="QUEUED_WAITING_FOR_SAFE_GPU")
            heartbeat.flush()
            acquired = False
            try:
                self.lease.acquire()
                acquired = True
                self.probe.require_safe(
                    minimum_free_vram_bytes=self.placement.minimum_free_vram_bytes,
                    maximum_utilization_percent=self.placement.maximum_idle_utilization_percent,
                )
                return
            except PlacementUnavailable:
                if acquired:
                    self.lease.release()
                waits += 1
                if test_only_max_wait_cycles is not None and waits >= test_only_max_wait_cycles:
                    raise
                if self.poll_seconds:
                    time.sleep(self.poll_seconds)
            except BaseException:
                if acquired:
                    self.lease.release()
                raise

    def run(
        self,
        *,
        groups: Sequence[Mapping[str, Any]],
        units: Sequence[Mapping[str, Any]],
        max_new_groups: int | None = None,
        test_only_max_wait_cycles: int | None = None,
    ) -> dict[str, Any]:
        if max_new_groups is not None and max_new_groups <= 0:
            raise ValueError("max_new_groups must be positive")
        survivor_axes = set(self.authorization.stage1.survivor_axes)
        if any(group.get("axis") not in survivor_axes for group in groups):
            raise ValueError("worker received a STOP-axis group")
        if any(unit.get("axis") not in survivor_axes for unit in units):
            raise ValueError("worker received a STOP-axis unit")
        unit_index = {str(row["lane_request_sha256"]): row for row in units}
        assigned = [
            group
            for group in groups
            if (int(group["group_sequence"]) - 1) % self.replica_count == self.replica_index
        ]
        heartbeat = HeartbeatLoop(
            self.worker_root / "heartbeat.json",
            self._heartbeat_payload(),
            self.config.heartbeat_interval_seconds,
        )
        completed = 0
        failed = 0
        cumulative = 0.0
        peak_allocated = 0
        peak_reserved = 0
        current_identity = self.config.sha256
        with heartbeat:
            heartbeat.flush()
            try:
                self.latch.require_clear()
                self._acquire_safe(heartbeat, test_only_max_wait_cycles=test_only_max_wait_cycles)
                with self.lease:
                    heartbeat.update(state="LOADING")
                    heartbeat.flush()
                    preflight = dict(self.engine.preflight())
                    if preflight.get("status") != "READY":
                        raise AceFormalWorkerStopped("ACE formal engine preflight is not READY")
                    self.engine.load()
                    self.probe.require_safe(
                        minimum_free_vram_bytes=self.placement.post_load_reserve_bytes,
                        allowed_pids={os.getpid()},
                        maximum_utilization_percent=None,
                    )
                    heartbeat.update(state="RUNNING")
                    for group in assigned:
                        self.latch.require_clear()
                        identity = str(group["group_request_sha256"])
                        current_identity = identity
                        call_ids = {
                            identity,
                            *(str(unit_id) for unit_id in group["lane_request_sha256s"]),
                        }
                        prior_states = self.ledger.request_states()
                        observed_prior = {
                            key: prior_states[key] for key in call_ids if key in prior_states
                        }
                        if (
                            observed_prior
                            and set(observed_prior) == call_ids
                            and set(observed_prior.values()) == {"SUCCEEDED"}
                        ):
                            continue
                        if observed_prior:
                            raise AceFormalWorkerStopped(
                                f"formal group {identity} has prior call states; retry forbidden"
                            )
                        try:
                            claim = self.claims.reserve_group(
                                group,
                                authorization=self.authorization,
                                git_commit=self.git_commit,
                                replica_index=self.replica_index,
                                physical_gpu_id=self.physical_gpu_id,
                            )
                        except AceFormalAlreadyClaimed as exc:
                            raise AceFormalWorkerStopped(
                                f"durable formal claim exists without completion: {identity}"
                            ) from exc
                        boundary = DurableCallBoundary(
                            claims=self.claims,
                            ledger=self.ledger,
                            group_claim=claim,
                            survivor_axes=self.authorization.stage1.survivor_axes,
                            replica_index=self.replica_index,
                            physical_gpu_id=self.physical_gpu_id,
                        )
                        heartbeat.update(
                            current_request_sha256=identity,
                            state="RUNNING",
                        )
                        heartbeat.flush()
                        group_units = [
                            unit_index[str(unit_id)] for unit_id in group["lane_request_sha256s"]
                        ]
                        try:
                            result = _validate_group_result(
                                self.engine.run_group(group, group_units, claim, boundary),
                                group=group,
                            )
                            boundary.require_complete(group, group_units)
                            last = self.claims.commit_group(
                                identity,
                                float(result["gpu_seconds"]),
                                lambda value=result: self.ledger.append(
                                    {
                                        "event_kind": "FORMAL_GROUP_COMMITTED",
                                        "finished_at_utc": utc_now(),
                                        **value,
                                    }
                                ),
                            )
                        except BaseException as exc:
                            failed += 1
                            self.latch.stop(
                                identity=identity,
                                replica_index=self.replica_index,
                                exc=exc,
                            )
                            boundary.fail_active(exc)
                            last = self.ledger.append(
                                {
                                    "event_kind": "FORMAL_GROUP_FAILED_STOPPED",
                                    "error_class": type(exc).__name__,
                                    "error_message": str(exc)[:2000],
                                    "failed_at_utc": utc_now(),
                                    "group_request_sha256": identity,
                                    "retry_allowed": False,
                                }
                            )
                            heartbeat.update(
                                current_request_sha256=None,
                                failed=failed,
                                last_ledger_sha256=last["ledger_row_sha256"],
                                state="FAILED_STOPPED",
                            )
                            heartbeat.flush()
                            raise AceFormalWorkerStopped(
                                f"ACE formal attempt failed at {identity}; within-attempt retry "
                                "is forbidden and repair requires a new run ID and claim"
                            ) from exc
                        completed += 1
                        cumulative += float(result["gpu_seconds"])
                        peak_allocated = max(peak_allocated, result["peak_allocated_bytes"])
                        peak_reserved = max(peak_reserved, result["peak_reserved_bytes"])
                        heartbeat.update(
                            completed=completed,
                            cumulative_synchronized_gpu_seconds=cumulative,
                            current_request_sha256=None,
                            current_shard=int(group["group_sequence"]),
                            last_ledger_sha256=last["ledger_row_sha256"],
                            peak_allocated_bytes=peak_allocated,
                            peak_reserved_bytes=peak_reserved,
                            state="RUNNING",
                        )
                        heartbeat.snapshot(
                            self.worker_root / "heartbeat-snapshots",
                            int(group["group_sequence"]),
                        )
                        if max_new_groups is not None and completed >= max_new_groups:
                            heartbeat.update(state="COMPLETE")
                            heartbeat.flush()
                            return {
                                "completed_groups": completed,
                                "replica_index": self.replica_index,
                                "status": "BOUNDED_BATCH_COMPLETE",
                            }
                    heartbeat.update(state="COMPLETE")
                    heartbeat.flush()
                    return {
                        "completed_groups": completed,
                        "replica_index": self.replica_index,
                        "status": "COMPLETE",
                    }
            except PlacementBlocked:
                heartbeat.update(state="PLACEMENT_HEADROOM_BLOCKED")
                heartbeat.flush()
                raise
            except AceFormalHardCapReached:
                heartbeat.update(state="HARD_CAP_REACHED")
                heartbeat.flush()
                raise
            except BaseException as exc:
                self.latch.stop(
                    identity=current_identity,
                    replica_index=self.replica_index,
                    exc=exc,
                )
                heartbeat.update(state="FAILED_STOPPED")
                heartbeat.flush()
                raise
            finally:
                self.engine.close()


__all__ = [
    "AceFormalGroupEngine",
    "AceFormalWorker",
    "AceFormalWorkerStopped",
    "FailureLatch",
]

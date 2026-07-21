"""Parallel-safe SA3 state worker with shared claims, ledger, locks, and heartbeats."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping, Sequence
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
from state_capture.sa3_artifacts import (
    StagedPrefixGroup,
    StagedResume,
    commit_prefix_group,
    commit_resume,
)
from state_capture.sa3_claims import (
    StateAlreadyClaimed,
    StateClaimStore,
    StateHardCapReached,
)
from state_capture.sa3_contract import SA3_MODEL_ID, SA3StateCaptureConfig, sha256_file


class StateEngine(Protocol):
    model_id: str

    def preflight(self) -> Mapping[str, Any]: ...

    def load(self) -> Mapping[str, Any]: ...

    def capture_group(
        self,
        group: Mapping[str, Any],
        units: Sequence[Mapping[str, Any]],
        staging_dir: Path,
    ) -> StagedPrefixGroup: ...

    def resume(
        self,
        unit: Mapping[str, Any],
        checkpoint_path: Path,
        staging_dir: Path,
    ) -> StagedResume: ...

    def close(self) -> None: ...


class StateWorkerStopped(RuntimeError):
    """A claimed state call failed or a prior claim cannot be retried."""


class SA3StateWorker:
    def __init__(
        self,
        *,
        config: SA3StateCaptureConfig,
        run_dir: Path,
        run_id: str,
        git_commit: str,
        bundle_manifest_sha256: str,
        replica_index: int,
        physical_gpu_id: int,
        engine: StateEngine,
        probe: NvidiaSmiProbe | None = None,
        lease: DeviceLease | None = None,
        placement_poll_seconds: float = 15.0,
    ) -> None:
        if engine.model_id != SA3_MODEL_ID:
            raise ValueError("state engine model identity mismatch")
        if replica_index not in range(config.placement.maximum_parallel_replicas):
            raise ValueError("replica_index is outside frozen 0..3")
        if physical_gpu_id not in config.placement.allowed_physical_gpu_ids:
            raise ValueError("physical GPU is not one of frozen an12:4..7 candidates")
        if not math.isfinite(placement_poll_seconds) or placement_poll_seconds < 0:
            raise ValueError("placement polling interval must be finite and non-negative")
        self.config = config
        self.run_dir = run_dir.resolve()
        self.run_id = run_id
        self.git_commit = git_commit
        self.bundle_sha = bundle_manifest_sha256
        self.replica_index = replica_index
        self.physical_gpu_id = physical_gpu_id
        self.engine = engine
        self.poll_seconds = float(placement_poll_seconds)
        self.placement = PlacementConfig(
            node="an12",
            physical_gpu_id=physical_gpu_id,
            logical_gpu_id=0,
            tp_width=1,
            replica_count=1,
            minimum_free_vram_bytes=config.placement.minimum_free_vram_bytes,
            post_load_reserve_bytes=config.placement.post_load_reserve_bytes,
            lock_root=config.placement.shared_core_lock_root,
            required_gpu_name_substring=config.placement.required_gpu_name_substring,
            maximum_idle_utilization_percent=(config.placement.maximum_idle_utilization_percent),
        )
        self.probe = probe or NvidiaSmiProbe(self.placement)
        self.lease = lease or DeviceLease(self.placement)
        self.ledger = HashChainedLedger(self.run_dir / "state-ledger.jsonl")
        self.claims = StateClaimStore(
            self.run_dir / "control" / "shared-state-claims",
            gpu_seconds_cap=config.initial_gpu_seconds_cap,
            prefix_group_reservation_seconds=config.prefix_group_reservation_seconds,
            resume_unit_reservation_seconds=config.resume_unit_reservation_seconds,
        )
        self.worker_root = self.run_dir / "workers" / f"replica-{replica_index:02d}"

    def _heartbeat_payload(self) -> dict[str, Any]:
        return {
            "completed": 0,
            "config_sha256": self.config.source_sha256,
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
            "prompt_manifest_sha256": self.bundle_sha,
            "run_id": self.run_id,
            "schema_version": 1,
            "state": "QUEUED_WAITING_FOR_SAFE_GPU",
            "updated_at_utc": utc_now(),
        }

    def _acquire_safe(
        self,
        heartbeat: HeartbeatLoop,
        *,
        test_only_max_wait_cycles: int | None,
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

    @staticmethod
    def _latest_states(ledger: HashChainedLedger) -> dict[str, str]:
        return ledger.request_states()

    def _already_complete_or_raise(self, identity: str) -> bool:
        state = self._latest_states(self.ledger).get(identity)
        if state == "SUCCEEDED":
            return True
        if state is not None:
            raise StateWorkerStopped(
                f"state request {identity} is {state}; no automatic retry is permitted"
            )
        return False

    def _claim_and_start(
        self,
        row: Mapping[str, Any],
        *,
        kind: str,
        identity: str,
        heartbeat: HeartbeatLoop,
    ) -> str:
        heartbeat.require_current(self.config.heartbeat_stale_after_seconds)
        self.probe.require_safe(
            minimum_free_vram_bytes=self.placement.minimum_free_vram_bytes,
            allowed_pids={os.getpid()},
        )
        try:
            claim = self.claims.claim(
                row,
                kind=kind,
                replica_index=self.replica_index,
                physical_gpu_id=self.physical_gpu_id,
            )
        except StateAlreadyClaimed as exc:
            raise StateWorkerStopped(
                f"durable {kind} claim exists without reusable completion: {identity}"
            ) from exc
        directory = self.claims.prefix_dir if kind == "PREFIX_GROUP" else self.claims.resume_dir
        claim_path = directory / f"{identity}.json"
        last = self.ledger.transition(
            identity,
            "CLAIMED",
            {
                "claim_kind": kind,
                "claim_sha256": sha256_file(claim_path),
                "claimed_at_utc": claim["claimed_at_utc"],
                "model_id": SA3_MODEL_ID,
                "physical_gpu_id": self.physical_gpu_id,
                "replica_index": self.replica_index,
            },
        )
        self.claims.assert_claimed(identity, kind=kind)
        last = self.ledger.transition(
            identity,
            "CALL_STARTED",
            {"call_kind": kind, "started_at_utc": utc_now()},
        )
        heartbeat.update(
            current_request_sha256=identity,
            last_ledger_sha256=last["ledger_row_sha256"],
            state="RUNNING",
        )
        heartbeat.flush()
        return str(last["ledger_row_sha256"])

    def run(
        self,
        *,
        units: Sequence[Mapping[str, Any]],
        groups: Sequence[Mapping[str, Any]],
        max_new_groups: int | None = None,
        test_only_max_wait_cycles: int | None = None,
    ) -> dict[str, Any]:
        """Run this static modulo shard; complete claims are skipped, never retried."""

        if max_new_groups is not None and max_new_groups <= 0:
            raise ValueError("max_new_groups must be positive")
        unit_index = {str(row["lane_request_sha256"]): row for row in units}
        assigned = [
            group
            for group in groups
            if (int(group["group_sequence"]) - 1) % self.config.placement.maximum_parallel_replicas
            == self.replica_index
        ]
        if len(assigned) != 36:
            raise ValueError("static four-way state shard must contain exactly 36 groups")
        heartbeat = HeartbeatLoop(
            self.worker_root / "heartbeat.json",
            self._heartbeat_payload(),
            self.config.heartbeat_interval_seconds,
        )
        completed_units = 0
        completed_groups = 0
        failed = 0
        cumulative = 0.0
        peak_allocated = 0
        peak_reserved = 0
        last_ledger = SHA256_ZERO
        terminal_state = "FAILED_STOPPED"
        with heartbeat:
            heartbeat.flush()
            try:
                self._acquire_safe(heartbeat, test_only_max_wait_cycles=test_only_max_wait_cycles)
                with self.lease:
                    heartbeat.update(state="LOADING")
                    heartbeat.flush()
                    preflight = dict(self.engine.preflight())
                    if preflight.get("status") != "READY":
                        raise StateWorkerStopped("SA3 state engine preflight is not READY")
                    self.engine.load()
                    self.probe.require_safe(
                        minimum_free_vram_bytes=self.placement.minimum_free_vram_bytes,
                        allowed_pids={os.getpid()},
                    )
                    heartbeat.update(state="RUNNING")
                    for group in assigned:
                        group_had_new_work = False
                        group_identity = str(group["group_request_sha256"])
                        group_units = [
                            unit_index[str(value)] for value in group["lane_request_sha256s"]
                        ]
                        group_complete = self._already_complete_or_raise(group_identity)
                        if not group_complete:
                            group_had_new_work = True
                            self._claim_and_start(
                                group,
                                kind="PREFIX_GROUP",
                                identity=group_identity,
                                heartbeat=heartbeat,
                            )
                            staging = self.run_dir / "staging" / group_identity
                            try:
                                staged_group = self.engine.capture_group(
                                    group, group_units, staging
                                )
                                if not isinstance(staged_group, StagedPrefixGroup):
                                    raise TypeError("state engine returned invalid prefix result")
                                self.claims.record_observed(
                                    group_identity,
                                    kind="PREFIX_GROUP",
                                    observed_gpu_seconds=staged_group.synchronized_gpu_seconds,
                                )
                                group_commit = commit_prefix_group(
                                    self.run_dir / "artifacts",
                                    group,
                                    group_units,
                                    staged_group,
                                    config=self.config,
                                )
                                last = self.ledger.transition(
                                    group_identity,
                                    "SUCCEEDED",
                                    {
                                        "actual_nfe": staged_group.actual_nfe,
                                        "call_kind": "PREFIX_GROUP",
                                        "commit": group_commit,
                                        "finished_at_utc": utc_now(),
                                        "peak_allocated_bytes": staged_group.peak_allocated_bytes,
                                        "peak_reserved_bytes": staged_group.peak_reserved_bytes,
                                        "synchronized_gpu_seconds": (
                                            staged_group.synchronized_gpu_seconds
                                        ),
                                    },
                                )
                                last_ledger = str(last["ledger_row_sha256"])
                                cumulative += staged_group.synchronized_gpu_seconds
                                peak_allocated = max(
                                    peak_allocated, staged_group.peak_allocated_bytes
                                )
                                peak_reserved = max(peak_reserved, staged_group.peak_reserved_bytes)
                            except BaseException as exc:
                                failed += 1
                                last = self.ledger.transition(
                                    group_identity,
                                    "FAILED",
                                    {
                                        "call_kind": "PREFIX_GROUP",
                                        "error_message": str(exc)[:2000],
                                        "error_type": type(exc).__name__,
                                        "failed_at_utc": utc_now(),
                                    },
                                )
                                heartbeat.update(
                                    current_request_sha256=None,
                                    failed=failed,
                                    last_ledger_sha256=last["ledger_row_sha256"],
                                    state="FAILED_STOPPED",
                                )
                                heartbeat.flush()
                                raise StateWorkerStopped(
                                    f"prefix group {group_identity} failed without retry"
                                ) from exc
                        for unit in group_units:
                            identity = str(unit["lane_request_sha256"])
                            if self._already_complete_or_raise(identity):
                                continue
                            group_had_new_work = True
                            self._claim_and_start(
                                unit,
                                kind="RESUME_UNIT",
                                identity=identity,
                                heartbeat=heartbeat,
                            )
                            checkpoint = (
                                self.run_dir / "artifacts" / str(unit["checkpoint_relpath"])
                            )
                            staging = self.run_dir / "staging" / identity
                            try:
                                staged_resume = self.engine.resume(unit, checkpoint, staging)
                                if not isinstance(staged_resume, StagedResume):
                                    raise TypeError("state engine returned invalid resume result")
                                self.claims.record_observed(
                                    identity,
                                    kind="RESUME_UNIT",
                                    observed_gpu_seconds=staged_resume.synchronized_gpu_seconds,
                                )
                                resume_commit = commit_resume(
                                    self.run_dir / "artifacts",
                                    unit,
                                    staged_resume,
                                    reference_terminal_relpath=str(
                                        group["reference_terminal_relpath"]
                                    ),
                                    config=self.config,
                                )
                                last = self.ledger.transition(
                                    identity,
                                    "SUCCEEDED",
                                    {
                                        "actual_nfe": staged_resume.actual_nfe,
                                        "call_kind": "RESUME_UNIT",
                                        "commit": resume_commit,
                                        "finished_at_utc": utc_now(),
                                        "peak_allocated_bytes": staged_resume.peak_allocated_bytes,
                                        "peak_reserved_bytes": staged_resume.peak_reserved_bytes,
                                        "synchronized_gpu_seconds": (
                                            staged_resume.synchronized_gpu_seconds
                                        ),
                                    },
                                )
                                last_ledger = str(last["ledger_row_sha256"])
                                completed_units += 1
                                cumulative += staged_resume.synchronized_gpu_seconds
                                peak_allocated = max(
                                    peak_allocated, staged_resume.peak_allocated_bytes
                                )
                                peak_reserved = max(
                                    peak_reserved, staged_resume.peak_reserved_bytes
                                )
                                heartbeat.update(
                                    completed=completed_units,
                                    cumulative_synchronized_gpu_seconds=cumulative,
                                    current_request_sha256=None,
                                    last_ledger_sha256=last_ledger,
                                    peak_allocated_bytes=peak_allocated,
                                    peak_reserved_bytes=peak_reserved,
                                )
                            except BaseException as exc:
                                failed += 1
                                last = self.ledger.transition(
                                    identity,
                                    "FAILED",
                                    {
                                        "call_kind": "RESUME_UNIT",
                                        "error_message": str(exc)[:2000],
                                        "error_type": type(exc).__name__,
                                        "failed_at_utc": utc_now(),
                                    },
                                )
                                heartbeat.update(
                                    current_request_sha256=None,
                                    failed=failed,
                                    last_ledger_sha256=last["ledger_row_sha256"],
                                    state="FAILED_STOPPED",
                                )
                                heartbeat.flush()
                                raise StateWorkerStopped(
                                    f"resume unit {identity} failed without retry"
                                ) from exc
                        if group_had_new_work:
                            completed_groups += 1
                        heartbeat.update(
                            current_shard=int(group["group_sequence"]), state="RUNNING"
                        )
                        if group_had_new_work:
                            heartbeat.snapshot(
                                self.worker_root / "heartbeat-snapshots",
                                int(group["group_sequence"]),
                            )
                        if (
                            group_had_new_work
                            and max_new_groups is not None
                            and completed_groups >= max_new_groups
                        ):
                            terminal_state = "COMPLETE"
                            heartbeat.update(state=terminal_state)
                            heartbeat.flush()
                            return {
                                "completed_groups": completed_groups,
                                "completed_units": completed_units,
                                "replica_index": self.replica_index,
                                "status": "BOUNDED_BATCH_COMPLETE",
                            }
                    terminal_state = "COMPLETE"
                    heartbeat.update(state=terminal_state)
                    heartbeat.flush()
                    return {
                        "completed_groups": completed_groups,
                        "completed_units": completed_units,
                        "replica_index": self.replica_index,
                        "status": "COMPLETE",
                    }
            except PlacementBlocked:
                terminal_state = "PLACEMENT_HEADROOM_BLOCKED"
                heartbeat.update(state=terminal_state)
                heartbeat.flush()
                raise
            except StateHardCapReached:
                terminal_state = "HARD_CAP_REACHED"
                heartbeat.update(state=terminal_state)
                heartbeat.flush()
                raise
            except BaseException:
                terminal_state = "FAILED_STOPPED"
                heartbeat.update(state=terminal_state)
                heartbeat.flush()
                raise
            finally:
                self.engine.close()


__all__ = ["SA3StateWorker", "StateEngine", "StateWorkerStopped"]

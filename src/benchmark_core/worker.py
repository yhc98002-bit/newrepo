"""Resident fail-closed single-GPU worker with an immutable no-retry ledger."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from benchmark_core.artifacts import StagedGeneration, commit_generation
from benchmark_core.claims import CallClaimStore, HardCapReached
from benchmark_core.config import ModelExecutionConfig
from benchmark_core.heartbeat import SHA256_ZERO, HeartbeatLoop, utc_now
from benchmark_core.launcher import validate_external_launch_claim
from benchmark_core.ledger import HashChainedLedger
from benchmark_core.placement import (
    DeviceLease,
    NvidiaSmiProbe,
    PlacementBlocked,
    PlacementUnavailable,
)


class CoreAdapter(Protocol):
    model_id: str

    def preflight(self) -> Mapping[str, Any]: ...

    def load(self) -> Mapping[str, Any]: ...

    def generate(
        self,
        request: Mapping[str, Any],
        staging_dir: Path,
        state_contracts: Sequence[Mapping[str, Any]],
    ) -> StagedGeneration: ...

    def close(self) -> None: ...


class WorkerStopped(RuntimeError):
    """A claimed request failed and the resident worker stopped without retry."""


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_rows(rows: Sequence[Mapping[str, Any]], model: ModelExecutionConfig) -> None:
    if not rows or len(rows) % 4:
        raise ValueError("resident queue must contain complete four-row shards")
    sequences = [row.get("sequence") for row in rows]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in sequences):
        raise ValueError("queue sequence values are invalid")
    if sequences != list(range(sequences[0], sequences[0] + len(rows))):
        raise ValueError("resident model queue rows must be consecutive")
    if any(row.get("model_id") != model.model_id for row in rows):
        raise ValueError("resident queue crosses model boundaries")
    if any(row.get("duration_seconds") != 30.0 for row in rows):
        raise ValueError("ordinary core queue contains a non-30-second request")
    hashes = [row.get("request_sha256") for row in rows]
    if len(set(hashes)) != len(rows) or not all(
        isinstance(value, str) and len(value) == 64 for value in hashes
    ):
        raise ValueError("queue request hashes are invalid or duplicated")


class BenchmarkWorker:
    """Load once, then execute consecutive shards until terminal state."""

    def __init__(
        self,
        *,
        run_dir: Path,
        run_id: str,
        git_commit: str,
        config_sha256: str,
        prompt_manifest_sha256: str,
        model: ModelExecutionConfig,
        adapter: CoreAdapter,
        heartbeat_interval_seconds: float,
        heartbeat_stale_after_seconds: float,
        launch_claim_path: Path,
        placement_wait_poll_seconds: float = 15.0,
        probe: NvidiaSmiProbe | None = None,
        lease: DeviceLease | None = None,
    ) -> None:
        if model.placement is None or model.budget is None:
            raise ValueError("worker model lacks placement or budget")
        if model.expected_sample_rate is None or model.expected_channels is None:
            raise ValueError("worker model lacks a frozen output audio format")
        if adapter.model_id != model.model_id:
            raise ValueError("adapter/model identity mismatch")
        self.run_dir = run_dir.resolve()
        self.run_id = run_id
        self.git_commit = git_commit
        self.config_sha256 = config_sha256
        self.prompt_manifest_sha256 = prompt_manifest_sha256
        self.model = model
        self.worker_root = self.run_dir / "workers" / model.slug
        self.adapter = adapter
        self.interval = heartbeat_interval_seconds
        if (
            not math.isfinite(heartbeat_stale_after_seconds)
            or heartbeat_stale_after_seconds <= heartbeat_interval_seconds
        ):
            raise ValueError("heartbeat stale threshold must exceed its interval")
        if not math.isfinite(placement_wait_poll_seconds) or placement_wait_poll_seconds < 0:
            raise ValueError("placement wait polling interval must be finite and non-negative")
        self.stale_after = float(heartbeat_stale_after_seconds)
        self.placement_wait_poll_seconds = float(placement_wait_poll_seconds)
        self.probe = probe or NvidiaSmiProbe(model.placement)
        self.lease = lease or DeviceLease(model.placement)
        self.launch_claim = validate_external_launch_claim(
            launch_claim_path,
            run_id=run_id,
            config_sha256=config_sha256,
            git_commit=git_commit,
            run_dir=self.run_dir,
        )
        self.ledger = HashChainedLedger(self.run_dir / "ledger.jsonl")
        self.claims = CallClaimStore(
            self.run_dir / "control" / model.slug,
            model_id=model.model_id,
            gpu_seconds_cap=model.budget.gpu_seconds_cap,
            scheduled_calls=model.budget.scheduled_calls,
            cold_plus_first_seconds=model.budget.cold_plus_first_seconds,
            resident_unit_seconds=model.budget.resident_unit_seconds,
        )

    def _acquire_safe_placement(
        self,
        heartbeat: HeartbeatLoop,
        *,
        minimum_free_vram_bytes: int,
        maximum_utilization_percent: int,
        test_only_max_wait_cycles: int | None,
    ) -> None:
        """Wait without signaling neighbors until the fixed device is safely leased."""

        wait_cycles = 0
        while True:
            heartbeat.require_current(self.stale_after)
            heartbeat.update(state="QUEUED_WAITING_FOR_SAFE_GPU")
            heartbeat.flush()
            acquired = False
            try:
                self.lease.acquire()
                acquired = True
                self.probe.require_safe(
                    minimum_free_vram_bytes=minimum_free_vram_bytes,
                    maximum_utilization_percent=maximum_utilization_percent,
                )
                return
            except PlacementUnavailable:
                if acquired:
                    self.lease.release()
                wait_cycles += 1
                if (
                    test_only_max_wait_cycles is not None
                    and wait_cycles >= test_only_max_wait_cycles
                ):
                    raise
                heartbeat.require_current(self.stale_after)
                if self.placement_wait_poll_seconds:
                    time.sleep(self.placement_wait_poll_seconds)
            except BaseException:
                if acquired:
                    self.lease.release()
                raise

    def _heartbeat_payload(self) -> dict[str, Any]:
        placement = self.model.placement
        assert placement is not None
        return {
            "completed": 0,
            "config_sha256": self.config_sha256,
            "cumulative_synchronized_gpu_seconds": 0.0,
            "current_request_sha256": None,
            "current_shard": 0,
            "failed": 0,
            "git_commit": self.git_commit,
            "last_ledger_sha256": SHA256_ZERO,
            "logical_gpu_id": placement.logical_gpu_id,
            "node": placement.node,
            "peak_allocated_bytes": 0,
            "peak_reserved_bytes": 0,
            "physical_gpu_id": placement.physical_gpu_id,
            "pid": os.getpid(),
            "prompt_manifest_sha256": self.prompt_manifest_sha256,
            "run_id": self.run_id,
            "schema_version": 1,
            "state": "QUEUED_WAITING_FOR_SAFE_GPU",
            "updated_at_utc": utc_now(),
        }

    def run(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        test_only_stop_after_shards: int | None = None,
        test_only_max_placement_wait_cycles: int | None = None,
    ) -> dict[str, Any]:
        """Run the resident model queue; formal state contracts are never accepted here."""

        _validate_rows(rows, self.model)
        budget = self.model.budget
        placement = self.model.placement
        assert budget is not None and placement is not None
        if len(rows) != budget.scheduled_calls:
            raise ValueError("resident queue length does not match the frozen scheduled_calls")
        if test_only_stop_after_shards is not None and test_only_stop_after_shards <= 0:
            raise ValueError("test-only shard stop must be positive")
        if (
            test_only_max_placement_wait_cycles is not None
            and test_only_max_placement_wait_cycles <= 0
        ):
            raise ValueError("test-only placement wait-cycle cap must be positive")

        heartbeat = HeartbeatLoop(
            self.worker_root / "heartbeat.json",
            self._heartbeat_payload(),
            self.interval,
        )
        completed = 0
        failed = 0
        cumulative_seconds = 0.0
        peak_allocated = 0
        peak_reserved = 0
        last_ledger = SHA256_ZERO
        adapter_loaded = False
        completed_shards: list[dict[str, Any]] = []
        terminal_state = "FAILED_STOPPED"

        with heartbeat:
            heartbeat.flush()
            try:
                self._acquire_safe_placement(
                    heartbeat,
                    minimum_free_vram_bytes=placement.minimum_free_vram_bytes,
                    maximum_utilization_percent=placement.maximum_idle_utilization_percent,
                    test_only_max_wait_cycles=test_only_max_placement_wait_cycles,
                )
                with self.lease:
                    self.claims.reserve_load(
                        {
                            "node": placement.node,
                            "physical_gpu_id": placement.physical_gpu_id,
                            "replica_count": placement.replica_count,
                            "tp_width": placement.tp_width,
                        }
                    )
                    heartbeat.update(state="LOADING")
                    heartbeat.flush()
                    preflight = dict(self.adapter.preflight())
                    if preflight.get("status") != "READY":
                        raise WorkerStopped("adapter preflight is not READY")
                    try:
                        self.probe.require_safe(
                            minimum_free_vram_bytes=placement.minimum_free_vram_bytes,
                            maximum_utilization_percent=(
                                placement.maximum_idle_utilization_percent
                            ),
                        )
                    except PlacementUnavailable:
                        self.lease.release()
                        self._acquire_safe_placement(
                            heartbeat,
                            minimum_free_vram_bytes=placement.minimum_free_vram_bytes,
                            maximum_utilization_percent=(
                                placement.maximum_idle_utilization_percent
                            ),
                            test_only_max_wait_cycles=test_only_max_placement_wait_cycles,
                        )
                        heartbeat.update(state="LOADING")
                        heartbeat.flush()
                    heartbeat.require_current(self.stale_after)
                    load_record = dict(self.adapter.load())
                    json.dumps(load_record, allow_nan=False, sort_keys=True)
                    observed_load = next(
                        (
                            load_record[key]
                            for key in (
                                "synchronized_load_wall_seconds",
                                "bridge_load_wall_seconds",
                                "load_wall_seconds",
                            )
                            if key in load_record
                        ),
                        None,
                    )
                    if observed_load is None:
                        raise WorkerStopped("adapter load omitted measured wall seconds")
                    self.claims.record_load_observed(float(observed_load))
                    adapter_loaded = True
                    self.probe.require_safe(
                        minimum_free_vram_bytes=placement.post_load_reserve_bytes,
                        allowed_pids={os.getpid()},
                    )
                    heartbeat.update(state="RUNNING")

                    for shard_index, offset in enumerate(range(0, len(rows), 4)):
                        heartbeat.update(current_shard=shard_index, state="RUNNING")
                        shard_rows = rows[offset : offset + 4]
                        shard_terminals: list[dict[str, Any]] = []
                        for row in shard_rows:
                            heartbeat.require_current(self.stale_after)
                            request_sha = str(row["request_sha256"])
                            try:
                                self.probe.require_safe(
                                    minimum_free_vram_bytes=placement.post_load_reserve_bytes,
                                    allowed_pids={os.getpid()},
                                )
                                heartbeat.require_current(self.stale_after)
                                claim = self.claims.claim(
                                    row,
                                    metadata={
                                        "node": placement.node,
                                        "physical_gpu_id": placement.physical_gpu_id,
                                        "sequence": row["sequence"],
                                        "shard_index": shard_index,
                                    },
                                )
                            except HardCapReached:
                                terminal_state = "HARD_CAP_REACHED"
                                heartbeat.update(state=terminal_state)
                                heartbeat.flush()
                                raise
                            except PlacementBlocked:
                                terminal_state = "PLACEMENT_HEADROOM_BLOCKED"
                                heartbeat.update(state=terminal_state)
                                heartbeat.flush()
                                raise
                            claim_path = self.claims.claims_dir / f"{request_sha}.json"
                            claim_sha = hashlib.sha256(claim_path.read_bytes()).hexdigest()
                            last = self.ledger.transition(
                                request_sha,
                                "CLAIMED",
                                {
                                    "claim_sha256": claim_sha,
                                    "claimed_at_utc": claim["claimed_at_utc"],
                                    "model_id": self.model.model_id,
                                    "sequence": row["sequence"],
                                },
                            )
                            self.claims.assert_claimed(request_sha)
                            last = self.ledger.transition(
                                request_sha,
                                "CALL_STARTED",
                                {"started_at_utc": utc_now()},
                            )
                            last_ledger = last["ledger_row_sha256"]
                            heartbeat.update(
                                current_request_sha256=request_sha,
                                last_ledger_sha256=last_ledger,
                            )
                            heartbeat.flush()
                            staging = self.run_dir / "staging" / request_sha
                            staging.mkdir(parents=True, exist_ok=False)
                            try:
                                staged = self.adapter.generate(row, staging, ())
                                if not isinstance(staged, StagedGeneration):
                                    raise TypeError("adapter did not return StagedGeneration")
                                self.claims.record_call_observed(
                                    request_sha, staged.synchronized_wall_seconds
                                )
                                commit = commit_generation(
                                    self.run_dir / "artifacts",
                                    row,
                                    staged,
                                    expected_sample_rate=self.model.expected_sample_rate,
                                    expected_channels=self.model.expected_channels,
                                )
                                last = self.ledger.transition(
                                    request_sha,
                                    "SUCCEEDED",
                                    {
                                        "actual_nfe": staged.actual_nfe,
                                        "commit": commit,
                                        "finished_at_utc": utc_now(),
                                        "peak_allocated_bytes": staged.peak_allocated_bytes,
                                        "peak_reserved_bytes": staged.peak_reserved_bytes,
                                        "synchronized_wall_seconds": (
                                            staged.synchronized_wall_seconds
                                        ),
                                    },
                                )
                                last_ledger = last["ledger_row_sha256"]
                                completed += 1
                                cumulative_seconds += staged.synchronized_wall_seconds
                                peak_allocated = max(peak_allocated, staged.peak_allocated_bytes)
                                peak_reserved = max(peak_reserved, staged.peak_reserved_bytes)
                                shard_terminals.append(
                                    {"request_sha256": request_sha, "state": "SUCCEEDED"}
                                )
                                heartbeat.update(
                                    completed=completed,
                                    cumulative_synchronized_gpu_seconds=cumulative_seconds,
                                    current_request_sha256=None,
                                    last_ledger_sha256=last_ledger,
                                    peak_allocated_bytes=peak_allocated,
                                    peak_reserved_bytes=peak_reserved,
                                )
                            except BaseException as exc:
                                failed += 1
                                failure = self.ledger.transition(
                                    request_sha,
                                    "FAILED",
                                    {
                                        "error_message": str(exc)[:2000],
                                        "error_type": type(exc).__name__,
                                        "failed_at_utc": utc_now(),
                                        "stage": "ADAPTER_OR_ARTIFACT_COMMIT",
                                    },
                                )
                                last_ledger = failure["ledger_row_sha256"]
                                terminal_state = "FAILED_STOPPED"
                                heartbeat.update(
                                    current_request_sha256=None,
                                    failed=failed,
                                    last_ledger_sha256=last_ledger,
                                    state=terminal_state,
                                )
                                heartbeat.flush()
                                raise WorkerStopped(
                                    f"request {request_sha} failed and remains non-retryable"
                                ) from exc

                        is_last = offset + 4 == len(rows)
                        boundary_state = "COMPLETE" if is_last else "RUNNING"
                        heartbeat.update(state=boundary_state)
                        snapshot = heartbeat.snapshot(
                            self.worker_root / "heartbeat-snapshots", shard_index
                        )
                        shard_record = {
                            "completed_at_utc": utc_now(),
                            "first_batch": shard_index == 0,
                            "heartbeat_snapshot": str(snapshot),
                            "ledger_tail_sha256": last_ledger,
                            "model_id": self.model.model_id,
                            "rows": shard_terminals,
                            "schema_version": 1,
                            "shard_index": shard_index,
                            "status": (
                                "FIRST_LEDGERED_BATCH" if shard_index == 0 else "SHARD_COMPLETE"
                            ),
                        }
                        _write_json_exclusive(
                            self.worker_root / "shards" / f"shard-{shard_index:06d}.json",
                            shard_record,
                        )
                        completed_shards.append(shard_record)
                        if (
                            test_only_stop_after_shards is not None
                            and len(completed_shards) >= test_only_stop_after_shards
                        ):
                            return {
                                "completed_calls": completed,
                                "completed_shards": completed_shards,
                                "status": "TEST_ONLY_STOP_AFTER_SHARD",
                            }
                    terminal_state = "COMPLETE"
                    heartbeat.update(state=terminal_state)
                    heartbeat.flush()
                    return {
                        "completed_calls": completed,
                        "completed_shards": completed_shards,
                        "status": terminal_state,
                    }
            except PlacementBlocked:
                terminal_state = "PLACEMENT_HEADROOM_BLOCKED"
                heartbeat.update(state=terminal_state)
                heartbeat.flush()
                raise
            except HardCapReached:
                terminal_state = "HARD_CAP_REACHED"
                heartbeat.update(state=terminal_state)
                heartbeat.flush()
                raise
            except BaseException:
                if terminal_state not in {"FAILED_STOPPED", "HARD_CAP_REACHED"}:
                    terminal_state = "FAILED_STOPPED"
                heartbeat.update(state=terminal_state)
                heartbeat.flush()
                raise
            finally:
                if adapter_loaded:
                    self.adapter.close()

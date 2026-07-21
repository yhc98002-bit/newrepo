from __future__ import annotations

import json
import os
import runpy
from pathlib import Path
from typing import Any

import pytest

import state_capture.sa3_worker as worker_module
from benchmark_core.heartbeat import validate_heartbeat
from benchmark_core.ledger import validate_ledger
from benchmark_core.placement import PlacementUnavailable
from state_capture.sa3_artifacts import StagedPrefixGroup, StagedResume
from state_capture.sa3_claims import (
    StateAlreadyClaimed,
    StateClaimStore,
    StateHardCapReached,
)
from state_capture.sa3_contract import (
    ACTIONS,
    AXES,
    EXPECTED_ACTION_ROWS,
    EXPECTED_GROUPS,
    EXPECTED_UNITS,
    LANE_CLOSED_STATUS,
    RESTART_LABEL,
    SA3_MODEL_ID,
    _build_rows,
    load_sa3_state_capture_config,
)
from state_capture.sa3_engine import require_post_load_cuda_reserve
from state_capture.sa3_launcher import (
    StateLaunchAuthorizationError,
    verify_state_decision,
)
from state_capture.sa3_worker import SA3StateWorker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sa3_state_capture_v2.json"


@pytest.fixture(scope="module")
def frozen_contract() -> tuple[Any, list[dict], list[dict], list[dict], dict]:
    config = load_sa3_state_capture_config(CONFIG_PATH, repo_root=ROOT)
    units, groups, actions, folds = _build_rows(config)
    return config, units, groups, actions, folds


def test_frozen_state_contract_has_exact_units_actions_folds_budget_and_placement(
    frozen_contract: tuple[Any, list[dict], list[dict], list[dict], dict],
) -> None:
    config, units, groups, actions, folds = frozen_contract

    assert (len(units), len(groups), len(actions)) == (
        EXPECTED_UNITS,
        EXPECTED_GROUPS,
        EXPECTED_ACTION_ROWS,
    )
    assert config.checkpoint_completed_steps == (13, 25, 38)
    assert config.placement.allowed_nodes == ("an12",)
    assert config.placement.allowed_physical_gpu_ids == (4, 5, 6, 7)
    assert config.placement.maximum_parallel_replicas == 4
    assert config.placement.tp_width == config.placement.replica_count_per_worker == 1
    assert config.initial_gpu_seconds_cap == pytest.approx(
        EXPECTED_GROUPS
        * (config.prefix_group_reservation_seconds + 3 * config.resume_unit_reservation_seconds),
        abs=1e-8,
    )
    assert {row["authorization_status"] for row in units} == {LANE_CLOSED_STATUS}
    assert {row["preview_source_request_sha256"] for row in units} == {
        row["parent_request_sha256"] for row in units
    }
    assert {row["action"] for row in actions} == set(ACTIONS)
    assert {row["outcome_label"] for row in actions if row["action"].startswith("RESTART_")} == {
        RESTART_LABEL
    }
    assert len(folds["rows"]) == 36
    for replica in range(4):
        shard = [row for row in groups if (row["group_sequence"] - 1) % 4 == replica]
        assert len(shard) == 36
    assert {row["axis"] for row in groups} == set(AXES)


def test_d0030_authorization_requires_exact_budget_hash_and_an12_gpu_set(
    tmp_path: Path,
    frozen_contract: tuple[Any, list[dict], list[dict], list[dict], dict],
) -> None:
    config = frozen_contract[0]
    cap = config.raw["execution"]["state_gpu_budget"]["initial_gpu_seconds_cap"]
    block = "\n".join(
        (
            "## D-0030 — SA3 state capture",
            "SA3_STATE_CAPTURE_INITIAL_AUTHORIZED = YES",
            "NO_AUTOMATIC_RETRY = YES",
            "SA3_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED = NO",
            f"STATE_CONFIG = configs/{config.source_path.name}",
            f"STATE_CONFIG_SHA256 = {config.source_sha256}",
            f"INITIAL_STATE_GPU_SECONDS_CAP = {json.dumps(cap)}",
            f"D0020_RESULT_SHA256 = {config.d0020_result_sha256}",
            "STATE_PLACEMENT = an12:[4,5,6,7]",
            "STATE_MAX_PARALLEL_REPLICAS = 4",
        )
    )
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(block + "\n", encoding="utf-8")

    observed, digest = verify_state_decision(decisions, decision_id="D-0030", config=config)
    assert observed == block + "\n"
    assert len(digest) == 64

    decisions.write_text(block.replace("an12:[4,5,6,7]", "an29:[4,5,6,7]") + "\n")
    with pytest.raises(StateLaunchAuthorizationError, match="exact bindings"):
        verify_state_decision(decisions, decision_id="D-0030", config=config)


def test_shared_claim_store_is_no_retry_and_stops_after_observed_cap_overrun(
    tmp_path: Path,
    frozen_contract: tuple[Any, list[dict], list[dict], list[dict], dict],
) -> None:
    config, units, groups, _, _ = frozen_contract
    store = StateClaimStore(
        tmp_path / "claims",
        gpu_seconds_cap=config.initial_gpu_seconds_cap,
        prefix_group_reservation_seconds=config.prefix_group_reservation_seconds,
        resume_unit_reservation_seconds=config.resume_unit_reservation_seconds,
    )
    group = groups[0]
    identity = group["group_request_sha256"]
    store.claim(group, kind="PREFIX_GROUP", replica_index=0, physical_gpu_id=4)
    with pytest.raises(StateAlreadyClaimed):
        store.claim(group, kind="PREFIX_GROUP", replica_index=1, physical_gpu_id=5)

    store.record_observed(
        identity,
        kind="PREFIX_GROUP",
        observed_gpu_seconds=config.initial_gpu_seconds_cap,
    )
    with pytest.raises(StateHardCapReached, match="cap"):
        store.claim(units[0], kind="RESUME_UNIT", replica_index=0, physical_gpu_id=4)
    usage = store.usage()
    assert usage["prefix_group_claims"] == 1
    assert usage["resume_unit_claims"] == 0
    assert usage["effective_gpu_seconds"] == config.initial_gpu_seconds_cap


def test_post_load_reserve_guard_fails_before_inference_without_cuda() -> None:
    observed = require_post_load_cuda_reserve(
        20_000_000_000,
        memory_info=lambda: (30_000_000_000, 80_000_000_000),
    )
    assert observed["free_vram_bytes"] == 30_000_000_000
    with pytest.raises(PlacementUnavailable, match="inference was not started"):
        require_post_load_cuda_reserve(
            20_000_000_000,
            memory_info=lambda: (19_999_999_999, 80_000_000_000),
        )


def test_supervisor_launch_requires_explicit_bounded_subset_or_all() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts/supervise_sa3_state_capture_v2.py"))
    select = namespace["_launch_replica_indices"]

    assert (
        select(
            launch=False,
            launch_all=False,
            requested=[],
            maximum_parallel_replicas=4,
        )
        == ()
    )
    assert select(
        launch=True,
        launch_all=False,
        requested=[0],
        maximum_parallel_replicas=4,
    ) == (0,)
    assert select(
        launch=True,
        launch_all=True,
        requested=[],
        maximum_parallel_replicas=4,
    ) == (0, 1, 2, 3)
    with pytest.raises(ValueError, match="exactly one"):
        select(
            launch=True,
            launch_all=False,
            requested=[],
            maximum_parallel_replicas=4,
        )
    with pytest.raises(ValueError, match="unique"):
        select(
            launch=True,
            launch_all=False,
            requested=[0, 0],
            maximum_parallel_replicas=4,
        )


class _FakeProbe:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def require_safe(self, **kwargs: Any) -> object:
        self.calls.append(dict(kwargs))
        return object()


class _FakeLease:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> _FakeLease:
        if self.held:
            raise RuntimeError("lease already held")
        self.held = True
        return self

    def release(self) -> None:
        self.held = False

    def __enter__(self) -> _FakeLease:
        return self if self.held else self.acquire()

    def __exit__(self, *_args: object) -> None:
        self.release()


class _FakeEngine:
    model_id = SA3_MODEL_ID

    def __init__(self) -> None:
        self.groups: list[str] = []
        self.units: list[str] = []
        self.close_count = 0

    def preflight(self) -> dict[str, str]:
        return {"status": "READY"}

    def load(self) -> dict[str, float]:
        return {"load_wall_seconds": 0.0}

    def capture_group(
        self, group: dict, _units: list[dict], staging_dir: Path
    ) -> StagedPrefixGroup:
        self.groups.append(group["group_request_sha256"])
        return StagedPrefixGroup(
            reference_terminal_path=staging_dir / "reference.wav",
            checkpoint_previews=(),
            actual_nfe=50,
            synchronized_gpu_seconds=1.0,
            peak_allocated_bytes=10,
            peak_reserved_bytes=20,
            conditioning_sha256="a" * 64,
        )

    def resume(self, unit: dict, _checkpoint_path: Path, staging_dir: Path) -> StagedResume:
        self.units.append(unit["lane_request_sha256"])
        return StagedResume(
            resumed_terminal_path=staging_dir / "terminal.wav",
            actual_nfe=50 - unit["checkpoint_completed_steps"],
            synchronized_gpu_seconds=1.0,
            peak_allocated_bytes=10,
            peak_reserved_bytes=20,
            child_pid=os.getpid() + 1,
        )

    def close(self) -> None:
        self.close_count += 1


def test_worker_runs_static_bounded_batches_with_shared_no_retry_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frozen_contract: tuple[Any, list[dict], list[dict], list[dict], dict],
) -> None:
    config, units, groups, _, _ = frozen_contract
    monkeypatch.setattr(
        worker_module,
        "commit_prefix_group",
        lambda *_args, **_kwargs: {"status": "COMMITTED"},
    )
    monkeypatch.setattr(
        worker_module,
        "commit_resume",
        lambda *_args, **_kwargs: {"status": "COMMITTED"},
    )
    engine = _FakeEngine()
    probe = _FakeProbe()
    worker = SA3StateWorker(
        config=config,
        run_dir=tmp_path,
        run_id="sa3-state-v2-test",
        git_commit="1" * 40,
        bundle_manifest_sha256="2" * 64,
        replica_index=0,
        physical_gpu_id=4,
        engine=engine,
        probe=probe,  # type: ignore[arg-type]
        lease=_FakeLease(),  # type: ignore[arg-type]
        placement_poll_seconds=0,
    )

    first = worker.run(units=units, groups=groups, max_new_groups=1)
    second = worker.run(units=units, groups=groups, max_new_groups=1)

    assert first["completed_groups"] == second["completed_groups"] == 1
    assert first["completed_units"] == second["completed_units"] == 3
    assert engine.groups == [
        groups[0]["group_request_sha256"],
        groups[4]["group_request_sha256"],
    ]
    assert len(engine.units) == 6
    assert engine.close_count == 2
    rows = validate_ledger(tmp_path / "state-ledger.jsonl")
    assert len(rows) == 24
    assert {row["request_state"] for row in rows} == {
        "CLAIMED",
        "CALL_STARTED",
        "SUCCEEDED",
    }
    heartbeat = validate_heartbeat(
        json.loads((tmp_path / "workers/replica-00/heartbeat.json").read_text(encoding="utf-8"))
    )
    assert heartbeat["state"] == "COMPLETE"
    assert heartbeat["physical_gpu_id"] == 4
    assert probe.calls
    assert {call["minimum_free_vram_bytes"] for call in probe.calls} == {
        config.placement.minimum_free_vram_bytes
    }

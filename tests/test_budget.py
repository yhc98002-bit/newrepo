"""CPU-only contract tests for the cross-process foundation execution budget."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import sa3_smoke.budget as budget_module
from sa3_smoke.budget import (
    ENV_CLAIM_PATH,
    ENV_LEDGER_PATH,
    ENV_LOCK_PATH,
    ENV_SMOKE,
    ENV_STATE_PATH,
    BudgetedStableAudioModel,
    BudgetExceeded,
    ExecutionBudget,
    smoke_context,
)


@pytest.fixture(autouse=True)
def clean_budget_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (ENV_STATE_PATH, ENV_LEDGER_PATH, ENV_LOCK_PATH, ENV_CLAIM_PATH, ENV_SMOKE):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    yield
    for name in (ENV_STATE_PATH, ENV_LEDGER_PATH, ENV_LOCK_PATH, ENV_CLAIM_PATH, ENV_SMOKE):
        os.environ.pop(name, None)


def initialize(tmp_path: Path) -> ExecutionBudget:
    run_root = tmp_path / "runs"
    run_dir = run_root / "immutable-run"
    run_dir.mkdir(parents=True)
    return ExecutionBudget.initialize(
        run_dir=run_dir,
        run_root=run_root,
        claim_identity={
            "repository_git_hash": "a" * 40,
            "configuration_sha256": "b" * 64,
            "protocol_sha256": "c" * 64,
            "decisions_sha256": "d" * 64,
            "seed_registry_sha256": "e" * 64,
        },
    )


def retained_artifact(root: Path, stem: str) -> dict[str, Any]:
    audio = root / f"{stem}.wav"
    provenance = root / f"{stem}.wav.provenance.json"
    audio.write_bytes(f"audio-{stem}".encode())
    provenance.write_text('{"label":"synthetic_model_output"}\n', encoding="utf-8")
    return {
        "path": str(audio.resolve()),
        "provenance_path": str(provenance.resolve()),
        "label": "synthetic_model_output",
        "sanity": {
            "pass": True,
            "sample_rate": 44_100,
            "channels": 2,
            "duration_seconds": 30.0,
            "decoded_waveform_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        },
    }


def record_call(
    budget: ExecutionBudget,
    root: Path,
    *,
    smoke: str,
    seed_id: str,
    seed: int,
    duration: float,
    batch_size: int,
    elapsed: float = 0.1,
) -> None:
    reservation = budget.reserve_call(
        smoke=smoke,
        seed_id=seed_id,
        seed=seed,
        duration_seconds=duration,
        batch_size=batch_size,
    )
    budget.complete_call(
        reservation,
        synchronized_gpu_wall_seconds=elapsed,
        succeeded=True,
        measurements={
            "backbone_forward_calls": 50,
            "wall_seconds": elapsed,
            "peak_allocated_bytes": 30_000,
            "peak_reserved_bytes": 40_000,
        },
    )
    artifacts = [
        retained_artifact(root, f"{reservation.call_id}-{index}") for index in range(batch_size)
    ]
    budget.finalize_latest_audio(artifacts, smoke=smoke)


def test_batch_four_consumes_four_generation_slots_and_cap_is_pre_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(budget_module, "MAX_GENERATIONS", 4)
    budget = initialize(tmp_path)
    reservation = budget.reserve_call(
        smoke="D",
        seed_id="S-0006",
        seed=73_193_006,
        duration_seconds=10.0,
        batch_size=4,
    )
    assert len(reservation.generation_ids) == 4
    assert budget.summary()["generation_slots_reserved"] == 4
    with pytest.raises(BudgetExceeded, match="MAX_GENERATIONS"):
        budget.reserve_call(
            smoke="A",
            seed_id="S-0001",
            seed=73_193_001,
            duration_seconds=30.0,
            batch_size=1,
        )


def test_clip_gpu_and_registered_seed_guards_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = initialize(tmp_path)
    with pytest.raises(BudgetExceeded, match="unregistered seed pair"):
        budget.reserve_call(
            smoke="A",
            seed_id="S-0001",
            seed=999,
            duration_seconds=30.0,
            batch_size=1,
        )
    with pytest.raises(BudgetExceeded, match="MAX_CLIP_SECONDS"):
        budget.reserve_call(
            smoke="A",
            seed_id="S-0001",
            seed=73_193_001,
            duration_seconds=30.01,
            batch_size=1,
        )
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    with pytest.raises(BudgetExceeded, match="MAX_GPUS"):
        budget.reserve_call(
            smoke="A",
            seed_id="S-0001",
            seed=73_193_001,
            duration_seconds=30.0,
            batch_size=1,
        )


def test_measured_time_cap_allows_current_atomic_evidence_then_blocks_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(budget_module, "MAX_GPU_SECONDS", 1.0)
    budget = initialize(tmp_path)
    reservation = budget.reserve_call(
        smoke="A",
        seed_id="S-0001",
        seed=73_193_001,
        duration_seconds=30.0,
        batch_size=1,
    )
    budget.complete_call(
        reservation,
        synchronized_gpu_wall_seconds=1.0,
        succeeded=True,
    )
    rows = budget.finalize_latest_audio(
        [retained_artifact(tmp_path, "cap-current-output")], smoke="A"
    )
    assert len(rows) == 1
    assert Path(rows[0]["audio_path"]).is_file()
    with pytest.raises(BudgetExceeded, match="measured GPU wall cap reached"):
        budget.reserve_call(
            smoke="A",
            seed_id="S-0001",
            seed=73_193_001,
            duration_seconds=30.0,
            batch_size=1,
        )


def test_residency_upper_bound_is_a_second_pre_call_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [0]
    monkeypatch.setattr(budget_module.time, "monotonic_ns", lambda: now[0])
    monkeypatch.setattr(budget_module, "MAX_GPU_SECONDS", 1.0)
    budget = initialize(tmp_path)
    now[0] = 1_000_000_000
    with pytest.raises(BudgetExceeded, match="residency upper bound"):
        budget.reserve_call(
            smoke="A",
            seed_id="S-0001",
            seed=73_193_001,
            duration_seconds=30.0,
            batch_size=1,
        )
    summary = budget.summary()
    assert summary["residency_cap_reached"] is True
    assert summary["gpu_residency_upper_bound_seconds"] == 1.0


def test_batch_ledger_has_four_hash_chained_registered_seed_rows(tmp_path: Path) -> None:
    budget = initialize(tmp_path)
    record_call(
        budget,
        tmp_path,
        smoke="D",
        seed_id="S-0006",
        seed=73_193_006,
        duration=10.0,
        batch_size=4,
        elapsed=0.4,
    )
    rows = [json.loads(line) for line in budget.paths.ledger.read_text().splitlines()]
    assert len(rows) == 4
    assert [row["generation_id"] for row in rows] == [
        "generation-01",
        "generation-02",
        "generation-03",
        "generation-04",
    ]
    assert {(row["seed_id"], row["seed"]) for row in rows} == {("S-0006", 73_193_006)}
    assert rows[0]["previous_row_sha256"] is None
    for previous, current in zip(rows, rows[1:], strict=False):
        assert current["previous_row_sha256"] == previous["row_sha256"]
    assert all(row["sanity"]["pass"] is True for row in rows)


def test_proxy_synchronizes_and_records_each_official_generate_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = initialize(tmp_path)
    clock = iter((10.0, 10.25))
    monkeypatch.setattr(budget_module.time, "perf_counter", lambda: next(clock))

    class FakeDevice:
        type = "cuda"

        def __str__(self) -> str:
            return "cuda:0"

    class FakeCuda:
        def __init__(self) -> None:
            self.sync_count = 0

        def is_available(self) -> bool:
            return True

        def device_count(self) -> int:
            return 1

        def synchronize(self, _device: FakeDevice) -> None:
            self.sync_count += 1

        def reset_peak_memory_stats(self, _device: FakeDevice) -> None:
            return None

        def memory_allocated(self, _device: FakeDevice) -> int:
            return 10_000

        def memory_reserved(self, _device: FakeDevice) -> int:
            return 20_000

        def max_memory_allocated(self, _device: FakeDevice) -> int:
            return 30_000

        def max_memory_reserved(self, _device: FakeDevice) -> int:
            return 40_000

        def get_device_name(self, _device: FakeDevice) -> str:
            return "NVIDIA A800 CPU-only mock"

    fake_cuda = FakeCuda()
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]
    fake_torch.device = lambda _value: FakeDevice()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    class HookHandle:
        def __init__(self, hooks: list[Any], callback: Any) -> None:
            self.hooks = hooks
            self.callback = callback

        def remove(self) -> None:
            self.hooks.remove(self.callback)

    class Backbone:
        def __init__(self) -> None:
            self.hooks: list[Any] = []

        def register_forward_pre_hook(self, callback: Any) -> HookHandle:
            self.hooks.append(callback)
            return HookHandle(self.hooks, callback)

        def invoke(self) -> None:
            for callback in tuple(self.hooks):
                callback(self, ())

    class Official:
        device = "cuda:0"

        def __init__(self) -> None:
            self.dit = Backbone()

        def generate(self, **kwargs: Any) -> str:
            for _ in range(kwargs["steps"]):
                self.dit.invoke()
            return "generated-output"

    with smoke_context("A"):
        output = BudgetedStableAudioModel(Official()).generate(
            prompt=(
                "A steady instrumental electronic music loop with drums, bass, and warm "
                "synthesizer, clean studio recording, 120 BPM"
            ),
            negative_prompt="low quality, clipping, silence",
            duration=30.0,
            steps=50,
            cfg_scale=7.0,
            seed=73_193_001,
            batch_size=1,
            sampler_type="euler",
            duration_padding_sec=6.0,
            truncate_output_to_duration=True,
            chunked_decode=True,
            disable_tqdm=True,
        )
    assert output == "generated-output"
    assert fake_cuda.sync_count == 2
    summary = budget.summary()
    assert summary["cumulative_synchronized_gpu_wall_seconds"] == 0.25
    measured = summary["smoke_measurements"]["A"]
    assert measured["actual_backbone_forward_calls"] == 50
    assert measured["peak_allocated_bytes"] == 30_000
    assert measured["peak_reserved_bytes"] == 40_000


def test_smoke_e_parent_and_three_child_calls_share_exact_accounting(tmp_path: Path) -> None:
    budget = initialize(tmp_path)
    record_call(
        budget,
        tmp_path,
        smoke="E",
        seed_id="S-0007",
        seed=73_193_007,
        duration=30.0,
        batch_size=1,
    )
    parent_pid = os.getpid()
    code = """
import json, os, sys
from pathlib import Path
from sa3_smoke.budget import ExecutionBudget
b = ExecutionBudget.from_environment()
r = b.reserve_call(smoke='E', seed_id='S-0007', seed=73193007, duration_seconds=30.0, batch_size=1)
b.complete_call(r, synchronized_gpu_wall_seconds=0.1, succeeded=True)
root = Path(sys.argv[1]); stem = sys.argv[2]
wav = root / (stem + '.wav'); prov = root / (stem + '.wav.provenance.json')
wav.write_bytes(stem.encode()); prov.write_text('{\"label\":\"synthetic_model_output\"}\\n')
b.finalize_latest_audio(
    [{
        'path': str(wav.resolve()),
        'provenance_path': str(prov.resolve()),
        'sanity': {'pass': True},
    }],
    smoke='E',
)
print(json.dumps({'pid': os.getpid(), 'call_id': r.call_id}))
"""
    child_pids: list[int] = []
    for index in range(3):
        completed = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), f"e-child-{index}"],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        child_pids.append(json.loads(completed.stdout)["pid"])
    summary = budget.summary()
    assert summary["calls_by_smoke"]["E"] == 4
    assert summary["generations_by_smoke"]["E"] == 4
    assert summary["seed_calls_by_smoke"]["E"] == {"S-0007": 4}
    assert summary["cumulative_synchronized_gpu_wall_seconds"] == pytest.approx(0.4)
    rows = [json.loads(line) for line in budget.paths.ledger.read_text().splitlines()]
    assert len(rows) == 4
    assert rows[0]["process_id"] == parent_pid
    assert [row["process_id"] for row in rows[1:]] == child_pids


def test_exact_plan_final_summary_has_11_calls_and_14_outputs(tmp_path: Path) -> None:
    budget = initialize(tmp_path)
    plan = [
        ("A", "S-0001", 73_193_001, 30.0, 1),
        ("A", "S-0001", 73_193_001, 30.0, 1),
        ("B", "S-0002", 73_193_002, 30.0, 1),
        ("C", "S-0003", 73_193_003, 30.0, 1),
        ("C", "S-0004", 73_193_004, 30.0, 1),
        ("D", "S-0005", 73_193_005, 30.0, 1),
        ("D", "S-0006", 73_193_006, 10.0, 4),
        ("E", "S-0007", 73_193_007, 30.0, 1),
        ("E", "S-0007", 73_193_007, 30.0, 1),
        ("E", "S-0007", 73_193_007, 30.0, 1),
        ("E", "S-0007", 73_193_007, 30.0, 1),
    ]
    for smoke, seed_id, seed, duration, batch_size in plan:
        record_call(
            budget,
            tmp_path,
            smoke=smoke,
            seed_id=seed_id,
            seed=seed,
            duration=duration,
            batch_size=batch_size,
        )
    summary = budget.finalize()
    assert summary["status"] == "PASS"
    assert summary["official_generate_calls_reserved"] == 11
    assert summary["generation_slots_reserved"] == 14
    assert summary["successful_model_calls"] == 11
    assert summary["generated_outputs"] == 14
    assert summary["ledgered_outputs"] == 14
    assert summary["cumulative_synchronized_gpu_wall_seconds"] == pytest.approx(1.1)
    assert summary["exact_plan_completed"] is True


def test_external_claim_prevents_second_run_without_later_decision(tmp_path: Path) -> None:
    first = initialize(tmp_path)
    assert first.paths.claim.parent == tmp_path / "runs"
    second_run = tmp_path / "runs" / "second-immutable-run"
    second_run.mkdir()
    with pytest.raises(BudgetExceeded, match="already exists"):
        ExecutionBudget.initialize(
            run_dir=second_run,
            run_root=tmp_path / "runs",
            claim_identity={"repository_git_hash": "f" * 40},
        )


def test_failed_reserved_generation_gets_terminal_hash_chained_ledger_row(
    tmp_path: Path,
) -> None:
    budget = initialize(tmp_path)
    reservation = budget.reserve_call(
        smoke="A",
        seed_id="S-0001",
        seed=73_193_001,
        duration_seconds=30.0,
        batch_size=1,
    )
    budget.complete_call(
        reservation,
        synchronized_gpu_wall_seconds=0.1,
        succeeded=False,
        measurements={"backbone_forward_calls": 0, "wall_seconds": 0.1},
        error="fixture failure",
    )

    summary = budget.finalize()

    assert summary["status"] == "FAIL"
    assert summary["terminal_failure_ledger_rows"] == 1
    rows = [json.loads(line) for line in budget.paths.ledger.read_text().splitlines()]
    assert rows[0]["generation_id"] == "generation-01"
    assert rows[0]["status"] == "MODEL_CALL_FAILED"
    assert rows[0]["audio_path"] is None
    assert rows[0]["row_sha256"]

from __future__ import annotations

from pathlib import Path

import pytest

from scoring.feature_worker import PostLoadHeadroomBlocked, require_post_load_headroom
from scoring.gpu_guard import acquire_idle_gpu, inspect_idle_gpus
from scoring.storage import ImmutableRun


class _Cuda:
    def __init__(self, free: int, total: int = 80_000_000_000) -> None:
        self.free = free
        self.total = total

    def mem_get_info(self) -> tuple[int, int]:
        return self.free, self.total


class _Torch:
    def __init__(self, free: int) -> None:
        self.cuda = _Cuda(free)


def _guard(tmp_path: Path) -> dict[str, object]:
    return {
        "candidates": [{"node": "an12", "physical_gpu_ids": [4, 5]}],
        "excluded_generation_allocations": [
            {"allocation_id": "live-generation", "node": "an12", "physical_gpu_id": 4}
        ],
        "generation_lock_roots": [str(tmp_path / "generation-locks")],
        "maximum_idle_utilization_percent": 5,
        "minimum_free_vram_bytes": 60_000_000_000,
        "policy": "QUEUE_DONT_PREEMPT",
        "required_gpu_name_substring": "A800",
        "scoring_lock_root": str(tmp_path / "scoring-locks"),
    }


def test_gpu_guard_excludes_generation_and_never_preempts(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...]) -> str:
        commands.append(tuple(command))
        if "--query-compute-apps=gpu_uuid,pid,used_gpu_memory" in command:
            return ""
        assert "--id=5" in command
        return "5, GPU-safe, NVIDIA A800, 70000, 80000, 0\n"

    observed = inspect_idle_gpus(_guard(tmp_path), runner=runner, hostname="an12")
    assert observed["selected_gpu_id"] == 5
    assert observed["observations"][0]["reason"].startswith(
        "EXCLUDED_GENERATION_ALLOCATION"
    )
    lease, decision = acquire_idle_gpu(_guard(tmp_path), runner=runner, hostname="an12")
    assert lease is not None and decision["status"] == "IDLE_GPU_LEASED"
    lease.release()
    flat = " ".join(part for command in commands for part in command)
    assert all(token not in flat for token in ("kill", "reset", "mig", "drain"))


def test_post_load_reserve_blocks_before_row_zero() -> None:
    with pytest.raises(PostLoadHeadroomBlocked) as caught:
        require_post_load_headroom(20_000_000_000, torch_module=_Torch(19_999_999_999))
    assert caught.value.free_bytes == 19_999_999_999
    assert require_post_load_headroom(
        20_000_000_000, torch_module=_Torch(20_000_000_000)
    )["free_vram_bytes_after_load"] == 20_000_000_000


def test_immutable_outputs_ledger_and_heartbeat_are_no_clobber(tmp_path: Path) -> None:
    run = ImmutableRun(tmp_path / "run", create=True)
    run.write_json("tables/table.json", {"status": "PASS"})
    with pytest.raises(FileExistsError):
        run.write_json("tables/table.json", {"status": "MUTATED"})
    first = run.ledger.append("FIRST", {"value": 1})
    second = run.ledger.append("SECOND", {"value": 2})
    assert second["previous_event_sha256"] == first["event_sha256"]
    heartbeat = run.heartbeat("RUNNING", {"completed": 1})
    assert heartbeat["payload"]["state"] == "RUNNING"
    assert len(list((tmp_path / "run" / "heartbeats").glob("[0-9]*.json"))) == 1

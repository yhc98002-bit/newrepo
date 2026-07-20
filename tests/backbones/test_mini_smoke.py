from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backbones.contracts import BackbonePreflight, GenerationMeasurement, GenerationRequest
from backbones.io import copy_file_exclusive
from backbones.mini_smoke import (
    MiniSmokeExecutionError,
    MiniSmokeJob,
    MiniSmokePlanError,
    RunContext,
    run_mini_smoke,
)
from sa3_smoke.artifacts import validate_adjacent_provenance
from sa3_smoke.audio import audio_sanity, save_float_wav_exclusive


class FakeAdapter:
    logical_name = "cpu-fake-backbone"
    model_id = "test/cpu-fake"
    config_sha256 = "a" * 64
    license_identifier = "test-only"

    def __init__(self) -> None:
        self.calls = 0

    def preflight(self) -> BackbonePreflight:
        return BackbonePreflight(
            status="READY_FOR_MINI_SMOKE",
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={"source": {"revision": "b" * 40}},
        )

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        self.calls += 1
        sample_rate = 8000
        frames = round(request.duration_seconds * sample_rate)
        phase = np.arange(frames, dtype=np.float32) / sample_rate
        mono = 0.05 * np.sin(2 * np.pi * 220 * phase)
        stereo = np.stack([mono, mono], axis=1)
        save_float_wav_exclusive(request.output_path, stereo, sample_rate)
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=sample_rate,
            requested_steps=3,
            actual_nfe=3,
            wall_seconds=0.125,
            peak_allocated_bytes=1024,
            peak_reserved_bytes=2048,
            metadata={"fake": True},
        )


def _context() -> RunContext:
    return RunContext(
        run_id="b2-cpu-fake-001",
        command="pytest CPU fake adapter",
        git_commit="c" * 40,
        node="cpu-test",
        gpu_ids=("fake0",),
        placement_justification="CPU fake validates orchestration only; no GPU/model endpoint.",
        package_freeze_sha256="d" * 64,
    )


def _request(run_dir: Path, index: int = 0) -> GenerationRequest:
    return GenerationRequest(
        prompt_id=f"p-{index}",
        prompt="A CPU fake sine wave",
        seed_id=f"S-TEST-{index}",
        seed=index,
        duration_seconds=0.25,
        output_path=run_dir / "audio" / f"clip-{index}.wav",
    )


def test_cpu_fake_runner_writes_measured_provenance_and_sanity(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    adapter = FakeAdapter()
    result = run_mini_smoke(
        [MiniSmokeJob(adapter=adapter, request=_request(run_dir))],
        run_dir=run_dir,
        context=_context(),
        require_one_visible_gpu=False,
    )
    assert adapter.calls == 1
    assert result["status"] == "PASS"
    assert result["measured_cost_rows"] == 1
    row = result["rows"][0]
    assert row["cost_status"] == "MEASURED"
    assert row["actual_nfe"] == 3
    output = run_dir / "audio" / "clip-0.wav"
    assert audio_sanity(
        output,
        0.25,
        expected_sample_rate=8000,
        expected_channels=2,
    )["pass"]
    assert validate_adjacent_provenance(output)["model_revision"] == "b" * 40
    ledger = (run_dir / "generation_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 1
    assert json.loads(ledger[0])["row_sha256"] == result["ledger_tail_sha256"]


def test_cap_violation_is_rejected_before_artifacts_or_calls(tmp_path: Path) -> None:
    run_dir = tmp_path / "over-cap"
    adapter = FakeAdapter()
    jobs = [MiniSmokeJob(adapter=adapter, request=_request(run_dir, index)) for index in range(11)]
    with pytest.raises(MiniSmokePlanError, match="cap is 10"):
        run_mini_smoke(
            jobs,
            run_dir=run_dir,
            context=_context(),
            require_one_visible_gpu=False,
        )
    assert adapter.calls == 0
    assert not run_dir.exists()


def test_run_and_copy_never_clobber(tmp_path: Path) -> None:
    run_dir = tmp_path / "existing"
    run_dir.mkdir()
    sentinel = run_dir / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    adapter = FakeAdapter()
    with pytest.raises(FileExistsError):
        run_mini_smoke(
            [MiniSmokeJob(adapter=adapter, request=_request(run_dir))],
            run_dir=run_dir,
            context=_context(),
            require_one_visible_gpu=False,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert adapter.calls == 0

    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"new")
    destination.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        copy_file_exclusive(source, destination)
    assert destination.read_bytes() == b"old"


def test_failed_fake_call_has_terminal_result_and_no_retry(tmp_path: Path) -> None:
    class FailingAdapter(FakeAdapter):
        def generate(self, request: GenerationRequest) -> GenerationMeasurement:
            self.calls += 1
            raise RuntimeError("synthetic endpoint failure")

    run_dir = tmp_path / "failed"
    adapter = FailingAdapter()
    with pytest.raises(MiniSmokeExecutionError, match="ledgered without retry"):
        run_mini_smoke(
            [MiniSmokeJob(adapter=adapter, request=_request(run_dir))],
            run_dir=run_dir,
            context=_context(),
            require_one_visible_gpu=False,
        )
    assert adapter.calls == 1
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "FAIL_ESCALATED"
    assert result["generation_count"] == 1
    assert result["measured_cost_rows"] == 0
    assert result["rows"][0]["status"] == "MODEL_CALL_FAILED"

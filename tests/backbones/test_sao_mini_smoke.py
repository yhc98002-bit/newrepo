from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import backbones.sao_mini_smoke as smoke_module
from backbones.contracts import (
    BackbonePreflight,
    GenerationMeasurement,
    GenerationRequest,
    sha256_file,
)
from backbones.mini_smoke import RunContext
from backbones.sao_mini_smoke import SaoMiniSmokeError, run_sao_mini_smoke
from sa3_smoke.audio import audio_sanity, save_float_wav_exclusive


class FakeSao:
    logical_name = "stable-audio-open-1.0"
    model_id = "stabilityai/stable-audio-open-1.0"
    config_sha256 = "a" * 64
    license_identifier = "test-license"

    def __init__(self, *, break_repro: bool = False) -> None:
        self.calls = 0
        self.break_repro = break_repro

    def preflight(self) -> BackbonePreflight:
        return BackbonePreflight(
            status="READY_FOR_MINI_SMOKE",
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={"receipt": {"resolved_provider_revision": "b" * 40}},
        )

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        self.calls += 1
        value = request.seed + (self.calls if self.break_repro else 0)
        samples = np.full((2, 32), (value % 100) / 1000, dtype=np.float32)
        save_float_wav_exclusive(request.output_path, samples, 44_100, channels_first=True)
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=44_100,
            requested_steps=100,
            actual_nfe=100,
            wall_seconds=float(self.calls),
            peak_allocated_bytes=1024,
            peak_reserved_bytes=2048,
            metadata={"load_wall_seconds": 10.0},
        )


def _context() -> RunContext:
    return RunContext(
        run_id="run",
        command="pytest fake SAO mini smoke",
        git_commit="c" * 40,
        node="cpu-test",
        gpu_ids=("fake0",),
        placement_justification="CPU fake orchestration only; no model endpoint.",
        package_freeze_sha256="d" * 64,
    )


def _requests(run: Path) -> list[GenerationRequest]:
    values = [
        (prompt_id, prompt, seed_id, seed)
        for (prompt_id, prompt), (seed_id, seed) in zip(
            smoke_module.EXPECTED_PROMPTS,
            smoke_module.EXPECTED_SEEDS,
            strict=True,
        )
    ]
    return [
        GenerationRequest(
            prompt_id=prompt_id,
            prompt=prompt,
            seed_id=seed_id,
            seed=seed,
            duration_seconds=30,
            output_path=run / "audio" / f"call-{index:02d}.wav",
        )
        for index, (prompt_id, prompt, seed_id, seed) in enumerate(values)
    ]


def _fake_sanity(path: Path, _requested: float) -> dict[str, object]:
    digest = sha256_file(path)
    return {
        "pass": True,
        "decoded_waveform_sha256": digest,
        "duration_seconds": 30.0,
        "duration_policy": {"pass": True, "tolerance_seconds": 0.25},
    }


def test_three_call_smoke_hashes_repro_and_emits_measured_core_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke_module, "_duration_adjudicated_sanity", _fake_sanity)
    run = tmp_path / "run"
    adapter = FakeSao()
    result = run_sao_mini_smoke(
        adapter,
        _requests(run),
        run_dir=run,
        context=_context(),
        require_visible_gpu=False,
    )
    assert adapter.calls == 3
    assert result["status"] == "PASS_MEASURED_READY"
    assert result["reproducibility_hash_pass"] is True
    assert result["cost_calibration"] == {
        "cost_status": "MEASURED",
        "cold_plus_first_seconds": 11.0,
        "resident_unit_seconds": 3.0,
        "scheduled_core_calls": 1536,
        "gpu_seconds_cap": 9221.0,
        "gpu_hours_cap": 9221.0 / 3600,
        "arithmetic_rule": "c=L0+W0; u=max(W1,W2); cap=c+1535*(2*u)",
    }
    rows = [
        json.loads(line)
        for line in (run / "generation-ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 3
    assert rows[0]["previous_row_sha256"] == "0" * 64
    assert rows[1]["previous_row_sha256"] == rows[0]["row_sha256"]
    assert all(row["cost_status"] == "MEASURED" for row in rows)


def test_repro_hash_mismatch_is_terminal_and_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke_module, "_duration_adjudicated_sanity", _fake_sanity)
    run = tmp_path / "run"
    adapter = FakeSao(break_repro=True)
    with pytest.raises(SaoMiniSmokeError, match="reproducibility"):
        run_sao_mini_smoke(
            adapter,
            _requests(run),
            run_dir=run,
            context=_context(),
            require_visible_gpu=False,
        )
    assert adapter.calls == 3
    terminal = json.loads(
        (run / "sao-mini-smoke-terminal.json").read_text(encoding="utf-8")
    )
    assert terminal["status"] == "FAILED_STOPPED_NO_RETRY"
    assert terminal["no_retry"] is True
    assert terminal["reproducibility_hash_pass"] is False


def test_duration_adjudication_accepts_only_sample_count_quantization(tmp_path: Path) -> None:
    frames = 1_318_590  # 29.9 s at 44.1 kHz, inside the 0.25 s policy.
    phase = np.arange(frames, dtype=np.float32) / 44_100
    mono = 0.05 * np.sin(2 * np.pi * 220 * phase)
    path = tmp_path / "quantized.wav"
    save_float_wav_exclusive(path, np.stack([mono, mono], axis=1), 44_100)
    from sa3_smoke.artifacts import write_adjacent_provenance

    write_adjacent_provenance(
        path,
        {
            "label": "synthetic_model_output",
            "created_at_utc": "2026-07-22T00:00:00Z",
            "creating_command": "pytest",
            "run_id": "duration-test",
            "source_ids": ["fixture"],
            "model_revision": "a" * 40,
            "license_identifier": "test",
            "transformation": "fixture",
        },
    )
    result = smoke_module._duration_adjudicated_sanity(path, 30.0)
    assert result["pass"] is True
    assert result["exact_sample_count_pass"] is False
    assert result["duration_policy"]["pass"] is True


def test_decoded_waveform_hash_ignores_float_wav_peak_chunk_metadata(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"
    samples = np.full((32, 2), 0.01, dtype=np.float32)
    save_float_wav_exclusive(first_path, samples, 44_100)
    save_float_wav_exclusive(second_path, samples, 44_100)
    payload = bytearray(second_path.read_bytes())
    peak = payload.index(b"PEAK")
    payload[peak + 12 : peak + 16] = b"\x01\x02\x03\x04"
    second_path.write_bytes(payload)

    first = audio_sanity(first_path, 32 / 44_100, require_provenance=False)
    second = audio_sanity(second_path, 32 / 44_100, require_provenance=False)
    assert first["file_sha256"] != second["file_sha256"]
    assert first["decoded_waveform_sha256"] == second["decoded_waveform_sha256"]

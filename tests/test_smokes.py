"""CPU-only contract tests for official-generation smokes A--D."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from sa3_smoke.artifacts import validate_adjacent_provenance
from sa3_smoke.smokes import (
    BASE_BATCH4_PROMPTS,
    BASE_CHUNKED_DECODE,
    BASE_NEGATIVE_PROMPT,
    ProvenanceContext,
    run_smoke_a,
    run_smoke_b,
    run_smoke_c,
    run_smoke_d,
)

BASE_PROMPT = (
    "A steady instrumental electronic music loop with drums, bass, and warm "
    "synthesizer, clean studio recording, 120 BPM"
)


def provenance_context(run_id: str = "cpu-mock") -> ProvenanceContext:
    return ProvenanceContext(
        creating_command="pytest CPU-only official-generate contract",
        run_id=run_id,
        source_ids=("stabilityai/stable-audio-3-medium-base@immutable-test",),
        model_revision="immutable-test",
        license_identifier="test-only",
    )


def stereo_tone_batch(duration: float, batch_size: int) -> np.ndarray:
    frames = round(duration * 44_100)
    phase = np.arange(frames, dtype=np.float32) * np.float32(2.0 * np.pi / 44_100)
    stereo = np.stack(
        (
            np.float32(0.1) * np.sin(np.float32(220.0) * phase),
            np.float32(0.08) * np.sin(np.float32(330.0) * phase),
        )
    ).astype(np.float32, copy=False)
    return np.repeat(stereo[None, ...], batch_size, axis=0)


class RecordingOfficialModel:
    """Small deterministic stand-in that records the official keyword contract."""

    device = "cpu"
    model_config = {"sample_size": 16_777_216}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> np.ndarray:
        self.calls.append(dict(kwargs))
        prompt = kwargs["prompt"]
        if isinstance(prompt, list):
            assert len(prompt) == kwargs["batch_size"]
        return stereo_tone_batch(kwargs["duration"], kwargs["batch_size"])


def assert_frozen_common_generate_args(call: dict[str, Any]) -> None:
    assert call["negative_prompt"] == BASE_NEGATIVE_PROMPT
    assert call["chunked_decode"] is BASE_CHUNKED_DECODE
    assert call["steps"] == 50
    assert call["cfg_scale"] == 7.0
    assert call["sampler_type"] == "euler"
    assert call["duration_padding_sec"] == 6.0
    assert call["truncate_output_to_duration"] is True
    assert call["disable_tqdm"] is True
    assert call["sample_size"] == 16_777_216


def test_mocked_a_b_c_pass_and_use_exact_official_arguments(tmp_path: Path) -> None:
    model = RecordingOfficialModel()
    context = provenance_context()

    result_a = run_smoke_a(model, tmp_path / "a", prompt=BASE_PROMPT, provenance=context)
    assert result_a.status == "PASS"
    assert len(result_a.artifacts) == 2
    assert result_a.checks["decoded_waveform_hashes_equal"] is True
    for call in model.calls[:2]:
        assert_frozen_common_generate_args(call)
        assert call["prompt"] == BASE_PROMPT
        assert call["duration"] == 30.0
        assert call["batch_size"] == 1
        assert call["seed"] == 73_193_001

    result_b = run_smoke_b(
        model,
        result_a.artifacts[0].path,
        tmp_path / "b",
        prompt="Continue the same instrumental electronic music",
        provenance=context,
    )
    assert result_b.status == "PASS"
    assert [artifact.label for artifact in result_b.artifacts] == [
        "derived_audio",
        "synthetic_model_output",
    ]
    continuation_call = model.calls[2]
    assert_frozen_common_generate_args(continuation_call)
    assert continuation_call["seed"] == 73_193_002
    assert continuation_call["inpaint_mask_start_seconds"] == 10.0
    assert continuation_call["inpaint_mask_end_seconds"] == 30.0
    source_rate, source_tensor = continuation_call["inpaint_audio"]
    assert source_rate == 44_100
    assert tuple(source_tensor.shape) == (2, 441_000)

    result_c = run_smoke_c(
        model,
        result_a.artifacts[0].path,
        tmp_path / "c",
        prompt="A seamless instrumental electronic music passage",
        provenance=context,
    )
    assert result_c.status == "PASS"
    assert len(result_c.artifacts) == 2
    single_call, multi_call = model.calls[3:5]
    for call in (single_call, multi_call):
        assert_frozen_common_generate_args(call)
        assert call["duration"] == 30.0
        assert call["batch_size"] == 1
    assert single_call["seed"] == 73_193_003
    assert single_call["inpaint_mask_start_seconds"] == 8.0
    assert single_call["inpaint_mask_end_seconds"] == 12.0
    assert multi_call["seed"] == 73_193_004
    assert multi_call["inpaint_mask_start_seconds"] == [4.0, 20.0]
    assert multi_call["inpaint_mask_end_seconds"] == [6.0, 23.0]

    for result in (result_a, result_b, result_c):
        json.dumps(result.to_dict(), allow_nan=False)
        for artifact in result.artifacts:
            assert artifact.sanity["pass"] is True
            assert validate_adjacent_provenance(artifact.path)["label"] == artifact.label


def test_a_hash_mismatch_is_terminal_failure_even_when_numerically_close(
    tmp_path: Path,
) -> None:
    class AlmostDeterministicModel(RecordingOfficialModel):
        def generate(self, **kwargs: Any) -> np.ndarray:
            output = super().generate(**kwargs)
            if len(self.calls) == 2:
                output[0, 0, 0] += np.float32(1e-7)
            return output

    result = run_smoke_a(
        AlmostDeterministicModel(),
        tmp_path,
        prompt=BASE_PROMPT,
        provenance=provenance_context("a-mismatch"),
        duration=0.02,
    )
    assert result.status == "FAIL"
    assert result.checks["decoded_waveform_hashes_equal"] is False
    comparison = result.metrics["waveform_comparison"]
    assert comparison["max_abs_error"] <= 1e-5
    assert result.metrics["diagnostic_closeness_tolerance"]["hash_mismatch_remains_failure"] is True


class FakeHookHandle:
    def __init__(self, hooks: list[Any], callback: Any) -> None:
        self.hooks = hooks
        self.callback = callback

    def remove(self) -> None:
        self.hooks.remove(self.callback)


class FakeBackbone:
    def __init__(self) -> None:
        self.hooks: list[Any] = []

    def register_forward_pre_hook(self, callback: Any) -> FakeHookHandle:
        self.hooks.append(callback)
        return FakeHookHandle(self.hooks, callback)

    def invoke(self) -> None:
        for hook in tuple(self.hooks):
            hook(self, ())


class InstrumentedOfficialModel(RecordingOfficialModel):
    device = "cuda:0"

    def __init__(self) -> None:
        super().__init__()
        self.dit = FakeBackbone()

    def generate(self, **kwargs: Any) -> np.ndarray:
        self.calls.append(dict(kwargs))
        prompt = kwargs["prompt"]
        if isinstance(prompt, list):
            assert len(prompt) == kwargs["batch_size"]
        for index in range(kwargs["steps"]):
            self.dit.invoke()
            kwargs["callback"]({"i": index})
        return stereo_tone_batch(kwargs["duration"], kwargs["batch_size"])


def install_fake_cuda_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDevice:
        type = "cuda"

        def __str__(self) -> str:
            return "cuda:0"

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def synchronize(_device: FakeDevice) -> None:
            return None

        @staticmethod
        def reset_peak_memory_stats(_device: FakeDevice) -> None:
            return None

        @staticmethod
        def memory_allocated(_device: FakeDevice) -> int:
            return 10_000

        @staticmethod
        def memory_reserved(_device: FakeDevice) -> int:
            return 20_000

        @staticmethod
        def max_memory_allocated(_device: FakeDevice) -> int:
            return 30_000

        @staticmethod
        def max_memory_reserved(_device: FakeDevice) -> int:
            return 40_000

        @staticmethod
        def get_device_name(_device: FakeDevice) -> str:
            return "NVIDIA A800-SXM4-80GB (CPU-only mock)"

    fake_torch = types.ModuleType("torch")
    fake_torch.device = lambda _configured: FakeDevice()  # type: ignore[attr-defined]
    fake_torch.cuda = FakeCuda()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)


def test_mocked_d_measures_calls_vram_and_exact_batch4_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_cuda_torch(monkeypatch)
    model = InstrumentedOfficialModel()

    result = run_smoke_d(
        model,
        tmp_path,
        prompt=BASE_PROMPT,
        provenance=provenance_context("d-cost"),
        batch4_prompts=BASE_BATCH4_PROMPTS,
    )

    assert result.status == "PASS"
    assert len(result.artifacts) == 5
    assert result.metrics["batch1"]["backbone_forward_calls"] == 50
    assert result.metrics["batch1"]["sampler_callback_calls"] == 50
    assert result.metrics["batch1"]["sampler_callback_step_indices"] == list(range(50))
    assert result.metrics["batch1"]["peak_allocated_bytes"] == 30_000
    assert result.metrics["batch1"]["peak_reserved_bytes"] == 40_000
    assert result.metrics["batch1"]["wall_seconds"] > 0
    assert result.metrics["batch4"]["items_per_second"] > 0
    assert result.metrics["batch4"]["generated_audio_seconds_per_second"] > 0

    batch1_call, batch4_call = model.calls
    for call in (batch1_call, batch4_call):
        assert_frozen_common_generate_args(call)
    assert batch1_call["prompt"] == BASE_PROMPT
    assert batch1_call["batch_size"] == 1
    assert batch1_call["duration"] == 30.0
    assert batch1_call["seed"] == 73_193_005
    assert batch4_call["prompt"] == list(BASE_BATCH4_PROMPTS)
    assert batch4_call["batch_size"] == 4
    assert batch4_call["duration"] == 10.0
    assert batch4_call["seed"] == 73_193_006
    json.dumps(result.to_dict(), allow_nan=False)

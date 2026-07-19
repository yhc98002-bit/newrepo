"""CPU-only integration test for high-level smoke E orchestration."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

import sa3_smoke.smoke_e as smoke_e_module
from sa3_smoke.artifacts import sha256_file, validate_adjacent_provenance
from sa3_smoke.latent import run_euler_transitions
from sa3_smoke.model_runtime import ModelRuntime, resolve_local_model_config
from sa3_smoke.smoke_e import _offload_parent_model_to_cpu, run_smoke_e
from sa3_smoke.smokes import ProvenanceContext

ROOT = Path(__file__).resolve().parents[1]
FROZEN_CONFIG = ROOT / "configs" / "foundation_v1.json"


def test_child_timeout_never_uses_remaining_budget_to_interrupt_atomic_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke_e_module, "remaining_budget_seconds", lambda: 0.25)
    assert smoke_e_module._bounded_child_timeout(None) is None
    assert smoke_e_module._bounded_child_timeout(90.0) == 90.0

    monkeypatch.setattr(smoke_e_module, "remaining_budget_seconds", lambda: 0.0)
    with pytest.raises(RuntimeError, match="deadline reached before Smoke E child"):
        smoke_e_module._bounded_child_timeout(None)


class MockBackbone(torch.nn.Module):
    def forward(self, latent: torch.Tensor, timestep: torch.Tensor, **_kwargs: Any) -> torch.Tensor:
        return latent * 0.125 + timestep[:, None, None] * 0.25 - 0.03125


class MockConditionedModel(torch.nn.Module):
    """Registered stand-in for conditioner, DiT, and pretransform ownership."""

    def __init__(self) -> None:
        super().__init__()
        self.conditioner = torch.nn.Linear(1, 1)
        self.model = MockBackbone()
        self.pretransform = torch.nn.Identity()


def _baseline_euler(
    model: Any,
    latent: torch.Tensor,
    sigmas: torch.Tensor,
    callback: Any = None,
    disable_tqdm: bool = False,
    **kwargs: Any,
) -> torch.Tensor:
    del disable_tqdm
    return run_euler_transitions(
        model,
        latent,
        sigmas,
        model_kwargs=kwargs,
        callback=callback,
    ).latent


def install_fake_stable_audio_modules(monkeypatch: pytest.MonkeyPatch | None = None) -> None:
    package = types.ModuleType("stable_audio_3")
    package.__path__ = []  # type: ignore[attr-defined]
    inference = types.ModuleType("stable_audio_3.inference")
    inference.__path__ = []  # type: ignore[attr-defined]
    sampling = types.ModuleType("stable_audio_3.inference.sampling")
    sampling.sample_discrete_euler = _baseline_euler  # type: ignore[attr-defined]
    package.inference = inference  # type: ignore[attr-defined]
    inference.sampling = sampling  # type: ignore[attr-defined]
    modules = {
        "stable_audio_3": package,
        "stable_audio_3.inference": inference,
        "stable_audio_3.inference.sampling": sampling,
    }
    for name, module in modules.items():
        if monkeypatch is None:
            sys.modules[name] = module
        else:
            monkeypatch.setitem(sys.modules, name, module)


class MockOfficialModel:
    """Deterministic official-generate stand-in that calls the injected sampler."""

    device = "cpu"

    def __init__(self, model_config: dict[str, Any]) -> None:
        self.model_config = model_config
        self.model = MockConditionedModel()
        self.dit = self.model.model
        self.same = self.model.pretransform
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> np.ndarray:
        self.calls.append(dict(kwargs))
        from stable_audio_3.inference import sampling

        generator = torch.Generator(device="cpu").manual_seed(kwargs["seed"])
        initial = torch.randn((1, 2, 8), generator=generator, dtype=torch.float64)
        schedule = torch.linspace(1.0, 0.0, kwargs["steps"] + 1, dtype=torch.float64)
        final_latent = sampling.sample_discrete_euler(
            self.dit,
            initial,
            schedule,
            disable_tqdm=kwargs["disable_tqdm"],
        )

        frames = round(float(kwargs["duration"]) * 44_100)
        phase = np.arange(frames, dtype=np.float32) * np.float32(2.0 * np.pi / 44_100)
        latent_term = np.float32(float(final_latent.mean()) * 1e-4)
        left = np.float32(0.08) * np.sin(np.float32(220.0) * phase) + latent_term
        right = np.float32(0.07) * np.sin(np.float32(330.0) * phase) - latent_term
        return np.ascontiguousarray(np.stack((left, right))[None, ...], dtype=np.float32)


def mock_child_model_loader(
    resolution: Any,
    checkpoint_path: str,
    *,
    device: str,
    model_half: bool,
    expected_checkpoint_sha256: str,
) -> ModelRuntime:
    """Importable local-only loader used by real child interpreters."""

    install_fake_stable_audio_modules()
    checkpoint = Path(checkpoint_path).resolve(strict=True)
    actual_sha256 = sha256_file(checkpoint)
    if actual_sha256 != expected_checkpoint_sha256:
        raise ValueError("mock checkpoint identity mismatch")
    model_config = json.loads(Path(resolution.resolved_config_path).read_text(encoding="utf-8"))
    return ModelRuntime(
        stable_audio_model=MockOfficialModel(model_config),
        config_resolution=resolution,
        checkpoint_path=str(checkpoint),
        checkpoint_sha256=actual_sha256,
        device=device,
        model_half=model_half,
    )


def make_local_snapshot(tmp_path: Path) -> tuple[Path, Path, Path]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    original = snapshot / "model_config.json"
    original.write_text(
        json.dumps(
            {
                "model_type": "diffusion_cond_inpaint",
                "sample_size": 256,
                "model": {
                    "conditioning": {
                        "configs": [
                            {
                                "id": "prompt",
                                "type": "t5gemma",
                                "config": {
                                    "max_length": 256,
                                    "repo_id": "stabilityai/stable-audio-3-medium",
                                    "subfolder": "t5gemma-b-b-ul2",
                                },
                            }
                        ]
                    }
                },
            },
            indent=4,
        ),
        encoding="utf-8",
    )
    conditioner = snapshot / "t5gemma-b-b-ul2"
    conditioner.mkdir()
    (conditioner / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["T5GemmaForConditionalGeneration"],
                "encoder": {"hidden_size": 768},
                "model_type": "t5gemma",
            }
        ),
        encoding="utf-8",
    )
    (conditioner / "model.safetensors").write_bytes(b"tiny test conditioner")
    checkpoint = snapshot / "model.ckpt"
    checkpoint.write_bytes(b"tiny test diffusion checkpoint")
    return original, conditioner, checkpoint


class PlacementDevice:
    def __init__(self, name: str) -> None:
        self.name = name
        self.type = name.split(":", 1)[0]

    def __str__(self) -> str:
        return self.name


class PlacementTensor:
    def __init__(self, device: str, size: int) -> None:
        self.device = PlacementDevice(device)
        self.size = size

    def numel(self) -> int:
        return self.size


class PlacementConditionedModel:
    conditioner = object()
    model = object()
    pretransform = object()

    def __init__(self) -> None:
        self.parameter = PlacementTensor("cuda:0", 100)
        self.buffer = PlacementTensor("cuda:0", 10)

    def named_parameters(self, recurse: bool = True):
        assert recurse
        return iter((("dit.weight", self.parameter),))

    def named_buffers(self, recurse: bool = True):
        assert recurse
        return iter((("pretransform.scale", self.buffer),))

    def to(self, device: str) -> PlacementConditionedModel:
        self.parameter.device = PlacementDevice(device)
        self.buffer.device = PlacementDevice(device)
        return self


class PlacementCuda:
    def __init__(self, model: PlacementConditionedModel) -> None:
        self.model = model
        self.empty_cache_calls = 0
        self.synchronize_calls = 0

    @staticmethod
    def is_available() -> bool:
        return True

    def synchronize(self, _device: PlacementDevice) -> None:
        self.synchronize_calls += 1

    def memory_allocated(self, _device: PlacementDevice) -> int:
        return 1_234 if self.model.parameter.device.type == "cuda" else 17

    def memory_reserved(self, _device: PlacementDevice) -> int:
        return 4_096 if self.model.parameter.device.type == "cuda" else 32

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


class PlacementTorch:
    def __init__(self, model: PlacementConditionedModel) -> None:
        self.cuda = PlacementCuda(model)

    @staticmethod
    def device(name: str | PlacementDevice) -> PlacementDevice:
        return name if isinstance(name, PlacementDevice) else PlacementDevice(name)


def test_parent_cuda_offload_records_allocator_and_non_model_residual() -> None:
    conditioned = PlacementConditionedModel()
    official = types.SimpleNamespace(model=conditioned, device="cuda:0")
    fake_torch = PlacementTorch(conditioned)

    metrics = _offload_parent_model_to_cpu(official, torch_module=fake_torch)

    assert official.device == "cpu"
    assert metrics["before_tensor_inventory"]["cuda_parameter_count"] == 1
    assert metrics["before_tensor_inventory"]["cuda_buffer_count"] == 1
    assert metrics["after_tensor_inventory"]["cuda_parameter_count"] == 0
    assert metrics["after_tensor_inventory"]["cuda_buffer_count"] == 0
    assert metrics["no_parent_model_parameters_or_buffers_on_cuda"] is True
    assert metrics["cuda_allocated_bytes_before_offload"] == 1_234
    assert metrics["cuda_reserved_bytes_before_offload"] == 4_096
    assert metrics["cuda_allocated_bytes_after_offload"] == 17
    assert metrics["cuda_reserved_bytes_after_offload"] == 32
    assert metrics["non_model_cuda_allocated_residual_bytes"] == 17
    assert metrics["non_model_cuda_reserved_residual_bytes"] == 32
    assert metrics["cuda_empty_cache_called"] is True
    assert metrics["cuda_synchronize_calls"] == 2
    assert fake_torch.cuda.empty_cache_calls == 1
    assert fake_torch.cuda.synchronize_calls == 2
    assert "non-model process residual" in metrics["residual_interpretation"]


def test_mocked_smoke_e_runs_three_official_child_resumes_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_stable_audio_modules(monkeypatch)
    original, conditioner, checkpoint = make_local_snapshot(tmp_path)
    parent_resolution = resolve_local_model_config(
        original,
        conditioner,
        tmp_path / "parent-config-resolution",
        required_t5_files=("config.json", "model.safetensors"),
    )
    checkpoint_sha256 = sha256_file(checkpoint)
    parent_official = MockOfficialModel(
        json.loads(Path(parent_resolution.resolved_config_path).read_text(encoding="utf-8"))
    )
    runtime = ModelRuntime(
        stable_audio_model=parent_official,
        config_resolution=parent_resolution,
        checkpoint_path=str(checkpoint.resolve()),
        checkpoint_sha256=checkpoint_sha256,
        device="cpu",
        model_half=False,
    )
    provenance = ProvenanceContext(
        creating_command="pytest mocked smoke E separate-process integration",
        run_id="smoke-e-cpu-integration",
        source_ids=(f"{checkpoint.resolve()}#sha256={checkpoint_sha256}",),
        model_revision="immutable-test-revision",
        license_identifier="test-only-license",
    )

    result = run_smoke_e(
        runtime,
        tmp_path / "smoke-e",
        frozen_config_path=FROZEN_CONFIG,
        provenance=provenance,
        python_executable=sys.executable,
        child_timeout_seconds=90,
        required_t5_files=("config.json", "model.safetensors"),
        child_model_loader_factory="tests.test_smoke_e:mock_child_model_loader",
    )

    assert result.status == "PASS", result.error or result.artifacts["resumes"]
    assert result.checks["checkpoints_exported_after_15_30_40_steps"] is True
    assert result.checks["three_children_launched_sequentially"] is True
    assert result.checks["remaining_forward_calls_are_35_20_10"] is True
    assert result.checks["all_waveform_equivalence_checks_pass"] is True
    assert (
        result.checks["parent_reference_output_and_final_latent_released_before_children"] is True
    )
    assert result.checks["parent_full_conditioned_model_offloaded_to_cpu_before_children"] is True
    assert result.checks["no_parent_model_parameters_or_buffers_remain_cuda"] is True
    assert result.checks["parent_cuda_cache_cleared_before_children"] is True
    assert result.metrics["remaining_forward_calls"] == [35, 20, 10]
    assert len(set(result.metrics["child_pids"])) == 3
    assert all(pid != result.metrics["reference_pid"] for pid in result.metrics["child_pids"])
    release = result.metrics["parent_runtime_release_before_children"]
    assert release["reference_output_reference_released"] is True
    assert release["reference_sampler_final_latent_reference_released"] is True
    assert release["release_completed_before_first_child"] is True
    assert release["parent_model_intentionally_not_restored_to_cuda"] is True
    assert release["final_official_device"] == "cpu"
    assert release["cuda_monitoring_active"] is False
    assert release["cuda_allocated_bytes_before_offload"] is None
    assert release["cuda_allocated_bytes_after_offload"] is None
    assert parent_official.device == "cpu"
    assert all(parameter.device.type == "cpu" for parameter in parent_official.model.parameters())
    assert all(buffer.device.type == "cpu" for buffer in parent_official.model.buffers())

    assert len(parent_official.calls) == 1
    reference_call = parent_official.calls[0]
    frozen = json.loads(FROZEN_CONFIG.read_text(encoding="utf-8"))
    assert reference_call == {
        "prompt": frozen["sampling"]["prompt"],
        "negative_prompt": frozen["sampling"]["negative_prompt"],
        "duration": 30.0,
        "steps": 50,
        "cfg_scale": 7.0,
        "batch_size": 1,
        "seed": 73_193_007,
        "duration_padding_sec": 6.0,
        "truncate_output_to_duration": True,
        "sampler_type": "euler",
        "disable_tqdm": True,
        "chunked_decode": True,
        "sample_size": 256,
    }

    reference_wav = result.artifacts["reference_wav"]
    assert reference_wav["sanity"]["pass"] is True
    assert validate_adjacent_provenance(reference_wav["path"])["label"] == (
        "synthetic_model_output"
    )

    checkpoints = result.artifacts["checkpoints"]
    assert [row["completed_steps"] for row in checkpoints] == [15, 30, 40]
    for row in checkpoints:
        provenance_record = validate_adjacent_provenance(row["path"])
        assert provenance_record["label"] == "latent_checkpoint"
        assert Path(row["state_metadata_path"]).is_file()

    resumes = result.artifacts["resumes"]
    assert [row["remaining_forward_calls"] for row in resumes] == [35, 20, 10]
    for row in resumes:
        assert row["status"] == "PASS"
        assert row["comparison_to_reference"]["pass"] is True
        assert row["comparison_to_reference"]["max_abs_error"] == 0.0
        assert row["wav"]["sanity"]["pass"] is True
        assert validate_adjacent_provenance(row["wav"]["path"])["label"] == (
            "synthetic_model_output"
        )
        assert validate_adjacent_provenance(row["result_path"])["label"] == ("latent_checkpoint")
        resolution = row["config_resolution"]
        for field in (
            "original_copy_path",
            "resolved_config_path",
            "diff_path",
            "resolution_manifest_path",
        ):
            assert Path(resolution[field]).is_file()
        manifest = json.loads(Path(resolution["resolution_manifest_path"]).read_text())
        assert manifest["network_access"] == "none"
        assert row["network_access"] == "disabled; local paths only"

    json.dumps(result.to_dict(), allow_nan=False)

"""CPU-only tests for exact Euler checkpoint/reload engineering."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
import torch

from sa3_smoke.latent import (
    CHECKPOINT_COMPLETED_STEPS,
    CheckpointingEulerSampler,
    CheckpointValidationError,
    ResumeRuntime,
    ResumingEulerSampler,
    json_sha256,
    load_euler_checkpoint,
    run_euler_transitions,
    run_resume_in_subprocess,
    sha256_file,
    tensor_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
CONDITIONING = {"prompt": "tiny deterministic fixture", "seconds_total": 0.001}
CONFIG = {"steps": 50, "sampler_type": "euler", "fixture": True}
CONDITIONING_SHA256 = json_sha256(CONDITIONING)
CONFIG_SHA256 = json_sha256(CONFIG)
GAIN = 0.125
OFFSET = -0.03125


class TinyVelocity(torch.nn.Module):
    """Small deterministic velocity field with the SA3 backbone call shape."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[torch.Tensor] = []

    def forward(
        self,
        latent: torch.Tensor,
        timestep: torch.Tensor,
        *,
        gain: float,
        offset: float,
    ) -> torch.Tensor:
        self.calls.append(timestep.detach().cpu().clone())
        return latent * gain + timestep[:, None, None] * 0.25 + offset


class PromotingTinyVelocity(TinyVelocity):
    """Mimic the production backbone returning float32 from float16 noise."""

    def forward(
        self,
        latent: torch.Tensor,
        timestep: torch.Tensor,
        *,
        gain: float,
        offset: float,
    ) -> torch.Tensor:
        return super().forward(latent, timestep, gain=gain, offset=offset).float()


def fixture_latent() -> torch.Tensor:
    return torch.linspace(-0.75, 0.9, 24, dtype=torch.float64).reshape(2, 3, 4)


def fixture_schedule() -> torch.Tensor:
    return torch.linspace(1.0, 0.0, 51, dtype=torch.float64)


def pinned_upstream_equation(
    model: TinyVelocity,
    latent: torch.Tensor,
    schedule: torch.Tensor,
    *,
    gain: float,
    offset: float,
) -> torch.Tensor:
    """Independent transcription of pinned upstream sample_discrete_euler."""

    x = latent
    t = schedule.to(x.device)
    per_element_schedule = t.dim() == 2
    for index in range(t.shape[-1] - 1):
        if per_element_schedule:
            t_curr_tensor = t[:, index].to(x.dtype)
            t_next = t[:, index + 1].to(x.dtype)
            dt = (t_next - t_curr_tensor).view(-1, 1, 1)
        else:
            t_curr = t[index]
            t_next = t[index + 1]
            t_curr_tensor = t_curr * torch.ones((x.shape[0],), dtype=x.dtype, device=x.device)
            dt = t_next - t_curr
        velocity = model(x, t_curr_tensor, gain=gain, offset=offset)
        x = x + dt * velocity
    return x


def injected_fake_runtime_factory(request: dict[str, Any], checkpoint: Any) -> ResumeRuntime:
    """Child-importable factory exercising official-generate sampler injection."""

    runtime_kwargs = request["runtime_kwargs"]
    conditioning = runtime_kwargs["conditioning"]
    config = runtime_kwargs["config"]
    gain = runtime_kwargs["gain"]
    offset = runtime_kwargs["offset"]

    def invoke_generate(sampler: Any) -> torch.Tensor:
        # This mimics what the official generate path supplies to its sampler:
        # a newly allocated noise latent, rebuilt full schedule, model, and
        # conditioning-derived model kwargs.  Resume must ignore only the
        # deliberately wrong fresh latent values.
        fresh_noise = torch.full(
            tuple(checkpoint.metadata["latent_shape"]),
            777.0,
            dtype=torch.float32,
        )
        rebuilt_schedule = fixture_schedule()
        return sampler(
            TinyVelocity(),
            fresh_noise,
            rebuilt_schedule,
            disable_tqdm=True,
            gain=gain,
            offset=offset,
        )

    def finalize(
        final_latent: torch.Tensor,
        generated_output: torch.Tensor,
        loaded_checkpoint: Any,
        loaded_request: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "generated_output_is_final_latent": bool(torch.equal(final_latent, generated_output)),
            "source_next_step_index": loaded_checkpoint.next_step_index,
            "request_result_name": Path(loaded_request["result_path"]).name,
        }

    return ResumeRuntime(
        conditioning_sha256=json_sha256(conditioning),
        config_sha256=json_sha256(config),
        invoke_generate=invoke_generate,
        finalize=finalize,
    )


@pytest.mark.parametrize("per_element_schedule", [False, True])
def test_exact_transition_and_callback_order_matches_pinned_upstream(
    per_element_schedule: bool,
) -> None:
    latent = fixture_latent()
    schedule = fixture_schedule()
    if per_element_schedule:
        schedule = torch.stack((schedule, schedule.square()))

    reference_model = TinyVelocity()
    expected = pinned_upstream_equation(
        reference_model,
        latent.clone(),
        schedule,
        gain=GAIN,
        offset=OFFSET,
    )
    callback_rows: list[dict[str, Any]] = []

    def callback(row: dict[str, Any]) -> None:
        callback_rows.append(
            {
                "i": row["i"],
                "x": row["x"].detach().clone(),
                "t": row["t"].detach().clone(),
                "denoised": row["denoised"].detach().clone(),
            }
        )

    model = TinyVelocity()
    actual = run_euler_transitions(
        model,
        latent.clone(),
        schedule,
        model_kwargs={"gain": GAIN, "offset": OFFSET},
        callback=callback,
    )

    assert torch.equal(actual.latent, expected)
    assert actual.forward_calls == 50
    assert len(model.calls) == 50
    assert [row["i"] for row in callback_rows] == list(range(50))
    assert torch.equal(callback_rows[0]["x"], latent)
    first_t = callback_rows[0]["t"]
    first_velocity = TinyVelocity()(latent, first_t, gain=GAIN, offset=OFFSET)
    assert torch.equal(
        callback_rows[0]["denoised"], latent - first_t[:, None, None] * first_velocity
    )


def test_matches_installed_pinned_upstream_sampler_without_gpu_or_weights() -> None:
    from stable_audio_3.inference.sampling import sample_discrete_euler

    latent = fixture_latent()
    schedule = fixture_schedule()
    upstream_model = TinyVelocity()
    upstream = sample_discrete_euler(
        upstream_model,
        latent.clone(),
        schedule,
        disable_tqdm=True,
        gain=GAIN,
        offset=OFFSET,
    )
    ours = run_euler_transitions(
        TinyVelocity(),
        latent.clone(),
        schedule,
        model_kwargs={"gain": GAIN, "offset": OFFSET},
    )
    assert torch.equal(ours.latent, upstream)


def test_checkpoint_boundaries_integrity_resume_index_and_no_clobber(
    tmp_path: Path,
) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    sampler = CheckpointingEulerSampler(
        checkpoint_dir=checkpoint_dir,
        checkpoint_prefix="reference",
        run_id="unit-reference",
        conditioning_sha256=CONDITIONING_SHA256,
        config_sha256=CONFIG_SHA256,
        run_metadata={"seed_id": "TEST-0001", "seed": 1234},
    )
    final_latent = sampler(
        TinyVelocity(),
        fixture_latent(),
        fixture_schedule(),
        disable_tqdm=True,
        gain=GAIN,
        offset=OFFSET,
    )
    assert sampler.last_run_result is not None
    assert sampler.last_run_result.forward_calls == 50
    assert tuple(item.completed_steps for item in sampler.last_run_result.checkpoints) == (
        CHECKPOINT_COMPLETED_STEPS
    )

    for completed_steps, artifact in zip(
        CHECKPOINT_COMPLETED_STEPS,
        sampler.last_run_result.checkpoints,
        strict=True,
    ):
        assert artifact.path.name == f"reference.step-{completed_steps:03d}.pt"
        assert artifact.path.is_file()
        assert artifact.state_metadata_path.is_file()
        assert artifact.checkpoint_sha256 == sha256_file(artifact.path)
        state = load_euler_checkpoint(
            artifact.path,
            expected_conditioning_sha256=CONDITIONING_SHA256,
            expected_config_sha256=CONFIG_SHA256,
        )
        partial = run_euler_transitions(
            TinyVelocity(),
            fixture_latent(),
            fixture_schedule(),
            stop_step_index=completed_steps,
            model_kwargs={"gain": GAIN, "offset": OFFSET},
        )
        assert state.next_step_index == completed_steps
        assert state.metadata["completed_steps"] == completed_steps
        assert state.metadata["completed_fraction"] == completed_steps / 50
        assert state.metadata["latent_sha256"] == tensor_sha256(state.latent)
        assert state.metadata["schedule_sha256"] == tensor_sha256(state.schedule)
        assert torch.equal(state.latent, partial.latent)

        resumed = ResumingEulerSampler(state)
        resumed_latent = resumed(
            TinyVelocity(),
            torch.full_like(fixture_latent(), 999.0),
            fixture_schedule(),
            gain=GAIN,
            offset=OFFSET,
        )
        assert resumed.runtime_schedule_validated
        assert resumed.last_run_result is not None
        assert resumed.last_run_result.start_step_index == completed_steps
        assert resumed.last_run_result.forward_calls == 50 - completed_steps
        assert torch.equal(resumed_latent, final_latent)

    first_artifact = sampler.last_run_result.checkpoints[0]
    checkpoint_bytes_before = first_artifact.path.read_bytes()
    state_bytes_before = first_artifact.state_metadata_path.read_bytes()
    duplicate_sampler = CheckpointingEulerSampler(
        checkpoint_dir=checkpoint_dir,
        checkpoint_prefix="reference",
        run_id="unit-reference-duplicate",
        conditioning_sha256=CONDITIONING_SHA256,
        config_sha256=CONFIG_SHA256,
    )
    with pytest.raises(FileExistsError, match="refusing to overwrite checkpoint"):
        duplicate_sampler(
            TinyVelocity(),
            fixture_latent(),
            fixture_schedule(),
            gain=GAIN,
            offset=OFFSET,
        )
    assert first_artifact.path.read_bytes() == checkpoint_bytes_before
    assert first_artifact.state_metadata_path.read_bytes() == state_bytes_before


def test_resuming_sampler_rejects_rebuilt_schedule_mismatch(tmp_path: Path) -> None:
    sampler = CheckpointingEulerSampler(
        checkpoint_dir=tmp_path,
        checkpoint_prefix="mismatch",
        run_id="unit-mismatch",
        conditioning_sha256=CONDITIONING_SHA256,
        config_sha256=CONFIG_SHA256,
    )
    sampler(
        TinyVelocity(),
        fixture_latent(),
        fixture_schedule(),
        gain=GAIN,
        offset=OFFSET,
    )
    assert sampler.last_run_result is not None
    state = load_euler_checkpoint(sampler.last_run_result.checkpoints[0].path)
    changed_schedule = fixture_schedule()
    changed_schedule[25] += 1e-8
    with pytest.raises(CheckpointValidationError, match="full schedule does not match"):
        ResumingEulerSampler(state)(
            TinyVelocity(),
            fixture_latent(),
            changed_schedule,
            gain=GAIN,
            offset=OFFSET,
        )


def test_resume_preserves_promoted_checkpoint_dtype_when_fresh_noise_is_half(
    tmp_path: Path,
) -> None:
    """Regression for the production float16-noise/float32-state boundary."""

    initial = torch.linspace(-0.75, 0.9, 24, dtype=torch.float16).reshape(2, 3, 4)
    base_schedule = fixture_schedule().to(torch.float32)
    schedule = torch.stack((base_schedule, base_schedule))
    reference_sampler = CheckpointingEulerSampler(
        checkpoint_dir=tmp_path,
        checkpoint_prefix="mixed-dtype",
        run_id="unit-mixed-dtype-reference",
        conditioning_sha256=CONDITIONING_SHA256,
        config_sha256=CONFIG_SHA256,
    )
    uninterrupted = reference_sampler(
        PromotingTinyVelocity(),
        initial,
        schedule,
        gain=GAIN,
        offset=OFFSET,
    )
    assert reference_sampler.last_run_result is not None

    state = load_euler_checkpoint(reference_sampler.last_run_result.checkpoints[0].path)
    assert state.latent.dtype == torch.float32
    fresh_official_noise = torch.full(initial.shape, 777.0, dtype=torch.float16)
    resumed_sampler = ResumingEulerSampler(state)
    resumed = resumed_sampler(
        PromotingTinyVelocity(),
        fresh_official_noise,
        schedule,
        gain=GAIN,
        offset=OFFSET,
    )

    assert resumed_sampler.fresh_initial_latent_dtype == "torch.float16"
    assert resumed_sampler.checkpoint_latent_dtype == "torch.float32"
    assert resumed_sampler.resume_latent_dtype_preserved is True
    assert resumed.dtype == torch.float32
    assert torch.equal(resumed, uninterrupted)


def test_three_checkpoints_resume_in_three_real_python_processes(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "checkpoints"
    reference_sampler = CheckpointingEulerSampler(
        checkpoint_dir=checkpoint_dir,
        checkpoint_prefix="reference",
        run_id="unit-child-reference",
        conditioning_sha256=CONDITIONING_SHA256,
        config_sha256=CONFIG_SHA256,
    )
    uninterrupted = reference_sampler(
        TinyVelocity(),
        fixture_latent(),
        fixture_schedule(),
        gain=GAIN,
        offset=OFFSET,
    )
    assert reference_sampler.last_run_result is not None

    child_env = os.environ.copy()
    source_path = str(ROOT / "src")
    existing_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = (
        source_path
        if not existing_pythonpath
        else f"{source_path}{os.pathsep}{existing_pythonpath}"
    )
    child_pids: list[int] = []

    for artifact in reference_sampler.last_run_result.checkpoints:
        step = artifact.next_step_index
        launched = run_resume_in_subprocess(
            request_path=tmp_path / f"resume-step-{step:03d}.request.json",
            checkpoint_path=artifact.path,
            result_path=tmp_path / f"resume-step-{step:03d}.result.pt",
            runtime_factory="tests.test_latent:injected_fake_runtime_factory",
            conditioning_sha256=CONDITIONING_SHA256,
            config_sha256=CONFIG_SHA256,
            runtime_kwargs={
                "conditioning": CONDITIONING,
                "config": CONFIG,
                "gain": GAIN,
                "offset": OFFSET,
            },
            request_metadata={"test": "real-separate-process"},
            python_executable=sys.executable,
            timeout_seconds=60,
            cwd=ROOT,
            env=child_env,
        )
        metadata = launched.artifact.metadata
        child_pids.append(metadata["child_pid"])
        assert metadata["child_pid"] != os.getpid()
        assert metadata["source_next_step_index"] == step
        assert metadata["forward_calls"] == 50 - step
        assert metadata["completed_steps"] == 50
        assert metadata["execution_mode"] == "official_generate_sampler_injection"
        assert metadata["runtime_schedule_validated"] is True
        assert metadata["ignored_fresh_initial_latent"] is True
        assert metadata["fresh_initial_latent_dtype"] == "torch.float32"
        assert metadata["checkpoint_latent_dtype"] == "torch.float64"
        assert metadata["resume_latent_dtype_preserved"] is True
        assert metadata["finalize_metadata"]["generated_output_is_final_latent"] is True
        assert torch.equal(launched.artifact.latent, uninterrupted)
        stdout_summary = json.loads(launched.process.stdout.strip().splitlines()[-1])
        assert stdout_summary["status"] == "PASS"
        assert stdout_summary["child_pid"] == metadata["child_pid"]

    assert len(set(child_pids)) == 3

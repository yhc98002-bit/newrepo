"""Hash-guarded ACE-Step v1 checkpoint export and continuation engine.

The pinned ACE upstream exposes neither a checkpoint callback nor a resume
argument.  This module therefore provides a deliberately narrow interposition
for the one frozen text-to-music configuration.  The official ``__call__``
still owns model loading, prompt/lyric conditioning, initial RNG construction,
and audio decoding; only its diffusion method is replaced.  Production refuses
to import the engine unless the complete upstream Git identity and the two
interposed source-file hashes match the frozen contract.

Importing this module is CPU-only.  PyTorch and ACE are imported only inside a
production engine instance after the sole attempt has already been consumed.
"""

from __future__ import annotations

import gc
import hashlib
import importlib
import io
import json
import os
import subprocess
import tempfile
import time
import types
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from state_capture.ace_artifacts import (
    ArtifactValidationError,
    sha256_file,
    validate_attempt_claim,
    write_bytes_exclusive,
    write_json_exclusive,
)
from state_capture.ace_contract import (
    CHECKPOINT_COMPLETED_TRANSITIONS,
    CHECKPOINT_CUMULATIVE_NFE,
    CHECKPOINT_FRACTIONS,
    MODEL_ID,
    LoadedContract,
    canonical_json_bytes,
    json_sha256,
    validate_static_config,
)

CHECKPOINT_FORMAT = "ace-step-v1-state-checkpoint-v2"
ENGINE_RESULT_FORMAT = "ace-step-v1-state-engine-result-v2"


class AceEngineError(RuntimeError):
    """The exact ACE engine surface or state identity is not usable."""


class AceStateEngine(Protocol):
    """Interface used by the one-attempt runner and separate child process."""

    def run_reference(
        self,
        *,
        request: Mapping[str, Any],
        output_path: Path,
        state_dir: Path,
    ) -> Mapping[str, Any]: ...

    def run_resume(
        self,
        *,
        request: Mapping[str, Any],
        checkpoint_path: Path,
        output_path: Path,
    ) -> Mapping[str, Any]: ...

    def decode_preview(
        self,
        *,
        checkpoint_path: Path,
        checkpoint_sha256: str,
        output_path: Path,
    ) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class LoadedAceCheckpoint:
    path: Path
    artifact_sha256: str
    latent: Any
    timesteps: Any
    sigmas: Any
    generator_state: Any
    metadata: Mapping[str, Any]


def resolve_engine_factory(reference: str) -> Callable[[Mapping[str, Any]], AceStateEngine]:
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise AceEngineError("engine factory must have form module.path:function")
    module_name, attribute = reference.split(":", 1)
    if not module_name or not attribute:
        raise AceEngineError("engine factory reference is incomplete")
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise AceEngineError(f"engine factory is not callable: {reference}")
    return factory


def _git_capture(source_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def inspect_production_capability(
    contract: LoadedContract,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Read-only capability evidence; this never imports ACE or touches CUDA."""

    environment = dict(os.environ if environ is None else environ)
    source_value = environment.get("ACE_STEP_V1_SOURCE_DIR")
    checkpoint_value = environment.get("ACE_STEP_V1_CHECKPOINT_DIR")
    checks: dict[str, Any] = {
        "source_environment_present": bool(source_value),
        "checkpoint_environment_present": bool(checkpoint_value),
        "source_commit_match": False,
        "source_tree_match": False,
        "source_worktree_clean": False,
        "pipeline_sha256_match": False,
        "scheduler_sha256_match": False,
        "checkpoint_root_present": False,
    }
    failures: list[str] = []
    engine = contract.raw["engine"]
    source: Path | None = None
    if not source_value:
        failures.append("ACE_STEP_V1_SOURCE_DIR is absent")
    else:
        source = Path(source_value).resolve()
        if not source.is_dir():
            failures.append("ACE_STEP_V1_SOURCE_DIR is not a directory")
        else:
            try:
                commit = _git_capture(source, "rev-parse", "HEAD")
                tree = _git_capture(source, "rev-parse", "HEAD^{tree}")
                status = _git_capture(source, "status", "--porcelain", "--untracked-files=all")
                checks["source_commit"] = commit
                checks["source_tree"] = tree
                checks["source_status_porcelain"] = status
                checks["source_commit_match"] = commit == engine["source_commit"]
                checks["source_tree_match"] = tree == engine["source_tree"]
                checks["source_worktree_clean"] = not status
                for key, relative_key, hash_key in (
                    (
                        "pipeline",
                        "upstream_pipeline_relative_path",
                        "upstream_pipeline_sha256",
                    ),
                    (
                        "scheduler",
                        "upstream_scheduler_relative_path",
                        "upstream_scheduler_sha256",
                    ),
                ):
                    path = (source / engine[relative_key]).resolve()
                    actual = sha256_file(path) if path.is_file() else None
                    checks[f"{key}_path"] = str(path)
                    checks[f"{key}_sha256"] = actual
                    checks[f"{key}_sha256_match"] = actual == engine[hash_key]
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(f"cannot verify ACE source identity: {exc}")
    if checkpoint_value:
        checkpoint = Path(checkpoint_value).resolve()
        checks["checkpoint_root"] = str(checkpoint)
        checks["checkpoint_root_present"] = checkpoint.is_dir()
    else:
        failures.append("ACE_STEP_V1_CHECKPOINT_DIR is absent")
    for key in (
        "source_commit_match",
        "source_tree_match",
        "source_worktree_clean",
        "pipeline_sha256_match",
        "scheduler_sha256_match",
        "checkpoint_root_present",
    ):
        if not checks[key]:
            failures.append(f"{key}=false")
    return {
        "schema_version": 1,
        "status": "READY" if not failures else "BLOCKED",
        "model_calls": 0,
        "generated_outputs": 0,
        "native_upstream_checkpoint_callback": False,
        "native_upstream_resume_argument": False,
        "execution_surface": "HASH_GUARDED_CONTROLLED_DIFFUSION_METHOD_INTERPOSITION",
        "official_surfaces_retained": [
            "ACEStepPipeline.__call__",
            "prompt_and_lyric_conditioning",
            "initial_seeded_generator_and_noise",
            "MusicDCAE_audio_decode",
        ],
        "engine_limitations": [
            "Pinned upstream has no native checkpoint callback or resume API.",
            "The interposition supports only the frozen BASE text-to-music Euler/cfg path.",
            "Any upstream pipeline or scheduler byte change hard-stops before model loading.",
            "Checkpoint fractions use nearest attainable post-transition states in the "
            "indivisible 45-NFE schedule.",
        ],
        "checks": checks,
        "failures": failures,
    }


def _tensor_sha256(tensor: Any) -> str:
    import torch

    if not isinstance(tensor, torch.Tensor) or tensor.layout != torch.strided:
        raise AceEngineError("state identity requires a strided torch.Tensor")
    canonical = tensor.detach().to(device="cpu").contiguous()
    digest = hashlib.sha256()
    digest.update(b"ace-state-tensor-v2\0")
    digest.update(str(canonical.dtype).encode("ascii"))
    digest.update(b"\0")
    digest.update(canonical_json_bytes(list(canonical.shape)))
    digest.update(b"\0")
    digest.update(canonical.view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def _tensor_bundle_sha256(values: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    hashes = {name: _tensor_sha256(tensor) for name, tensor in sorted(values.items())}
    return json_sha256(hashes), hashes


def _checkpoint_metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.state.json")


def _torch_save_bytes(value: Mapping[str, Any]) -> bytes:
    import torch

    buffer = io.BytesIO()
    torch.save(dict(value), buffer)
    return buffer.getvalue()


def _torch_load_mapping(path: Path) -> Mapping[str, Any]:
    import torch

    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:  # pragma: no cover - supported older torch fallback
        payload = torch.load(path, map_location="cpu")
    if not isinstance(payload, Mapping):
        raise AceEngineError("ACE state checkpoint payload is not a mapping")
    return payload


def save_ace_checkpoint(
    path: Path,
    *,
    latent: Any,
    timesteps: Any,
    sigmas: Any,
    generator_state: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist FP32 state and its complete identity with no-clobber semantics."""

    import torch

    if latent.dtype != torch.float32 or latent.device.type != "cpu":
        raise AceEngineError("exported ACE checkpoint latent must be CPU float32")
    payload = {
        "format": CHECKPOINT_FORMAT,
        "latent": latent.contiguous(),
        "timesteps": timesteps.detach().to(device="cpu", dtype=torch.float32).contiguous(),
        "sigmas": sigmas.detach().to(device="cpu", dtype=torch.float32).contiguous(),
        "generator_state": generator_state.detach().to(device="cpu").contiguous(),
    }
    tensor_hashes = {
        name: _tensor_sha256(value)
        for name, value in payload.items()
        if name != "format"
    }
    artifact_payload = {**payload, "tensor_sha256": tensor_hashes}
    write_bytes_exclusive(path, _torch_save_bytes(artifact_payload))
    sidecar: dict[str, Any] = {
        **dict(metadata),
        "format": CHECKPOINT_FORMAT,
        "artifact_path": str(path.resolve()),
        "artifact_sha256": sha256_file(path),
        "artifact_size_bytes": path.stat().st_size,
        "tensor_sha256": tensor_hashes,
    }
    sidecar["state_identity_sha256"] = json_sha256(sidecar)
    sidecar_path = _checkpoint_metadata_path(path)
    write_json_exclusive(sidecar_path, sidecar)
    loaded = load_ace_checkpoint(path)
    return {
        "path": str(path.resolve()),
        "sha256": loaded.artifact_sha256,
        "state_metadata_path": str(sidecar_path.resolve()),
        "state_metadata_sha256": sha256_file(sidecar_path),
        "completed_scheduler_transitions": loaded.metadata[
            "completed_scheduler_transitions"
        ],
        "cumulative_transformer_nfe": loaded.metadata["cumulative_transformer_nfe"],
        "checkpoint_fraction": loaded.metadata["checkpoint_fraction"],
        "latent_sha256": loaded.metadata["tensor_sha256"]["latent"],
    }


def load_ace_checkpoint(
    path: str | Path,
    *,
    expected_artifact_sha256: str | None = None,
    expected_config_sha256: str | None = None,
) -> LoadedAceCheckpoint:
    source = Path(path).resolve(strict=True)
    artifact_sha = sha256_file(source)
    if expected_artifact_sha256 is not None and artifact_sha != expected_artifact_sha256:
        raise AceEngineError("ACE checkpoint artifact SHA-256 changed")
    payload = _torch_load_mapping(source)
    if payload.get("format") != CHECKPOINT_FORMAT:
        raise AceEngineError("unsupported ACE checkpoint format")
    names = ("latent", "timesteps", "sigmas", "generator_state")
    if any(name not in payload for name in names):
        raise AceEngineError("ACE checkpoint tensor set is incomplete")
    recorded_hashes = payload.get("tensor_sha256")
    if not isinstance(recorded_hashes, Mapping) or set(recorded_hashes) != set(names):
        raise AceEngineError("ACE checkpoint tensor-hash set is incomplete")
    for name in names:
        if recorded_hashes[name] != _tensor_sha256(payload[name]):
            raise AceEngineError(f"ACE checkpoint tensor hash changed: {name}")
    import torch

    if payload["latent"].dtype != torch.float32 or payload["latent"].device.type != "cpu":
        raise AceEngineError("ACE checkpoint latent is not exported CPU float32")

    sidecar_path = _checkpoint_metadata_path(source)
    try:
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AceEngineError("ACE checkpoint state metadata is absent or invalid") from exc
    if not isinstance(metadata, dict):
        raise AceEngineError("ACE checkpoint state metadata is not an object")
    claimed_identity = metadata.get("state_identity_sha256")
    unhashed = dict(metadata)
    unhashed.pop("state_identity_sha256", None)
    if claimed_identity != json_sha256(unhashed):
        raise AceEngineError("ACE checkpoint state identity hash changed")
    if metadata.get("artifact_path") != str(source):
        raise AceEngineError("ACE checkpoint metadata path changed")
    if metadata.get("artifact_sha256") != artifact_sha:
        raise AceEngineError("ACE checkpoint sidecar artifact hash changed")
    if metadata.get("tensor_sha256") != dict(recorded_hashes):
        raise AceEngineError("ACE checkpoint sidecar tensor hashes changed")
    if (
        expected_config_sha256 is not None
        and metadata.get("config_sha256") != expected_config_sha256
    ):
        raise AceEngineError("ACE checkpoint configuration identity changed")
    completed = metadata.get("completed_scheduler_transitions")
    if completed not in CHECKPOINT_COMPLETED_TRANSITIONS:
        raise AceEngineError("ACE checkpoint transition is not one of the frozen checkpoints")
    index = CHECKPOINT_COMPLETED_TRANSITIONS.index(completed)
    if metadata.get("checkpoint_fraction") != CHECKPOINT_FRACTIONS[index]:
        raise AceEngineError("ACE checkpoint fraction/transition mapping changed")
    if metadata.get("cumulative_transformer_nfe") != CHECKPOINT_CUMULATIVE_NFE[index]:
        raise AceEngineError("ACE checkpoint NFE/transition mapping changed")
    if metadata.get("next_scheduler_index") != completed:
        raise AceEngineError("ACE checkpoint next scheduler index changed")
    return LoadedAceCheckpoint(
        path=source,
        artifact_sha256=artifact_sha,
        latent=payload["latent"],
        timesteps=payload["timesteps"],
        sigmas=payload["sigmas"],
        generator_state=payload["generator_state"],
        metadata=metadata,
    )


class _FrozenDiffusionController:
    """Exact restricted implementation of the pinned BASE Euler/cfg loop."""

    def __init__(
        self,
        *,
        contract: LoadedContract,
        request: Mapping[str, Any],
        state_dir: Path | None = None,
        resume: LoadedAceCheckpoint | None = None,
    ) -> None:
        if (state_dir is None) == (resume is None):
            raise AceEngineError("controller requires exactly one of capture or resume mode")
        self.contract = contract
        self.request = dict(request)
        self.state_dir = state_dir
        self.resume = resume
        self.checkpoints: list[dict[str, Any]] = []
        self.actual_nfe = 0
        self.terminal_latent_sha256: str | None = None
        self.conditioning_sha256: str | None = None
        self.conditioning_tensor_sha256: dict[str, str] = {}
        self.runtime_schedule_sha256: str | None = None
        self.runtime_rng_state_sha256: str | None = None
        self.grad_enabled_during_diffusion: bool | None = None

    def __call__(
        self,
        pipeline: Any,
        duration: float,
        encoder_text_hidden_states: Any,
        text_attention_mask: Any,
        speaker_embds: Any,
        lyric_token_ids: Any,
        lyric_mask: Any,
        random_generators: Any = None,
        infer_steps: int = 60,
        guidance_scale: float = 15.0,
        omega_scale: float = 10.0,
        scheduler_type: str = "euler",
        cfg_type: str = "apg",
        zero_steps: int = 1,
        use_zero_init: bool = True,
        guidance_interval: float = 0.5,
        guidance_interval_decay: float = 1.0,
        min_guidance_scale: float = 3.0,
        oss_steps: Any = None,
        encoder_text_hidden_states_null: Any = None,
        use_erg_lyric: bool = False,
        use_erg_diffusion: bool = False,
        retake_random_generators: Any = None,
        retake_variance: float = 0.5,
        add_retake_noise: bool = False,
        guidance_scale_text: float = 0.0,
        guidance_scale_lyric: float = 0.0,
        repaint_start: int = 0,
        repaint_end: int = 0,
        src_latents: Any = None,
        audio2audio_enable: bool = False,
        ref_audio_strength: float = 0.5,
        ref_latents: Any = None,
    ) -> Any:
        del (
            zero_steps,
            use_zero_init,
            retake_random_generators,
            retake_variance,
            repaint_start,
            repaint_end,
            ref_audio_strength,
        )
        generation = self.contract.raw["frozen_generation"]
        observed = {
            "duration": float(duration),
            "infer_steps": infer_steps,
            "guidance_scale": float(guidance_scale),
            "omega_scale": float(omega_scale),
            "scheduler_type": scheduler_type,
            "cfg_type": cfg_type,
            "guidance_interval": float(guidance_interval),
            "guidance_interval_decay": float(guidance_interval_decay),
            "min_guidance_scale": float(min_guidance_scale),
            "use_erg_lyric": use_erg_lyric,
            "use_erg_diffusion": use_erg_diffusion,
            "guidance_scale_text": float(guidance_scale_text),
            "guidance_scale_lyric": float(guidance_scale_lyric),
        }
        expected = {
            "duration": generation["audio_duration_seconds"],
            "infer_steps": generation["inference_steps"],
            "guidance_scale": generation["guidance_scale"],
            "omega_scale": generation["omega_scale"],
            "scheduler_type": generation["scheduler_type"],
            "cfg_type": generation["cfg_type"],
            "guidance_interval": generation["guidance_interval"],
            "guidance_interval_decay": generation["guidance_interval_decay"],
            "min_guidance_scale": generation["min_guidance_scale"],
            "use_erg_lyric": generation["use_erg_lyric"],
            "use_erg_diffusion": generation["use_erg_diffusion"],
            "guidance_scale_text": 0.0,
            "guidance_scale_lyric": 0.0,
        }
        if observed != expected:
            raise AceEngineError(f"ACE diffusion call differs from frozen subset: {observed}")
        if (
            oss_steps
            or add_retake_noise
            or src_latents is not None
            or audio2audio_enable
            or ref_latents is not None
            or encoder_text_hidden_states_null is not None
        ):
            raise AceEngineError("unsupported ACE branch reached the state interposition")
        if not isinstance(random_generators, list) or len(random_generators) != 1:
            raise AceEngineError("state preflight requires exactly one ACE generator")

        import torch
        from acestep.apg_guidance import cfg_forward
        from acestep.pipeline_ace_step import retrieve_timesteps
        from acestep.schedulers.scheduling_flow_match_euler_discrete import (
            FlowMatchEulerDiscreteScheduler,
        )
        from diffusers.utils.torch_utils import randn_tensor

        self.grad_enabled_during_diffusion = torch.is_grad_enabled()
        if self.grad_enabled_during_diffusion:
            raise AceEngineError("ACE controlled diffusion must execute under torch.no_grad")

        scheduler = FlowMatchEulerDiscreteScheduler(num_train_timesteps=1000, shift=3.0)
        timesteps, number_steps = retrieve_timesteps(
            scheduler,
            num_inference_steps=infer_steps,
            device=pipeline.device,
            timesteps=None,
        )
        if number_steps != 30 or len(timesteps) != 30:
            raise AceEngineError("ACE runtime did not rebuild the frozen 30-transition schedule")
        frame_length = int(duration * 44100 / 512 / 8)
        target_latents = randn_tensor(
            shape=(encoder_text_hidden_states.shape[0], 8, 16, frame_length),
            generator=random_generators,
            device=pipeline.device,
            dtype=pipeline.dtype,
        )
        reconstructed_rng_state = random_generators[0].get_state().detach().cpu()
        attention_mask = torch.ones(
            encoder_text_hidden_states.shape[0],
            frame_length,
            device=pipeline.device,
            dtype=pipeline.dtype,
        )
        start_idx = int(number_steps * ((1 - guidance_interval) / 2))
        end_idx = int(number_steps * (guidance_interval / 2 + 0.5))
        if (start_idx, end_idx) != (7, 22):
            raise AceEngineError("ACE guidance interval indices changed")

        encoder_hidden_states, encoder_hidden_mask = pipeline.ace_step_transformer.encode(
            encoder_text_hidden_states,
            text_attention_mask,
            speaker_embds,
            lyric_token_ids,
            lyric_mask,
        )
        encoder_hidden_states_null, _ = pipeline.ace_step_transformer.encode(
            torch.zeros_like(encoder_text_hidden_states),
            text_attention_mask,
            torch.zeros_like(speaker_embds),
            torch.zeros_like(lyric_token_ids),
            lyric_mask,
        )
        conditioning_tensors = {
            "encoder_text_hidden_states": encoder_text_hidden_states,
            "text_attention_mask": text_attention_mask,
            "speaker_embeds": speaker_embds,
            "lyric_token_ids": lyric_token_ids,
            "lyric_mask": lyric_mask,
            "attention_mask": attention_mask,
            "encoder_hidden_states": encoder_hidden_states,
            "encoder_hidden_mask": encoder_hidden_mask,
            "encoder_hidden_states_null": encoder_hidden_states_null,
        }
        self.conditioning_sha256, self.conditioning_tensor_sha256 = _tensor_bundle_sha256(
            conditioning_tensors
        )
        schedule_identity = {
            "timesteps_sha256": _tensor_sha256(timesteps.detach().float().cpu()),
            "sigmas_sha256": _tensor_sha256(scheduler.sigmas.detach().float().cpu()),
            "scheduler": "FlowMatchEulerDiscreteScheduler",
            "num_train_timesteps": 1000,
            "shift": 3.0,
            "omega_scale": float(omega_scale),
        }
        self.runtime_schedule_sha256 = json_sha256(schedule_identity)
        self.runtime_rng_state_sha256 = _tensor_sha256(reconstructed_rng_state)

        first_index = 0
        if self.resume is not None:
            metadata = self.resume.metadata
            checks = {
                "conditioning_sha256": self.conditioning_sha256,
                "runtime_schedule_sha256": self.runtime_schedule_sha256,
                "runtime_rng_state_sha256": self.runtime_rng_state_sha256,
                "request_sha256": json_sha256(dict(self.request)),
                "config_sha256": self.contract.sha256,
            }
            for key, actual in checks.items():
                if metadata.get(key) != actual:
                    raise AceEngineError(f"child-rebuilt ACE identity changed: {key}")
            if _tensor_sha256(self.resume.timesteps) != schedule_identity["timesteps_sha256"]:
                raise AceEngineError("checkpoint/runtime ACE timestep schedule differs")
            if _tensor_sha256(self.resume.sigmas) != schedule_identity["sigmas_sha256"]:
                raise AceEngineError("checkpoint/runtime ACE sigma schedule differs")
            first_index = int(metadata["next_scheduler_index"])
            target_latents = self.resume.latent.to(
                device=pipeline.device, dtype=pipeline.dtype
            )
            random_generators[0].set_state(self.resume.generator_state)
            scheduler.set_begin_index(first_index)

        for index in range(first_index, number_steps):
            timestep_value = timesteps[index]
            latent_model_input = target_latents
            timestep = timestep_value.expand(latent_model_input.shape[0])
            if start_idx <= index < end_idx:
                conditional = pipeline.ace_step_transformer.decode(
                    hidden_states=latent_model_input,
                    attention_mask=attention_mask,
                    encoder_hidden_states=encoder_hidden_states,
                    encoder_hidden_mask=encoder_hidden_mask,
                    output_length=latent_model_input.shape[-1],
                    timestep=timestep,
                ).sample
                unconditional = pipeline.ace_step_transformer.decode(
                    hidden_states=latent_model_input,
                    attention_mask=attention_mask,
                    encoder_hidden_states=encoder_hidden_states_null,
                    encoder_hidden_mask=encoder_hidden_mask,
                    output_length=latent_model_input.shape[-1],
                    timestep=timestep,
                ).sample
                noise_prediction = cfg_forward(
                    cond_output=conditional,
                    uncond_output=unconditional,
                    cfg_strength=guidance_scale,
                )
                self.actual_nfe += 2
            else:
                noise_prediction = pipeline.ace_step_transformer.decode(
                    hidden_states=latent_model_input,
                    attention_mask=attention_mask,
                    encoder_hidden_states=encoder_hidden_states,
                    encoder_hidden_mask=encoder_hidden_mask,
                    output_length=latent_model_input.shape[-1],
                    timestep=timestep,
                ).sample
                self.actual_nfe += 1
            target_latents = scheduler.step(
                model_output=noise_prediction,
                timestep=timestep_value,
                sample=target_latents,
                return_dict=False,
                omega=omega_scale,
                generator=random_generators[0],
            )[0]
            completed = index + 1
            if self.state_dir is not None and completed in CHECKPOINT_COMPLETED_TRANSITIONS:
                checkpoint_index = CHECKPOINT_COMPLETED_TRANSITIONS.index(completed)
                if self.actual_nfe != CHECKPOINT_CUMULATIVE_NFE[checkpoint_index]:
                    raise AceEngineError("runtime NFE differs at a frozen ACE checkpoint")
                if scheduler.step_index != completed:
                    raise AceEngineError("runtime scheduler index differs at ACE checkpoint")
                checkpoint_path = self.state_dir / f"checkpoint-{completed:02d}.pt"
                metadata = {
                    "schema_version": 2,
                    "model_id": MODEL_ID,
                    "config_sha256": self.contract.sha256,
                    "request_sha256": json_sha256(dict(self.request)),
                    "checkpoint_fraction": CHECKPOINT_FRACTIONS[checkpoint_index],
                    "completed_scheduler_transitions": completed,
                    "next_scheduler_index": completed,
                    "cumulative_transformer_nfe": CHECKPOINT_CUMULATIVE_NFE[checkpoint_index],
                    "total_scheduler_transitions": number_steps,
                    "total_transformer_nfe": 45,
                    "latent_export_dtype": "float32",
                    "conditioning_sha256": self.conditioning_sha256,
                    "conditioning_tensor_sha256": self.conditioning_tensor_sha256,
                    "runtime_schedule_sha256": self.runtime_schedule_sha256,
                    "runtime_schedule_identity": schedule_identity,
                    "runtime_rng_state_sha256": self.runtime_rng_state_sha256,
                    "scheduler_step_index": scheduler.step_index,
                    "source_pipeline_sha256": self.contract.raw["engine"][
                        "upstream_pipeline_sha256"
                    ],
                    "source_scheduler_sha256": self.contract.raw["engine"][
                        "upstream_scheduler_sha256"
                    ],
                    "parent_pid": os.getpid(),
                }
                artifact = save_ace_checkpoint(
                    checkpoint_path,
                    latent=target_latents.detach().float().cpu(),
                    timesteps=timesteps,
                    sigmas=scheduler.sigmas,
                    generator_state=random_generators[0].get_state(),
                    metadata=metadata,
                )
                self.checkpoints.append(artifact)

        expected_nfe = 45 if self.resume is None else 45 - int(
            self.resume.metadata["cumulative_transformer_nfe"]
        )
        if self.actual_nfe != expected_nfe:
            raise AceEngineError(
                f"ACE controlled loop observed {self.actual_nfe} NFE, expected {expected_nfe}"
            )
        self.terminal_latent_sha256 = _tensor_sha256(target_latents.detach().float().cpu())
        return target_latents


class ProductionAceStateEngine:
    """Production implementation, instantiated only after one-shot consumption."""

    def __init__(self, context: Mapping[str, Any]) -> None:
        repository_root = Path(str(context["repository_root"])).resolve(strict=True)
        self.contract = validate_static_config(
            Path(str(context["config_path"])), repository_root=repository_root
        )
        if context.get("config_sha256") != self.contract.sha256:
            raise AceEngineError("engine context configuration hash changed")
        execution_scope = context.get("execution_scope", "PREFLIGHT_ONE_SHOT")
        if execution_scope == "FORMAL_INITIAL_SURVIVOR_GROUP":
            from state_capture.ace_formal_contract import validate_formal_backend_invocation

            claim, call_claim = validate_formal_backend_invocation(context)
            if claim.get("preflight_config_sha256") != self.contract.sha256:
                raise AceEngineError("formal claim preflight-engine configuration differs")
            self._formal_call_kind: str | None = str(call_claim["call_kind"])
            self._formal_request_sha256: str | None = str(call_claim["request_sha256"])
            self._formal_call_consumed = False
            self._formal_context: dict[str, Any] | None = dict(context)
        elif execution_scope == "PREFLIGHT_ONE_SHOT":
            claim_path = Path(str(context["attempt_claim_path"])).resolve(strict=True)
            claim = validate_attempt_claim(claim_path)
            if sha256_file(claim_path) != context.get("attempt_claim_sha256"):
                raise AceEngineError("engine context attempt claim hash changed")
            if claim.get("config_sha256") != self.contract.sha256:
                raise AceEngineError("attempt claim configuration differs from engine")
            self._formal_call_kind = None
            self._formal_request_sha256 = None
            self._formal_call_consumed = False
            self._formal_context = None
        else:
            raise AceEngineError("unsupported ACE state-engine execution scope")
        self.repository_root = repository_root
        self.run_dir = Path(str(context["run_dir"])).resolve()
        self._attempt_claim = claim
        self._adapter: Any | None = None
        self._pipeline: Any | None = None
        capability = inspect_production_capability(self.contract)
        if capability["status"] != "READY":
            failures = "; ".join(capability["failures"])
            raise AceEngineError(f"ACE production capability is blocked: {failures}")
        self.capability = capability

    def _require_post_load_headroom(self) -> Mapping[str, Any]:
        """Recheck reserve and neighbors after load, before transformer inference."""

        from benchmark_core.config import PlacementConfig
        from benchmark_core.placement import NvidiaSmiProbe

        placement = self.contract.raw["placement"]
        configured = PlacementConfig(
            node=str(self._attempt_claim["node"]),
            physical_gpu_id=int(self._attempt_claim["physical_gpu_id"]),
            logical_gpu_id=0,
            tp_width=1,
            replica_count=1,
            minimum_free_vram_bytes=int(placement["minimum_free_vram_bytes"]),
            post_load_reserve_bytes=int(placement["post_load_reserve_bytes"]),
            lock_root=Path(placement["cooperative_lock_root"]),
            required_gpu_name_substring=str(placement["required_gpu_name_substring"]),
            maximum_idle_utilization_percent=int(
                placement["maximum_idle_utilization_percent"]
            ),
        )
        observation = NvidiaSmiProbe(configured).require_safe(
            minimum_free_vram_bytes=configured.post_load_reserve_bytes,
            allowed_pids={os.getpid(), os.getppid()},
            maximum_utilization_percent=None,
        )
        return {
            "node": observation.node,
            "physical_gpu_id": observation.physical_gpu_id,
            "gpu_uuid": observation.gpu_uuid,
            "gpu_name": observation.gpu_name,
            "free_vram_bytes": observation.free_vram_bytes,
            "total_vram_bytes": observation.total_vram_bytes,
            "utilization_percent": observation.utilization_percent,
            "compute_pids": list(observation.compute_pids),
            "minimum_post_load_reserve_bytes": configured.post_load_reserve_bytes,
        }

    def _load_pipeline(self) -> tuple[Any, float, dict[str, Any]]:
        if self._pipeline is not None:
            return self._pipeline, 0.0, {"status": "ALREADY_RESIDENT"}
        source_dir = Path(os.environ["ACE_STEP_V1_SOURCE_DIR"]).resolve(strict=True)
        if str(source_dir) not in os.sys.path:
            os.sys.path.insert(0, str(source_dir))
        source_root = self.repository_root / "src"
        if str(source_root) not in os.sys.path:
            os.sys.path.insert(0, str(source_root))
        from backbones.ace_step_v1 import AceStepV1Adapter

        adapter = AceStepV1Adapter(
            config_path=self.repository_root / "configs/backbones/ace_step_v1.json",
            evidence_dir=self.run_dir / "adapter-preflight",
            device="cuda:0",
        )
        preflight = adapter.preflight()
        started = time.perf_counter()
        adapter._ensure_loaded()  # noqa: SLF001 - frozen adapter has no public load-only surface
        load_seconds = time.perf_counter() - started
        pipeline = adapter._pipeline  # noqa: SLF001 - controlled one-off engine integration
        if pipeline is None:
            raise AceEngineError("ACE adapter returned without a loaded pipeline")
        self._adapter = adapter
        self._pipeline = pipeline
        return pipeline, load_seconds, {
            "status": preflight.status,
            "model_id": preflight.model_id,
            "config_sha256": preflight.config_sha256,
            "details": dict(preflight.details),
        }

    @staticmethod
    def _verify_transformer_residency(pipeline: Any) -> dict[str, Any]:
        """Prove the dropped upstream offload wrapper is a frozen no-op."""

        if getattr(pipeline, "cpu_offload", None) is not False:
            raise AceEngineError(
                "state interposition requires frozen cpu_offload=False semantics"
            )
        transformer = getattr(pipeline, "ace_step_transformer", None)
        if transformer is None:
            raise AceEngineError("ACE pipeline lacks ace_step_transformer")
        expected_device = str(pipeline.device)
        observed: list[dict[str, str]] = []
        for kind, iterator in (
            ("parameter", transformer.named_parameters(recurse=True)),
            ("buffer", transformer.named_buffers(recurse=True)),
        ):
            for name, tensor in iterator:
                observed.append({"kind": kind, "name": name, "device": str(tensor.device)})
        if not observed:
            raise AceEngineError("ACE transformer has no parameters or buffers to verify")
        mismatches = [row for row in observed if row["device"] != expected_device]
        if mismatches:
            sample = mismatches[:5]
            raise AceEngineError(
                f"ACE transformer is not fully resident on {expected_device}: {sample}"
            )
        return {
            "cpu_offload": False,
            "expected_device": expected_device,
            "tensor_count": len(observed),
            "all_parameters_and_buffers_on_expected_device": True,
            "upstream_cpu_offload_decorator_effect": "NO_OP_WHEN_CPU_OFFLOAD_IS_FALSE",
        }

    @staticmethod
    def _invoke_pipeline_no_grad(pipeline: Any, kwargs: Mapping[str, Any]) -> Any:
        """Reproduce the upstream diffusion method's torch.no_grad decorator."""

        import torch

        with torch.no_grad():
            return pipeline(**dict(kwargs))

    def _run(
        self,
        *,
        request: Mapping[str, Any],
        output_path: Path,
        state_dir: Path | None,
        resume: LoadedAceCheckpoint | None,
    ) -> Mapping[str, Any]:
        from backbones.runtime import CudaTelemetry

        if output_path.exists():
            raise FileExistsError(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if state_dir is not None:
            state_dir.mkdir(parents=True, exist_ok=False)
        controller = _FrozenDiffusionController(
            contract=self.contract,
            request=request,
            state_dir=state_dir,
            resume=resume,
        )
        telemetry = CudaTelemetry("cuda:0")
        with telemetry.measured() as measured:
            pipeline, load_seconds, preflight = self._load_pipeline()
            transformer_residency = self._verify_transformer_residency(pipeline)
            post_load_headroom = self._require_post_load_headroom()
            original = pipeline.text2music_diffusion_process
            pipeline.text2music_diffusion_process = types.MethodType(controller, pipeline)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix="ace-state-", suffix=".wav", dir=output_path.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            temporary.unlink()
            try:
                generation = self.contract.raw["frozen_generation"]
                result = self._invoke_pipeline_no_grad(
                    pipeline,
                    {
                        "format": generation["format"],
                        "audio_duration": generation["audio_duration_seconds"],
                        "prompt": request["prompt"],
                        "lyrics": generation["lyrics"],
                        "infer_step": generation["inference_steps"],
                        "guidance_scale": generation["guidance_scale"],
                        "omega_scale": generation["omega_scale"],
                        "manual_seeds": [request["seed"]],
                        "scheduler_type": generation["scheduler_type"],
                        "cfg_type": generation["cfg_type"],
                        "guidance_interval": generation["guidance_interval"],
                        "guidance_interval_decay": generation[
                            "guidance_interval_decay"
                        ],
                        "min_guidance_scale": generation["min_guidance_scale"],
                        "use_erg_tag": generation["use_erg_tag"],
                        "use_erg_lyric": generation["use_erg_lyric"],
                        "use_erg_diffusion": generation["use_erg_diffusion"],
                        "save_path": str(temporary),
                    },
                )
            finally:
                pipeline.text2music_diffusion_process = original
            if not temporary.is_file():
                raise AceEngineError(
                    "ACE official pipeline returned without retained temporary WAV"
                )
            write_bytes_exclusive(output_path, temporary.read_bytes())
            with suppress(FileNotFoundError):
                temporary.unlink()
            with suppress(FileNotFoundError):
                temporary.with_name(f"{temporary.stem}_input_params.json").unlink()
        result_paths = result[:-1] if isinstance(result, list) and result else []
        return {
            "format": ENGINE_RESULT_FORMAT,
            "status": "PASS",
            "pid": os.getpid(),
            "mode": "REFERENCE" if resume is None else "RESUME",
            "model_id": MODEL_ID,
            "output_path": str(output_path.resolve()),
            "output_sha256": sha256_file(output_path),
            "checkpoint_source_path": str(resume.path) if resume is not None else None,
            "checkpoint_source_sha256": resume.artifact_sha256 if resume is not None else None,
            "checkpoints": controller.checkpoints,
            "conditioning_sha256": controller.conditioning_sha256,
            "runtime_schedule_sha256": controller.runtime_schedule_sha256,
            "runtime_rng_state_sha256": controller.runtime_rng_state_sha256,
            "terminal_latent_sha256": controller.terminal_latent_sha256,
            "actual_nfe": controller.actual_nfe,
            "load_seconds": load_seconds,
            "gpu_seconds": float(measured["wall_seconds"]),
            "peak_allocated_bytes": int(measured["peak_allocated_bytes"]),
            "peak_reserved_bytes": int(measured["peak_reserved_bytes"]),
            "adapter_preflight": preflight,
            "transformer_residency": transformer_residency,
            "grad_enabled_during_diffusion": controller.grad_enabled_during_diffusion,
            "post_load_headroom": post_load_headroom,
            "official_pipeline_returned_paths": [str(path) for path in result_paths],
            "execution_surface": "HASH_GUARDED_CONTROLLED_DIFFUSION_METHOD_INTERPOSITION",
        }

    def run_reference(
        self,
        *,
        request: Mapping[str, Any],
        output_path: Path,
        state_dir: Path,
    ) -> Mapping[str, Any]:
        if self._formal_call_kind is not None:
            if self._formal_call_kind != "PREFIX_GROUP" or self._formal_call_consumed:
                raise AceEngineError("formal reference lacks its unconsumed prefix-call claim")
            from state_capture.ace_formal_contract import validate_formal_backend_invocation

            validate_formal_backend_invocation(self._formal_context or {})
            self._formal_call_consumed = True
        return self._run(
            request=request,
            output_path=output_path,
            state_dir=state_dir,
            resume=None,
        )

    def run_resume(
        self,
        *,
        request: Mapping[str, Any],
        checkpoint_path: Path,
        output_path: Path,
    ) -> Mapping[str, Any]:
        if self._formal_call_kind is not None:
            if (
                self._formal_call_kind != "RESUME_UNIT"
                or self._formal_call_consumed
                or request.get("request_id") != self._formal_request_sha256
            ):
                raise AceEngineError("formal resume lacks its exact unconsumed unit-call claim")
            from state_capture.ace_formal_contract import validate_formal_backend_invocation

            validate_formal_backend_invocation(self._formal_context or {})
            self._formal_call_consumed = True
        checkpoint = load_ace_checkpoint(
            checkpoint_path,
            expected_artifact_sha256=request.get("checkpoint_sha256"),
            expected_config_sha256=self.contract.sha256,
        )
        return self._run(
            request=request["reference_request"],
            output_path=output_path,
            state_dir=None,
            resume=checkpoint,
        )

    def decode_preview(
        self,
        *,
        checkpoint_path: Path,
        checkpoint_sha256: str,
        output_path: Path,
    ) -> Mapping[str, Any]:
        """Decode only this root's exported checkpoint into a pre-action preview."""

        if self._formal_call_kind not in {None, "PREFIX_GROUP"}:
            raise AceEngineError("formal preview decode must use the root prefix-call engine")
        if self._formal_context is not None:
            from state_capture.ace_formal_contract import validate_formal_backend_invocation

            validate_formal_backend_invocation(self._formal_context)
        if output_path.exists():
            raise FileExistsError(output_path)
        checkpoint = load_ace_checkpoint(
            checkpoint_path,
            expected_artifact_sha256=checkpoint_sha256,
            expected_config_sha256=self.contract.sha256,
        )
        from backbones.runtime import CudaTelemetry

        telemetry = CudaTelemetry("cuda:0")
        with telemetry.measured() as measured:
            pipeline, _load_seconds, _preflight = self._load_pipeline()
            latent = checkpoint.latent.to(device=pipeline.device, dtype=pipeline.dtype)
            sample_rate, waveforms = pipeline.music_dcae.decode(latent, sr=48000)
        if sample_rate != 48000 or not isinstance(waveforms, list) or len(waveforms) != 1:
            raise AceEngineError("ACE checkpoint preview decode returned an invalid batch")
        waveform = waveforms[0]
        if hasattr(waveform, "detach"):
            waveform = waveform.detach().float().cpu().numpy()
        import numpy as np
        import soundfile as sf

        array = np.asarray(waveform, dtype=np.float32)
        if array.ndim != 2 or array.shape[0] != 2:
            raise AceEngineError("ACE checkpoint preview must decode to stereo channels-first")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="ace-preview-", suffix=".wav", dir=output_path.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            sf.write(temporary, array.T, sample_rate, subtype="FLOAT")
            write_bytes_exclusive(output_path, temporary.read_bytes())
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
        return {
            "checkpoint_path": str(checkpoint.path),
            "checkpoint_sha256": checkpoint.artifact_sha256,
            "format": "ace-step-v1-root-local-preview-v2",
            "output_path": str(output_path.resolve()),
            "output_sha256": sha256_file(output_path),
            "gpu_seconds": float(measured["wall_seconds"]),
            "peak_allocated_bytes": int(measured["peak_allocated_bytes"]),
            "peak_reserved_bytes": int(measured["peak_reserved_bytes"]),
            "root_local_only": True,
            "sample_rate": sample_rate,
            "status": "PASS",
        }

    def close(self) -> None:
        pipeline = self._pipeline
        self._pipeline = None
        if self._adapter is not None:
            self._adapter._pipeline = None  # noqa: SLF001 - release parent before resume child
        self._adapter = None
        del pipeline
        gc.collect()
        with suppress(Exception):
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize("cuda:0")
                torch.cuda.empty_cache()


def production_engine_factory(context: Mapping[str, Any]) -> ProductionAceStateEngine:
    """Factory referenced by the frozen config and separate child requests."""

    return ProductionAceStateEngine(context)


def formal_engine_factory(context: Mapping[str, Any]) -> ProductionAceStateEngine:
    """D-0036 formal factory; requires a distinct survivor-group claim."""

    if context.get("execution_scope") != "FORMAL_INITIAL_SURVIVOR_GROUP":
        raise AceEngineError("formal engine factory lacks formal execution scope")
    return ProductionAceStateEngine(context)


def build_engine_context(
    *,
    contract: LoadedContract,
    repository_root: Path,
    run_dir: Path,
    attempt_claim_path: Path,
) -> dict[str, Any]:
    validate_attempt_claim(attempt_claim_path)
    return {
        "repository_root": str(repository_root.resolve(strict=True)),
        "config_path": str(contract.path),
        "config_sha256": contract.sha256,
        "run_dir": str(run_dir.resolve()),
        "attempt_claim_path": str(attempt_claim_path.resolve(strict=True)),
        "attempt_claim_sha256": sha256_file(attempt_claim_path),
    }


def validate_engine_result(result: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    value = dict(result)
    if value.get("format") != ENGINE_RESULT_FORMAT or value.get("status") != "PASS":
        raise ArtifactValidationError("engine result format/status is invalid")
    if value.get("mode") != mode or value.get("model_id") != MODEL_ID:
        raise ArtifactValidationError("engine result mode/model identity changed")
    output = Path(str(value.get("output_path", ""))).resolve(strict=True)
    if value.get("output_sha256") != sha256_file(output):
        raise ArtifactValidationError("engine output hash changed")
    for key in ("gpu_seconds", "peak_allocated_bytes", "peak_reserved_bytes", "actual_nfe"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
            raise ArtifactValidationError(f"engine result {key} is invalid")
    return value

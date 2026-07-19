"""Exact, checkpointable Stable Audio 3 Euler transitions.

The transition in :func:`run_euler_transitions` mirrors
``stable_audio_3.inference.sampling.sample_discrete_euler`` at stable-audio-3
commit ``0385302ea26522f00c80392c4b708df5ebf1adf5``.  In particular, callbacks
observe the pre-transition latent and checkpoints observe the post-transition
latent.  The latter distinction is what makes ``next_step_index`` unambiguous.

This module deliberately does not load a model or build conditioning.  The
sampler adapters near the end can be injected into the official ``generate``
path, leaving that path responsible for model loading, conditioning, noise, and
schedule construction.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

TOTAL_EULER_STEPS = 50
CHECKPOINT_COMPLETED_STEPS = (15, 30, 40)
UPSTREAM_STABLE_AUDIO_3_COMMIT = "0385302ea26522f00c80392c4b708df5ebf1adf5"
UPSTREAM_EULER_SYMBOL = "stable_audio_3.inference.sampling.sample_discrete_euler"

CHECKPOINT_FORMAT = "sa3-euler-checkpoint-v1"
RESUME_REQUEST_FORMAT = "sa3-euler-resume-request-v1"
RESUME_RESULT_FORMAT = "sa3-euler-resume-result-v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PREFIX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class CheckpointValidationError(ValueError):
    """Raised when a checkpoint or resume result fails an integrity check."""


class ChildResumeError(RuntimeError):
    """Raised when a separate resume process does not complete successfully."""


@dataclass(frozen=True)
class CheckpointArtifact:
    """Paths and integrity fields for one newly written checkpoint."""

    path: Path
    state_metadata_path: Path
    completed_steps: int
    next_step_index: int
    latent_sha256: str
    schedule_sha256: str
    checkpoint_sha256: str


@dataclass(frozen=True)
class EulerCheckpointState:
    """Verified state loaded from a checkpoint artifact."""

    latent: torch.Tensor
    schedule: torch.Tensor
    next_step_index: int
    metadata: Mapping[str, Any]
    path: Path
    checkpoint_sha256: str


@dataclass(frozen=True)
class EulerRunResult:
    """A completed (possibly partial) interval of the 50-step Euler path."""

    latent: torch.Tensor
    start_step_index: int
    completed_steps: int
    forward_calls: int
    checkpoints: tuple[CheckpointArtifact, ...] = ()


@dataclass
class ResumeRuntime:
    """Objects recomputed by a child-process runtime factory.

    A factory referenced by a resume request receives ``(request, checkpoint)``
    and returns this object.  There are two execution modes:

    * Set ``model`` for a direct call to :func:`run_euler_transitions` using the
      schedule stored in the checkpoint.
    * Set ``invoke_generate`` for official-API injection.  The child passes it
      a :class:`ResumingEulerSampler`; the callable must patch/inject that
      sampler and invoke the official ``generate`` call.  The sampler validates
      the freshly rebuilt full schedule and ignores only ``generate``'s fresh
      initial latent.

    ``finalize`` may decode/write retained output.  It is called as
    ``finalize(final_latent, generated_output, checkpoint, request)`` and must
    return JSON-serializable metadata, not tensor data.
    """

    conditioning_sha256: str
    config_sha256: str
    model: Callable[..., torch.Tensor] | None = None
    model_kwargs: Mapping[str, Any] = field(default_factory=dict)
    device: str | torch.device = "cpu"
    invoke_generate: Callable[[Callable[..., torch.Tensor]], Any] | None = None
    finalize: (
        Callable[
            [torch.Tensor, Any, EulerCheckpointState, Mapping[str, Any]],
            Mapping[str, Any],
        ]
        | None
    ) = None


@dataclass(frozen=True)
class ResumeArtifact:
    """A verified terminal latent emitted by a child process."""

    path: Path
    state_metadata_path: Path
    latent: torch.Tensor
    metadata: Mapping[str, Any]
    artifact_sha256: str


@dataclass(frozen=True)
class LaunchedResume:
    """Subprocess evidence plus its verified result artifact."""

    process: subprocess.CompletedProcess[str]
    artifact: ResumeArtifact


def utc_now() -> str:
    """Return a stable UTC timestamp representation for artifact metadata."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    """Hash a file without loading it all into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_sha256(value: Any) -> str:
    """Hash a JSON-serializable identity using a canonical encoding."""

    encoded = _json_bytes(value, trailing_newline=False)
    return hashlib.sha256(encoded).hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    """Hash tensor dtype, shape, and contiguous CPU bytes.

    Device is intentionally excluded: a checkpoint moved from an A800 to CPU
    for storage must retain the same tensor identity.
    """

    if not isinstance(tensor, torch.Tensor):
        raise TypeError(f"expected torch.Tensor, got {type(tensor).__name__}")
    if tensor.layout != torch.strided:
        raise TypeError(f"only strided tensors are supported, got {tensor.layout}")

    canonical = tensor.detach().to(device="cpu").contiguous()
    digest = hashlib.sha256()
    digest.update(b"sa3-tensor-v1\0")
    digest.update(str(canonical.dtype).encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(list(canonical.shape), separators=(",", ":")).encode("ascii"))
    digest.update(b"\0")
    digest.update(canonical.view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def _json_bytes(value: Any, *, trailing_newline: bool = True) -> bytes:
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(f"metadata must be finite JSON data: {exc}") from exc
    if trailing_newline:
        text += "\n"
    return text.encode("utf-8")


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _state_metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.state.json")


def _write_bytes_no_clobber(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Atomically publish bytes without ever replacing an existing path."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{os.urandom(8).hex()}"
    temporary = path.with_name(f".{path.name}.tmp-{token}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard-link is an atomic create-if-absent operation.  Unlike replace,
        # it cannot overwrite a checkpoint from an earlier run.
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _torch_save_bytes(payload: Mapping[str, Any]) -> bytes:
    buffer = io.BytesIO()
    torch.save(dict(payload), buffer)
    return buffer.getvalue()


def _torch_load_mapping(path: Path) -> Mapping[str, Any]:
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:  # pragma: no cover - compatibility with older supported torch builds
        payload = torch.load(path, map_location="cpu")
    if not isinstance(payload, Mapping):
        raise CheckpointValidationError("torch artifact payload is not a mapping")
    return payload


def _validate_schedule(schedule: torch.Tensor) -> None:
    if not isinstance(schedule, torch.Tensor):
        raise TypeError("schedule must be a torch.Tensor")
    if schedule.ndim not in (1, 2):
        raise ValueError(f"schedule must be 1D or 2D, got shape {tuple(schedule.shape)}")
    if schedule.shape[-1] != TOTAL_EULER_STEPS + 1:
        raise ValueError(
            f"the frozen base path requires 51 schedule points for 50 transitions, "
            f"got {schedule.shape[-1]}"
        )
    if not schedule.is_floating_point():
        raise TypeError(f"schedule must be floating point, got {schedule.dtype}")
    if not bool(torch.isfinite(schedule).all().item()):
        raise ValueError("schedule contains a non-finite value")


def _validate_latent_and_schedule(latent: torch.Tensor, schedule: torch.Tensor) -> None:
    if not isinstance(latent, torch.Tensor):
        raise TypeError("latent must be a torch.Tensor")
    if latent.ndim != 3:
        raise ValueError(f"SA3 latent must have shape (batch, channels, time), got {latent.shape}")
    if not latent.is_floating_point():
        raise TypeError(f"latent must be floating point, got {latent.dtype}")
    _validate_schedule(schedule)
    if schedule.ndim == 2 and schedule.shape[0] != latent.shape[0]:
        raise ValueError(
            "per-element schedule batch does not match latent batch: "
            f"{schedule.shape[0]} != {latent.shape[0]}"
        )


def save_euler_checkpoint(
    path: str | Path,
    *,
    latent: torch.Tensor,
    schedule: torch.Tensor,
    next_step_index: int,
    run_id: str,
    conditioning_sha256: str,
    config_sha256: str,
    run_metadata: Mapping[str, Any] | None = None,
) -> CheckpointArtifact:
    """Write one self-describing, no-clobber Euler checkpoint.

    Tensors are stored on CPU for process/device portability.  Tensor hashes
    include dtype and shape; the adjacent ``.state.json`` additionally records
    the SHA-256 of the serialized checkpoint file.  Project-level provenance
    remains a separate ``.provenance.json`` record.
    """

    path = Path(path)
    state_path = _state_metadata_path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite checkpoint: {path}")
    if state_path.exists():
        raise FileExistsError(f"refusing to overwrite checkpoint metadata: {state_path}")
    if next_step_index not in range(1, TOTAL_EULER_STEPS + 1):
        raise ValueError(f"next_step_index must be in [1, 50], got {next_step_index}")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    conditioning_sha256 = _require_sha256(conditioning_sha256, "conditioning_sha256")
    config_sha256 = _require_sha256(config_sha256, "config_sha256")
    _validate_latent_and_schedule(latent, schedule)

    latent_cpu = latent.detach().to(device="cpu").contiguous()
    schedule_cpu = schedule.detach().to(device="cpu").contiguous()
    metadata: dict[str, Any] = {
        "format": CHECKPOINT_FORMAT,
        "provenance_label": "latent_checkpoint",
        "created_at_utc": utc_now(),
        "exporter_pid": os.getpid(),
        "run_id": run_id,
        "upstream_commit": UPSTREAM_STABLE_AUDIO_3_COMMIT,
        "upstream_euler_symbol": UPSTREAM_EULER_SYMBOL,
        "total_steps": TOTAL_EULER_STEPS,
        "completed_steps": next_step_index,
        "next_step_index": next_step_index,
        "completed_fraction": next_step_index / TOTAL_EULER_STEPS,
        "latent_dtype": str(latent_cpu.dtype),
        "latent_shape": list(latent_cpu.shape),
        "latent_device_at_export": str(latent.device),
        "latent_sha256": tensor_sha256(latent_cpu),
        "schedule_dtype": str(schedule_cpu.dtype),
        "schedule_shape": list(schedule_cpu.shape),
        "schedule_sha256": tensor_sha256(schedule_cpu),
        "conditioning_sha256": conditioning_sha256,
        "config_sha256": config_sha256,
        "run_metadata": dict(run_metadata or {}),
    }
    # Validate supplemental metadata before writing the tensor artifact.
    _json_bytes(metadata)
    payload = {
        "format": CHECKPOINT_FORMAT,
        "latent": latent_cpu,
        "schedule": schedule_cpu,
        "metadata": metadata,
    }
    _write_bytes_no_clobber(path, _torch_save_bytes(payload))
    checkpoint_sha256 = sha256_file(path)
    sidecar = {
        **metadata,
        "checkpoint_file": {
            "name": path.name,
            "sha256": checkpoint_sha256,
            "size_bytes": path.stat().st_size,
        },
    }
    _write_bytes_no_clobber(state_path, _json_bytes(sidecar), mode=0o644)
    return CheckpointArtifact(
        path=path,
        state_metadata_path=state_path,
        completed_steps=next_step_index,
        next_step_index=next_step_index,
        latent_sha256=metadata["latent_sha256"],
        schedule_sha256=metadata["schedule_sha256"],
        checkpoint_sha256=checkpoint_sha256,
    )


def load_euler_checkpoint(
    path: str | Path,
    *,
    expected_conditioning_sha256: str | None = None,
    expected_config_sha256: str | None = None,
    require_state_metadata: bool = True,
) -> EulerCheckpointState:
    """Load a checkpoint only after verifying its file and tensor hashes."""

    path = Path(path)
    payload = _torch_load_mapping(path)
    if payload.get("format") != CHECKPOINT_FORMAT:
        raise CheckpointValidationError(f"unsupported checkpoint format: {payload.get('format')!r}")
    metadata = payload.get("metadata")
    latent = payload.get("latent")
    schedule = payload.get("schedule")
    if not isinstance(metadata, Mapping):
        raise CheckpointValidationError("checkpoint metadata is missing or invalid")
    if not isinstance(latent, torch.Tensor) or not isinstance(schedule, torch.Tensor):
        raise CheckpointValidationError("checkpoint latent or schedule is missing")

    _validate_latent_and_schedule(latent, schedule)
    checkpoint_sha256 = sha256_file(path)
    if metadata.get("format") != CHECKPOINT_FORMAT:
        raise CheckpointValidationError("embedded checkpoint format does not match")
    if metadata.get("upstream_commit") != UPSTREAM_STABLE_AUDIO_3_COMMIT:
        raise CheckpointValidationError("checkpoint names an unexpected upstream commit")
    if metadata.get("total_steps") != TOTAL_EULER_STEPS:
        raise CheckpointValidationError("checkpoint does not describe the frozen 50-step path")

    next_step_index = metadata.get("next_step_index")
    if not isinstance(next_step_index, int) or next_step_index not in range(1, 51):
        raise CheckpointValidationError(f"invalid next_step_index: {next_step_index!r}")
    if metadata.get("completed_steps") != next_step_index:
        raise CheckpointValidationError("completed_steps and next_step_index disagree")

    expected_fields = {
        "latent_dtype": str(latent.dtype),
        "latent_shape": list(latent.shape),
        "latent_sha256": tensor_sha256(latent),
        "schedule_dtype": str(schedule.dtype),
        "schedule_shape": list(schedule.shape),
        "schedule_sha256": tensor_sha256(schedule),
    }
    for key, expected in expected_fields.items():
        if metadata.get(key) != expected:
            raise CheckpointValidationError(
                f"checkpoint {key} mismatch: recorded {metadata.get(key)!r}, actual {expected!r}"
            )

    for expected, key in (
        (expected_conditioning_sha256, "conditioning_sha256"),
        (expected_config_sha256, "config_sha256"),
    ):
        if expected is not None:
            _require_sha256(expected, f"expected_{key}")
            if metadata.get(key) != expected:
                raise CheckpointValidationError(
                    f"checkpoint {key} mismatch: {metadata.get(key)!r} != {expected!r}"
                )

    state_path = _state_metadata_path(path)
    if require_state_metadata or state_path.exists():
        try:
            sidecar = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise CheckpointValidationError(
                f"invalid checkpoint state metadata: {state_path}"
            ) from exc
        checkpoint_file = sidecar.get("checkpoint_file", {})
        if checkpoint_file.get("name") != path.name:
            raise CheckpointValidationError("checkpoint state metadata names a different file")
        if checkpoint_file.get("sha256") != checkpoint_sha256:
            raise CheckpointValidationError("serialized checkpoint SHA-256 mismatch")
        if checkpoint_file.get("size_bytes") != path.stat().st_size:
            raise CheckpointValidationError("serialized checkpoint size mismatch")
        for key, value in metadata.items():
            if sidecar.get(key) != value:
                raise CheckpointValidationError(f"embedded and adjacent metadata differ at {key}")

    return EulerCheckpointState(
        latent=latent,
        schedule=schedule,
        next_step_index=next_step_index,
        metadata=dict(metadata),
        path=path,
        checkpoint_sha256=checkpoint_sha256,
    )


@torch.no_grad()
def run_euler_transitions(
    model: Callable[..., torch.Tensor],
    latent: torch.Tensor,
    schedule: torch.Tensor,
    *,
    start_step_index: int = 0,
    stop_step_index: int = TOTAL_EULER_STEPS,
    model_kwargs: Mapping[str, Any] | None = None,
    callback: Callable[[Mapping[str, Any]], None] | None = None,
    checkpoint_dir: str | Path | None = None,
    checkpoint_prefix: str | None = None,
    checkpoint_completed_steps: tuple[int, ...] = CHECKPOINT_COMPLETED_STEPS,
    checkpoint_run_id: str | None = None,
    conditioning_sha256: str | None = None,
    config_sha256: str | None = None,
    checkpoint_run_metadata: Mapping[str, Any] | None = None,
    checkpoint_callback: Callable[[CheckpointArtifact], None] | None = None,
) -> EulerRunResult:
    """Run an exact interval of the frozen 50-step upstream Euler path.

    ``start_step_index`` is the next transition to execute and
    ``stop_step_index`` is exclusive.  Thus a checkpoint written after step 15
    contains the result of indices 0 through 14 and resumes at index 15.
    """

    _validate_latent_and_schedule(latent, schedule)
    if not 0 <= start_step_index <= stop_step_index <= TOTAL_EULER_STEPS:
        raise ValueError(
            "step interval must satisfy 0 <= start <= stop <= 50, got "
            f"{start_step_index}, {stop_step_index}"
        )
    boundaries = tuple(sorted(set(checkpoint_completed_steps)))
    if any(step not in range(1, TOTAL_EULER_STEPS + 1) for step in boundaries):
        raise ValueError(f"invalid checkpoint boundary in {boundaries}")

    if checkpoint_dir is not None:
        if checkpoint_prefix is None or _PREFIX_RE.fullmatch(checkpoint_prefix) is None:
            raise ValueError("checkpoint_prefix must be a simple 1-128 character filename prefix")
        if checkpoint_run_id is None:
            raise ValueError("checkpoint_run_id is required when checkpointing")
        if conditioning_sha256 is None or config_sha256 is None:
            raise ValueError(
                "conditioning_sha256 and config_sha256 are required when checkpointing"
            )
        _require_sha256(conditioning_sha256, "conditioning_sha256")
        _require_sha256(config_sha256, "config_sha256")

    x = latent
    t = schedule.to(x.device)
    per_element_schedule = t.dim() == 2
    extra_args = dict(model_kwargs or {})
    artifacts: list[CheckpointArtifact] = []

    for index in range(start_step_index, stop_step_index):
        if per_element_schedule:
            t_curr_tensor = t[:, index].to(x.dtype)
            t_next = t[:, index + 1].to(x.dtype)
            dt_broadcast = (t_next - t_curr_tensor).view(-1, 1, 1)
        else:
            t_curr = t[index]
            t_next = t[index + 1]
            t_curr_tensor = t_curr * torch.ones((x.shape[0],), dtype=x.dtype, device=x.device)
            dt_broadcast = t_next - t_curr

        velocity = model(x, t_curr_tensor, **extra_args)
        if not isinstance(velocity, torch.Tensor) or velocity.shape != x.shape:
            raise ValueError(
                "Euler model must return a tensor with the latent shape, got "
                f"{getattr(velocity, 'shape', None)} for {x.shape}"
            )
        if callback is not None:
            denoised = x - t_curr_tensor[:, None, None] * velocity
            callback(
                {
                    "x": x,
                    "t": t_curr_tensor,
                    "sigma": t_curr_tensor,
                    "i": index,
                    "denoised": denoised,
                }
            )

        # This is the exact update order used by upstream sample_discrete_euler.
        x = x + dt_broadcast * velocity
        completed_steps = index + 1

        if checkpoint_dir is not None and completed_steps in boundaries:
            checkpoint_path = Path(checkpoint_dir) / (
                f"{checkpoint_prefix}.step-{completed_steps:03d}.pt"
            )
            artifact = save_euler_checkpoint(
                checkpoint_path,
                latent=x,
                schedule=t,
                next_step_index=completed_steps,
                run_id=checkpoint_run_id or "",
                conditioning_sha256=conditioning_sha256 or "",
                config_sha256=config_sha256 or "",
                run_metadata=checkpoint_run_metadata,
            )
            artifacts.append(artifact)
            if checkpoint_callback is not None:
                checkpoint_callback(artifact)

    return EulerRunResult(
        latent=x,
        start_step_index=start_step_index,
        completed_steps=stop_step_index,
        forward_calls=stop_step_index - start_step_index,
        checkpoints=tuple(artifacts),
    )


class CheckpointingEulerSampler:
    """Upstream-signature sampler callable for a reference ``generate`` run."""

    def __init__(
        self,
        *,
        checkpoint_dir: str | Path,
        checkpoint_prefix: str,
        run_id: str,
        conditioning_sha256: str,
        config_sha256: str,
        run_metadata: Mapping[str, Any] | None = None,
        checkpoint_callback: Callable[[CheckpointArtifact], None] | None = None,
    ) -> None:
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_prefix = checkpoint_prefix
        self.run_id = run_id
        self.conditioning_sha256 = conditioning_sha256
        self.config_sha256 = config_sha256
        self.run_metadata = dict(run_metadata or {})
        self.checkpoint_callback = checkpoint_callback
        self.last_run_result: EulerRunResult | None = None

    def __call__(
        self,
        model: Callable[..., torch.Tensor],
        x: torch.Tensor,
        sigmas: torch.Tensor,
        callback: Callable[[Mapping[str, Any]], None] | None = None,
        disable_tqdm: bool = False,
        **extra_args: Any,
    ) -> torch.Tensor:
        # ``disable_tqdm`` is accepted for exact upstream call compatibility;
        # this engineering sampler intentionally emits no progress UI.
        del disable_tqdm
        result = run_euler_transitions(
            model,
            x,
            sigmas,
            model_kwargs=extra_args,
            callback=callback,
            checkpoint_dir=self.checkpoint_dir,
            checkpoint_prefix=self.checkpoint_prefix,
            checkpoint_run_id=self.run_id,
            conditioning_sha256=self.conditioning_sha256,
            config_sha256=self.config_sha256,
            checkpoint_run_metadata=self.run_metadata,
            checkpoint_callback=self.checkpoint_callback,
        )
        self.last_run_result = result
        return result.latent


class ResumingEulerSampler:
    """Upstream-signature sampler that resumes a verified saved latent.

    This is designed for sampler injection into a fresh official ``generate``
    call in a separate process.  The official path rebuilds conditioning and a
    full schedule.  This callable checks that schedule bit-for-bit against the
    saved one, checks the fresh latent's shape, ignores its values, preserves
    the checkpoint latent's dtype, and executes only transitions beginning at
    ``next_step_index``.

    The fresh noise dtype is deliberately not required to equal the checkpoint
    dtype.  The pinned upstream Euler path may promote the evolving latent
    after its first model call (the production reference promoted float16
    noise to float32), while every fresh official ``generate`` invocation
    still allocates float16 noise.  Casting the saved state back to that
    discarded noise dtype would change the resumed numerical trajectory.
    """

    def __init__(self, checkpoint: EulerCheckpointState) -> None:
        self.checkpoint = checkpoint
        self.last_run_result: EulerRunResult | None = None
        self.runtime_schedule_validated = False
        self.fresh_initial_latent_dtype: str | None = None
        self.checkpoint_latent_dtype = str(checkpoint.latent.dtype)
        self.resume_latent_dtype_preserved = False

    def __call__(
        self,
        model: Callable[..., torch.Tensor],
        x: torch.Tensor,
        sigmas: torch.Tensor,
        callback: Callable[[Mapping[str, Any]], None] | None = None,
        disable_tqdm: bool = False,
        **extra_args: Any,
    ) -> torch.Tensor:
        del disable_tqdm
        if self.last_run_result is not None:
            raise RuntimeError("a ResumingEulerSampler instance may be invoked only once")
        _validate_latent_and_schedule(x, sigmas)
        expected_shape = tuple(self.checkpoint.metadata["latent_shape"])
        expected_dtype = self.checkpoint.metadata["latent_dtype"]
        if tuple(x.shape) != expected_shape:
            raise CheckpointValidationError(
                f"fresh official latent shape {tuple(x.shape)} != checkpoint {expected_shape}"
            )
        if str(self.checkpoint.latent.dtype) != expected_dtype:
            raise CheckpointValidationError(
                "loaded checkpoint latent dtype no longer matches its verified metadata"
            )
        self.fresh_initial_latent_dtype = str(x.dtype)
        runtime_schedule_sha256 = tensor_sha256(sigmas)
        saved_schedule_sha256 = self.checkpoint.metadata["schedule_sha256"]
        if runtime_schedule_sha256 != saved_schedule_sha256:
            raise CheckpointValidationError(
                "fresh official full schedule does not match the checkpoint: "
                f"{runtime_schedule_sha256} != {saved_schedule_sha256}"
            )
        self.runtime_schedule_validated = True

        resumed_x = self.checkpoint.latent.to(device=x.device)
        self.resume_latent_dtype_preserved = str(resumed_x.dtype) == expected_dtype
        if not self.resume_latent_dtype_preserved:
            raise CheckpointValidationError(
                "moving the checkpoint latent to the runtime device changed its dtype"
            )
        result = run_euler_transitions(
            model,
            resumed_x,
            sigmas,
            start_step_index=self.checkpoint.next_step_index,
            model_kwargs=extra_args,
            callback=callback,
        )
        self.last_run_result = result
        return result.latent


def resume_euler_from_checkpoint(
    model: Callable[..., torch.Tensor],
    checkpoint: str | Path | EulerCheckpointState,
    *,
    device: str | torch.device,
    model_kwargs: Mapping[str, Any] | None = None,
    callback: Callable[[Mapping[str, Any]], None] | None = None,
    expected_conditioning_sha256: str | None = None,
    expected_config_sha256: str | None = None,
) -> EulerRunResult:
    """Directly resume a checkpoint using its verified stored schedule."""

    state = (
        checkpoint
        if isinstance(checkpoint, EulerCheckpointState)
        else load_euler_checkpoint(
            checkpoint,
            expected_conditioning_sha256=expected_conditioning_sha256,
            expected_config_sha256=expected_config_sha256,
        )
    )
    latent = state.latent.to(device=device)
    schedule = state.schedule.to(device=device)
    return run_euler_transitions(
        model,
        latent,
        schedule,
        start_step_index=state.next_step_index,
        model_kwargs=model_kwargs,
        callback=callback,
    )


def write_resume_request_no_clobber(
    path: str | Path,
    *,
    checkpoint_path: str | Path,
    result_path: str | Path,
    runtime_factory: str,
    conditioning_sha256: str,
    config_sha256: str,
    runtime_kwargs: Mapping[str, Any] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write the immutable JSON contract consumed by ``resume_child``."""

    path = Path(path)
    checkpoint_path = Path(checkpoint_path).resolve()
    result_path = Path(result_path).resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(checkpoint_path)
    if not isinstance(runtime_factory, str) or runtime_factory.count(":") != 1:
        raise ValueError("runtime_factory must have the form 'module.path:function_name'")
    conditioning_sha256 = _require_sha256(conditioning_sha256, "conditioning_sha256")
    config_sha256 = _require_sha256(config_sha256, "config_sha256")
    request = {
        "format": RESUME_REQUEST_FORMAT,
        "provenance_label": "latent_checkpoint",
        "created_at_utc": utc_now(),
        "parent_pid": os.getpid(),
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "result_path": str(result_path),
        "runtime_factory": runtime_factory,
        "runtime_kwargs": dict(runtime_kwargs or {}),
        "conditioning_sha256": conditioning_sha256,
        "config_sha256": config_sha256,
        "request_metadata": dict(request_metadata or {}),
    }
    _write_bytes_no_clobber(path, _json_bytes(request), mode=0o644)
    return path


def _save_resume_result_no_clobber(
    path: str | Path,
    *,
    latent: torch.Tensor,
    metadata: Mapping[str, Any],
) -> ResumeArtifact:
    path = Path(path)
    state_path = _state_metadata_path(path)
    if path.exists() or state_path.exists():
        existing = path if path.exists() else state_path
        raise FileExistsError(f"refusing to overwrite resume result: {existing}")
    latent_cpu = latent.detach().to(device="cpu").contiguous()
    complete_metadata = {
        **dict(metadata),
        "format": RESUME_RESULT_FORMAT,
        "latent_dtype": str(latent_cpu.dtype),
        "latent_shape": list(latent_cpu.shape),
        "latent_sha256": tensor_sha256(latent_cpu),
    }
    _json_bytes(complete_metadata)
    _write_bytes_no_clobber(
        path,
        _torch_save_bytes(
            {
                "format": RESUME_RESULT_FORMAT,
                "latent": latent_cpu,
                "metadata": complete_metadata,
            }
        ),
    )
    artifact_sha256 = sha256_file(path)
    sidecar = {
        **complete_metadata,
        "result_file": {
            "name": path.name,
            "sha256": artifact_sha256,
            "size_bytes": path.stat().st_size,
        },
    }
    _write_bytes_no_clobber(state_path, _json_bytes(sidecar), mode=0o644)
    return ResumeArtifact(
        path=path,
        state_metadata_path=state_path,
        latent=latent_cpu,
        metadata=complete_metadata,
        artifact_sha256=artifact_sha256,
    )


def load_resume_result(path: str | Path) -> ResumeArtifact:
    """Load and verify a terminal child-process result."""

    path = Path(path)
    payload = _torch_load_mapping(path)
    if payload.get("format") != RESUME_RESULT_FORMAT:
        raise CheckpointValidationError("unsupported resume result format")
    latent = payload.get("latent")
    metadata = payload.get("metadata")
    if not isinstance(latent, torch.Tensor) or not isinstance(metadata, Mapping):
        raise CheckpointValidationError("resume result is missing latent or metadata")
    if metadata.get("format") != RESUME_RESULT_FORMAT:
        raise CheckpointValidationError("embedded resume result format mismatch")
    expected = {
        "latent_dtype": str(latent.dtype),
        "latent_shape": list(latent.shape),
        "latent_sha256": tensor_sha256(latent),
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise CheckpointValidationError(f"resume result {key} mismatch")

    artifact_sha256 = sha256_file(path)
    state_path = _state_metadata_path(path)
    try:
        sidecar = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise CheckpointValidationError(
            f"invalid resume result state metadata: {state_path}"
        ) from exc
    result_file = sidecar.get("result_file", {})
    if result_file.get("name") != path.name:
        raise CheckpointValidationError("resume result state metadata names a different file")
    if result_file.get("sha256") != artifact_sha256:
        raise CheckpointValidationError("serialized resume result SHA-256 mismatch")
    if result_file.get("size_bytes") != path.stat().st_size:
        raise CheckpointValidationError("serialized resume result size mismatch")
    for key, value in metadata.items():
        if sidecar.get(key) != value:
            raise CheckpointValidationError(f"resume result metadata differs at {key}")

    return ResumeArtifact(
        path=path,
        state_metadata_path=state_path,
        latent=latent,
        metadata=dict(metadata),
        artifact_sha256=artifact_sha256,
    )


def launch_resume_child(
    request_path: str | Path,
    *,
    python_executable: str | Path | None = None,
    timeout_seconds: float | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> LaunchedResume:
    """Launch and verify one real OS child process for a resume request."""

    request_path = Path(request_path).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("format") != RESUME_REQUEST_FORMAT:
        raise ValueError(f"unsupported resume request: {request.get('format')!r}")
    result_path = Path(request["result_path"])
    if result_path.exists() or _state_metadata_path(result_path).exists():
        raise FileExistsError(f"refusing to reuse resume result path: {result_path}")

    command = [
        str(python_executable or sys.executable),
        "-m",
        "sa3_smoke.resume_child",
        "--request",
        str(request_path),
    ]
    process = subprocess.run(
        command,
        cwd=None if cwd is None else str(cwd),
        env=None if env is None else dict(env),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )
    if process.returncode != 0:
        raise ChildResumeError(
            f"resume child exited {process.returncode}\n"
            f"command: {command!r}\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    artifact = load_resume_result(result_path)
    child_pid = artifact.metadata.get("child_pid")
    if not isinstance(child_pid, int) or child_pid == os.getpid():
        raise ChildResumeError(f"invalid separate-process PID evidence: {child_pid!r}")
    if artifact.metadata.get("request_sha256") != sha256_file(request_path):
        raise ChildResumeError("child result names the wrong resume request SHA-256")
    return LaunchedResume(process=process, artifact=artifact)


def run_resume_in_subprocess(
    *,
    request_path: str | Path,
    checkpoint_path: str | Path,
    result_path: str | Path,
    runtime_factory: str,
    conditioning_sha256: str,
    config_sha256: str,
    runtime_kwargs: Mapping[str, Any] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    python_executable: str | Path | None = None,
    timeout_seconds: float | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> LaunchedResume:
    """Create an immutable request and execute it in a separate interpreter."""

    written = write_resume_request_no_clobber(
        request_path,
        checkpoint_path=checkpoint_path,
        result_path=result_path,
        runtime_factory=runtime_factory,
        conditioning_sha256=conditioning_sha256,
        config_sha256=config_sha256,
        runtime_kwargs=runtime_kwargs,
        request_metadata=request_metadata,
    )
    return launch_resume_child(
        written,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        env=env,
    )

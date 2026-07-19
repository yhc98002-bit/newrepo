"""Separate-interpreter entry point for verified SA3 Euler resume."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import torch

from .latent import (
    RESUME_REQUEST_FORMAT,
    CheckpointValidationError,
    ResumeRuntime,
    ResumingEulerSampler,
    _save_resume_result_no_clobber,
    load_euler_checkpoint,
    run_euler_transitions,
    sha256_file,
    utc_now,
)


def _load_request(path: Path) -> Mapping[str, Any]:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid resume request: {path}") from exc
    if not isinstance(request, Mapping) or request.get("format") != RESUME_REQUEST_FORMAT:
        raise ValueError(f"unsupported resume request format: {request.get('format')!r}")
    required = {
        "checkpoint_path",
        "checkpoint_sha256",
        "result_path",
        "runtime_factory",
        "conditioning_sha256",
        "config_sha256",
    }
    missing = sorted(required.difference(request))
    if missing:
        raise ValueError(f"resume request is missing fields: {missing}")
    return request


def _resolve_factory(reference: str) -> Callable[..., ResumeRuntime]:
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise ValueError("runtime_factory must have the form 'module.path:function_name'")
    module_name, attribute_name = reference.split(":", 1)
    if not module_name or not attribute_name:
        raise ValueError("runtime_factory module and function must both be non-empty")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name)
    if not callable(factory):
        raise TypeError(f"runtime factory is not callable: {reference}")
    return factory


def execute_request(request_path: str | Path) -> Mapping[str, Any]:
    """Execute one immutable request and return its JSON summary."""

    request_path = Path(request_path).resolve()
    request = _load_request(request_path)
    checkpoint_path = Path(request["checkpoint_path"])
    recorded_checkpoint_sha256 = request["checkpoint_sha256"]
    actual_checkpoint_sha256 = sha256_file(checkpoint_path)
    if recorded_checkpoint_sha256 != actual_checkpoint_sha256:
        raise CheckpointValidationError(
            "resume request checkpoint SHA-256 does not match the current artifact"
        )

    conditioning_sha256 = request["conditioning_sha256"]
    config_sha256 = request["config_sha256"]
    checkpoint = load_euler_checkpoint(
        checkpoint_path,
        expected_conditioning_sha256=conditioning_sha256,
        expected_config_sha256=config_sha256,
    )

    factory = _resolve_factory(request["runtime_factory"])
    runtime = factory(request, checkpoint)
    if not isinstance(runtime, ResumeRuntime):
        raise TypeError(
            "runtime factory must return sa3_smoke.latent.ResumeRuntime, got "
            f"{type(runtime).__name__}"
        )
    if runtime.conditioning_sha256 != conditioning_sha256:
        raise CheckpointValidationError(
            "child-recomputed conditioning identity does not match the request/checkpoint"
        )
    if runtime.config_sha256 != config_sha256:
        raise CheckpointValidationError(
            "child-recomputed configuration identity does not match the request/checkpoint"
        )

    direct_mode = runtime.model is not None
    injection_mode = runtime.invoke_generate is not None
    if direct_mode == injection_mode:
        raise ValueError("ResumeRuntime must set exactly one of model or invoke_generate")

    generated_output: Any
    with torch.inference_mode():
        if injection_mode:
            sampler = ResumingEulerSampler(checkpoint)
            generated_output = runtime.invoke_generate(sampler)  # type: ignore[misc]
            run_result = sampler.last_run_result
            if run_result is None:
                raise RuntimeError("invoke_generate returned without invoking the resume sampler")
            if not sampler.runtime_schedule_validated:
                raise RuntimeError("injected resume sampler did not validate the runtime schedule")
            execution_mode = "official_generate_sampler_injection"
            runtime_schedule_validated = True
            ignored_fresh_initial_latent = True
        else:
            model = runtime.model
            if not callable(model):
                raise TypeError("ResumeRuntime.model must be callable")
            if hasattr(model, "eval"):
                model.eval()
            latent = checkpoint.latent.to(device=runtime.device)
            schedule = checkpoint.schedule.to(device=runtime.device)
            run_result = run_euler_transitions(
                model,
                latent,
                schedule,
                start_step_index=checkpoint.next_step_index,
                model_kwargs=runtime.model_kwargs,
            )
            generated_output = run_result.latent
            execution_mode = "direct_verified_euler"
            runtime_schedule_validated = False
            ignored_fresh_initial_latent = False

        finalize_metadata: Mapping[str, Any] = {}
        if runtime.finalize is not None:
            finalize_metadata = runtime.finalize(
                run_result.latent,
                generated_output,
                checkpoint,
                request,
            )
            if not isinstance(finalize_metadata, Mapping):
                raise TypeError("ResumeRuntime.finalize must return a metadata mapping")

    metadata = {
        "provenance_label": "latent_checkpoint",
        "created_at_utc": utc_now(),
        "child_pid": os.getpid(),
        "os_parent_pid": os.getppid(),
        "request_parent_pid": request.get("parent_pid"),
        "request_path": str(request_path),
        "request_sha256": sha256_file(request_path),
        "source_checkpoint_path": str(checkpoint_path.resolve()),
        "source_checkpoint_sha256": actual_checkpoint_sha256,
        "source_next_step_index": checkpoint.next_step_index,
        "completed_steps": run_result.completed_steps,
        "forward_calls": run_result.forward_calls,
        "conditioning_sha256": conditioning_sha256,
        "config_sha256": config_sha256,
        "execution_mode": execution_mode,
        "runtime_schedule_validated": runtime_schedule_validated,
        "ignored_fresh_initial_latent": ignored_fresh_initial_latent,
        "finalize_metadata": dict(finalize_metadata),
    }
    artifact = _save_resume_result_no_clobber(
        request["result_path"],
        latent=run_result.latent,
        metadata=metadata,
    )
    return {
        "status": "PASS",
        "result_path": str(artifact.path),
        "result_sha256": artifact.artifact_sha256,
        "child_pid": os.getpid(),
        "source_next_step_index": checkpoint.next_step_index,
        "forward_calls": run_result.forward_calls,
        "latent_sha256": artifact.metadata["latent_sha256"],
        "execution_mode": execution_mode,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = execute_request(args.request)
    print(json.dumps(summary, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

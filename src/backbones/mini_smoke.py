"""Bounded, no-clobber B2 mini-smoke runner.

The runner is inert until called. It neither selects a GPU nor discovers a
model. Production calls require exactly one visible GPU and reserve every
request in the immutable manifest before invoking an adapter. A failed call is
ledgered and never retried implicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backbones.contracts import BackboneAdapter, GenerationRequest, sha256_file
from sa3_smoke.artifacts import exclusive_write_json, write_adjacent_provenance
from sa3_smoke.audio import audio_sanity

MAX_B2_MINI_SMOKE_GENERATIONS = 10
MAX_B2_CLIP_SECONDS = 30.0
MAX_B2_GPUS_PER_JOB = 1


class MiniSmokePlanError(ValueError):
    """Raised before any model call when a B2 plan violates its hard caps."""


class MiniSmokeExecutionError(RuntimeError):
    """Raised after a failed model call has been recorded in the immutable ledger."""


@dataclass(frozen=True)
class MiniSmokeJob:
    adapter: BackboneAdapter
    request: GenerationRequest


@dataclass(frozen=True)
class RunContext:
    """Execution provenance supplied by the authorized outer launcher."""

    run_id: str
    command: str
    git_commit: str
    node: str
    gpu_ids: tuple[str, ...]
    placement_justification: str
    package_freeze_sha256: str
    tensor_parallel_width: int = 1
    replica_count: int = 1

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "command",
            "git_commit",
            "node",
            "placement_justification",
            "package_freeze_sha256",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if len(self.gpu_ids) != 1:
            raise ValueError("B2 mini-smoke context must bind exactly one GPU")
        if self.tensor_parallel_width != 1 or self.replica_count != 1:
            raise ValueError("B2 mini-smoke context requires TP1 and one replica")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _append_ledger_row(handle: Any, row: dict[str, Any], previous_hash: str) -> str:
    record = dict(row)
    record["previous_row_sha256"] = previous_hash
    row_hash = hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()
    record["row_sha256"] = row_hash
    handle.write((_canonical_json(record) + "\n").encode("utf-8"))
    handle.flush()
    os.fsync(handle.fileno())
    return row_hash


def _validate_visible_gpu(expected_gpu_id: str) -> None:
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is None:
        raise MiniSmokePlanError("CUDA_VISIBLE_DEVICES must explicitly bind one GPU")
    identifiers = tuple(part.strip() for part in visible.split(",") if part.strip())
    if identifiers != (expected_gpu_id,):
        raise MiniSmokePlanError(
            f"visible GPU {identifiers} does not match manifest GPU {(expected_gpu_id,)}"
        )


def _validate_plan(
    jobs: list[MiniSmokeJob],
    run_dir: Path,
    context: RunContext,
    *,
    require_one_visible_gpu: bool,
) -> None:
    if not jobs:
        raise MiniSmokePlanError("mini-smoke plan must contain at least one generation")
    if len(jobs) > MAX_B2_MINI_SMOKE_GENERATIONS:
        raise MiniSmokePlanError(
            f"mini-smoke plan has {len(jobs)} generations; cap is {MAX_B2_MINI_SMOKE_GENERATIONS}"
        )
    if os.path.lexists(run_dir):
        raise FileExistsError(run_dir)
    resolved_root = run_dir.resolve()
    outputs: set[Path] = set()
    for job in jobs:
        if job.request.duration_seconds > MAX_B2_CLIP_SECONDS:
            raise MiniSmokePlanError("mini-smoke request exceeds the 30-second hard cap")
        output = job.request.output_path.resolve()
        try:
            output.relative_to(resolved_root)
        except ValueError as exc:
            raise MiniSmokePlanError(f"output escapes immutable run directory: {output}") from exc
        if output in outputs:
            raise MiniSmokePlanError(f"duplicate mini-smoke output path: {output}")
        outputs.add(output)
    if require_one_visible_gpu:
        _validate_visible_gpu(context.gpu_ids[0])


def run_mini_smoke(
    jobs: list[MiniSmokeJob],
    *,
    run_dir: str | Path,
    context: RunContext,
    require_one_visible_gpu: bool = True,
) -> dict[str, Any]:
    """Execute a predeclared plan and write per-call measured rows.

    ``require_one_visible_gpu=False`` exists only for CPU fake-adapter tests; a
    production caller should never override the default.
    """

    destination = Path(run_dir)
    _validate_plan(
        jobs,
        destination,
        context,
        require_one_visible_gpu=require_one_visible_gpu,
    )
    preflights: dict[str, Any] = {}
    for job in jobs:
        if job.adapter.logical_name not in preflights:
            ready = job.adapter.preflight()
            if ready.status != "READY_FOR_MINI_SMOKE":
                raise MiniSmokePlanError(
                    f"{job.adapter.logical_name} preflight is not executable: {ready.status}"
                )
            preflights[job.adapter.logical_name] = {
                "status": ready.status,
                "model_id": ready.model_id,
                "config_sha256": ready.config_sha256,
                "details": dict(ready.details),
            }

    destination.mkdir(parents=False, exist_ok=False)
    manifest_path = destination / "manifest.json"
    ledger_path = destination / "generation_ledger.jsonl"
    result_path = destination / "result.json"
    started_at = _utc_now()
    manifest = {
        "schema_version": 1,
        "scope": "B2_MINI_SMOKE_ONLY",
        "run_id": context.run_id,
        "started_at_utc": started_at,
        "host_observed": socket.gethostname(),
        "command": context.command,
        "git_commit": context.git_commit,
        "package_freeze_sha256": context.package_freeze_sha256,
        "placement": {
            "node": context.node,
            "gpu_ids": list(context.gpu_ids),
            "tensor_parallel_width": context.tensor_parallel_width,
            "replica_count": context.replica_count,
            "justification": context.placement_justification,
        },
        "caps": {
            "max_generations": MAX_B2_MINI_SMOKE_GENERATIONS,
            "max_clip_seconds": MAX_B2_CLIP_SECONDS,
            "max_gpus": MAX_B2_GPUS_PER_JOB,
        },
        "reserved_generations": len(jobs),
        "preflights": preflights,
        "requests": [
            {
                "index": index,
                "logical_name": job.adapter.logical_name,
                "model_id": job.adapter.model_id,
                "config_sha256": job.adapter.config_sha256,
                "prompt_id": job.request.prompt_id,
                "seed_id": job.request.seed_id,
                "seed": job.request.seed,
                "duration_seconds": job.request.duration_seconds,
                "output_path": str(job.request.output_path),
            }
            for index, job in enumerate(jobs)
        ],
    }
    exclusive_write_json(manifest_path, manifest)

    rows: list[dict[str, Any]] = []
    previous_hash = "0" * 64

    def write_failed_result(error: str) -> None:
        failure = {
            "schema_version": 1,
            "run_id": context.run_id,
            "status": "FAIL_ESCALATED",
            "started_at_utc": started_at,
            "finished_at_utc": _utc_now(),
            "generation_count": len(rows),
            "measured_cost_rows": sum(
                row.get("cost_status") == "MEASURED" for row in rows
            ),
            "ledger_path": str(ledger_path),
            "ledger_sha256": sha256_file(ledger_path),
            "ledger_tail_sha256": previous_hash,
            "error": error,
            "rows": rows,
        }
        exclusive_write_json(result_path, failure)

    with ledger_path.open("xb") as ledger:
        for index, job in enumerate(jobs):
            request = job.request
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            row_base = {
                "schema_version": 1,
                "run_id": context.run_id,
                "generation_index": index,
                "logical_name": job.adapter.logical_name,
                "model_id": job.adapter.model_id,
                "config_sha256": job.adapter.config_sha256,
                "prompt_id": request.prompt_id,
                "seed_id": request.seed_id,
                "seed": request.seed,
                "duration_seconds": request.duration_seconds,
                "output_path": str(request.output_path),
                "attempted_at_utc": _utc_now(),
            }
            try:
                measurement = job.adapter.generate(request)
                provenance_path = write_adjacent_provenance(
                    measurement.output_path,
                    {
                        "label": "synthetic_model_output",
                        "created_at_utc": _utc_now(),
                        "creating_command": context.command,
                        "run_id": context.run_id,
                        "source_ids": [
                            f"{job.adapter.model_id}@config-sha256:{job.adapter.config_sha256}"
                        ],
                        "model_revision": preflights[job.adapter.logical_name]["details"].get(
                            "resolved_provider_revision",
                            preflights[job.adapter.logical_name]["details"]
                            .get("source", {})
                            .get("revision", "content-pinned-local-snapshot"),
                        ),
                        "license_identifier": job.adapter.license_identifier,
                        "transformation": "official backbone text-to-audio decode",
                    },
                )
                sanity = audio_sanity(
                    measurement.output_path,
                    request.duration_seconds,
                    expected_sample_rate=measurement.sample_rate,
                    expected_channels=2,
                    require_provenance=True,
                )
                status = "PASS" if sanity["pass"] else "AUDIO_SANITY_FAILED"
                row = {
                    **row_base,
                    "status": status,
                    "cost_status": "MEASURED",
                    "requested_steps": measurement.requested_steps,
                    "actual_nfe": measurement.actual_nfe,
                    "wall_seconds": measurement.wall_seconds,
                    "peak_allocated_bytes": measurement.peak_allocated_bytes,
                    "peak_reserved_bytes": measurement.peak_reserved_bytes,
                    "measurement_metadata": dict(measurement.metadata),
                    "file_sha256": sha256_file(measurement.output_path),
                    "provenance_path": str(provenance_path),
                    "provenance_sha256": sha256_file(provenance_path),
                    "audio_sanity": sanity,
                }
            except Exception as exc:
                row = {
                    **row_base,
                    "status": "MODEL_CALL_FAILED",
                    "cost_status": "NOT_MEASURED_CALL_FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                previous_hash = _append_ledger_row(ledger, row, previous_hash)
                rows.append(row)
                write_failed_result(str(exc))
                raise MiniSmokeExecutionError(
                    f"generation {index} failed and was ledgered without retry: {exc}"
                ) from exc
            previous_hash = _append_ledger_row(ledger, row, previous_hash)
            rows.append(row)
            if row["status"] != "PASS":
                write_failed_result("retained-audio sanity failed")
                raise MiniSmokeExecutionError(
                    f"generation {index} failed retained-audio sanity and was not retried"
                )

    result = {
        "schema_version": 1,
        "run_id": context.run_id,
        "status": "PASS",
        "started_at_utc": started_at,
        "finished_at_utc": _utc_now(),
        "generation_count": len(rows),
        "measured_cost_rows": len(rows),
        "ledger_path": str(ledger_path),
        "ledger_sha256": sha256_file(ledger_path),
        "ledger_tail_sha256": previous_hash,
        "rows": rows,
    }
    exclusive_write_json(result_path, result)
    return result

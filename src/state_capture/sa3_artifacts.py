"""No-clobber state, preview, resume, and feature-source artifact commits."""

from __future__ import annotations

import json
import math
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from benchmark_core.artifacts import basic_audio_sanity
from sa3_smoke.latent import load_euler_checkpoint
from state_capture.sa3_contract import SA3StateCaptureConfig, sha256_file


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe(root: Path, relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ValueError(f"unsafe state artifact path: {relative}")
    destination = (root / value).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"state artifact escapes root: {relative}") from exc
    return destination


def _copy_exclusive(source: Path, destination: Path) -> None:
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"staged state artifact is absent or empty: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(destination):
        raise FileExistsError(destination)
    temporary = destination.with_name(f".{destination.name}.partial-{uuid.uuid4().hex}")
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.link(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_checkpoint_pair_exclusive(
    checkpoint_source: Path,
    state_metadata_source: Path,
    checkpoint_destination: Path,
    state_metadata_destination: Path,
) -> None:
    """Relocate a checkpoint while preserving the sidecar's filename binding."""

    try:
        state_metadata = json.loads(state_metadata_source.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"invalid staged checkpoint state metadata: {state_metadata_source}"
        ) from exc
    if not isinstance(state_metadata, Mapping):
        raise ValueError("staged checkpoint state metadata must be an object")
    checkpoint_file = state_metadata.get("checkpoint_file")
    if not isinstance(checkpoint_file, Mapping):
        raise ValueError("staged checkpoint state metadata lacks checkpoint_file")

    source_sha256 = sha256_file(checkpoint_source)
    source_size = checkpoint_source.stat().st_size
    if checkpoint_file.get("name") != checkpoint_source.name:
        raise ValueError("staged checkpoint state metadata names a different file")
    if checkpoint_file.get("sha256") != source_sha256:
        raise ValueError("staged checkpoint state metadata SHA-256 mismatch")
    if checkpoint_file.get("size_bytes") != source_size:
        raise ValueError("staged checkpoint state metadata size mismatch")

    _copy_exclusive(checkpoint_source, checkpoint_destination)
    destination_sha256 = sha256_file(checkpoint_destination)
    destination_size = checkpoint_destination.stat().st_size
    if destination_sha256 != source_sha256 or destination_size != source_size:
        raise ValueError("published checkpoint differs from its staged source")

    relocated_metadata = dict(state_metadata)
    relocated_metadata["checkpoint_file"] = {
        "name": checkpoint_destination.name,
        "sha256": destination_sha256,
        "size_bytes": destination_size,
    }
    _write_json_exclusive(state_metadata_destination, relocated_metadata)


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


@dataclass(frozen=True)
class StagedCheckpointPreview:
    lane_request_sha256: str
    checkpoint_path: Path
    checkpoint_state_metadata_path: Path
    preview_path: Path


@dataclass(frozen=True)
class StagedPrefixGroup:
    reference_terminal_path: Path
    checkpoint_previews: Sequence[StagedCheckpointPreview]
    actual_nfe: int
    synchronized_gpu_seconds: float
    peak_allocated_bytes: int
    peak_reserved_bytes: int
    conditioning_sha256: str
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StagedResume:
    resumed_terminal_path: Path
    actual_nfe: int
    synchronized_gpu_seconds: float
    peak_allocated_bytes: int
    peak_reserved_bytes: int
    child_pid: int
    provenance: Mapping[str, Any] = field(default_factory=dict)


def _validate_measurement(value: Any, name: str, *, integer: bool = False) -> float | int:
    if integer:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def commit_prefix_group(
    artifact_root: Path,
    group: Mapping[str, Any],
    units: Sequence[Mapping[str, Any]],
    staged: StagedPrefixGroup,
    *,
    config: SA3StateCaptureConfig,
) -> dict[str, Any]:
    """Commit one true BASE-root reference plus all 25/50/75 previews atomically by marker."""

    root = artifact_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    expected_ids = list(group.get("lane_request_sha256s", []))
    unit_index = {str(unit["lane_request_sha256"]): unit for unit in units}
    supplied = {item.lane_request_sha256: item for item in staged.checkpoint_previews}
    if len(unit_index) != 3 or expected_ids != list(unit_index) or set(supplied) != set(unit_index):
        raise ValueError("prefix staging does not exactly match its three state units")
    if staged.actual_nfe != config.transformer_budget_nfe:
        raise ValueError("prefix reference did not execute the frozen transformer budget")
    for name in ("peak_allocated_bytes", "peak_reserved_bytes"):
        _validate_measurement(getattr(staged, name), name, integer=True)
    _validate_measurement(staged.synchronized_gpu_seconds, "synchronized_gpu_seconds")

    reference = _safe(root, str(group["reference_terminal_relpath"]))
    reference_commit = reference.with_suffix(".commit.json")
    reference_provenance = reference.with_suffix(".provenance.json")
    reference_sanity_path = reference.with_suffix(".sanity.json")
    for path in (reference, reference_commit, reference_provenance, reference_sanity_path):
        if os.path.lexists(path):
            raise FileExistsError(path)
    expected_rate = int(config.raw["execution"]["expected_sample_rate"])
    expected_channels = int(config.raw["execution"]["expected_channels"])
    duration = float(group["duration_seconds"])
    reference_sanity = basic_audio_sanity(
        staged.reference_terminal_path,
        expected_duration_seconds=duration,
        expected_sample_rate=expected_rate,
        expected_channels=expected_channels,
    )

    state_records: list[dict[str, Any]] = []
    for identity in expected_ids:
        unit = unit_index[identity]
        item = supplied[identity]
        checkpoint_state = load_euler_checkpoint(
            item.checkpoint_path,
            expected_conditioning_sha256=staged.conditioning_sha256,
            expected_config_sha256=config.source_sha256,
        )
        if (
            checkpoint_state.next_step_index != unit["checkpoint_completed_steps"]
            or checkpoint_state.metadata.get("completed_fraction")
            != unit["checkpoint_completed_steps"] / config.transformer_budget_nfe
        ):
            raise ValueError("checkpoint step/fraction metadata drift")
        if item.checkpoint_state_metadata_path != item.checkpoint_path.with_suffix(
            item.checkpoint_path.suffix + ".state.json"
        ):
            raise ValueError("checkpoint sidecar path is not canonical")
        preview_sanity = basic_audio_sanity(
            item.preview_path,
            expected_duration_seconds=duration,
            expected_sample_rate=expected_rate,
            expected_channels=expected_channels,
        )
        checkpoint_destination = _safe(root, str(unit["checkpoint_relpath"]))
        checkpoint_sidecar_destination = checkpoint_destination.with_suffix(
            checkpoint_destination.suffix + ".state.json"
        )
        preview_destination = _safe(root, str(unit["preview_relpath"]))
        feature_contract_destination = _safe(root, str(unit["feature_contract_relpath"]))
        for path in (
            checkpoint_destination,
            checkpoint_sidecar_destination,
            preview_destination,
            feature_contract_destination,
        ):
            if os.path.lexists(path):
                raise FileExistsError(path)
        _copy_checkpoint_pair_exclusive(
            item.checkpoint_path,
            item.checkpoint_state_metadata_path,
            checkpoint_destination,
            checkpoint_sidecar_destination,
        )
        load_euler_checkpoint(
            checkpoint_destination,
            expected_conditioning_sha256=staged.conditioning_sha256,
            expected_config_sha256=config.source_sha256,
        )
        _copy_exclusive(item.preview_path, preview_destination)
        preview_sha = sha256_file(preview_destination)
        checkpoint_sha = sha256_file(checkpoint_destination)
        feature_contract = {
            "axis": unit["axis"],
            "checkpoint_completed_steps": unit["checkpoint_completed_steps"],
            "checkpoint_fraction": unit["checkpoint_fraction"],
            "checkpoint_sha256": checkpoint_sha,
            "feature_contract": unit["feature_contract"],
            "lane_request_sha256": identity,
            "preview_relpath": unit["preview_relpath"],
            "preview_sha256": preview_sha,
            "preview_source_request_sha256": unit["preview_source_request_sha256"],
            "root_index": unit["root_index"],
            "schema_version": 1,
            "status": "FEATURE_INPUT_COMMITTED_NOT_YET_EVALUATED",
        }
        _write_json_exclusive(feature_contract_destination, feature_contract)
        state_records.append(
            {
                "checkpoint_completed_steps": unit["checkpoint_completed_steps"],
                "checkpoint_relpath": unit["checkpoint_relpath"],
                "checkpoint_sha256": checkpoint_sha,
                "feature_contract_relpath": unit["feature_contract_relpath"],
                "feature_contract_sha256": sha256_file(feature_contract_destination),
                "lane_request_sha256": identity,
                "preview_relpath": unit["preview_relpath"],
                "preview_sanity": preview_sanity,
                "preview_sha256": preview_sha,
            }
        )

    _copy_exclusive(staged.reference_terminal_path, reference)
    reference_sha = sha256_file(reference)
    provenance = {
        "actual_nfe": staged.actual_nfe,
        "conditioning_sha256": staged.conditioning_sha256,
        "config_sha256": config.source_sha256,
        "group_request_sha256": group["group_request_sha256"],
        "peak_allocated_bytes": staged.peak_allocated_bytes,
        "peak_reserved_bytes": staged.peak_reserved_bytes,
        "reference_terminal_sha256": reference_sha,
        "schema_version": 1,
        "state_artifacts": state_records,
        "synchronized_gpu_seconds": staged.synchronized_gpu_seconds,
        "upstream": dict(staged.provenance),
    }
    _write_json_exclusive(reference_provenance, provenance)
    _write_json_exclusive(
        reference_sanity_path,
        {
            "group_request_sha256": group["group_request_sha256"],
            "reference_terminal_sha256": reference_sha,
            "sanity": reference_sanity,
            "schema_version": 1,
        },
    )
    commit = {
        "group_request_sha256": group["group_request_sha256"],
        "provenance_sha256": sha256_file(reference_provenance),
        "reference_sanity_sha256": sha256_file(reference_sanity_path),
        "reference_terminal_relpath": group["reference_terminal_relpath"],
        "reference_terminal_sha256": reference_sha,
        "schema_version": 1,
        "state_artifact_count": 3,
        "status": "COMMITTED",
    }
    _write_json_exclusive(reference_commit, commit)
    return commit


def _waveform_equivalence(
    reference: Path,
    candidate: Path,
    *,
    max_abs_tolerance: float,
    minimum_snr_db: float,
) -> dict[str, Any]:
    first, first_rate = sf.read(reference, dtype="float32", always_2d=True)
    second, second_rate = sf.read(candidate, dtype="float32", always_2d=True)
    shape_match = first.shape == second.shape
    rate_match = first_rate == second_rate
    if not shape_match or not rate_match:
        return {
            "max_abs_error": None,
            "pass": False,
            "sample_rate_match": rate_match,
            "shape_match": shape_match,
            "snr_db": None,
        }
    difference = second.astype(np.float64) - first.astype(np.float64)
    max_abs = float(np.max(np.abs(difference)))
    error_power = float(np.mean(np.square(difference)))
    signal_power = float(np.mean(np.square(first.astype(np.float64))))
    snr = math.inf if error_power == 0 else 10 * math.log10(signal_power / error_power)
    return {
        "max_abs_error": max_abs,
        "max_abs_tolerance": max_abs_tolerance,
        "pass": max_abs <= max_abs_tolerance and snr >= minimum_snr_db,
        "sample_rate_match": True,
        "shape_match": True,
        "snr_db": None if math.isinf(snr) else snr,
        "snr_interpretation": "infinite_zero_error" if math.isinf(snr) else "finite",
        "snr_minimum_db": minimum_snr_db,
    }


def commit_resume(
    artifact_root: Path,
    unit: Mapping[str, Any],
    staged: StagedResume,
    *,
    reference_terminal_relpath: str,
    config: SA3StateCaptureConfig,
) -> dict[str, Any]:
    root = artifact_root.resolve()
    destination = _safe(root, str(unit["resumed_terminal_relpath"]))
    provenance_path = destination.with_suffix(".provenance.json")
    sanity_path = destination.with_suffix(".sanity.json")
    commit_path = destination.with_suffix(".commit.json")
    for path in (destination, provenance_path, sanity_path, commit_path):
        if os.path.lexists(path):
            raise FileExistsError(path)
    expected_rate = int(config.raw["execution"]["expected_sample_rate"])
    expected_channels = int(config.raw["execution"]["expected_channels"])
    sanity = basic_audio_sanity(
        staged.resumed_terminal_path,
        expected_duration_seconds=float(unit["duration_seconds"]),
        expected_sample_rate=expected_rate,
        expected_channels=expected_channels,
    )
    expected_remaining = config.transformer_budget_nfe - int(unit["checkpoint_completed_steps"])
    if staged.actual_nfe != expected_remaining:
        raise ValueError("resume NFE does not equal the frozen remaining budget")
    if staged.child_pid <= 0 or staged.child_pid == os.getpid():
        raise ValueError("resume must complete in a distinct child process")
    _validate_measurement(staged.synchronized_gpu_seconds, "synchronized_gpu_seconds")
    reference = _safe(root, reference_terminal_relpath)
    if not reference.is_file():
        raise ValueError("committed root reference terminal is absent")
    tolerance = config.raw["execution"]["waveform_equivalence"]
    comparison = _waveform_equivalence(
        reference,
        staged.resumed_terminal_path,
        max_abs_tolerance=float(tolerance["max_abs_tolerance"]),
        minimum_snr_db=float(tolerance["minimum_snr_db"]),
    )
    if not comparison["pass"]:
        raise ValueError("separate-process resume is not equivalent to root reference")
    _copy_exclusive(staged.resumed_terminal_path, destination)
    terminal_sha = sha256_file(destination)
    provenance = {
        "actual_nfe": staged.actual_nfe,
        "child_pid": staged.child_pid,
        "lane_request_sha256": unit["lane_request_sha256"],
        "peak_allocated_bytes": staged.peak_allocated_bytes,
        "peak_reserved_bytes": staged.peak_reserved_bytes,
        "reference_terminal_relpath": reference_terminal_relpath,
        "reference_terminal_sha256": sha256_file(reference),
        "resume_equivalence": comparison,
        "resumed_terminal_sha256": terminal_sha,
        "schema_version": 1,
        "synchronized_gpu_seconds": staged.synchronized_gpu_seconds,
        "upstream": dict(staged.provenance),
    }
    _write_json_exclusive(provenance_path, provenance)
    _write_json_exclusive(
        sanity_path,
        {
            "lane_request_sha256": unit["lane_request_sha256"],
            "resumed_terminal_sha256": terminal_sha,
            "sanity": sanity,
            "schema_version": 1,
        },
    )
    commit = {
        "lane_request_sha256": unit["lane_request_sha256"],
        "provenance_sha256": sha256_file(provenance_path),
        "resumed_terminal_relpath": unit["resumed_terminal_relpath"],
        "resumed_terminal_sha256": terminal_sha,
        "sanity_sha256": sha256_file(sanity_path),
        "schema_version": 1,
        "status": "COMMITTED",
    }
    _write_json_exclusive(commit_path, commit)
    return commit


__all__ = [
    "StagedCheckpointPreview",
    "StagedPrefixGroup",
    "StagedResume",
    "commit_prefix_group",
    "commit_resume",
]

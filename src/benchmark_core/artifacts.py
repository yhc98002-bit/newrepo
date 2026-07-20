"""No-clobber generation, provenance, sanity, and state artifact commits."""

from __future__ import annotations

import hashlib
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

from benchmark_core.queue import canonical_json


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_destination(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe artifact relative path: {relative}")
    destination = (root / path).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes root: {relative}") from exc
    return destination


def _copy_exclusive(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ValueError(f"staged artifact is absent: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(destination):
        raise FileExistsError(destination)
    temporary = destination.with_name(f".{destination.name}.partial-{uuid.uuid4().hex}")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as output:
            shutil.copyfileobj(source_handle, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def basic_audio_sanity(
    path: Path,
    *,
    expected_duration_seconds: float,
    expected_sample_rate: int,
    expected_channels: int,
) -> dict[str, Any]:
    """Decode the complete waveform and reject corrupt, empty, or non-finite audio."""

    if not path.is_file():
        raise ValueError(f"audio is absent: {path}")
    info = sf.info(path)
    if info.samplerate != expected_sample_rate:
        raise ValueError(
            f"audio sample rate {info.samplerate} does not match {expected_sample_rate}"
        )
    if info.channels != expected_channels:
        raise ValueError(f"audio channels {info.channels} do not match {expected_channels}")
    if info.frames <= 0:
        raise ValueError("audio metadata is invalid")
    expected_frames = round(expected_duration_seconds * expected_sample_rate)
    observed_duration = info.frames / info.samplerate
    if info.frames != expected_frames:
        raise ValueError(
            f"audio frame count {info.frames} does not exactly match {expected_frames} "
            f"for {expected_duration_seconds} seconds"
        )
    waveform, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if sample_rate != info.samplerate or waveform.shape != (info.frames, info.channels):
        raise ValueError("decoded waveform shape disagrees with metadata")
    if not np.isfinite(waveform).all():
        raise ValueError("decoded waveform contains non-finite values")
    peak = float(np.max(np.abs(waveform)))
    rms = float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64))))
    if not math.isfinite(peak) or not math.isfinite(rms) or rms <= 1e-8:
        raise ValueError("decoded waveform is silent or invalid")
    return {
        "channels": info.channels,
        "duration_seconds": observed_duration,
        "expected_frames": expected_frames,
        "frames": info.frames,
        "peak_absolute": peak,
        "rms": rms,
        "sample_rate": info.samplerate,
        "status": "PASS",
    }


@dataclass(frozen=True)
class StagedStateArtifact:
    state_request_sha256: str
    checkpoint_path: Path
    preview_path: Path


@dataclass(frozen=True)
class StagedGeneration:
    wav_path: Path
    actual_nfe: int
    synchronized_wall_seconds: float
    peak_allocated_bytes: int
    peak_reserved_bytes: int
    sample_rate: int
    channels: int
    provenance: Mapping[str, Any] = field(default_factory=dict)
    state_artifacts: Sequence[StagedStateArtifact] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.wav_path.is_file():
            raise ValueError("staged waveform is absent")
        if isinstance(self.actual_nfe, bool) or not isinstance(self.actual_nfe, int):
            raise ValueError("actual_nfe must be an integer")
        if self.actual_nfe <= 0:
            raise ValueError("actual_nfe must be positive")
        if not math.isfinite(self.synchronized_wall_seconds) or self.synchronized_wall_seconds <= 0:
            raise ValueError("synchronized wall time must be finite and positive")
        for name in ("peak_allocated_bytes", "peak_reserved_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.sample_rate <= 0 or self.channels <= 0:
            raise ValueError("staged sample rate and channel count must be positive")
        json.dumps(dict(self.provenance), allow_nan=False, sort_keys=True)


def _validate_state_contracts(
    contracts: Sequence[Mapping[str, Any]], artifacts: Sequence[StagedStateArtifact]
) -> dict[str, tuple[Mapping[str, Any], StagedStateArtifact]]:
    expected: dict[str, Mapping[str, Any]] = {}
    for contract in contracts:
        identity = contract.get("state_request_sha256")
        if not isinstance(identity, str) or len(identity) != 64 or identity in expected:
            raise ValueError("state contract identity is invalid or duplicated")
        unhashed = dict(contract)
        unhashed.pop("state_request_sha256", None)
        observed = hashlib.sha256(canonical_json(unhashed).encode()).hexdigest()
        if observed != identity:
            raise ValueError("state contract hash mismatch")
        if contract.get("preview_source_request_sha256") != contract.get("parent_request_sha256"):
            raise ValueError("state preview is not root-local")
        expected[identity] = contract
    supplied: dict[str, StagedStateArtifact] = {}
    for artifact in artifacts:
        if artifact.state_request_sha256 in supplied:
            raise ValueError("staged state artifact is duplicated")
        supplied[artifact.state_request_sha256] = artifact
    if set(expected) != set(supplied):
        raise ValueError("staged state artifacts do not exactly match capture contracts")
    return {identity: (expected[identity], supplied[identity]) for identity in expected}


def commit_generation(
    artifact_root: Path,
    request: Mapping[str, Any],
    staged: StagedGeneration,
    *,
    state_contracts: Sequence[Mapping[str, Any]] = (),
    expected_sample_rate: int,
    expected_channels: int,
) -> dict[str, Any]:
    """Commit all required artifacts without replacing any existing path.

    The commit marker is written last. If a process stops earlier, partial
    artifacts remain for audit and the durable request claim forbids retry.
    """

    root = artifact_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    request_sha = request.get("request_sha256")
    if not isinstance(request_sha, str) or len(request_sha) != 64:
        raise ValueError("request lacks request_sha256")
    unhashed_request = dict(request)
    unhashed_request.pop("request_sha256", None)
    observed_request_sha = hashlib.sha256(canonical_json(unhashed_request).encode()).hexdigest()
    if observed_request_sha != request_sha:
        raise ValueError("request hash mismatch at artifact boundary")
    duration = request.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("request duration is invalid")
    duration = float(duration)
    if not 0 < duration <= 30:
        raise ValueError("request duration exceeds 30 seconds")
    wav_destination = _safe_destination(root, str(request.get("output_relpath", "")))
    if wav_destination.suffix.lower() != ".wav":
        raise ValueError("generation output must have a .wav suffix")
    provenance_path = wav_destination.with_suffix(".provenance.json")
    sanity_path = wav_destination.with_suffix(".sanity.json")
    commit_path = wav_destination.with_suffix(".commit.json")
    for path in (wav_destination, provenance_path, sanity_path, commit_path):
        if os.path.lexists(path):
            raise FileExistsError(path)

    if staged.sample_rate != expected_sample_rate or staged.channels != expected_channels:
        raise ValueError("adapter measurement disagrees with frozen audio format")
    sanity = basic_audio_sanity(
        staged.wav_path,
        expected_duration_seconds=duration,
        expected_sample_rate=expected_sample_rate,
        expected_channels=expected_channels,
    )
    state_pairs = _validate_state_contracts(state_contracts, staged.state_artifacts)
    state_records: list[dict[str, Any]] = []
    for identity, (contract, artifact) in state_pairs.items():
        checkpoint = _safe_destination(root, str(contract["checkpoint_relpath"]))
        preview = _safe_destination(root, str(contract["preview_relpath"]))
        if os.path.lexists(checkpoint) or os.path.lexists(preview):
            raise FileExistsError(f"state destination already exists for {identity}")
        if not artifact.checkpoint_path.is_file() or artifact.checkpoint_path.stat().st_size <= 0:
            raise ValueError("staged checkpoint is absent or empty")
        preview_sanity = basic_audio_sanity(
            artifact.preview_path,
            expected_duration_seconds=duration,
            expected_sample_rate=expected_sample_rate,
            expected_channels=expected_channels,
        )
        _copy_exclusive(artifact.checkpoint_path, checkpoint)
        _copy_exclusive(artifact.preview_path, preview)
        state_records.append(
            {
                "checkpoint_fraction": contract["checkpoint_fraction"],
                "checkpoint_relpath": checkpoint.relative_to(root).as_posix(),
                "checkpoint_sha256": sha256_file(checkpoint),
                "preview_relpath": preview.relative_to(root).as_posix(),
                "preview_sanity": preview_sanity,
                "preview_sha256": sha256_file(preview),
                "state_request_sha256": identity,
            }
        )

    _copy_exclusive(staged.wav_path, wav_destination)
    wav_sha = sha256_file(wav_destination)
    provenance = {
        "actual_nfe": staged.actual_nfe,
        "model_id": request.get("model_id"),
        "expected_channels": expected_channels,
        "expected_sample_rate": expected_sample_rate,
        "peak_allocated_bytes": staged.peak_allocated_bytes,
        "peak_reserved_bytes": staged.peak_reserved_bytes,
        "request_sha256": request_sha,
        "root_index": request.get("root_index"),
        "schema_version": 1,
        "state_artifacts": state_records,
        "synchronized_wall_seconds": staged.synchronized_wall_seconds,
        "upstream": dict(staged.provenance),
        "wav_sha256": wav_sha,
    }
    _write_json_exclusive(provenance_path, provenance)
    _write_json_exclusive(
        sanity_path,
        {
            "request_sha256": request_sha,
            "schema_version": 1,
            "sanity": sanity,
            "wav_sha256": wav_sha,
        },
    )
    commit = {
        "output_relpath": wav_destination.relative_to(root).as_posix(),
        "provenance_sha256": sha256_file(provenance_path),
        "request_sha256": request_sha,
        "sanity_sha256": sha256_file(sanity_path),
        "schema_version": 1,
        "state_artifact_count": len(state_records),
        "status": "COMMITTED",
        "wav_sha256": wav_sha,
    }
    _write_json_exclusive(commit_path, commit)
    return commit

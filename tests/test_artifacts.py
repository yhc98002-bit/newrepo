"""Fast tests for immutable artifact and provenance helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sa3_smoke.artifacts import (
    ProvenanceValidationError,
    adjacent_provenance_path,
    create_immutable_directory,
    create_immutable_run_dir,
    exclusive_write_bytes,
    exclusive_write_json,
    sha256_bytes,
    sha256_file,
    validate_adjacent_provenance,
    write_adjacent_provenance,
)


def valid_record(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "label": "synthetic_model_output",
        "created_at_utc": "2026-07-19T12:00:00Z",
        "creating_command": "python -m sa3_smoke.run a",
        "run_id": "a-20260719T120000Z-deadbeef",
        "source_ids": ["stabilityai/stable-audio-3-medium-base@revision"],
        "model_revision": "revision",
        "license_identifier": "Stability-AI-Community",
        "transformation": "official text-to-audio decode",
    }
    record.update(updates)
    return record


def test_sha256_helpers_match_known_vector_and_stream(tmp_path: Path) -> None:
    payload = b"abc" * 1000
    expected = hashlib.sha256(payload).hexdigest()
    path = tmp_path / "payload.bin"
    path.write_bytes(payload)

    assert sha256_bytes(payload) == expected
    assert sha256_bytes(memoryview(payload)) == expected
    assert sha256_file(path, chunk_size=17) == expected
    with pytest.raises(ValueError, match="positive integer"):
        sha256_file(path, chunk_size=0)


def test_immutable_directories_and_run_names(tmp_path: Path) -> None:
    exact = create_immutable_directory(tmp_path / "exact")
    assert exact.is_dir()
    with pytest.raises(FileExistsError):
        create_immutable_directory(exact)

    first = create_immutable_run_dir(tmp_path / "runs", prefix="smoke-a")
    second = create_immutable_run_dir(tmp_path / "runs", prefix="smoke-a")
    assert first != second
    assert first.parent == second.parent == tmp_path / "runs"
    assert first.name.startswith("smoke-a-")
    with pytest.raises(ValueError, match="safe path component"):
        create_immutable_run_dir(tmp_path / "runs", prefix="../escape")


def test_exclusive_writers_never_clobber(tmp_path: Path) -> None:
    binary = tmp_path / "artifact.bin"
    exclusive_write_bytes(binary, b"original")
    with pytest.raises(FileExistsError):
        exclusive_write_bytes(binary, b"replacement")
    assert binary.read_bytes() == b"original"

    manifest = tmp_path / "manifest.json"
    exclusive_write_json(manifest, {"z": 1, "a": "value"})
    with pytest.raises(FileExistsError):
        exclusive_write_json(manifest, {"replacement": True})
    assert json.loads(manifest.read_text(encoding="utf-8")) == {"a": "value", "z": 1}
    with pytest.raises(ValueError, match="Out of range float"):
        exclusive_write_json(tmp_path / "bad.json", {"bad": float("nan")})
    assert not (tmp_path / "bad.json").exists()


def test_adjacent_provenance_write_and_validation(tmp_path: Path) -> None:
    artifact = tmp_path / "x.wav"
    exclusive_write_bytes(artifact, b"retained bytes")

    sidecar = write_adjacent_provenance(artifact, valid_record())
    assert sidecar == tmp_path / "x.wav.provenance.json"
    assert adjacent_provenance_path(artifact) == sidecar
    validated = validate_adjacent_provenance(artifact)
    assert validated["sha256"] == sha256_file(artifact)
    assert validated["size_bytes"] == artifact.stat().st_size

    with pytest.raises(FileExistsError):
        write_adjacent_provenance(artifact, valid_record())


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({}, "missing required fields"),
        (valid_record(label="unknown"), "invalid provenance label"),
        (valid_record(source_ids=[]), "source_ids"),
        (valid_record(created_at_utc="2026-07-19"), "include a UTC offset"),
        (valid_record(sha256="0" * 64), "sha256 mismatch"),
        (valid_record(size_bytes=999), "size mismatch"),
    ],
)
def test_invalid_provenance_is_rejected(
    tmp_path: Path, record: dict[str, object], message: str
) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")
    sidecar = adjacent_provenance_path(artifact)
    complete = dict(record)
    complete.setdefault("sha256", sha256_file(artifact))
    complete.setdefault("size_bytes", artifact.stat().st_size)
    sidecar.write_text(json.dumps(complete), encoding="utf-8")

    with pytest.raises(ProvenanceValidationError, match=message):
        validate_adjacent_provenance(artifact)


def test_missing_and_duplicate_key_provenance_are_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")
    with pytest.raises(ProvenanceValidationError, match="missing"):
        validate_adjacent_provenance(artifact)

    sidecar = adjacent_provenance_path(artifact)
    sidecar.write_text('{"label":"derived_audio","label":"latent_checkpoint"}', encoding="utf-8")
    with pytest.raises(ProvenanceValidationError, match="duplicate JSON key"):
        validate_adjacent_provenance(artifact)

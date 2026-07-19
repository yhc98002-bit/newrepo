"""Immutable artifact and provenance helpers for the SA3 smoke harness.

Artifact paths are intentionally boring: callers must choose the destination,
and every writer in this module uses exclusive creation.  Nothing here offers
an overwrite flag because a correction belongs in a new run directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PROVENANCE_LABELS = frozenset(
    {
        "external_upstream",
        "synthetic_model_output",
        "derived_audio",
        "latent_checkpoint",
    }
)
PROVENANCE_REQUIRED_FIELDS = frozenset(
    {
        "label",
        "sha256",
        "size_bytes",
        "created_at_utc",
        "creating_command",
        "run_id",
        "source_ids",
        "model_revision",
        "license_identifier",
        "transformation",
    }
)


class ProvenanceValidationError(ValueError):
    """Raised when an adjacent provenance record is absent or invalid."""


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return the lowercase SHA-256 digest of an in-memory byte sequence."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str], *, chunk_size: int = 1024 * 1024) -> str:
    """Stream *path* and return its lowercase SHA-256 digest."""

    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def create_immutable_directory(path: str | os.PathLike[str]) -> Path:
    """Create exactly *path* and fail if anything already occupies it."""

    destination = Path(path)
    destination.mkdir(parents=False, exist_ok=False)
    return destination


def create_immutable_run_dir(
    root: str | os.PathLike[str],
    *,
    prefix: str = "run",
    attempts: int = 32,
) -> Path:
    """Create a unique ``<prefix>-<UTC timestamp>-<random>`` run directory.

    The run root is ordinary scaffolding and is created if absent.  The run
    directory itself is always created atomically with no-clobber semantics.
    """

    if not SAFE_COMPONENT_RE.fullmatch(prefix):
        raise ValueError("prefix must be one safe path component")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
        raise ValueError("attempts must be a positive integer")

    run_root = Path(root)
    run_root.mkdir(parents=True, exist_ok=True)
    if not run_root.is_dir():
        raise NotADirectoryError(run_root)

    for _ in range(attempts):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        candidate = run_root / f"{prefix}-{timestamp}-{secrets.token_hex(6)}"
        try:
            return create_immutable_directory(candidate)
        except FileExistsError:
            continue
    raise FileExistsError(f"could not allocate a unique run directory under {run_root}")


def exclusive_write_bytes(
    path: str | os.PathLike[str], data: bytes | bytearray | memoryview
) -> Path:
    """Write bytes to a new file, refusing to replace an existing path."""

    destination = Path(path)
    payload = bytes(data)
    with destination.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def exclusive_write_json(path: str | os.PathLike[str], value: Any) -> Path:
    """Serialize strict, deterministic JSON and write it with no clobber."""

    payload = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return exclusive_write_bytes(path, payload)


def adjacent_provenance_path(artifact_path: str | os.PathLike[str]) -> Path:
    """Return the required ``<filename>.provenance.json`` sidecar path."""

    artifact = Path(artifact_path)
    return artifact.with_name(f"{artifact.name}.provenance.json")


def _nonempty_string(record: Mapping[str, Any], field: str) -> bool:
    value = record.get(field)
    return isinstance(value, str) and bool(value.strip())


def _validate_provenance_record(
    record: Mapping[str, Any],
    *,
    artifact_sha256: str,
    artifact_size: int,
) -> None:
    missing = sorted(PROVENANCE_REQUIRED_FIELDS.difference(record))
    if missing:
        raise ProvenanceValidationError(
            "provenance record is missing required fields: " + ", ".join(missing)
        )

    label = record["label"]
    if label not in PROVENANCE_LABELS:
        raise ProvenanceValidationError(f"invalid provenance label: {label!r}")

    recorded_digest = record["sha256"]
    if not isinstance(recorded_digest, str) or not SHA256_RE.fullmatch(recorded_digest):
        raise ProvenanceValidationError("provenance sha256 must be 64 lowercase hex characters")
    if recorded_digest != artifact_sha256:
        raise ProvenanceValidationError(
            f"provenance sha256 mismatch: recorded {recorded_digest}, actual {artifact_sha256}"
        )

    recorded_size = record["size_bytes"]
    if isinstance(recorded_size, bool) or not isinstance(recorded_size, int) or recorded_size < 0:
        raise ProvenanceValidationError("provenance size_bytes must be a non-negative integer")
    if recorded_size != artifact_size:
        raise ProvenanceValidationError(
            f"provenance size mismatch: recorded {recorded_size}, actual {artifact_size}"
        )

    for field in (
        "created_at_utc",
        "creating_command",
        "run_id",
        "model_revision",
        "license_identifier",
        "transformation",
    ):
        if not _nonempty_string(record, field):
            raise ProvenanceValidationError(f"provenance {field} must be a non-empty string")

    created_at = record["created_at_utc"]
    try:
        parsed_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceValidationError(
            "provenance created_at_utc must be an ISO-8601 timestamp"
        ) from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise ProvenanceValidationError("provenance created_at_utc must include a UTC offset")
    if parsed_time.utcoffset().total_seconds() != 0:
        raise ProvenanceValidationError("provenance created_at_utc must be UTC")

    source_ids = record["source_ids"]
    if (
        isinstance(source_ids, (str, bytes))
        or not isinstance(source_ids, Sequence)
        or not source_ids
        or any(not isinstance(value, str) or not value.strip() for value in source_ids)
    ):
        raise ProvenanceValidationError(
            "provenance source_ids must be a non-empty list of non-empty strings"
        )


def write_adjacent_provenance(
    artifact_path: str | os.PathLike[str], record: Mapping[str, Any]
) -> Path:
    """Validate and exclusively write an artifact's adjacent provenance.

    ``sha256`` and ``size_bytes`` are filled from the artifact when absent.  If
    supplied, they must already match.  All other policy fields are mandatory.
    """

    artifact = Path(artifact_path)
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    normalized = dict(record)
    normalized.setdefault("sha256", sha256_file(artifact))
    normalized.setdefault("size_bytes", artifact.stat().st_size)
    _validate_provenance_record(
        normalized,
        artifact_sha256=sha256_file(artifact),
        artifact_size=artifact.stat().st_size,
    )
    return exclusive_write_json(adjacent_provenance_path(artifact), normalized)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceValidationError(f"duplicate JSON key in provenance record: {key}")
        result[key] = value
    return result


def validate_adjacent_provenance(artifact_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Validate the required sidecar, including its artifact digest and size.

    The returned copy contains only JSON values and is therefore suitable for
    embedding in an immutable run result or report.
    """

    artifact = Path(artifact_path)
    if not artifact.is_file():
        raise ProvenanceValidationError(f"artifact is missing or not a file: {artifact}")
    sidecar = adjacent_provenance_path(artifact)
    try:
        raw = sidecar.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProvenanceValidationError(f"adjacent provenance is missing: {sidecar}") from exc
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except ProvenanceValidationError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProvenanceValidationError(f"invalid provenance JSON: {sidecar}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProvenanceValidationError("provenance record must be a JSON object")

    _validate_provenance_record(
        value,
        artifact_sha256=sha256_file(artifact),
        artifact_size=artifact.stat().st_size,
    )
    return dict(value)

"""Machine-readable provenance records for external and generated artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVENANCE_LABELS = frozenset(
    {
        "external_upstream",
        "synthetic_model_output",
        "derived_audio",
        "latent_checkpoint",
    }
)


class ProvenanceError(ValueError):
    """Raised when provenance is absent, malformed, or inconsistent."""


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Return the SHA-256 of *path* without loading the whole file into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adjacent_provenance_path(artifact: str | Path) -> Path:
    """Return the required ``<filename>.provenance.json`` sidecar path."""

    artifact_path = Path(artifact)
    return artifact_path.with_name(f"{artifact_path.name}.provenance.json")


def _exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)


def write_artifact_provenance(
    artifact: str | Path,
    *,
    label: str,
    run_id: str,
    model_revision: str,
    license_id: str,
    command: str,
    parents: Iterable[Mapping[str, str]] = (),
    transformation: str = "none",
    metadata: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> Path:
    """Create, without clobbering, the provenance sidecar for an artifact."""

    if label not in PROVENANCE_LABELS:
        raise ProvenanceError(f"unknown provenance label: {label}")
    artifact_path = Path(artifact)
    if not artifact_path.is_file():
        raise ProvenanceError(f"artifact is not a file: {artifact_path}")
    record = {
        "artifact": str(artifact_path.resolve()),
        "byte_size": artifact_path.stat().st_size,
        "command": command,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "label": label,
        "license_id": license_id,
        "metadata": dict(metadata or {}),
        "model_revision": model_revision,
        "parents": list(parents),
        "run_id": run_id,
        "sha256": sha256_file(artifact_path),
        "transformation": transformation,
    }
    sidecar = adjacent_provenance_path(artifact_path)
    _exclusive_json(sidecar, record)
    return sidecar


def validate_artifact_provenance(artifact: str | Path) -> dict[str, Any]:
    """Validate a required adjacent sidecar against current artifact bytes."""

    artifact_path = Path(artifact)
    sidecar = adjacent_provenance_path(artifact_path)
    if not sidecar.is_file():
        raise ProvenanceError(f"missing provenance sidecar: {sidecar}")
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"invalid provenance sidecar {sidecar}: {exc}") from exc
    required = {
        "artifact",
        "byte_size",
        "command",
        "created_at",
        "label",
        "license_id",
        "model_revision",
        "parents",
        "run_id",
        "sha256",
        "transformation",
    }
    missing = sorted(required.difference(record))
    if missing:
        raise ProvenanceError(f"missing provenance keys: {missing}")
    if record["label"] not in PROVENANCE_LABELS:
        raise ProvenanceError(f"unknown provenance label: {record['label']}")
    if record["byte_size"] != artifact_path.stat().st_size:
        raise ProvenanceError("provenance byte size does not match artifact")
    if record["sha256"] != sha256_file(artifact_path):
        raise ProvenanceError("provenance SHA-256 does not match artifact")
    return record


def build_weight_manifest(
    snapshot_dir: str | Path,
    *,
    modelscope_revision: str,
    huggingface_revision: str,
    expected: Mapping[str, Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    """Hash a complete snapshot, verify pinned expectations, and write a manifest.

    Any ``*.incomplete`` file is a hard failure. Files absent from *expected* are
    still hashed and labelled, but only expected entries can be claimed as
    cross-provider verified.
    """

    root = Path(snapshot_dir).resolve()
    if not root.is_dir():
        raise ProvenanceError(f"snapshot is not a directory: {root}")
    incomplete = sorted(str(path.relative_to(root)) for path in root.rglob("*.incomplete"))
    if incomplete:
        raise ProvenanceError(f"incomplete snapshot files: {incomplete}")

    output = Path(output_path).resolve()
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() == output:
            continue
        relative = path.relative_to(root).as_posix()
        actual_size = path.stat().st_size
        actual_sha = sha256_file(path)
        pinned = expected.get(relative)
        if pinned is not None:
            if pinned.get("size") is not None and int(pinned["size"]) != actual_size:
                raise ProvenanceError(f"size mismatch for {relative}")
            if pinned.get("sha256") is not None and pinned["sha256"] != actual_sha:
                raise ProvenanceError(f"SHA-256 mismatch for {relative}")
        entries.append(
            {
                "byte_size": actual_size,
                "cross_provider_verified": bool(
                    pinned and pinned.get("cross_provider_verified", False)
                ),
                "label": "external_upstream",
                "path": relative,
                "role": (pinned or {}).get("role", "snapshot_metadata"),
                "sha256": actual_sha,
            }
        )

    absent = sorted(set(expected).difference(item["path"] for item in entries))
    if absent:
        raise ProvenanceError(f"expected snapshot files absent: {absent}")

    manifest = {
        "artifact_root": str(root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": entries,
        "huggingface": {
            "provider_role": "UPSTREAM",
            "repo_id": "stabilityai/stable-audio-3-medium-base",
            "revision": huggingface_revision,
        },
        "label": "external_upstream",
        "licenses": [
            "Stability AI Community License Agreement (2024-07-05)",
            "Gemma Terms of Use",
            "Gemma Prohibited Use Policy",
        ],
        "modelscope": {
            "organization_label": "Stability AI - Mirror",
            "provider_role": "MIRROR",
            "repo_id": "stabilityai/stable-audio-3-medium-base",
            "revision": modelscope_revision,
        },
        "schema_version": 1,
    }
    _exclusive_json(output, manifest)
    return manifest

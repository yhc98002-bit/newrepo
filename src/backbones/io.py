"""No-clobber output and offline snapshot helpers for backbone adapters."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backbones.contracts import SHA256_RE, BackboneConfigurationError, sha256_file


def copy_file_exclusive(source: str | Path, destination: str | Path) -> Path:
    """Copy a completed file to a new destination, refusing to replace any path."""

    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as source_handle, destination_path.open("xb") as dest_handle:
        shutil.copyfileobj(source_handle, dest_handle, length=8 * 1024 * 1024)
        dest_handle.flush()
        os.fsync(dest_handle.fileno())
    return destination_path


@contextmanager
def temporary_output_path(*, suffix: str = ".wav") -> Iterator[Path]:
    """Yield an absent path inside a private temporary directory."""

    with tempfile.TemporaryDirectory(prefix="benchmark-backbone-") as root:
        yield Path(root) / f"model-output{suffix}"


def verify_checkpoint_files(
    root: str | Path,
    required_files: Sequence[Mapping[str, Any]],
    *,
    hash_files: bool = True,
) -> list[dict[str, Any]]:
    """Verify a local checkpoint by exact path, size, and optionally SHA-256.

    This function never resolves aliases, downloads files, or falls back to a
    provider cache. Any ``*.incomplete`` file is a hard failure.
    """

    checkpoint_root = Path(root).resolve()
    if not checkpoint_root.is_dir():
        raise BackboneConfigurationError(f"checkpoint directory is absent: {checkpoint_root}")
    incomplete = sorted(
        str(path.relative_to(checkpoint_root)) for path in checkpoint_root.rglob("*.incomplete")
    )
    if incomplete:
        raise BackboneConfigurationError(f"incomplete checkpoint artifacts: {incomplete}")

    observed: list[dict[str, Any]] = []
    for entry in required_files:
        relative = entry.get("path")
        expected_size = entry.get("size_bytes")
        expected_sha = entry.get("sha256")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise BackboneConfigurationError("checkpoint path must be non-empty and relative")
        if ".." in Path(relative).parts:
            raise BackboneConfigurationError(f"checkpoint path escapes its root: {relative}")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            raise BackboneConfigurationError(f"invalid expected size for {relative}")
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            raise BackboneConfigurationError(f"invalid expected SHA-256 for {relative}")
        path = checkpoint_root / relative
        if not path.is_file():
            raise BackboneConfigurationError(f"required checkpoint file is absent: {relative}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise BackboneConfigurationError(
                f"checkpoint size mismatch for {relative}: {actual_size} != {expected_size}"
            )
        actual_sha = sha256_file(path) if hash_files else None
        if hash_files and actual_sha != expected_sha:
            raise BackboneConfigurationError(
                f"checkpoint SHA-256 mismatch for {relative}: {actual_sha} != {expected_sha}"
            )
        observed.append(
            {
                "path": relative,
                "size_bytes": actual_size,
                "sha256": actual_sha,
                "hash_verified": hash_files,
            }
        )
    return observed

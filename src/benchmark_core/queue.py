"""Build the exact benchmark-v2 generation queue without invoking a model."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmark_core.config import NON_EXECUTABLE_QUEUE_STATUSES, QUEUE_STATUSES, READY, strict_json

AXIS_FILES = (
    ("vocal_instrumental", "vocal_instrumental.json"),
    ("tempo", "tempo.json"),
    ("integrity", "integrity.json"),
    ("structure_exploratory", "structure_exploratory.json"),
)
EXPECTED_OUTPUTS_PER_READY_BACKBONE = 1_536
ROOT_INDICES = tuple(range(8))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return the strict, stable serialization used for row hashes."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_seed(namespace: str, model_id: str, prompt_id: str, root_index: int) -> int:
    """Apply the frozen seed derivation exactly."""

    if not namespace or not model_id or not prompt_id:
        raise ValueError("namespace, model_id, and prompt_id must be non-empty")
    if root_index not in ROOT_INDICES:
        raise ValueError("root_index must be in 0..7")
    material = f"{namespace}|{model_id}|{prompt_id}|{root_index}".encode()
    return 1 + int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 2_147_483_646


def _read_json(path: Path) -> dict[str, Any]:
    return strict_json(path)


def _conditions(prompt: Mapping[str, Any]) -> Iterable[tuple[str, str]]:
    base = prompt.get("base_prompt")
    fixed = prompt.get("fixed_suffix")
    if not isinstance(base, str) or not base.strip():
        raise ValueError("prompt base_prompt must be a non-empty string")
    if not isinstance(fixed, str) or not fixed.strip():
        raise ValueError("prompt fixed_suffix must be a non-empty string")
    yield "BASE", base
    yield "FIXED", f"{base} {fixed}"
    diagnostic = prompt.get("diagnostic_negation_suffix")
    if diagnostic is not None:
        if prompt.get("request") != "instrumental":
            raise ValueError("negation diagnostic is permitted only on instrumental rows")
        if not isinstance(diagnostic, str) or not diagnostic.strip():
            raise ValueError("diagnostic_negation_suffix must be a non-empty string")
        yield "NEGATION_DIAGNOSTIC", f"{base} {diagnostic}"


def _model_slug(model: Mapping[str, Any]) -> str:
    slug = model.get("slug")
    if (
        not isinstance(slug, str)
        or not slug
        or any(char not in "-_0123456789abcdefghijklmnopqrstuvwxyz" for char in slug)
    ):
        raise ValueError("model slug must contain only lowercase ASCII letters, digits, '-' or '_'")
    return slug


def _queue_rows(
    config: Mapping[str, Any],
    prompt_root: Path,
    *,
    authorized_model_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    seed_registry = _read_json(prompt_root / "seed_registry.json")
    namespace = seed_registry.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("seed registry lacks namespace")

    models = config.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("core config must contain models")
    ready_model_ids = {
        model.get("model_id")
        for model in models
        if isinstance(model, dict) and model.get("queue_status") == READY
    }
    if authorized_model_ids is None:
        authorized_ids = ready_model_ids
    else:
        authorized_ids = set(authorized_model_ids)
        if (
            not authorized_model_ids
            or len(authorized_ids) != len(authorized_model_ids)
            or not authorized_ids.issubset(ready_model_ids)
        ):
            raise ValueError("authorized_model_ids must uniquely select READY backbones")
    rows: list[dict[str, Any]] = []
    sequence = 0
    model_ids: set[str] = set()
    slugs: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("each model config must be an object")
        status = model.get("queue_status")
        if status not in QUEUE_STATUSES:
            raise ValueError(f"unsupported queue_status: {status!r}")
        model_id = model.get("model_id")
        slug = _model_slug(model)
        if not isinstance(model_id, str) or model_id in model_ids or slug in slugs:
            raise ValueError("model IDs and slugs must be unique non-empty strings")
        model_ids.add(model_id)
        slugs.add(slug)
        if status in NON_EXECUTABLE_QUEUE_STATUSES:
            continue
        if status != READY:  # defensive if QUEUE_STATUSES grows later
            raise ValueError(f"queue status is not executable: {status}")
        if model_id not in authorized_ids:
            continue
        if not isinstance(model_id, str) or model_id not in seed_registry.get("models", []):
            raise ValueError(f"ready model is absent from seed registry: {model_id!r}")
        before = len(rows)
        for expected_axis, filename in AXIS_FILES:
            package = _read_json(prompt_root / filename)
            prompt_rows = package.get("rows")
            if not isinstance(prompt_rows, list) or not prompt_rows:
                raise ValueError(f"prompt file has no rows: {filename}")
            for prompt in prompt_rows:
                if not isinstance(prompt, dict) or prompt.get("axis") != expected_axis:
                    raise ValueError(f"axis mismatch in {filename}")
                prompt_id = prompt.get("prompt_id")
                cluster_id = prompt.get("cluster_id")
                if not isinstance(prompt_id, str) or not isinstance(cluster_id, str):
                    raise ValueError(f"invalid prompt identity in {filename}")
                safe_chars = "-_0123456789abcdefghijklmnopqrstuvwxyz"
                if not prompt_id or any(char not in safe_chars for char in prompt_id):
                    raise ValueError(f"unsafe prompt_id in {filename}: {prompt_id!r}")
                for condition, exact_prompt in _conditions(prompt):
                    for root_index in ROOT_INDICES:
                        sequence += 1
                        seed = derive_seed(namespace, model_id, prompt_id, root_index)
                        relative_output = (
                            Path(slug)
                            / expected_axis
                            / prompt_id
                            / condition.lower()
                            / f"root-{root_index:02d}.wav"
                        )
                        row = {
                            "axis": expected_axis,
                            "cluster_id": cluster_id,
                            "condition": condition,
                            "duration_seconds": 30.0,
                            "model_id": model_id,
                            "model_slug": slug,
                            "output_relpath": relative_output.as_posix(),
                            "prompt": exact_prompt,
                            "prompt_id": prompt_id,
                            "root_index": root_index,
                            "seed": seed,
                            "sequence": sequence,
                        }
                        row["request_sha256"] = hashlib.sha256(
                            canonical_json(row).encode()
                        ).hexdigest()
                        rows.append(row)
        observed = len(rows) - before
        if observed != EXPECTED_OUTPUTS_PER_READY_BACKBONE:
            raise ValueError(
                f"ready backbone {model_id} has {observed} rows, expected "
                f"{EXPECTED_OUTPUTS_PER_READY_BACKBONE}"
            )
    if not rows:
        raise ValueError("no READY backbone received queue rows")
    return rows


def build_queue(
    config_path: Path,
    output_dir: Path,
    *,
    authorized_model_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create an immutable JSONL queue and manifest under an absent directory."""

    config_path = config_path.resolve(strict=True)
    config = _read_json(config_path)
    if config.get("schema_version") != 2:
        raise ValueError("benchmark core config schema_version must equal 2")
    prompt_root_value = config.get("prompt_root")
    if not isinstance(prompt_root_value, str):
        raise ValueError("core config lacks prompt_root")
    prompt_root = (config_path.parent.parent / prompt_root_value).resolve()
    expected_hashes = config.get("prompt_sha256")
    if not isinstance(expected_hashes, dict):
        raise ValueError("core config lacks prompt_sha256")
    for _, filename in AXIS_FILES:
        if sha256_file(prompt_root / filename) != expected_hashes.get(filename):
            raise ValueError(f"prompt hash mismatch: {filename}")
    if sha256_file(prompt_root / "seed_registry.json") != expected_hashes.get("seed_registry.json"):
        raise ValueError("seed registry hash mismatch")

    rows = _queue_rows(
        config,
        prompt_root,
        authorized_model_ids=authorized_model_ids,
    )
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    _fsync_directory(output_dir.parent)
    _fsync_directory(output_dir.parent.parent)
    queue_path = output_dir / "queue.jsonl"
    with queue_path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(output_dir)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["model_id"]] = counts.get(row["model_id"], 0) + 1
    manifest = {
        "config_path": str(config_path),
        "config_sha256": sha256_file(config_path),
        "model_row_counts": counts,
        "queue_path": str(queue_path),
        "queue_sha256": sha256_file(queue_path),
        "row_count": len(rows),
        "schema_version": 1,
    }
    manifest_path = output_dir / "queue-manifest.json"
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(output_dir)
    return manifest


def load_queue(queue_path: Path) -> list[dict[str, Any]]:
    """Load and verify an immutable queue created by :func:`build_queue`."""

    rows: list[dict[str, Any]] = []
    for expected_sequence, line in enumerate(
        queue_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("sequence") != expected_sequence:
            raise ValueError("queue sequence is not contiguous")
        claimed = row.pop("request_sha256", None)
        observed = hashlib.sha256(canonical_json(row).encode()).hexdigest()
        row["request_sha256"] = claimed
        if claimed != observed:
            raise ValueError(f"queue row hash mismatch at sequence {expected_sequence}")
        rows.append(row)
    if not rows:
        raise ValueError("queue is empty")
    return rows

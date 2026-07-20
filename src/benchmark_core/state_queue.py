"""Root-local checkpoint/preview capture contracts for eligibility analysis."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmark_core.config import StateCapturePolicy
from benchmark_core.queue import canonical_json, sha256_file


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fraction_label(fraction: float) -> str:
    return f"{round(fraction * 1_000_000):06d}"


def state_capture_rows(
    generation_rows: Iterable[Mapping[str, Any]],
    policy: StateCapturePolicy,
    *,
    root_indices: Sequence[int],
    tier: str,
    authorization_status: str,
) -> list[dict[str, Any]]:
    """Create in-call capture units tied to the same prompt/root generation request."""

    result: list[dict[str, Any]] = []
    seen_parents: set[str] = set()
    sequence = 0
    for generation in generation_rows:
        parent = generation.get("request_sha256")
        if not isinstance(parent, str) or len(parent) != 64:
            raise ValueError("generation row lacks request_sha256")
        if parent in seen_parents:
            raise ValueError("generation request hashes must be unique")
        seen_parents.add(parent)
        if generation.get("model_id") not in policy.eligible_model_ids:
            continue
        if generation.get("axis") not in policy.axes:
            continue
        if generation.get("condition") not in policy.conditions:
            continue
        if generation.get("prompt_id") not in policy.eligible_prompt_ids:
            continue
        root = generation.get("root_index")
        if isinstance(root, bool) or not isinstance(root, int) or not 0 <= root <= 7:
            raise ValueError("state parent has an invalid root")
        if root not in root_indices:
            continue
        output = Path(str(generation.get("output_relpath", "")))
        if output.is_absolute() or ".." in output.parts or output.suffix.lower() != ".wav":
            raise ValueError("state parent output_relpath is unsafe")
        state_root = Path("state") / output.with_suffix("")
        for fraction in policy.checkpoint_fractions:
            sequence += 1
            label = _fraction_label(fraction)
            row: dict[str, Any] = {
                "axis": generation["axis"],
                "capture_mode": policy.capture_mode,
                "authorization_status": authorization_status,
                "checkpoint_fraction": fraction,
                "checkpoint_relpath": (state_root / f"checkpoint-{label}.state").as_posix(),
                "condition": generation["condition"],
                "model_id": generation["model_id"],
                "parent_request_sha256": parent,
                "preview_relpath": (state_root / f"preview-{label}.wav").as_posix(),
                "preview_source": policy.preview_source,
                "preview_source_request_sha256": parent,
                "prompt_id": generation["prompt_id"],
                "restart_outcome_label": policy.restart_outcome_label,
                "resume_output_relpath": (state_root / f"resumed-terminal-{label}.wav").as_posix(),
                "root_index": root,
                "sequence": sequence,
                "tier": tier,
            }
            row["state_request_sha256"] = hashlib.sha256(canonical_json(row).encode()).hexdigest()
            result.append(row)
    if not result:
        raise ValueError("state-capture policy selected no generation rows")
    units = {
        (row["model_id"], row["prompt_id"], row["root_index"], row["checkpoint_fraction"])
        for row in result
    }
    if len(units) != len(result):
        raise ValueError("state-capture units are not unique (prompt, root, checkpoint)")
    counts: dict[str, int] = {}
    for row in result:
        counts[row["model_id"]] = counts.get(row["model_id"], 0) + 1
    expected_per_model = (
        len(policy.eligible_prompt_ids) * len(root_indices) * len(policy.checkpoint_fractions)
    )
    if set(counts) != set(policy.eligible_model_ids) or any(
        count != expected_per_model for count in counts.values()
    ):
        raise ValueError(
            "state tier must select exactly 36 prompts x 4 roots x 3 checkpoints per capable model"
        )
    return result


def build_state_capture_queue(
    generation_rows: Iterable[Mapping[str, Any]],
    policy: StateCapturePolicy,
    output_dir: Path,
    *,
    root_indices: Sequence[int],
    tier: str,
    authorization_status: str,
) -> dict[str, Any]:
    """Write a no-clobber state capture queue; this invokes no model."""

    rows = state_capture_rows(
        generation_rows,
        policy,
        root_indices=root_indices,
        tier=tier,
        authorization_status=authorization_status,
    )
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    _fsync_directory(output.parent)
    _fsync_directory(output.parent.parent)
    queue_path = output / "state-capture-queue.jsonl"
    with queue_path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(output)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["model_id"]] = counts.get(row["model_id"], 0) + 1
    manifest = {
        "capture_mode": policy.capture_mode,
        "authorization_status": authorization_status,
        "model_row_counts": counts,
        "preview_source": policy.preview_source,
        "queue_path": str(queue_path),
        "queue_sha256": sha256_file(queue_path),
        "restart_outcome_label": policy.restart_outcome_label,
        "row_count": len(rows),
        "schema_version": 1,
        "tier": tier,
    }
    manifest_path = output / "state-capture-manifest.json"
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(output)
    return manifest


def load_state_capture_queue(path: Path) -> list[dict[str, Any]]:
    """Validate a state queue, including its root-local preview binding."""

    rows: list[dict[str, Any]] = []
    units: set[tuple[Any, ...]] = set()
    for expected_sequence, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("sequence") != expected_sequence:
            raise ValueError("state queue sequence is not contiguous")
        claimed = row.pop("state_request_sha256", None)
        observed = hashlib.sha256(canonical_json(row).encode()).hexdigest()
        row["state_request_sha256"] = claimed
        if claimed != observed:
            raise ValueError(f"state queue row hash mismatch at sequence {expected_sequence}")
        if row.get("preview_source_request_sha256") != row.get("parent_request_sha256"):
            raise ValueError("state preview is not bound to its own root request")
        unit = (
            row.get("model_id"),
            row.get("prompt_id"),
            row.get("root_index"),
            row.get("checkpoint_fraction"),
        )
        if unit in units:
            raise ValueError("duplicate state-capture unit")
        units.add(unit)
        rows.append(row)
    if not rows:
        raise ValueError("state capture queue is empty")
    return rows

"""Strict configuration loading for automatic scoring v2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scoring.common import load_json, require_exact_keys, require_sha256, sha256_file

CONFIG_KEYS = {
    "axes",
    "backbones",
    "execution",
    "feature_contract",
    "frozen_inputs",
    "gpu_guard",
    "output",
    "primary_backbones",
    "run_id",
    "schema_version",
    "sources",
    "status",
}
SOURCE_KEYS = {
    "backbone",
    "completion_mode",
    "expected_completed_rows",
    "expected_completed_shards",
    "expected_queue_rows",
    "expected_hashes",
    "model_id",
    "model_slug",
    "run_dir",
    "run_id",
    "worker_slug",
}
EXPECTED_PRIMARY_BACKBONES = [
    "stable-audio-3-medium-base",
    "stable-audio-open-1.0",
    "ACE-Step v1",
]
CANONICAL_RUN_ID = "automatic-scoring-v2-001"
CANONICAL_CANDIDATE_INDEX = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "runs/scoring-v2/automatic-scoring-v2-001/tables/human-audit-candidate-index.json"
)


def _verify_frozen(repo_root: Path, rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        require_exact_keys(row, {"path", "sha256"}, f"frozen_inputs[{index}]")
        expected = require_sha256(row["sha256"], f"frozen_inputs[{index}].sha256")
        path = (repo_root / str(row["path"])).resolve()
        if sha256_file(path) != expected:
            raise ValueError(f"frozen input hash mismatch: {path}")


def load_config(path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Load and validate the no-launch scoring configuration."""

    config_path = path.resolve()
    root = (repo_root or config_path.parents[1]).resolve()
    value = require_exact_keys(load_json(config_path), CONFIG_KEYS, "scoring config")
    if value["schema_version"] != 1 or value["run_id"] != CANONICAL_RUN_ID:
        raise ValueError("automatic scoring config identity is invalid")
    if value["status"] != "IMPLEMENTED_NOT_LAUNCHED":
        raise ValueError("scoring config must remain in the no-launch state")
    if value["primary_backbones"] != EXPECTED_PRIMARY_BACKBONES:
        raise ValueError("primary backbone header differs from rater schema v2")
    axes = value["axes"]
    if axes != {
        "confirmatory": ["vocal_instrumental", "tempo", "integrity"],
        "exploratory_only": ["structure_exploratory"],
    }:
        raise ValueError("axis roles differ from frozen preregistration v2")
    _verify_frozen(root, value["frozen_inputs"])

    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("exactly the completed SA3 and incremental ACE sources are required")
    for index, source in enumerate(sources):
        require_exact_keys(source, SOURCE_KEYS, f"source[{index}]")
        if source["completion_mode"] not in {"FULL", "INCREMENTAL_ADDITION"}:
            raise ValueError("source completion_mode is invalid")
        if source["backbone"] not in EXPECTED_PRIMARY_BACKBONES:
            raise ValueError("source backbone is not primary")
        for key, digest in source["expected_hashes"].items():
            require_sha256(digest, f"source[{index}].expected_hashes.{key}")
        for key in (
            "expected_completed_rows",
            "expected_completed_shards",
            "expected_queue_rows",
        ):
            count = source[key]
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError(f"source[{index}].{key} must be a positive integer")

    backbones = value["backbones"]
    if [row.get("backbone") for row in backbones] != EXPECTED_PRIMARY_BACKBONES:
        raise ValueError("backbone status order differs from the primary header")
    if backbones[1].get("status") != "MISSING_BLOCKED_ON_LICENSE":
        raise ValueError("stable-audio-open must remain explicitly license-blocked")

    output = value["output"]
    require_exact_keys(
        output,
        {"candidate_index", "root", "scoring_status"},
        "output",
    )
    if Path(output["candidate_index"]) != CANONICAL_CANDIDATE_INDEX:
        raise ValueError("candidate-index path differs from the canonical rater input")
    root_path = Path(output["root"])
    if CANONICAL_CANDIDATE_INDEX.parent.parent != root_path:
        raise ValueError("output root and candidate-index path disagree")
    if Path(output["scoring_status"]) != root_path / "scoring-status.json":
        raise ValueError("scoring-status path is not canonical")
    return value

"""Strict configuration loading for automatic scoring v2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchmark_core.config import SAO_MODEL_ID, load_core_execution_config
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
    raw = load_json(config_path)
    schema_version = raw.get("schema_version")
    expected_keys = CONFIG_KEYS if schema_version == 1 else CONFIG_KEYS | {"sao_gate"}
    value = require_exact_keys(raw, expected_keys, "scoring config")
    if schema_version not in {1, 2}:
        raise ValueError("automatic scoring config schema_version is unsupported")
    if schema_version == 1 and value["run_id"] != CANONICAL_RUN_ID:
        raise ValueError("legacy automatic scoring config identity is invalid")
    if schema_version == 2 and not str(value["run_id"]).startswith(
        "automatic-scoring-v2-sao-"
    ):
        raise ValueError("SAO scoring continuation run_id is invalid")
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
    expected_source_count = 2 if schema_version == 1 else 3
    if not isinstance(sources, list) or len(sources) != expected_source_count:
        raise ValueError(
            f"schema-{schema_version} scoring requires {expected_source_count} sources"
        )
    for index, source in enumerate(sources):
        require_exact_keys(source, SOURCE_KEYS, f"source[{index}]")
        allowed_modes = {"FULL", "INCREMENTAL_ADDITION"}
        if schema_version == 2:
            allowed_modes.add("INCREMENTAL_PREFIX")
        if source["completion_mode"] not in allowed_modes:
            raise ValueError("source completion_mode is invalid")
        if source["backbone"] not in EXPECTED_PRIMARY_BACKBONES:
            raise ValueError("source backbone is not primary")
        expected_hash_keys = (
            {"run_manifest", "queue", "ledger_tail"}
            if source["completion_mode"] == "INCREMENTAL_PREFIX"
            else {"run_manifest", "queue", "ledger", "heartbeat", "ledger_tail"}
        )
        if set(source["expected_hashes"]) != expected_hash_keys:
            raise ValueError("source expected_hashes keys differ from its completion mode")
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
    if schema_version == 1:
        if backbones[1].get("status") != "MISSING_BLOCKED_ON_LICENSE":
            raise ValueError("legacy stable-audio-open status must remain license-blocked")
    else:
        if {source["backbone"] for source in sources} != set(EXPECTED_PRIMARY_BACKBONES):
            raise ValueError("SAO scoring continuation must bind all three primary backbones")
        if backbones[1].get("status") not in {
            "INCREMENTAL_SOURCE_READY",
            "COMPLETED_SOURCE_READY",
        }:
            raise ValueError("SAO scoring source is neither incremental nor complete")
        gate = require_exact_keys(
            value["sao_gate"],
            {
                "decision_id",
                "access_receipt_path",
                "access_receipt_sha256",
                "core_authorization_path",
                "core_authorization_sha256",
                "core_config_path",
                "core_config_sha256",
                "state_capability",
                "eligibility_scope_expanded",
            },
            "sao_gate",
        )
        if (
            gate["decision_id"] != "D-0037"
            or gate["state_capability"] != "NOT_ATTEMPTED"
            or gate["eligibility_scope_expanded"] is not False
        ):
            raise ValueError("SAO scoring gate expands beyond generation+automatic scoring")
        for path_key, hash_key in (
            ("access_receipt_path", "access_receipt_sha256"),
            ("core_authorization_path", "core_authorization_sha256"),
            ("core_config_path", "core_config_sha256"),
        ):
            candidate = Path(str(gate[path_key]))
            candidate = (
                candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            )
            expected = require_sha256(gate[hash_key], f"sao_gate.{hash_key}")
            if sha256_file(candidate) != expected:
                raise ValueError(f"SAO scoring gate hash mismatch: {path_key}")
        core_path = Path(str(gate["core_config_path"]))
        core_path = core_path.resolve() if core_path.is_absolute() else (root / core_path).resolve()
        core_config = load_core_execution_config(core_path, repo_root=root)
        sao_models = [model for model in core_config.models if model.model_id == SAO_MODEL_ID]
        if (
            len(sao_models) != 1
            or sao_models[0].sao_runtime is None
            or sao_models[0].sao_runtime.access_receipt_sha256
            != gate["access_receipt_sha256"]
            or sao_models[0].sao_runtime.core_authorization_sha256
            != gate["core_authorization_sha256"]
        ):
            raise ValueError("SAO scoring gate differs from the verified core runtime binding")

    output = value["output"]
    require_exact_keys(
        output,
        {"candidate_index", "root", "scoring_status"},
        "output",
    )
    if schema_version == 1 and Path(output["candidate_index"]) != CANONICAL_CANDIDATE_INDEX:
        raise ValueError("legacy candidate-index path differs from the canonical rater input")
    root_path = Path(output["root"])
    if Path(output["candidate_index"]) != root_path / "tables" / "human-audit-candidate-index.json":
        raise ValueError("output root and candidate-index path disagree")
    if schema_version == 2 and root_path == CANONICAL_CANDIDATE_INDEX.parent.parent:
        raise ValueError("SAO continuation may not overwrite the immutable legacy scoring run")
    if Path(output["scoring_status"]) != root_path / "scoring-status.json":
        raise ValueError("scoring-status path is not canonical")
    return value

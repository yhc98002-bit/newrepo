"""Fail-closed assembly contract for frozen-instrument state-action inputs.

This module does not run an evaluator or inspect audio.  It accepts only
already-published, hash-bound outputs of the frozen automatic instruments and
the four root-local preview feature groups.  Missing assembly inputs are an
error; no proxy score, human label, or terminal feature can fill a gap.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eligibility.contract import (
    ACTIONS,
    EXPECTED_INITIAL_ROWS,
    EXPECTED_INITIAL_UNITS,
    ROOT_LOCAL_SOURCE,
    TIER,
    WATERMARK,
    AnalysisConfig,
    EligibilityContractError,
    _expected_prompt_factors,
    _prompt_registry,
    _validate_action,
    _validate_budget,
    _validate_queue_unit,
    _validate_state_features,
)
from scoring.common import (
    canonical_json,
    load_json,
    load_jsonl,
    require_exact_keys,
    require_sha256,
    sha256_file,
    sha256_json,
)

PREVIEW_KEYS = {
    "axis",
    "checkpoint_fraction",
    "evaluator_identities_sha256",
    "held_out_fitted_value_used",
    "human_gold_used",
    "lane_request_sha256",
    "model_id",
    "other_root_preview_used",
    "preview_audio_sha256",
    "preview_source",
    "preview_source_request_sha256",
    "root_index",
    "schema_version",
    "state_features",
    "terminal_features_used",
}
OUTCOME_KEYS = {
    "automatic_result_wording",
    "axis",
    "evaluator_identities_sha256",
    "human_gold_used",
    "metrics",
    "outcome_audio_sha256",
    "outcome_binding_sha256",
    "outcome_valid",
    "schema_version",
    "watermark",
}
COST_KEYS = {
    "elapsed_nfe",
    "elapsed_seconds",
    "lane_request_sha256",
    "remaining_nfe",
    "remaining_seconds",
    "schema_version",
    "total_nfe",
    "total_seconds",
}
_WORDING = {
    "vocal_instrumental": "AUTOMATIC_INSTRUMENT_OUTCOME_NOT_HUMAN_VOICE_JUDGMENT",
    "tempo": "AUTOMATIC_TEMPO_INSTRUMENT_OUTCOME_NOT_HUMAN_TAP_GOLD",
    "integrity": "OBJECTIVE_DSP_OUTCOME_NOT_HUMAN_AUDIBLE_DEFECT_GOLD",
}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_jsonl_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)
    _fsync_directory(path.parent)


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)
    _fsync_directory(path.parent)


def _bound_manifest_file(manifest: Mapping[str, Any], name: str) -> Path:
    record = manifest.get(name)
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise EligibilityContractError(f"queue manifest lacks {name} binding")
    path = Path(record["path"])
    if not path.is_absolute():
        raise EligibilityContractError(f"queue manifest {name} path must be absolute")
    path = path.resolve(strict=True)
    if sha256_file(path) != require_sha256(record.get("sha256"), f"queue {name} SHA"):
        raise EligibilityContractError(f"queue manifest {name} binding drifted")
    return path


def _scoring_identity(config: AnalysisConfig) -> tuple[str, dict[str, str]]:
    scoring = load_json(config.repo_root / "configs/automatic_scoring_v2.json")
    identities = scoring["feature_contract"]["expected_evaluator_identities"]
    code = {
        "integrity": sha256_file(config.repo_root / "src/instruments/integrity.py"),
        "tempo": sha256_file(config.repo_root / "src/instruments/tempo.py"),
        "voice": sha256_file(config.repo_root / "src/instruments/voice.py"),
    }
    return sha256_json(identities), code


def _outcome_success(axis: str, row: Mapping[str, Any]) -> bool:
    metrics = row["metrics"]
    if not isinstance(metrics, dict):
        raise EligibilityContractError("outcome metrics must be an object")
    if axis == "vocal_instrumental":
        metrics = require_exact_keys(metrics, {"automatic_instrument_success"}, "voice metrics")
        value = metrics["automatic_instrument_success"]
    elif axis == "tempo":
        metrics = require_exact_keys(metrics, {"full_clip_primary_5pct_success"}, "tempo metrics")
        value = metrics["full_clip_primary_5pct_success"]
    else:
        metrics = require_exact_keys(
            metrics, {"file_validity_failure", "integrity_failure"}, "integrity metrics"
        )
        invalid = metrics["file_validity_failure"]
        failure = metrics["integrity_failure"]
        if not isinstance(invalid, bool) or (failure is not None and not isinstance(failure, bool)):
            raise EligibilityContractError("integrity outcome metrics are invalid")
        value = False if invalid else not bool(failure)
    if not isinstance(value, bool):
        raise EligibilityContractError("primary automatic outcome must be Boolean")
    return value


def assemble_initial_rows(
    *,
    config: AnalysisConfig,
    backbone: str,
    model_id: str,
    axis: str,
    queue_units: Sequence[dict[str, Any]],
    action_rows: Sequence[dict[str, Any]],
    survivor_units: Sequence[dict[str, Any]],
    preview_rows: Sequence[dict[str, Any]],
    outcome_rows: Sequence[dict[str, Any]],
    cost_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join exact queue mappings to frozen-instrument results, never infer gaps."""

    evaluator_sha, _ = _scoring_identity(config)
    queue_index: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(queue_units):
        identity = _validate_queue_unit(unit, f"queue unit {index}")
        queue_index[identity] = unit
    survivor_ids = {
        require_sha256(unit.get("lane_request_sha256"), "survivor lane identity")
        for unit in survivor_units
        if unit.get("axis") == axis
    }
    if len(survivor_ids) != EXPECTED_INITIAL_UNITS:
        raise EligibilityContractError("builder requires exactly one 144-unit survivor cell")
    units = {identity: queue_index[identity] for identity in survivor_ids}
    if any(unit["axis"] != axis for unit in units.values()):
        raise EligibilityContractError("builder survivor set crosses axes")
    actions: dict[tuple[str, str], dict[str, Any]] = {}
    for index, action in enumerate(action_rows):
        _validate_action(action, f"action row {index}")
        identity = action["lane_request_sha256"]
        if identity not in survivor_ids:
            continue
        key = (identity, action["action"])
        if key in actions:
            raise EligibilityContractError("builder action mapping is duplicated")
        actions[key] = action
    if len(actions) != EXPECTED_INITIAL_ROWS:
        raise EligibilityContractError("builder action map is incomplete")

    previews: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(preview_rows):
        row = require_exact_keys(raw, PREVIEW_KEYS, f"preview row {index}")
        identity = require_sha256(row["lane_request_sha256"], "preview lane identity")
        if identity not in units or identity in previews:
            raise EligibilityContractError("preview row is duplicate or not a survivor")
        unit = units[identity]
        if (
            row["schema_version"] != 1
            or row["axis"] != axis
            or row["model_id"] != model_id
            or row["root_index"] != unit["root_index"]
            or row["checkpoint_fraction"] != unit["checkpoint_fraction"]
            or row["preview_source"] != ROOT_LOCAL_SOURCE
            or row["preview_source_request_sha256"] != unit["preview_source_request_sha256"]
            or row["evaluator_identities_sha256"] != evaluator_sha
            or row["human_gold_used"] is not False
            or row["terminal_features_used"] is not False
            or row["other_root_preview_used"] is not False
            or row["held_out_fitted_value_used"] is not False
        ):
            raise EligibilityContractError(
                "preview row violates root-local frozen-instrument scope"
            )
        require_sha256(row["preview_audio_sha256"], "preview audio SHA")
        state = _validate_state_features(
            row["state_features"], axis=axis, config=config, label="preview"
        )
        completed_budget = unit.get(
            "checkpoint_completed_steps", unit.get("checkpoint_cumulative_transformer_nfe")
        )
        total_budget = unit.get("transformer_budget_nfe", unit.get("total_transformer_nfe"))
        decoder = state["frozen_decoder_metadata"]
        if (
            completed_budget is None
            or total_budget is None
            or decoder["preview_sha256"] != row["preview_audio_sha256"]
            or float(decoder["checkpoint_fraction"]) != float(row["checkpoint_fraction"])
            or float(decoder["checkpoint_completed_steps"]) != float(completed_budget)
            or float(decoder["transformer_budget_nfe"]) != float(total_budget)
        ):
            raise EligibilityContractError("preview decoder metadata differs from its state unit")
        previews[identity] = row
    if set(previews) != survivor_ids:
        raise EligibilityContractError("root-local preview feature set is incomplete")

    outcomes: dict[str, tuple[dict[str, Any], bool]] = {}
    for index, raw in enumerate(outcome_rows):
        row = require_exact_keys(raw, OUTCOME_KEYS, f"outcome row {index}")
        identity = require_sha256(row["outcome_binding_sha256"], "outcome binding")
        if identity in outcomes:
            raise EligibilityContractError("automatic outcome binding is duplicated")
        if (
            row["schema_version"] != 1
            or row["watermark"] != WATERMARK
            or row["axis"] != axis
            or row["evaluator_identities_sha256"] != evaluator_sha
            or row["human_gold_used"] is not False
            or row["automatic_result_wording"] != _WORDING[axis]
            or not isinstance(row["outcome_valid"], bool)
        ):
            raise EligibilityContractError("automatic outcome receipt drifted")
        require_sha256(row["outcome_audio_sha256"], "outcome audio SHA")
        success = _outcome_success(axis, row)
        if row["outcome_valid"] is False:
            success = False
        outcomes[identity] = (row, success)

    costs: dict[str, dict[str, float]] = {}
    for index, raw in enumerate(cost_rows):
        row = require_exact_keys(raw, COST_KEYS, f"cost row {index}")
        identity = require_sha256(row["lane_request_sha256"], "cost lane identity")
        if identity not in units or identity in costs or row["schema_version"] != 1:
            raise EligibilityContractError("cost row is duplicate or not a survivor")
        base = {key: row[key] for key in COST_KEYS - {"lane_request_sha256", "schema_version"}}
        costs[identity] = _validate_budget(
            {
                **base,
                "incremental_cost_nfe": base["remaining_nfe"],
                "incremental_cost_seconds": base["remaining_seconds"],
            },
            "cost row",
        )
    if set(costs) != survivor_ids:
        raise EligibilityContractError("measured cost rows are incomplete")

    prompt_registry = _prompt_registry(config, axis)
    built: list[dict[str, Any]] = []
    used_outcomes: set[str] = set()
    for identity in sorted(survivor_ids):
        unit = units[identity]
        preview = previews[identity]
        factors, stratum = _expected_prompt_factors(axis, prompt_registry[unit["prompt_id"]])
        for action_name in ACTIONS:
            action = actions[(identity, action_name)]
            binding = (
                identity
                if action_name == "KEEP"
                else require_sha256(
                    action["outcome_source_request_sha256"], "restart outcome request"
                )
            )
            if binding not in outcomes:
                raise EligibilityContractError("a frozen mapped action outcome is unscored")
            outcome, success = outcomes[binding]
            used_outcomes.add(binding)
            budget = dict(costs[identity])
            if action_name != "KEEP":
                budget["incremental_cost_nfe"] = budget["total_nfe"]
                budget["incremental_cost_seconds"] = budget["total_seconds"]
            built.append(
                {
                    "action": action_name,
                    "action_mapping_sha256": action["action_mapping_sha256"],
                    "automatic_result_wording": outcome["automatic_result_wording"],
                    "axis": axis,
                    "backbone": backbone,
                    "budget_features": budget,
                    "checkpoint_fraction": unit["checkpoint_fraction"],
                    "fold_id": unit["fold_id"],
                    "held_out_fitted_value_used": False,
                    "human_gold_used": False,
                    "lane_request_sha256": identity,
                    "model_id": model_id,
                    "other_root_preview_used": False,
                    "outcome_audio_sha256": outcome["outcome_audio_sha256"],
                    "outcome_binding_sha256": binding,
                    "outcome_label": action["outcome_label"],
                    "outcome_source": action["outcome_source"],
                    "outcome_source_root_index": action["outcome_source_root_index"],
                    "outcome_success": success,
                    "outcome_valid": outcome["outcome_valid"],
                    "preview_audio_sha256": preview["preview_audio_sha256"],
                    "preview_source_request_sha256": preview["preview_source_request_sha256"],
                    "prompt_factors": factors,
                    "prompt_id": unit["prompt_id"],
                    "prompt_stratum": stratum,
                    "root_index": unit["root_index"],
                    "schema_version": 1,
                    "state_features": preview["state_features"],
                    "terminal_features_used": False,
                    "tier": TIER,
                    "watermark": WATERMARK,
                }
            )
    required_bindings = {
        identity if name == "KEEP" else actions[(identity, name)]["outcome_source_request_sha256"]
        for identity in survivor_ids
        for name in ACTIONS
    }
    if used_outcomes != required_bindings or set(outcomes) != required_bindings:
        raise EligibilityContractError("outcome inputs contain missing or unregistered extras")
    return built


def build_initial_input_package(
    *,
    config: AnalysisConfig,
    backbone: str,
    model_id: str,
    axis: str,
    queue_manifest_path: Path,
    survivor_manifest_path: Path,
    cancellation_manifest_path: Path,
    preview_features_path: Path,
    automatic_outcomes_path: Path,
    measured_costs_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Publish a no-clobber scored-row bundle; evaluators are never invoked."""

    queue_manifest_path = queue_manifest_path.resolve(strict=True)
    survivor_manifest_path = survivor_manifest_path.resolve(strict=True)
    cancellation_manifest_path = cancellation_manifest_path.resolve(strict=True)
    queue_manifest = load_json(queue_manifest_path)
    survivor_manifest = load_json(survivor_manifest_path)
    cancellation_manifest = load_json(cancellation_manifest_path)
    queue_units_path = _bound_manifest_file(queue_manifest, "units")
    action_path = _bound_manifest_file(queue_manifest, "action_map")
    folds_path = _bound_manifest_file(queue_manifest, "folds")
    survivor_units_path = Path(survivor_manifest["units_path"]).resolve(strict=True)
    cancellation_units_path = Path(cancellation_manifest["units_path"]).resolve(strict=True)
    if (
        sha256_file(survivor_units_path) != survivor_manifest["units_sha256"]
        or sha256_file(cancellation_units_path) != cancellation_manifest["units_sha256"]
    ):
        raise EligibilityContractError("Stage-1 input manifest hashes drifted")
    rows = assemble_initial_rows(
        config=config,
        backbone=backbone,
        model_id=model_id,
        axis=axis,
        queue_units=load_jsonl(queue_units_path),
        action_rows=load_jsonl(action_path),
        survivor_units=load_jsonl(survivor_units_path),
        preview_rows=load_jsonl(preview_features_path.resolve(strict=True)),
        outcome_rows=load_jsonl(automatic_outcomes_path.resolve(strict=True)),
        cost_rows=load_jsonl(measured_costs_path.resolve(strict=True)),
    )
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    _fsync_directory(output.parent)
    scored_path = output / "scored-state-actions.jsonl"
    _write_jsonl_exclusive(scored_path, rows)
    evaluator_sha, code_hashes = _scoring_identity(config)

    def binding(path: Path, *, row_count: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"path": str(path), "sha256": sha256_file(path)}
        if row_count is not None:
            result["row_count"] = row_count
        return result

    manifest = {
        "analysis_config_path": str(config.path),
        "analysis_config_sha256": config.sha256,
        "assembly_sources": {
            "automatic_outcomes": binding(
                automatic_outcomes_path.resolve(strict=True),
                row_count=len(load_jsonl(automatic_outcomes_path.resolve(strict=True))),
            ),
            "measured_costs": binding(
                measured_costs_path.resolve(strict=True),
                row_count=len(load_jsonl(measured_costs_path.resolve(strict=True))),
            ),
            "preview_features": binding(
                preview_features_path.resolve(strict=True),
                row_count=len(load_jsonl(preview_features_path.resolve(strict=True))),
            ),
        },
        "axis": axis,
        "backbone": backbone,
        "cancellation_manifest": binding(cancellation_manifest_path),
        "cancellation_units": binding(
            cancellation_units_path, row_count=len(load_jsonl(cancellation_units_path))
        ),
        "folds": binding(folds_path),
        "human_gold_labels_used": False,
        "instrument_scoring": {
            "assembly_status": "FROZEN_INSTRUMENT_ASSEMBLY_COMPLETE",
            "automatic_scoring_config_path": "configs/automatic_scoring_v2.json",
            "automatic_scoring_config_sha256": sha256_file(
                config.repo_root / "configs/automatic_scoring_v2.json"
            ),
            "evaluator_identities_sha256": evaluator_sha,
            "frozen_instrument_code_sha256s": code_hashes,
            "human_gold_labels_used": False,
        },
        "model_id": model_id,
        "queue_action_map": binding(action_path, row_count=len(load_jsonl(action_path))),
        "queue_manifest": binding(queue_manifest_path),
        "queue_units": binding(queue_units_path, row_count=len(load_jsonl(queue_units_path))),
        "schema_version": 1,
        "scored_rows": binding(scored_path, row_count=len(rows)),
        "status": "ELIGIBILITY_INITIAL_INPUT_COMPLETE",
        "survivor_manifest": binding(survivor_manifest_path),
        "survivor_units": binding(
            survivor_units_path, row_count=len(load_jsonl(survivor_units_path))
        ),
        "tier": TIER,
        "watermark": WATERMARK,
    }
    manifest_path = output / "input-manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
    }

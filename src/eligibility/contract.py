"""Fail-closed contracts for prospective v2 eligibility analysis.

The opening check in this module intentionally has no scored-input argument.
The command-line runner must prove that the config and its separate governance
decision are present on ``origin/main`` before it is allowed to open an input
manifest or a scored state-action row.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scoring.common import (
    canonical_json,
    load_json,
    load_jsonl,
    require_exact_keys,
    require_sha256,
    sha256_file,
)

ACTIONS = ("KEEP", "RESTART_BASE", "RESTART_FIXED")
AXES = ("vocal_instrumental", "tempo", "integrity")
CHECKPOINTS = (0.25, 0.5, 0.75)
INITIAL_ROOTS = (0, 1, 2, 3)
FOLD_COUNT = 6
PROMPT_COUNT = 12
ROWS_PER_UNIT = 3
EXPECTED_INITIAL_UNITS = PROMPT_COUNT * len(INITIAL_ROOTS) * len(CHECKPOINTS)
EXPECTED_INITIAL_ROWS = EXPECTED_INITIAL_UNITS * ROWS_PER_UNIT
WATERMARK = "AUTOMATIC-INSTRUMENT OUTCOMES"
ROOT_LOCAL_SOURCE = "ONLY_THE_SAME_UNITS_ROOT_LOCAL_PRE_ACTION_DECODED_PREVIEW"
RESTART_LABEL = "RESTART_POOL_SHARED_AT_PROMPT_LEVEL"
TIER = "INITIAL"

ROW_KEYS = {
    "action",
    "action_mapping_sha256",
    "automatic_result_wording",
    "axis",
    "backbone",
    "budget_features",
    "checkpoint_fraction",
    "fold_id",
    "held_out_fitted_value_used",
    "human_gold_used",
    "lane_request_sha256",
    "model_id",
    "other_root_preview_used",
    "outcome_audio_sha256",
    "outcome_binding_sha256",
    "outcome_label",
    "outcome_source",
    "outcome_source_root_index",
    "outcome_success",
    "outcome_valid",
    "preview_audio_sha256",
    "preview_source_request_sha256",
    "prompt_factors",
    "prompt_id",
    "prompt_stratum",
    "root_index",
    "schema_version",
    "state_features",
    "terminal_features_used",
    "tier",
    "watermark",
}
BUDGET_KEYS = {
    "elapsed_nfe",
    "elapsed_seconds",
    "incremental_cost_nfe",
    "incremental_cost_seconds",
    "remaining_nfe",
    "remaining_seconds",
    "total_nfe",
    "total_seconds",
}
PROMPT_FACTOR_KEYS = {"profile", "request", "salience", "style_family", "target_bpm"}
STATE_GROUPS = {
    "axis_evaluator_values",
    "integrity_values",
    "within_preview_summaries",
    "frozen_decoder_metadata",
}
MANIFEST_KEYS = {
    "analysis_config_path",
    "analysis_config_sha256",
    "assembly_sources",
    "axis",
    "backbone",
    "cancellation_manifest",
    "cancellation_units",
    "folds",
    "human_gold_labels_used",
    "instrument_scoring",
    "model_id",
    "queue_action_map",
    "queue_manifest",
    "queue_units",
    "schema_version",
    "scored_rows",
    "status",
    "survivor_manifest",
    "survivor_units",
    "tier",
    "watermark",
}
BINDING_KEYS = {"path", "sha256"}
ROW_BINDING_KEYS = {"path", "row_count", "sha256"}
INSTRUMENT_KEYS = {
    "assembly_status",
    "automatic_scoring_config_path",
    "automatic_scoring_config_sha256",
    "evaluator_identities_sha256",
    "frozen_instrument_code_sha256s",
    "human_gold_labels_used",
}

_EXPECTED_WORDING = {
    "vocal_instrumental": "AUTOMATIC_INSTRUMENT_OUTCOME_NOT_HUMAN_VOICE_JUDGMENT",
    "tempo": "AUTOMATIC_TEMPO_INSTRUMENT_OUTCOME_NOT_HUMAN_TAP_GOLD",
    "integrity": "OBJECTIVE_DSP_OUTCOME_NOT_HUMAN_AUDIBLE_DEFECT_GOLD",
}
_BACKBONE_MODEL = {
    "stable-audio-3-medium-base": "stabilityai/stable-audio-3-medium-base",
    "ACE-Step v1": "ACE-Step/ACE-Step-v1-3.5B",
}
_PROMPT_FILES = {
    "vocal_instrumental": "prompts/v2/vocal_instrumental.json",
    "tempo": "prompts/v2/tempo.json",
    "integrity": "prompts/v2/integrity.json",
}
_DECISION_HEADER = re.compile(r"(?m)^## (?P<id>D-[0-9]{4})\b[^\n]*$")


class EligibilityContractError(RuntimeError):
    """A prospective source, opening, queue, feature, or outcome binding drifted."""


@dataclass(frozen=True)
class AnalysisConfig:
    path: Path
    sha256: str
    schema_path: Path
    schema_sha256: str
    repo_root: Path
    raw: dict[str, Any]
    statistics: dict[str, Any]


@dataclass(frozen=True)
class BoundInitialInput:
    manifest_path: Path
    manifest_sha256: str
    manifest: dict[str, Any]
    rows_path: Path
    rows_sha256: str
    rows: tuple[dict[str, Any], ...]
    units: tuple[dict[str, Any], ...]
    actions: tuple[dict[str, Any], ...]
    folds: dict[str, int]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EligibilityContractError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EligibilityContractError(f"{label} must be a list")
    return value


def _finite(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EligibilityContractError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0.0):
        raise EligibilityContractError(f"{label} must be finite and valid")
    return result


def _numeric_or_bool(value: Any, label: str) -> float:
    if isinstance(value, bool):
        return float(value)
    return _finite(value, label)


def _hash_row(row: Mapping[str, Any], field: str, label: str) -> str:
    claimed = require_sha256(row.get(field), f"{label}.{field}")
    unhashed = dict(row)
    unhashed.pop(field, None)
    observed = hashlib.sha256(canonical_json(unhashed).encode("utf-8")).hexdigest()
    if claimed != observed:
        raise EligibilityContractError(f"{label}.{field} identity mismatch")
    return claimed


def _repo_file(repo_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise EligibilityContractError(f"{label} must be a repository-relative path")
    candidate = (repo_root / value).resolve(strict=True)
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise EligibilityContractError(f"{label} escapes the repository") from exc
    if not candidate.is_file():
        raise EligibilityContractError(f"{label} is not a file")
    return candidate


def _bound_absolute_file(value: Any, label: str, *, expected_sha256: Any) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise EligibilityContractError(f"{label}.path must be absolute")
    path = Path(value).resolve(strict=True)
    if value != str(path) or not path.is_file():
        raise EligibilityContractError(f"{label}.path is absent or noncanonical")
    expected = require_sha256(expected_sha256, f"{label}.sha256")
    if sha256_file(path) != expected:
        raise EligibilityContractError(f"{label} SHA-256 binding drifted")
    return path


def _validate_binding(value: Any, label: str, *, rows: bool) -> tuple[Path, int | None]:
    expected_keys = ROW_BINDING_KEYS if rows else BINDING_KEYS
    record = require_exact_keys(value, expected_keys, label)
    path = _bound_absolute_file(record["path"], label, expected_sha256=record["sha256"])
    count: int | None = None
    if rows:
        count = record["row_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise EligibilityContractError(f"{label}.row_count must be nonnegative")
    return path, count


def load_analysis_config(path: Path, *, repo_root: Path) -> AnalysisConfig:
    """Load the closed prospective config and verify every frozen source byte."""

    root = repo_root.resolve(strict=True)
    source = path.resolve(strict=True)
    raw = load_json(source)
    if (
        raw.get("schema_version") != 1
        or raw.get("status") != "PROSPECTIVE_CLOSED_PENDING_SEPARATE_DECISION_AND_PUSH"
    ):
        raise EligibilityContractError("eligibility analysis config identity/status drifted")
    frozen = _sequence(raw.get("frozen_sources"), "frozen_sources")
    seen: set[str] = set()
    for index, record_value in enumerate(frozen):
        record = require_exact_keys(record_value, {"path", "sha256"}, f"frozen_sources[{index}]")
        relative = record["path"]
        if relative in seen:
            raise EligibilityContractError("frozen source path is duplicated")
        seen.add(relative)
        source_path = _repo_file(root, relative, f"frozen_sources[{index}].path")
        if sha256_file(source_path) != require_sha256(
            record["sha256"], f"frozen_sources[{index}].sha256"
        ):
            raise EligibilityContractError(f"frozen source changed: {relative}")

    statistics = load_json(root / "configs" / "statistics_v2.json")
    eligibility = _mapping(statistics.get("eligibility"), "statistics.eligibility")
    if (
        eligibility.get("unit") != ["prompt", "root", "checkpoint"]
        or eligibility.get("actions") != list(ACTIONS)
        or eligibility.get("checkpoint_fractions") != list(CHECKPOINTS)
        or eligibility.get("fold_count") != FOLD_COUNT
        or eligibility.get("gate_order")
        != ["ELIGIBLE", "REPLICATION_ONLY", "INCONCLUSIVE_UNDERPOWERED", "STOP_AXIS"]
        or eligibility.get("prompt_bootstrap_replicates") != 10000
        or eligibility.get("prompt_bootstrap_seed") != 2026072002
        or eligibility.get("cross_fitted_deviation_share_minimum") != 0.10
        or eligibility.get("inconclusive_point_estimate_minimum") != 0.05
    ):
        raise EligibilityContractError("statistics_v2 eligibility settings drifted")
    model = _mapping(eligibility.get("model"), "statistics.eligibility.model")
    if model != {
        "coefficient_prior": "Normal(0,1)",
        "intercept_prior": "Normal(0,2.5)",
        "likelihood": "Bernoulli-logit",
        "optimizer": "L-BFGS-B",
        "optimizer_gradient_tolerance": 1e-08,
        "optimizer_max_iterations": 2000,
        "prompt_intercept_prior": "Normal(0,sigma_prompt)",
        "sigma_prompt_prior": "HalfNormal(1)",
        "unseen_prompt_intercept": 0.0,
    }:
        raise EligibilityContractError("statistics_v2 hierarchical MAP model drifted")
    gate = _mapping(raw.get("gate"), "gate")
    if (
        gate.get("order") != eligibility["gate_order"]
        or gate.get("cross_fitted_deviation_share_minimum") != 0.10
        or gate.get("inconclusive_point_estimate_minimum") != 0.05
        or gate.get("supplemental", {}).get("only_trigger") != "INCONCLUSIVE_UNDERPOWERED"
        or gate.get("supplemental", {}).get("maximum_doublings") != 1
    ):
        raise EligibilityContractError("analysis gate differs from statistics_v2")
    bootstrap = _mapping(raw.get("bootstrap"), "bootstrap")
    if (
        bootstrap.get("replicates") != 10000
        or bootstrap.get("seed") != 2026072002
        or bootstrap.get("cluster_unit") != "prompt_id"
        or bootstrap.get("stratum_field") != "prompt_stratum"
        or bootstrap.get("pairing") != "ONE_SHARED_RESAMPLE_FOR_BOTH_TIERS_AND_ALL_PAIRED_CONTRASTS"
        or bootstrap.get("one_sided_lower_quantile") != 0.05
        or bootstrap.get("two_sided_quantiles") != [0.025, 0.975]
        or bootstrap.get("quantile_method") != "linear"
        or bootstrap.get("refit_each_replicate") is not False
    ):
        raise EligibilityContractError("paired prompt bootstrap contract drifted")
    analysis_model = _mapping(raw.get("model"), "model")
    optimizer = _mapping(analysis_model.get("optimizer"), "model.optimizer")
    if (
        optimizer.get("method") != "L-BFGS-B"
        or optimizer.get("max_iterations") != 2000
        or optimizer.get("gtol") != 1e-08
        or optimizer.get("ftol") != 2.220446049250313e-09
        or optimizer.get("max_line_search_steps") != 20
        or optimizer.get("require_success") is not True
    ):
        raise EligibilityContractError("optimizer settings drifted")
    if (
        analysis_model.get("likelihood") != "Bernoulli-logit"
        or analysis_model.get("intercept_prior")
        != {"distribution": "Normal", "mean": 0.0, "sd": 2.5}
        or analysis_model.get("coefficient_prior")
        != {"distribution": "Normal", "mean": 0.0, "sd": 1.0}
        or analysis_model.get("prompt_intercept_prior") != "Normal(0,sigma_prompt)"
        or analysis_model.get("sigma_prompt_prior") != {"distribution": "HalfNormal", "scale": 1.0}
        or analysis_model.get("prompt_effect_parameterization")
        != "NONCENTERED_a_prompt_EQUALS_sigma_prompt_TIMES_z_prompt"
        or analysis_model.get("tiers")
        != ["PROMPT_PLUS_TIME_BUDGET", "PROMPT_PLUS_TIME_BUDGET_PLUS_STATE"]
        or analysis_model.get("sigma_prompt_lower_bound") != 1e-08
        or analysis_model.get("unseen_prompt_intercept") != 0.0
    ):
        raise EligibilityContractError("hierarchical MAP tier/prior settings drifted")
    policy = _mapping(raw.get("policy"), "policy")
    if (
        policy.get("action_tie_order") != eligibility.get("action_tie_order")
        or policy.get("incremental_cost_field") != "incremental_cost_nfe"
        or policy.get("prediction_tie_tolerance") != 0.0
        or policy.get("value_outcome") != "FROZEN_MAPPED_AUTOMATIC_INSTRUMENT_SUCCESS"
        or policy.get("weighting") != "EQUAL_OVER_PROMPTS_ROOTS_CHECKPOINTS"
    ):
        raise EligibilityContractError("action tie/cost policy drifted")
    sa3_feature_contract = _mapping(
        load_json(root / "configs" / "sa3_state_capture_v2.json").get("feature_contract"),
        "sa3 state feature contract",
    )
    state_fields = raw["input_contract"]["state_feature_fields"]
    if (
        state_fields["frozen_decoder_metadata"]
        != sa3_feature_contract.get("decoder_metadata_fields")
        or state_fields["within_preview_summaries"]
        != sa3_feature_contract.get("within_preview_summary_fields")
        or list(raw["feature_encoding"]["state_feature_groups"])
        != [
            "axis_evaluator_values",
            "integrity_values",
            "within_preview_summaries",
            "frozen_decoder_metadata",
        ]
    ):
        raise EligibilityContractError("root-local state feature fields drifted from the queue")
    opening = _mapping(raw.get("opening_contract"), "opening_contract")
    if (
        opening.get("status") != "CLOSED_PENDING_SEPARATE_APPEND_ONLY_DECISION_AND_PUSH"
        or opening.get("outcome_input_must_not_be_opened_before_validation") is not True
        or opening.get("remote_ref") != "refs/remotes/origin/main"
    ):
        raise EligibilityContractError("prospective opening contract drifted")
    schema_path = root / "configs" / "eligibility_scored_state_actions_v2.schema.json"
    if not schema_path.is_file():
        raise EligibilityContractError("scored state-action schema is absent")
    return AnalysisConfig(
        path=source,
        sha256=sha256_file(source),
        schema_path=schema_path,
        schema_sha256=sha256_file(schema_path),
        repo_root=root,
        raw=raw,
        statistics=statistics,
    )


def _decision_block(text: str, decision_id: str) -> str:
    matches = list(_DECISION_HEADER.finditer(text))
    matching = [index for index, match in enumerate(matches) if match.group("id") == decision_id]
    if len(matching) != 1:
        raise EligibilityContractError("prospective decision ID must occur exactly once")
    index = matching[0]
    start = matches[index].start()
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    return text[start:end].rstrip() + "\n"


def _assignments(block: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in block.splitlines()[1:]:
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*) = (\S+)", line.strip())
        if match is None:
            continue
        key, value = match.groups()
        if key in result:
            raise EligibilityContractError(f"duplicate decision assignment: {key}")
        result[key] = value
    return result


def _git(repo_root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise EligibilityContractError(f"git prospective-push proof failed: {detail}") from exc
    return result.stdout


def validate_prospective_opening(
    config: AnalysisConfig,
    *,
    decisions_path: Path,
    decision_id: str,
) -> dict[str, str]:
    """Prove the decision and config are frozen on ``origin/main``.

    This function deliberately accepts no input-manifest or outcome-row path.
    Consequently, a caller can and must complete it before even opening those
    files.
    """

    decisions = decisions_path.resolve(strict=True)
    if decisions != (config.repo_root / "DECISIONS.md").resolve(strict=True):
        raise EligibilityContractError("opening must use the repository DECISIONS.md")
    local_block = _decision_block(decisions.read_text(encoding="utf-8"), decision_id)
    observed = _assignments(local_block)
    opening = config.raw["opening_contract"]
    names = opening["required_assignment_names"]
    if set(observed) != set(names):
        raise EligibilityContractError("prospective decision assignment set drifted")
    for name, expected in opening["required_assignment_values"].items():
        if observed.get(name) != expected:
            raise EligibilityContractError(f"prospective decision assignment drifted: {name}")
    if observed.get("ELIGIBILITY_ANALYSIS_CONFIG_SHA256") != config.sha256:
        raise EligibilityContractError("decision does not bind the analysis config bytes")
    if observed.get("ELIGIBILITY_ACTION_ROW_SCHEMA_SHA256") != config.schema_sha256:
        raise EligibilityContractError("decision does not bind the scored-row schema bytes")

    remote_ref = str(opening["remote_ref"])
    config_relative = config.path.relative_to(config.repo_root).as_posix()
    schema_relative = config.schema_path.relative_to(config.repo_root).as_posix()
    decisions_relative = decisions.relative_to(config.repo_root).as_posix()
    remote_config = _git(config.repo_root, "show", f"{remote_ref}:{config_relative}")
    remote_schema = _git(config.repo_root, "show", f"{remote_ref}:{schema_relative}")
    remote_decisions = _git(config.repo_root, "show", f"{remote_ref}:{decisions_relative}")
    if hashlib.sha256(remote_config).hexdigest() != config.sha256:
        raise EligibilityContractError("analysis config is not the bound bytes on origin/main")
    if hashlib.sha256(remote_schema).hexdigest() != config.schema_sha256:
        raise EligibilityContractError("row schema is not the bound bytes on origin/main")
    remote_block = _decision_block(remote_decisions.decode("utf-8"), decision_id)
    if remote_block != local_block:
        raise EligibilityContractError("prospective decision block is not on origin/main")
    return {
        "config_sha256": config.sha256,
        "decision_block_sha256": hashlib.sha256(local_block.encode("utf-8")).hexdigest(),
        "decision_id": decision_id,
        "remote_ref": remote_ref,
        "schema_sha256": config.schema_sha256,
        "status": "PROSPECTIVE_OPENING_VERIFIED_BEFORE_OUTCOME_READ",
    }


def deterministic_fold(prompt_id: str, namespace: str) -> int:
    """Return the prompt rank later; callers assign cyclic IDs after sorting."""

    if not isinstance(prompt_id, str) or not prompt_id:
        raise EligibilityContractError("prompt_id must be nonempty")
    digest = hashlib.sha256(f"{namespace}|{prompt_id}".encode()).hexdigest()
    return int(digest, 16)


def expected_folds(prompt_ids: Sequence[str], *, namespace: str) -> dict[str, int]:
    if len(prompt_ids) != PROMPT_COUNT or len(set(prompt_ids)) != PROMPT_COUNT:
        raise EligibilityContractError("a cell must contain exactly 12 unique prompts")
    ordered = sorted(prompt_ids, key=lambda value: (deterministic_fold(value, namespace), value))
    return {prompt: index % FOLD_COUNT for index, prompt in enumerate(ordered)}


def _prompt_registry(config: AnalysisConfig, axis: str) -> dict[str, dict[str, Any]]:
    prompt_path = config.repo_root / _PROMPT_FILES[axis]
    values = _sequence(load_json(prompt_path).get("rows"), f"{axis} prompt rows")
    selected = config.statistics["eligibility"]["prompt_selection"]["axis_prompt_ids"][axis]
    by_id = {str(row.get("prompt_id")): row for row in values}
    if len(by_id) != len(values) or any(prompt not in by_id for prompt in selected):
        raise EligibilityContractError("frozen prompt registry is incomplete or duplicated")
    return {prompt: by_id[prompt] for prompt in selected}


def _expected_prompt_factors(axis: str, prompt: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    factors = {key: None for key in PROMPT_FACTOR_KEYS}
    if axis == "vocal_instrumental":
        factors["request"] = prompt["request"]
        stratum = str(prompt["request"])
    elif axis == "tempo":
        factors["target_bpm"] = float(prompt["target_bpm"])
        factors["salience"] = prompt["salience"]
        stratum = str(prompt["salience"])
    else:
        factors["profile"] = prompt["profile"]
        factors["style_family"] = prompt["style_family"]
        stratum = str(prompt["profile"])
    return factors, stratum


def _validate_state_features(
    value: Any, *, axis: str, config: AnalysisConfig, label: str
) -> dict[str, dict[str, Any]]:
    state = require_exact_keys(value, STATE_GROUPS, label)
    contract = config.raw["input_contract"]["state_feature_fields"]
    expected_by_group: dict[str, list[str]] = {
        "axis_evaluator_values": contract["axis_evaluator_values"][axis],
        "integrity_values": contract["integrity_values"],
        "within_preview_summaries": contract["within_preview_summaries"],
        "frozen_decoder_metadata": contract["frozen_decoder_metadata"],
    }
    result: dict[str, dict[str, Any]] = {}
    for group, expected_names in expected_by_group.items():
        values = require_exact_keys(state[group], set(expected_names), f"{label}.{group}")
        normalized: dict[str, Any] = {}
        for name in expected_names:
            item = values[name]
            if group == "frozen_decoder_metadata" and name in {
                "checkpoint_sha256",
                "preview_sha256",
                "schedule_sha256",
            }:
                normalized[name] = require_sha256(item, f"{label}.{group}.{name}")
            elif group == "frozen_decoder_metadata" and name == "latent_dtype":
                if not isinstance(item, str) or not item:
                    raise EligibilityContractError(f"{label}.{group}.{name} is invalid")
                normalized[name] = item
            elif group == "frozen_decoder_metadata" and name == "latent_shape":
                if (
                    not isinstance(item, list)
                    or not item
                    or any(
                        isinstance(dimension, bool)
                        or not isinstance(dimension, int)
                        or dimension <= 0
                        for dimension in item
                    )
                ):
                    raise EligibilityContractError(f"{label}.{group}.{name} is invalid")
                normalized[name] = list(item)
            elif group == "within_preview_summaries" and name == "dc_offset_per_channel":
                if not isinstance(item, list) or not item:
                    raise EligibilityContractError(f"{label}.{group}.{name} is invalid")
                normalized[name] = [_finite(value, f"{label}.{group}.{name}") for value in item]
            else:
                normalized[name] = _numeric_or_bool(item, f"{label}.{group}.{name}")
        result[group] = normalized
    return result


def _validate_budget(value: Any, label: str) -> dict[str, float]:
    budget = require_exact_keys(value, BUDGET_KEYS, label)
    normalized = {key: _finite(budget[key], f"{label}.{key}", nonnegative=True) for key in budget}
    if normalized["total_nfe"] <= 0 or normalized["total_seconds"] <= 0:
        raise EligibilityContractError(f"{label} total costs must be positive")
    if not math.isclose(
        normalized["elapsed_nfe"] + normalized["remaining_nfe"],
        normalized["total_nfe"],
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise EligibilityContractError(f"{label} NFE budget does not partition")
    if not math.isclose(
        normalized["elapsed_seconds"] + normalized["remaining_seconds"],
        normalized["total_seconds"],
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise EligibilityContractError(f"{label} time budget does not partition")
    return normalized


def _validate_queue_unit(row: Mapping[str, Any], label: str) -> str:
    identity = _hash_row(row, "lane_request_sha256", label)
    unit = require_exact_keys(
        row.get("eligibility_unit"), {"prompt", "root", "checkpoint"}, f"{label}.unit"
    )
    if (
        row.get("tier") != TIER
        or row.get("axis") not in AXES
        or unit.get("prompt") != row.get("prompt_id")
        or unit.get("root") != row.get("root_index")
        or unit.get("checkpoint") != row.get("checkpoint_fraction")
        or row.get("root_index") not in INITIAL_ROOTS
        or row.get("checkpoint_fraction") not in CHECKPOINTS
        or row.get("condition") != "BASE"
        or row.get("source_condition", "BASE") != "BASE"
        or row.get("preview_source") != ROOT_LOCAL_SOURCE
        or row.get("preview_source_request_sha256") != row.get("parent_request_sha256")
        or row.get("feature_contract", {}).get("root_local_only") is not True
    ):
        raise EligibilityContractError(f"{label} violates the initial root-local BASE contract")
    forbidden = row.get("feature_contract", {}).get("forbidden_sources")
    required_forbidden = {
        "OTHER_ROOT_PREVIEWS",
        "ACTION_OUTCOMES",
        "TERMINAL_AUDIO_FEATURES",
        "HUMAN_GOLD",
        "HELD_OUT_FITTED_VALUES",
    }
    if not isinstance(forbidden, list) or not required_forbidden <= set(forbidden):
        raise EligibilityContractError(f"{label} lost forbidden feature-source guards")
    return identity


def _validate_action(row: Mapping[str, Any], label: str) -> str:
    identity = _hash_row(row, "action_mapping_sha256", label)
    action = row.get("action")
    if action not in ACTIONS or row.get("tier") != TIER:
        raise EligibilityContractError(f"{label} action/tier drifted")
    common_keys = {
        "action",
        "action_mapping_sha256",
        "action_sequence",
        "axis",
        "checkpoint_fraction",
        "fold_id",
        "incremental_cost",
        "lane_request_sha256",
        "outcome_label",
        "outcome_source",
        "outcome_source_root_index",
        "prompt_id",
        "root_index",
        "tier",
    }
    if action == "KEEP":
        if set(row) != common_keys | {"outcome_relpath"}:
            raise EligibilityContractError(f"{label} KEEP schema drifted")
        if (
            row.get("outcome_label") != "KEEP_TRUE_ROOT_STATE"
            or row.get("outcome_source") != "ROOT_LOCAL_TRUE_STATE_RESUME"
            or row.get("outcome_source_root_index") != row.get("root_index")
            or row.get("incremental_cost") != "MEASURED_REMAINING_NFE_AND_TIME"
        ):
            raise EligibilityContractError(f"{label} KEEP mapping drifted")
    else:
        restart_keys = common_keys | {
            "outcome_source_condition",
            "outcome_source_core_artifact",
            "outcome_source_request_sha256",
            "restart_pool_root_indices",
            "rotation_direction",
            "rotation_offset",
        }
        checkpoint = json.dumps(
            float(row.get("checkpoint_fraction")), allow_nan=False, separators=(",", ":")
        )
        material = f"benchmark-v2-restart-map-20260720|{row.get('prompt_id')}|{checkpoint}|{action}"
        offset = int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 4
        roots = (4, 5, 6, 7)
        rotated = roots[offset:] + roots[:offset]
        root_index = row.get("root_index")
        expected_root = rotated[root_index] if root_index in INITIAL_ROOTS else None
        if (
            set(row) != restart_keys
            or row.get("outcome_label") != RESTART_LABEL
            or row.get("outcome_source") != "FROZEN_PROMPT_LEVEL_CORE_TERMINAL_POOL"
            or row.get("outcome_source_condition")
            != ("BASE" if action == "RESTART_BASE" else "FIXED")
            or row.get("incremental_cost") != "ONE_FULL_NATIVE_GENERATION"
            or row.get("restart_pool_root_indices") != [4, 5, 6, 7]
            or row.get("rotation_direction") != "LEFT"
            or row.get("rotation_offset") != offset
            or row.get("outcome_source_root_index") != expected_root
        ):
            raise EligibilityContractError(f"{label} restart prompt-pool mapping drifted")
    return identity


def _row_identity(row: Mapping[str, Any]) -> tuple[str, int, float, str]:
    return (
        str(row["prompt_id"]),
        int(row["root_index"]),
        float(row["checkpoint_fraction"]),
        str(row["action"]),
    )


def _validate_scored_rows(
    rows: Sequence[dict[str, Any]],
    *,
    config: AnalysisConfig,
    backbone: str,
    model_id: str,
    axis: str,
    units: Mapping[str, dict[str, Any]],
    actions: Mapping[tuple[str, str], dict[str, Any]],
    folds: Mapping[str, int],
    survivor_ids: frozenset[str],
    cancelled_ids: frozenset[str],
) -> tuple[dict[str, Any], ...]:
    if len(rows) != EXPECTED_INITIAL_ROWS:
        raise EligibilityContractError(
            f"initial scored row count is {len(rows)}, expected {EXPECTED_INITIAL_ROWS}"
        )
    prompts = _prompt_registry(config, axis)
    observed: set[tuple[str, int, float, str]] = set()
    per_unit: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        label = f"scored row {index}"
        try:
            row = require_exact_keys(raw, ROW_KEYS, label)
        except ValueError as exc:
            raise EligibilityContractError(str(exc)) from exc
        if (
            row["schema_version"] != 1
            or row["watermark"] != WATERMARK
            or row["backbone"] != backbone
            or row["model_id"] != model_id
            or row["axis"] != axis
            or row["tier"] != TIER
            or row["action"] not in ACTIONS
            or row["checkpoint_fraction"] not in CHECKPOINTS
            or row["root_index"] not in INITIAL_ROOTS
            or row["human_gold_used"] is not False
            or row["terminal_features_used"] is not False
            or row["other_root_preview_used"] is not False
            or row["held_out_fitted_value_used"] is not False
        ):
            raise EligibilityContractError(f"{label} identity/leakage guard drifted")
        for key in (
            "lane_request_sha256",
            "action_mapping_sha256",
            "outcome_binding_sha256",
            "outcome_audio_sha256",
            "preview_audio_sha256",
            "preview_source_request_sha256",
        ):
            require_sha256(row[key], f"{label}.{key}")
        lane_id = row["lane_request_sha256"]
        if lane_id in cancelled_ids or lane_id not in survivor_ids or lane_id not in units:
            raise EligibilityContractError(f"{label} is STOP/cancelled/unregistered")
        unit = units[lane_id]
        if (
            row["prompt_id"] != unit["prompt_id"]
            or row["root_index"] != unit["root_index"]
            or row["checkpoint_fraction"] != unit["checkpoint_fraction"]
            or row["fold_id"] != unit["fold_id"]
            or row["fold_id"] != folds[row["prompt_id"]]
            or row["preview_source_request_sha256"] != unit["preview_source_request_sha256"]
        ):
            raise EligibilityContractError(f"{label} differs from its queue unit/fold")
        action = actions.get((lane_id, row["action"]))
        if action is None or row["action_mapping_sha256"] != action["action_mapping_sha256"]:
            raise EligibilityContractError(f"{label} differs from its frozen action mapping")
        if (
            action["prompt_id"] != row["prompt_id"]
            or action["root_index"] != row["root_index"]
            or action["checkpoint_fraction"] != row["checkpoint_fraction"]
            or action["fold_id"] != row["fold_id"]
            or action["axis"] != row["axis"]
        ):
            raise EligibilityContractError(f"{label} action identity differs from its unit")
        for key in (
            "outcome_source",
            "outcome_label",
            "outcome_source_root_index",
        ):
            if row[key] != action[key]:
                raise EligibilityContractError(f"{label}.{key} differs from its action mapping")
        expected_binding = (
            lane_id if row["action"] == "KEEP" else action["outcome_source_request_sha256"]
        )
        if row["outcome_binding_sha256"] != expected_binding:
            raise EligibilityContractError(f"{label} outcome is not the frozen mapped outcome")
        if row["automatic_result_wording"] != _EXPECTED_WORDING[axis]:
            raise EligibilityContractError(f"{label} automatic-only wording drifted")
        if not isinstance(row["outcome_valid"], bool) or not isinstance(
            row["outcome_success"], bool
        ):
            raise EligibilityContractError(f"{label} outcome flags must be Boolean")
        if row["outcome_valid"] is False and row["outcome_success"] is not False:
            raise EligibilityContractError(f"{label} invalid files must be failures")
        factors = require_exact_keys(row["prompt_factors"], PROMPT_FACTOR_KEYS, f"{label}.factors")
        expected_factors, expected_stratum = _expected_prompt_factors(
            axis, prompts[row["prompt_id"]]
        )
        if factors != expected_factors or row["prompt_stratum"] != expected_stratum:
            raise EligibilityContractError(f"{label} prompt matrix/stratum drifted")
        state = _validate_state_features(
            row["state_features"], axis=axis, config=config, label=label
        )
        budget = _validate_budget(row["budget_features"], f"{label}.budget")
        decoder = state["frozen_decoder_metadata"]
        completed_budget = unit.get(
            "checkpoint_completed_steps", unit.get("checkpoint_cumulative_transformer_nfe")
        )
        total_budget = unit.get("transformer_budget_nfe", unit.get("total_transformer_nfe"))
        if (
            not math.isclose(
                float(decoder["checkpoint_fraction"]),
                float(row["checkpoint_fraction"]),
                abs_tol=1e-12,
            )
            or not math.isclose(
                float(decoder["checkpoint_completed_steps"]),
                budget["elapsed_nfe"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or not math.isclose(
                float(decoder["transformer_budget_nfe"]),
                budget["total_nfe"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or completed_budget is None
            or total_budget is None
            or not math.isclose(
                float(decoder["checkpoint_completed_steps"]),
                float(completed_budget),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or not math.isclose(
                float(decoder["transformer_budget_nfe"]),
                float(total_budget),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or decoder["preview_sha256"] != row["preview_audio_sha256"]
        ):
            raise EligibilityContractError(f"{label} decoder budget/checkpoint metadata drifted")
        if row["action"] == "KEEP":
            expected_nfe = budget["remaining_nfe"]
            expected_seconds = budget["remaining_seconds"]
        else:
            expected_nfe = budget["total_nfe"]
            expected_seconds = budget["total_seconds"]
        if not math.isclose(budget["incremental_cost_nfe"], expected_nfe, abs_tol=1e-9):
            raise EligibilityContractError(f"{label} incremental NFE cost drifted")
        if not math.isclose(
            budget["incremental_cost_seconds"], expected_seconds, rel_tol=1e-9, abs_tol=1e-9
        ):
            raise EligibilityContractError(f"{label} incremental time cost drifted")
        item = dict(row)
        item["state_features"] = state
        item["budget_features"] = budget
        identity = _row_identity(item)
        if identity in observed:
            raise EligibilityContractError(f"{label} duplicates a state-action identity")
        observed.add(identity)
        per_unit[lane_id].append(item)
        normalized.append(item)

    expected_identities = {
        (
            str(unit["prompt_id"]),
            int(unit["root_index"]),
            float(unit["checkpoint_fraction"]),
            action,
        )
        for unit in units.values()
        for action in ACTIONS
    }
    if observed != expected_identities:
        raise EligibilityContractError(
            "scored rows do not cover every survivor unit/action exactly"
        )
    for lane_id, group in per_unit.items():
        if {row["action"] for row in group} != set(ACTIONS):
            raise EligibilityContractError("a state unit does not contain all replicated actions")
        root_local = {
            canonical_json(
                {
                    "preview_audio_sha256": row["preview_audio_sha256"],
                    "preview_source_request_sha256": row["preview_source_request_sha256"],
                    "state_features": row["state_features"],
                }
            )
            for row in group
        }
        if len(root_local) != 1:
            raise EligibilityContractError(
                f"unit {lane_id} changes root-local preview features across actions"
            )
    return tuple(sorted(normalized, key=_row_identity))


def load_bound_initial_input(
    manifest_path: Path,
    *,
    config: AnalysisConfig,
) -> BoundInitialInput:
    """Open and validate a complete initial survivor cell after the push gate."""

    source = manifest_path.resolve(strict=True)
    manifest = require_exact_keys(load_json(source), MANIFEST_KEYS, "input manifest")
    if (
        manifest["schema_version"] != 1
        or manifest["status"] != "ELIGIBILITY_INITIAL_INPUT_COMPLETE"
        or manifest["watermark"] != WATERMARK
        or manifest["human_gold_labels_used"] is not False
        or manifest["tier"] != TIER
        or manifest["analysis_config_path"] != str(config.path)
        or manifest["analysis_config_sha256"] != config.sha256
    ):
        raise EligibilityContractError("input manifest identity or automatic-only status drifted")
    backbone = manifest["backbone"]
    model_id = manifest["model_id"]
    axis = manifest["axis"]
    if backbone not in _BACKBONE_MODEL or model_id != _BACKBONE_MODEL[backbone] or axis not in AXES:
        raise EligibilityContractError("input cell identity is invalid")

    row_paths: dict[str, tuple[Path, int | None]] = {}
    for name in (
        "scored_rows",
        "queue_units",
        "queue_action_map",
        "survivor_units",
        "cancellation_units",
    ):
        row_paths[name] = _validate_binding(manifest[name], name, rows=True)
    assembly_sources = require_exact_keys(
        manifest["assembly_sources"],
        {"automatic_outcomes", "measured_costs", "preview_features"},
        "assembly_sources",
    )
    for name in ("automatic_outcomes", "measured_costs", "preview_features"):
        _validate_binding(assembly_sources[name], f"assembly_sources.{name}", rows=True)
    file_paths: dict[str, Path] = {}
    for name in ("queue_manifest", "folds", "survivor_manifest", "cancellation_manifest"):
        file_paths[name] = _validate_binding(manifest[name], name, rows=False)[0]

    instrument = require_exact_keys(manifest["instrument_scoring"], INSTRUMENT_KEYS, "instrument")
    scoring_config_path = _repo_file(
        config.repo_root,
        instrument["automatic_scoring_config_path"],
        "instrument.automatic_scoring_config_path",
    )
    if (
        instrument["assembly_status"] != "FROZEN_INSTRUMENT_ASSEMBLY_COMPLETE"
        or instrument["human_gold_labels_used"] is not False
        or instrument["automatic_scoring_config_path"] != "configs/automatic_scoring_v2.json"
        or instrument["automatic_scoring_config_sha256"] != sha256_file(scoring_config_path)
    ):
        raise EligibilityContractError("instrument-scoring receipt is incomplete or drifted")
    require_sha256(instrument["evaluator_identities_sha256"], "evaluator identities hash")
    code_hashes = require_exact_keys(
        instrument["frozen_instrument_code_sha256s"],
        {"integrity", "tempo", "voice"},
        "instrument code hashes",
    )
    expected_code = {
        "voice": sha256_file(config.repo_root / "src/instruments/voice.py"),
        "tempo": sha256_file(config.repo_root / "src/instruments/tempo.py"),
        "integrity": sha256_file(config.repo_root / "src/instruments/integrity.py"),
    }
    if code_hashes != expected_code:
        raise EligibilityContractError("input was not assembled with the frozen instruments")

    queue_manifest = load_json(file_paths["queue_manifest"])
    for manifest_key, input_key in (
        ("units", "queue_units"),
        ("action_map", "queue_action_map"),
        ("folds", "folds"),
    ):
        record = _mapping(queue_manifest.get(manifest_key), f"queue manifest.{manifest_key}")
        bound = manifest[input_key]
        if record.get("path") != bound["path"] or record.get("sha256") != bound["sha256"]:
            raise EligibilityContractError(f"queue manifest does not bind {manifest_key}")
    if queue_manifest.get("tier") != TIER:
        raise EligibilityContractError("queue manifest is supplemental or has unknown tier")

    survivor_manifest = load_json(file_paths["survivor_manifest"])
    survivor_units_path, survivor_count = row_paths["survivor_units"]
    if (
        survivor_manifest.get("status") != "STAGE1_SURVIVOR_MANIFEST_COMPLETE"
        or survivor_manifest.get("watermark") != WATERMARK
        or survivor_manifest.get("human_gold_claims") is not False
        or survivor_manifest.get("automatic_instrument_outcomes") is not True
        or survivor_manifest.get("backbone") != backbone
        or axis not in survivor_manifest.get("pass_axes", [])
        or axis in survivor_manifest.get("stop_axes", [])
        or survivor_manifest.get("units_path") != str(survivor_units_path)
        or survivor_manifest.get("units_sha256") != sha256_file(survivor_units_path)
        or survivor_manifest.get("unit_count") != survivor_count
    ):
        raise EligibilityContractError("Stage-1 survivor binding does not authorize this cell")

    cancellation_manifest = load_json(file_paths["cancellation_manifest"])
    cancellation_units_path, cancellation_count = row_paths["cancellation_units"]
    if (
        cancellation_manifest.get("status") != "STAGE1_CANCELLATION_MANIFEST_COMPLETE"
        or cancellation_manifest.get("watermark") != WATERMARK
        or cancellation_manifest.get("human_gold_claims") is not False
        or cancellation_manifest.get("prohibited_operations") != ["EXECUTE", "SCORE"]
        or cancellation_manifest.get("units_path") != str(cancellation_units_path)
        or cancellation_manifest.get("units_sha256") != sha256_file(cancellation_units_path)
        or cancellation_manifest.get("event_count") != cancellation_count
    ):
        raise EligibilityContractError("Stage-1 cancellation binding drifted")

    queue_units_path, queue_unit_count = row_paths["queue_units"]
    action_path, action_count = row_paths["queue_action_map"]
    scored_path, scored_count = row_paths["scored_rows"]
    all_units = load_jsonl(queue_units_path)
    all_actions = load_jsonl(action_path)
    survivor_rows = load_jsonl(survivor_units_path)
    cancellation_rows = load_jsonl(cancellation_units_path)
    scored_rows = load_jsonl(scored_path)
    for expected_count, observed_rows, label in (
        (queue_unit_count, all_units, "queue units"),
        (action_count, all_actions, "queue actions"),
        (survivor_count, survivor_rows, "survivor units"),
        (cancellation_count, cancellation_rows, "cancellation units"),
        (scored_count, scored_rows, "scored rows"),
    ):
        if expected_count != len(observed_rows):
            raise EligibilityContractError(f"{label} row count drifted")

    queue_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(all_units):
        identity = _validate_queue_unit(row, f"queue unit {index}")
        if identity in queue_by_id:
            raise EligibilityContractError("queue unit identity is duplicated")
        queue_by_id[identity] = row
    survivor_ids = frozenset(
        require_sha256(row.get("lane_request_sha256"), "survivor lane_request_sha256")
        for row in survivor_rows
        if row.get("axis") == axis
    )
    if len(survivor_ids) != EXPECTED_INITIAL_UNITS:
        raise EligibilityContractError("survivor cell does not contain exactly 144 initial units")
    if any(
        queue_by_id.get(identity) != row
        for row in survivor_rows
        for identity in [row.get("lane_request_sha256")]
        if row.get("axis") == axis
    ):
        raise EligibilityContractError("survivor unit bytes differ from the registered queue")
    cancelled_ids: set[str] = set()
    for index, row in enumerate(cancellation_rows):
        identity = require_sha256(row.get("lane_request_sha256"), f"cancellation {index} identity")
        if (
            row.get("status") != "CANCELLED_STAGE1"
            or row.get("cancellation_reason") != "STOP_AXIS_STAGE1"
            or row.get("prohibited_operations") != ["EXECUTE", "SCORE"]
        ):
            raise EligibilityContractError("cancellation row lost its deny semantics")
        if row.get("backbone") == backbone and row.get("axis") == axis:
            raise EligibilityContractError("a purported survivor cell is also STOP_AXIS_STAGE1")
        cancelled_ids.add(identity)
    if survivor_ids & cancelled_ids:
        raise EligibilityContractError("survivor and cancellation sets overlap")
    target_units = {identity: queue_by_id[identity] for identity in survivor_ids}
    if any(row["axis"] != axis for row in target_units.values()):
        raise EligibilityContractError("survivor unit set crosses axes")

    action_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, action in enumerate(all_actions):
        identity = _validate_action(action, f"queue action {index}")
        lane_id = require_sha256(action.get("lane_request_sha256"), "action lane ID")
        if lane_id not in target_units:
            continue
        key = (lane_id, str(action["action"]))
        if key in action_by_key:
            raise EligibilityContractError("target action mapping is duplicated")
        if identity != action["action_mapping_sha256"]:
            raise EligibilityContractError("action mapping hash drifted")
        action_by_key[key] = action
    if len(action_by_key) != EXPECTED_INITIAL_ROWS:
        raise EligibilityContractError("survivor action map is incomplete")

    folds_raw = load_json(file_paths["folds"])
    fold_rows = _sequence(folds_raw.get("rows"), "fold rows")
    target_fold_rows = [row for row in fold_rows if row.get("axis") == axis]
    prompt_ids = config.statistics["eligibility"]["prompt_selection"]["axis_prompt_ids"][axis]
    expected = expected_folds(prompt_ids, namespace=config.raw["folds"]["namespace"])
    observed_folds: dict[str, int] = {}
    for row in target_fold_rows:
        prompt = row.get("prompt_id")
        fold = row.get("fold_id")
        if prompt in observed_folds or prompt not in expected or fold != expected[prompt]:
            raise EligibilityContractError("prompt-grouped fold assignment drifted")
        observed_folds[str(prompt)] = int(fold)
    if observed_folds != expected or Counter(observed_folds.values()) != Counter(
        {i: 2 for i in range(6)}
    ):
        raise EligibilityContractError("cell folds must contain two whole prompts each")
    if any(
        unit.get("fold_id") != observed_folds[unit["prompt_id"]] for unit in target_units.values()
    ):
        raise EligibilityContractError("a queue unit crosses its prompt fold")

    normalized = _validate_scored_rows(
        scored_rows,
        config=config,
        backbone=backbone,
        model_id=model_id,
        axis=axis,
        units=target_units,
        actions=action_by_key,
        folds=observed_folds,
        survivor_ids=survivor_ids,
        cancelled_ids=frozenset(cancelled_ids),
    )
    return BoundInitialInput(
        manifest_path=source,
        manifest_sha256=sha256_file(source),
        manifest=manifest,
        rows_path=scored_path,
        rows_sha256=sha256_file(scored_path),
        rows=normalized,
        units=tuple(target_units[key] for key in sorted(target_units)),
        actions=tuple(action_by_key[key] for key in sorted(action_by_key)),
        folds=observed_folds,
    )


def supplemental_trigger(gate_label: str) -> dict[str, Any]:
    """Return the sole legal supplemental transition without opening a queue here."""

    if gate_label not in {
        "ELIGIBLE",
        "REPLICATION_ONLY",
        "INCONCLUSIVE_UNDERPOWERED",
        "STOP_AXIS",
    }:
        raise EligibilityContractError("unknown four-way gate label")
    triggered = gate_label == "INCONCLUSIVE_UNDERPOWERED"
    return {
        "authorized_by_any_other_label": False,
        "maximum_additional_root_blocks": 1 if triggered else 0,
        "only_trigger": "INCONCLUSIVE_UNDERPOWERED",
        "root_indices": [4, 5, 6, 7] if triggered else [],
        "status": ("SINGLE_DOUBLING_TRIGGERED" if triggered else "SUPPLEMENTAL_REMAINS_LOCKED"),
        "triggered": triggered,
    }

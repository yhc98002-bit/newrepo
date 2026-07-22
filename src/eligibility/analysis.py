"""Cross-fitted policy metrics, paired prompt bootstrap, and four-way gate."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from eligibility.contract import AnalysisConfig, BoundInitialInput, supplemental_trigger
from eligibility.model import (
    BASELINE_TIER,
    STATE_TIER,
    OOFResult,
    cross_fitted_probabilities,
    require_frozen_numeric_runtime,
)

_ACTION_RANK = {"KEEP": 0, "RESTART_FIXED": 1, "RESTART_BASE": 2}


class EligibilityAnalysisError(RuntimeError):
    """The frozen analysis could not produce a complete, finite result."""


def apply_four_way_gate(
    *,
    one_sided_lower: float,
    point_estimate: float,
    two_sided_upper: float,
    deviation_share: float,
) -> str:
    """Apply the preregistered four rules in their verbatim order."""

    values = (one_sided_lower, point_estimate, two_sided_upper, deviation_share)
    if any(not math.isfinite(float(value)) for value in values):
        raise EligibilityAnalysisError("four-way gate inputs must be finite")
    if not 0.0 <= deviation_share <= 1.0:
        raise EligibilityAnalysisError("deviation share must lie in [0,1]")
    if one_sided_lower > 0.0 and deviation_share >= 0.10:
        return "ELIGIBLE"
    if one_sided_lower > 0.0 and deviation_share < 0.10:
        return "REPLICATION_ONLY"
    if one_sided_lower <= 0.0 and point_estimate >= 0.05 and two_sided_upper > 0.0:
        return "INCONCLUSIVE_UNDERPOWERED"
    return "STOP_AXIS"


def _selected_indices(
    rows: Sequence[Mapping[str, Any]], probabilities: np.ndarray
) -> dict[str, int]:
    if probabilities.shape != (len(rows),):
        raise EligibilityAnalysisError("policy probability vector shape drifted")
    by_unit: defaultdict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_unit[str(row["lane_request_sha256"])].append(index)
    selected: dict[str, int] = {}
    for identity, indices in by_unit.items():
        if len(indices) != 3 or {rows[index]["action"] for index in indices} != {
            "KEEP",
            "RESTART_BASE",
            "RESTART_FIXED",
        }:
            raise EligibilityAnalysisError("policy unit lacks the three replicated actions")
        selected[identity] = min(
            indices,
            key=lambda index: (
                -float(probabilities[index]),
                float(rows[index]["budget_features"]["incremental_cost_nfe"]),
                _ACTION_RANK[str(rows[index]["action"])],
            ),
        )
    return selected


def _prompt_means(
    values: np.ndarray, prompts: Sequence[str], prompt_order: Sequence[str]
) -> np.ndarray:
    if values.shape != (len(prompts),):
        raise EligibilityAnalysisError("prompt aggregation shape drifted")
    output = []
    prompt_array = np.asarray(prompts, dtype=object)
    for prompt in prompt_order:
        selected = values[prompt_array == prompt]
        if selected.size == 0 or not np.isfinite(selected).all():
            raise EligibilityAnalysisError(f"prompt metric is absent/nonfinite: {prompt}")
        output.append(float(np.mean(selected)))
    return np.asarray(output, dtype=np.float64)


def _bootstrap_indices(
    prompt_order: Sequence[str],
    prompt_strata: Mapping[str, str],
    *,
    replicates: int,
    seed: int,
) -> np.ndarray:
    if len(prompt_order) != 12 or set(prompt_order) != set(prompt_strata):
        raise EligibilityAnalysisError("prompt bootstrap requires the exact 12 prompt clusters")
    index = {prompt: position for position, prompt in enumerate(prompt_order)}
    rng = np.random.default_rng(seed)
    blocks: list[np.ndarray] = []
    for stratum in sorted(set(prompt_strata.values())):
        members = sorted(prompt for prompt in prompt_order if prompt_strata[prompt] == stratum)
        if not members:
            raise EligibilityAnalysisError("empty prompt bootstrap stratum")
        member_indices = np.asarray([index[prompt] for prompt in members], dtype=np.int64)
        draws = rng.integers(0, len(members), size=(replicates, len(members)))
        blocks.append(member_indices[draws])
    samples = np.concatenate(blocks, axis=1)
    if samples.shape != (replicates, len(prompt_order)):
        raise EligibilityAnalysisError("prompt bootstrap sample shape drifted")
    return samples


def _interval(
    point: float,
    prompt_values: np.ndarray,
    samples: np.ndarray,
    *,
    config: AnalysisConfig,
) -> dict[str, Any]:
    distribution = np.mean(prompt_values[samples], axis=1)
    bootstrap = config.raw["bootstrap"]
    lower_q = float(bootstrap["one_sided_lower_quantile"])
    two_q = bootstrap["two_sided_quantiles"]
    values = np.quantile(
        distribution,
        [lower_q, float(two_q[0]), float(two_q[1])],
        method=str(bootstrap["quantile_method"]),
    )
    return {
        "one_sided_95_lower": float(values[0]),
        "point": float(point),
        "two_sided_95": [float(values[1]), float(values[2])],
    }


def _calibration_bins(
    outcomes: np.ndarray, probabilities: np.ndarray, *, bin_count: int
) -> list[dict[str, Any]]:
    bins: list[dict[str, Any]] = []
    ids = np.minimum((probabilities * bin_count).astype(int), bin_count - 1)
    for bin_id in range(bin_count):
        selected = ids == bin_id
        bins.append(
            {
                "bin_id": bin_id,
                "count": int(np.count_nonzero(selected)),
                "lower_boundary": bin_id / bin_count,
                "mean_observed": float(np.mean(outcomes[selected])) if np.any(selected) else None,
                "mean_predicted": (
                    float(np.mean(probabilities[selected])) if np.any(selected) else None
                ),
                "right_closed": bin_id == bin_count - 1,
                "upper_boundary": (bin_id + 1) / bin_count,
            }
        )
    return bins


def _row_metric(
    rows: Sequence[Mapping[str, Any]],
    probabilities: Mapping[str, np.ndarray],
    indices: Sequence[int],
    *,
    prompt_order: Sequence[str],
    samples: np.ndarray,
    config: AnalysisConfig,
) -> dict[str, Any]:
    selected = np.asarray(indices, dtype=np.int64)
    outcomes = np.asarray([float(rows[index]["outcome_success"]) for index in selected])
    prompts = [str(rows[index]["prompt_id"]) for index in selected]
    clip = float(config.raw["metrics"]["probability_clip_for_reporting_loss"])
    output: dict[str, Any] = {}
    losses: dict[str, np.ndarray] = {}
    for tier in (BASELINE_TIER, STATE_TIER):
        predicted = probabilities[tier][selected]
        clipped = np.clip(predicted, clip, 1.0 - clip)
        loss = -(outcomes * np.log(clipped) + (1.0 - outcomes) * np.log(1.0 - clipped))
        brier = np.square(outcomes - predicted)
        bias = outcomes - predicted
        losses[tier] = loss
        output[tier] = {
            "brier": _interval(
                float(np.mean(brier)),
                _prompt_means(brier, prompts, prompt_order),
                samples,
                config=config,
            ),
            "calibration_bias_observed_minus_predicted": _interval(
                float(np.mean(bias)),
                _prompt_means(bias, prompts, prompt_order),
                samples,
                config=config,
            ),
            "calibration_bins": _calibration_bins(
                outcomes,
                predicted,
                bin_count=int(config.raw["metrics"]["calibration"]["bin_count"]),
            ),
            "mean_observed": float(np.mean(outcomes)),
            "mean_predicted": float(np.mean(predicted)),
            "oof_logloss": _interval(
                float(np.mean(loss)),
                _prompt_means(loss, prompts, prompt_order),
                samples,
                config=config,
            ),
        }
    legibility = (losses[BASELINE_TIER] - losses[STATE_TIER]) / math.log(2.0)
    output["legibility_bits"] = _interval(
        float(np.mean(legibility)),
        _prompt_means(legibility, prompts, prompt_order),
        samples,
        config=config,
    )
    return output


def _policy_metric(
    rows: Sequence[Mapping[str, Any]],
    probabilities: Mapping[str, np.ndarray],
    baseline_selected: Mapping[str, int],
    state_selected: Mapping[str, int],
    unit_ids: Sequence[str],
    *,
    prompt_order: Sequence[str],
    samples: np.ndarray,
    config: AnalysisConfig,
) -> dict[str, Any]:
    baseline_indices = [baseline_selected[identity] for identity in unit_ids]
    state_indices = [state_selected[identity] for identity in unit_ids]
    baseline_values = np.asarray(
        [float(rows[index]["outcome_success"]) for index in baseline_indices], dtype=np.float64
    )
    state_values = np.asarray(
        [float(rows[index]["outcome_success"]) for index in state_indices], dtype=np.float64
    )
    prompts = [str(rows[index]["prompt_id"]) for index in baseline_indices]
    baseline_prompt = _prompt_means(baseline_values, prompts, prompt_order)
    state_prompt = _prompt_means(state_values, prompts, prompt_order)
    delta = state_values - baseline_values
    delta_prompt = state_prompt - baseline_prompt
    deviation = np.asarray(
        [
            float(
                rows[baseline_selected[identity]]["action"]
                != rows[state_selected[identity]]["action"]
            )
            for identity in unit_ids
        ],
        dtype=np.float64,
    )
    keep_index = {
        str(row["lane_request_sha256"]): index
        for index, row in enumerate(rows)
        if row["action"] == "KEEP"
    }
    commitment = np.asarray(
        [abs(2.0 * probabilities[STATE_TIER][keep_index[identity]] - 1.0) for identity in unit_ids],
        dtype=np.float64,
    )
    result = {
        "baseline_policy_value": _interval(
            float(np.mean(baseline_values)), baseline_prompt, samples, config=config
        ),
        "cross_fitted_deviation_share": _interval(
            float(np.mean(deviation)),
            _prompt_means(deviation, prompts, prompt_order),
            samples,
            config=config,
        ),
        "outcome_commitment": _interval(
            float(np.mean(commitment)),
            _prompt_means(commitment, prompts, prompt_order),
            samples,
            config=config,
        ),
        "state_incremental_value": _interval(
            float(np.mean(delta)), delta_prompt, samples, config=config
        ),
        "state_policy_value": _interval(
            float(np.mean(state_values)), state_prompt, samples, config=config
        ),
    }
    result["selected_action_counts"] = {
        BASELINE_TIER: {
            action: sum(rows[index]["action"] == action for index in baseline_indices)
            for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED")
        },
        STATE_TIER: {
            action: sum(rows[index]["action"] == action for index in state_indices)
            for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED")
        },
    }
    return result


def analyze_initial_cell(
    bound: BoundInitialInput,
    *,
    config: AnalysisConfig,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Execute the frozen initial four-root analysis for one survivor cell."""

    runtime = require_frozen_numeric_runtime()
    rows = bound.rows
    oof: OOFResult = cross_fitted_probabilities(rows, model_config=config.raw["model"])
    baseline_selected = _selected_indices(rows, oof.probabilities[BASELINE_TIER])
    state_selected = _selected_indices(rows, oof.probabilities[STATE_TIER])
    prompt_order = sorted({str(row["prompt_id"]) for row in rows})
    prompt_strata: dict[str, str] = {}
    for row in rows:
        prompt = str(row["prompt_id"])
        stratum = str(row["prompt_stratum"])
        if prompt in prompt_strata and prompt_strata[prompt] != stratum:
            raise EligibilityAnalysisError("a prompt crosses bootstrap strata")
        prompt_strata[prompt] = stratum
    bootstrap = config.raw["bootstrap"]
    samples = _bootstrap_indices(
        prompt_order,
        prompt_strata,
        replicates=int(bootstrap["replicates"]),
        seed=int(bootstrap["seed"]),
    )
    all_indices = list(range(len(rows)))
    unit_to_checkpoint = {
        str(row["lane_request_sha256"]): float(row["checkpoint_fraction"]) for row in rows
    }
    all_units = sorted(unit_to_checkpoint)
    overall_scoring = _row_metric(
        rows,
        oof.probabilities,
        all_indices,
        prompt_order=prompt_order,
        samples=samples,
        config=config,
    )
    overall_policy = _policy_metric(
        rows,
        oof.probabilities,
        baseline_selected,
        state_selected,
        all_units,
        prompt_order=prompt_order,
        samples=samples,
        config=config,
    )
    curves: list[dict[str, Any]] = []
    for checkpoint in config.raw["metrics"]["report_checkpoints"]:
        row_indices = [
            index for index, row in enumerate(rows) if row["checkpoint_fraction"] == checkpoint
        ]
        unit_ids = sorted(
            identity for identity, value in unit_to_checkpoint.items() if value == checkpoint
        )
        curves.append(
            {
                "checkpoint_fraction": checkpoint,
                "policy": _policy_metric(
                    rows,
                    oof.probabilities,
                    baseline_selected,
                    state_selected,
                    unit_ids,
                    prompt_order=prompt_order,
                    samples=samples,
                    config=config,
                ),
                "predictive": _row_metric(
                    rows,
                    oof.probabilities,
                    row_indices,
                    prompt_order=prompt_order,
                    samples=samples,
                    config=config,
                ),
            }
        )
    incremental = overall_policy["state_incremental_value"]
    deviation = overall_policy["cross_fitted_deviation_share"]
    gate = apply_four_way_gate(
        one_sided_lower=float(incremental["one_sided_95_lower"]),
        point_estimate=float(incremental["point"]),
        two_sided_upper=float(incremental["two_sided_95"][1]),
        deviation_share=float(deviation["point"]),
    )
    supplemental = supplemental_trigger(gate)
    result = {
        "analysis_config_path": str(config.path),
        "analysis_config_sha256": config.sha256,
        "automatic_instrument_outcomes": True,
        "axis": bound.manifest["axis"],
        "backbone": bound.manifest["backbone"],
        "bootstrap": {
            "cluster_unit": "prompt_id",
            "paired": True,
            "refit_each_replicate": False,
            "replicates": int(bootstrap["replicates"]),
            "seed": int(bootstrap["seed"]),
            "stratified": True,
        },
        "curves": curves,
        "four_way_gate": gate,
        "gate_order": [
            "ELIGIBLE",
            "REPLICATION_ONLY",
            "INCONCLUSIVE_UNDERPOWERED",
            "STOP_AXIS",
        ],
        "human_gold_claims": False,
        "input_manifest_path": str(bound.manifest_path),
        "input_manifest_sha256": bound.manifest_sha256,
        "model_id": bound.manifest["model_id"],
        "numeric_runtime": runtime,
        "oof_fit_diagnostics": list(oof.diagnostics),
        "overall_policy": overall_policy,
        "overall_predictive": overall_scoring,
        "schema_version": 1,
        "scientific_result_scope": "AUTOMATIC_INSTRUMENT_STATE_ELIGIBILITY_SCREEN",
        "status": "ELIGIBILITY_INITIAL_ANALYSIS_COMPLETE",
        "supplemental": supplemental,
        "tier": "INITIAL",
        "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
    }
    oof_rows: list[dict[str, Any]] = []
    baseline_selected_set = set(baseline_selected.values())
    state_selected_set = set(state_selected.values())
    for index, row in enumerate(rows):
        oof_rows.append(
            {
                "action": row["action"],
                "action_mapping_sha256": row["action_mapping_sha256"],
                "axis": row["axis"],
                "baseline_oof_probability": float(oof.probabilities[BASELINE_TIER][index]),
                "baseline_policy_selected": index in baseline_selected_set,
                "checkpoint_fraction": row["checkpoint_fraction"],
                "fold_id": row["fold_id"],
                "human_gold_claims": False,
                "lane_request_sha256": row["lane_request_sha256"],
                "outcome_success": row["outcome_success"],
                "prompt_id": row["prompt_id"],
                "root_index": row["root_index"],
                "schema_version": 1,
                "state_oof_probability": float(oof.probabilities[STATE_TIER][index]),
                "state_policy_selected": index in state_selected_set,
                "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
            }
        )
    return result, tuple(oof_rows)

"""CPU-only Stage-1 outcome gates and immutable cancellation evidence.

The evaluator deliberately refuses to infer gate thresholds.  It can run only
after both minima have been explicitly frozen in the bound configuration.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scoring.common import (
    load_json,
    load_jsonl,
    require_exact_keys,
    require_sha256,
    sha256_file,
)
from scoring.storage import ImmutableEventLog, write_json_exclusive

AXES = ("integrity", "tempo", "vocal_instrumental")
BACKBONES = ("ACE-Step v1", "stable-audio-3-medium-base")
BASE_CONDITION = "BASE"
GATE_RULE = (
    "OUTCOME_SCREEN_PASS iff point baseline_failure_rate >= frozen minimum AND "
    "point mixed_outcome_prompt_share >= frozen minimum; STOP_AXIS_STAGE1 otherwise"
)
PRIMARY_METRICS = {
    "integrity": "integrity_failure",
    "tempo": "full_clip_primary_5pct_success",
    "vocal_instrumental": "automatic_instrument_success",
}
FAILURE_POLARITY = {
    "integrity": "TRUE_IS_FAILURE",
    "tempo": "FALSE_IS_FAILURE",
    "vocal_instrumental": "FALSE_IS_FAILURE",
}
VERDICTS = {"OUTCOME_SCREEN_PASS", "STOP_AXIS_STAGE1"}
EXPECTED_ROOTS = tuple(range(8))
EXPECTED_STATE_ROOTS = tuple(range(4))
EXPECTED_CHECKPOINTS = (0.25, 0.5, 0.75)


class Stage1SpecificationError(ValueError):
    """Raised before scoring or cancellation when the gate is not frozen."""


@dataclass(frozen=True)
class GatePolicy:
    decision_id: str
    baseline_failure_rate_minimum: float
    mixed_outcome_prompt_share_minimum: float
    bootstrap_replicates: int = 10_000
    bootstrap_seed: int = 2_026_072_001
    confidence_level: float = 0.95
    axes: tuple[str, ...] = AXES
    backbones: tuple[str, ...] = BACKBONES
    condition: str = BASE_CONDITION
    expected_roots: tuple[int, ...] = EXPECTED_ROOTS


def _probability(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Stage1SpecificationError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise Stage1SpecificationError(f"{context} must be finite and in [0,1]")
    return result


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Stage1SpecificationError(f"{context} must be a nonempty string")
    return value


def load_gate_policy(path: Path) -> GatePolicy:
    """Load a frozen policy, rejecting the committed blocked template."""

    value = load_json(path)
    require_exact_keys(
        value,
        {
            "bindings",
            "bootstrap",
            "decision_id",
            "gate_rule",
            "population",
            "schema_version",
            "status",
            "thresholds",
        },
        "Stage-1 configuration",
    )
    if value["schema_version"] != 1:
        raise Stage1SpecificationError("Stage-1 schema_version must equal 1")
    if value["status"] != "FROZEN":
        raise Stage1SpecificationError(
            "Stage-1 gate is not frozen: both numerical thresholds and a decision binding "
            "are required before any outcome calculation or cancellation"
        )
    decision_id = _nonempty_string(value["decision_id"], "decision_id")
    if value["gate_rule"] != GATE_RULE:
        raise Stage1SpecificationError("Stage-1 gate rule differs from the fail-closed rule")

    thresholds = require_exact_keys(
        value["thresholds"],
        {"baseline_failure_rate_minimum", "mixed_outcome_prompt_share_minimum"},
        "Stage-1 thresholds",
    )
    baseline_minimum = _probability(
        thresholds["baseline_failure_rate_minimum"],
        "thresholds.baseline_failure_rate_minimum",
    )
    mixed_minimum = _probability(
        thresholds["mixed_outcome_prompt_share_minimum"],
        "thresholds.mixed_outcome_prompt_share_minimum",
    )

    population = require_exact_keys(
        value["population"],
        {"axes", "backbones", "condition", "expected_roots", "prompt_source"},
        "Stage-1 population",
    )
    if population["axes"] != list(AXES):
        raise Stage1SpecificationError("Stage-1 axes must be the three frozen confirmatory axes")
    if population["backbones"] != list(BACKBONES):
        raise Stage1SpecificationError("Stage-1 backbones must be exactly ACE and SA3")
    if population["condition"] != BASE_CONDITION:
        raise Stage1SpecificationError("Stage-1 population must use BASE outcomes only")
    if population["expected_roots"] != list(EXPECTED_ROOTS):
        raise Stage1SpecificationError("Stage-1 outcome roots must be exactly 0..7")
    if population["prompt_source"] != "statistics_v2.eligibility.prompt_selection.axis_prompt_ids":
        raise Stage1SpecificationError("Stage-1 prompts must be the frozen eligibility prompts")

    bootstrap = require_exact_keys(
        value["bootstrap"],
        {"confidence_level", "replicates", "seed", "two_stage_order"},
        "Stage-1 bootstrap",
    )
    if bootstrap["replicates"] != 10_000 or bootstrap["seed"] != 2_026_072_001:
        raise Stage1SpecificationError("Stage-1 bootstrap must retain the frozen v2 count and seed")
    if bootstrap["confidence_level"] != 0.95:
        raise Stage1SpecificationError("Stage-1 confidence level must equal 0.95")
    if bootstrap["two_stage_order"] != [
        "stratified_prompt_cluster",
        "matched_seed_within_cluster",
    ]:
        raise Stage1SpecificationError("Stage-1 bootstrap order differs from frozen v2")

    # Validate binding shape here.  Bytes are checked separately, only after the
    # policy itself has passed this fail-closed validation.
    bindings = require_exact_keys(
        value["bindings"],
        {"outcome_rows", "state_queues", "statistics_config"},
        "Stage-1 bindings",
    )
    for name in ("outcome_rows", "statistics_config"):
        binding = require_exact_keys(bindings[name], {"path", "sha256"}, f"bindings.{name}")
        _nonempty_string(binding["path"], f"bindings.{name}.path")
        require_sha256(binding["sha256"], f"bindings.{name}.sha256")
    if not isinstance(bindings["state_queues"], list) or len(bindings["state_queues"]) != 2:
        raise Stage1SpecificationError("bindings.state_queues must contain ACE and SA3")
    observed_backbones: set[str] = set()
    for index, raw in enumerate(bindings["state_queues"]):
        binding = require_exact_keys(
            raw, {"backbone", "path", "sha256"}, f"bindings.state_queues[{index}]"
        )
        observed_backbones.add(_nonempty_string(binding["backbone"], "state queue backbone"))
        _nonempty_string(binding["path"], "state queue path")
        require_sha256(binding["sha256"], "state queue sha256")
    if observed_backbones != set(BACKBONES):
        raise Stage1SpecificationError("state queue bindings must identify ACE and SA3 exactly")

    return GatePolicy(
        decision_id=decision_id,
        baseline_failure_rate_minimum=baseline_minimum,
        mixed_outcome_prompt_share_minimum=mixed_minimum,
    )


def validated_bindings(config_path: Path) -> dict[str, Any]:
    """Return bound input metadata only when every immutable SHA matches."""

    value = load_json(config_path)
    bindings = value["bindings"]
    for name in ("outcome_rows", "statistics_config"):
        path = Path(bindings[name]["path"])
        if not path.is_file() or sha256_file(path) != bindings[name]["sha256"]:
            raise Stage1SpecificationError(f"{name} binding is missing or has changed bytes")
    for binding in bindings["state_queues"]:
        path = Path(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Stage1SpecificationError(
                f"state queue binding for {binding['backbone']} is missing or has changed bytes"
            )
    return bindings


def _failure_value(row: dict[str, Any], axis: str) -> bool:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("scored outcome row lacks a metrics object")
    if axis == "integrity":
        file_failure = metrics.get("file_validity_failure")
        if not isinstance(file_failure, bool):
            raise ValueError("integrity file-validity outcome must be Boolean")
        if file_failure:
            # Frozen v2 Section 11.2: invalid files are failures, never dropped.
            return True
    value = metrics.get(PRIMARY_METRICS[axis])
    if not isinstance(value, bool):
        raise ValueError(f"{axis} primary automatic outcome must be Boolean")
    return value if FAILURE_POLARITY[axis] == "TRUE_IS_FAILURE" else not value


def _seed(base_seed: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{base_seed}|{namespace}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _selected_prompt_ids(statistics: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    try:
        raw = statistics["eligibility"]["prompt_selection"]["axis_prompt_ids"]
    except (KeyError, TypeError) as exc:
        raise ValueError("statistics config lacks frozen eligibility prompt IDs") from exc
    if not isinstance(raw, dict) or set(raw) != set(AXES):
        raise ValueError("statistics prompt selection does not cover the exact Stage-1 axes")
    result: dict[str, tuple[str, ...]] = {}
    for axis in AXES:
        values = raw[axis]
        if (
            not isinstance(values, list)
            or len(values) != 12
            or len(set(values)) != 12
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise ValueError(f"{axis} must freeze exactly 12 unique prompt IDs")
        result[axis] = tuple(values)
    return result


def _cell_values(
    rows: list[dict[str, Any]],
    *,
    axis: str,
    backbone: str,
    prompt_ids: tuple[str, ...],
    policy: GatePolicy,
) -> dict[str, dict[str, dict[int, bool]]]:
    selected = [
        row
        for row in rows
        if row.get("axis") == axis
        and row.get("backbone") == backbone
        and row.get("condition") == policy.condition
        and row.get("prompt_id") in prompt_ids
    ]
    expected_rows = len(prompt_ids) * len(policy.expected_roots)
    if len(selected) != expected_rows:
        raise ValueError(
            f"{backbone}/{axis} has {len(selected)} selected BASE rows; expected {expected_rows}"
        )
    cells: dict[str, dict[str, dict[int, bool]]] = defaultdict(lambda: defaultdict(dict))
    for row in selected:
        prompt_id = str(row["prompt_id"])
        root = row.get("root_index")
        if isinstance(root, bool) or not isinstance(root, int) or root not in policy.expected_roots:
            raise ValueError(f"{backbone}/{axis}/{prompt_id} has an invalid root")
        stratum = row.get("stratum")
        if not isinstance(stratum, str) or not stratum:
            raise ValueError(f"{backbone}/{axis}/{prompt_id} lacks a frozen stratum")
        if root in cells[stratum][prompt_id]:
            raise ValueError(f"duplicate Stage-1 outcome for {backbone}/{axis}/{prompt_id}/{root}")
        cells[stratum][prompt_id][root] = _failure_value(row, axis)
    observed_prompts = {prompt for prompts in cells.values() for prompt in prompts}
    if observed_prompts != set(prompt_ids):
        raise ValueError(f"{backbone}/{axis} selected prompt identities drifted")
    for prompt in observed_prompts:
        matches = [
            roots
            for prompts in cells.values()
            for name, roots in prompts.items()
            if name == prompt
        ]
        if len(matches) != 1 or set(matches[0]) != set(policy.expected_roots):
            raise ValueError(f"{backbone}/{axis}/{prompt} must contain roots 0..7 exactly")
    return {
        stratum: {prompt: dict(roots) for prompt, roots in prompts.items()}
        for stratum, prompts in cells.items()
    }


def _point_estimates(cells: dict[str, dict[str, dict[int, bool]]]) -> tuple[float, float]:
    failures: list[float] = []
    mixed: list[float] = []
    for prompts in cells.values():
        prompt_failures = [float(np.mean(list(roots.values()))) for roots in prompts.values()]
        prompt_mixed = [float(len(set(roots.values())) > 1) for roots in prompts.values()]
        failures.append(float(np.mean(prompt_failures)))
        mixed.append(float(np.mean(prompt_mixed)))
    return float(np.mean(failures)), float(np.mean(mixed))


def _bootstrap_intervals(
    cells: dict[str, dict[str, dict[int, bool]]],
    *,
    policy: GatePolicy,
    namespace: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    rng = np.random.default_rng(_seed(policy.bootstrap_seed, namespace))
    strata = sorted(cells)
    failure_by_stratum = np.empty(
        (policy.bootstrap_replicates, len(strata)), dtype=np.float64
    )
    mixed_by_stratum = np.empty_like(failure_by_stratum)
    stratum_arrays: list[tuple[np.ndarray, int, int]] = []
    bounds_pattern: list[int] = []
    for stratum in strata:
        prompts = cells[stratum]
        names = sorted(prompts)
        root_ids = sorted(prompts[names[0]])
        values = np.asarray(
            [[prompts[name][root] for root in root_ids] for name in names],
            dtype=np.bool_,
        )
        prompt_count, root_count = values.shape
        stratum_arrays.append((values, prompt_count, root_count))
        bounds_pattern.extend([prompt_count] * prompt_count)
        bounds_pattern.extend([root_count] * (prompt_count * root_count))

    # One replicate's bounds follow the scalar algorithm's exact draw order:
    # P prompt indices, then P x R root indices, repeated by sorted stratum.
    # Broadcasting that pattern over B preserves the deterministic seeded RNG
    # stream while avoiding its Python replicate/prompt loops.  At the frozen
    # design maximum this is only 10,000 x (12 + 12 x 8) integer draws.
    bounds = np.broadcast_to(
        np.asarray(bounds_pattern, dtype=np.int64),
        (policy.bootstrap_replicates, len(bounds_pattern)),
    )
    draws = rng.integers(0, bounds)
    offset = 0
    for stratum_index, (values, prompt_count, root_count) in enumerate(stratum_arrays):
        sampled_prompts = draws[:, offset : offset + prompt_count]
        offset += prompt_count
        sampled_roots = draws[
            :, offset : offset + prompt_count * root_count
        ].reshape(policy.bootstrap_replicates, prompt_count, root_count)
        offset += prompt_count * root_count
        sampled_values = values[sampled_prompts[..., np.newaxis], sampled_roots]
        failure_by_stratum[:, stratum_index] = sampled_values.mean(axis=2).mean(axis=1)
        mixed_by_stratum[:, stratum_index] = (
            sampled_values.any(axis=2) & ~sampled_values.all(axis=2)
        ).mean(axis=1)
    failure_draws = failure_by_stratum.mean(axis=1)
    mixed_draws = mixed_by_stratum.mean(axis=1)
    alpha = 1.0 - policy.confidence_level
    quantiles = (alpha / 2.0, 1.0 - alpha / 2.0)
    failure_ci = np.quantile(failure_draws, quantiles, method="linear")
    mixed_ci = np.quantile(mixed_draws, quantiles, method="linear")
    return (
        (float(failure_ci[0]), float(failure_ci[1])),
        (float(mixed_ci[0]), float(mixed_ci[1])),
    )


def compute_gate_results(
    rows: list[dict[str, Any]], statistics: dict[str, Any], policy: GatePolicy
) -> list[dict[str, Any]]:
    """Compute six automatic-only gate cells from exact selected BASE rows."""

    prompt_ids = _selected_prompt_ids(statistics)
    results: list[dict[str, Any]] = []
    for axis in policy.axes:
        for backbone in policy.backbones:
            cells = _cell_values(
                rows,
                axis=axis,
                backbone=backbone,
                prompt_ids=prompt_ids[axis],
                policy=policy,
            )
            failure_rate, mixed_share = _point_estimates(cells)
            failure_ci, mixed_ci = _bootstrap_intervals(
                cells, policy=policy, namespace=f"{backbone}|{axis}|stage1"
            )
            verdict = (
                "OUTCOME_SCREEN_PASS"
                if failure_rate >= policy.baseline_failure_rate_minimum
                and mixed_share >= policy.mixed_outcome_prompt_share_minimum
                else "STOP_AXIS_STAGE1"
            )
            results.append(
                {
                    "automatic_instrument_outcomes": True,
                    "axis": axis,
                    "backbone": backbone,
                    "baseline_failure_rate": {
                        "ci_high": failure_ci[1],
                        "ci_low": failure_ci[0],
                        "minimum": policy.baseline_failure_rate_minimum,
                        "point": failure_rate,
                    },
                    "bootstrap_replicates": policy.bootstrap_replicates,
                    "bootstrap_seed_namespace": f"{backbone}|{axis}|stage1",
                    "condition": policy.condition,
                    "confidence_level": policy.confidence_level,
                    "decision_id": policy.decision_id,
                    "failure_polarity": FAILURE_POLARITY[axis],
                    "gate_rule": GATE_RULE,
                    "human_gold_claims": False,
                    "mixed_outcome_prompt_share": {
                        "ci_high": mixed_ci[1],
                        "ci_low": mixed_ci[0],
                        "minimum": policy.mixed_outcome_prompt_share_minimum,
                        "point": mixed_share,
                    },
                    "primary_metric": PRIMARY_METRICS[axis],
                    "prompt_count": len(prompt_ids[axis]),
                    "resampling_unit": "STRATIFIED_PROMPT_CLUSTER_THEN_MATCHED_ROOT",
                    "root_count_per_prompt": len(policy.expected_roots),
                    "verdict": verdict,
                    "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
                }
            )
    return results


def plan_cancellations(
    results: list[dict[str, Any]],
    queue_bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate and return one deny row per materialized unit in STOP cells."""

    stops = {
        (row["backbone"], row["axis"]): row
        for row in results
        if row["verdict"] == "STOP_AXIS_STAGE1"
    }
    if any(row.get("verdict") not in VERDICTS for row in results):
        raise ValueError("Stage-1 result contains an unsupported verdict")
    output: list[dict[str, Any]] = []
    for binding in queue_bindings:
        backbone = str(binding["backbone"])
        path = Path(binding["path"])
        expected_sha = require_sha256(binding["sha256"], "state queue sha256")
        if sha256_file(path) != expected_sha:
            raise ValueError(f"state queue bytes changed for {backbone}")
        queue_rows = load_jsonl(path)
        for row in queue_rows:
            axis = row.get("axis")
            gate = stops.get((backbone, axis))
            if gate is None:
                continue
            unit = row.get("eligibility_unit")
            if not isinstance(unit, dict) or set(unit) != {"prompt", "root", "checkpoint"}:
                raise ValueError("state queue row lacks the exact eligibility unit")
            if (
                unit["root"] not in EXPECTED_STATE_ROOTS
                or unit["checkpoint"] not in EXPECTED_CHECKPOINTS
            ):
                raise ValueError("state queue STOP unit is outside the frozen initial queue")
            output.append(
                {
                    "axis": axis,
                    "backbone": backbone,
                    "cancellation_reason": "STOP_AXIS_STAGE1",
                    "eligibility_unit": dict(unit),
                    "lane_request_sha256": require_sha256(
                        row.get("lane_request_sha256"), "lane_request_sha256"
                    ),
                    "prohibited_operations": ["EXECUTE", "SCORE"],
                    "source_queue_path": str(path.resolve()),
                    "source_queue_sha256": expected_sha,
                    "status": "CANCELLED_STAGE1",
                    "verdict_decision_id": gate["decision_id"],
                    "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
                }
            )
    expected_per_stop = 12 * len(EXPECTED_STATE_ROOTS) * len(EXPECTED_CHECKPOINTS)
    if len(output) != len(stops) * expected_per_stop:
        raise ValueError(
            f"cancellation plan covers {len(output)} units; expected "
            f"{len(stops) * expected_per_stop}"
        )
    identities = {
        (
            row["backbone"],
            row["axis"],
            row["eligibility_unit"]["prompt"],
            row["eligibility_unit"]["root"],
            row["eligibility_unit"]["checkpoint"],
        )
        for row in output
    }
    if len(identities) != len(output):
        raise ValueError("cancellation plan contains duplicate eligibility units")
    return sorted(
        output,
        key=lambda row: (
            row["backbone"],
            row["axis"],
            row["eligibility_unit"]["prompt"],
            row["eligibility_unit"]["root"],
            row["eligibility_unit"]["checkpoint"],
        ),
    )


def write_stage1_artifacts(
    output_root: Path,
    *,
    results: list[dict[str, Any]],
    cancellations: list[dict[str, Any]],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Write a no-clobber result plus append-only cancellation hash chain."""

    output_root.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        output_root / "stage1-outcome-gates.json",
        {
            "human_gold_claims": False,
            "provenance": provenance,
            "rows": results,
            "schema_version": 1,
            "status": "STAGE1_OUTCOME_GATES_COMPLETE",
            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
        },
    )
    ledger = ImmutableEventLog(output_root / "cancellations" / "events")
    last_event_sha256 = "0" * 64
    for row in cancellations:
        event = ledger.append("STATE_UNIT_CANCELLED_STAGE1", row)
        last_event_sha256 = event["event_sha256"]
    summary = {
        "cancelled_unit_count": len(cancellations),
        "last_event_sha256": last_event_sha256,
        "prohibited_operations": ["EXECUTE", "SCORE"],
        "status": "CANCELLATION_CHAIN_COMPLETE",
        "stop_cell_count": sum(row["verdict"] == "STOP_AXIS_STAGE1" for row in results),
    }
    write_json_exclusive(output_root / "cancellations" / "summary.json", summary)
    return summary

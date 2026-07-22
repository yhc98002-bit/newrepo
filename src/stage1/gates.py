"""CPU-only Stage-1 outcome gates and immutable state-unit evidence.

The evaluator deliberately refuses to infer gate thresholds. It can run only
after the complete bounded policy has been explicitly frozen in the bound
configuration.
"""

from __future__ import annotations

import hashlib
import math
import re
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
from scoring.storage import ImmutableEventLog, write_json_exclusive, write_jsonl_exclusive

AXES = ("integrity", "tempo", "vocal_instrumental")
BACKBONES = ("ACE-Step v1", "stable-audio-3-medium-base")
BASE_CONDITION = "BASE"
GATE_RULE = (
    "OUTCOME_SCREEN_PASS iff frozen minimum <= point baseline_failure_rate <= frozen "
    "maximum AND point mixed_outcome_prompt_share >= frozen minimum; "
    "STOP_AXIS_STAGE1 otherwise"
)
MIXED_OUTCOME_PROMPT_DEFINITION = (
    "registered BASE prompt with at least one success and at least one failure among its "
    "eight registered roots"
)
POLICY_DECISION_ID = "D-0046"
POLICY_SCHEMA_VERSION = 2
POLICY_SCHEMA_RELATIVE_PATH = "configs/stage1_outcome_gates_v2.schema.json"
POLICY_SCHEMA_SHA256 = "4c49948dd9d9471f6d66f737ad5858d2662c7c37d16c5a501baf1905d889f0a6"
FROZEN_BASELINE_FAILURE_MINIMUM = 0.10
FROZEN_BASELINE_FAILURE_MAXIMUM = 0.60
FROZEN_MIXED_PROMPT_MINIMUM = 0.20
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
BACKBONE_SLUGS = {
    "ACE-Step v1": "ace-step-v1",
    "stable-audio-3-medium-base": "stable-audio-3-medium-base",
}


class Stage1SpecificationError(ValueError):
    """Raised before scoring or cancellation when the gate is not frozen."""


@dataclass(frozen=True)
class GatePolicy:
    decision_id: str
    baseline_failure_rate_minimum: float
    baseline_failure_rate_maximum: float
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
            "schema_binding",
            "schema_version",
            "status",
            "thresholds",
        },
        "Stage-1 configuration",
    )
    if value["schema_version"] != POLICY_SCHEMA_VERSION:
        raise Stage1SpecificationError(
            f"Stage-1 schema_version must equal {POLICY_SCHEMA_VERSION}"
        )
    if value["status"] != "FROZEN":
        raise Stage1SpecificationError(
            "Stage-1 gate is not frozen: the complete bounded policy and a decision binding "
            "are required before any outcome calculation or state-unit partition"
        )
    decision_id = _nonempty_string(value["decision_id"], "decision_id")
    if decision_id != POLICY_DECISION_ID:
        raise Stage1SpecificationError(
            f"Stage-1 policy must be bound to {POLICY_DECISION_ID}"
        )
    if value["gate_rule"] != GATE_RULE:
        raise Stage1SpecificationError("Stage-1 gate rule differs from the fail-closed rule")

    schema_binding = require_exact_keys(
        value["schema_binding"], {"path", "sha256"}, "Stage-1 schema binding"
    )
    if (
        schema_binding["path"] != POLICY_SCHEMA_RELATIVE_PATH
        or schema_binding["sha256"] != POLICY_SCHEMA_SHA256
    ):
        raise Stage1SpecificationError("Stage-1 JSON schema binding drifted")
    schema_path = Path(__file__).resolve().parents[2] / POLICY_SCHEMA_RELATIVE_PATH
    if not schema_path.is_file() or sha256_file(schema_path) != POLICY_SCHEMA_SHA256:
        raise Stage1SpecificationError("Stage-1 JSON schema bytes are missing or changed")

    thresholds = require_exact_keys(
        value["thresholds"],
        {
            "baseline_failure_rate_maximum",
            "baseline_failure_rate_minimum",
            "mixed_outcome_prompt_share_minimum",
        },
        "Stage-1 thresholds",
    )
    baseline_minimum = _probability(
        thresholds["baseline_failure_rate_minimum"],
        "thresholds.baseline_failure_rate_minimum",
    )
    baseline_maximum = _probability(
        thresholds["baseline_failure_rate_maximum"],
        "thresholds.baseline_failure_rate_maximum",
    )
    mixed_minimum = _probability(
        thresholds["mixed_outcome_prompt_share_minimum"],
        "thresholds.mixed_outcome_prompt_share_minimum",
    )
    if (
        baseline_minimum != FROZEN_BASELINE_FAILURE_MINIMUM
        or baseline_maximum != FROZEN_BASELINE_FAILURE_MAXIMUM
        or mixed_minimum != FROZEN_MIXED_PROMPT_MINIMUM
    ):
        raise Stage1SpecificationError(
            f"Stage-1 thresholds differ from the {POLICY_DECISION_ID} freeze"
        )
    if baseline_minimum > baseline_maximum:
        raise Stage1SpecificationError("Stage-1 failure-rate bounds are reversed")

    population = require_exact_keys(
        value["population"],
        {
            "axes",
            "backbones",
            "condition",
            "expected_roots",
            "mixed_outcome_prompt_definition",
            "prompt_source",
        },
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
    if population["mixed_outcome_prompt_definition"] != MIXED_OUTCOME_PROMPT_DEFINITION:
        raise Stage1SpecificationError("Stage-1 mixed-outcome prompt definition drifted")
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
        baseline_failure_rate_maximum=baseline_maximum,
        mixed_outcome_prompt_share_minimum=mixed_minimum,
    )


def policy_decision_assignments(config_path: Path) -> tuple[str, ...]:
    """Return the exact append-only assignments required by the D-0046 freeze."""

    return (
        "STAGE1_POLICY_STATUS = FROZEN_BEFORE_OUTCOME_READ",
        "STAGE1_POLICY_CONFIG_PATH = configs/stage1_outcome_gates_v2.json",
        f"STAGE1_POLICY_CONFIG_SHA256 = {sha256_file(config_path)}",
        f"STAGE1_POLICY_SCHEMA_SHA256 = {POLICY_SCHEMA_SHA256}",
        "STAGE1_BASELINE_FAILURE_RATE_MINIMUM = 0.10",
        "STAGE1_BASELINE_FAILURE_RATE_MAXIMUM = 0.60",
        "STAGE1_MIXED_OUTCOME_PROMPT_SHARE_MINIMUM = 0.20",
        f"STAGE1_MIXED_OUTCOME_PROMPT_DEFINITION = {MIXED_OUTCOME_PROMPT_DEFINITION}",
        f"STAGE1_GATE_RULE = {GATE_RULE}",
        "STAGE1_OUTCOME_ROWS_READ_AT_FREEZE = NO",
    )


def verify_policy_decision(
    config_path: Path,
    decisions_path: Path,
    *,
    policy: GatePolicy | None = None,
) -> dict[str, str]:
    """Bind the frozen config to its append-only decision before outcome I/O."""

    frozen_policy = policy or load_gate_policy(config_path)
    try:
        decisions_text = decisions_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise Stage1SpecificationError("Stage-1 policy decision record is unreadable") from exc
    match = re.search(
        rf"(?ms)^## {re.escape(frozen_policy.decision_id)}\b.*?(?=^## D-\d+\b|\Z)",
        decisions_text,
    )
    if match is None:
        raise Stage1SpecificationError(
            f"Stage-1 policy decision is absent: {frozen_policy.decision_id}"
        )
    block = match.group(0)
    required_assignments = policy_decision_assignments(config_path)
    missing = [assignment for assignment in required_assignments if assignment not in block]
    if missing:
        raise Stage1SpecificationError(
            "Stage-1 policy decision does not bind the complete frozen config: "
            + "; ".join(missing)
        )
    return {
        "decision_block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
        "decision_id": frozen_policy.decision_id,
        "decisions_path": str(decisions_path.resolve()),
    }


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
    prompt_roots = [roots for prompts in cells.values() for roots in prompts.values()]
    failure_rate = float(
        np.mean([failure for roots in prompt_roots for failure in roots.values()])
    )
    mixed_prompt_share = float(
        np.mean([any(roots.values()) and not all(roots.values()) for roots in prompt_roots])
    )
    return failure_rate, mixed_prompt_share


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


def gate_verdict(
    baseline_failure_rate: float,
    mixed_outcome_prompt_share: float,
    policy: GatePolicy,
) -> str:
    """Apply the frozen inclusive bounded Stage-1 rule to point estimates."""

    return (
        "OUTCOME_SCREEN_PASS"
        if policy.baseline_failure_rate_minimum
        <= baseline_failure_rate
        <= policy.baseline_failure_rate_maximum
        and mixed_outcome_prompt_share >= policy.mixed_outcome_prompt_share_minimum
        else "STOP_AXIS_STAGE1"
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
            verdict = gate_verdict(failure_rate, mixed_share, policy)
            results.append(
                {
                    "automatic_instrument_outcomes": True,
                    "axis": axis,
                    "backbone": backbone,
                    "baseline_failure_rate": {
                        "ci_high": failure_ci[1],
                        "ci_low": failure_ci[0],
                        "maximum": policy.baseline_failure_rate_maximum,
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
                        "definition": MIXED_OUTCOME_PROMPT_DEFINITION,
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

    cells = _validated_result_cells(results)
    stops = {
        identity: row
        for identity, row in cells.items()
        if row["verdict"] == "STOP_AXIS_STAGE1"
    }
    output: list[dict[str, Any]] = []
    for binding in _validated_queue_bindings(queue_bindings):
        backbone = str(binding["backbone"])
        path = Path(binding["path"])
        expected_sha = require_sha256(binding["sha256"], "state queue sha256")
        if sha256_file(path) != expected_sha:
            raise ValueError(f"state queue bytes changed for {backbone}")
        queue_rows = load_jsonl(path)
        for row in queue_rows:
            axis = row.get("axis")
            unit, request_sha256 = _validated_state_queue_row(row, backbone=backbone)
            gate = stops.get((backbone, axis))
            if gate is None:
                continue
            output.append(
                {
                    "axis": axis,
                    "backbone": backbone,
                    "cancellation_reason": "STOP_AXIS_STAGE1",
                    "eligibility_unit": dict(unit),
                    "lane_request_sha256": request_sha256,
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


def _validated_result_cells(
    results: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    expected = {(backbone, axis) for backbone in BACKBONES for axis in AXES}
    if len(results) != len(expected):
        raise ValueError("Stage-1 result must contain exactly six cells")
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        identity = (row.get("backbone"), row.get("axis"))
        if identity not in expected or identity in cells:
            raise ValueError("Stage-1 result cell identity is invalid or duplicated")
        if row.get("verdict") not in VERDICTS:
            raise ValueError("Stage-1 result contains an unsupported verdict")
        cells[identity] = row
    if set(cells) != expected:
        raise ValueError("Stage-1 result does not cover the exact six cells")
    return cells


def _validated_queue_bindings(
    queue_bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(queue_bindings, list) or len(queue_bindings) != len(BACKBONES):
        raise ValueError("state queue bindings must contain ACE and SA3 exactly")
    observed = [binding.get("backbone") for binding in queue_bindings]
    if len(set(observed)) != len(observed) or set(observed) != set(BACKBONES):
        raise ValueError("state queue bindings must identify ACE and SA3 exactly")
    return queue_bindings


def _validated_state_queue_row(
    row: dict[str, Any], *, backbone: str
) -> tuple[dict[str, Any], str]:
    axis = row.get("axis")
    if axis not in AXES:
        raise ValueError(f"state queue for {backbone} contains an unsupported axis")
    unit = row.get("eligibility_unit")
    if not isinstance(unit, dict) or set(unit) != {"prompt", "root", "checkpoint"}:
        raise ValueError("state queue row lacks the exact eligibility unit")
    prompt = unit.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("state queue eligibility prompt must be nonempty")
    if unit.get("root") not in EXPECTED_STATE_ROOTS:
        raise ValueError("state queue root is outside the frozen initial queue")
    if unit.get("checkpoint") not in EXPECTED_CHECKPOINTS:
        raise ValueError("state queue checkpoint is outside the frozen initial queue")
    return dict(unit), require_sha256(row.get("lane_request_sha256"), "lane_request_sha256")


def plan_survivors(
    results: list[dict[str, Any]],
    queue_bindings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return exact source-queue rows for PASS cells, partitioned by backbone."""

    cells = _validated_result_cells(results)
    passes = {
        identity
        for identity, row in cells.items()
        if row["verdict"] == "OUTCOME_SCREEN_PASS"
    }
    survivors = {backbone: [] for backbone in BACKBONES}
    identities: set[tuple[str, str, str, int, float]] = set()
    for binding in _validated_queue_bindings(queue_bindings):
        backbone = str(binding["backbone"])
        path = Path(binding["path"])
        expected_sha = require_sha256(binding["sha256"], "state queue sha256")
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise ValueError(f"state queue bytes changed for {backbone}")
        for row in load_jsonl(path):
            unit, _ = _validated_state_queue_row(row, backbone=backbone)
            axis = str(row["axis"])
            if (backbone, axis) not in passes:
                continue
            identity = (
                backbone,
                axis,
                str(unit["prompt"]),
                int(unit["root"]),
                float(unit["checkpoint"]),
            )
            if identity in identities:
                raise ValueError("survivor plan contains duplicate eligibility units")
            identities.add(identity)
            survivors[backbone].append(dict(row))
    expected_per_pass = 12 * len(EXPECTED_STATE_ROOTS) * len(EXPECTED_CHECKPOINTS)
    expected_count = len(passes) * expected_per_pass
    if sum(len(rows) for rows in survivors.values()) != expected_count:
        raise ValueError(
            "survivor plan covers "
            f"{sum(len(rows) for rows in survivors.values())} units; expected {expected_count}"
        )
    return survivors


def write_stage1_artifacts(
    output_root: Path,
    *,
    results: list[dict[str, Any]],
    cancellations: list[dict[str, Any]],
    survivors: dict[str, list[dict[str, Any]]],
    queue_bindings: list[dict[str, Any]],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Write no-clobber results, cancellation evidence, and survivor manifests."""

    expected_cancellations = plan_cancellations(results, queue_bindings)
    expected_survivors = plan_survivors(results, queue_bindings)
    if cancellations != expected_cancellations:
        raise ValueError("provided cancellations differ from the exact STOP-unit plan")
    if survivors != expected_survivors:
        raise ValueError("provided survivors differ from the exact PASS-unit plan")
    output_root.mkdir(parents=True, exist_ok=False)
    result_path = output_root / "stage1-outcome-gates.json"
    write_json_exclusive(
        result_path,
        {
            "human_gold_claims": False,
            "provenance": provenance,
            "rows": results,
            "schema_version": 2,
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
    cancellation_root = output_root / "cancellations"
    summary_path = cancellation_root / "summary.json"
    write_json_exclusive(summary_path, summary)
    cancellation_units_path = cancellation_root / "units.jsonl"
    write_jsonl_exclusive(cancellation_units_path, cancellations)
    write_json_exclusive(
        cancellation_root / "manifest.json",
        {
            "event_count": len(cancellations),
            "event_last_sha256": last_event_sha256,
            "human_gold_claims": False,
            "prohibited_operations": ["EXECUTE", "SCORE"],
            "schema_version": 1,
            "stage1_result_path": str(result_path.resolve()),
            "stage1_result_sha256": sha256_file(result_path),
            "status": "STAGE1_CANCELLATION_MANIFEST_COMPLETE",
            "summary_path": str(summary_path.resolve()),
            "summary_sha256": sha256_file(summary_path),
            "units_path": str(cancellation_units_path.resolve()),
            "units_sha256": sha256_file(cancellation_units_path),
            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
        },
    )

    bindings_by_backbone = {
        str(binding["backbone"]): binding for binding in _validated_queue_bindings(queue_bindings)
    }
    result_cells = _validated_result_cells(results)
    survivor_index: dict[str, dict[str, Any]] = {}
    for backbone in BACKBONES:
        backbone_root = output_root / "survivors" / BACKBONE_SLUGS[backbone]
        units_path = backbone_root / "units.jsonl"
        write_jsonl_exclusive(units_path, survivors[backbone])
        binding = bindings_by_backbone[backbone]
        pass_axes = [
            axis
            for axis in AXES
            if result_cells[(backbone, axis)]["verdict"] == "OUTCOME_SCREEN_PASS"
        ]
        stop_axes = [axis for axis in AXES if axis not in pass_axes]
        manifest_path = backbone_root / "manifest.json"
        manifest = {
            "automatic_instrument_outcomes": True,
            "backbone": backbone,
            "decision_id": results[0]["decision_id"],
            "human_gold_claims": False,
            "pass_axes": pass_axes,
            "schema_version": 1,
            "source_queue_path": str(Path(binding["path"]).resolve()),
            "source_queue_sha256": require_sha256(
                binding["sha256"], "state queue sha256"
            ),
            "stage1_result_path": str(result_path.resolve()),
            "stage1_result_sha256": sha256_file(result_path),
            "status": "STAGE1_SURVIVOR_MANIFEST_COMPLETE",
            "stop_axes": stop_axes,
            "unit_count": len(survivors[backbone]),
            "units_path": str(units_path.resolve()),
            "units_sha256": sha256_file(units_path),
            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
        }
        write_json_exclusive(manifest_path, manifest)
        survivor_index[backbone] = {
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "unit_count": len(survivors[backbone]),
        }
    write_json_exclusive(
        output_root / "survivors" / "manifest.json",
        {
            "backbones": survivor_index,
            "human_gold_claims": False,
            "schema_version": 1,
            "stage1_result_sha256": sha256_file(result_path),
            "status": "STAGE1_SURVIVOR_INDEX_COMPLETE",
            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
        },
    )
    return summary

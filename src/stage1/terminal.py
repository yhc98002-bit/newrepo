"""Deep validation for immutable Stage-1 terminal evidence.

The state lanes must never trust a six-label JSON file.  This module binds the
terminal result back to the frozen Stage-1 policy and its input provenance,
validates every metric cell, recomputes every verdict, and validates the exact
deny-both cancellation chain against the frozen state queues.
"""

from __future__ import annotations

import math
import stat
from collections.abc import Mapping
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
    sha256_json,
)
from stage1.gates import (
    AXES,
    BACKBONES,
    BASE_CONDITION,
    FAILURE_POLARITY,
    GATE_RULE,
    PRIMARY_METRICS,
    VERDICTS,
    GatePolicy,
    compute_gate_results,
    load_gate_policy,
    plan_cancellations,
    validated_bindings,
)

RESULT_STATUS = "STAGE1_OUTCOME_GATES_COMPLETE"
PASS = "OUTCOME_SCREEN_PASS"
STOP = "STOP_AXIS_STAGE1"
WATERMARK = "AUTOMATIC-INSTRUMENT OUTCOMES"
GENESIS = "0" * 64

_RESULT_KEYS = {
    "human_gold_claims",
    "provenance",
    "rows",
    "schema_version",
    "status",
    "watermark",
}
_PROVENANCE_KEYS = {
    "config_path",
    "config_sha256",
    "outcome_rows_path",
    "outcome_rows_sha256",
    "statistics_config_path",
    "statistics_config_sha256",
}
_ROW_KEYS = {
    "automatic_instrument_outcomes",
    "axis",
    "backbone",
    "baseline_failure_rate",
    "bootstrap_replicates",
    "bootstrap_seed_namespace",
    "condition",
    "confidence_level",
    "decision_id",
    "failure_polarity",
    "gate_rule",
    "human_gold_claims",
    "mixed_outcome_prompt_share",
    "primary_metric",
    "prompt_count",
    "resampling_unit",
    "root_count_per_prompt",
    "verdict",
    "watermark",
}
_ESTIMATE_KEYS = {"ci_high", "ci_low", "minimum", "point"}
_SUMMARY_KEYS = {
    "cancelled_unit_count",
    "last_event_sha256",
    "prohibited_operations",
    "status",
    "stop_cell_count",
}
_EVENT_KEYS = {
    "event_kind",
    "event_sha256",
    "payload",
    "previous_event_sha256",
    "sequence",
}


class Stage1TerminalError(RuntimeError):
    """Stage-1 terminal evidence is incomplete, inconsistent, or unbound."""


@dataclass(frozen=True)
class Stage1Terminal:
    """Validated Stage-1 evidence safe for survivor-only state filtering."""

    config_path: Path
    config_sha256: str
    policy: GatePolicy
    result_path: Path
    result_sha256: str
    summary_path: Path
    summary_sha256: str
    result: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    summary: Mapping[str, Any]
    cancellations: tuple[Mapping[str, Any], ...]


def _immutable_file(path: Path, label: str) -> Path:
    source = path.resolve(strict=True)
    mode = source.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o222:
        raise Stage1TerminalError(f"{label} is not an immutable no-clobber artifact")
    return source


def _canonical_bound_file(path_value: Any, sha_value: Any, label: str) -> tuple[Path, str]:
    if not isinstance(path_value, str) or not path_value:
        raise Stage1TerminalError(f"{label} path must be nonempty")
    raw_path = Path(path_value)
    if not raw_path.is_absolute():
        raise Stage1TerminalError(f"{label} path must be absolute")
    path = raw_path.resolve(strict=True)
    if path_value != str(path):
        raise Stage1TerminalError(f"{label} path must be canonical")
    expected = require_sha256(sha_value, f"{label} sha256")
    if not path.is_file() or sha256_file(path) != expected:
        raise Stage1TerminalError(f"{label} SHA-256 binding drifted")
    return path, expected


def _probability(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Stage1TerminalError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise Stage1TerminalError(f"{label} must be finite and in [0,1]")
    return result


def _exact_positive_int(value: Any, expected: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise Stage1TerminalError(f"{label} must equal {expected}")


def _validate_estimate(
    raw: Any,
    *,
    expected_minimum: float,
    label: str,
) -> float:
    value = require_exact_keys(raw, _ESTIMATE_KEYS, label)
    point = _probability(value["point"], f"{label}.point")
    ci_low = _probability(value["ci_low"], f"{label}.ci_low")
    ci_high = _probability(value["ci_high"], f"{label}.ci_high")
    minimum = _probability(value["minimum"], f"{label}.minimum")
    if ci_low > ci_high:
        raise Stage1TerminalError(f"{label} CI bounds are reversed")
    if minimum != expected_minimum:
        raise Stage1TerminalError(f"{label} minimum differs from the frozen policy")
    return point


def _validate_provenance(
    result: Mapping[str, Any],
    *,
    expected_config_path: Path,
) -> tuple[Path, str, GatePolicy, dict[str, Any]]:
    provenance = require_exact_keys(result.get("provenance"), _PROVENANCE_KEYS, "provenance")
    config_path, config_sha256 = _canonical_bound_file(
        provenance["config_path"], provenance["config_sha256"], "Stage-1 config"
    )
    if config_path != expected_config_path.resolve(strict=True):
        raise Stage1TerminalError("Stage-1 result names a different gate configuration")
    outcome_path, outcome_sha256 = _canonical_bound_file(
        provenance["outcome_rows_path"],
        provenance["outcome_rows_sha256"],
        "Stage-1 outcome rows",
    )
    statistics_path, statistics_sha256 = _canonical_bound_file(
        provenance["statistics_config_path"],
        provenance["statistics_config_sha256"],
        "Stage-1 statistics config",
    )
    try:
        policy = load_gate_policy(config_path)
        bindings = validated_bindings(config_path)
    except (OSError, ValueError) as exc:
        raise Stage1TerminalError(f"frozen Stage-1 policy/provenance is invalid: {exc}") from exc
    outcome_binding = bindings["outcome_rows"]
    statistics_binding = bindings["statistics_config"]
    if (
        Path(outcome_binding["path"]).resolve(strict=True) != outcome_path
        or outcome_binding["sha256"] != outcome_sha256
        or Path(statistics_binding["path"]).resolve(strict=True) != statistics_path
        or statistics_binding["sha256"] != statistics_sha256
    ):
        raise Stage1TerminalError("Stage-1 result provenance differs from its frozen config")
    return config_path, config_sha256, policy, bindings


def _validate_rows(raw_rows: Any, policy: GatePolicy) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or len(raw_rows) != len(AXES) * len(BACKBONES):
        raise Stage1TerminalError("Stage-1 result must contain exactly six cells")
    rows: list[dict[str, Any]] = []
    cells: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_rows):
        row = require_exact_keys(raw, _ROW_KEYS, f"Stage-1 row[{index}]")
        axis = row["axis"]
        backbone = row["backbone"]
        if axis not in AXES or backbone not in BACKBONES or (backbone, axis) in cells:
            raise Stage1TerminalError("Stage-1 row cell identity is invalid or duplicated")
        cells.add((backbone, axis))
        if (
            row["automatic_instrument_outcomes"] is not True
            or row["human_gold_claims"] is not False
            or row["watermark"] != WATERMARK
            or row["condition"] != BASE_CONDITION
            or row["gate_rule"] != GATE_RULE
            or row["decision_id"] != policy.decision_id
            or row["primary_metric"] != PRIMARY_METRICS[axis]
            or row["failure_polarity"] != FAILURE_POLARITY[axis]
            or row["resampling_unit"]
            != "STRATIFIED_PROMPT_CLUSTER_THEN_MATCHED_ROOT"
            or row["bootstrap_seed_namespace"] != f"{backbone}|{axis}|stage1"
        ):
            raise Stage1TerminalError(f"Stage-1 {backbone}/{axis} metric contract drifted")
        _exact_positive_int(
            row["bootstrap_replicates"], policy.bootstrap_replicates, "bootstrap_replicates"
        )
        _exact_positive_int(row["prompt_count"], 12, "prompt_count")
        _exact_positive_int(
            row["root_count_per_prompt"], len(policy.expected_roots), "root_count_per_prompt"
        )
        confidence = _probability(row["confidence_level"], "confidence_level")
        if confidence != policy.confidence_level:
            raise Stage1TerminalError("confidence_level differs from the frozen policy")
        failure_point = _validate_estimate(
            row["baseline_failure_rate"],
            expected_minimum=policy.baseline_failure_rate_minimum,
            label=f"{backbone}/{axis}.baseline_failure_rate",
        )
        mixed_point = _validate_estimate(
            row["mixed_outcome_prompt_share"],
            expected_minimum=policy.mixed_outcome_prompt_share_minimum,
            label=f"{backbone}/{axis}.mixed_outcome_prompt_share",
        )
        recomputed = (
            PASS
            if failure_point >= policy.baseline_failure_rate_minimum
            and mixed_point >= policy.mixed_outcome_prompt_share_minimum
            else STOP
        )
        if row["verdict"] not in VERDICTS or row["verdict"] != recomputed:
            raise Stage1TerminalError(f"Stage-1 {backbone}/{axis} verdict was not recomputed")
        rows.append(row)
    expected_cells = {(backbone, axis) for backbone in BACKBONES for axis in AXES}
    if cells != expected_cells:
        raise Stage1TerminalError("Stage-1 result does not cover the exact six cells")
    return rows


def _validate_cancellations(
    summary_path: Path,
    *,
    rows: list[dict[str, Any]],
    queue_bindings: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = require_exact_keys(load_json(summary_path), _SUMMARY_KEYS, "cancellation summary")
    events_dir = summary_path.parent / "events"
    events = sorted(events_dir.glob("[0-9]*-*.json")) if events_dir.is_dir() else []
    previous = GENESIS
    payloads: list[dict[str, Any]] = []
    for sequence, path in enumerate(events, start=1):
        _immutable_file(path, "Stage-1 cancellation event")
        event = require_exact_keys(load_json(path), _EVENT_KEYS, "cancellation event")
        claimed = require_sha256(event["event_sha256"], "cancellation event sha256")
        unhashed = dict(event)
        unhashed.pop("event_sha256")
        if (
            event["sequence"] != sequence
            or event["previous_event_sha256"] != previous
            or event["event_kind"] != "STATE_UNIT_CANCELLED_STAGE1"
            or claimed != sha256_json(unhashed)
            or path.name != f"{sequence:06d}-{claimed}.json"
        ):
            raise Stage1TerminalError("Stage-1 cancellation hash chain is invalid")
        if not isinstance(event["payload"], dict):
            raise Stage1TerminalError("Stage-1 cancellation payload must be an object")
        payloads.append(event["payload"])
        previous = claimed
    stop_count = sum(row["verdict"] == STOP for row in rows)
    if (
        summary["status"] != "CANCELLATION_CHAIN_COMPLETE"
        or summary["prohibited_operations"] != ["EXECUTE", "SCORE"]
        or summary["cancelled_unit_count"] != len(payloads)
        or summary["last_event_sha256"] != previous
        or summary["stop_cell_count"] != stop_count
    ):
        raise Stage1TerminalError("Stage-1 cancellation summary disagrees with its chain")
    try:
        expected = plan_cancellations(rows, queue_bindings)
    except (OSError, ValueError) as exc:
        raise Stage1TerminalError(f"Stage-1 cancellation source is invalid: {exc}") from exc
    if [canonical_json(row) for row in payloads] != [canonical_json(row) for row in expected]:
        raise Stage1TerminalError("Stage-1 cancellation chain is not the exact STOP-unit plan")
    return summary, payloads


def validate_stage1_terminal(
    result_path: Path,
    summary_path: Path,
    *,
    expected_config_path: Path,
    expected_result_sha256: str | None = None,
    expected_summary_sha256: str | None = None,
) -> Stage1Terminal:
    """Validate all Stage-1 evidence before a state survivor can be selected."""

    try:
        result_path = _immutable_file(result_path, "Stage-1 result")
        summary_path = _immutable_file(summary_path, "Stage-1 cancellation summary")
        result_sha256 = sha256_file(result_path)
        summary_sha256 = sha256_file(summary_path)
        if expected_result_sha256 is not None and result_sha256 != require_sha256(
            expected_result_sha256, "expected Stage-1 result sha256"
        ):
            raise Stage1TerminalError("Stage-1 result content binding drifted")
        if expected_summary_sha256 is not None and summary_sha256 != require_sha256(
            expected_summary_sha256, "expected Stage-1 summary sha256"
        ):
            raise Stage1TerminalError("Stage-1 summary content binding drifted")
        result = require_exact_keys(load_json(result_path), _RESULT_KEYS, "Stage-1 result")
        if (
            result["schema_version"] != 1
            or result["status"] != RESULT_STATUS
            or result["human_gold_claims"] is not False
            or result["watermark"] != WATERMARK
        ):
            raise Stage1TerminalError("Stage-1 result is not complete automatic-only evidence")
        config_path, config_sha256, policy, bindings = _validate_provenance(
            result, expected_config_path=expected_config_path
        )
        rows = _validate_rows(result["rows"], policy)
        # A self-consistent six-label file is not evidence.  Re-run the frozen
        # calculation over the exact outcome/statistics bytes bound by the
        # policy, including the deterministic two-stage bootstrap, and require
        # byte-canonical equality for every reported cell.
        recomputed_rows = compute_gate_results(
            load_jsonl(Path(bindings["outcome_rows"]["path"])),
            load_json(Path(bindings["statistics_config"]["path"])),
            policy,
        )
        if [canonical_json(row) for row in rows] != [
            canonical_json(row) for row in recomputed_rows
        ]:
            raise Stage1TerminalError(
                "Stage-1 rows differ from recomputation over bound outcomes"
            )
        summary, cancellations = _validate_cancellations(
            summary_path,
            rows=rows,
            queue_bindings=bindings["state_queues"],
        )
    except Stage1TerminalError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise Stage1TerminalError(f"invalid Stage-1 terminal evidence: {exc}") from exc
    return Stage1Terminal(
        config_path=config_path,
        config_sha256=config_sha256,
        policy=policy,
        result_path=result_path,
        result_sha256=result_sha256,
        summary_path=summary_path,
        summary_sha256=summary_sha256,
        result=result,
        rows=tuple(rows),
        summary=summary,
        cancellations=tuple(cancellations),
    )


__all__ = [
    "PASS",
    "STOP",
    "Stage1Terminal",
    "Stage1TerminalError",
    "validate_stage1_terminal",
]

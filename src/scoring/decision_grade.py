"""Decision-grade summaries of frozen automatic-instrument outcomes."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from scoring.common import (
    load_json,
    load_jsonl,
    require_sha256,
    sha256_file,
    sha256_json,
)
from scoring.published_tables import WATERMARK, validate_automatic_table_language
from scoring.statistics import cluster_bootstrap_prevalence, prevalence_table

REGISTERED_BACKBONES = (
    "stable-audio-3-medium-base",
    "stable-audio-open-1.0",
    "ACE-Step v1",
)
CONFIRMATORY_AXES = ("vocal_instrumental", "tempo", "integrity")
INTEGRITY_DEFECTS = ("clipping", "dropout", "silence", "crackle")
FORBIDDEN_OUTPUT_TOKENS = ("accuracy", "human_gold", "human-gold", "human gold")
PRIMARY_CONDITIONS = ("BASE", "FIXED")
DIAGNOSTIC_CONDITION = "NEGATION_DIAGNOSTIC"
FROZEN_CORE_ROWS_PER_BACKBONE = 1536
FROZEN_CONFIRMATORY_CELL_ROWS = {
    ("vocal_instrumental", "BASE"): 192,
    ("vocal_instrumental", "FIXED"): 192,
    ("vocal_instrumental", DIAGNOSTIC_CONDITION): 96,
    ("tempo", "BASE"): 240,
    ("tempo", "FIXED"): 240,
    ("integrity", "BASE"): 144,
    ("integrity", "FIXED"): 144,
}
FROZEN_CONFIRMATORY_ROWS_PER_BACKBONE = sum(FROZEN_CONFIRMATORY_CELL_ROWS.values())
SOURCE_BINDING_STATUS = "VERIFIED_AGAINST_SCORING_CONFIG_STATUS_AND_COMPLETED_SNAPSHOT"
COMPLETE_SOURCE_STATUS = "COMPLETE_ALL_THREE_FROZEN_PRIMARY_BACKBONES"
PARTIAL_SOURCE_STATUS = "PARTIAL_REGISTERED_BACKBONES_OR_COMPLETED_SHARD_PREFIX"


def _derived_seed(base_seed: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{base_seed}|{namespace}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _validate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("decision-grade input must be a nonempty row list")
    seen_requests: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {index} must be an object")
        for field in (
            "automatic_result",
            "axis",
            "backbone",
            "cluster_id",
            "condition",
            "metrics",
            "prompt_metadata",
            "request_sha256",
            "root_index",
            "source_run_id",
            "stratum",
        ):
            if field not in row:
                raise ValueError(f"row {index} lacks {field}")
        if row["axis"] not in CONFIRMATORY_AXES:
            raise ValueError(f"row {index} is outside the confirmatory axes")
        if row["backbone"] not in REGISTERED_BACKBONES:
            raise ValueError(f"row {index} uses an unregistered backbone")
        condition = row["condition"]
        allowed_conditions = (
            {*PRIMARY_CONDITIONS, DIAGNOSTIC_CONDITION}
            if row["axis"] == "vocal_instrumental"
            else set(PRIMARY_CONDITIONS)
        )
        if condition not in allowed_conditions:
            raise ValueError(
                f"row {index} uses condition {condition!r} outside its frozen axis contract"
            )
        for field in ("cluster_id", "stratum"):
            if not isinstance(row[field], str) or not row[field]:
                raise ValueError(f"row {index}.{field} must be a nonempty string")
        root = row["root_index"]
        if isinstance(root, bool) or not isinstance(root, int) or root < 0:
            raise ValueError(f"row {index}.root_index must be a nonnegative integer")
        if (
            not isinstance(row["metrics"], dict)
            or not isinstance(row["automatic_result"], dict)
            or not isinstance(row["prompt_metadata"], dict)
        ):
            raise ValueError(f"row {index} metrics/result must be objects")
        if condition == DIAGNOSTIC_CONDITION and row["prompt_metadata"].get(
            "request"
        ) != "instrumental":
            raise ValueError("negation diagnostic is restricted to instrumental requests")
        for metric, value in row["metrics"].items():
            if not isinstance(metric, str) or not metric:
                raise ValueError(f"row {index} has an invalid metric name")
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"row {index}.{metric} must be boolean or null")
        request = require_sha256(row["request_sha256"], f"row {index}.request_sha256")
        source_run_id = row["source_run_id"]
        if not isinstance(source_run_id, str) or not source_run_id:
            raise ValueError(f"row {index}.source_run_id must be nonempty")
        if request in seen_requests:
            raise ValueError("decision-grade input contains a duplicate request")
        seen_requests.add(request)
    return rows


def _numeric_cells(
    rows: list[dict[str, Any]], value: Callable[[dict[str, Any]], float | None]
) -> tuple[dict[str, dict[str, dict[int, float]]], int]:
    raw: dict[str, dict[str, dict[int, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    observed = 0
    for index, row in enumerate(rows):
        item = value(row)
        if item is None:
            continue
        number = _finite_number(item, f"numeric summary row {index}")
        raw[str(row["stratum"])][str(row["cluster_id"])][int(row["root_index"])].append(number)
        observed += 1
    cells = {
        stratum: {
            cluster: {root: float(np.mean(values)) for root, values in roots.items()}
            for cluster, roots in clusters.items()
        }
        for stratum, clusters in raw.items()
    }
    return cells, observed


def _cell_mean(cells: dict[str, dict[str, dict[int, float]]]) -> float:
    stratum_means = []
    for clusters in cells.values():
        cluster_means = [
            float(np.mean(list(root_values.values()))) for root_values in clusters.values()
        ]
        if cluster_means:
            stratum_means.append(float(np.mean(cluster_means)))
    return float(np.mean(stratum_means))


def cluster_bootstrap_mean(
    rows: list[dict[str, Any]],
    value: Callable[[dict[str, Any]], float | None],
    *,
    replicates: int,
    seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    """Two-stage prompt-cluster interval for a finite continuous summary."""

    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates <= 0:
        raise ValueError("replicates must be a positive integer")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be in (0,1)")
    cells, observed = _numeric_cells(rows, value)
    cluster_count = sum(len(clusters) for clusters in cells.values())
    if observed == 0 or cluster_count == 0:
        return {
            "ci_high": None,
            "ci_low": None,
            "cluster_count": cluster_count,
            "missing_count": len(rows) - observed,
            "observed_count": observed,
            "point_mean": None,
            "row_count": len(rows),
        }
    point = _cell_mean(cells)
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=np.float64)
    for replicate in range(replicates):
        stratum_means = []
        for stratum in sorted(cells):
            clusters = cells[stratum]
            names = sorted(clusters)
            sampled_clusters = rng.integers(0, len(names), size=len(names))
            cluster_means = []
            for sampled_cluster in sampled_clusters:
                roots = clusters[names[int(sampled_cluster)]]
                root_ids = sorted(roots)
                sampled_roots = rng.integers(0, len(root_ids), size=len(root_ids))
                cluster_means.append(
                    float(
                        np.mean(
                            [roots[root_ids[int(sampled_root)]] for sampled_root in sampled_roots]
                        )
                    )
                )
            stratum_means.append(float(np.mean(cluster_means)))
        draws[replicate] = float(np.mean(stratum_means))
    alpha = 1.0 - confidence_level
    low, high = np.quantile(draws, (alpha / 2.0, 1.0 - alpha / 2.0), method="linear")
    return {
        "ci_high": float(high),
        "ci_low": float(low),
        "cluster_count": cluster_count,
        "missing_count": len(rows) - observed,
        "observed_count": observed,
        "point_mean": point,
        "row_count": len(rows),
    }


def _watermark(
    rows: list[dict[str, Any]], source_completeness: str
) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "source_completeness": source_completeness,
            "watermark": WATERMARK,
        }
        for row in rows
    ]


def _condition_prevalence(
    rows: list[dict[str, Any]],
    *,
    conditions: tuple[str, ...],
    table_scope: str,
    analysis_role: str,
    replicates: int,
    seed: int,
    confidence_level: float,
    source_completeness: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for condition in conditions:
        group = [row for row in rows if row["condition"] == condition]
        if not group:
            continue
        raw = prevalence_table(
            group,
            replicates=replicates,
            seed=seed,
            confidence_level=confidence_level,
            headline_only=False,
        )
        for row in raw:
            if row["condition"] != condition or row["slice"] != "ALL":
                continue
            cleaned = {key: value for key, value in row.items() if key != "human_gold_claims"}
            cleaned["analysis_role"] = analysis_role
            cleaned["table_scope"] = table_scope
            output.append(cleaned)
    return _watermark(output, source_completeness)


def _drift_value(row: dict[str, Any], field: str) -> float | None:
    drift = row["automatic_result"].get("window_drift")
    if not isinstance(drift, dict):
        raise ValueError("tempo row lacks window_drift")
    status = drift.get("status")
    if status == "WINDOW_DRIFT_UNRESOLVED":
        if drift.get(field) is not None:
            raise ValueError("unresolved window drift must be null")
        return None
    if status != "RESOLVED":
        raise ValueError("tempo row has an invalid window-drift status")
    return _finite_number(drift.get(field), f"window_drift.{field}")


def _tempo_drift_table(
    rows: list[dict[str, Any]],
    *,
    replicates: int,
    seed: int,
    confidence_level: float,
    source_completeness: str,
) -> list[dict[str, Any]]:
    output = []
    for backbone in REGISTERED_BACKBONES:
        for condition in PRIMARY_CONDITIONS:
            group = [
                row
                for row in rows
                if row["backbone"] == backbone
                and row["axis"] == "tempo"
                and row["condition"] == condition
            ]
            if not group:
                continue
            for metric, field in (
                ("second_minus_first_signed_drift_octaves", "signed_drift_octaves"),
                (
                    "second_vs_first_octave_invariant_absolute_drift",
                    "octave_invariant_absolute_drift",
                ),
            ):
                namespace = f"{backbone}|tempo|{condition}|window-drift|{metric}"
                output.append(
                    {
                        "axis": "tempo",
                        "backbone": backbone,
                        "bootstrap_replicates": replicates,
                        "bootstrap_seed_namespace": namespace,
                        "condition": condition,
                        "confidence_level": confidence_level,
                        "metric": metric,
                        "resampling_unit": "PROMPT_CLUSTER_THEN_MATCHED_SEED",
                        **cluster_bootstrap_mean(
                            group,
                            lambda row, active=field: _drift_value(row, active),
                            replicates=replicates,
                            seed=_derived_seed(seed, namespace),
                            confidence_level=confidence_level,
                        ),
                    }
                )
    return _watermark(output, source_completeness)


def _pair_summary(
    group: list[dict[str, Any]],
    *,
    axis: str,
    backbone: str,
    condition: str,
    comparison: str,
    left_name: str,
    right_name: str,
    values: Callable[[dict[str, Any]], tuple[bool | None, bool | None]],
    replicates: int,
    seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    derived = []
    cells = {"00": 0, "01": 0, "10": 0, "11": 0}
    for row in group:
        left, right = values(row)
        if left is not None and not isinstance(left, bool):
            raise ValueError(f"{comparison} left value must be boolean or null")
        if right is not None and not isinstance(right, bool):
            raise ValueError(f"{comparison} right value must be boolean or null")
        disagreement = None if left is None or right is None else left != right
        if left is not None and right is not None:
            cells[f"{int(left)}{int(right)}"] += 1
        derived.append({**row, "metrics": {"pair_disagreement": disagreement}})
    namespace = f"{backbone}|{axis}|{condition}|instrument-disagreement|{comparison}"
    summary = cluster_bootstrap_prevalence(
        derived,
        "pair_disagreement",
        replicates=replicates,
        seed=_derived_seed(seed, namespace),
        confidence_level=confidence_level,
    )
    return {
        "axis": axis,
        "backbone": backbone,
        "bootstrap_replicates": replicates,
        "bootstrap_seed_namespace": namespace,
        "comparison": comparison,
        "condition": condition,
        "confidence_level": confidence_level,
        "joint_boolean_counts": cells,
        "left_operationalization": left_name,
        "resampling_unit": "PROMPT_CLUSTER_THEN_MATCHED_SEED",
        "right_operationalization": right_name,
        **summary,
    }


def _direct_disagreement_summary(
    group: list[dict[str, Any]],
    *,
    axis: str,
    backbone: str,
    condition: str,
    comparison: str,
    operationalizations: list[str],
    value: Callable[[dict[str, Any]], bool | None],
    replicates: int,
    seed: int,
    confidence_level: float,
) -> dict[str, Any]:
    derived = []
    for row in group:
        item = value(row)
        if item is not None and not isinstance(item, bool):
            raise ValueError(f"{comparison} value must be boolean or null")
        derived.append({**row, "metrics": {"pair_disagreement": item}})
    namespace = f"{backbone}|{axis}|{condition}|instrument-disagreement|{comparison}"
    summary = cluster_bootstrap_prevalence(
        derived,
        "pair_disagreement",
        replicates=replicates,
        seed=_derived_seed(seed, namespace),
        confidence_level=confidence_level,
    )
    return {
        "axis": axis,
        "backbone": backbone,
        "bootstrap_replicates": replicates,
        "bootstrap_seed_namespace": namespace,
        "comparison": comparison,
        "condition": condition,
        "confidence_level": confidence_level,
        "operationalizations": operationalizations,
        "resampling_unit": "PROMPT_CLUSTER_THEN_MATCHED_SEED",
        **summary,
    }


def _tempo_estimator_disagreement(row: dict[str, Any]) -> bool | None:
    result = row["automatic_result"]
    audit = result.get("raw_estimator_audit")
    full = result.get("full_clip")
    if not isinstance(audit, dict) or not isinstance(full, dict):
        raise ValueError("tempo row lacks full estimator audit")
    full_audit = audit.get("full_clip")
    if not isinstance(full_audit, dict):
        raise ValueError("tempo row lacks full-clip estimator audit")
    beat_this = full_audit.get("beat_this")
    librosa = full_audit.get("librosa")
    if not isinstance(beat_this, dict) or not isinstance(librosa, dict):
        raise ValueError("tempo row lacks estimator records")
    beat_valid = beat_this.get("valid")
    librosa_valid = librosa.get("valid")
    if not isinstance(beat_valid, bool) or not isinstance(librosa_valid, bool):
        raise ValueError("tempo estimator validity must be boolean")
    if not (beat_valid and librosa_valid):
        return None
    status = full.get("status")
    if status not in {"RESOLVED", "ESTIMATOR_DISAGREEMENT"}:
        raise ValueError("two valid tempo estimators have an inconsistent resolution status")
    return status == "ESTIMATOR_DISAGREEMENT"


def _instrument_disagreement_table(
    rows: list[dict[str, Any]],
    *,
    conditions: tuple[str, ...],
    replicates: int,
    seed: int,
    confidence_level: float,
    source_completeness: str,
) -> list[dict[str, Any]]:
    output = []
    for backbone in REGISTERED_BACKBONES:
        for axis in CONFIRMATORY_AXES:
            for condition in conditions:
                group = [
                    row
                    for row in rows
                    if row["backbone"] == backbone
                    and row["axis"] == axis
                    and row["condition"] == condition
                ]
                if not group:
                    continue
                if axis == "vocal_instrumental":
                    output.append(
                        _pair_summary(
                            group,
                            axis=axis,
                            backbone=backbone,
                            condition=condition,
                            comparison="demucs_vs_panns_presence",
                            left_name="DEMUCs threshold branch",
                            right_name="PANNs threshold branch",
                            values=lambda row: (
                                row["metrics"].get("demucs_present"),
                                row["metrics"].get("panns_present"),
                            ),
                            replicates=replicates,
                            seed=seed,
                            confidence_level=confidence_level,
                        )
                    )
                elif axis == "tempo":
                    output.extend(
                        (
                            _direct_disagreement_summary(
                                group,
                                axis=axis,
                                backbone=backbone,
                                condition=condition,
                                comparison="beat_this_vs_librosa_estimator_disagreement",
                                operationalizations=["Beat This!", "librosa"],
                                value=_tempo_estimator_disagreement,
                                replicates=replicates,
                                seed=seed,
                                confidence_level=confidence_level,
                            ),
                            _pair_summary(
                                group,
                                axis=axis,
                                backbone=backbone,
                                condition=condition,
                                comparison="beat_this_vs_librosa_5pct_target_label",
                                left_name="Beat This! 5% target label",
                                right_name="librosa 5% target label",
                                values=lambda row: (
                                    row["metrics"].get(
                                        "beat_this_primary_5pct_success"
                                    ),
                                    row["metrics"].get(
                                        "librosa_primary_5pct_success"
                                    ),
                                ),
                                replicates=replicates,
                                seed=seed,
                                confidence_level=confidence_level,
                            ),
                        )
                    )
                else:
                    for defect in INTEGRITY_DEFECTS:
                        output.append(
                            _pair_summary(
                                group,
                                axis=axis,
                                backbone=backbone,
                                condition=condition,
                                comparison=f"{defect}_defect_vs_four_defect_or",
                                left_name=f"{defect} defect flag",
                                right_name="four-defect OR",
                                values=lambda row, active=defect: (
                                    row["metrics"].get(f"{active}_defect"),
                                    row["metrics"].get("integrity_failure"),
                                ),
                                replicates=replicates,
                                seed=seed,
                                confidence_level=confidence_level,
                            )
                        )
    return _watermark(output, source_completeness)


def _row_cell_counts(rows: list[dict[str, Any]], backbone: str) -> dict[str, int]:
    return {
        f"{axis}|{condition}": sum(
            row["backbone"] == backbone
            and row["axis"] == axis
            and row["condition"] == condition
            for row in rows
        )
        for axis, condition in FROZEN_CONFIRMATORY_CELL_ROWS
    }


def _require_count(value: Any, context: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a nonnegative integer")
    return value


def _unique_by_backbone(rows: Any, context: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{context} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{context}[{index}] must be an object")
        backbone = row.get("backbone")
        if backbone not in REGISTERED_BACKBONES:
            raise ValueError(f"{context}[{index}] has an unregistered backbone")
        if backbone in result:
            raise ValueError(f"{context} repeats backbone {backbone}")
        result[backbone] = row
    return result


def _snapshot_rows_by_request(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("completed snapshot rows must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"completed snapshot row {index} must be an object")
        if row.get("axis") not in CONFIRMATORY_AXES:
            continue
        request = require_sha256(
            row.get("request_sha256"), f"completed snapshot row {index}.request_sha256"
        )
        if request in result:
            raise ValueError("completed snapshot repeats a confirmatory request")
        result[request] = row
    return result


def load_bound_decision_grade_source(
    input_jsonl_path: Path,
    *,
    scoring_config_path: Path,
    scoring_status_path: Path,
    source_snapshot_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load rows only after binding them to the scoring snapshot and completion state."""

    input_path = input_jsonl_path.resolve()
    config_path = scoring_config_path.resolve()
    status_path = scoring_status_path.resolve()
    snapshot_path = source_snapshot_path.resolve()
    rows = _validate_rows(load_jsonl(input_path))
    config = load_json(config_path)
    status = load_json(status_path)
    snapshot = load_json(snapshot_path)

    if config.get("schema_version") not in {1, 2}:
        raise ValueError("scoring config schema is unsupported")
    if config.get("primary_backbones") != list(REGISTERED_BACKBONES):
        raise ValueError("scoring config does not bind the three frozen primary backbones")
    if status.get("schema_version") != 1:
        raise ValueError("scoring status schema is unsupported")
    if snapshot.get("schema_version") != 1:
        raise ValueError("completed snapshot schema is unsupported")

    claimed_snapshot_sha = require_sha256(
        snapshot.get("snapshot_sha256"), "source snapshot SHA-256"
    )
    snapshot_without_claim = dict(snapshot)
    del snapshot_without_claim["snapshot_sha256"]
    if sha256_json(snapshot_without_claim) != claimed_snapshot_sha:
        raise ValueError("source snapshot self-hash mismatch")
    source_ledger_sha = require_sha256(
        snapshot.get("source_ledger_sha256"), "snapshot source-ledger SHA-256"
    )
    if status.get("source_ledger_sha256") != source_ledger_sha:
        raise ValueError("scoring status and completed snapshot source ledgers differ")

    snapshot_rows = _snapshot_rows_by_request(snapshot)
    input_rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        request = require_sha256(row.get("request_sha256"), f"input row {index}.request_sha256")
        input_rows[request] = row
    if set(input_rows) != set(snapshot_rows):
        missing = len(set(snapshot_rows) - set(input_rows))
        extra = len(set(input_rows) - set(snapshot_rows))
        raise ValueError(
            "decision-grade input differs from completed-snapshot confirmatory rows; "
            f"missing={missing}, extra={extra}"
        )
    identity_fields = (
        "audio_sha256",
        "axis",
        "backbone",
        "cluster_id",
        "condition",
        "prompt_id",
        "root_index",
        "source_run_id",
    )
    for request, row in input_rows.items():
        source = snapshot_rows[request]
        if any(row.get(field) != source.get(field) for field in identity_fields):
            raise ValueError("decision-grade input identity differs from its snapshot row")

    config_sources = _unique_by_backbone(config.get("sources"), "scoring config sources")
    snapshot_sources = _unique_by_backbone(
        snapshot.get("sources"), "completed snapshot sources"
    )
    status_sources = _unique_by_backbone(status.get("backbones"), "scoring status backbones")
    if set(snapshot_sources) != set(config_sources):
        raise ValueError("completed snapshot source set differs from the scoring config")
    if set(status_sources) != set(REGISTERED_BACKBONES):
        raise ValueError("scoring status does not enumerate all frozen primary backbones")
    config_run_ids = [source.get("run_id") for source in config_sources.values()]
    if any(not isinstance(run_id, str) or not run_id for run_id in config_run_ids):
        raise ValueError("every scoring source must have a nonempty run ID")
    if len(set(config_run_ids)) != len(config_run_ids):
        raise ValueError("scoring source run IDs must be unique")

    observed_counts = {
        backbone: sum(row["backbone"] == backbone for row in rows)
        for backbone in REGISTERED_BACKBONES
    }
    derived_missing = [
        backbone for backbone in REGISTERED_BACKBONES if backbone not in config_sources
    ]
    derived_incomplete: list[str] = []
    source_records: list[dict[str, Any]] = []
    for backbone in REGISTERED_BACKBONES:
        status_row = status_sources[backbone]
        scored_rows = _require_count(
            status_row.get("scored_rows"), f"scoring status {backbone}.scored_rows"
        )
        if scored_rows != observed_counts[backbone]:
            raise ValueError(f"scoring status row count differs for {backbone}")
        config_source = config_sources.get(backbone)
        snapshot_source = snapshot_sources.get(backbone)
        if config_source is None:
            if snapshot_source is not None or observed_counts[backbone] != 0:
                raise ValueError(f"missing source {backbone} nevertheless contributes rows")
            if not str(status_row.get("status", "")).startswith("MISSING_"):
                raise ValueError(f"missing source {backbone} lacks a missing status")
            source_records.append(
                {
                    "backbone": backbone,
                    "core_completion": "MISSING_REGISTERED_BACKBONE",
                    "expected_completed_core_rows": None,
                    "expected_core_rows": None,
                    "observed_confirmatory_cells": _row_cell_counts(rows, backbone),
                    "observed_confirmatory_rows": 0,
                    "scoring_backbone_status": status_row["status"],
                    "snapshot_core_rows": None,
                    "source_completion_mode": None,
                    "source_run_id": None,
                }
            )
            continue

        if snapshot_source is None:
            raise ValueError(f"configured source {backbone} is absent from the snapshot")
        expected_rows = _require_count(
            config_source.get("expected_queue_rows"),
            f"scoring config {backbone}.expected_queue_rows",
        )
        expected_completed = _require_count(
            config_source.get("expected_completed_rows"),
            f"scoring config {backbone}.expected_completed_rows",
        )
        snapshot_count = _require_count(
            snapshot_source.get("row_count"), f"snapshot {backbone}.row_count"
        )
        actual_snapshot_count = sum(
            row.get("backbone") == backbone for row in snapshot.get("rows", [])
        )
        if snapshot_count != actual_snapshot_count:
            raise ValueError(f"snapshot source row count differs from rows for {backbone}")
        if expected_completed != snapshot_count:
            raise ValueError(f"declared completion differs from snapshot rows for {backbone}")
        if snapshot_source.get("run_id") != config_source.get("run_id"):
            raise ValueError(f"snapshot/config run ID differs for {backbone}")
        if snapshot_source.get("completion_mode") != config_source.get("completion_mode"):
            raise ValueError(f"snapshot/config completion mode differs for {backbone}")
        if any(
            row.get("source_run_id") != snapshot_source.get("run_id")
            for row in snapshot.get("rows", [])
            if row.get("backbone") == backbone
        ):
            raise ValueError(f"snapshot rows use the wrong source run ID for {backbone}")
        cells = _row_cell_counts(rows, backbone)
        cells_complete = cells == {
            f"{axis}|{condition}": count
            for (axis, condition), count in FROZEN_CONFIRMATORY_CELL_ROWS.items()
        }
        core_complete = (
            expected_rows == FROZEN_CORE_ROWS_PER_BACKBONE
            and expected_completed == FROZEN_CORE_ROWS_PER_BACKBONE
            and snapshot_count == FROZEN_CORE_ROWS_PER_BACKBONE
            and observed_counts[backbone] == FROZEN_CONFIRMATORY_ROWS_PER_BACKBONE
            and cells_complete
        )
        scoring_backbone_status = status_row.get("status")
        if core_complete:
            if scoring_backbone_status != "AUTOMATIC_ENDPOINTS_SCORED":
                raise ValueError(f"complete source {backbone} lacks its complete scoring status")
            completion = "COMPLETE_FROZEN_CORE"
        else:
            if scoring_backbone_status == "AUTOMATIC_ENDPOINTS_SCORED":
                raise ValueError(f"partial source {backbone} claims complete automatic endpoints")
            completion = "COMPLETED_SHARD_PREFIX_ONLY"
            derived_incomplete.append(backbone)
        source_records.append(
            {
                "backbone": backbone,
                "core_completion": completion,
                "expected_completed_core_rows": expected_completed,
                "expected_core_rows": expected_rows,
                "observed_confirmatory_cells": cells,
                "observed_confirmatory_rows": observed_counts[backbone],
                "scoring_backbone_status": scoring_backbone_status,
                "snapshot_core_rows": snapshot_count,
                "source_completion_mode": snapshot_source.get("completion_mode"),
                "source_run_id": snapshot_source.get("run_id"),
            }
        )

    if status.get("missing_primary_backbones") != derived_missing:
        raise ValueError("scoring-status missing-backbone list differs from source artifacts")
    if "incomplete_primary_backbones" in status:
        if status["incomplete_primary_backbones"] != derived_incomplete:
            raise ValueError(
                "scoring-status incomplete-backbone list differs from source artifacts"
            )
    elif not (
        not derived_incomplete
        and derived_missing
        and status.get("status") == "SCORING_COMPLETE_MISSING_PRIMARY_BACKBONE"
    ):
        raise ValueError(
            "scoring-status lacks its incomplete-backbone list outside the immutable "
            "complete-sources/missing-primary legacy case"
        )
    all_complete = all(
        record["core_completion"] == "COMPLETE_FROZEN_CORE" for record in source_records
    )
    source_completeness = COMPLETE_SOURCE_STATUS if all_complete else PARTIAL_SOURCE_STATUS
    binding = {
        "all_registered_backbones_complete": all_complete,
        "backbones": source_records,
        "binding_status": SOURCE_BINDING_STATUS,
        "input_jsonl_path": str(input_path),
        "input_jsonl_sha256": sha256_file(input_path),
        "normalized_rows_sha256": sha256_json({"rows": rows}),
        "registered_backbones": list(REGISTERED_BACKBONES),
        "schema_version": 1,
        "scoring_config_path": str(config_path),
        "scoring_config_sha256": sha256_file(config_path),
        "scoring_run_id": config.get("run_id"),
        "scoring_status_path": str(status_path),
        "scoring_status_sha256": sha256_file(status_path),
        "scoring_status_value": status.get("status"),
        "source_completeness": source_completeness,
        "source_ledger_sha256": source_ledger_sha,
        "source_snapshot_file_sha256": sha256_file(snapshot_path),
        "source_snapshot_path": str(snapshot_path),
        "source_snapshot_sha256": claimed_snapshot_sha,
    }
    return rows, binding


def _validate_source_binding(
    rows: list[dict[str, Any]], source_binding: dict[str, Any] | None
) -> str:
    if not isinstance(source_binding, dict):
        raise ValueError("verified source binding is required for decision-grade tables")
    if source_binding.get("binding_status") != SOURCE_BINDING_STATUS:
        raise ValueError("decision-grade source binding is not verified")
    if source_binding.get("registered_backbones") != list(REGISTERED_BACKBONES):
        raise ValueError("decision-grade source binding changes the registered backbones")
    if source_binding.get("normalized_rows_sha256") != sha256_json({"rows": rows}):
        raise ValueError("decision-grade rows differ from the verified source binding")
    records = _unique_by_backbone(
        source_binding.get("backbones"), "decision-grade source binding backbones"
    )
    if set(records) != set(REGISTERED_BACKBONES):
        raise ValueError("decision-grade source binding lacks a registered backbone")
    all_complete = True
    for backbone in REGISTERED_BACKBONES:
        record = records[backbone]
        observed = sum(row["backbone"] == backbone for row in rows)
        if record.get("observed_confirmatory_rows") != observed:
            raise ValueError("decision-grade source binding row count differs")
        cells = _row_cell_counts(rows, backbone)
        if record.get("observed_confirmatory_cells") != cells:
            raise ValueError("decision-grade source binding cell counts differ")
        complete = record.get("core_completion") == "COMPLETE_FROZEN_CORE"
        if complete and (
            record.get("expected_completed_core_rows") != FROZEN_CORE_ROWS_PER_BACKBONE
            or record.get("expected_core_rows") != FROZEN_CORE_ROWS_PER_BACKBONE
            or record.get("snapshot_core_rows") != FROZEN_CORE_ROWS_PER_BACKBONE
            or record.get("scoring_backbone_status") != "AUTOMATIC_ENDPOINTS_SCORED"
            or observed != FROZEN_CONFIRMATORY_ROWS_PER_BACKBONE
            or cells
            != {
                f"{axis}|{condition}": count
                for (axis, condition), count in FROZEN_CONFIRMATORY_CELL_ROWS.items()
            }
        ):
            raise ValueError("decision-grade source binding makes an invalid completeness claim")
        all_complete = all_complete and complete
    if source_binding.get("all_registered_backbones_complete") is not all_complete:
        raise ValueError("decision-grade aggregate source completeness is inconsistent")
    expected_status = COMPLETE_SOURCE_STATUS if all_complete else PARTIAL_SOURCE_STATUS
    if source_binding.get("source_completeness") != expected_status:
        raise ValueError("decision-grade source-completeness label is inconsistent")
    return expected_status


def validate_output_language(tables: dict[str, Any]) -> None:
    """Fail if a table accidentally adopts prohibited evaluative wording."""

    payload = json.dumps(tables, allow_nan=False, sort_keys=True).lower()
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in payload:
            raise ValueError(f"decision-grade output contains prohibited token {token!r}")
    validate_automatic_table_language(tables, "decision-grade output")
    source_completeness = tables.get("source_completeness")
    if source_completeness not in {COMPLETE_SOURCE_STATUS, PARTIAL_SOURCE_STATUS}:
        raise ValueError("decision-grade output has an invalid source-completeness label")
    for table_name in (
        "prevalence",
        "tempo_window_drift",
        "instrument_disagreement",
        "negation_diagnostic_prevalence",
        "negation_diagnostic_instrument_disagreement",
    ):
        table = tables.get(table_name)
        if not isinstance(table, list) or any(
            row.get("watermark") != WATERMARK
            or row.get("source_completeness") != source_completeness
            for row in table
        ):
            raise ValueError(f"{table_name} rows lack their automatic-instrument watermark")


def build_decision_grade_tables(
    rows: list[dict[str, Any]],
    *,
    source_binding: dict[str, Any] | None = None,
    replicates: int,
    seed: int,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Build tables without selecting thresholds or consulting label data."""

    normalized = _validate_rows(rows)
    source_completeness = _validate_source_binding(normalized, source_binding)
    observed = {row["backbone"] for row in normalized}
    included = [backbone for backbone in REGISTERED_BACKBONES if backbone in observed]
    tables = {
        "included_backbones": included,
        "instrument_disagreement": _instrument_disagreement_table(
            normalized,
            conditions=PRIMARY_CONDITIONS,
            replicates=replicates,
            seed=seed,
            confidence_level=confidence_level,
            source_completeness=source_completeness,
        ),
        "missing_registered_backbones": [
            backbone for backbone in REGISTERED_BACKBONES if backbone not in observed
        ],
        "negation_diagnostic_instrument_disagreement": _instrument_disagreement_table(
            normalized,
            conditions=(DIAGNOSTIC_CONDITION,),
            replicates=replicates,
            seed=seed,
            confidence_level=confidence_level,
            source_completeness=source_completeness,
        ),
        "negation_diagnostic_prevalence": _condition_prevalence(
            normalized,
            conditions=(DIAGNOSTIC_CONDITION,),
            table_scope="NEGATION_DIAGNOSTIC_PREVALENCE_SEPARATE_FROM_PRIMARY",
            analysis_role="ESTIMATE_ONLY_DIAGNOSTIC",
            replicates=replicates,
            seed=seed,
            confidence_level=confidence_level,
            source_completeness=source_completeness,
        ),
        "prevalence": _condition_prevalence(
            normalized,
            conditions=PRIMARY_CONDITIONS,
            table_scope="PER_AXIS_BACKBONE_CONDITION_PREVALENCE",
            analysis_role="PRIMARY_BASE_OR_POSITIVE_FIXED",
            replicates=replicates,
            seed=seed,
            confidence_level=confidence_level,
            source_completeness=source_completeness,
        ),
        "registered_backbones": list(REGISTERED_BACKBONES),
        "schema_version": 1,
        "source_binding": source_binding,
        "source_completeness": source_completeness,
        "status": (
            "DECISION_GRADE_AUTOMATIC_TABLES_COMPLETE_ALL_THREE_PRIMARY_BACKBONES"
            if source_completeness == COMPLETE_SOURCE_STATUS
            else "DECISION_GRADE_AUTOMATIC_TABLES_PARTIAL_VERIFIED_SOURCES"
        ),
        "tempo_window_drift": _tempo_drift_table(
            normalized,
            replicates=replicates,
            seed=seed,
            confidence_level=confidence_level,
            source_completeness=source_completeness,
        ),
        "watermark": WATERMARK,
    }
    validate_output_language(tables)
    return tables

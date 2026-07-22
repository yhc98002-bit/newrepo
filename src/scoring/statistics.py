"""Prompt-cluster prevalence summaries for automatic benchmark endpoints."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

import numpy as np

METRICS = {
    "vocal_instrumental": (
        "automatic_instrument_success",
        "automatic_voice_presence",
    ),
    "tempo": (
        "full_clip_primary_5pct_success",
        "full_clip_sensitivity_10pct_success",
        "full_clip_abstention",
        "first_window_primary_5pct_success",
        "first_window_sensitivity_10pct_success",
        "second_window_primary_5pct_success",
        "second_window_sensitivity_10pct_success",
        "window_drift_resolved",
    ),
    "integrity": (
        "clipping_defect",
        "dropout_defect",
        "silence_defect",
        "crackle_defect",
        "integrity_failure",
        "file_validity_failure",
    ),
}


def _seed(base_seed: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{base_seed}|{namespace}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _cells(rows: list[dict[str, Any]], metric: str) -> dict[str, dict[str, dict[int, float]]]:
    raw: dict[str, dict[str, dict[int, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in rows:
        value = row["metrics"].get(metric)
        if value is None:
            continue
        if not isinstance(value, bool):
            raise ValueError(f"prevalence metric {metric} must be boolean or null")
        raw[str(row["stratum"])][str(row["cluster_id"])][int(row["root_index"])].append(
            float(value)
        )
    return {
        stratum: {
            cluster: {seed: float(np.mean(values)) for seed, values in seeds.items()}
            for cluster, seeds in clusters.items()
        }
        for stratum, clusters in raw.items()
    }


def _estimate(cells: dict[str, dict[str, dict[int, float]]]) -> float:
    stratum_means: list[float] = []
    for clusters in cells.values():
        cluster_means = [
            float(np.mean(list(seed_values.values()))) for seed_values in clusters.values()
        ]
        if cluster_means:
            stratum_means.append(float(np.mean(cluster_means)))
    return float(np.mean(stratum_means)) if stratum_means else float("nan")


def cluster_bootstrap_prevalence(
    rows: list[dict[str, Any]],
    metric: str,
    *,
    replicates: int,
    seed: int,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Two-stage stratified cluster/seed bootstrap for a Boolean prevalence."""

    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates <= 0:
        raise ValueError("replicates must be a positive integer")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be in (0,1)")
    cells = _cells(rows, metric)
    point = _estimate(cells)
    total = len(rows)
    observed = sum(row["metrics"].get(metric) is not None for row in rows)
    cluster_count = sum(len(clusters) for clusters in cells.values())
    if observed == 0 or cluster_count == 0:
        return {
            "ci_high": None,
            "ci_low": None,
            "cluster_count": cluster_count,
            "missing_count": total - observed,
            "observed_count": observed,
            "point_prevalence": None,
            "row_count": total,
        }

    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=np.float64)
    strata = sorted(cells)
    for replicate in range(replicates):
        stratum_means: list[float] = []
        for stratum in strata:
            clusters = cells[stratum]
            names = sorted(clusters)
            sampled_indices = rng.integers(0, len(names), size=len(names))
            sampled_cluster_means: list[float] = []
            for index in sampled_indices:
                seed_values = clusters[names[int(index)]]
                seed_ids = sorted(seed_values)
                sampled_seeds = rng.integers(0, len(seed_ids), size=len(seed_ids))
                sampled_cluster_means.append(
                    float(
                        np.mean(
                            [seed_values[seed_ids[int(seed_index)]] for seed_index in sampled_seeds]
                        )
                    )
                )
            stratum_means.append(float(np.mean(sampled_cluster_means)))
        draws[replicate] = float(np.mean(stratum_means))
    alpha = 1.0 - confidence_level
    low, high = np.quantile(draws, (alpha / 2.0, 1.0 - alpha / 2.0), method="linear")
    return {
        "ci_high": float(high),
        "ci_low": float(low),
        "cluster_count": cluster_count,
        "missing_count": total - observed,
        "observed_count": observed,
        "point_prevalence": point,
        "row_count": total,
    }


def _slice_value(row: dict[str, Any], axis: str) -> str:
    if axis == "vocal_instrumental":
        return str(row["prompt_metadata"]["request"])
    if axis == "tempo":
        return str(row["prompt_metadata"]["salience"])
    return str(row["prompt_metadata"]["profile"])


def prevalence_table(
    rows: list[dict[str, Any]],
    *,
    replicates: int,
    seed: int,
    confidence_level: float,
    headline_only: bool = False,
) -> list[dict[str, Any]]:
    """Report every registered endpoint by backbone, condition, and frozen slice."""

    output: list[dict[str, Any]] = []
    backbones = sorted({row["backbone"] for row in rows})
    for backbone in backbones:
        for axis, metrics in METRICS.items():
            axis_rows = [
                row for row in rows if row["backbone"] == backbone and row["axis"] == axis
            ]
            if not axis_rows:
                continue
            conditions = ["ALL", *sorted({str(row["condition"]) for row in axis_rows})]
            slices = ["ALL", *sorted({_slice_value(row, axis) for row in axis_rows})]
            group_keys = (
                [("ALL", "ALL")]
                if headline_only
                else [
                    *((condition, "ALL") for condition in conditions),
                    *(("ALL", slice_value) for slice_value in slices[1:]),
                ]
            )
            for condition, slice_value in group_keys:
                group = [
                    row
                    for row in axis_rows
                    if (condition == "ALL" or row["condition"] == condition)
                    and (slice_value == "ALL" or _slice_value(row, axis) == slice_value)
                ]
                if not group:
                    continue
                for metric in metrics:
                    namespace = f"{backbone}|{axis}|{condition}|{slice_value}|{metric}"
                    summary = cluster_bootstrap_prevalence(
                        group,
                        metric,
                        replicates=replicates,
                        seed=_seed(seed, namespace),
                        confidence_level=confidence_level,
                    )
                    output.append(
                        {
                            "axis": axis,
                            "backbone": backbone,
                            "bootstrap_replicates": replicates,
                            "bootstrap_seed_namespace": namespace,
                            "condition": condition,
                            "confidence_level": confidence_level,
                            "metric": metric,
                            "resampling_unit": "PROMPT_CLUSTER_THEN_MATCHED_SEED",
                            "slice": slice_value,
                            **summary,
                        }
                    )
    return output

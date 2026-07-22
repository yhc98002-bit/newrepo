"""Test-only builders for fully bound Stage-1 terminal evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scoring.common import load_json, sha256_file
from stage1.gates import (
    AXES,
    BACKBONES,
    compute_gate_results,
    load_gate_policy,
    plan_cancellations,
    write_stage1_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
PASS = "OUTCOME_SCREEN_PASS"
STOP = "STOP_AXIS_STAGE1"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, allow_nan=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def queue_binding(path: Path, backbone: str) -> dict[str, str]:
    return {"backbone": backbone, "path": str(path.resolve()), "sha256": sha256_file(path)}


def build_terminal(
    tmp_path: Path,
    *,
    queue_bindings: list[dict[str, str]],
    stopped_cells: set[tuple[str, str]],
    decision_id: str = "D-STAGE1-FIXTURE",
    baseline_minimum: float = 0.25,
    mixed_minimum: float = 0.25,
) -> tuple[Path, Path, Path]:
    """Build evidence with the same deep schema and bindings as the production writer."""

    if {binding["backbone"] for binding in queue_bindings} != set(BACKBONES):
        raise ValueError("fixture queue bindings must cover ACE and SA3")
    inputs = tmp_path / "inputs"
    outcome_rows = inputs / "automatic-endpoint-outcomes.jsonl"
    statistics = inputs / "statistics_v2.json"
    prompt_ids = {
        axis: [f"{axis}-prompt-{index:02d}" for index in range(12)] for axis in AXES
    }
    statistics_value = {
        "eligibility": {"prompt_selection": {"axis_prompt_ids": prompt_ids}}
    }
    outcome_values: list[dict[str, Any]] = []
    for backbone in BACKBONES:
        for axis in AXES:
            stopped = (backbone, axis) in stopped_cells
            for prompt_index, prompt_id in enumerate(prompt_ids[axis]):
                for root in range(8):
                    failure = False if stopped else root % 2 == 0
                    if axis == "integrity":
                        metrics = {
                            "file_validity_failure": False,
                            "integrity_failure": failure,
                        }
                    elif axis == "tempo":
                        metrics = {"full_clip_primary_5pct_success": not failure}
                    else:
                        metrics = {"automatic_instrument_success": not failure}
                    outcome_values.append(
                        {
                            "axis": axis,
                            "backbone": backbone,
                            "condition": "BASE",
                            "metrics": metrics,
                            "prompt_id": prompt_id,
                            "root_index": root,
                            "stratum": (
                                "all"
                                if axis == "vocal_instrumental"
                                else f"s{prompt_index % 3}"
                            ),
                        }
                    )
    write_jsonl(outcome_rows, outcome_values)
    write_json(statistics, statistics_value)

    config = load_json(ROOT / "configs" / "stage1_outcome_gates_v2.json")
    config["status"] = "FROZEN"
    config["decision_id"] = decision_id
    config["thresholds"] = {
        "baseline_failure_rate_minimum": baseline_minimum,
        "mixed_outcome_prompt_share_minimum": mixed_minimum,
    }
    config["bindings"] = {
        "outcome_rows": {
            "path": str(outcome_rows.resolve()),
            "sha256": sha256_file(outcome_rows),
        },
        "state_queues": queue_bindings,
        "statistics_config": {
            "path": str(statistics.resolve()),
            "sha256": sha256_file(statistics),
        },
    }
    config_path = tmp_path / "configs" / "stage1_outcome_gates_v2.json"
    write_json(config_path, config)

    rows = compute_gate_results(
        outcome_values,
        statistics_value,
        load_gate_policy(config_path),
    )
    cancellations = plan_cancellations(rows, queue_bindings)
    stage1_root = tmp_path / "stage1"
    write_stage1_artifacts(
        stage1_root,
        results=rows,
        cancellations=cancellations,
        provenance={
            "config_path": str(config_path.resolve()),
            "config_sha256": sha256_file(config_path),
            "outcome_rows_path": str(outcome_rows.resolve()),
            "outcome_rows_sha256": sha256_file(outcome_rows),
            "statistics_config_path": str(statistics.resolve()),
            "statistics_config_sha256": sha256_file(statistics),
        },
    )
    return (
        stage1_root / "stage1-outcome-gates.json",
        stage1_root / "cancellations" / "summary.json",
        config_path,
    )


def rewrite_immutable_json(path: Path, value: Any) -> None:
    path.chmod(0o644)
    write_json(path, value)
    path.chmod(0o444)


__all__ = [
    "build_terminal",
    "queue_binding",
    "rewrite_immutable_json",
    "write_jsonl",
]

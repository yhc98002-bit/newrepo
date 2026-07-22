"""No-clobber runner for the prospectively opened initial eligibility analysis."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eligibility.analysis import analyze_initial_cell
from eligibility.contract import AnalysisConfig, load_bound_initial_input
from scoring.common import canonical_json, sha256_file


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)
    _fsync_directory(path.parent)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)
    _fsync_directory(path.parent)


def _write_text(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)
    _fsync_directory(path.parent)


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _markdown(result: Mapping[str, Any]) -> str:
    policy = result["overall_policy"]
    incremental = policy["state_incremental_value"]
    deviation = policy["cross_fitted_deviation_share"]
    lines = [
        "# Initial state-information eligibility result",
        "",
        "> AUTOMATIC-INSTRUMENT OUTCOMES — no human-gold or evaluator-accuracy claim.",
        "",
        f"- Backbone: `{result['backbone']}`",
        f"- Axis: `{result['axis']}`",
        f"- Gate: **{result['four_way_gate']}**",
        f"- State incremental value: `{incremental['point']:.8f}`",
        f"- One-sided 95% lower bound: `{incremental['one_sided_95_lower']:.8f}`",
        (
            "- Two-sided 95% interval: "
            f"`[{incremental['two_sided_95'][0]:.8f}, "
            f"{incremental['two_sided_95'][1]:.8f}]`"
        ),
        f"- Cross-fitted deviation share: `{deviation['point']:.8f}`",
        f"- Supplemental status: `{result['supplemental']['status']}`",
        "",
        "## Checkpoint curves",
        "",
        "| checkpoint | legibility bits | commitment | deviation | incremental value |",
        "|---:|---:|---:|---:|---:|",
    ]
    for curve in result["curves"]:
        checkpoint = curve["checkpoint_fraction"]
        predictive = curve["predictive"]
        checkpoint_policy = curve["policy"]
        lines.append(
            "| "
            f"{checkpoint:.2f} | {predictive['legibility_bits']['point']:.8f} | "
            f"{checkpoint_policy['outcome_commitment']['point']:.8f} | "
            f"{checkpoint_policy['cross_fitted_deviation_share']['point']:.8f} | "
            f"{checkpoint_policy['state_incremental_value']['point']:.8f} |"
        )
    lines.extend(
        [
            "",
            "The full machine-readable file contains OOF log loss, Brier score, ",
            "calibration summaries, paired 10,000-prompt-bootstrap intervals, fit diagnostics, ",
            "and selected-action counts. Invalid files were retained as failures.",
            "",
        ]
    )
    return "\n".join(lines)


def run_initial_analysis(
    *,
    config: AnalysisConfig,
    opening_receipt: Mapping[str, str],
    input_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Read outcomes only now, after the caller has verified the push gate."""

    bound = load_bound_initial_input(input_manifest_path, config=config)
    result, oof_rows = analyze_initial_cell(bound, config=config)
    result["git_commit"] = _git_head(config.repo_root)
    result["prospective_opening"] = dict(opening_receipt)
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    _fsync_directory(output.parent)
    result_path = output / "eligibility-analysis.json"
    oof_path = output / "oof-action-probabilities.jsonl"
    report_path = output / "ELIGIBILITY_ANALYSIS.md"
    _write_json(result_path, result)
    _write_jsonl(oof_path, oof_rows)
    _write_text(report_path, _markdown(result))
    manifest = {
        "analysis_config_sha256": config.sha256,
        "artifacts": {
            "markdown": {"path": str(report_path), "sha256": sha256_file(report_path)},
            "oof_rows": {
                "path": str(oof_path),
                "row_count": len(oof_rows),
                "sha256": sha256_file(oof_path),
            },
            "result": {"path": str(result_path), "sha256": sha256_file(result_path)},
        },
        "automatic_instrument_outcomes": True,
        "four_way_gate": result["four_way_gate"],
        "human_gold_claims": False,
        "input_manifest_sha256": bound.manifest_sha256,
        "schema_version": 1,
        "status": "ELIGIBILITY_INITIAL_ANALYSIS_COMPLETE",
        "supplemental": result["supplemental"],
        "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
    }
    manifest_path = output / "analysis-manifest.json"
    _write_json(manifest_path, manifest)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
    }

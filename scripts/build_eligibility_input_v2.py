#!/usr/bin/env python3
"""Assemble frozen-instrument eligibility input after the prospective push gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eligibility.builder import build_initial_input_package
from eligibility.contract import load_analysis_config, validate_prospective_opening


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--automatic-outcomes", type=Path, required=True)
    parser.add_argument("--axis", required=True)
    parser.add_argument("--backbone", required=True)
    parser.add_argument("--cancellation-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--measured-costs", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preview-features", type=Path, required=True)
    parser.add_argument("--queue-manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--survivor-manifest", type=Path, required=True)
    args = parser.parse_args()

    config = load_analysis_config(args.config, repo_root=args.repo_root)
    # No preview, outcome, cost, queue, or Stage-1 artifact is opened before
    # this proof succeeds.
    validate_prospective_opening(
        config,
        decisions_path=args.decisions,
        decision_id=args.decision_id,
    )
    result = build_initial_input_package(
        config=config,
        backbone=args.backbone,
        model_id=args.model_id,
        axis=args.axis,
        queue_manifest_path=args.queue_manifest,
        survivor_manifest_path=args.survivor_manifest,
        cancellation_manifest_path=args.cancellation_manifest,
        preview_features_path=args.preview_features,
        automatic_outcomes_path=args.automatic_outcomes,
        measured_costs_path=args.measured_costs,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

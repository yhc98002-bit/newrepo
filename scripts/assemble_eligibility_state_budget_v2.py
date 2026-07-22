#!/usr/bin/env python3
"""Assemble outcome-blind eligibility time budgets after the pushed opening."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eligibility.state_budget import (
    assemble_state_budget,
    publish_state_budget,
    validate_state_budget_opening,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-config", type=Path, required=True)
    parser.add_argument("--analysis-decision-id", required=True)
    parser.add_argument("--axis", required=True)
    parser.add_argument("--backbone", required=True)
    parser.add_argument("--budget-config", type=Path, required=True)
    parser.add_argument("--budget-decision-id", required=True)
    parser.add_argument("--cancellation-manifest", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--queue-manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--survivor-manifest", type=Path, required=True)
    args = parser.parse_args()

    config, _analysis = validate_state_budget_opening(
        args.budget_config,
        args.analysis_config,
        repo_root=args.repo_root,
        decisions_path=args.decisions,
        analysis_decision_id=args.analysis_decision_id,
        budget_decision_id=args.budget_decision_id,
    )
    # No queue, core receipt, ledger, or other experimental input is opened
    # until both remote opening proofs above have passed.
    result = assemble_state_budget(
        backbone=args.backbone,
        axis=args.axis,
        queue_manifest_path=args.queue_manifest,
        survivor_manifest_path=args.survivor_manifest,
        cancellation_manifest_path=args.cancellation_manifest,
    )
    published = publish_state_budget(
        result,
        config_path=args.budget_config,
        schema_path=args.repo_root / config["budget_package_schema"]["path"],
        output_dir=args.output_dir,
    )
    print(json.dumps(published, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run one frozen initial eligibility cell after its separate push gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eligibility.contract import load_analysis_config, validate_prospective_opening
from eligibility.runner import run_initial_analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()

    # These are the only reads allowed before the opening gate.  In particular,
    # input-manifest is kept as an unresolved argparse value until after proof.
    config = load_analysis_config(args.config, repo_root=args.repo_root)
    opening = validate_prospective_opening(
        config,
        decisions_path=args.decisions,
        decision_id=args.decision_id,
    )
    result = run_initial_analysis(
        config=config,
        opening_receipt=opening,
        input_manifest_path=args.input_manifest,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

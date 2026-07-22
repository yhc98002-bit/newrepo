#!/usr/bin/env python3
"""Run the CPU-only Stage-1 gate after, and only after, threshold freeze."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SRC = REPOSITORY / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scoring.common import load_json, load_jsonl, sha256_file  # noqa: E402
from stage1.gates import (  # noqa: E402
    compute_gate_results,
    load_gate_policy,
    plan_cancellations,
    plan_survivors,
    validated_bindings,
    verify_policy_decision,
    write_stage1_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "stage1_outcome_gates_v2.json",
    )
    parser.add_argument("--decisions", type=Path, default=REPOSITORY / "DECISIONS.md")
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def run(config_path: Path, output_root: Path, *, decisions_path: Path) -> None:
    """Run only after policy validation; this ordering is governance-critical."""

    # This validation intentionally precedes every read of scored rows and queues.
    policy = load_gate_policy(config_path)
    decision_binding = verify_policy_decision(
        config_path, decisions_path, policy=policy
    )
    bindings = validated_bindings(config_path)
    outcomes_path = Path(bindings["outcome_rows"]["path"])
    statistics_path = Path(bindings["statistics_config"]["path"])
    rows = load_jsonl(outcomes_path)
    statistics = load_json(statistics_path)
    results = compute_gate_results(rows, statistics, policy)
    cancellations = plan_cancellations(results, bindings["state_queues"])
    survivors = plan_survivors(results, bindings["state_queues"])
    write_stage1_artifacts(
        output_root,
        results=results,
        cancellations=cancellations,
        survivors=survivors,
        queue_bindings=bindings["state_queues"],
        provenance={
            "config_path": str(config_path.resolve()),
            "config_sha256": sha256_file(config_path),
            "outcome_rows_path": str(outcomes_path.resolve()),
            "outcome_rows_sha256": sha256_file(outcomes_path),
            "statistics_config_path": str(statistics_path.resolve()),
            "statistics_config_sha256": sha256_file(statistics_path),
            "policy_decision_block_sha256": decision_binding["decision_block_sha256"],
            "policy_decision_id": decision_binding["decision_id"],
            "policy_decisions_path": decision_binding["decisions_path"],
        },
    )


def main() -> int:
    args = parse_args()
    run(args.config, args.output_root, decisions_path=args.decisions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

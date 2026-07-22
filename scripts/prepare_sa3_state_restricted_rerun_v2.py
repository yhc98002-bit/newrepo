#!/usr/bin/env python3
"""Prepare one D-0035/D-0045 SA3 survivor-only attempt; make no model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def main() -> int:
    from state_capture.sa3_restricted_rerun import prepare_restricted_rerun

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "sa3_state_restricted_rerun_v2.json",
    )
    parser.add_argument("--decision-id", default="D-0035")
    parser.add_argument("--decisions", type=Path, default=REPOSITORY / "DECISIONS.md")
    parser.add_argument("--run-id")
    parser.add_argument("--attempt-claim-path", type=Path)
    parser.add_argument("--physical-gpu-id", action="append", type=int)
    parser.add_argument("--predecessor-failure", type=Path)
    args = parser.parse_args()
    result = prepare_restricted_rerun(
        args.config,
        decisions_path=args.decisions,
        decision_id=args.decision_id,
        repo_root=REPOSITORY,
        run_id=args.run_id,
        attempt_claim_path=args.attempt_claim_path,
        physical_gpu_ids=tuple(args.physical_gpu_id or (4, 5, 6, 7)),
        predecessor_failure_path=args.predecessor_failure,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare the D-0030-authorized SA3 initial state queue; make no model calls."""

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
    from state_capture.sa3_launcher import prepare_state_run

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "sa3_state_capture_v2.json",
    )
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--decisions", type=Path, default=REPOSITORY / "DECISIONS.md")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = prepare_state_run(
        args.config,
        run_id=args.run_id,
        decisions_path=args.decisions,
        decision_id=args.decision_id,
        repo_root=REPOSITORY,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

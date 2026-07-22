#!/usr/bin/env python3
"""Materialize the identity-only SA3 completed-exclusion/remaining package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from state_capture.sa3_remaining_repair import (  # noqa: E402
    materialize_remaining_repair_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "sa3_state_restricted_rerun_v2.json",
    )
    parser.add_argument("--predecessor-run-dir", type=Path, required=True)
    parser.add_argument("--predecessor-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = materialize_remaining_repair_package(
        args.config,
        repo_root=REPOSITORY,
        predecessor_run_dir=args.predecessor_run_dir,
        predecessor_run_id=args.predecessor_run_id,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

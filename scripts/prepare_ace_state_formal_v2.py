#!/usr/bin/env python3
"""Prepare the D-0036 ACE survivor-only formal run; make zero model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from state_capture.ace_formal_launcher import prepare_formal_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "ace_state_formal_v2.json",
    )
    parser.add_argument("--decisions", type=Path, default=REPOSITORY / "DECISIONS.md")
    args = parser.parse_args()
    result = prepare_formal_run(
        args.config,
        decisions_path=args.decisions,
        repo_root=REPOSITORY,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

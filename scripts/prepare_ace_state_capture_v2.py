#!/usr/bin/env python3
"""Materialize the D-0033-bound ACE initial state queue; never run a model."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def _head_commit() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def main() -> int:
    from state_capture.ace_queue import prepare_opened_queue_package

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY / "configs" / "ace_state_capture_v2.json",
    )
    parser.add_argument(
        "--decisions", type=Path, default=REPOSITORY / "DECISIONS.md"
    )
    parser.add_argument("--decision-id", default="D-0033")
    parser.add_argument("--preflight-terminal", type=Path, required=True)
    parser.add_argument("--preflight-terminal-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--git-commit", default=None)
    args = parser.parse_args()
    result = prepare_opened_queue_package(
        args.config,
        repo_root=REPOSITORY,
        decisions_path=args.decisions,
        decision_id=args.decision_id,
        preflight_terminal_path=args.preflight_terminal,
        preflight_terminal_sha256=args.preflight_terminal_sha256,
        output_dir=args.output_dir,
        git_commit=args.git_commit or _head_commit(),
    )
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

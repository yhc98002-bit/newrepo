#!/usr/bin/env python3
"""Acquire one exact Stable Audio Open snapshot; performs no generation."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbones.sao_acquisition import acquire_snapshot  # noqa: E402


def _git_state() -> str:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    ).strip()
    if head != origin or branch != "main" or dirty:
        raise RuntimeError("SAO acquisition requires clean local main equal to origin/main")
    return head


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, default=ROOT / "DECISIONS.md")
    parser.add_argument("--accepted-by", required=True)
    parser.add_argument("--accepted-at-utc", required=True)
    parser.add_argument("--execute-ack", required=True)
    args = parser.parse_args()
    result = acquire_snapshot(
        args.config,
        args.decisions,
        execute_ack=args.execute_ack,
        accepted_by=args.accepted_by,
        accepted_at_utc=args.accepted_at_utc,
        command=" ".join(shlex.quote(value) for value in sys.argv),
        git_commit=_git_state(),
    )
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

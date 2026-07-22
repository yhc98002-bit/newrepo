#!/usr/bin/env python3
"""Finalize the authorized retained SAO snapshot without external access."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbones.sao_acquisition import (  # noqa: E402
    finalize_retained_acquisition_recovery,
)

TOKEN_ENVIRONMENT_VARIABLES = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)


def _git_state(environment: Mapping[str, str] | None = None) -> str:
    inherited = dict(os.environ if environment is None else environment)
    if any(name in inherited for name in TOKEN_ENVIRONMENT_VARIABLES):
        raise RuntimeError("SAO recovery refuses an environment containing provider tokens")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, env=inherited, text=True
    ).strip()
    origin = subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, env=inherited, text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, env=inherited, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, env=inherited, text=True
    ).strip()
    if head != origin or branch != "main" or dirty:
        raise RuntimeError("SAO recovery requires clean local main equal to origin/main")
    return head


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "sao_live_v2.json",
    )
    parser.add_argument("--decisions", type=Path, default=ROOT / "DECISIONS.md")
    args = parser.parse_args()
    result = finalize_retained_acquisition_recovery(
        args.config,
        args.decisions,
        command=" ".join(shlex.quote(value) for value in sys.argv),
        git_commit=_git_state(),
    )
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

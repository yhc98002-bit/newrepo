#!/usr/bin/env python3
"""Dry-run or execute the sole ACE-Step v1 state-preflight attempt.

The default mode is read-only.  Production execution is accepted only through
the GNU-timeout wrapper, with a completed external authorization and the exact
one-attempt phrase.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from state_capture.ace_contract import EXECUTE_PHRASE, RUN_ID  # noqa: E402
from state_capture.ace_runner import (  # noqa: E402
    AuthorizedAttemptFailed,
    execute_authorized_preflight,
    run_dry_preflight,
)

DEFAULT_CONFIG = REPOSITORY_ROOT / "configs/ace_state_preflight_v2.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--run-id", choices=[RUN_ID])
    parser.add_argument("--execute")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    production_requested = any(
        value is not None
        for value in (arguments.authorization, arguments.run_id, arguments.execute)
    )
    if arguments.dry_run and production_requested:
        raise SystemExit("--dry-run cannot be combined with production arguments")
    if not production_requested:
        result = run_dry_preflight(
            config_path=arguments.config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
        return 0
    if (
        arguments.authorization is None
        or arguments.run_id != RUN_ID
        or arguments.execute != EXECUTE_PHRASE
    ):
        raise SystemExit(
            "production requires --authorization, the fixed --run-id, and exact --execute phrase"
        )
    try:
        terminal = execute_authorized_preflight(
            config_path=arguments.config,
            authorization_path=arguments.authorization,
            execute_phrase=arguments.execute,
            repository_root=REPOSITORY_ROOT,
        )
    except AuthorizedAttemptFailed as exc:
        print(json.dumps(exc.terminal, allow_nan=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(terminal, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Frozen outer GNU-timeout boundary for the ACE B2 mini-smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "b2_mini_smoke_v2.json"
RUNNER_PATH = REPOSITORY_ROOT / "scripts" / "run_b2_mini_smoke_v2.py"
WRAPPER_PATH = Path(__file__).resolve()
PYTHON_PATH = Path("/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python")
TIMEOUT_PATH = Path("/usr/bin/timeout")
PYCACHE_PREFIX = Path("/tmp/pxy1289-b2-mini-smoke-v2-disabled-pycache")
FIXED_RUN_ID = "b2-ace-v1-mini-smoke-v2-001"
EXECUTE_PHRASE = "I_UNDERSTAND_THIS_MAKES_EXACTLY_TWO_NON_BENCHMARK_MODEL_CALLS"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _terminal_refusal(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "run_id": FIXED_RUN_ID,
        "status": "REFUSED_PREFLIGHT",
        "MEASUREMENT_STATUS": "NOT_MEASURED_NO_MODEL_CALL",
        "MEASUREMENT_SCOPE": "B2_MINI_SMOKE_NON_BENCHMARK",
        "benchmark_endpoint": False,
        "model_call_count": 0,
        "generated_output_count": 0,
        "finished_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error_type": type(error).__name__,
        "error": str(error),
        "global_claim_consumed": False,
        "retry_count": 0,
        "no_retry": True,
    }


def build_commands(
    *,
    config_path: Path,
    authorization_path: Path,
    run_id: str,
    execute_phrase: str,
) -> tuple[list[str], list[str]]:
    """Return the exact recorded wrapper and GNU-timeout argv vectors."""

    if Path(sys.executable).resolve(strict=True) != PYTHON_PATH.resolve(strict=True):
        raise RuntimeError(f"wrapper must run with {PYTHON_PATH}")
    if config_path.resolve(strict=True) != CONFIG_PATH.resolve(strict=True):
        raise RuntimeError(f"production config must be exactly {CONFIG_PATH}")
    authorization = authorization_path.resolve(strict=True)
    if run_id != FIXED_RUN_ID or execute_phrase != EXECUTE_PHRASE:
        raise RuntimeError("fixed run ID or execute phrase changed")
    if not TIMEOUT_PATH.is_file():
        raise RuntimeError(f"GNU timeout executable is absent: {TIMEOUT_PATH}")
    if os.path.lexists(PYCACHE_PREFIX):
        raise RuntimeError(f"alternate pycache prefix must be absent: {PYCACHE_PREFIX}")

    forwarded = [
        "--config",
        str(CONFIG_PATH),
        "--authorization",
        str(authorization),
        "--run-id",
        FIXED_RUN_ID,
        "--execute",
        EXECUTE_PHRASE,
    ]
    production = [str(PYTHON_PATH), str(WRAPPER_PATH), *forwarded]
    timeout = [
        str(TIMEOUT_PATH),
        "-k",
        "30s",
        "1800s",
        str(PYTHON_PATH),
        "-B",
        "-X",
        f"pycache_prefix={PYCACHE_PREFIX}",
        str(RUNNER_PATH),
        *forwarded,
    ]
    return production, timeout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--run-id", choices=[FIXED_RUN_ID], required=True)
    parser.add_argument("--execute", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        production, timeout = build_commands(
            config_path=args.config,
            authorization_path=args.authorization,
            run_id=args.run_id,
            execute_phrase=args.execute,
        )
        version = subprocess.run(
            [str(TIMEOUT_PATH), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if not version or "GNU coreutils" not in version[0]:
            raise RuntimeError("/usr/bin/timeout is not GNU coreutils timeout")
        environment = dict(os.environ)
        environment.update(
            {
                "B2_PRODUCTION_WRAPPER_PATH": str(WRAPPER_PATH),
                "B2_PRODUCTION_WRAPPER_SHA256": _sha256_file(WRAPPER_PATH),
                "B2_OUTER_PRODUCTION_COMMAND_JSON": json.dumps(production, separators=(",", ":")),
                "B2_OUTER_TIMEOUT_COMMAND_JSON": json.dumps(timeout, separators=(",", ":")),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPYCACHEPREFIX": str(PYCACHE_PREFIX),
            }
        )
        os.execve(str(TIMEOUT_PATH), timeout, environment)
    except Exception as exc:
        print(json.dumps(_terminal_refusal(exc), allow_nan=False, sort_keys=True), file=sys.stderr)
        return 2
    raise AssertionError("os.execve unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())

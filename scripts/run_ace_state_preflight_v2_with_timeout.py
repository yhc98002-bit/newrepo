#!/usr/bin/env python3
"""Frozen 600-second GNU-timeout boundary for the ACE state preflight."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from state_capture.ace_artifacts import (  # noqa: E402
    HashChainedLedger,
    OneShotAttemptStore,
    sha256_file,
    validate_ledger,
)
from state_capture.ace_contract import (  # noqa: E402
    EXECUTE_PHRASE,
    OUTER_KILL_GRACE_SECONDS,
    OUTER_SOFT_TIMEOUT_SECONDS,
    RUN_ID,
    validate_static_config,
)

CONFIG_PATH = REPOSITORY_ROOT / "configs/ace_state_preflight_v2.json"
RUNNER_PATH = REPOSITORY_ROOT / "scripts/run_ace_state_preflight_v2.py"
WRAPPER_PATH = Path(__file__).resolve()
PYTHON_PATH = Path("/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python")
TIMEOUT_PATH = Path("/usr/bin/timeout")
PYCACHE_PREFIX = Path("/tmp/pxy1289-ace-state-preflight-v2-disabled-pycache")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--run-id", choices=[RUN_ID], required=True)
    parser.add_argument("--execute", required=True)
    return parser


def build_timeout_command(
    *,
    config_path: Path,
    authorization_path: Path,
    run_id: str,
    execute_phrase: str,
) -> list[str]:
    if Path(sys.executable).resolve(strict=True) != PYTHON_PATH.resolve(strict=True):
        raise RuntimeError(f"wrapper must run with {PYTHON_PATH}")
    if config_path.resolve(strict=True) != CONFIG_PATH.resolve(strict=True):
        raise RuntimeError(f"production config must be exactly {CONFIG_PATH}")
    if run_id != RUN_ID or execute_phrase != EXECUTE_PHRASE:
        raise RuntimeError("fixed run ID or execute phrase changed")
    if not TIMEOUT_PATH.is_file():
        raise RuntimeError("/usr/bin/timeout is absent")
    if os.path.lexists(PYCACHE_PREFIX):
        raise RuntimeError(f"alternate pycache prefix must be absent: {PYCACHE_PREFIX}")
    return [
        str(TIMEOUT_PATH),
        "-k",
        f"{OUTER_KILL_GRACE_SECONDS}s",
        f"{OUTER_SOFT_TIMEOUT_SECONDS}s",
        str(PYTHON_PATH),
        "-B",
        "-X",
        f"pycache_prefix={PYCACHE_PREFIX}",
        str(RUNNER_PATH),
        "--config",
        str(CONFIG_PATH),
        "--authorization",
        str(authorization_path.resolve(strict=True)),
        "--run-id",
        RUN_ID,
        "--execute",
        EXECUTE_PHRASE,
    ]


def _terminalize_interrupted_attempt(error: MappingLike, contract: Any) -> dict[str, Any] | None:
    run = contract.raw["run"]
    store = OneShotAttemptStore(
        run["claim_root"],
        claim_filename=run["attempt_claim_filename"],
        repository_root=REPOSITORY_ROOT,
    )
    if store.terminal_path.exists():
        return json.loads(store.terminal_path.read_text(encoding="utf-8"))
    if not store.claim_path.is_file():
        return None
    ledger_path = Path(run["run_root"]) / RUN_ID / "ledger.jsonl"
    if ledger_path.is_file():
        ledger = HashChainedLedger(ledger_path)
        rows = validate_ledger(ledger_path)
        latest = {
            row["call_id"]: row["call_state"]
            for row in rows
            if row.get("event_kind") == "MODEL_CALL_STATE"
        }
        for call_id, state in latest.items():
            if state == "CLAIMED":
                ledger.transition(
                    call_id,
                    "CALL_STARTED",
                    {
                        "outer_boundary_salvage": True,
                        "model_call_may_have_started": True,
                    },
                )
                state = "CALL_STARTED"
            if state == "CALL_STARTED":
                ledger.transition(
                    call_id,
                    "FAILED",
                    {
                        "error_type": "OUTER_TIMEOUT_OR_RUNNER_INTERRUPTION",
                        "outer_boundary_salvage": True,
                    },
                )
    return store.write_terminal(
        status="FAIL",
        claim_sha256=sha256_file(store.claim_path),
        ledger_path=ledger_path if ledger_path.is_file() else None,
        payload={
            "error_type": "OUTER_TIMEOUT_OR_RUNNER_INTERRUPTION",
            "error": dict(error),
            "retry_allowed": False,
            "state_queue_accessed": False,
        },
    )


MappingLike = dict[str, Any]


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        contract = validate_static_config(arguments.config, repository_root=REPOSITORY_ROOT)
        command = build_timeout_command(
            config_path=arguments.config,
            authorization_path=arguments.authorization,
            run_id=arguments.run_id,
            execute_phrase=arguments.execute,
        )
        version = subprocess.run(
            [str(TIMEOUT_PATH), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()
        if not version or "GNU coreutils" not in version[0]:
            raise RuntimeError("/usr/bin/timeout is not GNU coreutils timeout")
        authorization = json.loads(arguments.authorization.resolve(strict=True).read_text("utf-8"))
        physical_gpu_id = authorization.get("placement", {}).get("physical_gpu_id")
        if (
            isinstance(physical_gpu_id, bool)
            or physical_gpu_id not in contract.raw["placement"]["candidate_physical_gpu_ids"]
        ):
            raise RuntimeError("authorization does not name one prioritized GPU in 4..7")
        environment = dict(os.environ)
        environment.update(
            {
                "ACE_STATE_PREFLIGHT_WRAPPER_SHA256": sha256_file(WRAPPER_PATH),
                "CUDA_VISIBLE_DEVICES": str(physical_gpu_id),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPYCACHEPREFIX": str(PYCACHE_PREFIX),
            }
        )
        python_path = [str(SOURCE_ROOT)]
        if environment.get("PYTHONPATH"):
            python_path.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(python_path)
        process = subprocess.run(command, text=True, env=environment, cwd=REPOSITORY_ROOT)
        if process.returncode == 0:
            return 0
        terminal = _terminalize_interrupted_attempt(
            {
                "timeout_command": command,
                "returncode": process.returncode,
                "timeout_exit": process.returncode in {124, 137},
            },
            contract,
        )
        if terminal is not None:
            print(json.dumps(terminal, allow_nan=False, indent=2, sort_keys=True), file=sys.stderr)
        return process.returncode if 0 < process.returncode < 126 else 1
    except Exception as exc:
        refusal = {
            "schema_version": 1,
            "status": "REFUSED_BEFORE_TIMEOUT_BOUNDARY",
            "run_id": RUN_ID,
            "model_call_count": 0,
            "generated_output_count": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "retry_consumed_by_this_refusal": False,
        }
        print(json.dumps(refusal, allow_nan=False, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Separate-interpreter ACE checkpoint continuation entry point."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from state_capture.ace_artifacts import sha256_file, write_json_exclusive
from state_capture.ace_contract import json_sha256, load_json_object
from state_capture.ace_engine import resolve_engine_factory, validate_engine_result

RESUME_CHILD_REQUEST_FORMAT = "ace-step-v1-resume-child-request-v2"
RESUME_CHILD_RESULT_FORMAT = "ace-step-v1-resume-child-result-v2"


class AceChildError(RuntimeError):
    """The immutable child request or separate-process execution is invalid."""


def validate_child_request(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve(strict=True)
    request = load_json_object(source)
    if request.get("format") != RESUME_CHILD_REQUEST_FORMAT:
        raise AceChildError("unsupported ACE resume-child request format")
    required = {
        "format",
        "request_id",
        "parent_pid",
        "engine_factory",
        "engine_context",
        "engine_context_sha256",
        "checkpoint_path",
        "checkpoint_sha256",
        "checkpoint_state_metadata_sha256",
        "output_path",
        "result_path",
        "reference_request",
        "config_sha256",
        "request_identity_sha256",
    }
    if set(request) != required:
        raise AceChildError(
            f"resume-child request schema mismatch: missing={sorted(required-set(request))}, "
            f"extra={sorted(set(request)-required)}"
        )
    claimed = request["request_identity_sha256"]
    unhashed = dict(request)
    unhashed.pop("request_identity_sha256")
    if claimed != json_sha256(unhashed):
        raise AceChildError("resume-child request identity hash changed")
    if request["engine_context_sha256"] != json_sha256(request["engine_context"]):
        raise AceChildError("resume-child engine context identity changed")
    parent_pid = request["parent_pid"]
    if isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 0:
        raise AceChildError("resume-child parent PID is invalid")
    checkpoint = Path(request["checkpoint_path"]).resolve(strict=True)
    if sha256_file(checkpoint) != request["checkpoint_sha256"]:
        raise AceChildError("resume-child checkpoint SHA-256 changed")
    sidecar = checkpoint.with_name(f"{checkpoint.name}.state.json")
    if sha256_file(sidecar) != request["checkpoint_state_metadata_sha256"]:
        raise AceChildError("resume-child checkpoint metadata SHA-256 changed")
    for key in ("output_path", "result_path"):
        destination = Path(request[key])
        if destination.exists():
            raise AceChildError(f"resume-child destination already exists: {destination}")
    return request


def execute_request(path: str | Path) -> dict[str, Any]:
    """Execute one continuation and publish one immutable child result."""

    source = Path(path).resolve(strict=True)
    request = validate_child_request(source)
    if os.getpid() == request["parent_pid"]:
        raise AceChildError("resume must run in a process distinct from its parent")
    factory = resolve_engine_factory(request["engine_factory"])
    engine = factory(request["engine_context"])
    try:
        engine_result = validate_engine_result(
            engine.run_resume(
                request=request,
                checkpoint_path=Path(request["checkpoint_path"]),
                output_path=Path(request["output_path"]),
            ),
            mode="RESUME",
        )
    finally:
        engine.close()
    if engine_result.get("pid") != os.getpid():
        raise AceChildError("engine result PID differs from the child interpreter")
    result: dict[str, Any] = {
        "format": RESUME_CHILD_RESULT_FORMAT,
        "status": "PASS",
        "request_path": str(source),
        "request_sha256": sha256_file(source),
        "request_identity_sha256": request["request_identity_sha256"],
        "parent_pid": request["parent_pid"],
        "child_pid": os.getpid(),
        "os_parent_pid": os.getppid(),
        "checkpoint_path": request["checkpoint_path"],
        "checkpoint_sha256": request["checkpoint_sha256"],
        "engine_result": engine_result,
    }
    result["result_identity_sha256"] = json_sha256(result)
    result_path = Path(request["result_path"])
    write_json_exclusive(result_path, result)
    return {
        **result,
        "result_path": str(result_path.resolve()),
        "result_sha256": sha256_file(result_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    result = execute_request(arguments.request)
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

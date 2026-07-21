#!/usr/bin/env python3
"""Read-only plan and external-authorization preparation for ACE state preflight.

This helper never launches ACE.  Its default action prints the exact paths and
commands.  Optional template/seal writes use exclusive creation outside the
repository and still do not consume the one attempt.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from state_capture.ace_artifacts import safe_external_path, write_json_exclusive  # noqa: E402
from state_capture.ace_contract import (  # noqa: E402
    ATTEMPT_ID,
    AUTHORIZATION_ID,
    EXECUTE_PHRASE,
    RUN_ID,
    SCOPE,
    authorization_token_identity,
    capture_git_evidence,
    json_sha256,
    load_json_object,
    sha256_file,
    validate_static_config,
)
from state_capture.ace_runner import package_hashes  # noqa: E402

CONFIG_PATH = REPOSITORY_ROOT / "configs/ace_state_preflight_v2.json"
PYTHON_PATH = Path("/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python")
SOURCE_PATH = Path("/XYFS02/HDD_POOL/paratera_xy/pxy1289/source/ACE-Step")
CHECKPOINT_PATH = Path(
    "/HOME/paratera_xy/pxy1289/.cache/modelscope/hub/models/ACE-Step/ACE-Step-v1-3___5B"
)
AUTHORIZATION_ROOT = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "authorizations/ace-state-preflight-v2"
)
DEFAULT_DRAFT = AUTHORIZATION_ROOT / f"{RUN_ID}.authorization.draft.json"
DEFAULT_AUTHORIZATION = AUTHORIZATION_ROOT / f"{RUN_ID}.authorization.json"


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("<FILL_") or value == "PENDING"
    if isinstance(value, Mapping):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def build_template(contract: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "authorization_id": AUTHORIZATION_ID,
        "scope": SCOPE,
        "execution_authorized": False,
        "authorized_at_utc": "<FILL_UTC_AT_OR_AFTER_POSTFREEZE_DECISION>",
        "expires_at_utc": "<FILL_UTC_NO_MORE_THAN_24_HOURS_LATER>",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "config_sha256": contract.sha256,
        "git_commit": capture_git_evidence(REPOSITORY_ROOT)["head"],
        "engine_factory": contract.raw["engine"]["production_factory"],
        "caps": dict(contract.raw["caps"]),
        "reference_request": dict(contract.raw["proposed_reference_request"]),
        "package_sha256": package_hashes(REPOSITORY_ROOT),
        "decision": {
            "path": "DECISIONS.md",
            "sha256": "<FILL_POSTFREEZE_DECISIONS_SHA256>",
        },
        "seed_registry": {
            "path": "SEED_REGISTRY.md",
            "sha256": "<FILL_APPEND_ONLY_SEED_REGISTRY_SHA256>",
        },
        "placement": {
            "node": "an12",
            "physical_gpu_id": 4,
            "logical_gpu_id": 0,
            "tensor_parallel_width": 1,
            "replica_count": 1,
            "placement_justification": (
                "First live-safe device in the frozen an12 priority order [4,5,6,7]; "
                "TP1 fits 3.5B and the shared core lock plus live idle/headroom probes "
                "protect all neighbors without preemption."
            ),
        },
        "attempt_token_sha256": "<FILL_BY_THIS_HELPERS_SEAL_DRAFT_MODE>",
    }


def build_plan(contract: Any) -> dict[str, Any]:
    run = contract.raw["run"]
    claim_root = Path(run["claim_root"])
    run_dir = Path(run["run_root"]) / RUN_ID
    dry_command = [
        str(PYTHON_PATH),
        str(REPOSITORY_ROOT / "scripts/run_ace_state_preflight_v2.py"),
        "--dry-run",
    ]
    template_command = [
        str(PYTHON_PATH),
        str(Path(__file__).resolve()),
        "--write-template",
        str(DEFAULT_DRAFT),
    ]
    seal_command = [
        str(PYTHON_PATH),
        str(Path(__file__).resolve()),
        "--seal-draft",
        str(DEFAULT_DRAFT),
        "--output",
        str(DEFAULT_AUTHORIZATION),
    ]
    launch_command = [
        str(PYTHON_PATH),
        str(REPOSITORY_ROOT / "scripts/run_ace_state_preflight_v2_with_timeout.py"),
        "--config",
        str(CONFIG_PATH),
        "--authorization",
        str(DEFAULT_AUTHORIZATION),
        "--run-id",
        RUN_ID,
        "--execute",
        EXECUTE_PHRASE,
    ]
    return {
        "schema_version": 1,
        "status": "PREPARED_NOT_AUTHORIZED",
        "model_calls": 0,
        "generated_outputs": 0,
        "writes_performed": False,
        "node_priority": ["an12", "an29"],
        "an12_gpu_priority": [4, 5, 6, 7],
        "forbidden_gpu_ids": [0, 1, 2, 3],
        "selection_rule": (
            "Use the first candidate that passes the shared nonblocking core lock, zero-neighbor, "
            "A800, <=5% utilization, >=60GB pre-load free, and >=20GB post-load reserve checks."
        ),
        "environment": {
            "ACE_STEP_V1_SOURCE_DIR": str(SOURCE_PATH),
            "ACE_STEP_V1_CHECKPOINT_DIR": str(CHECKPOINT_PATH),
        },
        "commands": {
            "read_only_dry_run": dry_command,
            "create_external_inert_template": template_command,
            "seal_completed_external_draft": seal_command,
            "sole_production_launch_after_all_gates": launch_command,
        },
        "expected_paths": {
            "authorization_draft": str(DEFAULT_DRAFT),
            "authorization": str(DEFAULT_AUTHORIZATION),
            "attempt_claim": str(claim_root / run["attempt_claim_filename"]),
            "attempt_terminal": str(
                claim_root / run["attempt_claim_filename"].replace(".claim.json", ".terminal.json")
            ),
            "run_dir": str(run_dir),
            "run_manifest": str(run_dir / "manifest.json"),
            "ledger": str(run_dir / "ledger.jsonl"),
            "heartbeat": str(run_dir / "heartbeat.json"),
            "result": str(run_dir / "result.json"),
        },
        "mandatory_prelaunch_state": [
            "Post-freeze DECISIONS.md authorization assignments are appended and committed.",
            "S-0010 exact non-benchmark seed row is appended to SEED_REGISTRY.md.",
            "main is clean and byte-identical to origin/main.",
            "The completed authorization is outside the repository and valid for <=24 hours.",
            "No attempt claim or terminal path exists.",
            "ACE source/checkpoint environment variables bind the exact local artifacts.",
        ],
        "caps": dict(contract.raw["caps"]),
        "no_retry": True,
        "state_queue_access": "FORBIDDEN",
    }


def _external_destination(path: Path) -> Path:
    parent = safe_external_path(
        path.parent,
        repository_root=REPOSITORY_ROOT,
        name="authorization destination parent",
    )
    return parent / path.name


def seal_draft(draft_path: Path, output_path: Path, contract: Any) -> dict[str, Any]:
    draft = load_json_object(draft_path.resolve(strict=True))
    unfinished = {
        key: value for key, value in draft.items() if key != "attempt_token_sha256"
    }
    if _contains_placeholder(unfinished):
        raise ValueError("authorization draft still contains required placeholders")
    if draft.get("execution_authorized") is not True:
        raise ValueError("authorization draft is not affirmatively authorized")
    if draft.get("config_sha256") != contract.sha256:
        raise ValueError("authorization draft config hash differs from live package")
    if draft.get("package_sha256") != package_hashes(REPOSITORY_ROOT):
        raise ValueError("authorization draft package hashes differ from live package")
    identity = authorization_token_identity(draft, config_sha256=contract.sha256)
    sealed = {**draft, "attempt_token_sha256": json_sha256(identity)}
    destination = _external_destination(output_path)
    write_json_exclusive(destination, sealed)
    return {
        "status": "SEALED_EXTERNAL_AUTHORIZATION_NOT_CONSUMED",
        "path": str(destination.resolve()),
        "sha256": sha256_file(destination),
        "attempt_token_sha256": sealed["attempt_token_sha256"],
        "model_calls": 0,
        "generated_outputs": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write-template", type=Path)
    group.add_argument("--seal-draft", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    contract = validate_static_config(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
    if arguments.write_template is not None:
        if arguments.output is not None:
            raise SystemExit("--output is used only with --seal-draft")
        destination = _external_destination(arguments.write_template)
        write_json_exclusive(destination, build_template(contract))
        result = {
            "status": "INERT_EXTERNAL_TEMPLATE_WRITTEN",
            "path": str(destination.resolve()),
            "sha256": sha256_file(destination),
            "model_calls": 0,
            "generated_outputs": 0,
        }
    elif arguments.seal_draft is not None:
        if arguments.output is None:
            raise SystemExit("--seal-draft requires --output")
        result = seal_draft(arguments.seal_draft, arguments.output, contract)
    else:
        if arguments.output is not None:
            raise SystemExit("--output requires --seal-draft")
        result = build_plan(contract)
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

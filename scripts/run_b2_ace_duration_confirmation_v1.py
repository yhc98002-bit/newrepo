#!/usr/bin/env python3
"""Fail-closed launcher for the sole ACE-Step v1 duration-confirmation call.

Importing this module performs no model construction, CUDA query, filesystem
write, or generation.  The live path requires a post-decision external
authorization and the exact execute phrase.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.run_b2_mini_smoke_v2 import (  # noqa: E402
    B2ExecutionError,
    B2GateError,
    DurableLog,
    _canonical_json,
    _contains_placeholder,
    _git_capture,
    _hostname_node,
    _latest_assignment,
    _parse_utc,
    _source_environment,
    _validate_external_root,
    capture_runtime_environment,
    device_lock,
    elapsed_deadline,
    exclusive_write_json,
    probe_gpu,
    read_json_object,
    sha256_file,
)

DEFAULT_CONFIG = REPOSITORY_ROOT / "configs" / "b2_ace_duration_confirmation_v1.json"
DEFAULT_RUNNER = Path(__file__).resolve()
DEFAULT_WRAPPER = (
    REPOSITORY_ROOT / "scripts" / "run_b2_ace_duration_confirmation_v1_with_timeout.py"
)
AUTHORIZATION_SCOPE = "ACE_STEP_V1_DURATION_CONFIRMATION_NON_BENCHMARK"
AUTHORIZATION_ID = "B2-ACE-V1-DURATION-CONFIRMATION-V1-ONE-SHOT"
FIXED_RUN_ID = "b2-ace-v1-duration-confirmation-v1-001"
EXECUTE_PHRASE = "I_UNDERSTAND_THIS_MAKES_EXACTLY_ONE_ACE_DURATION_CONFIRMATION_MODEL_CALL"
EXPECTED_JOB = {
    "duration_seconds": 30.0,
    "index": 0,
    "lyrics": "",
    "original_b2_call_index": 1,
    "output_relative_path": "audio/confirmation-00.wav",
    "prompt": (
        "A steady instrumental engineering test passage led by acoustic guitar, "
        "warm bass, and hand percussion, with continuous sound and a clean ending."
    ),
    "prompt_id": "b2-mini-smoke-engineering-ace-02",
    "seed": 73193009,
    "seed_id": "S-0009",
}
EXPECTED_CAPS = {
    "exact_generated_outputs": 1,
    "exact_model_calls": 1,
    "max_clip_seconds_requested": 30.0,
    "max_generated_outputs": 1,
    "max_gpu_seconds": 1800.0,
    "max_gpus": 1,
    "max_model_calls": 1,
    "max_retries": 0,
    "shared_b2_generation_ceiling": 10,
}
EXPECTED_AUTHORIZATION_CAPS = {
    "max_clip_seconds_requested": 30.0,
    "max_generated_outputs": 1,
    "max_gpu_seconds": 1800.0,
    "max_gpus": 1,
    "max_model_calls": 1,
    "max_retries": 0,
}
EXPECTED_DURATION_POLICY = {
    "ace_step_v1_tolerance_seconds": 0.25,
    "rule": "abs(decoded_duration_seconds - requested_duration_seconds) <= tolerance_seconds",
    "stable_audio_3_tolerance_seconds": 0.25,
}
EXPECTED_AUDIO_SANITY_POLICY = {
    "duration_tolerance_seconds": 0.25,
    "expected_channels": 2,
    "expected_sample_rate": 48000,
}
PRIOR_RUNTIME_ROOT = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime"
)
PRIOR_RUN_DIR = PRIOR_RUNTIME_ROOT / "runs/b2-mini-smoke-v2/b2-ace-v1-mini-smoke-v2-001"
PRIOR_CALL_CLAIM_DIR = PRIOR_RUNTIME_ROOT / "claims/b2-ace-v1-mini-smoke-v2-001"
EXPECTED_PRIOR_EVIDENCE = {
    "artifacts": {
        "external_authorization": {
            "path": str(
                PRIOR_RUNTIME_ROOT
                / "authorizations/b2-ace-v1-mini-smoke-v2-001.authorization-02.json"
            ),
            "sha256": "504b91ebdee19a2f3203f45a1d6d3079ad12492bea8131db4edbfa969b9c183d",
        },
        "global_claim": {
            "path": str(PRIOR_RUNTIME_ROOT / "claims/b2-ace-v1-mini-smoke-v2-one-shot.claim.json"),
            "sha256": "deb9d1c3bff85f96fe162f624a52e54b3b9cc94f84e620efd58d65152a545084",
        },
        "call_00_claim": {
            "path": str(PRIOR_CALL_CLAIM_DIR / "call-00.claim.json"),
            "sha256": "93fc96218ef13524237f3a67d2313fed6e18e6dd55c9a919cabcc63198ae0123",
        },
        "manifest": {
            "path": str(PRIOR_RUN_DIR / "manifest.json"),
            "sha256": "466b56249594724e0241cf6fe0f447fa71012bac23bd3a63cde4a38cdd8470e2",
        },
        "generation_ledger": {
            "path": str(PRIOR_RUN_DIR / "generation_ledger.jsonl"),
            "sha256": "d6b9aa821f8a4031b370ec267c864a3bbe5d68f8fb8fed26efad4cdc58b9c627",
        },
        "common_result": {
            "path": str(PRIOR_RUN_DIR / "result.json"),
            "sha256": "012a6ebb57c2273cf4cea5d4a678bc4285acc92a20d199d481baceb2fd120f36",
        },
        "terminal_result": {
            "path": str(PRIOR_RUN_DIR / "b2_mini_smoke_result.json"),
            "sha256": "66c4aafd3dc1d7c8da774d539f003fe03c94ae276e248d85386411461a693df0",
        },
        "retained_wav": {
            "path": str(PRIOR_RUN_DIR / "audio/call-00.wav"),
            "sha256": "1a86fb30dceeb03f5da4e0bcb1cbf488aa2fc7490ac1c8297125e451635bd458",
        },
        "retained_wav_provenance": {
            "path": str(PRIOR_RUN_DIR / "audio/call-00.wav.provenance.json"),
            "sha256": "881f09abeb1b4aa103db37125dc3017aa289f6a8b0e6d493b5f15568eaa70f4b",
        },
    },
    "original_run_id": "b2-ace-v1-mini-smoke-v2-001",
    "required_absent_paths": [
        str(PRIOR_CALL_CLAIM_DIR / "call-01.claim.json"),
        str(PRIOR_RUN_DIR / "audio/call-01.wav"),
    ],
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_FROZEN_PATHS = {
    "ace_adapter": "src/backbones/ace_step_v1.py",
    "ace_config": "configs/backbones/ace_step_v1.json",
    "authorization_template": (
        "provenance/b2/b2_ace_duration_confirmation_authorization.template.json"
    ),
    "common_contracts": "src/backbones/contracts.py",
    "common_io": "src/backbones/io.py",
    "common_runtime": "src/backbones/runtime.py",
    "confirmation_protocol": "B2_ACE_DURATION_CONFIRMATION_PROTOCOL_v1.md",
    "confirmation_runner": "scripts/run_b2_ace_duration_confirmation_v1.py",
    "confirmation_wrapper": "scripts/run_b2_ace_duration_confirmation_v1_with_timeout.py",
    "duration_policy": "src/audio_duration_policy.py",
    "duration_quantization_provenance": (
        "provenance/b2/ace_duration_quantization_provenance_v1.json"
    ),
    "duration_readjudication": "provenance/b2/ace_call0_duration_readjudication_v1.json",
    "duration_sanity": "src/backbones/duration_sanity.py",
    "legacy_b2_runner": "scripts/run_b2_mini_smoke_v2.py",
    "sa3_artifacts": "src/sa3_smoke/artifacts.py",
    "sa3_audio": "src/sa3_smoke/audio.py",
    "seed_registry": "SEED_REGISTRY.md",
}


class AuthorizedConfirmationFailure(B2ExecutionError):
    """Failure after external authorization became valid and non-retryable."""


def _repo_record(
    repository_root: Path, record: Mapping[str, Any], field: str, expected_path: str
) -> Path:
    if record.get("path") != expected_path or Path(expected_path).is_absolute():
        raise B2GateError(f"{field}.path changed")
    path = (repository_root / expected_path).resolve(strict=True)
    try:
        path.relative_to(repository_root.resolve(strict=True))
    except ValueError as exc:
        raise B2GateError(f"{field}.path escapes repository") from exc
    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise B2GateError(f"{field}.sha256 must be lowercase SHA-256")
    observed = sha256_file(path)
    if observed != expected_hash:
        raise B2GateError(f"{field} SHA-256 mismatch: {observed} != {expected_hash}")
    return path


def validate_static_config(
    config_path: Path = DEFAULT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the complete inert package without touching CUDA or external state."""

    config = read_json_object(config_path)
    if config.get("schema_version") != 1 or config.get("scope") != AUTHORIZATION_SCOPE:
        raise B2GateError("unexpected confirmation config schema or scope")
    if config.get("protocol_status") != "PREPARED_NOT_AUTHORIZED":
        raise B2GateError("confirmation config must remain PREPARED_NOT_AUTHORIZED")
    if config.get("scoring") != {
        "benchmark_endpoints_scored": False,
        "human_packet_member": False,
        "instrument_evaluation_allowed": False,
    }:
        raise B2GateError("confirmation must remain unscored and outside human packets")
    if config.get("caps") != EXPECTED_CAPS:
        raise B2GateError("one-call confirmation caps changed")
    if config.get("duration_policy") != EXPECTED_DURATION_POLICY:
        raise B2GateError("duration policy changed")
    if config.get("audio_sanity") != EXPECTED_AUDIO_SANITY_POLICY:
        raise B2GateError("ACE audio-sanity policy must remain exactly 48 kHz/stereo/0.25 s")
    jobs = config.get("jobs")
    if jobs != [EXPECTED_JOB]:
        raise B2GateError("exact S-0009 confirmation job changed")
    if "S-0008" in json.dumps(jobs, sort_keys=True):
        raise B2GateError("consumed S-0008 may not enter the confirmation plan")

    authorization = config.get("authorization")
    if not isinstance(authorization, dict):
        raise B2GateError("authorization gate is absent")
    expected_authorization_scalars = {
        "authorization_id": AUTHORIZATION_ID,
        "model_call_authorized_by_this_config_alone": False,
        "required_execute_phrase": EXECUTE_PHRASE,
        "required_prereg_status": "FROZEN_PROSPECTIVE_DESIGN",
        "requires_completed_external_authorization": True,
    }
    if any(
        authorization.get(key) != value for key, value in expected_authorization_scalars.items()
    ):
        raise B2GateError("authorization controls changed")

    frozen = config.get("frozen_sources")
    if not isinstance(frozen, dict) or set(frozen) != set(EXPECTED_FROZEN_PATHS):
        raise B2GateError("frozen source key set is not exact")
    hashes: dict[str, str] = {"confirmation_config": sha256_file(config_path)}
    for name, expected_path in EXPECTED_FROZEN_PATHS.items():
        record = frozen.get(name)
        if not isinstance(record, dict):
            raise B2GateError(f"frozen source {name} is absent")
        path = _repo_record(repository_root, record, f"frozen_sources.{name}", expected_path)
        hashes[name] = sha256_file(path)
    template = authorization.get("template")
    if template != frozen["authorization_template"]:
        raise B2GateError("authorization template binding differs from frozen source")
    backbone = config.get("backbone")
    if not isinstance(backbone, dict) or backbone.get("config") != frozen["ace_config"]:
        raise B2GateError("ACE config binding differs from frozen source")
    if backbone.get("model_id") != "ACE-Step/ACE-Step-v1-3.5B":
        raise B2GateError("ACE model ID changed")
    if backbone.get("required_checkpoint_file_count") != 17:
        raise B2GateError("ACE checkpoint file count changed")

    outer = config.get("outer_timeout")
    if not isinstance(outer, dict) or any(
        outer.get(key) != value
        for key, value in {
            "duration": "1800s",
            "kill_after": "30s",
            "pycache_prefix": "/tmp/pxy1289-b2-ace-duration-confirmation-v1-disabled-pycache",
            "python_executable": "/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python",
            "runner_relative_path": "scripts/run_b2_ace_duration_confirmation_v1.py",
            "timeout_executable": "/usr/bin/timeout",
            "wrapper_relative_path": "scripts/run_b2_ace_duration_confirmation_v1_with_timeout.py",
        }.items()
    ):
        raise B2GateError("outer timeout boundary changed")
    wrapper = repository_root / outer["wrapper_relative_path"]
    if wrapper.resolve(strict=True) != (
        repository_root / EXPECTED_FROZEN_PATHS["confirmation_wrapper"]
    ).resolve(strict=True):
        raise B2GateError("wrapper path changed")
    if not os.access(wrapper, os.X_OK):
        raise B2GateError("production wrapper is not executable")

    run = config.get("run")
    if not isinstance(run, dict) or run.get("fixed_run_id") != FIXED_RUN_ID:
        raise B2GateError("fixed confirmation run ID changed")
    if run.get("authorization_claim_filename") != (
        "b2-ace-v1-duration-confirmation-v1-one-shot.claim.json"
    ):
        raise B2GateError("global claim filename changed")
    if run.get("authorization_attempt_claim_filename") != (
        "b2-ace-v1-duration-confirmation-v1-authorized-attempt.claim.json"
    ):
        raise B2GateError("authorized-attempt claim filename changed")
    if config.get("prior_consumed_evidence") != EXPECTED_PRIOR_EVIDENCE:
        raise B2GateError("prior consumed-evidence binding changed")

    seed_text = (repository_root / "SEED_REGISTRY.md").read_text(encoding="utf-8")
    if not re.search(
        r"(?m)^\|\s*S-0009\s*\|\s*73193009\s*\|\s*B2 ACE-Step v1 mini-smoke job 2,",
        seed_text,
    ):
        raise B2GateError("S-0009 reservation is absent from SEED_REGISTRY.md")
    for source in sorted((repository_root / "prompts" / "v2").rglob("*")):
        if (
            source.is_file()
            and source.suffix.lower() in {".json", ".jsonl", ".md", ".txt"}
            and EXPECTED_JOB["prompt_id"] in source.read_text(encoding="utf-8")
        ):
            raise B2GateError("engineering prompt ID leaked into benchmark prompt pool")
    return config, hashes


def expected_outer_commands(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    authorization_path: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, list[str]]:
    outer = config["outer_timeout"]
    wrapper = repository_root / outer["wrapper_relative_path"]
    runner = repository_root / outer["runner_relative_path"]
    forwarded = [
        "--config",
        str(config_path.resolve(strict=True)),
        "--authorization",
        str(authorization_path.resolve(strict=True)),
        "--run-id",
        FIXED_RUN_ID,
        "--execute",
        EXECUTE_PHRASE,
    ]
    production = [outer["python_executable"], str(wrapper.resolve(strict=True)), *forwarded]
    timeout = [
        outer["timeout_executable"],
        "-k",
        outer["kill_after"],
        outer["duration"],
        outer["python_executable"],
        "-B",
        "-X",
        f"pycache_prefix={outer['pycache_prefix']}",
        str(runner.resolve(strict=True)),
        *forwarded,
    ]
    return {"production_wrapper_command": production, "outer_timeout_command": timeout}


def _json_string_list(value: str | None, field: str) -> list[str]:
    if value is None:
        raise B2GateError(f"{field} is absent")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise B2GateError(f"{field} is invalid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise B2GateError(f"{field} must be a JSON string list")
    return parsed


def capture_outer_timeout_boundary(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    authorization_path: Path,
    repository_root: Path = REPOSITORY_ROOT,
    parent_pid: int | None = None,
    proc_executable: str | None = None,
    proc_command: Sequence[str] | None = None,
    timeout_version: str | None = None,
) -> dict[str, Any]:
    expected = expected_outer_commands(
        config=config,
        config_path=config_path,
        authorization_path=authorization_path,
        repository_root=repository_root,
    )
    production = _json_string_list(
        os.environ.get("B2_ACE_CONFIRMATION_PRODUCTION_COMMAND_JSON"),
        "B2_ACE_CONFIRMATION_PRODUCTION_COMMAND_JSON",
    )
    timeout = _json_string_list(
        os.environ.get("B2_ACE_CONFIRMATION_TIMEOUT_COMMAND_JSON"),
        "B2_ACE_CONFIRMATION_TIMEOUT_COMMAND_JSON",
    )
    if (
        production != expected["production_wrapper_command"]
        or timeout != expected["outer_timeout_command"]
    ):
        raise B2GateError("recorded wrapper/timeout command differs from frozen command")
    wrapper = (repository_root / config["outer_timeout"]["wrapper_relative_path"]).resolve(
        strict=True
    )
    if os.environ.get("B2_ACE_CONFIRMATION_WRAPPER_PATH") != str(wrapper):
        raise B2GateError("wrapper path evidence is absent or changed")
    if os.environ.get("B2_ACE_CONFIRMATION_WRAPPER_SHA256") != sha256_file(wrapper):
        raise B2GateError("wrapper hash evidence is absent or changed")
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1" or not sys.dont_write_bytecode:
        raise B2GateError("production runner must disable bytecode writes")
    if sys.pycache_prefix != config["outer_timeout"]["pycache_prefix"]:
        raise B2GateError("pycache prefix differs from frozen boundary")
    if os.path.lexists(sys.pycache_prefix):
        raise B2GateError("alternate pycache prefix must be absent at runner preflight")
    observed_parent = os.getppid() if parent_pid is None else parent_pid
    if proc_executable is None:
        proc_executable = str(Path(f"/proc/{observed_parent}/exe").resolve(strict=True))
    if proc_command is None:
        raw = Path(f"/proc/{observed_parent}/cmdline").read_bytes()
        proc_command = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    if proc_executable != config["outer_timeout"]["timeout_executable"]:
        raise B2GateError("runner parent is not frozen /usr/bin/timeout")
    if list(proc_command) != expected["outer_timeout_command"]:
        raise B2GateError("runner parent argv differs from exact one-call timeout argv")
    if timeout_version is None:
        timeout_version = subprocess.run(
            [proc_executable, "--version"], check=True, capture_output=True, text=True
        ).stdout.splitlines()[0]
    if "GNU coreutils" not in timeout_version:
        raise B2GateError("timeout executable is not GNU coreutils")
    return {
        **expected,
        "outer_timeout_command_shell": shlex.join(expected["outer_timeout_command"]),
        "production_wrapper_command_shell": shlex.join(expected["production_wrapper_command"]),
        "parent_pid": observed_parent,
        "parent_executable": proc_executable,
        "parent_argv": list(proc_command),
        "timeout_version": timeout_version,
    }


def _expected_decisions_assignments(
    config: Mapping[str, Any], hashes: Mapping[str, str], authorization: Mapping[str, Any]
) -> dict[str, str]:
    prior = config["prior_consumed_evidence"]["artifacts"]
    return {
        "BENCHMARK_PREREG_V2_FROZEN": "YES",
        "BENCHMARK_PREREG_V2_SHA256": authorization["frozen_artifacts"]["benchmark_prereg_v2"][
            "sha256"
        ],
        "B2_MINI_SMOKE_V2_AUTHORIZED": "NO",
        "B2_ACE_DURATION_CONFIRMATION_V1_AUTHORIZED": "YES",
        "B2_ACE_DURATION_CONFIRMATION_V1_SCOPE": AUTHORIZATION_SCOPE,
        "B2_ACE_DURATION_CONFIRMATION_V1_CONFIG_SHA256": hashes["confirmation_config"],
        "B2_ACE_DURATION_CONFIRMATION_V1_PROTOCOL_SHA256": hashes["confirmation_protocol"],
        "B2_ACE_DURATION_CONFIRMATION_V1_RUNNER_SHA256": hashes["confirmation_runner"],
        "B2_ACE_DURATION_CONFIRMATION_V1_WRAPPER_SHA256": hashes["confirmation_wrapper"],
        "B2_ACE_DURATION_CONFIRMATION_V1_AUTH_TEMPLATE_SHA256": hashes["authorization_template"],
        "B2_ACE_DURATION_CONFIRMATION_V1_DURATION_POLICY_SHA256": hashes["duration_policy"],
        "B2_ACE_DURATION_CONFIRMATION_V1_DURATION_SANITY_SHA256": hashes["duration_sanity"],
        "B2_ACE_DURATION_CONFIRMATION_V1_QUANTIZATION_PROVENANCE_SHA256": hashes[
            "duration_quantization_provenance"
        ],
        "B2_ACE_DURATION_CONFIRMATION_V1_READJUDICATION_SHA256": hashes["duration_readjudication"],
        "B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_GLOBAL_CLAIM_SHA256": prior["global_claim"][
            "sha256"
        ],
        "B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_CALL_CLAIM_SHA256": prior["call_00_claim"]["sha256"],
        "B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_LEDGER_SHA256": prior["generation_ledger"]["sha256"],
        "B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_WAV_SHA256": prior["retained_wav"]["sha256"],
        "B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_PROVENANCE_SHA256": prior["retained_wav_provenance"][
            "sha256"
        ],
        "B2_ACE_DURATION_CONFIRMATION_V1_MAX_MODEL_CALLS": "1",
        "B2_ACE_DURATION_CONFIRMATION_V1_MAX_GENERATED_OUTPUTS": "1",
        "B2_ACE_DURATION_CONFIRMATION_V1_MAX_REQUESTED_CLIP_SECONDS": "30",
        "B2_ACE_DURATION_CONFIRMATION_V1_DURATION_TOLERANCE_SECONDS": "0.25",
        "B2_ACE_DURATION_CONFIRMATION_V1_MAX_GPUS": "1",
        "B2_ACE_DURATION_CONFIRMATION_V1_MAX_GPU_SECONDS": "1800",
        "B2_ACE_DURATION_CONFIRMATION_V1_RETRIES": "0",
        "B2_ACE_DURATION_CONFIRMATION_V1_PROMPT_ID": EXPECTED_JOB["prompt_id"],
        "B2_ACE_DURATION_CONFIRMATION_V1_RESERVED_SEED": "S-0009:73193009",
    }


def validate_external_authorization(
    authorization_path: Path,
    *,
    config: Mapping[str, Any],
    hashes: Mapping[str, str],
    repository_root: Path = REPOSITORY_ROOT,
    runner_path: Path = DEFAULT_RUNNER,
    now: datetime | None = None,
    git_evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_authorization = authorization_path.resolve(strict=True)
    try:
        resolved_authorization.relative_to(repository_root.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise B2GateError("completed external authorization must be outside the repository")
    authorization = read_json_object(authorization_path)
    if _contains_placeholder(authorization):
        raise B2GateError("authorization is still an inert template")
    expected_scalars = {
        "schema_version": 1,
        "authorization_id": AUTHORIZATION_ID,
        "scope": AUTHORIZATION_SCOPE,
        "execution_authorized": True,
        "benchmark_endpoint": False,
        "required_prereg_status": "FROZEN_PROSPECTIVE_DESIGN",
        "run_id": FIXED_RUN_ID,
    }
    if any(authorization.get(key) != value for key, value in expected_scalars.items()):
        raise B2GateError("external authorization identity or boolean authority changed")
    if authorization.get("caps") != EXPECTED_AUTHORIZATION_CAPS:
        raise B2GateError("external authorization one-call caps changed")
    if authorization.get("duration_policy") != EXPECTED_DURATION_POLICY:
        raise B2GateError("external authorization duration policy changed")
    if authorization.get("prior_consumed_evidence") != EXPECTED_PRIOR_EVIDENCE:
        raise B2GateError("external authorization prior evidence changed")
    if authorization.get("reserved_non_benchmark_seeds") != [
        {"prompt_id": EXPECTED_JOB["prompt_id"], "seed": 73193009, "seed_id": "S-0009"}
    ]:
        raise B2GateError("external authorization does not bind only S-0009")

    authorized_at = _parse_utc(authorization.get("authorized_at_utc"), "authorized_at_utc")
    expires_at = _parse_utc(authorization.get("expires_at_utc"), "expires_at_utc")
    current = now or datetime.now(timezone.utc)
    if current < authorized_at or current > expires_at:
        raise B2GateError("external authorization is not currently valid")
    if expires_at <= authorized_at or (expires_at - authorized_at).total_seconds() > 86400:
        raise B2GateError("external authorization validity must be positive and at most 24 hours")

    frozen = authorization.get("frozen_artifacts")
    expected_artifacts = {
        **{name: hashes[name] for name in EXPECTED_FROZEN_PATHS},
        "confirmation_config": hashes["confirmation_config"],
        "benchmark_prereg_v2": sha256_file(repository_root / "BENCHMARK_PREREG_v2.md"),
    }
    expected_paths = {
        **EXPECTED_FROZEN_PATHS,
        "confirmation_config": "configs/b2_ace_duration_confirmation_v1.json",
        "benchmark_prereg_v2": "BENCHMARK_PREREG_v2.md",
    }
    if not isinstance(frozen, dict) or set(frozen) != set(expected_artifacts):
        raise B2GateError("authorization frozen-artifact key set is not exact")
    for name, expected_hash in expected_artifacts.items():
        record = frozen[name]
        if not isinstance(record, dict) or record.get("sha256") != expected_hash:
            raise B2GateError(f"authorization does not bind live {name} hash")
        _repo_record(repository_root, record, f"frozen_artifacts.{name}", expected_paths[name])
    if hashes["confirmation_runner"] != sha256_file(runner_path):
        raise B2GateError("live production runner differs from frozen runner")

    prereg_text = (repository_root / "BENCHMARK_PREREG_v2.md").read_text(encoding="utf-8")
    if not re.search(r"(?m)^- Status: `FROZEN_PROSPECTIVE_DESIGN`\s*$", prereg_text):
        raise B2GateError("live prereg status is not frozen")
    if _latest_assignment(prereg_text, "BENCHMARK_PREREG_V2_FROZEN") != "YES":
        raise B2GateError("live prereg frozen marker is not YES")

    if authorization.get("runtime_environment") != config.get("runtime_environment"):
        raise B2GateError("authorization runtime identity changed")
    if authorization.get("source_bindings") != config.get("source_bindings"):
        raise B2GateError("authorization source/checkpoint bindings changed")

    decisions_path = repository_root / "DECISIONS.md"
    decisions_hash = sha256_file(decisions_path)
    if authorization.get("decisions_sha256") != decisions_hash:
        raise B2GateError("authorization does not bind live post-amendment DECISIONS.md")
    expected_assignments = _expected_decisions_assignments(config, hashes, authorization)
    required_names = config["authorization"].get("required_decisions_assignments")
    if not isinstance(required_names, list) or set(required_names) != set(expected_assignments):
        raise B2GateError("config decision-assignment key set is incomplete")
    decisions_text = decisions_path.read_text(encoding="utf-8")
    for name, expected in expected_assignments.items():
        observed = _latest_assignment(decisions_text, name)
        if observed != expected:
            raise B2GateError(
                f"latest DECISIONS assignment {name}={observed!r}, expected {expected!r}"
            )

    git = dict(git_evidence or _git_capture(repository_root))
    origin = authorization.get("origin")
    if (
        not isinstance(origin, dict)
        or origin.get("branch") != "main"
        or origin.get("remote_tracking_ref") != "origin/main"
    ):
        raise B2GateError("authorization must bind main and origin/main")
    commit = origin.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise B2GateError("authorization origin commit must be a full Git SHA")
    if not git.get("clean") or git.get("branch") != "main":
        raise B2GateError("repository must be clean on main, including untracked files")
    if git.get("head") != commit or git.get("origin_main") != commit:
        raise B2GateError("authorization commit must equal clean HEAD and origin/main")

    placement = authorization.get("placement")
    if not isinstance(placement, dict):
        raise B2GateError("authorization placement is absent")
    if placement.get("node") not in config["placement"]["allowed_nodes"]:
        raise B2GateError("authorization node is not allowed")
    if placement.get("physical_gpu_id") not in config["placement"]["allowed_physical_gpu_ids"]:
        raise B2GateError("authorization physical GPU is not allowed")
    if placement.get("tensor_parallel_width") != 1 or placement.get("replica_count") != 1:
        raise B2GateError("confirmation requires TP1 and one replica")
    if (
        not isinstance(placement.get("placement_justification"), str)
        or not placement["placement_justification"].strip()
    ):
        raise B2GateError("placement justification is absent")
    return authorization, {"decisions_sha256": decisions_hash, "git": git}


def _strict_external_record(record: Mapping[str, Any], field: str) -> Path:
    path_value = record.get("path")
    expected_hash = record.get("sha256")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise B2GateError(f"{field}.path must be absolute")
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise B2GateError(f"{field}.sha256 must be lowercase SHA-256")
    path = Path(path_value).resolve(strict=True)
    if sha256_file(path) != expected_hash:
        raise B2GateError(f"{field} retained evidence hash changed")
    return path


def validate_prior_consumed_evidence(
    config: Mapping[str, Any], *, repository_root: Path = REPOSITORY_ROOT
) -> dict[str, Any]:
    """Re-hash and semantically re-adjudicate retained call 0 without writing it."""

    prior = config["prior_consumed_evidence"]
    paths = {
        name: _strict_external_record(record, f"prior_consumed_evidence.{name}")
        for name, record in prior["artifacts"].items()
    }
    for absent in prior["required_absent_paths"]:
        if os.path.lexists(absent):
            raise B2GateError(f"forbidden old call-01 path now exists: {absent}")

    global_claim = read_json_object(paths["global_claim"])
    call_claim = read_json_object(paths["call_00_claim"])
    if (
        global_claim.get("run_id") != prior["original_run_id"]
        or global_claim.get("authorization_id") != "B2-ACE-V1-MINI-SMOKE-V2-ONE-SHOT"
    ):
        raise B2GateError("prior global claim semantics changed")
    if (call_claim.get("generation_index"), call_claim.get("seed_id"), call_claim.get("seed")) != (
        0,
        "S-0008",
        73193008,
    ):
        raise B2GateError("prior consumed call claim semantics changed")

    lines = paths["generation_ledger"].read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise B2GateError("prior generation ledger must retain exactly one row")
    try:
        old_row = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise B2GateError("prior generation ledger is invalid JSON") from exc
    old_sanity = old_row.get("audio_sanity")
    if old_row.get("status") != "AUDIO_SANITY_FAILED" or not isinstance(old_sanity, dict):
        raise B2GateError("prior ledger no longer records the original exact-frame failure")
    if [row.get("check") for row in old_sanity.get("failures", [])] != ["sample_count"]:
        raise B2GateError("prior call had a new non-duration sanity failure")

    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))
    from backbones.duration_sanity import duration_tolerant_audio_sanity

    readjudicated = duration_tolerant_audio_sanity(
        paths["retained_wav"],
        30.0,
        duration_tolerance_seconds=0.25,
        expected_sample_rate=48000,
        expected_channels=2,
        require_provenance=True,
    )
    if not readjudicated["pass"] or readjudicated["duration_seconds"] != 29.9073125:
        raise B2GateError("retained call 0 does not pass the amended duration-only criterion")
    provenance = read_json_object(
        repository_root / config["frozen_sources"]["duration_quantization_provenance"]["path"]
    )
    if provenance.get("shared_observation", {}).get("replicated_seed_count") != 8:
        raise B2GateError("duration quantization provenance lacks eight replicated seeds")
    readjudication = read_json_object(
        repository_root / config["frozen_sources"]["duration_readjudication"]["path"]
    )
    if readjudication.get("status") != "PASS_UNDER_AMENDED_DURATION_RULE":
        raise B2GateError("committed retained-call re-adjudication is not PASS")
    return {
        "artifact_hashes": {name: sha256_file(path) for name, path in paths.items()},
        "required_absences_verified": list(prior["required_absent_paths"]),
        "retained_call_readjudication": readjudicated,
        "duration_quantization_replicated_seed_count": 8,
    }


def consume_authorized_attempt(
    *,
    claim_root: Path,
    config: Mapping[str, Any],
    hashes: Mapping[str, str],
    authorization: Mapping[str, Any],
    authorization_path: Path,
    governance: Mapping[str, Any],
) -> dict[str, str]:
    """Durably consume the authority before any engineering/runtime preflight."""

    claim_root.mkdir(parents=True, exist_ok=True)
    attempt_path = claim_root / config["run"]["authorization_attempt_claim_filename"]
    attempt = {
        "authorization_id": AUTHORIZATION_ID,
        "claim_type": "VALID_EXTERNAL_AUTHORIZATION_DURABLE_ATTEMPT_CONSUMPTION",
        "claimed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": FIXED_RUN_ID,
        "scope": AUTHORIZATION_SCOPE,
        "benchmark_endpoint": False,
        "authorization_path": str(authorization_path.resolve(strict=True)),
        "authorization_sha256": sha256_file(authorization_path),
        "config_sha256": hashes["confirmation_config"],
        "runner_sha256": hashes["confirmation_runner"],
        "decisions_sha256": governance["decisions_sha256"],
        "origin_commit": governance["git"]["head"],
        "exact_job": EXPECTED_JOB,
        "caps": config["caps"],
        "duration_policy": config["duration_policy"],
        "authorized_placement": dict(authorization["placement"]),
        "terminal_rule": ("ANY_SUBSEQUENT_FAILURE_IS_BLOCKED_ON_ENGINEERING_FAILURE_WITH_NO_RETRY"),
    }
    exclusive_write_json(attempt_path, attempt)
    return {"path": str(attempt_path), "sha256": sha256_file(attempt_path)}


def confirmation_row_status(
    sanity: Mapping[str, Any],
    measurement_sample_rate: int,
    audio_sanity_policy: Mapping[str, Any],
) -> tuple[str, bool]:
    """Return the terminal row status and independent adapter-rate agreement."""

    expected_sample_rate = audio_sanity_policy.get("expected_sample_rate")
    if isinstance(measurement_sample_rate, bool) or not isinstance(measurement_sample_rate, int):
        raise B2ExecutionError("adapter measurement sample rate must be an integer")
    matches = measurement_sample_rate == expected_sample_rate
    if not matches:
        return "ADAPTER_MEASUREMENT_SAMPLE_RATE_FAILED", False
    return ("PASS" if sanity.get("pass") is True else "AUDIO_SANITY_FAILED"), True


class OneCallClaimingAdapter:
    """Bind every request field and durably reserve the sole call before delegation."""

    def __init__(
        self,
        delegate: Any,
        *,
        job: Mapping[str, Any],
        output_path: Path,
        claim_dir: Path,
        claim_context: Mapping[str, Any],
        placement: Mapping[str, Any],
        physical_gpu_id: int,
        deadline_monotonic: float,
        logger: DurableLog,
        gpu_probe: Callable[..., dict[str, Any]] = probe_gpu,
        behavior_identity_probe: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self._delegate = delegate
        self._job = dict(job)
        self._output_path = output_path.resolve()
        self._claim_dir = claim_dir
        self._claim_context = dict(claim_context)
        self._placement = dict(placement)
        self._physical_gpu_id = physical_gpu_id
        self._deadline_monotonic = deadline_monotonic
        self._logger = logger
        self._gpu_probe = gpu_probe
        self._behavior_identity_probe = behavior_identity_probe
        self._claimed = False
        for name in ("model_id", "logical_name", "config_sha256", "license_identifier"):
            setattr(self, name, getattr(delegate, name))

    def preflight(self) -> Any:
        return self._delegate.preflight()

    def generate(self, request: Any) -> Any:
        if self._claimed:
            raise B2ExecutionError(
                "the sole confirmation call was already claimed; retry forbidden"
            )
        observed = {
            "prompt_id": request.prompt_id,
            "prompt": request.prompt,
            "seed_id": request.seed_id,
            "seed": request.seed,
            "duration_seconds": request.duration_seconds,
            "lyrics": request.lyrics,
            "output_path": str(request.output_path.resolve()),
        }
        expected = {
            "prompt_id": self._job["prompt_id"],
            "prompt": self._job["prompt"],
            "seed_id": self._job["seed_id"],
            "seed": self._job["seed"],
            "duration_seconds": self._job["duration_seconds"],
            "lyrics": self._job["lyrics"],
            "output_path": str(self._output_path),
        }
        if observed != expected:
            raise B2ExecutionError("request differs from exact S-0009 confirmation job")
        if time.monotonic() >= self._deadline_monotonic:
            raise B2ExecutionError("1,800-second deadline elapsed before sole model call")
        identity = (
            dict(self._behavior_identity_probe())
            if self._behavior_identity_probe is not None
            else {"test_injection": "NO_PRODUCTION_IDENTITY_PROBE"}
        )
        live = self._gpu_probe(
            self._physical_gpu_id,
            minimum_free_mib=int(self._placement["minimum_free_memory_before_claim_mib"]),
            maximum_utilization_percent=int(self._placement["max_idle_utilization_percent"]),
            required_name_substring=str(self._placement["required_gpu_name_substring"]),
            allowed_compute_pids=set(),
        )
        if time.monotonic() >= self._deadline_monotonic:
            raise B2ExecutionError("deadline elapsed during sole per-call preflight")
        claim = {
            **self._claim_context,
            "claim_type": "SOLE_ACE_DURATION_CONFIRMATION_MODEL_CALL_RESERVATION",
            "claimed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "generation_index": 0,
            "original_b2_call_index": 1,
            "request": observed,
            "live_placement": live,
            "immediate_behavior_identity": identity,
        }
        claim_path = self._claim_dir / "call-00.claim.json"
        exclusive_write_json(claim_path, claim)
        claim_hash = sha256_file(claim_path)
        self._claimed = True
        self._logger.append(
            "SOLE_PER_CALL_CLAIM_DURABLE", {"path": str(claim_path), "sha256": claim_hash}
        )
        return self._delegate.generate(request)


def _append_ledger_row(path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    record = {**dict(row), "previous_row_sha256": "0" * 64}
    record["row_sha256"] = hashlib.sha256(_canonical_json(record)).hexdigest()
    with path.open("xb") as handle:
        handle.write(_canonical_json(record) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def validate_one_row_ledger(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    lines = raw.splitlines()
    if len(lines) != 1 or not raw.endswith(b"\n"):
        raise B2ExecutionError("confirmation ledger must contain one complete row")
    try:
        row = json.loads(
            lines[0],
            object_pairs_hook=lambda pairs: _reject_duplicate_pairs(pairs),
            parse_constant=lambda token: (_ for _ in ()).throw(
                B2ExecutionError(f"non-finite ledger token: {token}")
            ),
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise B2ExecutionError("confirmation ledger is not strict JSON") from exc
    if not isinstance(row, dict) or _canonical_json(row) != lines[0]:
        raise B2ExecutionError("confirmation ledger row is not canonical JSON")
    claimed = row.get("row_sha256")
    unhashed = dict(row)
    unhashed.pop("row_sha256", None)
    if row.get("previous_row_sha256") != "0" * 64:
        raise B2ExecutionError("confirmation ledger chain does not start at zero")
    actual = hashlib.sha256(_canonical_json(unhashed)).hexdigest()
    if claimed != actual:
        raise B2ExecutionError("confirmation ledger row hash is invalid")
    return {"row": row, "ledger_tail_sha256": actual, "ledger_sha256": sha256_file(path)}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise B2ExecutionError(f"duplicate ledger key: {key}")
        result[key] = value
    return result


def execute_confirmation(
    *,
    config_path: Path,
    authorization_path: Path,
    execute_phrase: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Execute the sole model call after every static and live gate passes."""

    config, hashes = validate_static_config(config_path, repository_root=repository_root)
    if execute_phrase != EXECUTE_PHRASE:
        raise B2GateError("exact one-call execute phrase is absent or incorrect")
    outer = capture_outer_timeout_boundary(
        config=config,
        config_path=config_path,
        authorization_path=authorization_path,
        repository_root=repository_root,
    )
    authorization, governance = validate_external_authorization(
        authorization_path,
        config=config,
        hashes=hashes,
        repository_root=repository_root,
        runner_path=repository_root / EXPECTED_FROZEN_PATHS["confirmation_runner"],
    )
    run_control = config["run"]
    try:
        claim_root = _validate_external_root(
            run_control["claim_root"], repository_root, "claim_root"
        )
        authorized_attempt = consume_authorized_attempt(
            claim_root=claim_root,
            config=config,
            hashes=hashes,
            authorization=authorization,
            authorization_path=authorization_path,
            governance=governance,
        )
    except Exception as exc:
        raise AuthorizedConfirmationFailure(
            f"valid external authorization reached terminal attempt boundary: {exc}"
        ) from exc
    prior_evidence = validate_prior_consumed_evidence(config, repository_root=repository_root)
    source_environment = _source_environment(config)
    runtime = capture_runtime_environment(config)

    placement = config["placement"]
    authorized_placement = authorization["placement"]
    node = _hostname_node()
    physical_gpu_id = authorized_placement["physical_gpu_id"]
    if node != authorized_placement["node"] or node not in placement["allowed_nodes"]:
        raise B2GateError("live node differs from authorized an12/an29 node")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != str(physical_gpu_id):
        raise B2GateError("CUDA_VISIBLE_DEVICES must bind exactly the authorized physical GPU")

    run_root = _validate_external_root(run_control["run_root"], repository_root, "run_root")
    log_root = _validate_external_root(run_control["log_root"], repository_root, "log_root")
    run_dir = run_root / FIXED_RUN_ID
    log_path = log_root / f"{FIXED_RUN_ID}.jsonl"
    claim_dir = claim_root / FIXED_RUN_ID
    global_claim_path = claim_root / run_control["authorization_claim_filename"]
    for path in (run_dir, log_path, claim_dir, global_claim_path):
        if os.path.lexists(path):
            raise B2GateError(f"immutable one-shot path already exists: {path}")

    lock_path = Path(
        placement["device_lock_template"].format(node=node, physical_gpu_id=physical_gpu_id)
    )
    with device_lock(lock_path):
        initial_gpu = probe_gpu(
            physical_gpu_id,
            minimum_free_mib=placement["minimum_free_memory_before_claim_mib"],
            maximum_utilization_percent=placement["max_idle_utilization_percent"],
            required_name_substring=placement["required_gpu_name_substring"],
            allowed_compute_pids=set(),
        )
        run_root.mkdir(parents=True, exist_ok=True)
        log_root.mkdir(parents=True, exist_ok=True)
        claim_root.mkdir(parents=True, exist_ok=True)
        claim_dir.mkdir(parents=False, exist_ok=False)
        logger = DurableLog(log_path)
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            runtime_path = claim_dir / "runtime-environment-preclaim.json"
            exclusive_write_json(runtime_path, runtime)
            preclaim = {
                "authorization_path": str(authorization_path.resolve()),
                "authorization_sha256": sha256_file(authorization_path),
                "authorized_attempt_claim": authorized_attempt,
                "config_path": str(config_path.resolve()),
                "config_sha256": hashes["confirmation_config"],
                "runner_sha256": hashes["confirmation_runner"],
                "governance": governance,
                "prior_consumed_evidence": prior_evidence,
                "source_environment": source_environment,
                "runtime_environment_sha256": sha256_file(runtime_path),
                "initial_placement": initial_gpu,
                "outer_timeout_boundary": outer,
                "lock_path": str(lock_path),
                "lock_held": True,
            }
            preclaim_path = claim_dir / "authorization-and-placement-preclaim.json"
            exclusive_write_json(preclaim_path, preclaim)
            logger.append("PRECLAIM_VALIDATION_PASS", {"path": str(preclaim_path)})

            if str(SOURCE_ROOT) not in sys.path:
                sys.path.insert(0, str(SOURCE_ROOT))
            source_dir = source_environment[
                config["backbone"]["required_source_environment_variable"]
            ]
            if source_dir not in sys.path:
                sys.path.insert(1, source_dir)
            from backbones.ace_step_v1 import AceStepV1Adapter, verify_exact_checkpoint_tree
            from backbones.contracts import GenerationRequest
            from backbones.duration_sanity import duration_tolerant_audio_sanity
            from backbones.runtime import verify_clean_git_revision
            from sa3_smoke.artifacts import write_adjacent_provenance

            adapter = AceStepV1Adapter(
                config_path=repository_root / config["backbone"]["config"]["path"],
                evidence_dir=claim_dir / "adapter-preflight-evidence",
            )
            adapter_preflight = adapter.preflight()
            if adapter_preflight.status != "READY_FOR_MINI_SMOKE":
                raise B2GateError("ACE adapter preflight is not ready")
            adapter_preflight_path = claim_dir / "adapter-preflight.json"
            exclusive_write_json(
                adapter_preflight_path,
                {
                    "status": adapter_preflight.status,
                    "model_id": adapter_preflight.model_id,
                    "config_sha256": adapter_preflight.config_sha256,
                    "details": dict(adapter_preflight.details),
                },
            )
            immediate_gpu = probe_gpu(
                physical_gpu_id,
                minimum_free_mib=placement["minimum_free_memory_before_claim_mib"],
                maximum_utilization_percent=placement["max_idle_utilization_percent"],
                required_name_substring=placement["required_gpu_name_substring"],
                allowed_compute_pids=set(),
            )
            global_claim = {
                "authorization_id": AUTHORIZATION_ID,
                "claim_type": "SOLE_ACE_DURATION_CONFIRMATION_EXECUTION",
                "claimed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "run_id": FIXED_RUN_ID,
                "scope": AUTHORIZATION_SCOPE,
                "benchmark_endpoint": False,
                "config_sha256": hashes["confirmation_config"],
                "runner_sha256": hashes["confirmation_runner"],
                "authorization_sha256": sha256_file(authorization_path),
                "authorized_attempt_claim_sha256": authorized_attempt["sha256"],
                "decisions_sha256": governance["decisions_sha256"],
                "origin_commit": governance["git"]["head"],
                "caps": config["caps"],
                "exact_job": EXPECTED_JOB,
                "duration_policy": EXPECTED_DURATION_POLICY,
                "prior_evidence_hashes": prior_evidence["artifact_hashes"],
                "runtime_environment_sha256": sha256_file(runtime_path),
                "adapter_preflight_sha256": sha256_file(adapter_preflight_path),
                "immediate_preclaim_placement": immediate_gpu,
                "node": node,
                "physical_gpu_id": physical_gpu_id,
                "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                "process_visible_device": "cuda:0",
                "outer_timeout_command": outer["outer_timeout_command"],
                "outer_production_command": outer["production_wrapper_command"],
                "tensor_parallel_width": 1,
                "replica_count": 1,
                "placement_justification": authorized_placement["placement_justification"],
                "run_dir": str(run_dir),
                "log_path": str(log_path),
            }
            exclusive_write_json(global_claim_path, global_claim)
            global_claim_hash = sha256_file(global_claim_path)
            logger.append(
                "GLOBAL_ONE_SHOT_CLAIM_DURABLE",
                {"path": str(global_claim_path), "sha256": global_claim_hash},
            )

            run_dir.mkdir(parents=False, exist_ok=False)
            output_path = run_dir / EXPECTED_JOB["output_relative_path"]
            output_path.parent.mkdir(parents=True, exist_ok=False)
            manifest_path = run_dir / "manifest.json"
            ledger_path = run_dir / "generation_ledger.jsonl"
            exclusive_write_json(
                manifest_path,
                {
                    "schema_version": 1,
                    "scope": AUTHORIZATION_SCOPE,
                    "run_id": FIXED_RUN_ID,
                    "started_at_utc": started_at,
                    "command": outer["outer_timeout_command_shell"],
                    "git_commit": governance["git"]["head"],
                    "placement": {
                        "node": node,
                        "gpu_ids": [str(physical_gpu_id)],
                        "tensor_parallel_width": 1,
                        "replica_count": 1,
                        "justification": authorized_placement["placement_justification"],
                    },
                    "caps": config["caps"],
                    "duration_policy": config["duration_policy"],
                    "reserved_generations": 1,
                    "requests": [{**EXPECTED_JOB, "output_path": str(output_path)}],
                },
            )

            deadline_seconds = float(run_control["deadline_seconds"])
            deadline_monotonic = time.monotonic() + deadline_seconds

            def behavior_identity_probe() -> dict[str, Any]:
                ace_config = adapter.config
                return {
                    "checkpoint_tree": verify_exact_checkpoint_tree(
                        adapter.checkpoint_dir,
                        ace_config["checkpoint"]["required_files"],
                        ace_config["checkpoint"]["exact_tree_sha256"],
                    ),
                    "source": verify_clean_git_revision(
                        adapter.source_dir,
                        ace_config["provenance"]["upstream_code_revision"],
                        expected_tree=ace_config["provenance"]["upstream_code_tree"],
                    ),
                }

            claiming_adapter = OneCallClaimingAdapter(
                adapter,
                job=EXPECTED_JOB,
                output_path=output_path,
                claim_dir=claim_dir,
                claim_context={
                    "authorization_id": AUTHORIZATION_ID,
                    "global_claim_sha256": global_claim_hash,
                    "run_id": FIXED_RUN_ID,
                    "config_sha256": hashes["confirmation_config"],
                    "origin_commit": governance["git"]["head"],
                    "outer_timeout_command": outer["outer_timeout_command"],
                },
                placement=placement,
                physical_gpu_id=physical_gpu_id,
                deadline_monotonic=deadline_monotonic,
                logger=logger,
                behavior_identity_probe=behavior_identity_probe,
            )
            request = GenerationRequest(
                prompt_id=EXPECTED_JOB["prompt_id"],
                prompt=EXPECTED_JOB["prompt"],
                seed_id=EXPECTED_JOB["seed_id"],
                seed=EXPECTED_JOB["seed"],
                duration_seconds=EXPECTED_JOB["duration_seconds"],
                output_path=output_path,
                lyrics=EXPECTED_JOB["lyrics"],
            )
            gpu_started = time.monotonic()
            try:
                with elapsed_deadline(deadline_seconds):
                    measurement = claiming_adapter.generate(request)
                provenance_path = write_adjacent_provenance(
                    measurement.output_path,
                    {
                        "label": "synthetic_model_output",
                        "created_at_utc": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "creating_command": outer["outer_timeout_command_shell"],
                        "run_id": FIXED_RUN_ID,
                        "source_ids": [f"{adapter.model_id}@config-sha256:{adapter.config_sha256}"],
                        "model_revision": adapter.config["provenance"]["upstream_code_revision"],
                        "license_identifier": adapter.license_identifier,
                        "transformation": "official backbone text-to-audio decode",
                    },
                )
                sanity_policy = config["audio_sanity"]
                sanity = duration_tolerant_audio_sanity(
                    measurement.output_path,
                    EXPECTED_JOB["duration_seconds"],
                    duration_tolerance_seconds=sanity_policy["duration_tolerance_seconds"],
                    expected_sample_rate=sanity_policy["expected_sample_rate"],
                    expected_channels=sanity_policy["expected_channels"],
                    require_provenance=True,
                )
                row_status, measurement_sample_rate_matches_frozen = confirmation_row_status(
                    sanity,
                    measurement.sample_rate,
                    sanity_policy,
                )
                row = {
                    "schema_version": 1,
                    "run_id": FIXED_RUN_ID,
                    "generation_index": 0,
                    "original_b2_call_index": 1,
                    "logical_name": adapter.logical_name,
                    "model_id": adapter.model_id,
                    "config_sha256": adapter.config_sha256,
                    "prompt_id": request.prompt_id,
                    "seed_id": request.seed_id,
                    "seed": request.seed,
                    "duration_seconds": request.duration_seconds,
                    "output_path": str(output_path),
                    "status": row_status,
                    "cost_status": "MEASURED",
                    "requested_steps": measurement.requested_steps,
                    "actual_nfe": measurement.actual_nfe,
                    "wall_seconds": measurement.wall_seconds,
                    "peak_allocated_bytes": measurement.peak_allocated_bytes,
                    "peak_reserved_bytes": measurement.peak_reserved_bytes,
                    "measurement_sample_rate": measurement.sample_rate,
                    "frozen_expected_sample_rate": sanity_policy["expected_sample_rate"],
                    "measurement_sample_rate_matches_frozen": (
                        measurement_sample_rate_matches_frozen
                    ),
                    "measurement_metadata": dict(measurement.metadata),
                    "file_sha256": sha256_file(output_path),
                    "provenance_path": str(provenance_path),
                    "provenance_sha256": sha256_file(provenance_path),
                    "audio_sanity": sanity,
                }
            except Exception as exc:
                if not os.path.lexists(ledger_path):
                    _append_ledger_row(
                        ledger_path,
                        {
                            "schema_version": 1,
                            "run_id": FIXED_RUN_ID,
                            "generation_index": 0,
                            "original_b2_call_index": 1,
                            "prompt_id": EXPECTED_JOB["prompt_id"],
                            "seed_id": "S-0009",
                            "seed": 73193009,
                            "status": "MODEL_CALL_FAILED",
                            "cost_status": "NOT_MEASURED_CALL_FAILED",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                raise
            gpu_residency_seconds = time.monotonic() - gpu_started
            if os.path.lexists(ledger_path):
                raise B2ExecutionError("confirmation ledger unexpectedly pre-existed")
            row["gpu_residency_seconds"] = gpu_residency_seconds
            row = _append_ledger_row(ledger_path, row)
            verified = validate_one_row_ledger(ledger_path)
            if gpu_residency_seconds > config["caps"]["max_gpu_seconds"]:
                raise B2ExecutionError("measured one-GPU residency exceeded 1,800 seconds")
            if row["status"] != "PASS":
                raise B2ExecutionError("confirmation retained audio failed amended sanity")
            required = set(config["result_contract"]["required_per_call_measures"])
            if not required.issubset(row):
                raise B2ExecutionError("confirmation row lacks required measured fields")

            result = {
                "schema_version": 1,
                "run_id": FIXED_RUN_ID,
                "status": "PASS",
                "measurement_status": "MEASURED",
                "measurement_scope": "B2_ACE_DURATION_CONFIRMATION_NON_BENCHMARK",
                "benchmark_endpoint": False,
                "started_at_utc": started_at,
                "finished_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "model_call_count": 1,
                "generated_output_count": 1,
                "retry_count": 0,
                "gpu_count": 1,
                "gpu_residency_seconds": gpu_residency_seconds,
                "node": node,
                "physical_gpu_id": physical_gpu_id,
                "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                "process_visible_device": "cuda:0",
                "tensor_parallel_width": 1,
                "replica_count": 1,
                "duration_policy": config["duration_policy"],
                "row": verified["row"],
                "ledger_path": str(ledger_path),
                "ledger_sha256": verified["ledger_sha256"],
                "ledger_tail_sha256": verified["ledger_tail_sha256"],
                "global_claim_path": str(global_claim_path),
                "global_claim_sha256": global_claim_hash,
                "authorized_attempt_claim": authorized_attempt,
                "log_path": str(log_path),
            }
            result_path = run_dir / "b2_ace_duration_confirmation_result.json"
            exclusive_write_json(result_path, result)
            logger.append(
                "TERMINAL_PASS", {"path": str(result_path), "sha256": sha256_file(result_path)}
            )
            return result
        except Exception as exc:
            logger.append(
                "TERMINAL_BLOCKED_ON_ENGINEERING_FAILURE",
                {"error_type": type(exc).__name__, "error": str(exc), "no_retry": True},
            )
            if run_dir.is_dir() and not os.path.lexists(
                run_dir / "b2_ace_duration_confirmation_result.json"
            ):
                exclusive_write_json(
                    run_dir / "b2_ace_duration_confirmation_result.json",
                    {
                        "schema_version": 1,
                        "run_id": FIXED_RUN_ID,
                        "status": "BLOCKED_ON_ENGINEERING_FAILURE",
                        "measurement_status": "NOT_MEASURED_TERMINAL_FAILURE",
                        "measurement_scope": "B2_ACE_DURATION_CONFIRMATION_NON_BENCHMARK",
                        "benchmark_endpoint": False,
                        "started_at_utc": started_at,
                        "finished_at_utc": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "no_retry": True,
                        "node": node,
                        "physical_gpu_id": physical_gpu_id,
                        "log_path": str(log_path),
                    },
                )
            raise
        finally:
            logger.close()


def terminal_failure_record(
    exc: Exception,
    *,
    claim_root: Path = Path(
        "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims"
    ),
    run_root: Path = Path(
        "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/b2-ace-duration-confirmation-v1"
    ),
) -> dict[str, Any]:
    authorized_attempt = (
        claim_root / "b2-ace-v1-duration-confirmation-v1-authorized-attempt.claim.json"
    )
    global_claim = claim_root / "b2-ace-v1-duration-confirmation-v1-one-shot.claim.json"
    call_claim = claim_root / FIXED_RUN_ID / "call-00.claim.json"
    output = run_root / FIXED_RUN_ID / EXPECTED_JOB["output_relative_path"]
    attempt_consumed = os.path.lexists(authorized_attempt)
    global_consumed = os.path.lexists(global_claim)
    consumed = attempt_consumed or global_consumed or isinstance(exc, AuthorizedConfirmationFailure)
    return {
        "schema_version": 1,
        "run_id": FIXED_RUN_ID,
        "status": "BLOCKED_ON_ENGINEERING_FAILURE" if consumed else "REFUSED_PREFLIGHT",
        "measurement_status": (
            "NOT_MEASURED_TERMINAL_FAILURE" if consumed else "NOT_MEASURED_NO_MODEL_CALL"
        ),
        "measurement_scope": "B2_ACE_DURATION_CONFIRMATION_NON_BENCHMARK",
        "benchmark_endpoint": False,
        "finished_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "authorization_attempt_claim_consumed": attempt_consumed,
        "global_claim_consumed": global_consumed,
        "per_call_claim_count": int(os.path.lexists(call_claim)),
        "model_call_count": 0 if not consumed else None,
        "generated_output_count": int(os.path.lexists(output)),
        "retry_count": 0,
        "no_retry": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--authorization",
        type=Path,
        default=os.environ.get("B2_ACE_DURATION_CONFIRMATION_AUTHORIZATION"),
        required=os.environ.get("B2_ACE_DURATION_CONFIRMATION_AUTHORIZATION") is None,
    )
    parser.add_argument("--run-id", choices=[FIXED_RUN_ID], required=True)
    parser.add_argument("--execute", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute_confirmation(
            config_path=args.config.resolve(),
            authorization_path=args.authorization.resolve(),
            execute_phrase=args.execute,
        )
    except Exception as exc:
        print(
            json.dumps(terminal_failure_record(exc), allow_nan=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

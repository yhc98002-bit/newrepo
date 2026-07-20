#!/usr/bin/env python3
"""Fail-closed launcher for the two-call ACE-Step v1 B2 engineering mini-smoke.

Importing this module performs no adapter construction, model import, GPU
query, filesystem write, or model call. The live path requires a completed
external authorization record plus the explicit execute phrase.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
DEFAULT_CONFIG = REPOSITORY_ROOT / "configs" / "b2_mini_smoke_v2.json"
DEFAULT_RUNNER = Path(__file__).resolve()
DEFAULT_WRAPPER = REPOSITORY_ROOT / "scripts" / "run_b2_mini_smoke_v2_with_timeout.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,95}$")
PLACEHOLDER_RE = re.compile(r"REPLACE_WITH|PREPARED_NOT_AUTHORIZED")
AUTHORIZATION_SCOPE = "ACE_STEP_V1_ENGINEERING_COST_ONLY_NON_BENCHMARK"
AUTHORIZATION_ID = "B2-ACE-V1-MINI-SMOKE-V2-ONE-SHOT"
FIXED_RUN_ID = "b2-ace-v1-mini-smoke-v2-001"
EXPECTED_SEEDS = (
    ("S-0008", 73193008, "b2-mini-smoke-engineering-ace-01"),
    ("S-0009", 73193009, "b2-mini-smoke-engineering-ace-02"),
)
EXPECTED_CONDA_META_SHA256 = "d95ae86c3d6c832777b8f571554388fd664044a79e7b8d62138453f58a991845"
EXPECTED_CONDA_HISTORY_SHA256 = "592f2e9842fc975efffc320703b4589b00dc01be4359506aa33930c59c2a0108"
EXPECTED_PIP_FREEZE_SHA256 = "c11b37406749e4ae2abc030bb7ae2c6bb12206a46321af4c45535465086be680"


class B2GateError(RuntimeError):
    """Raised before a model call when any frozen gate is not satisfied."""


class B2ExecutionError(RuntimeError):
    """Raised after a claim or model call; retained evidence must be inspected."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise B2GateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_object(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                B2GateError(f"non-finite JSON token: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise B2GateError(f"cannot read strict JSON object {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise B2GateError(f"JSON root must be an object: {source}")
    return value


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return bool(PLACEHOLDER_RE.search(value))
    if isinstance(value, Mapping):
        return any(
            _contains_placeholder(key) or _contains_placeholder(item) for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_placeholder(item) for item in value)
    return False


def exclusive_write_json(path: Path, value: Any) -> Path:
    payload = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path


def _repo_file(repository_root: Path, record: Mapping[str, Any], field: str) -> Path:
    relative = record.get("path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise B2GateError(f"{field}.path must be a repository-relative path")
    path = (repository_root / relative).resolve(strict=True)
    try:
        path.relative_to(repository_root)
    except ValueError as exc:
        raise B2GateError(f"{field}.path escapes the repository") from exc
    expected = record.get("sha256")
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
        raise B2GateError(f"{field}.sha256 must be lowercase SHA-256")
    actual = sha256_file(path)
    if actual != expected:
        raise B2GateError(f"{field} SHA-256 mismatch: {actual} != {expected}")
    return path


def _seed_rows(registry_text: str) -> dict[str, tuple[int, str]]:
    rows: dict[str, tuple[int, str]] = {}
    pattern = re.compile(r"^\|\s*(S-\d{4})\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
    for match in pattern.finditer(registry_text):
        rows[match.group(1)] = (int(match.group(2)), match.group(3).strip())
    return rows


def _assert_engineering_prompts_absent_from_benchmark_pool(
    repository_root: Path, prompt_ids: Sequence[str]
) -> None:
    prompt_root = repository_root / "prompts" / "v2"
    for source in sorted(prompt_root.rglob("*")):
        if not source.is_file() or source.name == "seed_registry.json":
            continue
        if source.suffix.lower() not in {".json", ".jsonl", ".md", ".txt"}:
            continue
        text = source.read_text(encoding="utf-8")
        for prompt_id in prompt_ids:
            if prompt_id in text:
                raise B2GateError(
                    f"engineering-only prompt ID leaked into benchmark prompt file: {source}"
                )


def validate_static_config(
    config_path: Path = DEFAULT_CONFIG,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the frozen package without constructing an adapter or touching CUDA."""

    config = read_json_object(config_path)
    if config.get("schema_version") != 2 or config.get("scope") != AUTHORIZATION_SCOPE:
        raise B2GateError("unexpected B2 config schema or scope")
    if config.get("protocol_status") != "PREPARED_NOT_AUTHORIZED":
        raise B2GateError("config must remain PREPARED_NOT_AUTHORIZED")
    scoring = config.get("scoring")
    expected_scoring = {
        "benchmark_endpoints_scored": False,
        "human_packet_member": False,
        "instrument_evaluation_allowed": False,
    }
    if scoring != expected_scoring:
        raise B2GateError("B2 mini-smoke must remain non-benchmark and unscored")

    caps = config.get("caps")
    expected_caps = {
        "exact_generated_outputs": 2,
        "exact_model_calls": 2,
        "max_clip_seconds": 30.0,
        "max_generated_outputs": 2,
        "max_gpu_seconds": 1800.0,
        "max_gpus": 1,
        "max_model_calls": 2,
        "max_retries": 0,
        "shared_b2_generation_ceiling": 10,
    }
    if caps != expected_caps:
        raise B2GateError("B2 exact plan or hard caps changed")

    authorization = config.get("authorization")
    if not isinstance(authorization, dict):
        raise B2GateError("authorization control is absent")
    if authorization.get("authorization_id") != AUTHORIZATION_ID:
        raise B2GateError("authorization ID changed")
    if authorization.get("model_call_authorized_by_this_config_alone") is not False:
        raise B2GateError("config must not authorize a model call by itself")
    if authorization.get("requires_completed_external_authorization") is not True:
        raise B2GateError("external authorization gate must remain required")
    if authorization.get("required_prereg_status") != "FROZEN_PROSPECTIVE_DESIGN":
        raise B2GateError("live prereg status gate changed")

    outer_timeout = config.get("outer_timeout")
    if not isinstance(outer_timeout, dict):
        raise B2GateError("frozen outer timeout control is absent")
    expected_outer_scalars = {
        "duration": "1800s",
        "kill_after": "30s",
        "pycache_prefix": "/tmp/pxy1289-b2-mini-smoke-v2-disabled-pycache",
        "python_executable": "/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python",
        "runner_relative_path": "scripts/run_b2_mini_smoke_v2.py",
        "timeout_executable": "/usr/bin/timeout",
    }
    if any(outer_timeout.get(key) != value for key, value in expected_outer_scalars.items()):
        raise B2GateError("outer GNU timeout command changed")
    wrapper_record = outer_timeout.get("wrapper")
    if not isinstance(wrapper_record, dict):
        raise B2GateError("frozen production wrapper binding is absent")
    wrapper_path = _repo_file(repository_root, wrapper_record, "outer_timeout.wrapper")
    if wrapper_path != (repository_root / "scripts/run_b2_mini_smoke_v2_with_timeout.py").resolve():
        raise B2GateError("production wrapper path changed")
    if not os.access(wrapper_path, os.X_OK):
        raise B2GateError("production wrapper is not executable")

    run = config.get("run")
    if not isinstance(run, dict) or run.get("fixed_run_id") != FIXED_RUN_ID:
        raise B2GateError("fixed one-shot run ID changed")
    if not SAFE_RUN_ID_RE.fullmatch(str(run.get("fixed_run_id", ""))):
        raise B2GateError("run ID is not a safe path component")

    jobs = config.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 2:
        raise B2GateError("exactly two jobs are required")
    seen_outputs: set[str] = set()
    seen_prompts: list[str] = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or job.get("index") != index:
            raise B2GateError("jobs must have contiguous frozen indices 0 and 1")
        seed_id, seed, prompt_id = EXPECTED_SEEDS[index]
        if (job.get("seed_id"), job.get("seed"), job.get("prompt_id")) != (
            seed_id,
            seed,
            prompt_id,
        ):
            raise B2GateError(f"job {index} seed or engineering prompt ID changed")
        if job.get("duration_seconds") != 30.0 or job.get("lyrics") != "":
            raise B2GateError(f"job {index} must be a 30-second instrumental call")
        prompt = job.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise B2GateError(f"job {index} prompt must be non-empty")
        output = job.get("output_relative_path")
        if not isinstance(output, str) or Path(output).is_absolute() or ".." in Path(output).parts:
            raise B2GateError(f"job {index} output must be a safe relative path")
        if not output.endswith(".wav") or output in seen_outputs:
            raise B2GateError(f"job {index} output path is invalid or duplicated")
        seen_outputs.add(output)
        seen_prompts.append(prompt_id)

    seed_record = config.get("frozen_sources", {}).get("seed_registry")
    if not isinstance(seed_record, dict):
        raise B2GateError("append-only seed registry binding is absent")
    seed_path = _repo_file(repository_root, seed_record, "frozen_sources.seed_registry")
    if seed_path != (repository_root / "SEED_REGISTRY.md").resolve():
        raise B2GateError("seeds must bind repository SEED_REGISTRY.md")
    parsed_seeds = _seed_rows(seed_path.read_text(encoding="utf-8"))
    for seed_id, seed, _prompt_id in EXPECTED_SEEDS:
        value = parsed_seeds.get(seed_id)
        if value is None or value[0] != seed or "B2 ACE-Step v1 mini-smoke" not in value[1]:
            raise B2GateError(f"{seed_id} is absent or not reserved for this B2 mini-smoke")
    _assert_engineering_prompts_absent_from_benchmark_pool(repository_root, seen_prompts)

    hashes: dict[str, str] = {
        "b2_config": sha256_file(config_path),
        "b2_wrapper": sha256_file(wrapper_path),
    }
    frozen_sources = config.get("frozen_sources")
    if not isinstance(frozen_sources, dict):
        raise B2GateError("frozen_sources must be an object")
    for name, record in sorted(frozen_sources.items()):
        if not isinstance(record, dict):
            raise B2GateError(f"frozen source {name} is not an object")
        path = _repo_file(repository_root, record, f"frozen_sources.{name}")
        hashes[name] = sha256_file(path)
    backbone = config.get("backbone")
    if not isinstance(backbone, dict):
        raise B2GateError("backbone control is absent")
    ace_config_record = backbone.get("config")
    if not isinstance(ace_config_record, dict):
        raise B2GateError("ACE backbone config binding is absent")
    ace_config_path = _repo_file(repository_root, ace_config_record, "backbone.config")
    hashes["ace_config"] = sha256_file(ace_config_path)
    ace_config = read_json_object(ace_config_path)
    checkpoint = ace_config.get("checkpoint")
    provenance = ace_config.get("provenance")
    if not isinstance(checkpoint, dict) or not isinstance(provenance, dict):
        raise B2GateError("ACE config checkpoint/provenance bindings are absent")
    required_files = checkpoint.get("required_files")
    if not isinstance(required_files, list):
        raise B2GateError("ACE exact checkpoint manifest is absent")
    if checkpoint.get("exact_tree_sha256") != backbone.get(
        "required_checkpoint_tree_sha256"
    ) or len(required_files) != backbone.get("required_checkpoint_file_count"):
        raise B2GateError("B2 config and ACE exact checkpoint tree binding differ")
    if provenance.get("upstream_code_revision") != backbone.get(
        "required_source_revision"
    ) or provenance.get("upstream_code_tree") != backbone.get("required_source_tree"):
        raise B2GateError("B2 config and ACE exact source tree binding differ")
    template = authorization.get("template")
    if not isinstance(template, dict):
        raise B2GateError("authorization template binding is absent")
    template_path = _repo_file(repository_root, template, "authorization.template")
    hashes["authorization_template"] = sha256_file(template_path)

    runtime = config.get("runtime_environment")
    required_runtime = {
        "python_executable": "/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python",
        "python_prefix": "/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm",
        "python_version": "3.10.20",
        "conda_meta_manifest_sha256": EXPECTED_CONDA_META_SHA256,
        "conda_meta_history_sha256": EXPECTED_CONDA_HISTORY_SHA256,
        "pip_freeze_sorted_sha256": EXPECTED_PIP_FREEZE_SHA256,
        "conda_executable_available": False,
    }
    if not isinstance(runtime, dict) or any(
        runtime.get(key) != value for key, value in required_runtime.items()
    ):
        raise B2GateError("ACE audio-prm runtime identity changed")
    return config, hashes


def _latest_assignment(text: str, name: str) -> str | None:
    pattern = re.compile(rf"(?m)^\s*(?:[-*]\s*)?`?{re.escape(name)}\s*=\s*([^`\r\n]+?)`?\s*$")
    matches = list(pattern.finditer(text))
    return matches[-1].group(1).strip() if matches else None


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise B2GateError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise B2GateError(f"invalid {field}: {value!r}") from exc
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise B2GateError(f"{field} must carry a UTC offset")
    return parsed


def _git_capture(repository_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    try:
        branch = run("symbolic-ref", "--quiet", "--short", "HEAD")
        head = run("rev-parse", "HEAD")
        origin_main = run("rev-parse", "origin/main")
        status = run("status", "--porcelain=v1", "--untracked-files=all")
    except subprocess.CalledProcessError as exc:
        raise B2GateError(f"Git clean-origin probe failed: {exc}") from exc
    return {
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "status_porcelain_v1": status.splitlines() if status else [],
        "clean": not status,
    }


def expected_outer_commands(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    authorization_path: Path,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, list[str]]:
    """Construct the sole frozen production wrapper and GNU-timeout commands."""

    outer = config["outer_timeout"]
    wrapper = repository_root / outer["wrapper"]["path"]
    runner = repository_root / outer["runner_relative_path"]
    python = outer["python_executable"]
    forwarded = [
        "--config",
        str(config_path.resolve(strict=True)),
        "--authorization",
        str(authorization_path.resolve(strict=True)),
        "--run-id",
        FIXED_RUN_ID,
        "--execute",
        config["authorization"]["required_execute_phrase"],
    ]
    production = [python, str(wrapper.resolve(strict=True)), *forwarded]
    timeout = [
        outer["timeout_executable"],
        "-k",
        outer["kill_after"],
        outer["duration"],
        python,
        "-B",
        "-X",
        f"pycache_prefix={outer['pycache_prefix']}",
        str(runner.resolve(strict=True)),
        *forwarded,
    ]
    return {"production_wrapper_command": production, "outer_timeout_command": timeout}


def _strict_json_string_list(value: str | None, field: str) -> list[str]:
    if value is None:
        raise B2GateError(f"{field} is absent")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise B2GateError(f"{field} is not valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise B2GateError(f"{field} must be a JSON string array")
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
    """Prove the live runner is a child of the exact frozen GNU timeout argv."""

    expected = expected_outer_commands(
        config=config,
        config_path=config_path,
        authorization_path=authorization_path,
        repository_root=repository_root,
    )
    production_env = _strict_json_string_list(
        os.environ.get("B2_OUTER_PRODUCTION_COMMAND_JSON"),
        "B2_OUTER_PRODUCTION_COMMAND_JSON",
    )
    timeout_env = _strict_json_string_list(
        os.environ.get("B2_OUTER_TIMEOUT_COMMAND_JSON"),
        "B2_OUTER_TIMEOUT_COMMAND_JSON",
    )
    if production_env != expected["production_wrapper_command"]:
        raise B2GateError("recorded production wrapper command differs from the frozen command")
    if timeout_env != expected["outer_timeout_command"]:
        raise B2GateError("recorded outer timeout command differs from the frozen command")
    outer = config["outer_timeout"]
    wrapper_path = (repository_root / outer["wrapper"]["path"]).resolve(strict=True)
    if os.environ.get("B2_PRODUCTION_WRAPPER_PATH") != str(wrapper_path):
        raise B2GateError("production wrapper path evidence is absent or changed")
    if os.environ.get("B2_PRODUCTION_WRAPPER_SHA256") != sha256_file(wrapper_path):
        raise B2GateError("production wrapper SHA-256 evidence is absent or changed")
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1" or not sys.dont_write_bytecode:
        raise B2GateError("production runner must use -B and PYTHONDONTWRITEBYTECODE=1")
    if sys.pycache_prefix != outer["pycache_prefix"]:
        raise B2GateError("process sys.pycache_prefix differs from the frozen alternate prefix")
    if os.path.lexists(outer["pycache_prefix"]):
        raise B2GateError("alternate pycache prefix was not absent at runner preflight")

    observed_parent_pid = os.getppid() if parent_pid is None else parent_pid
    if proc_executable is None:
        proc_executable = str(Path(f"/proc/{observed_parent_pid}/exe").resolve(strict=True))
    if proc_command is None:
        raw = Path(f"/proc/{observed_parent_pid}/cmdline").read_bytes()
        proc_command = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    if proc_executable != outer["timeout_executable"]:
        raise B2GateError("runner parent executable is not the frozen /usr/bin/timeout")
    if list(proc_command) != expected["outer_timeout_command"]:
        raise B2GateError("runner parent argv is not exact GNU timeout -k 30s 1800s")
    if timeout_version is None:
        timeout_version = subprocess.run(
            [outer["timeout_executable"], "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
    if "GNU coreutils" not in timeout_version:
        raise B2GateError("frozen timeout executable is not GNU coreutils timeout")
    return {
        **expected,
        "outer_timeout_command_shell": shlex.join(expected["outer_timeout_command"]),
        "production_wrapper_command_shell": shlex.join(expected["production_wrapper_command"]),
        "parent_pid": observed_parent_pid,
        "parent_executable": proc_executable,
        "parent_argv": list(proc_command),
        "timeout_version": timeout_version,
        "kill_after": outer["kill_after"],
        "duration": outer["duration"],
        "python_dont_write_bytecode": sys.dont_write_bytecode,
        "python_pycache_prefix": sys.pycache_prefix,
        "pycache_prefix_absent": True,
    }


def _expected_decisions_assignments(
    config: Mapping[str, Any], hashes: Mapping[str, str], authorization: Mapping[str, Any]
) -> dict[str, str]:
    prereg = authorization["frozen_artifacts"]["benchmark_prereg_v2"]["sha256"]
    return {
        "BENCHMARK_PREREG_V2_FROZEN": "YES",
        "BENCHMARK_PREREG_V2_SHA256": prereg,
        "B2_MINI_SMOKE_V2_AUTHORIZED": "YES",
        "B2_MINI_SMOKE_V2_SCOPE": AUTHORIZATION_SCOPE,
        "B2_MINI_SMOKE_V2_CONFIG_SHA256": hashes["b2_config"],
        "B2_MINI_SMOKE_V2_PROTOCOL_SHA256": hashes["protocol"],
        "B2_MINI_SMOKE_V2_RUNNER_SHA256": authorization["frozen_artifacts"]["b2_runner"]["sha256"],
        "B2_MINI_SMOKE_V2_WRAPPER_SHA256": hashes["b2_wrapper"],
        "B2_MINI_SMOKE_V2_AUTH_TEMPLATE_SHA256": hashes["authorization_template"],
        "B2_MINI_SMOKE_V2_SEED_REGISTRY_SHA256": hashes["seed_registry"],
        "B2_MINI_SMOKE_V2_ACE_CONFIG_SHA256": hashes["ace_config"],
        "B2_MINI_SMOKE_V2_ACE_ADAPTER_SHA256": hashes["ace_adapter"],
        "B2_MINI_SMOKE_V2_COMMON_FACTORY_SHA256": hashes["common_factory"],
        "B2_MINI_SMOKE_V2_COMMON_RUNNER_SHA256": hashes["common_mini_smoke"],
        "B2_MINI_SMOKE_V2_BACKBONES_INIT_SHA256": hashes["backbones_init"],
        "B2_MINI_SMOKE_V2_COMMON_CONTRACTS_SHA256": hashes["common_contracts"],
        "B2_MINI_SMOKE_V2_COMMON_IO_SHA256": hashes["common_io"],
        "B2_MINI_SMOKE_V2_COMMON_RUNTIME_SHA256": hashes["common_runtime"],
        "B2_MINI_SMOKE_V2_SA3_ARTIFACTS_SHA256": hashes["sa3_artifacts"],
        "B2_MINI_SMOKE_V2_SA3_AUDIO_SHA256": hashes["sa3_audio"],
        "B2_MINI_SMOKE_V2_ACE_CHECKPOINT_TREE_SHA256": config["backbone"][
            "required_checkpoint_tree_sha256"
        ],
        "B2_MINI_SMOKE_V2_ACE_SOURCE_TREE": config["backbone"]["required_source_tree"],
        "B2_MINI_SMOKE_V2_RUNTIME_CONDA_META_SHA256": config["runtime_environment"][
            "conda_meta_manifest_sha256"
        ],
        "B2_MINI_SMOKE_V2_RUNTIME_PIP_FREEZE_SHA256": config["runtime_environment"][
            "pip_freeze_sorted_sha256"
        ],
        "B2_MINI_SMOKE_V2_MAX_MODEL_CALLS": "2",
        "B2_MINI_SMOKE_V2_MAX_GENERATED_OUTPUTS": "2",
        "B2_MINI_SMOKE_V2_MAX_CLIP_SECONDS": "30",
        "B2_MINI_SMOKE_V2_MAX_GPUS": "1",
        "B2_MINI_SMOKE_V2_MAX_GPU_SECONDS": "1800",
        "B2_MINI_SMOKE_V2_RETRIES": "0",
        "B2_MINI_SMOKE_V2_PROMPT_IDS": (
            "b2-mini-smoke-engineering-ace-01,b2-mini-smoke-engineering-ace-02"
        ),
        "B2_MINI_SMOKE_V2_RESERVED_NON_BENCHMARK_SEEDS": ("S-0008:73193008,S-0009:73193009"),
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
    """Validate governance, file hashes, one-shot binding, expiry, and clean origin."""

    authorization = read_json_object(authorization_path)
    if _contains_placeholder(authorization):
        raise B2GateError("authorization is still a template or contains a placeholder")
    if authorization.get("schema_version") != 2:
        raise B2GateError("authorization schema_version must equal 2")
    if authorization.get("authorization_id") != AUTHORIZATION_ID:
        raise B2GateError("authorization ID mismatch")
    if authorization.get("scope") != AUTHORIZATION_SCOPE:
        raise B2GateError("authorization scope mismatch")
    if authorization.get("execution_authorized") is not True:
        raise B2GateError("external authorization must contain boolean true")
    if authorization.get("benchmark_endpoint") is not False:
        raise B2GateError("authorization must label this as non-benchmark")
    if (
        authorization.get("required_prereg_status")
        != config["authorization"]["required_prereg_status"]
    ):
        raise B2GateError("authorization does not bind the frozen prereg status")
    if authorization.get("run_id") != FIXED_RUN_ID:
        raise B2GateError("authorization does not bind the fixed one-shot run ID")
    expected_caps = {
        "max_clip_seconds": 30.0,
        "max_generated_outputs": 2,
        "max_gpu_seconds": 1800.0,
        "max_gpus": 1,
        "max_model_calls": 2,
        "max_retries": 0,
    }
    if authorization.get("caps") != expected_caps:
        raise B2GateError("authorization caps differ from the exact two-call plan")
    expected_reserved = [
        {"prompt_id": prompt_id, "seed": seed, "seed_id": seed_id}
        for seed_id, seed, prompt_id in EXPECTED_SEEDS
    ]
    if authorization.get("reserved_non_benchmark_seeds") != expected_reserved:
        raise B2GateError("authorization does not bind S-0008/S-0009 to both engineering prompts")

    authorized_at = _parse_utc(authorization.get("authorized_at_utc"), "authorized_at_utc")
    expires_at = _parse_utc(authorization.get("expires_at_utc"), "expires_at_utc")
    current = now or datetime.now(timezone.utc)
    if current < authorized_at or current > expires_at:
        raise B2GateError("external authorization is not currently valid")
    if (expires_at - authorized_at).total_seconds() > 24 * 60 * 60:
        raise B2GateError("external authorization may be valid for at most 24 hours")

    frozen = authorization.get("frozen_artifacts")
    if not isinstance(frozen, dict):
        raise B2GateError("authorization frozen_artifacts are absent")
    expected_artifacts = {
        "ace_adapter": hashes["ace_adapter"],
        "ace_config": hashes["ace_config"],
        "authorization_template": hashes["authorization_template"],
        "b2_config": hashes["b2_config"],
        "b2_protocol": hashes["protocol"],
        "b2_runner": sha256_file(runner_path),
        "b2_wrapper": hashes["b2_wrapper"],
        "backbones_init": hashes["backbones_init"],
        "common_contracts": hashes["common_contracts"],
        "common_factory": hashes["common_factory"],
        "common_io": hashes["common_io"],
        "common_mini_smoke": hashes["common_mini_smoke"],
        "common_runtime": hashes["common_runtime"],
        "sa3_artifacts": hashes["sa3_artifacts"],
        "sa3_audio": hashes["sa3_audio"],
        "seed_registry": hashes["seed_registry"],
    }
    for name, expected_hash in expected_artifacts.items():
        record = frozen.get(name)
        if not isinstance(record, dict) or record.get("sha256") != expected_hash:
            raise B2GateError(f"authorization does not bind live {name} SHA-256")
        _repo_file(repository_root, record, f"authorization.frozen_artifacts.{name}")
    prereg_record = frozen.get("benchmark_prereg_v2")
    if not isinstance(prereg_record, dict):
        raise B2GateError("authorization lacks frozen BENCHMARK_PREREG_v2.md")
    prereg_path = _repo_file(repository_root, prereg_record, "benchmark_prereg_v2")
    prereg_text = prereg_path.read_text(encoding="utf-8")
    prereg_status = re.search(r"(?m)^- Status: `([^`]+)`\s*$", prereg_text)
    if prereg_status is None or prereg_status.group(1) != authorization["required_prereg_status"]:
        raise B2GateError("live BENCHMARK_PREREG_v2.md status is not frozen")
    if _latest_assignment(prereg_text, "BENCHMARK_PREREG_V2_FROZEN") != "YES":
        raise B2GateError("live BENCHMARK_PREREG_v2.md does not declare its frozen marker YES")

    runtime_authorized = authorization.get("runtime_environment")
    if runtime_authorized != config.get("runtime_environment"):
        raise B2GateError("authorization does not bind the exact ACE runtime identity")
    source_bindings = authorization.get("source_bindings")
    expected_source = {
        "checkpoint_dir": config["backbone"]["required_checkpoint_dir"],
        "checkpoint_exact_file_count": config["backbone"]["required_checkpoint_file_count"],
        "checkpoint_manifest_exclusions": [],
        "checkpoint_tree_sha256": config["backbone"]["required_checkpoint_tree_sha256"],
        "source_dir": config["backbone"]["required_source_dir"],
        "source_revision": config["backbone"]["required_source_revision"],
        "source_tree": config["backbone"]["required_source_tree"],
        "source_untracked_exception": "ONLY_CPYTHON_310_PYCACHE_NOT_READ_UNDER_ALTERNATE_PREFIX",
    }
    if source_bindings != expected_source:
        raise B2GateError("authorization source/checkpoint bindings changed")

    decisions_path = repository_root / "DECISIONS.md"
    decisions_hash = sha256_file(decisions_path)
    if authorization.get("decisions_sha256") != decisions_hash:
        raise B2GateError("authorization does not bind the live post-append DECISIONS.md")
    decisions_text = decisions_path.read_text(encoding="utf-8")
    expected_assignments = _expected_decisions_assignments(config, hashes, authorization)
    configured_names = config["authorization"]["required_decisions_assignments"]
    if set(configured_names) != set(expected_assignments):
        raise B2GateError("config required DECISIONS assignment list is incomplete")
    for name, expected in expected_assignments.items():
        observed = _latest_assignment(decisions_text, name)
        if observed != expected:
            raise B2GateError(
                f"latest DECISIONS assignment {name} is {observed!r}, not {expected!r}"
            )

    git = dict(git_evidence or _git_capture(repository_root))
    origin = authorization.get("origin")
    if not isinstance(origin, dict):
        raise B2GateError("authorization origin binding is absent")
    commit = origin.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise B2GateError("authorization origin commit must be a full Git SHA")
    if origin.get("branch") != "main" or origin.get("remote_tracking_ref") != "origin/main":
        raise B2GateError("authorization must bind main and origin/main")
    if not git.get("clean"):
        raise B2GateError("repository is not clean, including untracked files")
    if git.get("branch") != "main":
        raise B2GateError("repository is not on main")
    if git.get("head") != commit or git.get("origin_main") != commit:
        raise B2GateError("authorized commit must equal clean HEAD and local origin/main")
    return authorization, {"decisions_sha256": decisions_hash, "git": git}


def capture_runtime_environment(
    config: Mapping[str, Any],
    *,
    command_runner: Callable[[Sequence[str]], str] | None = None,
) -> dict[str, Any]:
    """Capture and validate audio-prm without treating the SA3 freeze as ACE evidence."""

    expected = config["runtime_environment"]
    expected_python = Path(expected["python_executable"]).resolve(strict=True)
    observed_python = Path(sys.executable).resolve(strict=True)
    if observed_python != expected_python:
        raise B2GateError(f"must run with {expected_python}, not {observed_python}")
    observed_prefix = Path(sys.prefix).resolve(strict=True)
    if observed_prefix != Path(expected["python_prefix"]).resolve(strict=True):
        raise B2GateError("Python prefix is not the frozen audio-prm environment")
    if platform.python_version() != expected["python_version"]:
        raise B2GateError("audio-prm Python patch version drifted")

    conda_meta = observed_prefix / "conda-meta"
    rows = [
        {"path": source.name, "sha256": sha256_file(source), "size_bytes": source.stat().st_size}
        for source in sorted(conda_meta.glob("*.json"))
    ]
    if not rows:
        raise B2GateError("audio-prm conda-meta package records are absent")
    conda_manifest_hash = hashlib.sha256(
        _canonical_json([{"path": row["path"], "sha256": row["sha256"]} for row in rows])
    ).hexdigest()
    history_path = conda_meta / "history"
    history_hash = sha256_file(history_path)

    if command_runner is None:

        def command_runner(command: Sequence[str]) -> str:
            return subprocess.run(list(command), check=True, capture_output=True, text=True).stdout

    pip_output = command_runner([str(expected_python), "-m", "pip", "freeze", "--all"])
    pip_lines = sorted(line.strip() for line in pip_output.splitlines() if line.strip())
    normalized_pip = "\n".join(pip_lines) + "\n"
    pip_hash = hashlib.sha256(normalized_pip.encode("utf-8")).hexdigest()
    observed_hashes = {
        "conda_meta_manifest_sha256": conda_manifest_hash,
        "conda_meta_history_sha256": history_hash,
        "pip_freeze_sorted_sha256": pip_hash,
    }
    for name, value in observed_hashes.items():
        if value != expected[name]:
            raise B2GateError(f"ACE audio-prm environment drift: {name}={value}")
    if not any(
        line.startswith("-e git+https://github.com/ace-step/ACE-Step.git@1bee4c9f")
        for line in pip_lines
    ):
        raise B2GateError("audio-prm does not expose the exact editable ACE-Step source commit")
    identity_hash = hashlib.sha256(
        _canonical_json(
            {
                **observed_hashes,
                "python_executable": str(observed_python),
                "python_prefix": str(observed_prefix),
                "python_version": platform.python_version(),
            }
        )
    ).hexdigest()
    return {
        "captured_at_utc": _utc_now(),
        "python_executable": str(observed_python),
        "python_prefix": str(observed_prefix),
        "python_version": platform.python_version(),
        "conda_executable_available": False,
        "conda_meta_files": rows,
        "conda_meta_manifest_sha256": conda_manifest_hash,
        "conda_meta_history_sha256": history_hash,
        "pip_freeze_sorted_lines": pip_lines,
        "pip_freeze_sorted_sha256": pip_hash,
        "environment_identity_sha256": identity_hash,
        "snapshot_limitation": expected["snapshot_limitation"],
    }


def _capture_command(command: Sequence[str]) -> str:
    return subprocess.run(list(command), check=True, capture_output=True, text=True).stdout


def probe_gpu(
    physical_gpu_id: int,
    *,
    minimum_free_mib: int,
    maximum_utilization_percent: int,
    required_name_substring: str,
    allowed_compute_pids: set[int],
    command_runner: Callable[[Sequence[str]], str] = _capture_command,
) -> dict[str, Any]:
    gpu_output = command_runner(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.free,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    gpu_rows: list[dict[str, Any]] = []
    for line in gpu_output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 6:
            raise B2GateError(f"unexpected nvidia-smi GPU row: {line!r}")
        gpu_rows.append(
            {
                "index": int(fields[0]),
                "uuid": fields[1],
                "name": fields[2],
                "memory_free_mib": int(fields[3]),
                "memory_total_mib": int(fields[4]),
                "utilization_gpu_percent": int(fields[5]),
            }
        )
    selected = [row for row in gpu_rows if row["index"] == physical_gpu_id]
    if len(selected) != 1:
        raise B2GateError(f"physical GPU {physical_gpu_id} was not found exactly once")
    gpu = selected[0]
    process_output = command_runner(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    active: list[dict[str, Any]] = []
    for line in process_output.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3:
            raise B2GateError(f"unexpected nvidia-smi process row: {line!r}")
        if fields[0] == gpu["uuid"]:
            active.append(
                {"gpu_uuid": fields[0], "pid": int(fields[1]), "used_memory_mib": int(fields[2])}
            )
    neighbor_pids = sorted(row["pid"] for row in active if row["pid"] not in allowed_compute_pids)
    checks = {
        "required_gpu_name": required_name_substring in gpu["name"],
        "minimum_free_memory": gpu["memory_free_mib"] >= minimum_free_mib,
        "low_utilization": gpu["utilization_gpu_percent"] <= maximum_utilization_percent,
        "no_neighbor_compute_process": not neighbor_pids,
        "one_visible_physical_gpu": os.environ.get("CUDA_VISIBLE_DEVICES") == str(physical_gpu_id),
    }
    if not all(checks.values()):
        raise B2GateError(
            f"GPU idle/headroom gate failed without preemption: checks={checks}, "
            f"gpu={gpu}, neighbor_pids={neighbor_pids}"
        )
    return {
        "captured_at_utc": _utc_now(),
        "physical_gpu_id": physical_gpu_id,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "process_visible_device": "cuda:0",
        "process_visible_index": 0,
        "physical_to_process_mapping": f"physical GPU {physical_gpu_id} -> cuda:0",
        "selected_gpu": gpu,
        "active_compute_processes": active,
        "allowed_compute_pids": sorted(allowed_compute_pids),
        "neighbor_pids": neighbor_pids,
        "minimum_free_memory_mib": minimum_free_mib,
        "maximum_utilization_percent": maximum_utilization_percent,
        "checks": checks,
    }


@contextmanager
def device_lock(lock_path: Path) -> Iterator[Path]:
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise B2GateError(f"GPU lock is already held: {lock_path}") from exc
        yield lock_path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_external_root(path_value: Any, repository_root: Path, field: str) -> Path:
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise B2GateError(f"{field} must be an absolute external path")
    path = Path(path_value)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise B2GateError(f"{field} must be outside the repository")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            raise B2GateError(f"{field} contains a symlink component: {current}")
    return resolved


class DurableLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = path.open("xb")
        self._previous = "0" * 64

    def append(self, event: str, details: Mapping[str, Any]) -> str:
        row = {
            "at_utc": _utc_now(),
            "event": event,
            "details": dict(details),
            "previous_row_sha256": self._previous,
        }
        digest = hashlib.sha256(_canonical_json(row)).hexdigest()
        row["row_sha256"] = digest
        self._handle.write(_canonical_json(row) + b"\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._previous = digest
        return digest

    def close(self) -> None:
        self._handle.close()


class ClaimingAdapter:
    """Insert a durable one-call claim and neighbor probe before each delegate call."""

    def __init__(
        self,
        delegate: Any,
        *,
        jobs: Sequence[Mapping[str, Any]],
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
        self._jobs = {str(job["prompt_id"]): dict(job) for job in jobs}
        self._claim_dir = claim_dir
        self._claim_context = dict(claim_context)
        self._placement = placement
        self._physical_gpu_id = physical_gpu_id
        self._deadline_monotonic = deadline_monotonic
        self._logger = logger
        self._gpu_probe = gpu_probe
        self._behavior_identity_probe = behavior_identity_probe
        self._claimed: set[int] = set()
        self._previous_claim_hash = "0" * 64
        for name in ("model_id", "logical_name", "config_sha256", "license_identifier"):
            setattr(self, name, getattr(delegate, name))

    def preflight(self) -> Any:
        return self._delegate.preflight()

    def generate(self, request: Any) -> Any:
        if time.monotonic() >= self._deadline_monotonic:
            raise B2ExecutionError("1,800-second deadline elapsed before the next model call")
        job = self._jobs.get(request.prompt_id)
        if job is None:
            raise B2ExecutionError(f"unplanned prompt reached adapter: {request.prompt_id}")
        index = int(job["index"])
        if index in self._claimed:
            raise B2ExecutionError(f"implicit retry forbidden for call {index}")
        behavior_identity = (
            dict(self._behavior_identity_probe())
            if self._behavior_identity_probe is not None
            else {"test_injection": "NO_PRODUCTION_IDENTITY_PROBE"}
        )
        allowed_pids = set() if index == 0 else {os.getpid()}
        minimum_free = (
            self._placement["minimum_free_memory_before_claim_mib"]
            if index == 0
            else self._placement["minimum_free_memory_before_subsequent_call_mib"]
        )
        live = self._gpu_probe(
            self._physical_gpu_id,
            minimum_free_mib=int(minimum_free),
            maximum_utilization_percent=int(self._placement["max_idle_utilization_percent"]),
            required_name_substring=str(self._placement["required_gpu_name_substring"]),
            allowed_compute_pids=allowed_pids,
        )
        if time.monotonic() >= self._deadline_monotonic:
            raise B2ExecutionError("1,800-second deadline elapsed during per-call preflight")
        claim = {
            **self._claim_context,
            "claim_type": "PER_MODEL_CALL_DURABLE_RESERVATION",
            "claimed_at_utc": _utc_now(),
            "generation_index": index,
            "prompt_id": request.prompt_id,
            "seed_id": request.seed_id,
            "seed": request.seed,
            "duration_seconds": request.duration_seconds,
            "output_path": str(request.output_path),
            "live_placement": live,
            "immediate_behavior_identity": behavior_identity,
            "previous_call_claim_sha256": self._previous_claim_hash,
        }
        claim_path = self._claim_dir / f"call-{index:02d}.claim.json"
        exclusive_write_json(claim_path, claim)
        claim_hash = sha256_file(claim_path)
        self._previous_claim_hash = claim_hash
        self._claimed.add(index)
        self._logger.append(
            "PER_CALL_CLAIM_DURABLE",
            {"generation_index": index, "path": str(claim_path), "sha256": claim_hash},
        )
        return self._delegate.generate(request)


@contextmanager
def elapsed_deadline(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        raise ValueError("deadline must be positive")
    if not hasattr(signal, "setitimer") or signal.getsignal(signal.SIGALRM) is signal.SIG_IGN:
        raise B2GateError("POSIX interval timer is required for the Python deadline")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expired(_signum: int, _frame: Any) -> None:
        raise B2ExecutionError("Python 1,800-second execution deadline expired")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def validate_ledger_chain(ledger_path: Path, expected_count: int = 2) -> dict[str, Any]:
    previous = "0" * 64
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("previous_row_sha256") != previous:
            raise B2ExecutionError("generation ledger previous-hash chain is invalid")
        claimed_hash = row.get("row_sha256")
        unhashed = dict(row)
        unhashed.pop("row_sha256", None)
        actual_hash = hashlib.sha256(_canonical_json(unhashed)).hexdigest()
        if claimed_hash != actual_hash:
            raise B2ExecutionError("generation ledger row SHA-256 is invalid")
        previous = actual_hash
        rows.append(row)
    if len(rows) != expected_count:
        raise B2ExecutionError(f"ledger has {len(rows)} rows, expected {expected_count}")
    return {"rows": rows, "ledger_tail_sha256": previous, "ledger_sha256": sha256_file(ledger_path)}


def _hostname_node() -> str:
    return socket.gethostname().split(".", maxsplit=1)[0]


def _source_environment(config: Mapping[str, Any]) -> dict[str, str]:
    backbone = config["backbone"]
    expected = {
        backbone["required_checkpoint_environment_variable"]: backbone["required_checkpoint_dir"],
        backbone["required_source_environment_variable"]: backbone["required_source_dir"],
    }
    for name, value in expected.items():
        observed = os.environ.get(name)
        if observed != value or Path(observed).resolve(strict=True) != Path(value).resolve(
            strict=True
        ):
            raise B2GateError(f"{name} must resolve exactly to {value}")
    return expected


def execute_b2_mini_smoke(
    *,
    config_path: Path,
    authorization_path: Path,
    execute_phrase: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Execute only after all gates pass; this is the sole model-calling function."""

    config, hashes = validate_static_config(config_path, repository_root=repository_root)
    required_phrase = config["authorization"]["required_execute_phrase"]
    if execute_phrase != required_phrase:
        raise B2GateError("explicit two-model-call execute phrase is absent or incorrect")
    outer_boundary = capture_outer_timeout_boundary(
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
    )
    source_environment = _source_environment(config)
    runtime = capture_runtime_environment(config)

    placement = config["placement"]
    authorization_placement = authorization["placement"]
    node = _hostname_node()
    physical_gpu_id = authorization_placement.get("physical_gpu_id")
    if node not in placement["allowed_nodes"] or authorization_placement.get("node") != node:
        raise B2GateError("live node is not authorized an12/an29 placement")
    if physical_gpu_id not in placement["allowed_physical_gpu_ids"]:
        raise B2GateError("authorization physical GPU ID is outside 0..7")
    if authorization_placement.get("tensor_parallel_width") != 1:
        raise B2GateError("authorization must use TP1")
    if authorization_placement.get("replica_count") != 1:
        raise B2GateError("authorization must use one replica")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != str(physical_gpu_id):
        raise B2GateError("CUDA_VISIBLE_DEVICES must bind the authorized physical GPU exactly")
    gpu_mapping = {
        "physical_gpu_id": physical_gpu_id,
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
        "process_visible_device": "cuda:0",
        "process_visible_index": 0,
        "mapping": f"physical GPU {physical_gpu_id} -> process-visible cuda:0",
    }

    run_control = config["run"]
    run_root = _validate_external_root(run_control["run_root"], repository_root, "run_root")
    log_root = _validate_external_root(run_control["log_root"], repository_root, "log_root")
    claim_root = _validate_external_root(run_control["claim_root"], repository_root, "claim_root")
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
        initial_placement = probe_gpu(
            int(physical_gpu_id),
            minimum_free_mib=int(placement["minimum_free_memory_before_claim_mib"]),
            maximum_utilization_percent=int(placement["max_idle_utilization_percent"]),
            required_name_substring=str(placement["required_gpu_name_substring"]),
            allowed_compute_pids=set(),
        )

        run_root.mkdir(parents=True, exist_ok=True)
        log_root.mkdir(parents=True, exist_ok=True)
        claim_root.mkdir(parents=True, exist_ok=True)
        claim_dir.mkdir(parents=False, exist_ok=False)
        logger = DurableLog(log_path)
        started_at = _utc_now()
        command = outer_boundary["outer_timeout_command_shell"]
        try:
            runtime_path = claim_dir / "runtime-environment-preclaim.json"
            exclusive_write_json(runtime_path, runtime)
            authorization_evidence = {
                "authorization_path": str(authorization_path.resolve()),
                "authorization_sha256": sha256_file(authorization_path),
                "config_path": str(config_path.resolve()),
                "config_sha256": hashes["b2_config"],
                "runner_path": str(DEFAULT_RUNNER),
                "runner_sha256": sha256_file(DEFAULT_RUNNER),
                "governance": governance,
                "source_environment": source_environment,
                "runtime_environment_path": str(runtime_path),
                "runtime_environment_sha256": sha256_file(runtime_path),
                "initial_placement": initial_placement,
                "gpu_mapping": gpu_mapping,
                "outer_timeout_boundary": outer_boundary,
                "lock_path": str(lock_path),
                "lock_held": True,
            }
            preclaim_path = claim_dir / "authorization-and-placement-preclaim.json"
            exclusive_write_json(preclaim_path, authorization_evidence)
            logger.append(
                "PRECLAIM_VALIDATION_PASS",
                {"path": str(preclaim_path), "sha256": sha256_file(preclaim_path)},
            )

            if str(SOURCE_ROOT) not in sys.path:
                sys.path.insert(0, str(SOURCE_ROOT))
            source_dir = source_environment[
                config["backbone"]["required_source_environment_variable"]
            ]
            if source_dir not in sys.path:
                sys.path.insert(1, source_dir)
            from backbones.ace_step_v1 import AceStepV1Adapter, verify_exact_checkpoint_tree
            from backbones.contracts import GenerationRequest
            from backbones.mini_smoke import MiniSmokeJob, RunContext, run_mini_smoke
            from backbones.runtime import verify_clean_git_revision

            adapter = AceStepV1Adapter(
                config_path=repository_root / config["backbone"]["config"]["path"],
                evidence_dir=claim_dir / "adapter-preflight-evidence",
            )
            adapter_preflight = adapter.preflight()
            if adapter_preflight.status != "READY_FOR_MINI_SMOKE":
                raise B2GateError(f"ACE adapter preflight returned {adapter_preflight.status}")
            preflight_path = claim_dir / "adapter-preflight.json"
            exclusive_write_json(
                preflight_path,
                {
                    "status": adapter_preflight.status,
                    "model_id": adapter_preflight.model_id,
                    "config_sha256": adapter_preflight.config_sha256,
                    "details": dict(adapter_preflight.details),
                },
            )
            immediate_placement = probe_gpu(
                int(physical_gpu_id),
                minimum_free_mib=int(placement["minimum_free_memory_before_claim_mib"]),
                maximum_utilization_percent=int(placement["max_idle_utilization_percent"]),
                required_name_substring=str(placement["required_gpu_name_substring"]),
                allowed_compute_pids=set(),
            )
            global_claim = {
                "authorization_id": AUTHORIZATION_ID,
                "claim_type": "ONE_SHOT_TWO_MODEL_CALL_EXECUTION",
                "claimed_at_utc": _utc_now(),
                "run_id": FIXED_RUN_ID,
                "scope": AUTHORIZATION_SCOPE,
                "benchmark_endpoint": False,
                "config_sha256": hashes["b2_config"],
                "runner_sha256": sha256_file(DEFAULT_RUNNER),
                "authorization_sha256": sha256_file(authorization_path),
                "decisions_sha256": governance["decisions_sha256"],
                "origin_commit": governance["git"]["head"],
                "caps": config["caps"],
                "exact_jobs": config["jobs"],
                "runtime_environment_sha256": sha256_file(runtime_path),
                "adapter_preflight_sha256": sha256_file(preflight_path),
                "immediate_preclaim_placement": immediate_placement,
                "node": node,
                "physical_gpu_id": physical_gpu_id,
                "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                "process_visible_device": "cuda:0",
                "outer_timeout_command": outer_boundary["outer_timeout_command"],
                "outer_production_command": outer_boundary["production_wrapper_command"],
                "tensor_parallel_width": 1,
                "replica_count": 1,
                "placement_justification": authorization_placement["placement_justification"],
                "run_dir": str(run_dir),
                "log_path": str(log_path),
            }
            exclusive_write_json(global_claim_path, global_claim)
            global_claim_hash = sha256_file(global_claim_path)
            logger.append(
                "GLOBAL_ONE_SHOT_CLAIM_DURABLE",
                {"path": str(global_claim_path), "sha256": global_claim_hash},
            )

            deadline_seconds = float(run_control["deadline_seconds"])
            deadline_monotonic = time.monotonic() + deadline_seconds

            def behavior_identity_probe() -> dict[str, Any]:
                ace_config = adapter.config
                checkpoint = ace_config["checkpoint"]
                provenance = ace_config["provenance"]
                return {
                    "checkpoint_tree": verify_exact_checkpoint_tree(
                        adapter.checkpoint_dir,
                        checkpoint["required_files"],
                        checkpoint["exact_tree_sha256"],
                    ),
                    "source": verify_clean_git_revision(
                        adapter.source_dir,
                        provenance["upstream_code_revision"],
                        expected_tree=provenance["upstream_code_tree"],
                    ),
                }

            claiming_adapter = ClaimingAdapter(
                adapter,
                jobs=config["jobs"],
                claim_dir=claim_dir,
                claim_context={
                    "authorization_id": AUTHORIZATION_ID,
                    "global_claim_sha256": global_claim_hash,
                    "run_id": FIXED_RUN_ID,
                    "config_sha256": hashes["b2_config"],
                    "origin_commit": governance["git"]["head"],
                    "gpu_mapping": gpu_mapping,
                    "outer_timeout_command": outer_boundary["outer_timeout_command"],
                },
                placement=placement,
                physical_gpu_id=int(physical_gpu_id),
                deadline_monotonic=deadline_monotonic,
                logger=logger,
                behavior_identity_probe=behavior_identity_probe,
            )
            jobs = [
                MiniSmokeJob(
                    adapter=claiming_adapter,
                    request=GenerationRequest(
                        prompt_id=job["prompt_id"],
                        prompt=job["prompt"],
                        seed_id=job["seed_id"],
                        seed=job["seed"],
                        duration_seconds=job["duration_seconds"],
                        output_path=run_dir / job["output_relative_path"],
                        lyrics=job["lyrics"],
                    ),
                )
                for job in config["jobs"]
            ]
            context = RunContext(
                run_id=FIXED_RUN_ID,
                command=command,
                git_commit=governance["git"]["head"],
                node=node,
                gpu_ids=(str(physical_gpu_id),),
                placement_justification=authorization_placement["placement_justification"],
                package_freeze_sha256=runtime["environment_identity_sha256"],
                tensor_parallel_width=1,
                replica_count=1,
            )
            gpu_started = time.monotonic()
            with elapsed_deadline(deadline_seconds):
                common_result = run_mini_smoke(
                    jobs,
                    run_dir=run_dir,
                    context=context,
                    require_one_visible_gpu=True,
                )
            gpu_residency_seconds = time.monotonic() - gpu_started
            if gpu_residency_seconds > config["caps"]["max_gpu_seconds"]:
                raise B2ExecutionError("measured one-GPU residency exceeded 1,800 seconds")
            chain = validate_ledger_chain(Path(common_result["ledger_path"]), expected_count=2)
            rows = chain["rows"]
            if common_result.get("status") != "PASS" or any(
                row.get("status") != "PASS" for row in rows
            ):
                raise B2ExecutionError("common mini-smoke did not report two passing rows")
            if any(row.get("cost_status") != "MEASURED" for row in rows):
                raise B2ExecutionError("one or more mini-smoke cost rows are not MEASURED")
            if common_result.get("ledger_tail_sha256") != chain["ledger_tail_sha256"]:
                raise B2ExecutionError("common result ledger tail does not match verified chain")
            required_measures = set(config["result_contract"]["required_per_call_measures"])
            for row in rows:
                if not required_measures.issubset(row):
                    raise B2ExecutionError(
                        "a measured row lacks required cost/sanity provenance fields"
                    )

            evidence_path = run_dir / "b2-authorization-runtime-evidence.json"
            exclusive_write_json(
                evidence_path,
                {
                    **authorization_evidence,
                    "global_claim_path": str(global_claim_path),
                    "global_claim_sha256": global_claim_hash,
                    "adapter_preflight_path": str(preflight_path),
                    "adapter_preflight_sha256": sha256_file(preflight_path),
                    "runtime_environment_identity_sha256": runtime["environment_identity_sha256"],
                },
            )
            result = {
                "schema_version": 2,
                "run_id": FIXED_RUN_ID,
                "status": "PASS",
                "MEASUREMENT_STATUS": "MEASURED",
                "MEASUREMENT_SCOPE": "B2_MINI_SMOKE_NON_BENCHMARK",
                "benchmark_endpoint": False,
                "started_at_utc": started_at,
                "finished_at_utc": _utc_now(),
                "model_call_count": 2,
                "generated_output_count": 2,
                "retry_count": 0,
                "gpu_count": 1,
                "gpu_residency_seconds": gpu_residency_seconds,
                "node": node,
                "physical_gpu_id": physical_gpu_id,
                "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                "process_visible_device": "cuda:0",
                "process_visible_index": 0,
                "gpu_mapping": gpu_mapping,
                "outer_timeout_command": outer_boundary["outer_timeout_command"],
                "outer_timeout_command_shell": outer_boundary["outer_timeout_command_shell"],
                "outer_production_command": outer_boundary["production_wrapper_command"],
                "outer_production_command_shell": outer_boundary[
                    "production_wrapper_command_shell"
                ],
                "tensor_parallel_width": 1,
                "replica_count": 1,
                "placement_justification": authorization_placement["placement_justification"],
                "rows": rows,
                "ledger_path": common_result["ledger_path"],
                "ledger_sha256": chain["ledger_sha256"],
                "ledger_tail_sha256": chain["ledger_tail_sha256"],
                "authorization_runtime_evidence_path": str(evidence_path),
                "authorization_runtime_evidence_sha256": sha256_file(evidence_path),
                "global_claim_path": str(global_claim_path),
                "global_claim_sha256": global_claim_hash,
                "log_path": str(log_path),
            }
            result_path = run_dir / "b2_mini_smoke_result.json"
            exclusive_write_json(result_path, result)
            logger.append(
                "TERMINAL_PASS",
                {"result_path": str(result_path), "sha256": sha256_file(result_path)},
            )
            return result
        except Exception as exc:
            logger.append(
                "TERMINAL_FAIL_ESCALATED",
                {"error_type": type(exc).__name__, "error": str(exc), "no_retry": True},
            )
            if run_dir.is_dir() and not os.path.lexists(run_dir / "b2_mini_smoke_result.json"):
                exclusive_write_json(
                    run_dir / "b2_mini_smoke_result.json",
                    {
                        "schema_version": 2,
                        "run_id": FIXED_RUN_ID,
                        "status": "FAIL_ESCALATED",
                        "MEASUREMENT_STATUS": "NOT_MEASURED_TERMINAL_FAILURE",
                        "MEASUREMENT_SCOPE": "B2_MINI_SMOKE_NON_BENCHMARK",
                        "benchmark_endpoint": False,
                        "started_at_utc": started_at,
                        "finished_at_utc": _utc_now(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "no_retry": True,
                        "node": node,
                        "physical_gpu_id": physical_gpu_id,
                        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                        "process_visible_device": "cuda:0",
                        "outer_timeout_command": outer_boundary["outer_timeout_command"],
                        "outer_production_command": outer_boundary["production_wrapper_command"],
                        "log_path": str(log_path),
                    },
                )
            raise
        finally:
            logger.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--authorization",
        type=Path,
        default=os.environ.get("B2_MINI_SMOKE_AUTHORIZATION"),
        required=os.environ.get("B2_MINI_SMOKE_AUTHORIZATION") is None,
        help="Completed external one-shot authorization JSON (never the committed template).",
    )
    parser.add_argument("--run-id", choices=[FIXED_RUN_ID], required=True)
    parser.add_argument("--execute", required=True, help="Exact phrase frozen in the config.")
    return parser


def terminal_failure_record(
    exc: Exception,
    *,
    claim_root: Path = Path(
        "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims"
    ),
    run_root: Path = Path(
        "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
        "runs/b2-mini-smoke-v2"
    ),
) -> dict[str, Any]:
    """Return one standardized terminal JSON record even for early refusals."""

    global_claim = claim_root / "b2-ace-v1-mini-smoke-v2-one-shot.claim.json"
    call_claim_dir = claim_root / FIXED_RUN_ID
    call_claim_count = sum(
        1 for index in range(2) if os.path.lexists(call_claim_dir / f"call-{index:02d}.claim.json")
    )
    run_audio = run_root / FIXED_RUN_ID / "audio"
    generated_output_count = sum(
        1 for index in range(2) if os.path.lexists(run_audio / f"call-{index:02d}.wav")
    )
    global_consumed = os.path.lexists(global_claim)
    status = "FAIL_ESCALATED" if global_consumed else "REFUSED_PREFLIGHT"
    return {
        "schema_version": 2,
        "run_id": FIXED_RUN_ID,
        "status": status,
        "MEASUREMENT_STATUS": (
            "NOT_MEASURED_TERMINAL_FAILURE" if global_consumed else "NOT_MEASURED_NO_MODEL_CALL"
        ),
        "MEASUREMENT_SCOPE": "B2_MINI_SMOKE_NON_BENCHMARK",
        "benchmark_endpoint": False,
        "finished_at_utc": _utc_now(),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "global_claim_consumed": global_consumed,
        "per_call_claim_count": call_claim_count,
        "model_call_count": 0 if not global_consumed else None,
        "model_call_count_note": (
            "exactly zero before global claim; indeterminate after claim, "
            "inspect call claims/ledger"
        ),
        "generated_output_count": generated_output_count,
        "retry_count": 0,
        "no_retry": True,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "process_visible_device": "cuda:0" if os.environ.get("CUDA_VISIBLE_DEVICES") else None,
        "outer_timeout_command": os.environ.get("B2_OUTER_TIMEOUT_COMMAND_JSON"),
        "production_wrapper_command": os.environ.get("B2_OUTER_PRODUCTION_COMMAND_JSON"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute_b2_mini_smoke(
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

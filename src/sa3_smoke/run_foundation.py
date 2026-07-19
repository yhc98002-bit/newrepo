"""High-level, no-clobber orchestration for the frozen SA3 foundation smokes.

The CLI performs all validation before importing or loading the model, creates
one immutable run directory, loads the verified checkpoint exactly once, then
runs A through E sequentially.  Every attempted invocation receives terminal
per-smoke results and manifests, including preflight, dependency, and model-load
failures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sa3_smoke.artifacts import (
    create_immutable_directory,
    create_immutable_run_dir,
    exclusive_write_json,
    sha256_file,
)
from sa3_smoke.budget import ExecutionBudget, smoke_context

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "configs" / "foundation_v2.json"
DEFAULT_RUN_ROOT = Path("/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/runs")
EXPECTED_CONFIG_SHA256 = "d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f"
EXPECTED_SUPERSEDED_CONFIG_SHA256 = (
    "42e99699e7c3f8fb56d615086684b10afd4fdc1a8b3f162e37818ec462814a14"
)
EXPECTED_GPU_PLACEMENT_SHA256 = "a76eb1fc11eac87238ecd9fcc11e1070968b6a423e9c650698445d45a631229a"
EXPECTED_SEED_REGISTRY_SHA256 = "fcdcd09c6474fe2cfba477a0a0e70fcbfa6205ab10e3f8c9f460440850cad8d5"
EXPECTED_MODEL_ID = "stabilityai/stable-audio-3-medium-base"
EXPECTED_CONFIG_VERSION = 2
EXPECTED_STABLE_AUDIO_3_COMMIT = "0385302ea26522f00c80392c4b708df5ebf1adf5"
EXPECTED_STABLE_AUDIO_TOOLS_COMMIT = "3241adba4fc2a85cf5b29d9eb68d42f40a28e820"
EXPECTED_MODELSCOPE_REVISION = "a9c479f5f28ee89f6fbdaca57b683e6b6c160314"
EXPECTED_HUGGINGFACE_REVISION = "b32993f73c3bdc3864043a72d8032606bba737c8"
LICENSE_IDENTIFIER = "Stability AI Community License Agreement (2024-07-05) + Gemma Terms of Use"
TERMINAL_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED_ON_LICENSE"})
SMOKE_NAMES = ("A", "B", "C", "D", "E")
REQUIRED_T5_MANIFEST_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
)
PROVIDER_METADATA_ONLY_FILES = frozenset({".gitattributes", "configuration.json"})
EXPECTED_CROSS_PROVIDER_EXCLUSIONS = frozenset(
    {
        ".gitattributes",
        "configuration.json",
        "t5gemma-b-b-ul2/.gitattributes",
    }
)
_SENSITIVE_ENV_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PRIVATE_KEY|API_KEY)", re.I
)


@dataclass(frozen=True)
class OrchestrationDependencies:
    """Injectable boundaries used by CPU-only orchestration tests."""

    testing_only: bool
    resolve_model_config: Callable[..., Any]
    load_model: Callable[..., Any]
    run_smoke_a: Callable[..., Any]
    run_smoke_b: Callable[..., Any]
    run_smoke_c: Callable[..., Any]
    run_smoke_d: Callable[..., Any]
    run_smoke_e: Callable[..., Any]
    environment_validator: Callable[[Path], Mapping[str, Any]]
    hardware_probe: Callable[[], Mapping[str, Any]]
    git_probe: Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True)
class FoundationRunOutcome:
    """Programmatic result returned by :func:`run_foundation`."""

    exit_code: int
    run_dir: Path
    result_path: Path
    result: Mapping[str, Any]


@dataclass(frozen=True)
class PreflightReport:
    """Validated inputs and complete evidence, including terminal failures."""

    passed: bool
    failures: tuple[str, ...]
    config: Mapping[str, Any]
    evidence: Mapping[str, Any]
    weights_manifest: Mapping[str, Any]
    model_artifact_sha256s: Mapping[str, str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _full_environment_sha256(environment: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(environment.items()):
        digest.update(name.encode("utf-8", errors="surrogateescape"))
        digest.update(b"=")
        digest.update(value.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
    return digest.hexdigest()


def capture_process_context() -> dict[str, Any]:
    """Capture exact process/cwd/environment identity without disclosing credentials."""

    try:
        raw_argv = Path(f"/proc/{os.getpid()}/cmdline").read_bytes().split(b"\0")
        argv = [item.decode("utf-8", errors="surrogateescape") for item in raw_argv if item]
    except OSError:
        argv = list(sys.argv)
    environment = dict(os.environ)
    safe_values: dict[str, str] = {}
    sensitive_hashes: dict[str, str] = {}
    for name, value in sorted(environment.items()):
        if _SENSITIVE_ENV_RE.search(name):
            sensitive_hashes[name] = hashlib.sha256(
                value.encode("utf-8", errors="surrogateescape")
            ).hexdigest()
        else:
            safe_values[name] = value
    return {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "argv": argv,
        "exact_command": shlex.join(argv),
        "executable": sys.executable,
        "python_version": sys.version,
        "cwd": str(Path.cwd().resolve()),
        "environment": {
            "safe_values": safe_values,
            "sensitive_value_sha256s": sensitive_hashes,
            "full_environment_sha256": _full_environment_sha256(environment),
            "variable_count": len(environment),
        },
    }


def _run_git(repository_root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def default_git_probe(repository_root: Path) -> dict[str, Any]:
    """Capture commit, branch, local remote-tracking state, and exact dirtiness."""

    status = _run_git(repository_root, "status", "--porcelain=v1", "--untracked-files=all")
    head = _run_git(repository_root, "rev-parse", "HEAD")
    try:
        origin_main = _run_git(repository_root, "rev-parse", "origin/main")
    except subprocess.CalledProcessError:
        origin_main = None
    try:
        branch = _run_git(repository_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except subprocess.CalledProcessError:
        branch = None
    return {
        "head": head,
        "branch": branch,
        "origin_main": origin_main,
        "head_matches_origin_main": bool(origin_main is not None and origin_main == head),
        "clean": status == "",
        "porcelain_v1": status.splitlines() if status else [],
    }


def default_hardware_probe() -> dict[str, Any]:
    """Inspect the visible CUDA placement without allocating model weights."""

    import torch

    available = bool(torch.cuda.is_available())
    count = int(torch.cuda.device_count()) if available else 0
    devices = [
        {
            "visible_index": index,
            "name": str(torch.cuda.get_device_name(index)),
            "capability": list(torch.cuda.get_device_capability(index)),
        }
        for index in range(count)
    ]
    return {
        "node": socket.gethostname().split(".", maxsplit=1)[0],
        "hostname": socket.gethostname(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "cuda_available": available,
        "visible_device_count": count,
        "devices": devices,
    }


def default_dependencies() -> OrchestrationDependencies:
    """Resolve heavy/model-specific imports only when orchestration begins."""

    from sa3_smoke.environment_validation import validate_live_environment
    from sa3_smoke.model_runtime import load_local_model, resolve_local_model_config
    from sa3_smoke.smoke_e import run_smoke_e
    from sa3_smoke.smokes import run_smoke_a, run_smoke_b, run_smoke_c, run_smoke_d

    return OrchestrationDependencies(
        testing_only=False,
        resolve_model_config=resolve_local_model_config,
        load_model=load_local_model,
        run_smoke_a=run_smoke_a,
        run_smoke_b=run_smoke_b,
        run_smoke_c=run_smoke_c,
        run_smoke_d=run_smoke_d,
        run_smoke_e=run_smoke_e,
        environment_validator=validate_live_environment,
        hardware_probe=default_hardware_probe,
        git_probe=default_git_probe,
    )


def _value(config: Mapping[str, Any], *keys: str) -> Any:
    current: Any = config
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _same_filesystem_object(left: Path, right: Path) -> bool:
    """Compare filesystem identity, including distinct bind-mount path aliases."""

    return left.samefile(right)


def _check_equal(
    failures: list[str],
    label: str,
    observed: Any,
    expected: Any,
) -> None:
    if observed != expected:
        failures.append(f"{label}: expected {expected!r}, got {observed!r}")


def _resolve_repo_path(repository_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty path string")
    candidate = (
        (repository_root / value).resolve()
        if not Path(value).is_absolute()
        else Path(value).resolve()
    )
    if not candidate.is_relative_to(repository_root.resolve()):
        raise ValueError(f"{label} must resolve inside the repository: {candidate}")
    return candidate


def _snapshot_verification(
    snapshot: Path,
    manifest: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Rehash the exact live expected set; ignore only runtime manifest copy."""

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("weights manifest files must be a non-empty list")
    expected: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise ValueError("weights manifest contains an invalid file entry")
        relative = entry["path"]
        if relative in expected:
            raise ValueError(f"weights manifest contains duplicate path: {relative}")
        expected[relative] = entry

    actual_paths = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_file() and path.relative_to(snapshot).as_posix() != "weights.manifest.json"
    }
    expected_paths = set(expected)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unexpected = sorted(actual_paths - expected_paths)
        raise ValueError(
            f"live snapshot file set differs from committed manifest; "
            f"missing={missing}, unexpected={unexpected}"
        )
    incomplete = sorted(path for path in actual_paths if path.endswith(".incomplete"))
    if incomplete:
        raise ValueError(f"live snapshot contains incomplete artifacts: {incomplete}")

    hashes: dict[str, str] = {}
    verified_rows: list[dict[str, Any]] = []
    for relative in sorted(expected):
        path = snapshot / relative
        entry = expected[relative]
        expected_size = entry.get("byte_size")
        expected_sha256 = entry.get("sha256")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise ValueError(
                f"live snapshot size mismatch for {relative}: {actual_size} != {expected_size}"
            )
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"live snapshot SHA-256 mismatch for {relative}: "
                f"{actual_sha256} != {expected_sha256}"
            )
        hashes[relative] = actual_sha256
        verified_rows.append({"path": relative, "byte_size": actual_size, "sha256": actual_sha256})
    return hashes, {
        "status": "PASS",
        "artifact_root": str(snapshot),
        "ignored_runtime_files": ["weights.manifest.json"],
        "exact_expected_file_set": True,
        "verified_file_count": len(verified_rows),
        "verified_total_bytes": sum(row["byte_size"] for row in verified_rows),
        "files": verified_rows,
    }


def _latest_decision_assignment(path: Path) -> dict[str, Any]:
    """Return the latest old-or-amended foundation authorization assignment."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read append-only decisions file {path}: {exc}") from exc
    pattern = re.compile(
        r"\b(SA3_FOUNDATION_SMOKE_AUTHORIZED|FOUNDATION_COST_SMOKE_AUTHORIZED)"
        r"\s*=\s*([A-Za-z_]+)"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        raise ValueError("DECISIONS.md contains no foundation authorization assignment")
    latest = matches[-1]
    assignment_name = latest.group(1)
    state = latest.group(2).upper()
    line_number = text.count("\n", 0, latest.start()) + 1
    caps: dict[str, int | None] = {}
    for name in ("MAX_GENERATIONS", "MAX_CLIP_SECONDS", "MAX_GPUS", "MAX_GPU_SECONDS"):
        cap_matches = list(re.finditer(rf"\b{name}\s*=\s*(\d+)", text))
        caps[name] = int(cap_matches[-1].group(1)) if cap_matches else None
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "assignment_count": len(matches),
        "latest_assignment": assignment_name,
        "latest_state": state,
        "latest_line_number": line_number,
        "authorized": state == "YES",
        "caps": caps,
    }


def _validate_seed_registry(path: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    """Bind every configured seed ID/value to the append-only registry."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read seed registry {path}: {exc}") from exc
    rows: dict[str, int] = {}
    for match in re.finditer(r"^\|\s*(S-\d{4})\s*\|\s*(\d+)\s*\|", text, re.MULTILINE):
        identifier = match.group(1)
        value = int(match.group(2))
        if identifier in rows:
            raise ValueError(f"seed registry contains duplicate identifier {identifier}")
        rows[identifier] = value
    configured = {
        "S-0001": _value(config, "smokes", "a", "seed"),
        "S-0002": _value(config, "smokes", "b", "seed"),
        "S-0003": _value(config, "smokes", "c", "single_seed"),
        "S-0004": _value(config, "smokes", "c", "multi_seed"),
        "S-0005": _value(config, "smokes", "d", "single_seed"),
        "S-0006": _value(config, "smokes", "d", "batch_seed"),
        "S-0007": _value(config, "smokes", "e", "seed"),
    }
    if rows != configured:
        raise ValueError(
            f"seed registry/config mapping mismatch: registry={rows}, config={configured}"
        )
    return {
        "status": "PASS",
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "row_count": len(rows),
        "rows": [{"seed_id": key, "value": value} for key, value in rows.items()],
        "unused_in_authorized_scope": [],
    }


def _manifest_file_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("weights manifest files must be a non-empty list")
    result: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise ValueError("weights manifest contains an invalid file entry")
        relative = entry["path"]
        if relative in result:
            raise ValueError(f"weights manifest contains duplicate path: {relative}")
        result[relative] = entry
    return result


def _validate_cross_provider_overlay(
    *,
    overlay_path: Path,
    v1_manifest_path: Path,
    v1_manifest: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the v2 overlay without trusting superseded v1 verification flags."""

    overlay = _read_json_object(overlay_path)
    if overlay.get("schema_version") != 2:
        raise ValueError("cross-provider overlay schema_version must be 2")
    if overlay.get("status") != "PASS":
        raise ValueError("cross-provider overlay status must be PASS")
    if overlay.get("label") != "external_upstream":
        raise ValueError("cross-provider overlay label must be external_upstream")

    v1_sha256 = sha256_file(v1_manifest_path)
    supersedes = overlay.get("supersedes")
    if not isinstance(supersedes, Mapping):
        raise ValueError("cross-provider overlay lacks supersedes metadata")
    if supersedes.get("path") != "provenance/weights.manifest.json":
        raise ValueError("cross-provider overlay supersedes the wrong path")
    if supersedes.get("sha256") != v1_sha256:
        raise ValueError("cross-provider overlay does not bind the committed v1 manifest")

    expected_provider_values = {
        "huggingface": {
            "repo_id": _value(config, "model", "id"),
            "revision": _value(config, "model", "huggingface_revision"),
        },
        "modelscope": {
            "repo_id": _value(config, "model", "id"),
            "revision": _value(config, "model", "modelscope_revision"),
        },
    }
    for provider, expected in expected_provider_values.items():
        observed = overlay.get(provider)
        v1_observed = v1_manifest.get(provider)
        if not isinstance(observed, Mapping) or not isinstance(v1_observed, Mapping):
            raise ValueError(f"{provider} provenance metadata must be objects in v1 and v2")
        for field, expected_value in expected.items():
            if observed.get(field) != expected_value:
                raise ValueError(f"cross-provider {provider}.{field} differs from config")
            if v1_observed.get(field) != expected_value:
                raise ValueError(f"v1 {provider}.{field} differs from config")
    huggingface = overlay["huggingface"]
    if huggingface.get("gated") is not False or huggingface.get("private") is not False:
        raise ValueError("official Hugging Face base snapshot must be public and ungated")

    v1_files = _manifest_file_map(v1_manifest)
    expected_verified_paths = set(v1_files).difference(PROVIDER_METADATA_ONLY_FILES)
    verified_files = overlay.get("verified_files")
    if not isinstance(verified_files, list):
        raise ValueError("cross-provider overlay verified_files must be a list")
    observed_verified: dict[str, Mapping[str, Any]] = {}
    for entry in verified_files:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise ValueError("cross-provider overlay contains an invalid verified file")
        relative = entry["path"]
        if relative in observed_verified:
            raise ValueError(f"cross-provider overlay contains duplicate path: {relative}")
        if entry.get("cross_provider_verified") is not True:
            raise ValueError(f"cross-provider verification is not true for {relative}")
        observed_verified[relative] = entry
    if set(observed_verified) != expected_verified_paths:
        missing = sorted(expected_verified_paths.difference(observed_verified))
        unexpected = sorted(set(observed_verified).difference(expected_verified_paths))
        raise ValueError(
            "cross-provider verified file set differs from substantive v1 files; "
            f"missing={missing}, unexpected={unexpected}"
        )
    for relative, overlay_entry in observed_verified.items():
        v1_entry = v1_files[relative]
        if overlay_entry.get("byte_size") != v1_entry.get("byte_size"):
            raise ValueError(f"cross-provider size differs from v1 for {relative}")
        if overlay_entry.get("sha256") != v1_entry.get("sha256"):
            raise ValueError(f"cross-provider SHA-256 differs from v1 for {relative}")

    verification = overlay.get("verification")
    if not isinstance(verification, Mapping):
        raise ValueError("cross-provider overlay verification must be an object")
    if verification.get("verified_common_file_count") != len(expected_verified_paths):
        raise ValueError("cross-provider verified_common_file_count is inconsistent")
    provider_metadata = overlay.get("provider_metadata")
    if not isinstance(provider_metadata, Mapping):
        raise ValueError("cross-provider overlay provider_metadata must be an object")
    exclusions = provider_metadata.get("excluded_from_content_equivalence")
    if not isinstance(exclusions, list):
        raise ValueError("cross-provider provider exclusions must be a list")
    exclusion_paths = {row.get("path") for row in exclusions if isinstance(row, Mapping)}
    if exclusion_paths != EXPECTED_CROSS_PROVIDER_EXCLUSIONS:
        raise ValueError("cross-provider metadata exclusion set is inconsistent")
    if provider_metadata.get("runtime_required") is not False:
        raise ValueError("provider-specific metadata must not be runtime-required")

    return overlay, {
        "path": str(overlay_path.resolve()),
        "sha256": sha256_file(overlay_path),
        "schema_version": 2,
        "status": "PASS",
        "supersedes_v1_sha256": v1_sha256,
        "verified_file_count": len(observed_verified),
        "v1_cross_provider_flags_trusted": False,
        "overlay_scope": "cross_provider_verified flags only",
    }


def validate_preflight(
    *,
    config_path: Path,
    repository_root: Path,
    expected_config_sha256: str,
    dependencies: OrchestrationDependencies,
    process_context: Mapping[str, Any],
    require_clean_git: bool,
) -> PreflightReport:
    """Validate frozen bytes, schema, placement, Git state, and live model files."""

    failures: list[str] = []
    evidence: dict[str, Any] = {}
    config: dict[str, Any] = {}
    weights_manifest: dict[str, Any] = {}
    model_hashes: dict[str, str] = {}

    try:
        config_sha256 = sha256_file(config_path)
        config = _read_json_object(config_path)
    except (OSError, ValueError) as exc:
        failures.append(str(exc))
        config_sha256 = None
    evidence["configuration"] = {
        "path": str(config_path.resolve()),
        "sha256": config_sha256,
        "expected_sha256": expected_config_sha256,
        "hash_matches": config_sha256 == expected_config_sha256,
    }
    if config_sha256 != expected_config_sha256:
        failures.append(
            f"frozen configuration SHA-256 mismatch: {config_sha256} != {expected_config_sha256}"
        )

    if config:
        _check_equal(
            failures,
            "config.version",
            config.get("version"),
            EXPECTED_CONFIG_VERSION,
        )
        if expected_config_sha256 == EXPECTED_CONFIG_SHA256:
            expected_supersession = {
                "path": "configs/foundation_v1.json",
                "scope": "placement.gpu_ids, placement.justification, and version only",
                "sha256": EXPECTED_SUPERSEDED_CONFIG_SHA256,
            }
            _check_equal(
                failures,
                "config.supersedes",
                config.get("supersedes"),
                expected_supersession,
            )
        _check_equal(
            failures,
            "model.id",
            _value(config, "model", "id"),
            EXPECTED_MODEL_ID,
        )
        _check_equal(
            failures,
            "model.model_half",
            _value(config, "model", "model_half"),
            True,
        )
        _check_equal(
            failures,
            "model.modelscope_revision",
            _value(config, "model", "modelscope_revision"),
            EXPECTED_MODELSCOPE_REVISION,
        )
        _check_equal(
            failures,
            "model.huggingface_revision",
            _value(config, "model", "huggingface_revision"),
            EXPECTED_HUGGINGFACE_REVISION,
        )
        _check_equal(
            failures,
            "audio.sample_rate",
            _value(config, "audio", "sample_rate"),
            44_100,
        )
        _check_equal(failures, "audio.channels", _value(config, "audio", "channels"), 2)
        _check_equal(failures, "audio.subtype", _value(config, "audio", "subtype"), "FLOAT")
        frozen_sampling = {
            "cfg_scale": 7.0,
            "chunked_decode": True,
            "duration_padding_sec": 6.0,
            "duration_seconds": 30,
            "negative_prompt": "low quality, clipping, silence",
            "prompt": (
                "A steady instrumental electronic music loop with drums, bass, and "
                "warm synthesizer, clean studio recording, 120 BPM"
            ),
            "sampler_type": "euler",
            "steps": 50,
        }
        for key, expected in frozen_sampling.items():
            _check_equal(
                failures,
                f"sampling.{key}",
                _value(config, "sampling", key),
                expected,
            )
        _check_equal(
            failures,
            "smokes.a.repeat_count",
            _value(config, "smokes", "a", "repeat_count"),
            2,
        )
        _check_equal(
            failures,
            "smokes.a.seed",
            _value(config, "smokes", "a", "seed"),
            73_193_001,
        )
        _check_equal(
            failures,
            "smokes.b.source_seconds",
            _value(config, "smokes", "b", "source_seconds"),
            10,
        )
        _check_equal(
            failures,
            "smokes.b.prompt",
            _value(config, "smokes", "b", "prompt"),
            (
                "Continue the same instrumental electronic music with consistent "
                "rhythm and instrumentation"
            ),
        )
        _check_equal(
            failures,
            "smokes.b.continuation_mask_seconds",
            _value(config, "smokes", "b", "continuation_mask_seconds"),
            [10, 30],
        )
        _check_equal(
            failures,
            "smokes.c.single_mask_seconds",
            _value(config, "smokes", "c", "single_mask_seconds"),
            [[8, 12]],
        )
        _check_equal(
            failures,
            "smokes.c.multi_mask_seconds",
            _value(config, "smokes", "c", "multi_mask_seconds"),
            [[4, 6], [20, 23]],
        )
        _check_equal(
            failures,
            "smokes.c.prompt",
            _value(config, "smokes", "c", "prompt"),
            (
                "A seamless instrumental electronic music passage with steady drums "
                "and warm synthesizer"
            ),
        )
        _check_equal(
            failures,
            "smokes.d.batch_size",
            _value(config, "smokes", "d", "batch_size"),
            4,
        )
        _check_equal(
            failures,
            "smokes.d.batch_duration_seconds",
            _value(config, "smokes", "d", "batch_duration_seconds"),
            10,
        )
        batch_prompts = _value(config, "smokes", "d", "batch_prompts")
        expected_batch_prompts = [
            "Steady electronic drums and warm synthesizer, 100 BPM",
            "Clean acoustic guitar rhythm with light percussion, 110 BPM",
            "Ambient synthesizer pulse with a steady beat, 90 BPM",
            "Bright piano groove with bass and drums, 120 BPM",
        ]
        if batch_prompts != expected_batch_prompts:
            failures.append("smokes.d.batch_prompts differ from the frozen prompt set")
        elif len(set(batch_prompts)) != 4:
            failures.append("smokes.d.batch_prompts must contain four distinct prompts")
        _check_equal(
            failures,
            "smokes.e.checkpoint_completed_steps",
            _value(config, "smokes", "e", "checkpoint_completed_steps"),
            [15, 30, 40],
        )
        _check_equal(
            failures,
            "smokes.e.waveform_max_abs_tolerance",
            _value(config, "smokes", "e", "waveform_max_abs_tolerance"),
            1e-5,
        )
        _check_equal(
            failures,
            "smokes.e.waveform_min_snr_db",
            _value(config, "smokes", "e", "waveform_min_snr_db"),
            80.0,
        )
        expected_seeds = {
            ("a", "seed"): 73_193_001,
            ("b", "seed"): 73_193_002,
            ("c", "single_seed"): 73_193_003,
            ("c", "multi_seed"): 73_193_004,
            ("d", "single_seed"): 73_193_005,
            ("d", "batch_seed"): 73_193_006,
            ("e", "seed"): 73_193_007,
        }
        for (smoke, key), expected in expected_seeds.items():
            _check_equal(
                failures,
                f"smokes.{smoke}.{key}",
                _value(config, "smokes", smoke, key),
                expected,
            )

    decisions_path = repository_root / "DECISIONS.md"
    try:
        decisions_evidence = _latest_decision_assignment(decisions_path)
        if not decisions_evidence["authorized"]:
            failures.append("latest foundation authorization assignment is not YES")
        if expected_config_sha256 == EXPECTED_CONFIG_SHA256:
            if decisions_evidence.get("latest_assignment") != "FOUNDATION_COST_SMOKE_AUTHORIZED":
                failures.append(
                    "latest production authorization is not the bounded cost-smoke amendment"
                )
            expected_caps = {
                "MAX_GENERATIONS": 20,
                "MAX_CLIP_SECONDS": 30,
                "MAX_GPUS": 1,
                "MAX_GPU_SECONDS": 1800,
            }
            if decisions_evidence.get("caps") != expected_caps:
                failures.append("bounded cost-smoke hard caps differ from D-0013")
    except ValueError as exc:
        failures.append(str(exc))
        decisions_evidence = {
            "path": str(decisions_path.resolve()),
            "sha256": sha256_file(decisions_path) if decisions_path.is_file() else None,
            "latest_state": None,
            "authorized": False,
            "error": str(exc),
        }
    evidence["governance_authorization"] = decisions_evidence

    seed_registry_path = repository_root / "SEED_REGISTRY.md"
    try:
        seed_registry = _validate_seed_registry(seed_registry_path, config)
        if (
            expected_config_sha256 == EXPECTED_CONFIG_SHA256
            and seed_registry["sha256"] != EXPECTED_SEED_REGISTRY_SHA256
        ):
            failures.append(
                "frozen seed registry SHA-256 mismatch: "
                f"{seed_registry['sha256']} != {EXPECTED_SEED_REGISTRY_SHA256}"
            )
    except ValueError as exc:
        failures.append(str(exc))
        seed_registry = {
            "status": "FAIL",
            "path": str(seed_registry_path.resolve()),
            "sha256": sha256_file(seed_registry_path) if seed_registry_path.is_file() else None,
            "error": str(exc),
        }
    evidence["seed_registry"] = seed_registry

    try:
        protocol_path = _resolve_repo_path(
            repository_root, _value(config, "protocol", "path"), "protocol.path"
        )
        protocol_sha256 = sha256_file(protocol_path)
        expected_protocol_sha256 = _value(config, "protocol", "sha256")
        if protocol_sha256 != expected_protocol_sha256:
            failures.append(
                f"protocol SHA-256 mismatch: {protocol_sha256} != {expected_protocol_sha256}"
            )
    except (OSError, ValueError) as exc:
        failures.append(str(exc))
        protocol_path = repository_root / "SMOKE_PROTOCOL.md"
        protocol_sha256 = None
        expected_protocol_sha256 = _value(config, "protocol", "sha256")
    evidence["protocol"] = {
        "path": str(protocol_path.resolve()),
        "sha256": protocol_sha256,
        "expected_sha256": expected_protocol_sha256,
        "hash_matches": protocol_sha256 == expected_protocol_sha256,
    }

    freeze_path = repository_root / "environment" / "package-freeze.txt"
    runtime_path = repository_root / "environment" / "runtime.json"
    try:
        runtime = _read_json_object(runtime_path)
        freeze_sha256 = sha256_file(freeze_path)
        if freeze_sha256 != runtime.get("freeze_sha256"):
            failures.append("package freeze SHA-256 differs from environment/runtime.json")
        freeze_text = freeze_path.read_text(encoding="utf-8")
        expected_freeze_fragments = (
            f"stable-audio-3/archive/{EXPECTED_STABLE_AUDIO_3_COMMIT}.tar.gz",
            f"stable-audio-tools/archive/{EXPECTED_STABLE_AUDIO_TOOLS_COMMIT}.tar.gz",
            "torch==2.7.1",
            "torchaudio==2.7.1",
        )
        for fragment in expected_freeze_fragments:
            if fragment not in freeze_text:
                failures.append(f"package freeze lacks pinned dependency: {fragment}")
        _check_equal(failures, "runtime.python", runtime.get("python"), "3.10.12")
        _check_equal(failures, "runtime.torch", runtime.get("torch"), "2.7.1+cu126")
        _check_equal(
            failures,
            "runtime.torchaudio",
            runtime.get("torchaudio"),
            "2.7.1+cu126",
        )
    except (OSError, ValueError) as exc:
        failures.append(str(exc))
        runtime = {}
        freeze_sha256 = None
    evidence["environment_freeze"] = {
        "path": str(freeze_path.resolve()),
        "sha256": freeze_sha256,
        "runtime_record_path": str(runtime_path.resolve()),
        "runtime_record_sha256": sha256_file(runtime_path) if runtime_path.is_file() else None,
    }

    try:
        live_environment = dict(dependencies.environment_validator(repository_root))
        if live_environment.get("passed") is not True:
            live_failures = live_environment.get("failures")
            if isinstance(live_failures, Sequence) and not isinstance(live_failures, (str, bytes)):
                failures.extend(f"live environment drift: {failure}" for failure in live_failures)
            else:
                failures.append("live environment validation failed without failure details")
    except Exception as exc:  # noqa: BLE001 - environment drift must fail preflight
        live_environment = {
            "passed": False,
            "failures": [f"{type(exc).__name__}: {exc}"],
            "evidence": {},
        }
        failures.append(f"live environment validation failed: {type(exc).__name__}: {exc}")
    evidence["live_environment"] = live_environment

    placement_record_path = repository_root / "environment" / "gpu-placement-v2.json"
    if expected_config_sha256 == EXPECTED_CONFIG_SHA256:
        try:
            placement_record = _read_json_object(placement_record_path)
            placement_record_sha256 = sha256_file(placement_record_path)
            if placement_record_sha256 != EXPECTED_GPU_PLACEMENT_SHA256:
                failures.append(
                    "GPU placement record SHA-256 mismatch: "
                    f"{placement_record_sha256} != {EXPECTED_GPU_PLACEMENT_SHA256}"
                )
            _check_equal(
                failures,
                "gpu_placement.schema_version",
                placement_record.get("schema_version"),
                2,
            )
            _check_equal(
                failures,
                "gpu_placement.config_sha256",
                placement_record.get("config_sha256"),
                config_sha256,
            )
            supersedes_runtime = placement_record.get("supersedes")
            if not isinstance(supersedes_runtime, Mapping):
                raise ValueError("GPU placement supersedes record must be an object")
            _check_equal(
                failures,
                "gpu_placement.supersedes.runtime_sha256",
                supersedes_runtime.get("sha256"),
                sha256_file(runtime_path),
            )
            script_path = _resolve_repo_path(
                repository_root,
                placement_record.get("script_path"),
                "gpu_placement.script_path",
            )
            _check_equal(
                failures,
                "gpu_placement.script_sha256",
                sha256_file(script_path),
                placement_record.get("script_sha256"),
            )
            log_path = Path(str(placement_record.get("log_path"))).resolve(strict=True)
            _check_equal(
                failures,
                "gpu_placement.log_sha256",
                sha256_file(log_path),
                placement_record.get("log_sha256"),
            )
        except (OSError, ValueError) as exc:
            failures.append(f"GPU placement record validation failed: {exc}")
            placement_record = {}
            placement_record_sha256 = None
            script_path = repository_root / "scripts" / "validate_gpu_placement.py"
            log_path = Path("/nonexistent/gpu-placement-validation.log")
    else:
        placement_record = {"gpu_validation": runtime.get("gpu_validation", {})}
        placement_record_sha256 = None
        script_path = None
        log_path = None
    evidence["gpu_placement_record"] = {
        "path": str(placement_record_path.resolve()),
        "sha256": placement_record_sha256,
        "script_path": None if script_path is None else str(script_path.resolve()),
        "log_path": None if log_path is None else str(log_path.resolve()),
        "record": placement_record,
    }

    try:
        git = dict(dependencies.git_probe(repository_root))
    except Exception as exc:  # noqa: BLE001 - validation must become terminal evidence
        git = {"probe_error": f"{type(exc).__name__}: {exc}", "clean": False}
        failures.append(f"Git probe failed: {type(exc).__name__}: {exc}")
    if require_clean_git and not git.get("clean"):
        failures.append("repository worktree is not clean")
    if git.get("origin_main") is not None and not git.get("head_matches_origin_main"):
        failures.append("repository HEAD does not match local origin/main")
    evidence["git"] = git

    try:
        hardware = dict(dependencies.hardware_probe())
    except Exception as exc:  # noqa: BLE001
        hardware = {"probe_error": f"{type(exc).__name__}: {exc}"}
        failures.append(f"hardware probe failed: {type(exc).__name__}: {exc}")
    placement = config.get("placement", {}) if isinstance(config.get("placement"), Mapping) else {}
    _check_equal(failures, "placement.node", placement.get("node"), "an12")
    _check_equal(failures, "placement.gpu_ids", placement.get("gpu_ids"), [4])
    _check_equal(
        failures,
        "placement.tensor_parallel_width",
        placement.get("tensor_parallel_width"),
        1,
    )
    _check_equal(failures, "placement.replica_count", placement.get("replica_count"), 1)
    _check_equal(failures, "hardware.node", hardware.get("node"), placement.get("node"))
    _check_equal(failures, "CUDA_VISIBLE_DEVICES", hardware.get("cuda_visible_devices"), "4")
    _check_equal(failures, "hardware.cuda_available", hardware.get("cuda_available"), True)
    _check_equal(failures, "hardware.visible_device_count", hardware.get("visible_device_count"), 1)
    recorded_gpu = placement_record.get("gpu_validation", {})
    recorded_gpu = recorded_gpu if isinstance(recorded_gpu, Mapping) else {}
    _check_equal(
        failures,
        "placement_record.gpu.cuda_visible_devices",
        recorded_gpu.get("cuda_visible_devices"),
        hardware.get("cuda_visible_devices"),
    )
    _check_equal(
        failures,
        "placement_record.gpu.visible_device_count",
        recorded_gpu.get("visible_device_count", 1),
        hardware.get("visible_device_count"),
    )
    _check_equal(
        failures,
        "placement_record.gpu.node",
        recorded_gpu.get("node"),
        placement.get("node"),
    )
    _check_equal(
        failures,
        "placement_record.gpu.gpu_ids",
        recorded_gpu.get("gpu_ids"),
        placement.get("gpu_ids"),
    )
    _check_equal(
        failures,
        "placement_record.gpu.tensor_parallel_width",
        recorded_gpu.get("tensor_parallel_width"),
        placement.get("tensor_parallel_width"),
    )
    _check_equal(
        failures,
        "placement_record.gpu.replica_count",
        recorded_gpu.get("replica_count"),
        placement.get("replica_count"),
    )
    devices = hardware.get("devices")
    if (
        not isinstance(devices, list)
        or len(devices) != 1
        or "A800" not in str(devices[0].get("name"))
    ):
        failures.append("the one visible CUDA device must identify as an A800")
    if process_context.get("cwd") != str(repository_root.resolve()):
        failures.append(
            f"process cwd must equal repository root: {process_context.get('cwd')!r} != "
            f"{str(repository_root.resolve())!r}"
        )
    evidence["placement"] = {"configured": dict(placement), "observed": hardware}

    manifest_path = repository_root / "provenance" / "weights.manifest.json"
    try:
        weights_manifest = _read_json_object(manifest_path)
        _check_equal(
            failures,
            "weights_manifest.schema_version",
            weights_manifest.get("schema_version"),
            1,
        )
        _check_equal(
            failures,
            "weights_manifest.label",
            weights_manifest.get("label"),
            "external_upstream",
        )
        licenses = weights_manifest.get("licenses")
        required_licenses = {
            "Stability AI Community License Agreement (2024-07-05)",
            "Gemma Terms of Use",
            "Gemma Prohibited Use Policy",
        }
        if not isinstance(licenses, list) or set(licenses) != required_licenses:
            failures.append("weights manifest license set differs from the frozen records")
        snapshot_value = _value(config, "model", "snapshot")
        if not isinstance(snapshot_value, str) or not snapshot_value:
            raise ValueError("model.snapshot must be a non-empty path")
        snapshot = Path(snapshot_value).resolve(strict=True)
        artifact_root_value = weights_manifest.get("artifact_root")
        if not isinstance(artifact_root_value, str) or not artifact_root_value:
            raise ValueError("weights manifest artifact_root must be a non-empty path")
        artifact_root = Path(artifact_root_value).resolve(strict=True)
        if not _same_filesystem_object(snapshot, artifact_root):
            raise ValueError("configured snapshot differs from weights manifest artifact_root")
        _check_equal(
            failures,
            "model.modelscope_revision",
            _value(config, "model", "modelscope_revision"),
            _value(weights_manifest, "modelscope", "revision"),
        )
        _check_equal(
            failures,
            "model.huggingface_revision",
            _value(config, "model", "huggingface_revision"),
            _value(weights_manifest, "huggingface", "revision"),
        )
        model_hashes, snapshot_evidence = _snapshot_verification(snapshot, weights_manifest)
    except (OSError, ValueError) as exc:
        failures.append(f"snapshot verification failed: {exc}")
        snapshot = Path(str(_value(config, "model", "snapshot") or ".")).resolve()
        snapshot_evidence = {"status": "FAIL", "error": str(exc), "artifact_root": str(snapshot)}
    v1_manifest_evidence = {
        "path": str(manifest_path.resolve()),
        "sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
        "schema_version": weights_manifest.get("schema_version"),
        "status": snapshot_evidence.get("status"),
    }
    overlay_path = repository_root / "provenance" / "weights.cross-provider-verification.v2.json"
    try:
        _, overlay_evidence = _validate_cross_provider_overlay(
            overlay_path=overlay_path,
            v1_manifest_path=manifest_path,
            v1_manifest=weights_manifest,
            config=config,
        )
    except (OSError, ValueError) as exc:
        failures.append(f"cross-provider verification failed: {exc}")
        overlay_evidence = {
            "path": str(overlay_path.resolve()),
            "sha256": sha256_file(overlay_path) if overlay_path.is_file() else None,
            "schema_version": None,
            "status": "FAIL",
            "error": str(exc),
            "v1_cross_provider_flags_trusted": False,
        }
    evidence["weights_manifest"] = v1_manifest_evidence
    evidence["weights_manifests"] = {
        "local_snapshot_v1": v1_manifest_evidence,
        "cross_provider_v2": overlay_evidence,
    }
    evidence["live_snapshot_verification"] = snapshot_evidence
    evidence["process_context"] = dict(process_context)
    evidence["runtime_record"] = runtime
    return PreflightReport(
        passed=not failures,
        failures=tuple(failures),
        config=config,
        evidence=evidence,
        weights_manifest=weights_manifest,
        model_artifact_sha256s=model_hashes,
    )


def _normalize_result(
    smoke: str,
    value: Any,
    *,
    started_at: str,
    ended_at: str,
) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if not isinstance(value, Mapping):
        raise TypeError(f"smoke {smoke} returned {type(value).__name__}, expected mapping")
    result = dict(value)
    status = result.get("status")
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"smoke {smoke} returned invalid terminal status: {status!r}")
    result.setdefault("smoke", smoke)
    result.setdefault("started_at_utc", started_at)
    result.setdefault("ended_at_utc", ended_at)
    json.dumps(result, allow_nan=False)
    return result


def _failure_result(
    smoke: str,
    *,
    stage: str,
    message: str,
    started_at: str | None = None,
) -> dict[str, Any]:
    started = started_at or _utc_now()
    return {
        "smoke": smoke,
        "status": "FAIL",
        "started_at_utc": started,
        "ended_at_utc": _utc_now(),
        "parameters": {},
        "checks": {"execution_completed": False},
        "metrics": {},
        "artifacts": [],
        "error": {"stage": stage, "message": message},
    }


def _execute(
    smoke: str,
    function: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    started = _utc_now()
    try:
        with smoke_context(smoke):
            value = function(*args, **kwargs)
        return _normalize_result(smoke, value, started_at=started, ended_at=_utc_now())
    except Exception as exc:  # noqa: BLE001 - every smoke must become terminal
        return _failure_result(
            smoke,
            stage="smoke_execution",
            message=f"{type(exc).__name__}: {exc}",
            started_at=started,
        )


def _source_audio_from_result(result: Mapping[str, Any]) -> str | None:
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        path = artifact.get("path")
        if isinstance(path, str) and path.lower().endswith(".wav") and Path(path).is_file():
            return path
    return None


def _artifact_paths(value: Any, run_dir: Path) -> list[str]:
    paths: set[str] = set()

    def visit(item: Any, key: str | None = None) -> None:
        if isinstance(item, Mapping):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for child in item:
                visit(child, key)
        elif isinstance(item, str) and key is not None and "path" in key.lower():
            candidate = Path(item)
            if candidate.is_file():
                resolved = candidate.resolve()
                if resolved.is_relative_to(run_dir.resolve()):
                    paths.add(str(resolved))

    visit(value)
    return sorted(paths)


def _seed_rows(config: Mapping[str, Any], smoke: str) -> list[dict[str, Any]]:
    rows = {
        "A": [("seed_id", "seed")],
        "B": [("seed_id", "seed")],
        "C": [("single_seed_id", "single_seed"), ("multi_seed_id", "multi_seed")],
        "D": [("single_seed_id", "single_seed"), ("batch_seed_id", "batch_seed")],
        "E": [("seed_id", "seed")],
    }[smoke]
    section = _value(config, "smokes", smoke.lower())
    section = section if isinstance(section, Mapping) else {}
    return [
        {"seed_id": section.get(identifier_key), "value": section.get(value_key)}
        for identifier_key, value_key in rows
    ]


def _resolution_dict(resolution: Any) -> dict[str, Any]:
    if hasattr(resolution, "to_dict"):
        value = resolution.to_dict()
    elif hasattr(resolution, "__dataclass_fields__"):
        value = asdict(resolution)
    elif isinstance(resolution, Mapping):
        value = dict(resolution)
    else:
        raise TypeError("model config resolution must be mapping-like")
    if not isinstance(value, dict):
        raise TypeError("model config resolution to_dict() must return a dict")
    return value


def _verify_resolution_against_manifest(
    resolution: Any,
    model_hashes: Mapping[str, str],
) -> dict[str, Any]:
    value = _resolution_dict(resolution)
    original_hash = value.get("original_sha256")
    expected_original = model_hashes.get("model_config.json")
    if original_hash != expected_original:
        raise ValueError(
            f"resolved original config hash differs from manifest: "
            f"{original_hash} != {expected_original}"
        )
    t5_hashes = value.get("t5_snapshot_file_sha256s")
    if not isinstance(t5_hashes, Mapping):
        raise ValueError("config resolution lacks T5Gemma digest map")
    if set(t5_hashes) != set(REQUIRED_T5_MANIFEST_FILES):
        raise ValueError("config resolution T5Gemma digest map has a missing or unexpected file")
    expected_t5 = {
        relative: model_hashes.get(f"t5gemma-b-b-ul2/{relative}")
        for relative in REQUIRED_T5_MANIFEST_FILES
    }
    if any(digest is None for digest in expected_t5.values()):
        raise ValueError("committed manifest lacks a required T5Gemma runtime file")
    if dict(t5_hashes) != expected_t5:
        raise ValueError("resolved T5Gemma digest map differs from committed manifest")
    return {
        "status": "PASS",
        "original_config_sha256": original_hash,
        "resolved_config_sha256": value.get("resolved_sha256"),
        "diff_sha256": value.get("diff_sha256"),
        "t5_file_count": len(t5_hashes),
        "manifest_match": True,
    }


def _common_manifest(
    *,
    smoke: str,
    result: Mapping[str, Any],
    run_dir: Path,
    preflight: PreflightReport,
    config_path: Path,
    process_context: Mapping[str, Any],
    resolution: Any | None,
    deviations: Sequence[Mapping[str, Any] | str],
) -> dict[str, Any]:
    config = preflight.config
    placement = _value(config, "placement")
    placement = placement if isinstance(placement, Mapping) else {}
    environment_freeze = preflight.evidence.get("environment_freeze", {})
    git = preflight.evidence.get("git", {})
    protocol = preflight.evidence.get("protocol", {})
    audio = _value(config, "audio")
    audio = dict(audio) if isinstance(audio, Mapping) else {}
    sampling = _value(config, "sampling")
    sampling = dict(sampling) if isinstance(sampling, Mapping) else {}
    smoke_protocol = _value(config, "smokes", smoke.lower())
    smoke_protocol = dict(smoke_protocol) if isinstance(smoke_protocol, Mapping) else {}
    return {
        "schema_version": 1,
        "run_id": f"{run_dir.name}-{smoke.lower()}",
        "smoke": smoke,
        "status": result["status"],
        "node": placement.get("node"),
        "gpu_ids": placement.get("gpu_ids"),
        "tensor_parallel_width": placement.get("tensor_parallel_width"),
        "replica_count": placement.get("replica_count"),
        "placement_justification": placement.get("justification"),
        "exact_command": process_context.get("exact_command"),
        "process": dict(process_context),
        "repository_cwd": process_context.get("cwd"),
        "repository_git_hash": git.get("head"),
        "repository_git_branch": git.get("branch"),
        "repository_git_clean": git.get("clean"),
        "repository_git_status": git.get("porcelain_v1"),
        "repository_head_matches_origin_main": git.get("head_matches_origin_main"),
        "configuration_path": str(config_path.resolve()),
        "configuration_sha256": preflight.evidence.get("configuration", {}).get("sha256"),
        "frozen_configuration": dict(config),
        "protocol_path": protocol.get("path"),
        "protocol_sha256": protocol.get("sha256"),
        "frozen_protocol_fields": {
            "audio": audio,
            "sampling": sampling,
            "smoke": smoke_protocol,
        },
        "seeds": _seed_rows(config, smoke),
        "seed_registry": preflight.evidence.get("seed_registry"),
        "package_freeze_path": environment_freeze.get("path"),
        "package_freeze_sha256": environment_freeze.get("sha256"),
        "live_environment_validation": preflight.evidence.get("live_environment"),
        "gpu_placement_record": preflight.evidence.get("gpu_placement_record"),
        "model_artifact_sha256s": dict(preflight.model_artifact_sha256s),
        "weights_manifests": preflight.evidence.get("weights_manifests"),
        "governance_authorization": preflight.evidence.get("governance_authorization"),
        "model_config_resolution": _resolution_dict(resolution) if resolution else None,
        "started_at_utc": result.get("started_at_utc"),
        "ended_at_utc": result.get("ended_at_utc"),
        "artifact_paths": _artifact_paths(result, run_dir),
        "deviations": list(deviations),
        "result": dict(result),
    }


def _write_smoke_manifest(
    smoke_dir: Path,
    manifest: Mapping[str, Any],
) -> tuple[Path, str]:
    path = smoke_dir / "manifest.json"
    exclusive_write_json(path, manifest)
    return path, sha256_file(path)


def _provenance_context(
    *,
    run_dir: Path,
    smoke: str,
    config: Mapping[str, Any],
    command: str,
) -> dict[str, Any]:
    model = _value(config, "model")
    model = model if isinstance(model, Mapping) else {}
    return {
        "creating_command": command,
        "run_id": f"{run_dir.name}-{smoke.lower()}",
        "source_ids": [
            f"{model.get('id')}@huggingface:{model.get('huggingface_revision')}",
            f"{model.get('id')}@modelscope:{model.get('modelscope_revision')}",
        ],
        "model_revision": str(model.get("huggingface_revision")),
        "license_identifier": LICENSE_IDENTIFIER,
    }


def _smoke_e_kwargs(
    *,
    frozen_config_path: Path,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build only the keyword-only arguments accepted by live smoke E."""

    return {
        "frozen_config_path": frozen_config_path,
        "provenance": provenance,
        "python_executable": sys.executable,
    }


def run_foundation(
    config_path: str | os.PathLike[str] = DEFAULT_CONFIG_PATH,
    *,
    repository_root: str | os.PathLike[str] = REPOSITORY_ROOT,
    run_root: str | os.PathLike[str] | None = None,
) -> FoundationRunOutcome:
    """Run the canonical live path with every authorization guard enabled.

    Dependency injection and relaxed provenance checks intentionally are not
    part of this public entry point.  CPU orchestration tests use the private
    ``_run_foundation_for_testing`` boundary below.
    """

    return _run_foundation_core(
        config_path=config_path,
        repository_root=repository_root,
        run_root=run_root,
        expected_config_sha256=EXPECTED_CONFIG_SHA256,
        dependencies=default_dependencies(),
        process_context=None,
        require_clean_git=True,
        live_execution=True,
    )


def _run_foundation_for_testing(
    config_path: str | os.PathLike[str],
    *,
    repository_root: str | os.PathLike[str],
    run_root: str | os.PathLike[str],
    expected_config_sha256: str,
    dependencies: OrchestrationDependencies,
    process_context: Mapping[str, Any],
    require_clean_git: bool = True,
) -> FoundationRunOutcome:
    """Exercise orchestration with CPU fakes; never use for model execution."""

    if not dependencies.testing_only:
        raise ValueError("the private test entry point requires testing-only dependencies")

    return _run_foundation_core(
        config_path=config_path,
        repository_root=repository_root,
        run_root=run_root,
        expected_config_sha256=expected_config_sha256,
        dependencies=dependencies,
        process_context=process_context,
        require_clean_git=require_clean_git,
        live_execution=False,
    )


def _run_foundation_core(
    config_path: str | os.PathLike[str],
    *,
    repository_root: str | os.PathLike[str],
    run_root: str | os.PathLike[str] | None,
    expected_config_sha256: str,
    dependencies: OrchestrationDependencies,
    process_context: Mapping[str, Any] | None,
    require_clean_git: bool,
    live_execution: bool,
) -> FoundationRunOutcome:
    """Validate, run A--E, and retain strict terminal results/manifests."""

    if live_execution == dependencies.testing_only:
        raise ValueError("execution mode does not match the dependency boundary")

    started_at = _utc_now()
    repo = Path(repository_root).resolve()
    config_file = Path(config_path).resolve()
    context = dict(process_context or capture_process_context())
    deps = dependencies
    preflight = validate_preflight(
        config_path=config_file,
        repository_root=repo,
        expected_config_sha256=expected_config_sha256,
        dependencies=deps,
        process_context=context,
        require_clean_git=require_clean_git,
    )

    configured_run_root = _value(preflight.config, "run_root")
    selected_run_root = Path(
        run_root
        if run_root is not None
        else configured_run_root
        if isinstance(configured_run_root, str) and preflight.passed
        else DEFAULT_RUN_ROOT
    )
    run_dir = create_immutable_run_dir(selected_run_root, prefix="sa3-foundation")
    smoke_dirs = {
        smoke: create_immutable_directory(run_dir / f"smoke-{smoke.lower()}")
        for smoke in SMOKE_NAMES
    }
    resolution_dir = create_immutable_directory(run_dir / "model-config-resolution")

    resolution: Any | None = None
    runtime: Any | None = None
    setup_failure: str | None = None
    resolution_verification: dict[str, Any] | None = None
    budget: ExecutionBudget | None = None
    load_attempt_count = 0
    load_success_count = 0
    model_load_wall_seconds: float | None = None
    if not preflight.passed:
        setup_failure = "preflight validation failed: " + "; ".join(preflight.failures)
    elif live_execution and (
        not isinstance(configured_run_root, str)
        or selected_run_root.resolve() != Path(configured_run_root).resolve()
    ):
        setup_failure = (
            "live execution must use the frozen configured run_root so the one-shot "
            "authorization claim cannot be bypassed"
        )
    elif live_execution:
        try:
            budget = ExecutionBudget.initialize(
                run_dir=run_dir,
                run_root=Path(configured_run_root).resolve(),
                claim_identity={
                    "repository_git_hash": preflight.evidence.get("git", {}).get("head"),
                    "configuration_sha256": preflight.evidence.get("configuration", {}).get(
                        "sha256"
                    ),
                    "protocol_sha256": preflight.evidence.get("protocol", {}).get("sha256"),
                    "seed_registry_sha256": preflight.evidence.get("seed_registry", {}).get(
                        "sha256"
                    ),
                    "decisions_sha256": preflight.evidence.get("governance_authorization", {}).get(
                        "sha256"
                    ),
                    "environment_freeze_sha256": preflight.evidence.get(
                        "environment_freeze", {}
                    ).get("sha256"),
                    "runtime_record_sha256": preflight.evidence.get("environment_freeze", {}).get(
                        "runtime_record_sha256"
                    ),
                    "weights_manifest_sha256": preflight.evidence.get("weights_manifests", {})
                    .get("local_snapshot_v1", {})
                    .get("sha256"),
                    "cross_provider_overlay_sha256": preflight.evidence.get("weights_manifests", {})
                    .get("cross_provider_v2", {})
                    .get("sha256"),
                    "gpu_placement_record_sha256": preflight.evidence.get(
                        "gpu_placement_record", {}
                    ).get("sha256"),
                    "observed_placement": preflight.evidence.get("placement"),
                },
            )
        except Exception as exc:  # noqa: BLE001 - claim failures must precede model load
            setup_failure = f"execution_budget initialization failed: {type(exc).__name__}: {exc}"

    if preflight.passed and setup_failure is None:
        snapshot = Path(str(_value(preflight.config, "model", "snapshot"))).resolve()
        try:
            resolution = deps.resolve_model_config(
                snapshot / "model_config.json",
                snapshot / "t5gemma-b-b-ul2",
                resolution_dir,
            )
            resolution_verification = _verify_resolution_against_manifest(
                resolution, preflight.model_artifact_sha256s
            )
            load_attempt_count += 1
            load_started = time.perf_counter()
            runtime = deps.load_model(
                resolution,
                snapshot / "model.safetensors",
                device="cuda:0",
                model_half=bool(_value(preflight.config, "model", "model_half")),
                expected_checkpoint_sha256=preflight.model_artifact_sha256s["model.safetensors"],
            )
            if live_execution:
                import torch

                torch.cuda.synchronize(torch.device("cuda:0"))
            model_load_wall_seconds = float(time.perf_counter() - load_started)
            load_success_count += 1
        except Exception as exc:  # noqa: BLE001 - fan out to five terminal results
            setup_failure = f"model_setup failed: {type(exc).__name__}: {exc}"

    config = preflight.config
    sampling = config.get("sampling", {}) if isinstance(config.get("sampling"), Mapping) else {}
    smoke_config = config.get("smokes", {}) if isinstance(config.get("smokes"), Mapping) else {}
    deviations: list[Mapping[str, Any] | str] = []
    runtime_record = preflight.evidence.get("runtime_record")
    if isinstance(runtime_record, Mapping) and runtime_record.get("storage_deviation"):
        deviations.append({"runtime_storage": runtime_record["storage_deviation"]})
    if resolution is not None:
        deviations.append(
            {
                "conditioner_resolution": (
                    "Only repo_id/subfolder was replaced by the verified embedded "
                    "T5Gemma model_path; original config and diff retained."
                )
            }
        )

    results: dict[str, dict[str, Any]] = {}
    manifest_records: dict[str, dict[str, Any]] = {}

    def retain(smoke: str, result: dict[str, Any]) -> None:
        if budget is not None:
            snapshot_path = smoke_dirs[smoke] / "execution-budget.snapshot.json"
            exclusive_write_json(snapshot_path, budget.immutable_snapshot())
            metrics = result.get("metrics")
            metrics = dict(metrics) if isinstance(metrics, Mapping) else {}
            summary = budget.summary()
            metrics["execution_budget_after_smoke"] = {
                "snapshot_path": str(snapshot_path.resolve()),
                "snapshot_sha256": sha256_file(snapshot_path),
                "official_generate_calls_reserved": summary["official_generate_calls_reserved"],
                "generation_slots_reserved": summary["generation_slots_reserved"],
                "ledgered_outputs": summary["ledgered_outputs"],
                "cumulative_synchronized_gpu_wall_seconds": summary[
                    "cumulative_synchronized_gpu_wall_seconds"
                ],
                "gpu_residency_upper_bound_seconds": summary["gpu_residency_upper_bound_seconds"],
            }
            result["metrics"] = metrics
        smoke_deviations = list(deviations)
        if result["status"] != "PASS":
            smoke_deviations.append(
                {"terminal_failure": result.get("error", "smoke returned FAIL")}
            )
        manifest = _common_manifest(
            smoke=smoke,
            result=result,
            run_dir=run_dir,
            preflight=preflight,
            config_path=config_file,
            process_context=context,
            resolution=resolution,
            deviations=smoke_deviations,
        )
        path, digest = _write_smoke_manifest(smoke_dirs[smoke], manifest)
        results[smoke] = result
        manifest_records[smoke] = {
            "path": str(path.resolve()),
            "sha256": digest,
            "status": result["status"],
        }

    if setup_failure is not None or runtime is None:
        failure = setup_failure or "model runtime was not created"
        for smoke in SMOKE_NAMES:
            retain(smoke, _failure_result(smoke, stage="setup", message=failure))
    else:
        common = {
            "negative_prompt": sampling["negative_prompt"],
            "chunked_decode": sampling["chunked_decode"],
            "duration": sampling["duration_seconds"],
            "steps": sampling["steps"],
            "cfg_scale": sampling["cfg_scale"],
        }
        provenance_a = _provenance_context(
            run_dir=run_dir,
            smoke="A",
            config=config,
            command=str(context["exact_command"]),
        )
        result_a = _execute(
            "A",
            deps.run_smoke_a,
            runtime,
            smoke_dirs["A"],
            prompt=sampling["prompt"],
            provenance=provenance_a,
            seed=smoke_config["a"]["seed"],
            **common,
        )
        retain("A", result_a)
        source_audio = _source_audio_from_result(result_a)

        if source_audio is None:
            result_b = _failure_result(
                "B", stage="dependency", message="smoke A produced no retained source WAV"
            )
            result_c = _failure_result(
                "C", stage="dependency", message="smoke A produced no retained source WAV"
            )
        else:
            result_b = _execute(
                "B",
                deps.run_smoke_b,
                runtime,
                source_audio,
                smoke_dirs["B"],
                prompt=smoke_config["b"]["prompt"],
                provenance=_provenance_context(
                    run_dir=run_dir,
                    smoke="B",
                    config=config,
                    command=str(context["exact_command"]),
                ),
                seed=smoke_config["b"]["seed"],
                source_duration=smoke_config["b"]["source_seconds"],
                **common,
            )
            result_c = _execute(
                "C",
                deps.run_smoke_c,
                runtime,
                source_audio,
                smoke_dirs["C"],
                prompt=smoke_config["c"]["prompt"],
                provenance=_provenance_context(
                    run_dir=run_dir,
                    smoke="C",
                    config=config,
                    command=str(context["exact_command"]),
                ),
                single_seed=smoke_config["c"]["single_seed"],
                multi_seed=smoke_config["c"]["multi_seed"],
                **common,
            )
        retain("B", result_b)
        retain("C", result_c)

        result_d = _execute(
            "D",
            deps.run_smoke_d,
            runtime,
            smoke_dirs["D"],
            prompt=sampling["prompt"],
            provenance=_provenance_context(
                run_dir=run_dir,
                smoke="D",
                config=config,
                command=str(context["exact_command"]),
            ),
            negative_prompt=sampling["negative_prompt"],
            chunked_decode=sampling["chunked_decode"],
            batch4_prompts=smoke_config["d"]["batch_prompts"],
            batch1_seed=smoke_config["d"]["single_seed"],
            batch4_seed=smoke_config["d"]["batch_seed"],
            steps=sampling["steps"],
            cfg_scale=sampling["cfg_scale"],
        )
        retain("D", result_d)

        result_e = _execute(
            "E",
            deps.run_smoke_e,
            runtime,
            smoke_dirs["E"],
            **_smoke_e_kwargs(
                frozen_config_path=config_file,
                provenance=_provenance_context(
                    run_dir=run_dir,
                    smoke="E",
                    config=config,
                    command=str(context["exact_command"]),
                ),
            ),
        )
        retain("E", result_e)

    budget_summary: dict[str, Any] | None = budget.finalize() if budget is not None else None
    statuses = {smoke: results[smoke]["status"] for smoke in SMOKE_NAMES}
    all_terminal = all(status in TERMINAL_STATUSES for status in statuses.values())
    budget_pass = budget_summary is None or budget_summary["status"] == "PASS"
    all_pass = all(status == "PASS" for status in statuses.values()) and budget_pass
    smoke_status = "PASS" if all_pass else "FAIL_ESCALATED"
    exit_code = 0 if all_pass else 1
    ended_at = _utc_now()
    top_result: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "run_dir": str(run_dir.resolve()),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "SMOKE_STATUS": smoke_status,
        "exit_code": exit_code,
        "summary": {
            "statuses": statuses,
            "all_five_terminal": all_terminal,
            "pass_count": sum(status == "PASS" for status in statuses.values()),
            "failure_count": sum(status != "PASS" for status in statuses.values()),
            "execution_budget_pass": budget_pass,
        },
        "preflight": {
            "status": "PASS" if preflight.passed else "FAIL",
            "failures": list(preflight.failures),
            "evidence": dict(preflight.evidence),
        },
        "model_setup": {
            "status": "PASS" if setup_failure is None and runtime is not None else "FAIL",
            "error": setup_failure,
            "config_resolution": _resolution_dict(resolution) if resolution else None,
            "resolution_manifest_verification": resolution_verification,
            "load_attempt_count": load_attempt_count,
            "load_success_count": load_success_count,
            "load_count": load_success_count,
            "model_load_wall_seconds": model_load_wall_seconds,
            "offline_only": True,
        },
        "execution_budget": budget_summary,
        "smokes": {
            smoke: {
                "status": statuses[smoke],
                "result": results[smoke],
                "manifest": manifest_records[smoke],
            }
            for smoke in SMOKE_NAMES
        },
    }
    result_path = run_dir / "result.json"
    exclusive_write_json(result_path, top_result)
    return FoundationRunOutcome(
        exit_code=exit_code,
        run_dir=run_dir,
        result_path=result_path,
        result=top_result,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--run-root", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    outcome = run_foundation(
        args.config,
        repository_root=args.repository_root,
        run_root=args.run_root,
    )
    print(
        json.dumps(
            {
                "SMOKE_STATUS": outcome.result["SMOKE_STATUS"],
                "exit_code": outcome.exit_code,
                "result_path": str(outcome.result_path),
                "run_dir": str(outcome.run_dir),
                "statuses": outcome.result["summary"]["statuses"],
            },
            allow_nan=False,
            sort_keys=True,
        )
    )
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

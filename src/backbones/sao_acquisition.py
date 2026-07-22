"""No-clobber, token-hygienic Stable Audio Open snapshot acquisition.

The provider token is accepted only through the configured environment
variable, removed from that environment before the first provider call, passed
explicitly in memory, and never included in returned or persisted records.
Importing this module performs no network access and writes nothing.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import stat
from collections.abc import Callable, MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backbones.contracts import (
    DEFAULT_SAO_CONFIG,
    REVISION_RE,
    sha256_file,
    strict_json_object,
)

MODEL_ID = "stabilityai/stable-audio-open-1.0"
DECISION_ID = "D-0037"
RECOVERY_DECISION_ID = "D-0039"
RECOVERY_SOURCE_RUN_ID = "sao-acquisition-v2-001"
RECOVERY_RUN_ID = "sao-acquisition-recovery-v2-001"
RECOVERY_REVISION = "f21265c1e2710b3bd2386596943f0007f55f802e"
RECOVERY_FAILURE_TERMINAL_SHA256 = (
    "d1b7f3c35ab211372910db3ba9a0a73abcf2b24d49745f3d0717cdb77096db82"
)
RECOVERY_ACQUISITION_MANIFEST_SHA256 = (
    "65d1f48497ec451f5620327b006b85d1f34e084c164802b5ddfe0230b402f8e9"
)
RECOVERY_ATTEMPT2_DECISION_ID = "D-0041"
RECOVERY_ATTEMPT2_RUN_ID = "sao-acquisition-recovery-v2-002"
RECOVERY_ATTEMPT2_MATERIALIZATION = "HARDLINK_CLONE_RETAINED_STAGE"
RECOVERY_ATTEMPT1_ACCESS_RECEIPT_SHA256 = (
    "1fd37fc4e59ba8439f1dcc6c17b9b04a54f9652474e5fd72e8748bfb71188eb5"
)
RECOVERY_ATTEMPT1_SNAPSHOT_MANIFEST_SHA256 = (
    "e3756f588cf5db90a122e597f3582f2a3c4ee66316b239383c78927402da0b39"
)
RECOVERY_ATTEMPT1_TREE_SHA256 = (
    "354b42d6e427a3ab68558a427754dcd949a734d9bddd8cdb293a48d16fab3b8c"
)
RECOVERY_ATTEMPT1_FAILURE_LOG_SHA256 = (
    "02a9d101c1c20cc9b73fb7e381f1c03cd6929c5eb4105203faf290f211dd1477"
)
EXECUTE_ACK = "I_ACKNOWLEDGE_SAO_ACQUISITION_USES_ONE_EPHEMERAL_READ_TOKEN"
TOKEN_ENVIRONMENT_VARIABLE = "HF_TOKEN"
CONFIG_STATUS = "CLOSED_UNTIL_D0037_LIVE_BINDING"
REQUIRED_DECISION_ASSIGNMENTS = (
    "SAO_ACQUISITION_AUTHORIZED = YES",
    "SAO_MINI_SMOKE_EXACT_CALLS = 3",
    "SAO_CORE_EXACT_ROWS = 1536",
    "SAO_STATE_CAPABILITY = NOT_ATTEMPTED",
    "SAO_ELIGIBILITY_SCOPE_EXPANDED = NO",
)
LICENSE_CANDIDATES = ("LICENSE", "LICENSE.md", "LICENSE.txt")
RECOVERY_SOURCE_RUN_FILES = frozenset(
    {"acquisition-manifest.json", "terminal-failure.json"}
)
RECOVERY_ATTEMPT1_RUN_FILES = frozenset(
    {"access-receipt.json", "snapshot-manifest.json"}
)


class SaoAcquisitionError(RuntimeError):
    """Fail-closed acquisition error with no provider credential payload."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_exclusive(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _decision_block(text: str, decision_id: str) -> str:
    matches = list(
        re.finditer(
        rf"(?ms)^## {re.escape(decision_id)}\b.*?(?=^## D-\d+\b|\Z)",
        text,
        )
    )
    if not matches:
        raise SaoAcquisitionError(f"required decision is absent: {decision_id}")
    if len(matches) != 1:
        raise SaoAcquisitionError(f"required decision is duplicated: {decision_id}")
    return matches[0].group(0)


def _single_decision_assignment(
    block: str,
    key: str,
    *,
    decision_id: str = RECOVERY_DECISION_ID,
) -> str:
    values: list[str] = []
    pattern = re.compile(rf"{re.escape(key)}\s*=\s*(\S+)")
    for line in block.splitlines():
        candidate = line.strip()
        if candidate.startswith("`") and candidate.endswith("`"):
            candidate = candidate[1:-1].strip()
        match = pattern.fullmatch(candidate)
        if match is not None:
            values.append(match.group(1))
    if len(values) != 1:
        raise SaoAcquisitionError(
            f"{decision_id} must contain exactly one {key} assignment"
        )
    return values[0]


def validate_recovery_decision(decisions_path: Path) -> dict[str, str]:
    """Validate the one fixed, offline retained-stage recovery authority."""

    try:
        source = decisions_path.resolve(strict=True)
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoAcquisitionError("cannot read SAO recovery decision") from exc
    block = _decision_block(text, RECOVERY_DECISION_ID)
    expected = {
        "SAO_ACQUISITION_RECOVERY_AUTHORIZED": "YES",
        "SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID": RECOVERY_SOURCE_RUN_ID,
        "SAO_ACQUISITION_RECOVERY_RUN_ID": RECOVERY_RUN_ID,
        "SAO_ACQUISITION_RECOVERY_REVISION": RECOVERY_REVISION,
        "SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256": (
            RECOVERY_FAILURE_TERMINAL_SHA256
        ),
        "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS": "NO",
        "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS": "NO",
        "SAO_ACQUISITION_RECOVERY_MODEL_CALLS": "0",
    }
    observed_keys: list[str] = []
    assignment_pattern = re.compile(r"(SAO_ACQUISITION_RECOVERY_[A-Z0-9_]+)\s*=\s*\S+")
    for line in block.splitlines():
        candidate = line.strip()
        if candidate.startswith("`") and candidate.endswith("`"):
            candidate = candidate[1:-1].strip()
        match = assignment_pattern.fullmatch(candidate)
        if match is not None:
            observed_keys.append(match.group(1))
    if set(observed_keys) != set(expected):
        extra = sorted(set(observed_keys).difference(expected))
        missing = sorted(set(expected).difference(observed_keys))
        raise SaoAcquisitionError(
            f"{RECOVERY_DECISION_ID} recovery assignment vocabulary changed: "
            f"missing={missing}, extra={extra}"
        )
    for key, expected_value in expected.items():
        if _single_decision_assignment(block, key) != expected_value:
            raise SaoAcquisitionError(
                f"{RECOVERY_DECISION_ID} assignment mismatch: {key}"
            )
    if re.search(r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE)\b", block, re.IGNORECASE):
        raise SaoAcquisitionError(f"{RECOVERY_DECISION_ID} contains an unresolved marker")
    return {
        "decision_id": RECOVERY_DECISION_ID,
        "decision_path": str(source),
        "decision_file_sha256": sha256_file(source),
        "decision_block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
    }


def validate_recovery_attempt2_decision(decisions_path: Path) -> dict[str, str]:
    """Validate the fixed D-0041 hard-link materialization authority."""

    try:
        source = decisions_path.resolve(strict=True)
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoAcquisitionError("cannot read SAO recovery-attempt-2 decision") from exc
    block = _decision_block(text, RECOVERY_ATTEMPT2_DECISION_ID)
    expected = {
        "SAO_ACQUISITION_RECOVERY_AUTHORIZED": "YES",
        "SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID": RECOVERY_SOURCE_RUN_ID,
        "SAO_ACQUISITION_RECOVERY_FAILED_RECOVERY_RUN_ID": RECOVERY_RUN_ID,
        "SAO_ACQUISITION_RECOVERY_RUN_ID": RECOVERY_ATTEMPT2_RUN_ID,
        "SAO_ACQUISITION_RECOVERY_REVISION": RECOVERY_REVISION,
        "SAO_ACQUISITION_RECOVERY_FAILED_ACCESS_RECEIPT_SHA256": (
            RECOVERY_ATTEMPT1_ACCESS_RECEIPT_SHA256
        ),
        "SAO_ACQUISITION_RECOVERY_FAILED_SNAPSHOT_MANIFEST_SHA256": (
            RECOVERY_ATTEMPT1_SNAPSHOT_MANIFEST_SHA256
        ),
        "SAO_ACQUISITION_RECOVERY_FAILED_RECOVERY_TREE_SHA256": (
            RECOVERY_ATTEMPT1_TREE_SHA256
        ),
        "SAO_ACQUISITION_RECOVERY_FAILURE_LOG_SHA256": (
            RECOVERY_ATTEMPT1_FAILURE_LOG_SHA256
        ),
        "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS": "NO",
        "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS": "NO",
        "SAO_ACQUISITION_RECOVERY_MODEL_CALLS": "0",
        "SAO_ACQUISITION_RECOVERY_MATERIALIZATION": (
            RECOVERY_ATTEMPT2_MATERIALIZATION
        ),
    }
    observed_keys: list[str] = []
    assignment_pattern = re.compile(
        r"(SAO_ACQUISITION_RECOVERY_[A-Z0-9_]+)\s*=\s*\S+"
    )
    for line in block.splitlines():
        candidate = line.strip()
        if candidate.startswith("`") and candidate.endswith("`"):
            candidate = candidate[1:-1].strip()
        match = assignment_pattern.fullmatch(candidate)
        if match is not None:
            observed_keys.append(match.group(1))
    if set(observed_keys) != set(expected):
        extra = sorted(set(observed_keys).difference(expected))
        missing = sorted(set(expected).difference(observed_keys))
        raise SaoAcquisitionError(
            f"{RECOVERY_ATTEMPT2_DECISION_ID} recovery assignment vocabulary changed: "
            f"missing={missing}, extra={extra}"
        )
    for key, expected_value in expected.items():
        if (
            _single_decision_assignment(
                block,
                key,
                decision_id=RECOVERY_ATTEMPT2_DECISION_ID,
            )
            != expected_value
        ):
            raise SaoAcquisitionError(
                f"{RECOVERY_ATTEMPT2_DECISION_ID} assignment mismatch: {key}"
            )
    if re.search(r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE)\b", block, re.IGNORECASE):
        raise SaoAcquisitionError(
            f"{RECOVERY_ATTEMPT2_DECISION_ID} contains an unresolved marker"
        )
    return {
        "decision_id": RECOVERY_ATTEMPT2_DECISION_ID,
        "decision_path": str(source),
        "decision_file_sha256": sha256_file(source),
        "decision_block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
    }


def validate_live_config(config_path: Path, decisions_path: Path) -> dict[str, Any]:
    """Validate the static closed config and its external D-0037 live binding."""

    config = strict_json_object(config_path)
    expected_keys = {
        "schema_version",
        "status",
        "model_id",
        "backbone_config",
        "acquisition",
        "mini_smoke",
        "core",
    }
    if set(config) != expected_keys or config.get("schema_version") != 1:
        raise SaoAcquisitionError("SAO live config schema/keys are invalid")
    if config["status"] != CONFIG_STATUS or config["model_id"] != MODEL_ID:
        raise SaoAcquisitionError("SAO live config status/model identity is invalid")
    backbone = config["backbone_config"]
    expected_backbone_sha = sha256_file(DEFAULT_SAO_CONFIG)
    if backbone != {
        "path": "configs/backbones/stable_audio_open_1_0.json",
        "sha256": expected_backbone_sha,
    }:
        raise SaoAcquisitionError("SAO live config does not bind the frozen adapter config")
    acquisition = config["acquisition"]
    if acquisition.get("provider") != "huggingface_hub":
        raise SaoAcquisitionError("SAO acquisition provider must be huggingface_hub")
    if acquisition.get("token_environment_variable") != TOKEN_ENVIRONMENT_VARIABLE:
        raise SaoAcquisitionError("SAO token environment variable changed")
    if acquisition.get("requested_revision") != "main":
        raise SaoAcquisitionError("SAO acquisition must resolve main to an exact revision first")
    if acquisition.get("proxy_wrapper") != "scripts/with_proxy.sh":
        raise SaoAcquisitionError("SAO acquisition must use the project proxy wrapper")
    for key in ("snapshot_root", "run_root"):
        path = Path(str(acquisition.get(key, "")))
        if not path.is_absolute() or path == Path("/"):
            raise SaoAcquisitionError(f"acquisition.{key} must be a scoped absolute path")
    if config["mini_smoke"] != {
        "decision_id": DECISION_ID,
        "exact_calls": 3,
        "max_clip_seconds": 30,
        "max_gpus": 1,
        "seed_ids": ["S-0011", "S-0011", "S-0012"],
        "state_capability": "NOT_ATTEMPTED",
    }:
        raise SaoAcquisitionError("SAO mini-smoke closure changed")
    if config["core"] != {
        "decision_id": DECISION_ID,
        "exact_rows": 1536,
        "max_clip_seconds": 30,
        "max_gpus_per_worker": 1,
        "state_capability": "NOT_ATTEMPTED",
        "eligibility_scope_expanded": False,
    }:
        raise SaoAcquisitionError("SAO core closure changed")
    config_sha = sha256_file(config_path)
    block = _decision_block(decisions_path.read_text(encoding="utf-8"), DECISION_ID)
    assignments = (*REQUIRED_DECISION_ASSIGNMENTS, f"SAO_LIVE_CONFIG_SHA256 = {config_sha}")
    for assignment in assignments:
        if assignment not in block:
            raise SaoAcquisitionError(f"D-0037 lacks required assignment: {assignment}")
    if re.search(r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE)\b", block, re.IGNORECASE):
        raise SaoAcquisitionError("D-0037 contains an unresolved marker")
    return config


def consume_read_token(environment: MutableMapping[str, str]) -> str:
    """Pop the only authorized token variable without exposing its value."""

    token = environment.pop(TOKEN_ENVIRONMENT_VARIABLE, None)
    if not isinstance(token, str) or not token:
        raise SaoAcquisitionError("HF_TOKEN is absent from the controlled environment")
    if "HUGGING_FACE_HUB_TOKEN" in environment:
        environment.pop("HUGGING_FACE_HUB_TOKEN", None)
        raise SaoAcquisitionError("ambiguous second Hugging Face token variable was removed")
    environment["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    return token


def _snapshot_files(snapshot: Path) -> list[dict[str, Any]]:
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise SaoAcquisitionError("SAO snapshot root must be a real directory")
    rows: list[dict[str, Any]] = []
    for path in sorted(snapshot.rglob("*")):
        if path.is_symlink():
            raise SaoAcquisitionError(
                f"provider snapshot contains a forbidden symlink: {path.relative_to(snapshot)}"
            )
        if path.is_dir():
            continue
        if path.is_file():
            rows.append(
                {
                    "path": path.relative_to(snapshot).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
            continue
        raise SaoAcquisitionError(
            f"provider snapshot contains a non-regular entry: {path.relative_to(snapshot)}"
        )
    if not rows:
        raise SaoAcquisitionError("downloaded SAO snapshot is empty")
    return rows


def _tree_sha256(files: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical({"files": files})).hexdigest()


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename one directory while refusing every existing target."""

    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:  # pragma: no cover - production platform contract
        raise SaoAcquisitionError("atomic no-replace rename is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(destination)
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        raise SaoAcquisitionError("filesystem lacks atomic no-replace rename support")
    raise OSError(error_number, os.strerror(error_number), str(destination))


def _reject_incomplete_entries(snapshot: Path) -> None:
    for path in snapshot.rglob("*"):
        relative = path.relative_to(snapshot)
        if any(".incomplete" in part for part in relative.parts):
            raise SaoAcquisitionError(
                f"provider snapshot contains an incomplete entry: {relative}"
            )


def _validate_snapshot_payload(snapshot: Path) -> tuple[list[dict[str, Any]], Path]:
    _reject_incomplete_entries(snapshot)
    if not (snapshot / "model_config.json").is_file():
        raise SaoAcquisitionError("downloaded snapshot lacks model_config.json")
    weights = [
        path
        for path in (snapshot / "model.safetensors", snapshot / "model.ckpt")
        if path.is_file()
    ]
    if not weights:
        raise SaoAcquisitionError(
            "downloaded snapshot lacks a supported root model weight file"
        )
    licenses = [snapshot / name for name in LICENSE_CANDIDATES if (snapshot / name).is_file()]
    if len(licenses) != 1:
        raise SaoAcquisitionError("downloaded snapshot lacks one unambiguous license text file")
    return _snapshot_files(snapshot), licenses[0]


def _validate_download(snapshot: Path) -> tuple[list[dict[str, Any]], Path]:
    control_cache = snapshot / ".cache" / "huggingface"
    if control_cache.exists():
        shutil.rmtree(control_cache)
        cache_parent = snapshot / ".cache"
        if cache_parent.exists() and not any(cache_parent.iterdir()):
            cache_parent.rmdir()
    return _validate_snapshot_payload(snapshot)


def _validate_retained_stage(snapshot: Path) -> tuple[list[dict[str, Any]], Path]:
    """Hash one untouched stage after rejecting all download-control residue."""

    if snapshot.is_symlink() or not snapshot.is_dir():
        raise SaoAcquisitionError("retained SAO stage is absent or not a real directory")
    for path in snapshot.rglob("*"):
        relative = path.relative_to(snapshot)
        if ".cache" in relative.parts:
            raise SaoAcquisitionError(
                f"retained SAO stage contains forbidden provider cache: {relative}"
            )
        if any(".incomplete" in part for part in relative.parts):
            raise SaoAcquisitionError(
                f"retained SAO stage contains an incomplete entry: {relative}"
            )
    return _validate_snapshot_payload(snapshot)


def _validate_utc_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SaoAcquisitionError(f"{field} must be a non-empty UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SaoAcquisitionError(f"{field} is not ISO-8601") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise SaoAcquisitionError(f"{field} must be UTC")
    return value


def _require_exact_keys(record: dict[str, Any], expected: set[str], label: str) -> None:
    if set(record) != expected:
        missing = sorted(expected.difference(record))
        unexpected = sorted(set(record).difference(expected))
        raise SaoAcquisitionError(
            f"{label} keys are invalid: missing={missing}, unexpected={unexpected}"
        )


def _source_command_value(command: Any, flag: str) -> str:
    if not isinstance(command, str) or not command.strip():
        raise SaoAcquisitionError("original acquisition command is invalid")
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        raise SaoAcquisitionError("original acquisition command cannot be parsed") from exc
    values: list[str] = []
    for index, argument in enumerate(arguments):
        if argument == flag:
            if index + 1 >= len(arguments):
                raise SaoAcquisitionError(f"original acquisition command lacks {flag} value")
            values.append(arguments[index + 1])
        elif argument.startswith(f"{flag}="):
            values.append(argument.split("=", 1)[1])
    if len(values) != 1 or not values[0].strip():
        raise SaoAcquisitionError(
            f"original acquisition command must contain exactly one {flag} value"
        )
    return values[0]


def _strict_acquisition_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return strict_json_object(path)
    except Exception as exc:
        if isinstance(exc, SaoAcquisitionError):
            raise
        raise SaoAcquisitionError(f"cannot validate {label}") from exc


def _validate_source_failure(
    *,
    source_run_dir: Path,
    config_path: Path,
    config_sha256: str,
) -> dict[str, Any]:
    """Verify the immutable zero-call failure that retained the official stage."""

    if source_run_dir.is_symlink() or not source_run_dir.is_dir():
        raise SaoAcquisitionError("original failed SAO acquisition run is absent")
    source_entries = list(source_run_dir.iterdir())
    if any(path.is_symlink() for path in source_entries):
        raise SaoAcquisitionError("original failed SAO acquisition run contains a symlink")
    if {path.name for path in source_entries} != RECOVERY_SOURCE_RUN_FILES or any(
        not path.is_file() for path in source_entries
    ):
        raise SaoAcquisitionError("original failed SAO acquisition run closure changed")

    failure_path = source_run_dir / "terminal-failure.json"
    if sha256_file(failure_path) != RECOVERY_FAILURE_TERMINAL_SHA256:
        raise SaoAcquisitionError("original SAO failure terminal SHA-256 mismatch")
    failure = _strict_acquisition_json(failure_path, "original SAO failure terminal")
    _require_exact_keys(
        failure,
        {
            "schema_version",
            "status",
            "run_id",
            "started_at_utc",
            "finished_at_utc",
            "error_type",
            "acquisition_manifest_path",
            "acquisition_manifest_sha256",
            "credential_mechanism",
            "partial_snapshot_retained",
            "model_calls",
            "generated_audio",
        },
        "original SAO failure terminal",
    )
    expected_failure = {
        "schema_version": 1,
        "status": "ACQUISITION_FAILED_STOPPED",
        "run_id": RECOVERY_SOURCE_RUN_ID,
        "error_type": "SaoAcquisitionError",
        "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
        "partial_snapshot_retained": True,
        "model_calls": 0,
        "generated_audio": 0,
    }
    for field, expected in expected_failure.items():
        if failure.get(field) != expected:
            raise SaoAcquisitionError(f"original SAO failure terminal mismatch: {field}")
    _validate_utc_timestamp(failure["started_at_utc"], "failure started_at_utc")
    _validate_utc_timestamp(failure["finished_at_utc"], "failure finished_at_utc")

    manifest_path = source_run_dir / "acquisition-manifest.json"
    try:
        recorded_manifest_path = Path(str(failure["acquisition_manifest_path"])).resolve(
            strict=True
        )
    except OSError as exc:
        raise SaoAcquisitionError("original acquisition manifest path is unavailable") from exc
    if recorded_manifest_path != manifest_path.resolve(strict=True):
        raise SaoAcquisitionError("original failure terminal points to the wrong manifest")
    manifest_sha256 = sha256_file(manifest_path)
    if manifest_sha256 != RECOVERY_ACQUISITION_MANIFEST_SHA256:
        raise SaoAcquisitionError("original acquisition manifest fixed SHA-256 mismatch")
    if failure["acquisition_manifest_sha256"] != manifest_sha256:
        raise SaoAcquisitionError("original acquisition manifest SHA-256 mismatch")
    manifest = _strict_acquisition_json(manifest_path, "original acquisition manifest")
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "status",
            "run_id",
            "started_at_utc",
            "node",
            "command",
            "git_commit",
            "live_config_path",
            "live_config_sha256",
            "model_id",
            "provider",
            "credential_mechanism",
            "gpu_count",
            "model_calls",
            "generated_audio",
        },
        "original acquisition manifest",
    )
    expected_manifest = {
        "schema_version": 1,
        "status": "STARTED_NO_MODEL_CALLS",
        "run_id": RECOVERY_SOURCE_RUN_ID,
        "model_id": MODEL_ID,
        "provider": "huggingface_hub",
        "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
        "gpu_count": 0,
        "model_calls": 0,
        "generated_audio": 0,
        "live_config_sha256": config_sha256,
        "started_at_utc": failure["started_at_utc"],
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise SaoAcquisitionError(f"original acquisition manifest mismatch: {field}")
    if not isinstance(manifest.get("node"), str) or not manifest["node"].strip():
        raise SaoAcquisitionError("original acquisition node is invalid")
    if not isinstance(manifest.get("git_commit"), str) or REVISION_RE.fullmatch(
        manifest["git_commit"]
    ) is None:
        raise SaoAcquisitionError("original acquisition Git revision is invalid")
    try:
        recorded_config_path = Path(str(manifest["live_config_path"])).resolve(strict=True)
    except OSError as exc:
        raise SaoAcquisitionError("original acquisition live config is unavailable") from exc
    if recorded_config_path != config_path.resolve(strict=True):
        raise SaoAcquisitionError("original acquisition live config path mismatch")
    accepted_by = _source_command_value(manifest["command"], "--accepted-by")
    accepted_at_utc = _source_command_value(manifest["command"], "--accepted-at-utc")
    _validate_utc_timestamp(accepted_at_utc, "original accepted_at_utc")
    return {
        "failure_terminal_path": str(failure_path.resolve(strict=True)),
        "failure_terminal_sha256": RECOVERY_FAILURE_TERMINAL_SHA256,
        "acquisition_manifest_path": str(manifest_path.resolve(strict=True)),
        "acquisition_manifest_sha256": manifest_sha256,
        "accepted_by": accepted_by,
        "accepted_at_utc": accepted_at_utc,
        "source_run_files": _snapshot_files(source_run_dir),
    }


def _attempt1_failure_log_path(run_root: Path) -> Path:
    """Derive the fixed failed-recovery log from the frozen runtime layout."""

    if (
        run_root.name != "acquisition"
        or run_root.parent.name != "sao-live-v2"
        or run_root.parent.parent.name != "runs"
    ):
        raise SaoAcquisitionError("SAO recovery run root lacks the frozen runtime layout")
    return (
        run_root.parent.parent.parent
        / "logs"
        / "sao-live-v2"
        / f"{RECOVERY_RUN_ID}.log"
    )


def _validate_failed_recovery_attempt(
    *,
    failed_run_dir: Path,
    failure_log_path: Path,
    final_snapshot: Path,
    retained_files: list[dict[str, Any]],
    retained_license_path: Path,
    source: dict[str, Any],
    failed_decision: dict[str, str],
) -> dict[str, Any]:
    """Verify the exact two-file D-0039 failure and its immutable log."""

    if failed_run_dir.is_symlink() or not failed_run_dir.is_dir():
        raise SaoAcquisitionError("failed SAO recovery-attempt-1 run is absent")
    failed_entries = list(failed_run_dir.iterdir())
    if any(path.is_symlink() for path in failed_entries):
        raise SaoAcquisitionError("failed SAO recovery-attempt-1 contains a symlink")
    if {path.name for path in failed_entries} != RECOVERY_ATTEMPT1_RUN_FILES or any(
        not path.is_file() for path in failed_entries
    ):
        raise SaoAcquisitionError("failed SAO recovery-attempt-1 closure changed")

    receipt_path = failed_run_dir / "access-receipt.json"
    manifest_path = failed_run_dir / "snapshot-manifest.json"
    if sha256_file(receipt_path) != RECOVERY_ATTEMPT1_ACCESS_RECEIPT_SHA256:
        raise SaoAcquisitionError("failed recovery access receipt SHA-256 mismatch")
    if sha256_file(manifest_path) != RECOVERY_ATTEMPT1_SNAPSHOT_MANIFEST_SHA256:
        raise SaoAcquisitionError("failed recovery snapshot manifest SHA-256 mismatch")
    failed_files = _snapshot_files(failed_run_dir)
    if _tree_sha256(failed_files) != RECOVERY_ATTEMPT1_TREE_SHA256:
        raise SaoAcquisitionError("failed recovery two-file tree SHA-256 mismatch")

    if (
        failure_log_path.is_symlink()
        or not failure_log_path.is_file()
        or sha256_file(failure_log_path) != RECOVERY_ATTEMPT1_FAILURE_LOG_SHA256
    ):
        raise SaoAcquisitionError("failed recovery log path or SHA-256 mismatch")

    manifest = _strict_acquisition_json(
        manifest_path, "failed recovery snapshot manifest"
    )
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "provider",
            "acquisition_mode",
            "model_id",
            "revision",
            "snapshot_dir",
            "snapshot_tree_sha256",
            "files",
            "source_run_id",
            "source_failure_terminal_path",
            "source_failure_terminal_sha256",
            "recovery_decision_id",
            "recovery_decision_block_sha256",
        },
        "failed recovery snapshot manifest",
    )
    expected_manifest = {
        "schema_version": 1,
        "provider": "huggingface_hub",
        "acquisition_mode": "OFFLINE_RETAINED_STAGE_RECOVERY",
        "model_id": MODEL_ID,
        "revision": RECOVERY_REVISION,
        "snapshot_dir": str(final_snapshot),
        "source_run_id": RECOVERY_SOURCE_RUN_ID,
        "source_failure_terminal_path": source["failure_terminal_path"],
        "source_failure_terminal_sha256": source["failure_terminal_sha256"],
        "recovery_decision_id": RECOVERY_DECISION_ID,
        "recovery_decision_block_sha256": failed_decision[
            "decision_block_sha256"
        ],
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise SaoAcquisitionError(
                f"failed recovery snapshot manifest mismatch: {field}"
            )
    if manifest.get("files") != retained_files:
        raise SaoAcquisitionError("failed recovery manifest no longer binds retained stage")
    if manifest.get("snapshot_tree_sha256") != _tree_sha256(retained_files):
        raise SaoAcquisitionError("failed recovery snapshot tree SHA-256 mismatch")

    receipt = _strict_acquisition_json(receipt_path, "failed recovery access receipt")
    _require_exact_keys(
        receipt,
        {
            "schema_version",
            "model_id",
            "resolved_provider_revision",
            "accepted_by",
            "accepted_at_utc",
            "user_confirmed_acceptance",
            "license_identifier",
            "license_text_sha256",
            "snapshot_manifest_path",
            "snapshot_manifest_sha256",
        },
        "failed recovery access receipt",
    )
    expected_receipt = {
        "schema_version": 1,
        "model_id": MODEL_ID,
        "resolved_provider_revision": RECOVERY_REVISION,
        "user_confirmed_acceptance": True,
        "license_text_sha256": sha256_file(retained_license_path),
        "snapshot_manifest_path": str(manifest_path.resolve(strict=True)),
        "snapshot_manifest_sha256": RECOVERY_ATTEMPT1_SNAPSHOT_MANIFEST_SHA256,
    }
    for field, expected in expected_receipt.items():
        if receipt.get(field) != expected:
            raise SaoAcquisitionError(f"failed recovery access receipt mismatch: {field}")
    for field in ("accepted_by", "license_identifier"):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            raise SaoAcquisitionError(f"failed recovery access receipt invalid: {field}")
    _validate_utc_timestamp(receipt.get("accepted_at_utc"), "accepted_at_utc")
    return {
        "access_receipt_path": str(receipt_path.resolve(strict=True)),
        "access_receipt_sha256": RECOVERY_ATTEMPT1_ACCESS_RECEIPT_SHA256,
        "snapshot_manifest_path": str(manifest_path.resolve(strict=True)),
        "snapshot_manifest_sha256": RECOVERY_ATTEMPT1_SNAPSHOT_MANIFEST_SHA256,
        "failed_run_files": failed_files,
        "failed_run_tree_sha256": RECOVERY_ATTEMPT1_TREE_SHA256,
        "failure_log_path": str(failure_log_path.resolve(strict=True)),
        "failure_log_sha256": RECOVERY_ATTEMPT1_FAILURE_LOG_SHA256,
        "accepted_by": receipt["accepted_by"],
        "accepted_at_utc": receipt["accepted_at_utc"],
        "license_identifier": receipt["license_identifier"],
    }


def _prevalidate_hardlink_support(snapshot_root: Path) -> None:
    """Exercise one scoped hard link before any recovery artifact is created."""

    probe_root = snapshot_root / ".sao-hardlink-probe-recovery-v2-002"
    source = probe_root / "source"
    linked = probe_root / "linked"
    if os.path.lexists(probe_root):
        raise SaoAcquisitionError("scoped SAO hard-link probe path already exists")
    try:
        probe_root.mkdir(mode=0o700, exist_ok=False)
        with source.open("xb") as handle:
            handle.write(b"SAO hard-link recovery probe\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(source, linked, follow_symlinks=False)
        source_stat = source.stat(follow_symlinks=False)
        linked_stat = linked.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(source_stat.st_mode)
            or not stat.S_ISREG(linked_stat.st_mode)
            or source_stat.st_dev != linked_stat.st_dev
            or source_stat.st_ino != linked_stat.st_ino
            or source.read_bytes() != linked.read_bytes()
        ):
            raise SaoAcquisitionError("scoped SAO hard-link probe identity failed")
    except BaseException as exc:
        if isinstance(exc, (SaoAcquisitionError, KeyboardInterrupt, SystemExit)):
            raise
        raise SaoAcquisitionError("scoped SAO hard-link support probe failed") from exc
    finally:
        for path in (linked, source):
            if os.path.lexists(path):
                path.unlink()
        if os.path.lexists(probe_root):
            probe_root.rmdir()


def _hardlink_clone_snapshot(
    source_root: Path,
    destination_root: Path,
    files: list[dict[str, Any]],
) -> None:
    """Create a no-overwrite hierarchy of hard links from a sealed file list."""

    relative_paths: list[Path] = []
    for row in files:
        relative = Path(str(row.get("path", "")))
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.as_posix() in {"", "."}
            or ".." in relative.parts
        ):
            raise SaoAcquisitionError("retained snapshot contains an unsafe path")
        relative_paths.append(relative)
    directories = {
        parent
        for relative in relative_paths
        for parent in relative.parents
        if parent != Path(".")
    }
    for relative in sorted(directories, key=lambda value: (len(value.parts), value.as_posix())):
        destination = destination_root / relative
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        destination.mkdir(mode=0o755, exist_ok=False)

    for row, relative in zip(files, relative_paths, strict=True):
        source = source_root / relative
        destination = destination_root / relative
        source_stat = source.stat(follow_symlinks=False)
        if source.is_symlink() or not stat.S_ISREG(source_stat.st_mode):
            raise SaoAcquisitionError("retained snapshot entry changed before hard-linking")
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        os.link(source, destination, follow_symlinks=False)
        destination_stat = destination.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(destination_stat.st_mode)
            or source_stat.st_dev != destination_stat.st_dev
            or source_stat.st_ino != destination_stat.st_ino
            or destination_stat.st_size != row["size_bytes"]
        ):
            raise SaoAcquisitionError("hard-linked snapshot file identity mismatch")


def _write_attempt2_failure_terminal(
    *,
    recovery_run_dir: Path,
    final_snapshot: Path,
    retained_stage: Path,
    started_at_utc: str,
    command: str,
    git_commit: str,
    error: BaseException,
) -> Path:
    """Seal a sanitized terminal while retaining every partial artifact."""

    return _write_json_exclusive(
        recovery_run_dir / "terminal-failure.json",
        {
            "schema_version": 1,
            "status": "RECOVERY_FAILED_STOPPED_ARTIFACTS_RETAINED",
            "run_id": RECOVERY_ATTEMPT2_RUN_ID,
            "source_run_id": RECOVERY_SOURCE_RUN_ID,
            "failed_recovery_run_id": RECOVERY_RUN_ID,
            "started_at_utc": started_at_utc,
            "finished_at_utc": _utc_now(),
            "node": socket.gethostname().split(".", 1)[0],
            "command": command,
            "git_commit": git_commit,
            "error_type": type(error).__name__,
            "recovery_decision_id": RECOVERY_ATTEMPT2_DECISION_ID,
            "materialization": RECOVERY_ATTEMPT2_MATERIALIZATION,
            "snapshot_dir": str(final_snapshot),
            "partial_snapshot_retained": final_snapshot.is_dir(),
            "source_stage_retained": retained_stage.is_dir(),
            "original_failed_run_preserved": True,
            "failed_recovery_run_preserved": True,
            "network_access": False,
            "token_access": False,
            "gpu_count": 0,
            "model_calls": 0,
            "generated_audio": 0,
        },
    )


def finalize_retained_acquisition_recovery(
    config_path: Path,
    decisions_path: Path,
    *,
    command: str,
    git_commit: str,
) -> dict[str, Any]:
    """Finalize the one authorized retained snapshot without external access.

    This path imports no provider, model, GPU, or token surface. It verifies the
    original immutable zero-call failure and the complete retained stage before
    performing one same-root rename and sealing a new receipt run.
    """

    if not command.strip() or REVISION_RE.fullmatch(git_commit) is None:
        raise SaoAcquisitionError("recovery command/git identity is invalid")
    config = validate_live_config(config_path, decisions_path)
    acquisition = config["acquisition"]
    if acquisition.get("run_id") != RECOVERY_SOURCE_RUN_ID:
        raise SaoAcquisitionError("SAO recovery source run ID changed")
    decision = validate_recovery_decision(decisions_path)

    run_root = Path(str(acquisition["run_root"]))
    snapshot_root = Path(str(acquisition["snapshot_root"]))
    source_run_dir = run_root / RECOVERY_SOURCE_RUN_ID
    recovery_run_dir = run_root / RECOVERY_RUN_ID
    retained_stage = snapshot_root / f".{RECOVERY_SOURCE_RUN_ID}.partial"
    final_snapshot = snapshot_root / RECOVERY_REVISION
    if not run_root.is_dir() or run_root.is_symlink():
        raise SaoAcquisitionError("SAO acquisition run root is unavailable")
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        raise SaoAcquisitionError("SAO snapshot root is unavailable")
    if os.path.lexists(recovery_run_dir):
        raise FileExistsError(recovery_run_dir)
    if os.path.lexists(final_snapshot):
        raise FileExistsError(final_snapshot)

    lock_path = snapshot_root / ".sao-acquisition.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise SaoAcquisitionError("scoped SAO acquisition lock is unavailable")
    lock_handle = lock_path.open("r+b")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise SaoAcquisitionError("another SAO acquisition holds the scoped lock") from exc

    started = _utc_now()
    try:
        # Repeat no-clobber checks while holding the same lock used by ordinary
        # acquisition; the final move also uses kernel-enforced RENAME_NOREPLACE.
        if os.path.lexists(recovery_run_dir):
            raise FileExistsError(recovery_run_dir)
        if os.path.lexists(final_snapshot):
            raise FileExistsError(final_snapshot)
        source = _validate_source_failure(
            source_run_dir=source_run_dir,
            config_path=config_path,
            config_sha256=sha256_file(config_path),
        )
        files, license_path = _validate_retained_stage(retained_stage)
        source_run_tree_sha256 = _tree_sha256(source["source_run_files"])
        snapshot_tree_sha256 = _tree_sha256(files)

        recovery_run_dir.mkdir(mode=0o755, exist_ok=False)
        manifest = {
            "schema_version": 1,
            "provider": "huggingface_hub",
            "acquisition_mode": "OFFLINE_RETAINED_STAGE_RECOVERY",
            "model_id": MODEL_ID,
            "revision": RECOVERY_REVISION,
            "snapshot_dir": str(final_snapshot),
            "snapshot_tree_sha256": snapshot_tree_sha256,
            "files": files,
            "source_run_id": RECOVERY_SOURCE_RUN_ID,
            "source_failure_terminal_path": source["failure_terminal_path"],
            "source_failure_terminal_sha256": source["failure_terminal_sha256"],
            "recovery_decision_id": decision["decision_id"],
            "recovery_decision_block_sha256": decision["decision_block_sha256"],
        }
        manifest_path = _write_json_exclusive(
            recovery_run_dir / "snapshot-manifest.json", manifest
        )
        receipt = {
            "schema_version": 1,
            "model_id": MODEL_ID,
            "resolved_provider_revision": RECOVERY_REVISION,
            "accepted_by": source["accepted_by"],
            "accepted_at_utc": source["accepted_at_utc"],
            "user_confirmed_acceptance": True,
            "license_identifier": acquisition["license_identifier"],
            "license_text_sha256": sha256_file(license_path),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": sha256_file(manifest_path),
        }
        receipt_path = _write_json_exclusive(
            recovery_run_dir / "access-receipt.json", receipt
        )

        # The stage and destination share snapshot_root. The scoped acquisition
        # lock plus the no-clobber destination check makes this the sole mutation
        # of retained model bytes; no file is deleted, copied, or redownloaded.
        _rename_no_replace(retained_stage, final_snapshot)
        if os.path.lexists(retained_stage) or not final_snapshot.is_dir():
            raise SaoAcquisitionError("retained SAO stage rename did not complete")
        if _snapshot_files(source_run_dir) != source["source_run_files"]:
            raise SaoAcquisitionError("original failed SAO acquisition run changed")
        from backbones.license_gate import validate_access_receipt

        verified_receipt = validate_access_receipt(
            receipt_path,
            expected_model_id=MODEL_ID,
            expected_snapshot_dir=final_snapshot,
        )
        if verified_receipt["resolved_provider_revision"] != RECOVERY_REVISION:
            raise SaoAcquisitionError("recovered access receipt revision mismatch")

        terminal = {
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_RECOVERED_OFFLINE_NO_GENERATION",
            "run_id": RECOVERY_RUN_ID,
            "source_run_id": RECOVERY_SOURCE_RUN_ID,
            "started_at_utc": started,
            "finished_at_utc": _utc_now(),
            "node": socket.gethostname().split(".", 1)[0],
            "command": command,
            "git_commit": git_commit,
            "model_id": MODEL_ID,
            "resolved_provider_revision": RECOVERY_REVISION,
            "snapshot_dir": str(final_snapshot),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": sha256_file(manifest_path),
            "snapshot_tree_sha256": snapshot_tree_sha256,
            "access_receipt_path": str(receipt_path),
            "access_receipt_sha256": sha256_file(receipt_path),
            "source_failure_terminal_path": source["failure_terminal_path"],
            "source_failure_terminal_sha256": source["failure_terminal_sha256"],
            "source_acquisition_manifest_path": source["acquisition_manifest_path"],
            "source_acquisition_manifest_sha256": source[
                "acquisition_manifest_sha256"
            ],
            "source_run_tree_sha256": source_run_tree_sha256,
            "recovery_decision_id": decision["decision_id"],
            "recovery_decision_path": decision["decision_path"],
            "recovery_decision_file_sha256": decision["decision_file_sha256"],
            "recovery_decision_block_sha256": decision["decision_block_sha256"],
            "recovery_mode": "RETAINED_STAGE_RENAME_ONLY",
            "network_access": False,
            "token_access": False,
            "gpu_count": 0,
            "model_calls": 0,
            "generated_audio": 0,
            "original_failed_run_preserved": True,
        }
        terminal_path = _write_json_exclusive(recovery_run_dir / "terminal.json", terminal)
        return {**terminal, "terminal_path": str(terminal_path)}
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def finalize_retained_acquisition_recovery_attempt2(
    config_path: Path,
    decisions_path: Path,
    *,
    command: str,
    git_commit: str,
) -> dict[str, Any]:
    """Hard-link the retained stage under the one fixed D-0041 authority.

    The source stage, original acquisition failure, and failed D-0039 recovery
    remain in place. This function imports no provider, model, GPU, or token
    surface and performs no deletion or overwrite of acquisition artifacts.
    """

    if not command.strip() or REVISION_RE.fullmatch(git_commit) is None:
        raise SaoAcquisitionError("recovery-attempt-2 command/git identity is invalid")
    config = validate_live_config(config_path, decisions_path)
    acquisition = config["acquisition"]
    if acquisition.get("run_id") != RECOVERY_SOURCE_RUN_ID:
        raise SaoAcquisitionError("SAO recovery-attempt-2 source run ID changed")
    failed_decision = validate_recovery_decision(decisions_path)
    decision = validate_recovery_attempt2_decision(decisions_path)

    run_root = Path(str(acquisition["run_root"]))
    snapshot_root = Path(str(acquisition["snapshot_root"]))
    source_run_dir = run_root / RECOVERY_SOURCE_RUN_ID
    failed_run_dir = run_root / RECOVERY_RUN_ID
    recovery_run_dir = run_root / RECOVERY_ATTEMPT2_RUN_ID
    retained_stage = snapshot_root / f".{RECOVERY_SOURCE_RUN_ID}.partial"
    final_snapshot = snapshot_root / RECOVERY_REVISION
    failure_log_path = _attempt1_failure_log_path(run_root)
    if not run_root.is_dir() or run_root.is_symlink():
        raise SaoAcquisitionError("SAO acquisition run root is unavailable")
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        raise SaoAcquisitionError("SAO snapshot root is unavailable")
    if os.path.lexists(recovery_run_dir):
        raise FileExistsError(recovery_run_dir)
    if os.path.lexists(final_snapshot):
        raise FileExistsError(final_snapshot)

    lock_path = snapshot_root / ".sao-acquisition.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise SaoAcquisitionError("scoped SAO acquisition lock is unavailable")
    lock_handle = lock_path.open("r+b")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise SaoAcquisitionError("another SAO acquisition holds the scoped lock") from exc

    started = _utc_now()
    artifacts_started = False
    try:
        if os.path.lexists(recovery_run_dir):
            raise FileExistsError(recovery_run_dir)
        if os.path.lexists(final_snapshot):
            raise FileExistsError(final_snapshot)
        source = _validate_source_failure(
            source_run_dir=source_run_dir,
            config_path=config_path,
            config_sha256=sha256_file(config_path),
        )
        retained_files, retained_license_path = _validate_retained_stage(retained_stage)
        failed = _validate_failed_recovery_attempt(
            failed_run_dir=failed_run_dir,
            failure_log_path=failure_log_path,
            final_snapshot=final_snapshot,
            retained_files=retained_files,
            retained_license_path=retained_license_path,
            source=source,
            failed_decision=failed_decision,
        )

        # This probe is cleaned before either durable attempt-2 directory is
        # created. Thus unsupported hard links cannot leave a second partial run.
        _prevalidate_hardlink_support(snapshot_root)
        if os.path.lexists(recovery_run_dir) or os.path.lexists(final_snapshot):
            raise SaoAcquisitionError("SAO recovery target appeared during prevalidation")

        recovery_run_dir.mkdir(mode=0o755, exist_ok=False)
        artifacts_started = True
        final_snapshot.mkdir(mode=0o755, exist_ok=False)
        _hardlink_clone_snapshot(retained_stage, final_snapshot, retained_files)

        manifest = {
            "schema_version": 1,
            "provider": "huggingface_hub",
            "acquisition_mode": "OFFLINE_RETAINED_STAGE_RECOVERY_ATTEMPT2",
            "materialization": RECOVERY_ATTEMPT2_MATERIALIZATION,
            "model_id": MODEL_ID,
            "revision": RECOVERY_REVISION,
            "snapshot_dir": str(final_snapshot),
            "snapshot_tree_sha256": _tree_sha256(retained_files),
            "files": retained_files,
            "source_run_id": RECOVERY_SOURCE_RUN_ID,
            "failed_recovery_run_id": RECOVERY_RUN_ID,
            "failed_recovery_access_receipt_sha256": failed[
                "access_receipt_sha256"
            ],
            "failed_recovery_snapshot_manifest_sha256": failed[
                "snapshot_manifest_sha256"
            ],
            "failed_recovery_tree_sha256": failed["failed_run_tree_sha256"],
            "failed_recovery_log_path": failed["failure_log_path"],
            "failed_recovery_log_sha256": failed["failure_log_sha256"],
            "source_failure_terminal_path": source["failure_terminal_path"],
            "source_failure_terminal_sha256": source["failure_terminal_sha256"],
            "recovery_decision_id": decision["decision_id"],
            "recovery_decision_block_sha256": decision["decision_block_sha256"],
        }
        manifest_path = _write_json_exclusive(
            recovery_run_dir / "snapshot-manifest.json", manifest
        )
        if _strict_acquisition_json(manifest_path, "recovery-attempt-2 manifest") != manifest:
            raise SaoAcquisitionError("recovery-attempt-2 manifest write verification failed")
        receipt = {
            "schema_version": 1,
            "model_id": MODEL_ID,
            "resolved_provider_revision": RECOVERY_REVISION,
            "accepted_by": failed["accepted_by"],
            "accepted_at_utc": failed["accepted_at_utc"],
            "user_confirmed_acceptance": True,
            "license_identifier": failed["license_identifier"],
            "license_text_sha256": sha256_file(retained_license_path),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": sha256_file(manifest_path),
        }
        receipt_path = _write_json_exclusive(
            recovery_run_dir / "access-receipt.json", receipt
        )
        if _strict_acquisition_json(receipt_path, "recovery-attempt-2 receipt") != receipt:
            raise SaoAcquisitionError("recovery-attempt-2 receipt write verification failed")

        from backbones.license_gate import validate_access_receipt

        verified_receipt = validate_access_receipt(
            receipt_path,
            expected_model_id=MODEL_ID,
            expected_snapshot_dir=final_snapshot,
        )
        if (
            verified_receipt["resolved_provider_revision"] != RECOVERY_REVISION
            or verified_receipt["receipt_sha256"] != sha256_file(receipt_path)
            or [
                {
                    "path": row["path"],
                    "size_bytes": row["size_bytes"],
                    "sha256": row["sha256"],
                }
                for row in verified_receipt["verified_files"]
            ]
            != retained_files
        ):
            raise SaoAcquisitionError("recovery-attempt-2 exact receipt verification failed")

        # Recheck identity and every small immutable evidence closure after the
        # final receipt hashes the materialized files. The source stage remains.
        for row in retained_files:
            relative = Path(row["path"])
            source_stat = (retained_stage / relative).stat(follow_symlinks=False)
            final_stat = (final_snapshot / relative).stat(follow_symlinks=False)
            if (
                source_stat.st_dev != final_stat.st_dev
                or source_stat.st_ino != final_stat.st_ino
            ):
                raise SaoAcquisitionError("final snapshot is not a hard-link clone")
        if _snapshot_files(source_run_dir) != source["source_run_files"]:
            raise SaoAcquisitionError("original failed SAO acquisition run changed")
        if _snapshot_files(failed_run_dir) != failed["failed_run_files"]:
            raise SaoAcquisitionError("failed SAO recovery-attempt-1 run changed")
        if sha256_file(failure_log_path) != failed["failure_log_sha256"]:
            raise SaoAcquisitionError("failed SAO recovery-attempt-1 log changed")

        terminal = {
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_RECOVERED_OFFLINE_HARDLINK_NO_GENERATION",
            "run_id": RECOVERY_ATTEMPT2_RUN_ID,
            "source_run_id": RECOVERY_SOURCE_RUN_ID,
            "failed_recovery_run_id": RECOVERY_RUN_ID,
            "started_at_utc": started,
            "finished_at_utc": _utc_now(),
            "node": socket.gethostname().split(".", 1)[0],
            "command": command,
            "git_commit": git_commit,
            "model_id": MODEL_ID,
            "resolved_provider_revision": RECOVERY_REVISION,
            "snapshot_dir": str(final_snapshot),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": sha256_file(manifest_path),
            "snapshot_tree_sha256": manifest["snapshot_tree_sha256"],
            "access_receipt_path": str(receipt_path),
            "access_receipt_sha256": sha256_file(receipt_path),
            "source_failure_terminal_path": source["failure_terminal_path"],
            "source_failure_terminal_sha256": source["failure_terminal_sha256"],
            "source_acquisition_manifest_path": source["acquisition_manifest_path"],
            "source_acquisition_manifest_sha256": source[
                "acquisition_manifest_sha256"
            ],
            "failed_recovery_access_receipt_path": failed["access_receipt_path"],
            "failed_recovery_access_receipt_sha256": failed[
                "access_receipt_sha256"
            ],
            "failed_recovery_snapshot_manifest_path": failed[
                "snapshot_manifest_path"
            ],
            "failed_recovery_snapshot_manifest_sha256": failed[
                "snapshot_manifest_sha256"
            ],
            "failed_recovery_tree_sha256": failed["failed_run_tree_sha256"],
            "failed_recovery_log_path": failed["failure_log_path"],
            "failed_recovery_log_sha256": failed["failure_log_sha256"],
            "recovery_decision_id": decision["decision_id"],
            "recovery_decision_path": decision["decision_path"],
            "recovery_decision_file_sha256": decision["decision_file_sha256"],
            "recovery_decision_block_sha256": decision["decision_block_sha256"],
            "materialization": RECOVERY_ATTEMPT2_MATERIALIZATION,
            "source_stage_retained": True,
            "original_failed_run_preserved": True,
            "failed_recovery_run_preserved": True,
            "network_access": False,
            "token_access": False,
            "gpu_count": 0,
            "model_calls": 0,
            "generated_audio": 0,
        }
        terminal_path = _write_json_exclusive(
            recovery_run_dir / "terminal.json", terminal
        )
        return {**terminal, "terminal_path": str(terminal_path)}
    except BaseException as exc:
        if artifacts_started and recovery_run_dir.is_dir():
            try:
                _write_attempt2_failure_terminal(
                    recovery_run_dir=recovery_run_dir,
                    final_snapshot=final_snapshot,
                    retained_stage=retained_stage,
                    started_at_utc=started,
                    command=command,
                    git_commit=git_commit,
                    error=exc,
                )
            except BaseException as terminal_exc:
                raise SaoAcquisitionError(
                    "SAO recovery-attempt-2 failed and its terminal could not be sealed"
                ) from terminal_exc
        raise
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def acquire_snapshot(
    config_path: Path,
    decisions_path: Path,
    *,
    execute_ack: str,
    accepted_by: str,
    accepted_at_utc: str,
    command: str = "test-injected SAO acquisition",
    git_commit: str = "0" * 40,
    environment: MutableMapping[str, str] | None = None,
    api_factory: Callable[[], Any] | None = None,
    snapshot_download_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Resolve, download, hash, and receipt one new exact HF snapshot.

    Test callers inject provider doubles. Production imports Hugging Face only
    after every local gate and the token-pop boundary passes.
    """

    if execute_ack != EXECUTE_ACK:
        raise SaoAcquisitionError("exact SAO acquisition acknowledgement is absent")
    if not accepted_by.strip():
        raise SaoAcquisitionError("accepted_by must be non-empty")
    if not command.strip() or re.fullmatch(r"[0-9a-f]{40}", git_commit) is None:
        raise SaoAcquisitionError("acquisition command/git identity is invalid")
    try:
        accepted = datetime.fromisoformat(accepted_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SaoAcquisitionError("accepted_at_utc is not ISO-8601") from exc
    if accepted.utcoffset() is None or accepted.utcoffset().total_seconds() != 0:
        raise SaoAcquisitionError("accepted_at_utc must be UTC")
    config = validate_live_config(config_path, decisions_path)
    env = environment if environment is not None else os.environ
    if not env.get("HTTPS_PROXY") and not env.get("https_proxy"):
        raise SaoAcquisitionError("project proxy wrapper is not active")
    token = consume_read_token(env)
    acquisition = config["acquisition"]
    run_id = str(acquisition["run_id"])
    run_dir = Path(acquisition["run_root"]) / run_id
    snapshot_root = Path(acquisition["snapshot_root"])
    if run_dir.exists():
        token = ""
        raise FileExistsError(run_dir)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    stage = snapshot_root / f".{run_id}.partial"
    if stage.exists():
        token = ""
        raise FileExistsError(stage)
    lock_path = snapshot_root / ".sao-acquisition.lock"
    lock_handle = lock_path.open("a+b")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        token = ""
        lock_handle.close()
        raise SaoAcquisitionError("another SAO acquisition holds the scoped lock") from exc
    run_dir.mkdir(parents=True, exist_ok=False)
    started = _utc_now()
    acquisition_manifest_path: Path | None = None
    try:
        acquisition_manifest_path = _write_json_exclusive(
            run_dir / "acquisition-manifest.json",
            {
                "schema_version": 1,
                "status": "STARTED_NO_MODEL_CALLS",
                "run_id": run_id,
                "started_at_utc": started,
                "node": socket.gethostname().split(".", 1)[0],
                "command": command,
                "git_commit": git_commit,
                "live_config_path": str(config_path.resolve()),
                "live_config_sha256": sha256_file(config_path),
                "model_id": MODEL_ID,
                "provider": "huggingface_hub",
                "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
                "gpu_count": 0,
                "model_calls": 0,
                "generated_audio": 0,
            },
        )
        if api_factory is None or snapshot_download_fn is None:
            from huggingface_hub import HfApi, snapshot_download

            api_factory = HfApi
            snapshot_download_fn = snapshot_download
        api = api_factory()
        info = api.model_info(
            MODEL_ID,
            revision=acquisition["requested_revision"],
            token=token,
        )
        revision = str(getattr(info, "sha", ""))
        if REVISION_RE.fullmatch(revision) is None:
            raise SaoAcquisitionError("provider did not resolve a 40-hex revision")
        final_snapshot = snapshot_root / revision
        if final_snapshot.exists():
            raise FileExistsError(final_snapshot)
        snapshot_download_fn(
            repo_id=MODEL_ID,
            repo_type="model",
            revision=revision,
            local_dir=stage,
            token=token,
            force_download=False,
            max_workers=int(acquisition["max_download_workers"]),
        )
        token = ""
        env.pop(TOKEN_ENVIRONMENT_VARIABLE, None)
        files, license_path = _validate_download(stage)
        os.rename(stage, final_snapshot)
        manifest = {
            "schema_version": 1,
            "provider": "huggingface_hub",
            "model_id": MODEL_ID,
            "revision": revision,
            "snapshot_dir": str(final_snapshot),
            "snapshot_tree_sha256": _tree_sha256(files),
            "files": files,
        }
        manifest_path = _write_json_exclusive(run_dir / "snapshot-manifest.json", manifest)
        receipt = {
            "schema_version": 1,
            "model_id": MODEL_ID,
            "resolved_provider_revision": revision,
            "accepted_by": accepted_by,
            "accepted_at_utc": accepted_at_utc,
            "user_confirmed_acceptance": True,
            "license_identifier": config["acquisition"]["license_identifier"],
            "license_text_sha256": sha256_file(final_snapshot / license_path.name),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": sha256_file(manifest_path),
        }
        receipt_path = _write_json_exclusive(run_dir / "access-receipt.json", receipt)
        terminal = {
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_VERIFIED_NO_GENERATION",
            "run_id": run_id,
            "started_at_utc": started,
            "finished_at_utc": _utc_now(),
            "model_id": MODEL_ID,
            "resolved_provider_revision": revision,
            "snapshot_dir": str(final_snapshot),
            "snapshot_manifest_path": str(manifest_path),
            "snapshot_manifest_sha256": sha256_file(manifest_path),
            "snapshot_tree_sha256": manifest["snapshot_tree_sha256"],
            "access_receipt_path": str(receipt_path),
            "access_receipt_sha256": sha256_file(receipt_path),
            "acquisition_manifest_path": str(acquisition_manifest_path),
            "acquisition_manifest_sha256": sha256_file(acquisition_manifest_path),
            "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
            "model_calls": 0,
            "generated_audio": 0,
        }
        terminal_path = _write_json_exclusive(run_dir / "terminal.json", terminal)
        return {**terminal, "terminal_path": str(terminal_path)}
    except BaseException as exc:
        token = ""
        env.pop(TOKEN_ENVIRONMENT_VARIABLE, None)
        failure_path = run_dir / "terminal-failure.json"
        if (
            run_dir.is_dir()
            and acquisition_manifest_path is not None
            and not failure_path.exists()
        ):
            _write_json_exclusive(
                failure_path,
                {
                    "schema_version": 1,
                    "status": "ACQUISITION_FAILED_STOPPED",
                    "run_id": run_id,
                    "started_at_utc": started,
                    "finished_at_utc": _utc_now(),
                    "error_type": type(exc).__name__,
                    "acquisition_manifest_path": str(acquisition_manifest_path),
                    "acquisition_manifest_sha256": sha256_file(acquisition_manifest_path),
                    "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
                    "partial_snapshot_retained": stage.exists(),
                    "model_calls": 0,
                    "generated_audio": 0,
                },
            )
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, (SaoAcquisitionError, FileExistsError)):
            raise
        # Provider/client exceptions have included request headers and tokens in
        # their messages in the past.  Preserve only the exception type in the
        # sanitized terminal and never propagate the provider's text/traceback.
        raise SaoAcquisitionError(
            "SAO acquisition failed; see the retained sanitized failure terminal"
        ) from None
    finally:
        token = ""
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()

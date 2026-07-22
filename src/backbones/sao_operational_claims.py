"""Durable one-shot authorization claims for Stable Audio Open execution.

This module is deliberately independent of the model adapter.  Both claims are
consumed before a model can be loaded: the exact three-call mini-smoke has one
fixed attempt identity, while an SAO-only core decision/config pair can prepare
one exact 1,536-row run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAO_MODEL_ID = "stabilityai/stable-audio-open-1.0"
SAO_MINI_SMOKE_RUN_ID = "sao-mini-smoke-v2-001"
SAO_MINI_SMOKE_RUN_DIR = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "runs/sao-live-v2/mini-smoke/sao-mini-smoke-v2-001"
)
SAO_MINI_SMOKE_ATTEMPT_CLAIM = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "claims/sao-live-v2/sao-mini-smoke-v2-001.attempt.claim.json"
)
SAO_MINI_SMOKE_REPLACEMENT_RUN_ID = "sao-mini-smoke-v2-002"
SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR = SAO_MINI_SMOKE_RUN_DIR.with_name(
    SAO_MINI_SMOKE_REPLACEMENT_RUN_ID
)
SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "claims/sao-live-v2/sao-mini-smoke-v2-002.pre-model-replacement.claim.json"
)
SAO_MINI_SMOKE_FAILURE_LOG = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "logs/sao-live-v2/sao-mini-smoke-v2-001.launch.log"
)
SAO_DECISIONS_PATH = Path(__file__).resolve().parents[2] / "DECISIONS.md"
SAO_MINI_SMOKE_ORIGINAL_ATTEMPT_CLAIM_SHA256 = (
    "e57df24fdec18681764ca11c2585d1727f0fe677494a36e6eb8e4b43f55ad995"
)
SAO_MINI_SMOKE_FAILURE_LOG_SHA256 = (
    "73ecd7e0f5c59b75787d5a55f1016cf85461f862e95ee31c6bc8a87ea77593ba"
)
SAO_MINI_SMOKE_ORIGINAL_CLAIM_IDENTITY_SHA256 = (
    "f9342534decebc58a43e6f70b87d070e73986fbf7820cd7491c3bfb34ea19d6a"
)
SAO_MINI_SMOKE_ORIGINAL_RUNTIME_AUTHORIZATION_SHA256 = (
    "b6a0be60366701465482c9a0991cd5008c4f9935806466d657885936068fb09e"
)
SAO_MINI_SMOKE_ORIGINAL_GIT_COMMIT = "17696ed77cb118c01eb51867fc483415788c87a0"
SAO_MINI_SMOKE_ORIGINAL_RUNNER_SHA256 = (
    "91a476fb8f1050c415c147907226c1a99167acb9ba52fa3a3103f404c6603883"
)
SAO_MINI_SMOKE_ORIGINAL_IMPLEMENTATION_SHA256 = (
    "220d45c4fcd1381946e6f63af9e63abbdefdff3688e7f3e1362b291dcfcc782d"
)
SAO_MINI_SMOKE_ORIGINAL_CLAIMS_SOURCE_SHA256 = (
    "8e2aa6bd46c3532c09f0045605f98d4a321a5e8c8a0fd953e561521851a7495f"
)
SAO_MINI_SMOKE_ORIGINAL_ADAPTER_SHA256 = (
    "b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef"
)
SAO_MINI_SMOKE_REPLACEMENT_DECISION_ID = "D-0042"
SAO_MINI_SMOKE_ORIGINAL_FAILURE_PHASE = "PRE_MODEL_RUN_DIRECTORY_CREATION"
SAO_MINI_SMOKE_SEED_SCHEDULE = (
    ("S-0011", 73193011),
    ("S-0011", 73193011),
    ("S-0012", 73193012),
)
_ORIGINAL_ATTEMPT_CLAIM_KEYS = {
    "authorized_calls",
    "authorized_max_clip_seconds",
    "authorized_max_gpus",
    "backbone_config_sha256",
    "claim_identity_sha256",
    "claimed_at_utc",
    "decision_id",
    "git_commit",
    "live_config_path",
    "live_config_sha256",
    "model_id",
    "retry_allowed",
    "run_dir",
    "run_id",
    "runtime_authorization_path",
    "runtime_authorization_sha256",
    "schema_version",
    "scope",
    "status",
}
_PRE_MODEL_REPLACEMENT_CLAIM_KEYS = _ORIGINAL_ATTEMPT_CLAIM_KEYS | {
    "authorized_seed_schedule",
    "cumulative_audio_outputs_before_replacement",
    "cumulative_model_loads_before_replacement",
    "cumulative_model_calls_before_replacement",
    "decision_block_sha256",
    "decisions_path",
    "failure_log_path",
    "failure_log_sha256",
    "original_attempt_claim_identity_sha256",
    "original_attempt_claim_path",
    "original_attempt_claim_sha256",
    "original_failure_phase",
}
SHARED_CORE_DEVICE_LOCK_ROOT = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
    "locks/core-v2"
)
SAO_CORE_EXACT_GENERATIONS = 1_536

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SaoOperationalAuthorizationError(RuntimeError):
    """An SAO one-shot authority is invalid, already consumed, or replayed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SaoOperationalAuthorizationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _strict_json_object(path: Path) -> tuple[Path, dict[str, Any]]:
    try:
        source = path.resolve(strict=True)
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                SaoOperationalAuthorizationError(f"non-finite JSON number: {token}")
            ),
        )
    except SaoOperationalAuthorizationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SaoOperationalAuthorizationError(f"cannot read authorization JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SaoOperationalAuthorizationError("authorization JSON must be an object")
    return source, value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_o_excl(path: Path, value: Mapping[str, Any]) -> None:
    """Create one immutable claim atomically; an existing path is never reused."""

    payload = (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:  # pragma: no cover - defensive kernel-I/O guard
                raise OSError("short write while sealing SAO authorization claim")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _require_exact_int(value: Any, expected: int, field: str) -> None:
    if type(value) is not int or value != expected:
        raise SaoOperationalAuthorizationError(
            f"SAO runtime authorization mismatch: {field} must equal {expected}"
        )


def _claim_identity(record: Mapping[str, Any]) -> str:
    unhashed = dict(record)
    unhashed.pop("claim_identity_sha256", None)
    return hashlib.sha256(_canonical_json(unhashed).encode()).hexdigest()


def _preparation_identity(record: Mapping[str, Any]) -> str:
    unhashed = dict(record)
    unhashed.pop("preparation_identity_sha256", None)
    return hashlib.sha256(_canonical_json(unhashed).encode()).hexdigest()


def _path_entry_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _expected_pre_model_failure_log_text() -> str:
    return (
        "Traceback (most recent call last):\n"
        '  File "/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/repository/scripts/'
        'run_sao_mini_smoke_v2.py", line 191, in <module>\n'
        "    raise SystemExit(main())\n"
        '  File "/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/repository/scripts/'
        'run_sao_mini_smoke_v2.py", line 167, in main\n'
        "    result = run_sao_mini_smoke(\n"
        '  File "/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/repository/src/'
        'backbones/sao_mini_smoke.py", line 849, in run_sao_mini_smoke\n'
        "    destination.mkdir(parents=False, exist_ok=False)\n"
        '  File "/usr/lib/python3.10/pathlib.py", line 1175, in mkdir\n'
        "    self._accessor.mkdir(self, mode)\n"
        "FileNotFoundError: [Errno 2] No such file or directory: "
        f"'{SAO_MINI_SMOKE_RUN_DIR.resolve()}'\n"
    )


def _validate_original_mini_smoke_attempt_claim(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise SaoOperationalAuthorizationError("SAO original attempt claim may not be a symlink")
    source, value = _strict_json_object(path)
    expected = {
        "authorized_calls": 3,
        "authorized_max_clip_seconds": 30,
        "authorized_max_gpus": 1,
        "decision_id": "D-0037",
        "model_id": SAO_MODEL_ID,
        "retry_allowed": False,
        "run_dir": str(SAO_MINI_SMOKE_RUN_DIR.resolve()),
        "run_id": SAO_MINI_SMOKE_RUN_ID,
        "schema_version": 1,
        "scope": "SAO_MINI_SMOKE_EXACT_THREE_CALL_ONE_SHOT",
        "status": "CLAIMED_NO_RETRY",
    }
    if set(value) != _ORIGINAL_ATTEMPT_CLAIM_KEYS:
        raise SaoOperationalAuthorizationError("SAO original attempt claim keys drifted")
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise SaoOperationalAuthorizationError(f"SAO mini-smoke claim mismatch: {field}")
    for field in (
        "backbone_config_sha256",
        "claim_identity_sha256",
        "live_config_sha256",
        "runtime_authorization_sha256",
    ):
        if not isinstance(value.get(field), str) or SHA256_RE.fullmatch(value[field]) is None:
            raise SaoOperationalAuthorizationError(f"SAO mini-smoke claim hash invalid: {field}")
    if GIT_REVISION_RE.fullmatch(str(value.get("git_commit", ""))) is None:
        raise SaoOperationalAuthorizationError("SAO mini-smoke claim Git revision is invalid")
    if value.get("claim_identity_sha256") != _claim_identity(value):
        raise SaoOperationalAuthorizationError("SAO mini-smoke claim identity mismatch")
    return {**value, "path": str(source), "sha256": _sha256_file(source)}


def _validate_pre_model_failure_observation(*, require_replacement_absent: bool) -> dict[str, Any]:
    original_path = SAO_MINI_SMOKE_ATTEMPT_CLAIM
    if not original_path.is_absolute() or original_path.resolve() != original_path:
        raise SaoOperationalAuthorizationError("SAO original attempt claim path is not canonical")
    original = _validate_original_mini_smoke_attempt_claim(original_path)
    if original["sha256"] != SAO_MINI_SMOKE_ORIGINAL_ATTEMPT_CLAIM_SHA256:
        raise SaoOperationalAuthorizationError("SAO original attempt claim hash mismatch")
    if (
        original["claim_identity_sha256"]
        != SAO_MINI_SMOKE_ORIGINAL_CLAIM_IDENTITY_SHA256
        or original["runtime_authorization_sha256"]
        != SAO_MINI_SMOKE_ORIGINAL_RUNTIME_AUTHORIZATION_SHA256
        or original["git_commit"] != SAO_MINI_SMOKE_ORIGINAL_GIT_COMMIT
    ):
        raise SaoOperationalAuthorizationError("SAO original attempt claim lineage drifted")

    log_path = SAO_MINI_SMOKE_FAILURE_LOG
    if not log_path.is_absolute() or log_path.is_symlink():
        raise SaoOperationalAuthorizationError("SAO pre-model failure log path is invalid")
    try:
        resolved_log = log_path.resolve(strict=True)
        raw_log = resolved_log.read_bytes()
        observed_text = raw_log.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoOperationalAuthorizationError("SAO pre-model failure log is unavailable") from exc
    if hashlib.sha256(raw_log).hexdigest() != SAO_MINI_SMOKE_FAILURE_LOG_SHA256:
        raise SaoOperationalAuthorizationError("SAO pre-model failure log hash mismatch")
    if observed_text != _expected_pre_model_failure_log_text():
        raise SaoOperationalAuthorizationError("SAO pre-model failure traceback content drifted")

    original_artifacts = (
        SAO_MINI_SMOKE_RUN_DIR,
        SAO_MINI_SMOKE_RUN_DIR / "manifest.json",
        SAO_MINI_SMOKE_RUN_DIR / "generation-ledger.jsonl",
        SAO_MINI_SMOKE_RUN_DIR / "audio",
        SAO_MINI_SMOKE_RUN_DIR / "sao-mini-smoke-terminal.json",
    )
    if any(_path_entry_exists(path) for path in original_artifacts):
        raise SaoOperationalAuthorizationError(
            "SAO original attempt materialized a run, ledger, or audio artifact"
        )
    if require_replacement_absent:
        replacement_artifacts = (
            SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR,
            SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR / "generation-ledger.jsonl",
            SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR / "audio",
        )
        if any(_path_entry_exists(path) for path in replacement_artifacts):
            raise SaoOperationalAuthorizationError(
                "SAO replacement run, ledger, or audio artifact already exists"
            )
    return {
        "status": "VALIDATED_ZERO_CALL_PRE_MODEL_FAILURE",
        "original_attempt_claim_path": original["path"],
        "original_attempt_claim_sha256": original["sha256"],
        "original_attempt_claim_identity_sha256": original["claim_identity_sha256"],
        "failure_log_path": str(resolved_log),
        "failure_log_sha256": hashlib.sha256(raw_log).hexdigest(),
        "original_failure_phase": SAO_MINI_SMOKE_ORIGINAL_FAILURE_PHASE,
        "cumulative_model_calls_before_replacement": 0,
        "cumulative_model_loads_before_replacement": 0,
        "cumulative_audio_outputs_before_replacement": 0,
    }


def validate_sao_mini_smoke_pre_model_failure_observation() -> dict[str, Any]:
    """Prove that D-0037 stopped before a run directory or model call existed."""

    return _validate_pre_model_failure_observation(require_replacement_absent=True)


def _verify_clean_main_revision(expected_git_commit: str) -> None:
    root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        origin = subprocess.check_output(
            ["git", "rev-parse", "origin/main"], cwd=root, text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=root, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SaoOperationalAuthorizationError("cannot verify clean main for replacement") from exc
    if head != expected_git_commit or head != origin or branch != "main" or dirty:
        raise SaoOperationalAuthorizationError(
            "SAO pre-model replacement requires clean local main equal to origin/main"
        )


def prepare_sao_mini_smoke_attempt(
    runtime_authorization_path: Path,
    *,
    requested_run_dir: Path,
    live_config_path: Path,
    git_commit: str,
    decisions_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and seal every deterministic input before reserving a GPU."""

    original_consumed = _path_entry_exists(SAO_MINI_SMOKE_ATTEMPT_CLAIM)
    expected_run_dir = (
        SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR.resolve()
        if original_consumed
        else SAO_MINI_SMOKE_RUN_DIR.resolve()
    )
    expected_run_id = (
        SAO_MINI_SMOKE_REPLACEMENT_RUN_ID if original_consumed else SAO_MINI_SMOKE_RUN_ID
    )
    observed_run_dir = requested_run_dir.resolve()
    if original_consumed and observed_run_dir == SAO_MINI_SMOKE_RUN_DIR.resolve():
        raise SaoOperationalAuthorizationError(
            "SAO mini-smoke original global attempt authority was already consumed"
        )
    if observed_run_dir != expected_run_dir or observed_run_dir.name != expected_run_id:
        raise SaoOperationalAuthorizationError(
            "SAO mini-smoke run directory is not the fixed authorized run path"
        )
    if GIT_REVISION_RE.fullmatch(git_commit) is None:
        raise SaoOperationalAuthorizationError("SAO mini-smoke Git revision is invalid")

    authorization_path, authorization = _strict_json_object(runtime_authorization_path)
    expected_strings = {
        "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
        "decision_id": "D-0037",
    }
    for field, expected in expected_strings.items():
        if authorization.get(field) != expected:
            raise SaoOperationalAuthorizationError(
                f"SAO runtime authorization mismatch: {field}"
            )
    _require_exact_int(authorization.get("schema_version"), 1, "schema_version")
    _require_exact_int(authorization.get("max_generations"), 3, "max_generations")
    _require_exact_int(authorization.get("max_clip_seconds"), 30, "max_clip_seconds")
    _require_exact_int(authorization.get("max_gpus"), 1, "max_gpus")
    for field in ("backbone_config_sha256", "access_receipt_sha256"):
        if not isinstance(authorization.get(field), str) or SHA256_RE.fullmatch(
            str(authorization[field])
        ) is None:
            raise SaoOperationalAuthorizationError(
                f"SAO runtime authorization mismatch: {field}"
            )

    try:
        resolved_live_config = live_config_path.resolve(strict=True)
    except OSError as exc:
        raise SaoOperationalAuthorizationError("SAO live config is unavailable") from exc
    claim_path = (
        SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM
        if original_consumed
        else SAO_MINI_SMOKE_ATTEMPT_CLAIM
    )
    if not claim_path.is_absolute():
        raise SaoOperationalAuthorizationError("SAO mini-smoke claim path must be absolute")
    if original_consumed:
        if decisions_path is None:
            raise SaoOperationalAuthorizationError(
                "SAO mini-smoke authority was already consumed; D-0042 replacement is required"
            )
        if _path_entry_exists(claim_path):
            raise SaoOperationalAuthorizationError(
                "SAO mini-smoke pre-model replacement authority was already consumed"
            )
        failure = validate_sao_mini_smoke_pre_model_failure_observation()
        decision = verify_sao_mini_smoke_pre_model_replacement_decision(decisions_path)
        _verify_clean_main_revision(git_commit)
        record: dict[str, Any] = {
            "authorized_calls": 3,
            "authorized_max_clip_seconds": 30,
            "authorized_max_gpus": 1,
            "authorized_seed_schedule": [
                {"generation_index": index, "seed_id": seed_id, "seed": seed}
                for index, (seed_id, seed) in enumerate(SAO_MINI_SMOKE_SEED_SCHEDULE)
            ],
            "backbone_config_sha256": authorization["backbone_config_sha256"],
            "cumulative_audio_outputs_before_replacement": 0,
            "cumulative_model_calls_before_replacement": 0,
            "cumulative_model_loads_before_replacement": 0,
            "decision_block_sha256": decision["decision_block_sha256"],
            "decision_id": SAO_MINI_SMOKE_REPLACEMENT_DECISION_ID,
            "decisions_path": decision["decisions_path"],
            "failure_log_path": failure["failure_log_path"],
            "failure_log_sha256": failure["failure_log_sha256"],
            "git_commit": git_commit,
            "live_config_path": str(resolved_live_config),
            "live_config_sha256": _sha256_file(resolved_live_config),
            "model_id": SAO_MODEL_ID,
            "original_attempt_claim_identity_sha256": failure[
                "original_attempt_claim_identity_sha256"
            ],
            "original_attempt_claim_path": failure["original_attempt_claim_path"],
            "original_attempt_claim_sha256": failure["original_attempt_claim_sha256"],
            "original_failure_phase": failure["original_failure_phase"],
            "retry_allowed": False,
            "run_dir": str(expected_run_dir),
            "run_id": expected_run_id,
            "runtime_authorization_path": str(authorization_path),
            "runtime_authorization_sha256": _sha256_file(authorization_path),
            "schema_version": 1,
            "scope": "SAO_MINI_SMOKE_EXACT_THREE_CALL_PRE_MODEL_REPLACEMENT",
            "status": "CLAIMED_PRE_MODEL_REPLACEMENT_NO_FURTHER_RETRY",
        }
    else:
        record = {
            "authorized_calls": 3,
            "authorized_max_clip_seconds": 30,
            "authorized_max_gpus": 1,
            "backbone_config_sha256": authorization["backbone_config_sha256"],
            "decision_id": "D-0037",
            "git_commit": git_commit,
            "live_config_path": str(resolved_live_config),
            "live_config_sha256": _sha256_file(resolved_live_config),
            "model_id": SAO_MODEL_ID,
            "retry_allowed": False,
            "run_dir": str(expected_run_dir),
            "run_id": expected_run_id,
            "runtime_authorization_path": str(authorization_path),
            "runtime_authorization_sha256": _sha256_file(authorization_path),
            "schema_version": 1,
            "scope": "SAO_MINI_SMOKE_EXACT_THREE_CALL_ONE_SHOT",
            "status": "CLAIMED_NO_RETRY",
        }
    root = Path(__file__).resolve().parents[2]
    bound_paths = {
        authorization_path,
        resolved_live_config,
        root / "scripts" / "run_sao_mini_smoke_v2.py",
        root / "src" / "backbones" / "sao_mini_smoke.py",
        root / "src" / "backbones" / "sao_operational_claims.py",
        root / "src" / "backbones" / "stable_audio_open.py",
    }
    if original_consumed:
        bound_paths.update(
            {
                SAO_MINI_SMOKE_ATTEMPT_CLAIM,
                SAO_MINI_SMOKE_FAILURE_LOG,
                Path(str(record["decisions_path"])),
            }
        )
    preparation: dict[str, Any] = {
        "bound_file_sha256": {
            str(path.resolve(strict=True)): _sha256_file(path.resolve(strict=True))
            for path in sorted(bound_paths, key=lambda item: str(item))
        },
        "claim_path": str(claim_path),
        "original_consumed": original_consumed,
        "record": record,
        "schema_version": 1,
        "status": "PREPARED_FOR_ATOMIC_CLAIM",
    }
    preparation["preparation_identity_sha256"] = _preparation_identity(preparation)
    return preparation


def consume_sao_mini_smoke_attempt(
    runtime_authorization_path: Path,
    *,
    requested_run_dir: Path,
    live_config_path: Path,
    git_commit: str,
    decisions_path: Path | None = None,
    prepared_attempt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically consume one already-validated D-0037 or D-0042 claim."""

    canonical_preparation = prepare_sao_mini_smoke_attempt(
        runtime_authorization_path,
        requested_run_dir=requested_run_dir,
        live_config_path=live_config_path,
        git_commit=git_commit,
        decisions_path=decisions_path,
    )
    if prepared_attempt is not None and _canonical_json(dict(prepared_attempt)) != _canonical_json(
        canonical_preparation
    ):
        raise SaoOperationalAuthorizationError(
            "SAO mini-smoke prepared attempt is not the canonical authorization"
        )
    preparation = canonical_preparation
    if set(preparation) != {
        "claim_path",
        "bound_file_sha256",
        "original_consumed",
        "preparation_identity_sha256",
        "record",
        "schema_version",
        "status",
    }:
        raise SaoOperationalAuthorizationError("SAO mini-smoke preparation keys drifted")
    if (
        preparation.get("schema_version") != 1
        or preparation.get("status") != "PREPARED_FOR_ATOMIC_CLAIM"
        or preparation.get("preparation_identity_sha256") != _preparation_identity(preparation)
    ):
        raise SaoOperationalAuthorizationError("SAO mini-smoke preparation identity mismatch")
    record_value = preparation.get("record")
    if not isinstance(record_value, dict):
        raise SaoOperationalAuthorizationError("SAO mini-smoke prepared record is invalid")
    record = dict(record_value)
    bound_files = preparation.get("bound_file_sha256")
    if not isinstance(bound_files, dict) or not bound_files:
        raise SaoOperationalAuthorizationError("SAO mini-smoke preparation has no file bindings")
    for raw_path, expected_sha256 in bound_files.items():
        if (
            not isinstance(raw_path, str)
            or not isinstance(expected_sha256, str)
            or SHA256_RE.fullmatch(expected_sha256) is None
        ):
            raise SaoOperationalAuthorizationError(
                "SAO mini-smoke prepared file binding is invalid"
            )
        bound_path = Path(raw_path)
        if not bound_path.is_absolute() or bound_path.is_symlink():
            raise SaoOperationalAuthorizationError(
                "SAO mini-smoke prepared file path is invalid"
            )
        try:
            observed_sha256 = _sha256_file(bound_path.resolve(strict=True))
        except OSError as exc:
            raise SaoOperationalAuthorizationError(
                "SAO mini-smoke prepared input disappeared before claim"
            ) from exc
        if observed_sha256 != expected_sha256:
            raise SaoOperationalAuthorizationError(
                "SAO mini-smoke prepared input changed before claim"
            )
    claim_path = Path(str(preparation["claim_path"]))
    original_consumed = preparation.get("original_consumed")
    expected_claim_path = (
        SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM
        if original_consumed is True
        else SAO_MINI_SMOKE_ATTEMPT_CLAIM
    )
    if type(original_consumed) is not bool or claim_path != expected_claim_path:
        raise SaoOperationalAuthorizationError("SAO mini-smoke prepared claim path drifted")
    if record.get("run_dir") != str(requested_run_dir.resolve()):
        raise SaoOperationalAuthorizationError("SAO mini-smoke prepared run path drifted")
    if record.get("git_commit") != git_commit:
        raise SaoOperationalAuthorizationError("SAO mini-smoke prepared Git revision drifted")
    if record.get("runtime_authorization_path") != str(runtime_authorization_path.resolve()):
        raise SaoOperationalAuthorizationError("SAO mini-smoke prepared authorization drifted")
    if record.get("live_config_path") != str(live_config_path.resolve()):
        raise SaoOperationalAuthorizationError("SAO mini-smoke prepared live config drifted")
    if _path_entry_exists(claim_path):
        raise SaoOperationalAuthorizationError(
            "SAO mini-smoke global attempt authority was already consumed"
        )
    if original_consumed is True:
        if not _path_entry_exists(SAO_MINI_SMOKE_ATTEMPT_CLAIM):
            raise SaoOperationalAuthorizationError("SAO original attempt claim disappeared")
        forbidden = (SAO_MINI_SMOKE_RUN_DIR, SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR)
    else:
        if _path_entry_exists(SAO_MINI_SMOKE_ATTEMPT_CLAIM):
            raise SaoOperationalAuthorizationError("SAO original attempt claim appeared")
        forbidden = (SAO_MINI_SMOKE_RUN_DIR,)
    if any(_path_entry_exists(path) for path in forbidden):
        raise SaoOperationalAuthorizationError("SAO mini-smoke run appeared before claim")

    record["claimed_at_utc"] = _utc_now()
    record["claim_identity_sha256"] = _claim_identity(record)
    try:
        _write_json_o_excl(claim_path, record)
    except FileExistsError as exc:
        raise SaoOperationalAuthorizationError(
            "SAO mini-smoke global attempt authority was already consumed"
        ) from exc
    return {
        **record,
        "path": str(claim_path.resolve(strict=True)),
        "sha256": _sha256_file(claim_path),
    }


def validate_sao_mini_smoke_attempt_claim(path: Path) -> dict[str, Any]:
    """Deeply validate either the original claim or sole D-0042 replacement."""

    if path.is_symlink():
        raise SaoOperationalAuthorizationError("SAO mini-smoke attempt claim may not be a symlink")
    source, value = _strict_json_object(path)
    if value.get("decision_id") == "D-0037":
        return _validate_original_mini_smoke_attempt_claim(path)
    if value.get("decision_id") != SAO_MINI_SMOKE_REPLACEMENT_DECISION_ID:
        raise SaoOperationalAuthorizationError("SAO mini-smoke claim decision is unauthorized")
    if source != SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM.resolve():
        raise SaoOperationalAuthorizationError("SAO replacement claim path is not canonical")
    if set(value) != _PRE_MODEL_REPLACEMENT_CLAIM_KEYS:
        raise SaoOperationalAuthorizationError("SAO replacement claim keys drifted")
    expected = {
        "authorized_calls": 3,
        "authorized_max_clip_seconds": 30,
        "authorized_max_gpus": 1,
        "authorized_seed_schedule": [
            {"generation_index": index, "seed_id": seed_id, "seed": seed}
            for index, (seed_id, seed) in enumerate(SAO_MINI_SMOKE_SEED_SCHEDULE)
        ],
        "cumulative_audio_outputs_before_replacement": 0,
        "cumulative_model_calls_before_replacement": 0,
        "cumulative_model_loads_before_replacement": 0,
        "decision_id": SAO_MINI_SMOKE_REPLACEMENT_DECISION_ID,
        "model_id": SAO_MODEL_ID,
        "original_attempt_claim_identity_sha256": (
            SAO_MINI_SMOKE_ORIGINAL_CLAIM_IDENTITY_SHA256
        ),
        "original_attempt_claim_sha256": SAO_MINI_SMOKE_ORIGINAL_ATTEMPT_CLAIM_SHA256,
        "original_failure_phase": SAO_MINI_SMOKE_ORIGINAL_FAILURE_PHASE,
        "retry_allowed": False,
        "run_dir": str(SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR.resolve()),
        "run_id": SAO_MINI_SMOKE_REPLACEMENT_RUN_ID,
        "schema_version": 1,
        "scope": "SAO_MINI_SMOKE_EXACT_THREE_CALL_PRE_MODEL_REPLACEMENT",
        "status": "CLAIMED_PRE_MODEL_REPLACEMENT_NO_FURTHER_RETRY",
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise SaoOperationalAuthorizationError(f"SAO replacement claim mismatch: {field}")
    if value.get("claim_identity_sha256") != _claim_identity(value):
        raise SaoOperationalAuthorizationError("SAO replacement claim identity mismatch")
    failure = _validate_pre_model_failure_observation(require_replacement_absent=False)
    for claim_field, failure_field in (
        ("original_attempt_claim_path", "original_attempt_claim_path"),
        ("original_attempt_claim_sha256", "original_attempt_claim_sha256"),
        ("original_attempt_claim_identity_sha256", "original_attempt_claim_identity_sha256"),
        ("failure_log_path", "failure_log_path"),
        ("failure_log_sha256", "failure_log_sha256"),
        ("original_failure_phase", "original_failure_phase"),
        (
            "cumulative_model_calls_before_replacement",
            "cumulative_model_calls_before_replacement",
        ),
        (
            "cumulative_model_loads_before_replacement",
            "cumulative_model_loads_before_replacement",
        ),
        (
            "cumulative_audio_outputs_before_replacement",
            "cumulative_audio_outputs_before_replacement",
        ),
    ):
        if value.get(claim_field) != failure[failure_field]:
            raise SaoOperationalAuthorizationError(
                f"SAO replacement claim failure lineage mismatch: {claim_field}"
            )
    decision = verify_sao_mini_smoke_pre_model_replacement_decision(
        Path(str(value.get("decisions_path", "")))
    )
    if value.get("decision_block_sha256") != decision["decision_block_sha256"]:
        raise SaoOperationalAuthorizationError("SAO replacement decision block hash mismatch")
    return {**value, "path": str(source), "sha256": _sha256_file(source)}


def _decision_block(text: str, decision_id: str) -> str:
    header = re.compile(rf"^##\s+{re.escape(decision_id)}(?:\s|$)")
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if header.search(line)]
    if len(starts) != 1:
        raise SaoOperationalAuthorizationError(
            "SAO core decision ID must identify exactly one entry"
        )
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    # A future append-only decision heading must not mutate this block's hash
    # merely by turning the existing EOF newline into a separating blank line.
    return "\n".join(lines[start:end]).rstrip()


def _single_decision_assignment(block: str, key: str) -> str:
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
        raise SaoOperationalAuthorizationError(
            f"SAO core decision must contain exactly one {key} assignment"
        )
    return values[0]


def sao_mini_smoke_pre_model_replacement_decision_assignments() -> dict[str, str]:
    """Return the exact D-0042 vocabulary, including all execution source hashes."""

    root = Path(__file__).resolve().parents[2]
    return {
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_AUTHORIZED": "YES",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_RUN_ID": SAO_MINI_SMOKE_RUN_ID,
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_RUN_ID": SAO_MINI_SMOKE_REPLACEMENT_RUN_ID,
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM_PATH": str(
            SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_CLAIM_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_ATTEMPT_CLAIM_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_CLAIM_IDENTITY_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_CLAIM_IDENTITY_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_RUNTIME_AUTHORIZATION_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_RUNTIME_AUTHORIZATION_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_GIT_COMMIT": (
            SAO_MINI_SMOKE_ORIGINAL_GIT_COMMIT
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_FAILURE_LOG_SHA256": (
            SAO_MINI_SMOKE_FAILURE_LOG_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_FAILURE_PHASE": (
            SAO_MINI_SMOKE_ORIGINAL_FAILURE_PHASE
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_MODEL_CALLS": "0",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_MODEL_LOADS": "0",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_AUDIO_OUTPUTS": "0",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_EXACT_CALLS": "3",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_EXACT_CLAIMS": "1",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_MAX_CLIP_SECONDS": "30",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_MAX_GPUS": "1",
        "SAO_MINI_SMOKE_FURTHER_REPLACEMENT_AUTHORIZED": "NO",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_RUNNER_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_RUNNER_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_IMPLEMENTATION_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_IMPLEMENTATION_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_CLAIMS_SOURCE_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_CLAIMS_SOURCE_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_ADAPTER_SHA256": (
            SAO_MINI_SMOKE_ORIGINAL_ADAPTER_SHA256
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_RUNNER_SHA256": _sha256_file(
            root / "scripts" / "run_sao_mini_smoke_v2.py"
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_IMPLEMENTATION_SHA256": _sha256_file(
            root / "src" / "backbones" / "sao_mini_smoke.py"
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIMS_SHA256": _sha256_file(
            root / "src" / "backbones" / "sao_operational_claims.py"
        ),
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ADAPTER_SHA256": _sha256_file(
            root / "src" / "backbones" / "stable_audio_open.py"
        ),
    }


def verify_sao_mini_smoke_pre_model_replacement_decision(
    decisions_path: Path,
) -> dict[str, str]:
    """Validate the sole D-0042 replacement and its exact source/evidence bindings."""

    if decisions_path.is_symlink():
        raise SaoOperationalAuthorizationError("SAO replacement decision path may not be a symlink")
    try:
        source = decisions_path.resolve(strict=True)
        expected_source = SAO_DECISIONS_PATH.resolve(strict=True)
        if source != expected_source:
            raise SaoOperationalAuthorizationError(
                "SAO replacement decision is not the repository DECISIONS.md"
            )
        block = _decision_block(
            source.read_text(encoding="utf-8"), SAO_MINI_SMOKE_REPLACEMENT_DECISION_ID
        )
    except SaoOperationalAuthorizationError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoOperationalAuthorizationError(
            "SAO replacement decision file is unavailable"
        ) from exc
    expected = sao_mini_smoke_pre_model_replacement_decision_assignments()
    for key, expected_value in expected.items():
        if _single_decision_assignment(block, key) != expected_value:
            raise SaoOperationalAuthorizationError(
                f"SAO pre-model replacement decision mismatch: {key}"
            )
    return {
        "decision_block_sha256": hashlib.sha256(block.encode()).hexdigest(),
        "decision_id": SAO_MINI_SMOKE_REPLACEMENT_DECISION_ID,
        "decisions_path": str(source),
    }


def verify_exact_sao_core_decision(
    decisions_path: Path,
    *,
    decision_id: str,
    requested_run_id: str,
    expected_decision_block_sha256: str,
) -> dict[str, str]:
    """Bind the SAO-only launcher to one run ID in the authorized block."""

    if RUN_ID_RE.fullmatch(requested_run_id) is None:
        raise SaoOperationalAuthorizationError("SAO core run ID is invalid")
    try:
        source = decisions_path.resolve(strict=True)
        block = _decision_block(source.read_text(encoding="utf-8"), decision_id)
    except SaoOperationalAuthorizationError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoOperationalAuthorizationError("SAO core decision file is unavailable") from exc
    block_sha256 = hashlib.sha256(block.encode()).hexdigest()
    if (
        SHA256_RE.fullmatch(expected_decision_block_sha256) is None
        or block_sha256 != expected_decision_block_sha256
    ):
        raise SaoOperationalAuthorizationError("SAO core decision block identity changed")
    authorized_run_id = _single_decision_assignment(
        block, "BENCHMARK_CORE_AUTHORIZED_RUN_ID"
    )
    if authorized_run_id != requested_run_id:
        raise SaoOperationalAuthorizationError(
            "SAO core requested run ID differs from the sole authorized run ID"
        )
    authorized_models = _single_decision_assignment(
        block, "BENCHMARK_CORE_AUTHORIZED_MODEL_IDS"
    )
    if authorized_models != SAO_MODEL_ID:
        raise SaoOperationalAuthorizationError("SAO core decision is not SAO-only")
    return {
        "authorized_run_id": authorized_run_id,
        "decision_block_sha256": block_sha256,
        "decisions_path": str(source),
    }


def sao_core_global_claim_path(
    run_root: Path,
    *,
    config_sha256: str,
    decision_block_sha256: str,
) -> Path:
    """Derive the one global path for one frozen SAO decision/config pair."""

    if not run_root.is_absolute():
        raise SaoOperationalAuthorizationError("SAO core run root must be absolute")
    if SHA256_RE.fullmatch(config_sha256) is None or SHA256_RE.fullmatch(
        decision_block_sha256
    ) is None:
        raise SaoOperationalAuthorizationError("SAO core claim identity hashes are invalid")
    resolved_root = run_root.resolve()
    if resolved_root.name != "core-v2" or resolved_root.parent.name != "runs":
        raise SaoOperationalAuthorizationError(
            "SAO core run root is outside the shared core-v2 runtime namespace"
        )
    runtime_root = resolved_root.parent.parent
    return runtime_root / "claims" / "core-v2" / "sao-one-shot" / (
        f"{config_sha256}-{decision_block_sha256}.claim.json"
    )


def consume_sao_core_run_claim(
    *,
    run_id: str,
    run_dir: Path,
    run_root: Path,
    config_path: Path,
    config_sha256: str,
    decisions_path: Path,
    decision_id: str,
    decision_block_sha256: str,
    git_commit: str,
) -> dict[str, Any]:
    """Atomically consume the SAO core authority before materializing a run."""

    if RUN_ID_RE.fullmatch(run_id) is None or GIT_REVISION_RE.fullmatch(git_commit) is None:
        raise SaoOperationalAuthorizationError("SAO core run/Git identity is invalid")
    expected_run_dir = run_root.resolve() / run_id
    if run_dir.resolve() != expected_run_dir:
        raise SaoOperationalAuthorizationError("SAO core run path differs from its fixed run ID")
    try:
        resolved_config = config_path.resolve(strict=True)
        resolved_decisions = decisions_path.resolve(strict=True)
    except OSError as exc:
        raise SaoOperationalAuthorizationError("SAO core launch input is unavailable") from exc
    if _sha256_file(resolved_config) != config_sha256:
        raise SaoOperationalAuthorizationError("SAO core config changed before global claim")
    claim_path = sao_core_global_claim_path(
        run_root,
        config_sha256=config_sha256,
        decision_block_sha256=decision_block_sha256,
    )
    record: dict[str, Any] = {
        "authorized_model_ids": [SAO_MODEL_ID],
        "claimed_at_utc": _utc_now(),
        "config_path": str(resolved_config),
        "config_sha256": config_sha256,
        "decision_block_sha256": decision_block_sha256,
        "decision_id": decision_id,
        "decisions_path": str(resolved_decisions),
        "exact_generations": SAO_CORE_EXACT_GENERATIONS,
        "git_commit": git_commit,
        "retry_allowed": False,
        "run_dir": str(expected_run_dir),
        "run_id": run_id,
        "schema_version": 1,
        "scope": "SAO_CORE_1536_ONE_SHOT",
        "status": "CLAIMED_NO_RETRY",
    }
    record["claim_identity_sha256"] = _claim_identity(record)
    try:
        _write_json_o_excl(claim_path, record)
    except FileExistsError as exc:
        raise SaoOperationalAuthorizationError(
            "SAO core decision/config authority was already consumed"
        ) from exc
    return {**record, "path": str(claim_path), "sha256": _sha256_file(claim_path)}


def validate_sao_core_run_claim(
    path: Path,
    *,
    run_id: str,
    run_dir: Path,
    config_sha256: str,
    decision_id: str,
    decision_block_sha256: str,
    git_commit: str,
) -> dict[str, Any]:
    """Revalidate the external global authority from any worker process."""

    source, value = _strict_json_object(path)
    expected_path = sao_core_global_claim_path(
        run_dir.parent,
        config_sha256=config_sha256,
        decision_block_sha256=decision_block_sha256,
    ).resolve()
    if source != expected_path:
        raise SaoOperationalAuthorizationError("SAO core global claim path is not canonical")
    expected: dict[str, Any] = {
        "authorized_model_ids": [SAO_MODEL_ID],
        "config_sha256": config_sha256,
        "decision_block_sha256": decision_block_sha256,
        "decision_id": decision_id,
        "exact_generations": SAO_CORE_EXACT_GENERATIONS,
        "git_commit": git_commit,
        "retry_allowed": False,
        "run_dir": str(run_dir.resolve()),
        "run_id": run_id,
        "schema_version": 1,
        "scope": "SAO_CORE_1536_ONE_SHOT",
        "status": "CLAIMED_NO_RETRY",
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise SaoOperationalAuthorizationError(f"SAO core global claim mismatch: {field}")
    if value.get("claim_identity_sha256") != _claim_identity(value):
        raise SaoOperationalAuthorizationError("SAO core global claim identity mismatch")
    return {**value, "path": str(source), "sha256": _sha256_file(source)}

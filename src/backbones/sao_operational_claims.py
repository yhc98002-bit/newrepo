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


def consume_sao_mini_smoke_attempt(
    runtime_authorization_path: Path,
    *,
    requested_run_dir: Path,
    live_config_path: Path,
    git_commit: str,
) -> dict[str, Any]:
    """Consume the sole global mini-smoke authority before GPU/model access."""

    expected_run_dir = SAO_MINI_SMOKE_RUN_DIR.resolve()
    observed_run_dir = requested_run_dir.resolve()
    if observed_run_dir != expected_run_dir or observed_run_dir.name != SAO_MINI_SMOKE_RUN_ID:
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
    claim_path = SAO_MINI_SMOKE_ATTEMPT_CLAIM
    if not claim_path.is_absolute():
        raise SaoOperationalAuthorizationError("SAO mini-smoke claim path must be absolute")
    record: dict[str, Any] = {
        "authorized_calls": 3,
        "authorized_max_clip_seconds": 30,
        "authorized_max_gpus": 1,
        "backbone_config_sha256": authorization["backbone_config_sha256"],
        "claimed_at_utc": _utc_now(),
        "decision_id": "D-0037",
        "git_commit": git_commit,
        "live_config_path": str(resolved_live_config),
        "live_config_sha256": _sha256_file(resolved_live_config),
        "model_id": SAO_MODEL_ID,
        "retry_allowed": False,
        "run_dir": str(expected_run_dir),
        "run_id": SAO_MINI_SMOKE_RUN_ID,
        "runtime_authorization_path": str(authorization_path),
        "runtime_authorization_sha256": _sha256_file(authorization_path),
        "schema_version": 1,
        "scope": "SAO_MINI_SMOKE_EXACT_THREE_CALL_ONE_SHOT",
        "status": "CLAIMED_NO_RETRY",
    }
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
    """Validate the immutable smoke attempt claim without granting a new attempt."""

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
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise SaoOperationalAuthorizationError(f"SAO mini-smoke claim mismatch: {field}")
    if value.get("claim_identity_sha256") != _claim_identity(value):
        raise SaoOperationalAuthorizationError("SAO mini-smoke claim identity mismatch")
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
    return "\n".join(lines[start:end])


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

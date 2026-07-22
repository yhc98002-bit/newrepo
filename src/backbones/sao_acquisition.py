"""No-clobber, token-hygienic Stable Audio Open snapshot acquisition.

The provider token is accepted only through the configured environment
variable, removed from that environment before the first provider call, passed
explicitly in memory, and never included in returned or persisted records.
Importing this module performs no network access and writes nothing.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
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
    match = re.search(
        rf"(?ms)^## {re.escape(decision_id)}\b.*?(?=^## D-\d+\b|\Z)",
        text,
    )
    if match is None:
        raise SaoAcquisitionError(f"required decision is absent: {decision_id}")
    return match.group(0)


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
    rows: list[dict[str, Any]] = []
    for path in sorted(snapshot.rglob("*")):
        if path.is_symlink():
            raise SaoAcquisitionError(
                f"provider snapshot contains a forbidden symlink: {path.relative_to(snapshot)}"
            )
        if path.is_file():
            rows.append(
                {
                    "path": path.relative_to(snapshot).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    if not rows:
        raise SaoAcquisitionError("downloaded SAO snapshot is empty")
    return rows


def _tree_sha256(files: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical({"files": files})).hexdigest()


def _validate_download(snapshot: Path) -> tuple[list[dict[str, Any]], Path]:
    control_cache = snapshot / ".cache" / "huggingface"
    if control_cache.exists():
        shutil.rmtree(control_cache)
        cache_parent = snapshot / ".cache"
        if cache_parent.exists() and not any(cache_parent.iterdir()):
            cache_parent.rmdir()
    if not (snapshot / "model_config.json").is_file():
        raise SaoAcquisitionError("downloaded snapshot lacks model_config.json")
    weights = [
        path
        for path in (snapshot / "model.safetensors", snapshot / "model.ckpt")
        if path.is_file()
    ]
    if len(weights) != 1:
        raise SaoAcquisitionError(
            "downloaded snapshot must contain exactly one supported model weight file"
        )
    licenses = [snapshot / name for name in LICENSE_CANDIDATES if (snapshot / name).is_file()]
    if len(licenses) != 1:
        raise SaoAcquisitionError("downloaded snapshot lacks one unambiguous license text file")
    return _snapshot_files(snapshot), licenses[0]


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

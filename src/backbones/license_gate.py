"""Offline validation for the Stable Audio Open human license/access gate."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from backbones.contracts import (
    REVISION_RE,
    SHA256_RE,
    BackboneConfigurationError,
    LicenseGateBlocked,
    sha256_file,
    strict_json_object,
)
from backbones.io import verify_checkpoint_files

_SECRET_KEY_RE = re.compile(r"token|secret|password|credential|authorization", re.IGNORECASE)


def license_block_from_config(config: dict[str, Any]) -> LicenseGateBlocked:
    """Materialize the committed fail-closed blocker without touching a provider."""

    gate = config.get("license_gate")
    if not isinstance(gate, dict):
        raise BackboneConfigurationError("BLOCKED_ON_LICENSE config lacks license_gate")
    reason = gate.get("blocker")
    steps = gate.get("human_steps")
    if not isinstance(reason, str) or not reason.strip():
        raise BackboneConfigurationError("license blocker must be a non-empty string")
    if (
        not isinstance(steps, list)
        or not steps
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise BackboneConfigurationError("license human_steps must be a non-empty string list")
    return LicenseGateBlocked(model_id=config["model_id"], reason=reason, human_steps=steps)


def _reject_secret_fields(value: Any, *, location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                raise BackboneConfigurationError(
                    f"secret-like field {key!r} is forbidden in {location}"
                )
            _reject_secret_fields(nested, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_fields(nested, location=f"{location}[{index}]")


def _utc_timestamp(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise BackboneConfigurationError(f"{key} must be a non-empty UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackboneConfigurationError(f"{key} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackboneConfigurationError(f"{key} must include a UTC offset")
    if parsed.utcoffset().total_seconds() != 0:
        raise BackboneConfigurationError(f"{key} must be UTC")
    return value


def validate_access_receipt(
    receipt_path: str | Path,
    *,
    expected_model_id: str,
    expected_snapshot_dir: str | Path,
) -> dict[str, Any]:
    """Validate non-secret acceptance metadata and every local snapshot file.

    The snapshot manifest is resolved relative to the receipt unless absolute.
    It must bind the same model/revision and list exact file sizes and hashes.
    """

    receipt_file = Path(receipt_path).resolve()
    receipt = strict_json_object(receipt_file)
    _reject_secret_fields(receipt)
    required = {
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
    }
    missing = sorted(required.difference(receipt))
    if missing:
        raise BackboneConfigurationError(f"access receipt is missing fields: {missing}")
    unexpected = sorted(set(receipt).difference(required))
    if unexpected:
        raise BackboneConfigurationError(f"access receipt has unexpected fields: {unexpected}")
    if receipt["schema_version"] != 1 or receipt["model_id"] != expected_model_id:
        raise BackboneConfigurationError("access receipt schema/model identity mismatch")
    revision = receipt["resolved_provider_revision"]
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise BackboneConfigurationError("resolved provider revision must be 40 lowercase hex")
    if receipt["user_confirmed_acceptance"] is not True:
        raise BackboneConfigurationError("access receipt lacks explicit human acceptance")
    for key in ("accepted_by", "license_identifier"):
        if not isinstance(receipt[key], str) or not receipt[key].strip():
            raise BackboneConfigurationError(f"{key} must be a non-empty string")
    _utc_timestamp(receipt["accepted_at_utc"], "accepted_at_utc")
    for key in ("license_text_sha256", "snapshot_manifest_sha256"):
        if not isinstance(receipt[key], str) or not SHA256_RE.fullmatch(receipt[key]):
            raise BackboneConfigurationError(f"{key} must be 64 lowercase hex")

    manifest_value = receipt["snapshot_manifest_path"]
    if not isinstance(manifest_value, str) or not manifest_value:
        raise BackboneConfigurationError("snapshot_manifest_path must be non-empty")
    manifest_path = Path(manifest_value)
    if not manifest_path.is_absolute():
        manifest_path = receipt_file.parent / manifest_path
    manifest_path = manifest_path.resolve()
    if sha256_file(manifest_path) != receipt["snapshot_manifest_sha256"]:
        raise BackboneConfigurationError("snapshot manifest SHA-256 does not match receipt")
    manifest = strict_json_object(manifest_path)
    _reject_secret_fields(manifest, location="snapshot_manifest")
    if manifest.get("model_id") != expected_model_id or manifest.get("revision") != revision:
        raise BackboneConfigurationError("snapshot manifest model/revision mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise BackboneConfigurationError("snapshot manifest must list at least one file")
    observed = verify_checkpoint_files(expected_snapshot_dir, files, hash_files=True)
    return {
        "receipt_path": str(receipt_file),
        "receipt_sha256": sha256_file(receipt_file),
        "snapshot_manifest_path": str(manifest_path),
        "snapshot_manifest_sha256": receipt["snapshot_manifest_sha256"],
        "resolved_provider_revision": revision,
        "license_identifier": receipt["license_identifier"],
        "verified_files": observed,
    }


def validate_runtime_authorization(
    authorization_path: str | Path,
    *,
    expected_config_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str, Any]:
    """Require a later append-only decision record before SAO generation can run."""

    record = strict_json_object(authorization_path)
    _reject_secret_fields(record, location="runtime_authorization")
    required = {
        "schema_version",
        "status",
        "decision_id",
        "backbone_config_sha256",
        "access_receipt_sha256",
        "max_generations",
        "max_clip_seconds",
        "max_gpus",
    }
    missing = sorted(required.difference(record))
    if missing:
        raise BackboneConfigurationError(f"runtime authorization is missing fields: {missing}")
    unexpected = sorted(set(record).difference(required))
    if unexpected:
        raise BackboneConfigurationError(
            f"runtime authorization has unexpected fields: {unexpected}"
        )
    if record["schema_version"] != 1:
        raise BackboneConfigurationError("runtime authorization schema_version must equal 1")
    if record["status"] != "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED":
        raise BackboneConfigurationError("runtime authorization status is not executable")
    if record["backbone_config_sha256"] != expected_config_sha256:
        raise BackboneConfigurationError("runtime authorization config hash mismatch")
    if record["access_receipt_sha256"] != expected_receipt_sha256:
        raise BackboneConfigurationError("runtime authorization receipt hash mismatch")
    if record["max_gpus"] != 1 or record["max_clip_seconds"] > 30:
        raise BackboneConfigurationError("runtime authorization exceeds B2 GPU/clip caps")
    generations = record["max_generations"]
    if (
        isinstance(generations, bool)
        or not isinstance(generations, int)
        or not 1 <= generations <= 10
    ):
        raise BackboneConfigurationError("runtime authorization generation cap must be in [1, 10]")
    if not isinstance(record["decision_id"], str) or not record["decision_id"].strip():
        raise BackboneConfigurationError("runtime authorization decision_id must be non-empty")
    return record

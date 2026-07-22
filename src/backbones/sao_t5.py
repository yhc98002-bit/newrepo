"""Deterministic receipt identity for the offline SAO T5 conditioning bundle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from backbones.contracts import SHA256_RE, BackboneConfigurationError

T5_MODEL_NAME = "t5-base"
T5_BUNDLE_LAYOUT = (
    ("config.json", "text_encoder/config.json"),
    ("model.safetensors", "text_encoder/model.safetensors"),
    ("special_tokens_map.json", "tokenizer/special_tokens_map.json"),
    ("spiece.model", "tokenizer/spiece.model"),
    ("tokenizer.json", "tokenizer/tokenizer.json"),
    ("tokenizer_config.json", "tokenizer/tokenizer_config.json"),
)


def conditioning_bundle_record(
    verified_files: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the exact path/hash mapping and its path-independent identity."""

    files: list[dict[str, Any]] = []
    for bundle_path, snapshot_path in T5_BUNDLE_LAYOUT:
        matches = [row for row in verified_files if row.get("path") == snapshot_path]
        if len(matches) != 1:
            raise BackboneConfigurationError(
                f"SAO receipt does not uniquely bind T5 file: {snapshot_path}"
            )
        row = matches[0]
        size = row.get("size_bytes")
        digest = row.get("sha256")
        if (
            row.get("hash_verified") is not True
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
        ):
            raise BackboneConfigurationError(
                f"SAO receipt T5 file is not hash-verified: {snapshot_path}"
            )
        files.append(
            {
                "bundle_path": bundle_path,
                "snapshot_path": snapshot_path,
                "size_bytes": size,
                "sha256": digest,
            }
        )
    payload = {
        "schema_version": 1,
        "t5_model_name": T5_MODEL_NAME,
        "files": files,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {**payload, "conditioning_bundle_sha256": digest}

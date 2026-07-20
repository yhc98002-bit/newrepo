#!/usr/bin/env python3
"""Strictly validate a PI timing-pilot response and write an immutable receipt."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rater.bundle_common import (
    freeze_private_tree,
    load_json_strict,
    require_exact_keys,
    sha256_file,
    write_json_exclusive,
)

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE / "schema_v2.json"

ITEM_KEYS = {
    "completed_full_playback",
    "elapsed_seconds",
    "item_id",
    "play_events",
    "playback_coverage_seconds",
    "response",
    "taps_seconds",
    "task",
}
TOP_LEVEL_KEYS = {
    "build_identity_sha256",
    "bundle_id",
    "completed_at_utc",
    "responses",
    "schema_version",
    "session_elapsed_seconds",
    "status",
    "user_agent",
}
ATTESTATION_KEYS = {
    "actual_minutes",
    "affirmation",
    "attestation_schema_version",
    "build_identity_sha256",
    "bundle_id",
    "pi_identity",
    "protocol_deviations",
    "response_sha256",
    "signature",
    "signed_at_utc",
    "usability_status",
}
DEFECT_LABELS = frozenset({"clipping", "dropout", "silence", "crackle"})
VOICE_LABELS = frozenset({"present", "absent", "unsure"})


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{context} must be a finite number")
    return number


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def _validate_completed_at(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("completed_at_utc must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("completed_at_utc must be an ISO-8601 UTC string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("completed_at_utc must include UTC timezone")


def _validate_bundle(bundle: Any) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict):
        raise ValueError("offered bundle must be an object")
    require_exact_keys(
        bundle,
        {
            "build_identity_sha256",
            "bundle_id",
            "expected_minutes",
            "items",
            "purpose",
            "response_schema_version",
            "schema_version",
        },
        "offered bundle",
    )
    if bundle["schema_version"] != 2 or bundle["response_schema_version"] != 2:
        raise ValueError("offered bundle schema must be v2")
    if bundle["purpose"] != "BLINDED_TIMING_PILOT":
        raise ValueError("ingestion accepts only the timing-pilot bundle")
    if not isinstance(bundle["bundle_id"], str) or not bundle["bundle_id"]:
        raise ValueError("offered bundle has invalid bundle_id")
    if bundle["expected_minutes"] != 15 or isinstance(bundle["expected_minutes"], bool):
        raise ValueError("offered bundle expected_minutes must be exactly 15")
    digest = bundle["build_identity_sha256"]
    if not _valid_sha256(digest):
        raise ValueError("offered bundle has invalid build identity")
    items = bundle["items"]
    if not isinstance(items, list) or not 8 <= len(items) <= 10:
        raise ValueError("offered bundle must contain 8--10 items")
    ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"bundle item {index} must be an object")
        require_exact_keys(item, {"audio", "item_id", "task"}, f"bundle item {index}")
        item_id = item["item_id"]
        if not isinstance(item_id, str) or not item_id or item_id in ids:
            raise ValueError("bundle item IDs must be unique nonempty strings")
        ids.add(item_id)
        if item["task"] not in {"tempo_tap", "voice_stress", "integrity_audit"}:
            raise ValueError(f"bundle item {item_id} has invalid task")
        audio = item["audio"]
        if (
            not isinstance(audio, str)
            or not audio.startswith("audio/")
            or Path(audio).is_absolute()
            or ".." in Path(audio).parts
        ):
            raise ValueError(f"bundle item {item_id} has unsafe audio path")
    return items


def _validate_taps(row: dict[str, Any]) -> None:
    raw_taps = row["taps_seconds"]
    if not isinstance(raw_taps, list):
        raise ValueError("taps_seconds must be a list")
    taps = [_finite_number(value, "tap time") for value in raw_taps]
    if taps != sorted(taps):
        raise ValueError("taps_seconds must be monotonically nondecreasing")
    if row["task"] != "tempo_tap":
        if taps:
            raise ValueError("non-tempo response must have no taps")
        return
    first = [value for value in taps if 2.0 <= value <= 14.0]
    second = [value for value in taps if 16.0 <= value <= 28.0]
    if len(first) + len(second) != len(taps):
        raise ValueError("every tempo tap must lie in a frozen tap window")
    if len(first) < 8 or len(second) < 8:
        raise ValueError("tempo response requires at least eight taps in each window")
    response = row["response"]
    if not isinstance(response, dict):
        raise ValueError("tempo response must be an object")
    require_exact_keys(
        response,
        {"first_window_tap_count", "second_window_tap_count"},
        "tempo response",
    )
    first_count = _integer(response["first_window_tap_count"], "first-window tap count")
    second_count = _integer(response["second_window_tap_count"], "second-window tap count")
    if first_count != len(first) or second_count != len(second):
        raise ValueError("declared tap counts do not match taps_seconds")


def _validate_task_response(row: dict[str, Any]) -> None:
    task = row["task"]
    if task == "tempo_tap":
        _validate_taps(row)
        return
    _validate_taps(row)
    if task == "voice_stress":
        if row["response"] not in VOICE_LABELS:
            raise ValueError("voice response is outside the frozen labels")
        return
    response = row["response"]
    if not isinstance(response, dict):
        raise ValueError("integrity response must be an object")
    require_exact_keys(
        response,
        {"defect_labels", "intentional_musical_content"},
        "integrity response",
    )
    labels_value = response["defect_labels"]
    if not isinstance(labels_value, list) or not labels_value:
        raise ValueError("integrity defect_labels must be a nonempty label list")
    if any(not isinstance(label, str) for label in labels_value) or len(set(labels_value)) != len(
        labels_value
    ):
        raise ValueError("integrity labels must be unique strings")
    intentional = response["intentional_musical_content"]
    if not isinstance(intentional, bool):
        raise ValueError("intentional_musical_content must be boolean")
    labels = set(labels_value)
    if labels == {"clean"} or labels == {"unsure"}:
        return
    if not labels <= DEFECT_LABELS:
        raise ValueError("integrity response must be clean, unsure, or defect labels only")


def _validate_attestation(
    bundle: dict[str, Any],
    response_path: Path,
    response: dict[str, Any],
    attestation: Any,
    schema: Any,
) -> dict[str, Any]:
    if not isinstance(attestation, dict):
        raise ValueError("PI timing-pilot attestation must be an object")
    require_exact_keys(attestation, ATTESTATION_KEYS, "PI timing-pilot attestation")
    if attestation["attestation_schema_version"] != 1:
        raise ValueError("PI attestation schema_version must be 1")
    if not isinstance(schema, dict) or not isinstance(schema.get("timing_pilot"), dict):
        raise ValueError("rater schema lacks timing_pilot attestation rules")
    rules = schema["timing_pilot"]
    required_identity = rules.get("required_pi_identity")
    required_affirmation = rules.get("attestation_affirmation")
    if attestation["pi_identity"] != required_identity:
        raise ValueError("PI attestation identity does not match the frozen rater schema")
    if attestation["signature"] != required_identity:
        raise ValueError("PI attestation signature does not match the required identity")
    if attestation["affirmation"] != required_affirmation:
        raise ValueError("PI attestation affirmation is absent or incorrect")
    _validate_completed_at(attestation["signed_at_utc"])
    if attestation["bundle_id"] != bundle["bundle_id"]:
        raise ValueError("PI attestation bundle_id mismatch")
    if attestation["build_identity_sha256"] != bundle["build_identity_sha256"]:
        raise ValueError("PI attestation build identity mismatch")
    response_hash = sha256_file(response_path)
    if attestation["response_sha256"] != response_hash:
        raise ValueError("PI attestation is not bound to the exact response")
    if attestation["usability_status"] != "PASS":
        raise ValueError("PI attestation does not mark the timing pilot usable")
    deviations = attestation["protocol_deviations"]
    if not isinstance(deviations, list) or any(
        not isinstance(value, str) or not value for value in deviations
    ):
        raise ValueError("PI attestation deviations must be a list of nonempty strings")
    if deviations:
        raise ValueError("PI attestation records protocol deviations")
    actual_minutes = _finite_number(attestation["actual_minutes"], "actual_minutes")
    response_minutes = (
        _finite_number(response["session_elapsed_seconds"], "session_elapsed_seconds") / 60.0
    )
    if actual_minutes <= 0.0 or not math.isclose(
        actual_minutes, response_minutes, rel_tol=0.0, abs_tol=1e-9
    ):
        raise ValueError("PI-attested actual minutes disagree with the response timer")
    return attestation


def _validate_response(bundle: dict[str, Any], response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        raise ValueError("response must be an object")
    require_exact_keys(response, TOP_LEVEL_KEYS, "timing-pilot response")
    if response["schema_version"] != 2:
        raise ValueError("response schema_version must be 2")
    if response["status"] != "COMPLETE":
        raise ValueError("only a COMPLETE timing-pilot response can be ingested")
    if response["bundle_id"] != bundle["bundle_id"]:
        raise ValueError("response bundle_id does not match offered bundle")
    if response["build_identity_sha256"] != bundle["build_identity_sha256"]:
        raise ValueError("response build identity does not match offered bundle")
    _validate_completed_at(response["completed_at_utc"])
    if not isinstance(response["user_agent"], str) or not 1 <= len(response["user_agent"]) <= 4096:
        raise ValueError("user_agent must be a nonempty bounded string")

    expected_items = bundle["items"]
    observed = response["responses"]
    if not isinstance(observed, list) or len(observed) != len(expected_items):
        raise ValueError("response must contain every item exactly once in packet order")
    item_elapsed_total = 0.0
    for index, (item, row) in enumerate(zip(expected_items, observed, strict=True)):
        if not isinstance(row, dict):
            raise ValueError(f"response row {index} must be an object")
        require_exact_keys(row, ITEM_KEYS, f"response row {index}")
        if row["item_id"] != item["item_id"] or row["task"] != item["task"]:
            raise ValueError("response must contain every item exactly once in packet order")
        if row["completed_full_playback"] is not True:
            raise ValueError("every response requires completed_full_playback=true")
        coverage = _finite_number(row["playback_coverage_seconds"], "playback coverage")
        elapsed = _finite_number(row["elapsed_seconds"], "elapsed_seconds")
        if not 29.5 <= coverage <= 30.5:
            raise ValueError("every item requires essentially full 30-second playback coverage")
        if elapsed < 29.5 or elapsed + 0.25 < coverage:
            raise ValueError("elapsed_seconds is incompatible with full playback")
        item_elapsed_total += elapsed
        _integer(row["play_events"], "play_events", minimum=1)
        _validate_task_response(row)
    session_elapsed = _finite_number(response["session_elapsed_seconds"], "session_elapsed_seconds")
    if session_elapsed + 0.25 < item_elapsed_total:
        raise ValueError("session_elapsed_seconds cannot be shorter than item elapsed time")
    return observed


def ingest(
    bundle_dir: Path,
    response_path: Path,
    receipt_dir: Path,
    *,
    attestation_path: Path | None,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    response_path = response_path.resolve()
    bundle_path = bundle_dir / "bundle.json"
    bundle = load_json_strict(bundle_path)
    response = load_json_strict(response_path)
    if attestation_path is None or not attestation_path.is_file():
        raise ValueError("a signed PI timing-pilot attestation is required")
    attestation_path = attestation_path.resolve()
    attestation = load_json_strict(attestation_path)
    schema = load_json_strict(schema_path.resolve())
    items = _validate_bundle(bundle)
    observed = _validate_response(bundle, response)
    signed = _validate_attestation(bundle, response_path, response, attestation, schema)
    session_elapsed = _finite_number(response["session_elapsed_seconds"], "session_elapsed_seconds")

    receipt = {
        "attestation_schema_version": signed["attestation_schema_version"],
        "attestation_sha256": sha256_file(attestation_path),
        "build_identity_sha256": bundle["build_identity_sha256"],
        "bundle_id": bundle["bundle_id"],
        "bundle_json_sha256": sha256_file(bundle_path),
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "item_count": len(observed),
        "pi_affirmation": signed["affirmation"],
        "pi_identity": signed["pi_identity"],
        "pi_signature": signed["signature"],
        "protocol_deviations": signed["protocol_deviations"],
        "receipt_schema_version": 2,
        "response_schema_version": response["schema_version"],
        "response_sha256": sha256_file(response_path),
        "session_elapsed_seconds": session_elapsed,
        "status": "TIMING_PILOT_INGESTED",
        "signed_at_utc": signed["signed_at_utc"],
        "task_counts": {
            task: sum(item["task"] == task for item in items)
            for task in ("integrity_audit", "tempo_tap", "voice_stress")
        },
        "total_minutes": session_elapsed / 60.0,
        "usability_status": signed["usability_status"],
    }
    receipt_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json_exclusive(receipt_dir / "receipt.json", receipt, mode=0o400)
    freeze_private_tree(receipt_dir)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("response", type=Path)
    parser.add_argument("receipt_dir", type=Path)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()
    print(
        json.dumps(
            ingest(
                args.bundle_dir,
                args.response,
                args.receipt_dir,
                attestation_path=args.attestation,
                schema_path=args.schema,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Gate, deterministically select, and assemble the future human-audit packet.

Running this module without a candidate index is a read-only gate check.  Packet
assembly requires a strict timing-pilot receipt and explicit no-clobber public
and private output roots.  Human labels are never inputs to selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import soundfile as sf

from audio_duration_policy import duration_within_tolerance
from instruments.integrity import (
    DropoutCandidateMetrics,
    score_integrity_raw_metrics,
)
from instruments.voice import load_promoted_or_from_manifest, score_promoted_or_raw
from rater.bundle_common import (
    freeze_private_tree,
    freeze_public_tree,
    load_json_strict,
    render_bundle_html,
    require_exact_keys,
    sha256_file,
    sha256_json,
    write_json_exclusive,
)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_SCHEMA = HERE / "schema_v2.json"
DEFAULT_TEMPLATE = HERE / "timing_pilot.html"
VOICE_SOURCE_MANIFEST = REPO_ROOT / "provenance" / "b1" / "voice_source_manifest.json"
VOICE_CONFIG = load_promoted_or_from_manifest(VOICE_SOURCE_MANIFEST)
AXIS_TO_TASK = {
    "integrity": "integrity_audit",
    "tempo": "tempo_tap",
    "voice": "voice_stress",
}
CONDITIONS = frozenset({"BASE", "FIXED", "NEGATION_DIAGNOSTIC"})
DEFECTS = ("clipping", "dropout", "silence", "crackle")
TEMPO_THRESHOLD = math.log2(1.05)
PACKET_AUDIO_REQUESTED_SECONDS = 30.0
PACKET_AUDIO_DURATION_TOLERANCE_SECONDS = 0.25
CANDIDATE_INDEX_KEYS = {
    "primary_backbones",
    "rows",
    "schema_version",
    "source_ledger_sha256",
}
CANDIDATE_ROW_KEYS = {
    "audio_path",
    "audio_sha256",
    "axis",
    "backbone",
    "cluster_id",
    "condition",
    "defects",
    "demucs_vocal_energy_ratio",
    "demucs_present",
    "integrity_raw",
    "integrity_profile",
    "mixture_rms",
    "panns_max_vocal_probability",
    "panns_present",
    "prompt_id",
    "request",
    "row_id",
    "salience",
    "seed_index",
    "target_bpm",
    "tempo_e_oct",
    "tempo_primary_pass",
    "tempo_status",
    "voice_margin",
    "voice_present",
}
INTEGRITY_RAW_KEYS = {
    "all_sample_rms",
    "dropout_candidates",
    "hard_clipped_fraction",
    "longest_hard_clip_run_samples",
    "maximum_channel_crackle_count",
    "silent_frame_fraction",
    "true_peak",
}
DROPOUT_CANDIDATE_KEYS = {
    "duration_ms",
    "left_boundary_ms",
    "left_level_dbfs",
    "low_level_dbfs",
    "right_boundary_ms",
    "right_level_dbfs",
}
RECEIPT_KEYS = {
    "attestation_schema_version",
    "attestation_sha256",
    "build_identity_sha256",
    "bundle_id",
    "bundle_json_sha256",
    "ingested_at_utc",
    "item_count",
    "pi_affirmation",
    "pi_identity",
    "pi_signature",
    "protocol_deviations",
    "receipt_schema_version",
    "response_schema_version",
    "response_sha256",
    "session_elapsed_seconds",
    "signed_at_utc",
    "status",
    "task_counts",
    "total_minutes",
    "usability_status",
}


def _finite(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be a finite number")
    return result


def _valid_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _stable_digest(namespace: str, *parts: object) -> str:
    payload = "|".join((namespace, *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rotate(values: list[str], namespace: str, *parts: object) -> list[str]:
    offset = int(_stable_digest(namespace, *parts)[:16], 16) % len(values)
    return values[offset:] + values[:offset]


def _validate_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict) or schema.get("schema_version") != 2:
        raise ValueError("rater schema must be a schema-v2 object")
    packet = schema.get("human_packet")
    if not isinstance(packet, dict):
        raise ValueError("rater schema lacks human_packet")
    backbones = packet.get("primary_backbones")
    if (
        not isinstance(backbones, list)
        or len(backbones) != packet.get("primary_backbone_count")
        or len(set(backbones)) != len(backbones)
        or any(not isinstance(value, str) or not value for value in backbones)
    ):
        raise ValueError("human_packet primary_backbones is invalid")
    return packet


def _validate_defects(value: Any, context: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} defects must be an object")
    require_exact_keys(value, set(DEFECTS), f"{context} defects")
    for defect in DEFECTS:
        entry = value[defect]
        if not isinstance(entry, dict):
            raise ValueError(f"{context} {defect} must be an object")
        require_exact_keys(entry, {"flag", "margin"}, f"{context} {defect}")
        if not isinstance(entry["flag"], bool):
            raise ValueError(f"{context} {defect}.flag must be boolean")
        _finite(entry["margin"], f"{context} {defect}.margin")
    return value


def _validate_integrity_raw(value: Any, context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{context}.integrity_raw must be an object")
    require_exact_keys(value, INTEGRITY_RAW_KEYS, f"{context}.integrity_raw")
    nonnegative_float_fields = (
        "all_sample_rms",
        "hard_clipped_fraction",
        "silent_frame_fraction",
        "true_peak",
    )
    parsed: dict[str, Any] = {}
    for field in nonnegative_float_fields:
        number = _finite(value[field], f"{context}.integrity_raw.{field}")
        if number < 0.0:
            raise ValueError(f"{context}.integrity_raw.{field} must be nonnegative")
        parsed[field] = number
    for field in (
        "longest_hard_clip_run_samples",
        "maximum_channel_crackle_count",
    ):
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ValueError(f"{context}.integrity_raw.{field} must be a nonnegative integer")
        parsed[field] = number
    raw_candidates = value["dropout_candidates"]
    if not isinstance(raw_candidates, list):
        raise ValueError(f"{context}.integrity_raw.dropout_candidates must be a list")
    candidates: list[DropoutCandidateMetrics] = []
    for candidate_index, candidate in enumerate(raw_candidates):
        candidate_context = f"{context}.integrity_raw.dropout_candidates[{candidate_index}]"
        if not isinstance(candidate, dict):
            raise ValueError(f"{candidate_context} must be an object")
        require_exact_keys(candidate, DROPOUT_CANDIDATE_KEYS, candidate_context)
        parsed_candidate = {
            field: _finite(candidate[field], f"{candidate_context}.{field}")
            for field in DROPOUT_CANDIDATE_KEYS
        }
        for field in ("duration_ms", "left_boundary_ms", "right_boundary_ms"):
            if parsed_candidate[field] < 0.0:
                raise ValueError(f"{candidate_context}.{field} must be nonnegative")
        candidates.append(DropoutCandidateMetrics(**parsed_candidate))
    parsed["dropout_candidates"] = candidates
    return parsed, score_integrity_raw_metrics(**parsed)


def _validate_candidate_row(row: Any, index: int, backbones: set[str]) -> dict[str, Any]:
    context = f"candidate row {index}"
    if not isinstance(row, dict):
        raise ValueError(f"{context} must be an object")
    require_exact_keys(row, CANDIDATE_ROW_KEYS, context)
    for key in ("audio_path", "backbone", "cluster_id", "prompt_id", "row_id"):
        if not isinstance(row[key], str) or not row[key]:
            raise ValueError(f"{context}.{key} must be a nonempty string")
    if row["backbone"] not in backbones:
        raise ValueError(f"{context} uses an unregistered backbone")
    if not _valid_sha(row["audio_sha256"]):
        raise ValueError(f"{context}.audio_sha256 must be lowercase SHA-256")
    if row["axis"] not in AXIS_TO_TASK:
        raise ValueError(f"{context}.axis is invalid")
    if row["condition"] not in CONDITIONS:
        raise ValueError(f"{context}.condition is invalid")
    seed = row["seed_index"]
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"{context}.seed_index must be a nonnegative integer")

    axis = row["axis"]
    if axis == "voice":
        if row["request"] not in {"vocal", "instrumental"}:
            raise ValueError(f"{context}.request is invalid for voice")
        if row["request"] == "vocal" and row["condition"] == "NEGATION_DIAGNOSTIC":
            raise ValueError("vocal rows cannot use NEGATION_DIAGNOSTIC")
        raw_voice = {
            "mixture_rms": _finite(row["mixture_rms"], f"{context}.mixture_rms"),
            "demucs_vocal_energy_ratio": _finite(
                row["demucs_vocal_energy_ratio"],
                f"{context}.demucs_vocal_energy_ratio",
            ),
            "panns_max_vocal_probability": _finite(
                row["panns_max_vocal_probability"],
                f"{context}.panns_max_vocal_probability",
            ),
        }
        if raw_voice["mixture_rms"] < 0.0 or raw_voice["demucs_vocal_energy_ratio"] < 0.0:
            raise ValueError(f"{context} voice raw levels must be nonnegative")
        if not 0.0 <= raw_voice["panns_max_vocal_probability"] <= 1.0:
            raise ValueError(f"{context}.panns_max_vocal_probability must be in [0, 1]")
        supplied_margin = _finite(row["voice_margin"], f"{context}.voice_margin")
        recomputed = score_promoted_or_raw(VOICE_CONFIG, **raw_voice)
        for key in ("demucs_present", "panns_present", "voice_present"):
            if not isinstance(row[key], bool):
                raise ValueError(f"{context}.{key} must be boolean")
            if row[key] is not getattr(recomputed, key):
                raise ValueError(f"{context}.{key} disagrees with canonical raw recomputation")
        if not math.isclose(
            supplied_margin,
            recomputed.voice_margin,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(f"{context}.voice_margin disagrees with canonical raw recomputation")
        for key in (
            "defects",
            "integrity_raw",
            "integrity_profile",
            "salience",
            "target_bpm",
            "tempo_e_oct",
            "tempo_primary_pass",
            "tempo_status",
        ):
            if row[key] is not None:
                raise ValueError(f"{context}.{key} must be null for voice")
    elif axis == "tempo":
        if row["condition"] not in {"BASE", "FIXED"} or row["request"] is not None:
            raise ValueError(f"{context} has invalid tempo request/condition")
        if row["tempo_status"] not in {
            "RESOLVED",
            "ESTIMATOR_DISAGREEMENT",
            "ESTIMATOR_INVALID",
        }:
            raise ValueError(f"{context}.tempo_status is invalid")
        if row["salience"] not in {
            "legato_light_percussion",
            "percussive_regular",
            "syncopated",
        }:
            raise ValueError(f"{context}.salience is invalid")
        target = _finite(row["target_bpm"], f"{context}.target_bpm")
        if target <= 0:
            raise ValueError(f"{context}.target_bpm must be positive")
        if row["tempo_status"] == "RESOLVED":
            error = _finite(row["tempo_e_oct"], f"{context}.tempo_e_oct")
            if error < 0 or not isinstance(row["tempo_primary_pass"], bool):
                raise ValueError(f"{context} has invalid resolved tempo result")
            if row["tempo_primary_pass"] != (error <= TEMPO_THRESHOLD):
                raise ValueError(f"{context} tempo pass is inconsistent with frozen 5% rule")
        elif row["tempo_e_oct"] is not None or row["tempo_primary_pass"] is not None:
            raise ValueError(f"{context} unresolved tempo values must be null")
        for key in (
            "defects",
            "demucs_vocal_energy_ratio",
            "demucs_present",
            "integrity_raw",
            "integrity_profile",
            "mixture_rms",
            "panns_max_vocal_probability",
            "panns_present",
            "voice_margin",
            "voice_present",
        ):
            if row[key] is not None:
                raise ValueError(f"{context}.{key} must be null for tempo")
    else:
        if row["condition"] not in {"BASE", "FIXED"} or row["request"] is not None:
            raise ValueError(f"{context} has invalid integrity request/condition")
        if row["integrity_profile"] not in {
            "soft_sustained",
            "sharp_percussive_control",
            "dense_loud",
        }:
            raise ValueError(f"{context}.integrity_profile is invalid")
        defects = _validate_defects(row["defects"], context)
        _, recomputed = _validate_integrity_raw(row["integrity_raw"], context)
        for defect in DEFECTS:
            supplied = defects[defect]
            expected = recomputed["defects"][defect]
            if supplied["flag"] is not expected["flag"]:
                raise ValueError(f"{context} {defect}.flag disagrees with raw DSP recomputation")
            if not math.isclose(
                float(supplied["margin"]),
                float(expected["margin"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError(f"{context} {defect}.margin disagrees with raw DSP recomputation")
        for key in (
            "demucs_vocal_energy_ratio",
            "demucs_present",
            "mixture_rms",
            "panns_max_vocal_probability",
            "panns_present",
            "salience",
            "target_bpm",
            "tempo_e_oct",
            "tempo_primary_pass",
            "tempo_status",
            "voice_margin",
            "voice_present",
        ):
            if row[key] is not None:
                raise ValueError(f"{context}.{key} must be null for integrity")
    return row


def validate_candidate_index(value: Any, schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the strict automatic-only candidate-index transport contract."""

    if not isinstance(value, dict):
        raise ValueError("candidate index must be an object")
    require_exact_keys(value, CANDIDATE_INDEX_KEYS, "candidate index")
    if value["schema_version"] != 2 or not _valid_sha(value["source_ledger_sha256"]):
        raise ValueError("candidate index identity is invalid")
    packet = _validate_schema(schema)
    if value["primary_backbones"] != packet["primary_backbones"]:
        raise ValueError("candidate index primary_backbones differ from the frozen schema")
    raw_rows = value["rows"]
    if not isinstance(raw_rows, list):
        raise ValueError("candidate index rows must be a list")
    rows = [
        _validate_candidate_row(row, index, set(packet["primary_backbones"]))
        for index, row in enumerate(raw_rows)
    ]
    row_ids = [row["row_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("candidate row IDs must be globally unique")
    return rows


def _condition_order(assigned: str, allowed: list[str], namespace: str) -> list[str]:
    rotated = _rotate(allowed, namespace, "condition-fallback")
    return [assigned, *(value for value in rotated if value != assigned)]


def _pick_row(
    rows: list[dict[str, Any]],
    *,
    assigned_condition: str,
    allowed_conditions: list[str],
    desired: Callable[[dict[str, Any]], bool],
    score: Callable[[dict[str, Any]], tuple[Any, ...]],
    namespace: str,
    used_ids: set[str],
    used_hashes: set[str],
    used_clusters: set[str],
    empty_stratum_fallback: Callable[[dict[str, Any]], bool] | None = None,
    prefer_unused_clusters: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    conditions = _condition_order(assigned_condition, allowed_conditions, namespace)
    for condition_index, condition in enumerate(conditions):
        candidates = [
            row
            for row in rows
            if row["condition"] == condition
            and row["row_id"] not in used_ids
            and row["audio_sha256"] not in used_hashes
            and desired(row)
        ]
        if candidates:

            def ordering(row: dict[str, Any]) -> tuple[Any, ...]:
                cluster_used = row["cluster_id"] in used_clusters
                scored = score(row)
                if prefer_unused_clusters:
                    return (cluster_used, *scored, _stable_digest(namespace, "tie", row["row_id"]))
                return (*scored, cluster_used, _stable_digest(namespace, "tie", row["row_id"]))

            candidates.sort(key=ordering)
            deviation = "NONE"
            if condition_index:
                deviation = f"CONDITION_FALLBACK:{assigned_condition}->{condition}"
            return candidates[0], deviation
    if empty_stratum_fallback is None:
        return None, "STRATUM_EMPTY"
    for condition_index, condition in enumerate(conditions):
        candidates = [
            row
            for row in rows
            if row["condition"] == condition
            and row["row_id"] not in used_ids
            and row["audio_sha256"] not in used_hashes
            and empty_stratum_fallback(row)
        ]
        if candidates:

            def fallback_ordering(row: dict[str, Any]) -> tuple[Any, ...]:
                cluster_used = row["cluster_id"] in used_clusters
                scored = score(row)
                digest = _stable_digest(namespace, "empty-stratum-tie", row["row_id"])
                return (
                    (cluster_used, *scored, digest)
                    if prefer_unused_clusters
                    else (*scored, cluster_used, digest)
                )

            candidates.sort(key=fallback_ordering)
            actual = candidates[0]["condition"]
            suffix = "" if condition_index == 0 else f":{assigned_condition}->{actual}"
            return candidates[0], f"EMPTY_STRATUM_NEXT_CLOSEST{suffix}"
    return None, "STRATUM_EMPTY"


def _selection_record(row: dict[str, Any], stratum: str, fallback: str) -> dict[str, Any]:
    return {
        **row,
        "rating_task": AXIS_TO_TASK[row["axis"]],
        "selector_fallback": fallback,
        "selector_stratum": stratum,
    }


def _voice_in_stratum(row: dict[str, Any], stratum: str) -> bool:
    if stratum == "boundary":
        return True
    if stratum == "detector_disagreement":
        return bool(row["demucs_present"] != row["panns_present"])
    if stratum == "far_predicted_present":
        return row["voice_present"] is True
    return row["voice_present"] is False


def _voice_metric(row: dict[str, Any], stratum: str) -> tuple[float]:
    magnitude = abs(float(row["voice_margin"]))
    return (magnitude,) if stratum in {"boundary", "detector_disagreement"} else (-magnitude,)


def _tempo_in_stratum(row: dict[str, Any], stratum: str) -> bool:
    if stratum == "boundary":
        return row["tempo_status"] == "RESOLVED"
    if stratum == "disagreement_or_invalid":
        return row["tempo_status"] != "RESOLVED"
    if stratum == "far_pass":
        return row["tempo_status"] == "RESOLVED" and row["tempo_primary_pass"] is True
    return row["tempo_status"] == "RESOLVED" and row["tempo_primary_pass"] is False


def _tempo_metric(row: dict[str, Any], stratum: str) -> tuple[float | int]:
    if stratum == "boundary":
        return (abs(float(row["tempo_e_oct"]) - TEMPO_THRESHOLD),)
    if stratum == "disagreement_or_invalid":
        return (0 if row["tempo_status"] == "ESTIMATOR_DISAGREEMENT" else 1,)
    if stratum == "far_pass":
        return (float(row["tempo_e_oct"]),)
    return (-float(row["tempo_e_oct"]),)


def _integrity_in_stratum(row: dict[str, Any], defect: str, side: str) -> bool:
    if side == "flagged":
        return row["defects"][defect]["flag"] is True
    return (
        not any(row["defects"][name]["flag"] for name in DEFECTS)
        and float(row["defects"][defect]["margin"]) < 0
        and row["integrity_profile"] != "sharp_percussive_control"
    )


def _integrity_metric(row: dict[str, Any], defect: str, side: str) -> tuple[float]:
    margin = float(row["defects"][defect]["margin"])
    return (-margin,) if side == "flagged" else (abs(margin),)


def _select_voice(
    rows: list[dict[str, Any]], backbone: str, namespace: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected: list[dict[str, Any]] = []
    empty: list[dict[str, str]] = []
    used_ids: set[str] = set()
    used_hashes: set[str] = set()
    used_clusters: set[str] = set()
    slots = [
        "boundary",
        "boundary",
        "detector_disagreement",
        "detector_disagreement",
        "far_predicted_present",
        "far_predicted_absent",
    ]
    by_request = [row for row in rows if row["axis"] == "voice" and row["backbone"] == backbone]
    for request, quota in (
        ("vocal", ["BASE"] * 3 + ["FIXED"] * 3),
        (
            "instrumental",
            ["BASE"] * 2 + ["FIXED"] * 2 + ["NEGATION_DIAGNOSTIC"] * 2,
        ),
    ):
        prompt_rotation = sorted(
            {row["prompt_id"] for row in by_request if row["request"] == request}
        )
        slot_conditions = _rotate(
            quota,
            namespace,
            backbone,
            request,
            "prompt-hash-condition-quota",
            *prompt_rotation,
        )
        allowed = sorted(set(quota))
        request_rows = [row for row in by_request if row["request"] == request]
        for slot_index, (stratum, condition) in enumerate(zip(slots, slot_conditions, strict=True)):
            slot_namespace = f"{namespace}|voice|{backbone}|{request}|{slot_index}|{stratum}"
            row, fallback = _pick_row(
                request_rows,
                assigned_condition=condition,
                allowed_conditions=allowed,
                desired=lambda candidate, active=stratum: _voice_in_stratum(candidate, active),
                score=lambda candidate, active=stratum: _voice_metric(candidate, active),
                namespace=slot_namespace,
                used_ids=used_ids,
                used_hashes=used_hashes,
                used_clusters=used_clusters,
                empty_stratum_fallback=lambda candidate, active=request: (
                    candidate["request"] == active
                ),
            )
            full_stratum = f"{request}:{stratum}:{slot_index + 1}"
            if row is None:
                empty.append({"backbone": backbone, "selector_stratum": full_stratum})
                continue
            selected.append(_selection_record(row, full_stratum, fallback))
            used_ids.add(row["row_id"])
            used_hashes.add(row["audio_sha256"])
            used_clusters.add(row["cluster_id"])
    return selected, empty


def _select_tempo(
    rows: list[dict[str, Any]], backbone: str, namespace: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected: list[dict[str, Any]] = []
    empty: list[dict[str, str]] = []
    used_ids: set[str] = set()
    used_hashes: set[str] = set()
    used_clusters: set[str] = set()
    used_targets: Counter[float] = Counter()
    used_salience: Counter[str] = Counter()
    slots = ["boundary"] * 10 + ["disagreement_or_invalid"] * 10
    slots += ["far_pass"] * 5 + ["far_failure"] * 5
    candidates = [row for row in rows if row["axis"] == "tempo" and row["backbone"] == backbone]
    prompt_rotation = sorted({row["prompt_id"] for row in candidates})
    conditions = _rotate(
        ["BASE"] * 15 + ["FIXED"] * 15,
        namespace,
        backbone,
        "tempo-prompt-hash-condition-quota",
        *prompt_rotation,
    )
    for slot_index, (stratum, condition) in enumerate(zip(slots, conditions, strict=True)):

        def score(row: dict[str, Any], active: str = stratum) -> tuple[Any, ...]:
            return (
                used_targets[float(row["target_bpm"])],
                used_salience[str(row["salience"])],
                *_tempo_metric(row, active),
                row["seed_index"],
            )

        slot_namespace = f"{namespace}|tempo|{backbone}|{slot_index}|{stratum}"
        row, fallback = _pick_row(
            candidates,
            assigned_condition=condition,
            allowed_conditions=["BASE", "FIXED"],
            desired=lambda candidate, active=stratum: _tempo_in_stratum(candidate, active),
            score=score,
            namespace=slot_namespace,
            used_ids=used_ids,
            used_hashes=used_hashes,
            used_clusters=used_clusters,
        )
        full_stratum = f"{stratum}:{slot_index + 1}"
        if row is None:
            empty.append({"backbone": backbone, "selector_stratum": full_stratum})
            continue
        selected.append(_selection_record(row, full_stratum, fallback))
        used_ids.add(row["row_id"])
        used_hashes.add(row["audio_sha256"])
        used_clusters.add(row["cluster_id"])
        used_targets[float(row["target_bpm"])] += 1
        used_salience[str(row["salience"])] += 1
    return selected, empty


def _select_integrity(
    rows: list[dict[str, Any]], backbone: str, namespace: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    selected: list[dict[str, Any]] = []
    empty: list[dict[str, str]] = []
    used_ids: set[str] = set()
    used_hashes: set[str] = set()
    used_clusters: set[str] = set()
    candidates = [row for row in rows if row["axis"] == "integrity" and row["backbone"] == backbone]
    for defect in DEFECTS:
        flagged_condition = (
            "BASE"
            if int(_stable_digest(namespace, backbone, defect, "flagged-condition")[:2], 16) % 2
            == 0
            else "FIXED"
        )
        clean_condition = "FIXED" if flagged_condition == "BASE" else "BASE"
        for side, condition in (("flagged", flagged_condition), ("clean_side", clean_condition)):
            stratum = f"{defect}:{side}"
            row, fallback = _pick_row(
                candidates,
                assigned_condition=condition,
                allowed_conditions=[condition],
                desired=lambda candidate, target=defect, active=side: _integrity_in_stratum(
                    candidate, target, active
                ),
                score=lambda candidate, target=defect, active=side: _integrity_metric(
                    candidate, target, active
                ),
                namespace=f"{namespace}|integrity|{backbone}|{stratum}",
                used_ids=used_ids,
                used_hashes=used_hashes,
                used_clusters=used_clusters,
                prefer_unused_clusters=False,
            )
            if row is None:
                empty.append({"backbone": backbone, "selector_stratum": stratum})
                continue
            selected.append(_selection_record(row, stratum, fallback))
            used_ids.add(row["row_id"])
            used_hashes.add(row["audio_sha256"])
            used_clusters.add(row["cluster_id"])

    for condition in ("BASE", "FIXED"):
        stratum = f"sharp_percussive_control:{condition.lower()}"
        row, fallback = _pick_row(
            candidates,
            assigned_condition=condition,
            allowed_conditions=[condition],
            desired=lambda candidate: (
                candidate["integrity_profile"] == "sharp_percussive_control"
                and not any(candidate["defects"][name]["flag"] for name in DEFECTS)
                and float(candidate["defects"]["crackle"]["margin"]) < 0
            ),
            score=lambda candidate: (abs(float(candidate["defects"]["crackle"]["margin"])),),
            namespace=f"{namespace}|integrity|{backbone}|{stratum}",
            used_ids=used_ids,
            used_hashes=used_hashes,
            used_clusters=used_clusters,
            prefer_unused_clusters=False,
        )
        if row is None:
            empty.append({"backbone": backbone, "selector_stratum": stratum})
            continue
        selected.append(_selection_record(row, stratum, fallback))
        used_ids.add(row["row_id"])
        used_hashes.add(row["audio_sha256"])
        used_clusters.add(row["cluster_id"])
    return selected, empty


def select_human_packet(candidate_index: Any, schema: Any) -> dict[str, Any]:
    """Apply every preregistered automatic-only human-audit selector."""

    packet = _validate_schema(schema)
    rows = validate_candidate_index(candidate_index, schema)
    normalized_candidate = {
        **candidate_index,
        "rows": sorted(candidate_index["rows"], key=lambda row: row["row_id"]),
    }
    namespace = str(packet["selector_namespace"])
    selected: list[dict[str, Any]] = []
    empty: list[dict[str, str]] = []
    for backbone in packet["primary_backbones"]:
        for selector in (_select_voice, _select_tempo, _select_integrity):
            chosen, missing = selector(rows, backbone, namespace)
            selected.extend(chosen)
            empty.extend(missing)
    counts = {
        backbone: {
            task: sum(
                row["backbone"] == backbone and row["rating_task"] == task for row in selected
            )
            for task in AXIS_TO_TASK.values()
        }
        for backbone in packet["primary_backbones"]
    }
    return {
        "candidate_index_sha256": sha256_json(normalized_candidate),
        "counts": counts,
        "empty_strata": sorted(empty, key=lambda row: (row["backbone"], row["selector_stratum"])),
        "schema_version": 2,
        "selected": sorted(selected, key=lambda row: row["row_id"]),
        "selection_status": "COMPLETE" if not empty else "COMPLETE_WITH_STRATUM_EMPTY",
        "selector_namespace": namespace,
        "source_ledger_sha256": candidate_index["source_ledger_sha256"],
    }


def _planned_counts(packet: dict[str, Any]) -> tuple[int, int]:
    unique_per_backbone = sum(packet["unique_items_per_backbone"].values())
    repeats_per_backbone = sum(packet["hidden_repeats_per_backbone"].values())
    backbones = int(packet["primary_backbone_count"])
    return backbones * unique_per_backbone, backbones * repeats_per_backbone


def _project_minutes(packet: dict[str, Any], pilot_minutes: float) -> dict[str, float | int]:
    unique, repeats = _planned_counts(packet)
    presentations = unique + repeats
    timed = presentations * float(packet["item_allowance_seconds"]) / 60.0
    projected = (timed + float(packet["fixed_minutes_excluding_pilot"]) + pilot_minutes) * (
        1.0 + float(packet["contingency_fraction"])
    )
    return {
        "planned_hidden_repeats": repeats,
        "planned_presentations": presentations,
        "planned_unique_items": unique,
        "projected_minutes": projected,
        "timed_packet_minutes": timed,
    }


def packet_gate(
    bundle_dir: Path,
    receipt_path: Path | None,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    """Return a fail-closed packet gate bound to one immutable pilot bundle."""

    bundle_path = bundle_dir.resolve() / "bundle.json"
    bundle = load_json_strict(bundle_path)
    if not isinstance(bundle, dict):
        raise ValueError("timing-pilot bundle must be an object")
    schema = load_json_strict(schema_path.resolve())
    packet = _validate_schema(schema)
    if receipt_path is None or not receipt_path.is_file():
        return {
            "PACKET_ASSEMBLY_STATUS": "BLOCKED_ON_TIMING_PILOT_INGESTION",
            "reason": "PI timing-pilot response receipt is absent",
        }
    receipt = load_json_strict(receipt_path.resolve())
    if not isinstance(receipt, dict):
        raise ValueError("timing-pilot receipt must be an object")
    require_exact_keys(receipt, RECEIPT_KEYS, "timing-pilot receipt")
    if receipt["receipt_schema_version"] != 2 or receipt["status"] != "TIMING_PILOT_INGESTED":
        raise ValueError("timing-pilot receipt is not terminal schema-v2 PASS")
    if receipt["usability_status"] != "PASS" or receipt["protocol_deviations"] != []:
        raise ValueError("timing-pilot receipt records a usability failure or deviation")
    timing_rules = schema.get("timing_pilot")
    if not isinstance(timing_rules, dict):
        raise ValueError("rater schema lacks timing-pilot attestation rules")
    if receipt["attestation_schema_version"] != 1 or not _valid_sha(receipt["attestation_sha256"]):
        raise ValueError("timing-pilot receipt lacks a valid signed attestation bind")
    required_identity = timing_rules.get("required_pi_identity")
    if receipt["pi_identity"] != required_identity or receipt["pi_signature"] != required_identity:
        raise ValueError("timing-pilot receipt PI identity/signature mismatch")
    if receipt["pi_affirmation"] != timing_rules.get("attestation_affirmation"):
        raise ValueError("timing-pilot receipt affirmation mismatch")
    bundle_hash = sha256_file(bundle_path)
    if receipt["bundle_json_sha256"] != bundle_hash:
        raise ValueError("timing-pilot receipt is not bound to this bundle")
    if receipt["bundle_id"] != bundle.get("bundle_id"):
        raise ValueError("timing-pilot receipt bundle_id mismatch")
    if receipt["build_identity_sha256"] != bundle.get("build_identity_sha256"):
        raise ValueError("timing-pilot receipt build identity mismatch")
    pilot_minutes = _finite(receipt["total_minutes"], "receipt total_minutes")
    session_seconds = _finite(receipt["session_elapsed_seconds"], "receipt session_elapsed_seconds")
    if pilot_minutes <= 0 or abs(pilot_minutes * 60.0 - session_seconds) > 1e-6:
        raise ValueError("timing-pilot receipt minutes and seconds disagree")
    projection = _project_minutes(packet, pilot_minutes)
    maximum = float(packet["maximum_projected_minutes"])
    if float(projection["projected_minutes"]) > maximum:
        return {
            "PACKET_ASSEMBLY_STATUS": "BLOCKED_ON_HUMAN_TIME_BUDGET",
            **projection,
            "maximum_projected_minutes": maximum,
            "reason": "updated conservative PI-time projection exceeds the frozen cap",
        }
    return {
        "PACKET_ASSEMBLY_STATUS": "READY_TO_ASSEMBLE",
        **projection,
        "maximum_projected_minutes": maximum,
        "reason": "matching strict PI timing-pilot receipt is within the frozen budget",
    }


def _build_layout(selection: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    namespace = str(packet["selector_namespace"])
    selected = selection["selected"]
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        by_group[(row["backbone"], row["rating_task"])].append(row)
    unique_entries: list[dict[str, Any]] = []
    repeat_entries: list[dict[str, Any]] = []
    missing_repeats: list[dict[str, Any]] = []
    for group, rows in sorted(by_group.items()):
        backbone, task = group
        ordered = sorted(rows, key=lambda row: _stable_digest(namespace, "block", row["row_id"]))
        offset = int(_stable_digest(namespace, backbone, task, "block-offset")[:8], 16) % 3
        blocks: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
        for index, row in enumerate(ordered):
            block = (index + offset) % 3 + 1
            blocks[block].append(row)
            unique_entries.append(
                {"block": block, "is_repeat": False, "repeat_of_row_id": None, "row": row}
            )
        requested = int(packet["hidden_repeats_per_backbone"][task])
        repeat_plan = [(1, 2), (2, 3)][:requested]
        if requested == 1:
            repeat_plan = [(1, 3)]
        for source_block, target_block in repeat_plan:
            source_rows = blocks[source_block]
            if not source_rows:
                missing_repeats.append(
                    {"backbone": backbone, "source_block": source_block, "task": task}
                )
                continue
            source = min(
                source_rows,
                key=lambda row: _stable_digest(
                    namespace, "hidden-repeat", backbone, task, source_block, row["row_id"]
                ),
            )
            repeat_entries.append(
                {
                    "block": target_block,
                    "is_repeat": True,
                    "repeat_of_row_id": source["row_id"],
                    "row": source,
                }
            )
    entries = unique_entries + repeat_entries
    entries.sort(
        key=lambda entry: (
            entry["block"],
            _stable_digest(
                namespace,
                "presentation-order",
                entry["block"],
                "repeat" if entry["is_repeat"] else "unique",
                entry["row"]["row_id"],
            ),
        )
    )
    for index in range(1, len(entries)):
        entry = entries[index]
        previous = entries[index - 1]
        if entry["is_repeat"] and entry["repeat_of_row_id"] == previous["row"]["row_id"]:
            swap_index = next(
                (
                    candidate
                    for candidate in range(index + 1, len(entries))
                    if entries[candidate]["block"] == entry["block"]
                    and entries[candidate]["row"]["row_id"] != entry["repeat_of_row_id"]
                ),
                None,
            )
            if swap_index is None:
                raise ValueError("cannot make hidden repeat non-adjacent within its block")
            entries[index], entries[swap_index] = entries[swap_index], entries[index]
    if any(
        entry["is_repeat"]
        and index > 0
        and entry["repeat_of_row_id"] == entries[index - 1]["row"]["row_id"]
        for index, entry in enumerate(entries)
    ):
        raise RuntimeError("hidden-repeat adjacency survived layout validation")
    return {
        "entries": entries,
        "missing_repeats": missing_repeats,
        "repeat_count": len(repeat_entries),
        "unique_count": len(unique_entries),
    }


def _write_text_exclusive(path: Path, text: str, mode: int) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, mode)


def _resolve_audio(candidate_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = candidate_path.resolve().parent / path
    return path.resolve()


def validate_packet_audio_duration(duration_seconds: float) -> None:
    """Apply the D-0026 per-backbone duration rule at packet assembly."""

    if not duration_within_tolerance(
        duration_seconds,
        PACKET_AUDIO_REQUESTED_SECONDS,
        PACKET_AUDIO_DURATION_TOLERANCE_SECONDS,
    ):
        raise ValueError(
            "candidate audio is outside the amended 30-second +/-0.25-second rule"
        )


def assemble_human_packet(
    bundle_dir: Path,
    receipt_path: Path,
    candidate_path: Path,
    output_root: Path,
    admin_root: Path,
    *,
    schema_path: Path = DEFAULT_SCHEMA,
    template_path: Path = DEFAULT_TEMPLATE,
) -> dict[str, Any]:
    """Assemble a blinded no-clobber packet after the strict timing gate opens."""

    gate = packet_gate(bundle_dir, receipt_path, schema_path)
    if gate["PACKET_ASSEMBLY_STATUS"] != "READY_TO_ASSEMBLE":
        raise RuntimeError(str(gate["PACKET_ASSEMBLY_STATUS"]))
    schema = load_json_strict(schema_path.resolve())
    packet = _validate_schema(schema)
    candidate = load_json_strict(candidate_path.resolve())
    selection = select_human_packet(candidate, schema)
    layout = _build_layout(selection, packet)
    build_inputs = {
        "candidate_index": sha256_file(candidate_path.resolve()),
        "packet_builder": sha256_file(Path(__file__).resolve()),
        "rater_schema": sha256_file(schema_path.resolve()),
        "shared_helpers": sha256_file((HERE / "bundle_common.py").resolve()),
        "timing_bundle": sha256_file(bundle_dir.resolve() / "bundle.json"),
        "timing_receipt": sha256_file(receipt_path.resolve()),
        "ui_template": sha256_file(template_path.resolve()),
    }
    build_identity = sha256_json(build_inputs)
    directory_name = f"benchmark-v2-human-audit-packet-01-{build_identity[:12]}"
    public_dir = output_root.resolve() / directory_name
    private_dir = admin_root.resolve() / directory_name
    if public_dir.exists() or private_dir.exists():
        raise FileExistsError(f"human packet destination already exists: {directory_name}")
    validated_sources: dict[str, Path] = {}
    for entry in layout["entries"]:
        row = entry["row"]
        if row["row_id"] in validated_sources:
            continue
        source = _resolve_audio(candidate_path, row["audio_path"])
        if sha256_file(source) != row["audio_sha256"]:
            raise ValueError(f"candidate audio hash mismatch: {row['row_id']}")
        info = sf.info(source)
        try:
            validate_packet_audio_duration(float(info.duration))
        except ValueError as error:
            raise ValueError(f"{error}: {row['row_id']}") from error
        validated_sources[row["row_id"]] = source
    public_dir.mkdir(parents=True, exist_ok=False)
    private_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    audio_dir = public_dir / "audio"
    audio_dir.mkdir()

    public_rows: list[dict[str, Any]] = []
    admin_rows: list[dict[str, Any]] = []
    tree_entries: list[dict[str, Any]] = []
    original_item_ids: dict[str, str] = {}
    for index, entry in enumerate(layout["entries"], start=1):
        row = entry["row"]
        source = validated_sources[row["row_id"]]
        item_id = f"item-{index:03d}"
        destination = audio_dir / f"{item_id}.wav"
        with source.open("rb") as source_handle, destination.open("xb") as output_handle:
            shutil.copyfileobj(source_handle, output_handle, length=1024 * 1024)
        os.chmod(destination, 0o444)
        relative = f"audio/{destination.name}"
        copied_hash = sha256_file(destination)
        if copied_hash != row["audio_sha256"]:
            raise RuntimeError(f"copied candidate audio hash mismatch: {row['row_id']}")
        public_rows.append({"audio": relative, "item_id": item_id, "task": row["rating_task"]})
        if not entry["is_repeat"]:
            original_item_ids[row["row_id"]] = item_id
        admin_rows.append(
            {
                "audio_sha256": copied_hash,
                "automatic_values": {
                    "defects": row["defects"],
                    "tempo_e_oct": row["tempo_e_oct"],
                    "tempo_status": row["tempo_status"],
                    "voice_margin": row["voice_margin"],
                    "voice_present": row["voice_present"],
                },
                "backbone": row["backbone"],
                "block": entry["block"],
                "condition": row["condition"],
                "item_id": item_id,
                "prompt_id": row["prompt_id"],
                "repeat_of_item_id": None,
                "repeat_of_row_id": entry["repeat_of_row_id"],
                "row_id": row["row_id"],
                "seed_index": row["seed_index"],
                "selector_fallback": row["selector_fallback"],
                "selector_stratum": row["selector_stratum"],
                "task": row["rating_task"],
            }
        )
        tree_entries.append(
            {"path": relative, "sha256": copied_hash, "size_bytes": destination.stat().st_size}
        )
    for row in admin_rows:
        repeat_of = row.pop("repeat_of_row_id")
        if repeat_of is not None:
            row["repeat_of_item_id"] = original_item_ids[repeat_of]

    pilot_minutes = float(gate["projected_minutes"]) / (1.0 + float(packet["contingency_fraction"]))
    pilot_minutes -= float(gate["timed_packet_minutes"])
    pilot_minutes -= float(packet["fixed_minutes_excluding_pilot"])
    session_limit_minutes = (
        float(packet["maximum_projected_minutes"]) / (1.0 + float(packet["contingency_fraction"]))
        - float(packet["fixed_minutes_excluding_pilot"])
        - pilot_minutes
    )
    public_bundle = {
        "build_identity_sha256": build_identity,
        "bundle_id": "benchmark-v2-human-audit-packet-01",
        "expected_minutes": float(gate["timed_packet_minutes"]),
        "item_allowance_seconds": float(packet["item_allowance_seconds"]),
        "items": public_rows,
        "purpose": "HUMAN_AUDIT_PACKET",
        "response_schema_version": 2,
        "schema_version": 2,
        "session_limit_seconds": session_limit_minutes * 60.0,
    }
    bundle_path = public_dir / "bundle.json"
    write_json_exclusive(bundle_path, public_bundle)
    tree_entries.append(
        {
            "path": "bundle.json",
            "sha256": sha256_file(bundle_path),
            "size_bytes": bundle_path.stat().st_size,
        }
    )
    index_path = public_dir / "index.html"
    _write_text_exclusive(
        index_path,
        render_bundle_html(template_path.resolve(), public_bundle),
        0o444,
    )
    tree_entries.append(
        {
            "path": "index.html",
            "sha256": sha256_file(index_path),
            "size_bytes": index_path.stat().st_size,
        }
    )
    readme_path = public_dir / "README.txt"
    _write_text_exclusive(
        readme_path,
        "Open index.html locally. Do not inspect files or hashes. Export the COMPLETE "
        "response JSON and return only that file to the project.\n",
        0o444,
    )
    tree_entries.append(
        {
            "path": "README.txt",
            "sha256": sha256_file(readme_path),
            "size_bytes": readme_path.stat().st_size,
        }
    )
    tree_hash = sha256_json(sorted(tree_entries, key=lambda row: row["path"]))
    manifest = {
        "build_identity_sha256": build_identity,
        "bundle_id": public_bundle["bundle_id"],
        "file_count_excluding_manifest": len(tree_entries),
        "item_count": len(public_rows),
        "public_tree_sha256": tree_hash,
        "schema_version": 2,
        "status": "HUMAN_AUDIT_PACKET_ASSEMBLED",
    }
    manifest_path = public_dir / "manifest.json"
    write_json_exclusive(manifest_path, manifest)
    admin_map = {
        "build_inputs": build_inputs,
        "build_identity_sha256": build_identity,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "empty_strata": selection["empty_strata"],
        "items": admin_rows,
        "layout_missing_repeats": layout["missing_repeats"],
        "public_bundle_sha256": sha256_file(bundle_path),
        "public_manifest_sha256": sha256_file(manifest_path),
        "public_tree_entries": sorted(tree_entries, key=lambda row: row["path"]),
        "public_tree_sha256": tree_hash,
        "schema_version": 2,
        "selection": selection,
        "timing_gate": gate,
    }
    admin_path = private_dir / "admin-map.json"
    write_json_exclusive(admin_path, admin_map, mode=0o400)
    freeze_public_tree(public_dir)
    freeze_private_tree(private_dir)
    return {
        **manifest,
        "admin_dir": str(private_dir),
        "admin_map_sha256": sha256_file(admin_path),
        "audio_generation_calls": 0,
        "bundle_dir": str(public_dir),
        "bundle_json_sha256": sha256_file(bundle_path),
        "public_manifest_sha256": sha256_file(manifest_path),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--candidate-index", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--admin-root", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    gate = packet_gate(args.bundle_dir, args.receipt, args.schema)
    if args.candidate_index is None:
        print(json.dumps(gate, allow_nan=False, sort_keys=True))
        return 0 if gate["PACKET_ASSEMBLY_STATUS"] == "READY_TO_ASSEMBLE" else 3
    if args.receipt is None or args.output_root is None or args.admin_root is None:
        raise SystemExit(
            "assembly requires --receipt, --candidate-index, --output-root, and --admin-root"
        )
    if gate["PACKET_ASSEMBLY_STATUS"] != "READY_TO_ASSEMBLE":
        print(json.dumps(gate, allow_nan=False, sort_keys=True))
        return 3
    result = assemble_human_packet(
        args.bundle_dir,
        args.receipt,
        args.candidate_index,
        args.output_root,
        args.admin_root,
        schema_path=args.schema,
        template_path=args.template,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

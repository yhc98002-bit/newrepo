"""Recompute frozen automatic endpoint decisions from raw evaluator features."""

from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from instruments.integrity import DropoutCandidateMetrics, score_integrity_raw_metrics
from instruments.tempo import (
    beat_this_estimate,
    librosa_estimate,
    octave_invariant_error,
    resolve_tempo,
    resolve_tempo_windows,
)
from instruments.voice import load_promoted_or_from_manifest, score_promoted_or_raw
from scoring.common import (
    finite_float,
    require_exact_keys,
    require_sha256,
    sha256_json,
)

FEATURE_BUNDLE_KEYS = {
    "created_at_utc",
    "evaluator_identities",
    "human_gold_labels_used",
    "rows",
    "schema_version",
    "snapshot_sha256",
    "status",
}
FEATURE_ROW_KEYS = {"audio_sha256", "axis", "features", "request_sha256"}
WINDOW_KEYS = {
    "beat_this_events_seconds",
    "hop_length",
    "librosa_beat_frames",
    "librosa_tempo_bpm",
    "sample_rate",
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
DROPOUT_KEYS = {
    "duration_ms",
    "left_boundary_ms",
    "left_level_dbfs",
    "low_level_dbfs",
    "right_boundary_ms",
    "right_level_dbfs",
}
DEFECTS = ("clipping", "dropout", "silence", "crackle")
FRESH_AUTOMATIC_REFERENCE = "FRESH_AUTOMATIC_OUTPUTS_ONLY_NOT_HUMAN_GOLD"


def _reject_gold_fields(value: Any, context: str) -> None:
    """Reject accidental label/gold transport below the explicit bundle attestation."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("-", "_")
            if any(token in normalized for token in ("human", "gold", "label", "pi_")):
                raise ValueError(f"{context} contains forbidden audit field {key!r}")
            _reject_gold_fields(child, context)
    elif isinstance(value, list):
        for child in value:
            _reject_gold_fields(child, context)


def _finite_sequence(value: Any, context: str, *, integers: bool = False) -> list[float | int]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    result: list[float | int] = []
    for index, item in enumerate(value):
        if integers:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise ValueError(f"{context}[{index}] must be a nonnegative integer")
            result.append(item)
        else:
            result.append(finite_float(item, f"{context}[{index}]"))
    return result


def _tempo_window(value: Any, context: str) -> tuple[Any, Any, dict[str, Any]]:
    raw = require_exact_keys(value, WINDOW_KEYS, context)
    events = _finite_sequence(raw["beat_this_events_seconds"], f"{context}.beat_this_events")
    frames = _finite_sequence(
        raw["librosa_beat_frames"], f"{context}.librosa_frames", integers=True
    )
    tempo = finite_float(raw["librosa_tempo_bpm"], f"{context}.librosa_tempo_bpm")
    sample_rate = raw["sample_rate"]
    hop_length = raw["hop_length"]
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or sample_rate <= 0
        or isinstance(hop_length, bool)
        or not isinstance(hop_length, int)
        or hop_length <= 0
    ):
        raise ValueError(f"{context} sample_rate/hop_length must be positive integers")
    beat_this = beat_this_estimate(events)
    librosa = librosa_estimate(
        tempo,
        frames,
        sample_rate=sample_rate,
        hop_length=hop_length,
    )
    audit = {
        "beat_this": asdict(beat_this),
        "librosa": asdict(librosa),
    }
    return beat_this, librosa, audit


def _resolution(value: Any) -> dict[str, Any]:
    resolved = value.status == "RESOLVED"
    return {
        "beat_this_aligned_bpm": value.beat_this_aligned_bpm if resolved else None,
        "consensus_bpm": value.consensus_bpm if resolved else None,
        "disagreement_octaves": value.disagreement_octaves,
        "librosa_aligned_bpm": value.librosa_aligned_bpm if resolved else None,
        "octave_invariant_error": value.octave_invariant_error if resolved else None,
        "primary_5pct_success": bool(value.primary_5pct_success) if resolved else False,
        "raw_absolute_percentage_error": value.raw_absolute_percentage_error if resolved else None,
        "sensitivity_10pct_success": bool(value.sensitivity_10pct_success) if resolved else False,
        "status": value.status,
    }


def _individual_tempo_pass(estimate: Any, target: float) -> bool | None:
    if not estimate.valid or estimate.bpm is None:
        return None
    return octave_invariant_error(float(estimate.bpm), target) <= math.log2(1.05)


def _normalize_voice(
    row: dict[str, Any], features: Any, voice_config: Any
) -> tuple[dict[str, Any], dict[str, bool | None]]:
    raw = require_exact_keys(
        features,
        {"demucs_vocal_energy_ratio", "mixture_rms", "panns_max_vocal_probability"},
        "voice features",
    )
    mixture = finite_float(raw["mixture_rms"], "mixture_rms", nonnegative=True)
    ratio = finite_float(
        raw["demucs_vocal_energy_ratio"], "demucs_vocal_energy_ratio", nonnegative=True
    )
    probability = finite_float(raw["panns_max_vocal_probability"], "panns probability")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("panns_max_vocal_probability must be in [0,1]")
    decision = score_promoted_or_raw(
        voice_config,
        mixture_rms=mixture,
        demucs_vocal_energy_ratio=ratio,
        panns_max_vocal_probability=probability,
    )
    request = row["prompt_metadata"].get("request")
    if request not in {"vocal", "instrumental"}:
        raise ValueError("voice prompt lacks its frozen request direction")
    success = decision.voice_present if request == "vocal" else not decision.voice_present
    result = {
        "automatic_instrument_success": success,
        "automatic_result_wording": "AUTOMATIC_INSTRUMENT_OUTCOME_NOT_HUMAN_VOICE_JUDGMENT",
        "demucs_present": decision.demucs_present,
        "demucs_vocal_energy_ratio": ratio,
        "mixture_rms": mixture,
        "panns_max_vocal_probability": probability,
        "panns_present": decision.panns_present,
        "request": request,
        "voice_margin": decision.voice_margin,
        "voice_present": decision.voice_present,
    }
    metrics = {
        "automatic_instrument_success": success,
        "automatic_voice_presence": decision.voice_present,
        "demucs_present": decision.demucs_present,
        "panns_present": decision.panns_present,
    }
    return result, metrics


def _normalize_tempo(
    row: dict[str, Any], features: Any
) -> tuple[dict[str, Any], dict[str, bool | None]]:
    raw = require_exact_keys(
        features,
        {"first_window", "full_clip", "second_window"},
        "tempo features",
    )
    target = finite_float(row["prompt_metadata"].get("target_bpm"), "target_bpm")
    if target <= 0.0:
        raise ValueError("target_bpm must be positive")
    full_bt, full_librosa, full_audit = _tempo_window(raw["full_clip"], "full_clip")
    first_bt, first_librosa, first_audit = _tempo_window(raw["first_window"], "first_window")
    second_bt, second_librosa, second_audit = _tempo_window(
        raw["second_window"], "second_window"
    )
    full = resolve_tempo(target, full_bt, full_librosa)
    windows = resolve_tempo_windows(
        target,
        first_beat_this=first_bt,
        first_librosa=first_librosa,
        second_beat_this=second_bt,
        second_librosa=second_librosa,
    )
    drift_resolved = (
        windows.first_window.status == "RESOLVED" and windows.second_window.status == "RESOLVED"
    )
    result = {
        "automatic_result_wording": "AUTOMATIC_TEMPO_INSTRUMENT_OUTCOME_NOT_HUMAN_TAP_GOLD",
        "first_window": _resolution(windows.first_window),
        "full_clip": _resolution(full),
        "raw_estimator_audit": {
            "first_window": first_audit,
            "full_clip": full_audit,
            "second_window": second_audit,
        },
        "second_window": _resolution(windows.second_window),
        "target_bpm": target,
        "window_drift": {
            "octave_invariant_absolute_drift": (
                windows.octave_invariant_absolute_drift if drift_resolved else None
            ),
            "signed_drift_octaves": windows.signed_drift_octaves if drift_resolved else None,
            "status": "RESOLVED" if drift_resolved else "WINDOW_DRIFT_UNRESOLVED",
        },
    }
    metrics: dict[str, bool | None] = {
        "beat_this_primary_5pct_success": _individual_tempo_pass(full_bt, target),
        "first_window_primary_5pct_success": (
            windows.first_window.primary_5pct_success
            if windows.first_window.status == "RESOLVED"
            else False
        ),
        "first_window_sensitivity_10pct_success": (
            windows.first_window.sensitivity_10pct_success
            if windows.first_window.status == "RESOLVED"
            else False
        ),
        "full_clip_abstention": full.status != "RESOLVED",
        "full_clip_primary_5pct_success": (
            full.primary_5pct_success if full.status == "RESOLVED" else False
        ),
        "full_clip_sensitivity_10pct_success": (
            full.sensitivity_10pct_success if full.status == "RESOLVED" else False
        ),
        "librosa_primary_5pct_success": _individual_tempo_pass(full_librosa, target),
        "second_window_primary_5pct_success": (
            windows.second_window.primary_5pct_success
            if windows.second_window.status == "RESOLVED"
            else False
        ),
        "second_window_sensitivity_10pct_success": (
            windows.second_window.sensitivity_10pct_success
            if windows.second_window.status == "RESOLVED"
            else False
        ),
        "window_drift_resolved": drift_resolved,
    }
    return result, metrics


def _parse_integrity_raw(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = require_exact_keys(value, INTEGRITY_RAW_KEYS, "integrity raw metrics")
    parsed: dict[str, Any] = {
        "all_sample_rms": finite_float(
            raw["all_sample_rms"], "all_sample_rms", nonnegative=True
        ),
        "hard_clipped_fraction": finite_float(
            raw["hard_clipped_fraction"], "hard_clipped_fraction", nonnegative=True
        ),
        "silent_frame_fraction": finite_float(
            raw["silent_frame_fraction"], "silent_frame_fraction", nonnegative=True
        ),
        "true_peak": finite_float(raw["true_peak"], "true_peak", nonnegative=True),
    }
    for key in ("longest_hard_clip_run_samples", "maximum_channel_crackle_count"):
        item = raw[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
        parsed[key] = item
    candidates = raw["dropout_candidates"]
    if not isinstance(candidates, list):
        raise ValueError("dropout_candidates must be a list")
    parsed_candidates: list[DropoutCandidateMetrics] = []
    serialized_candidates: list[dict[str, float]] = []
    for index, candidate in enumerate(candidates):
        record = require_exact_keys(candidate, DROPOUT_KEYS, f"dropout candidate {index}")
        serialized = {
            key: finite_float(record[key], f"dropout candidate {index}.{key}")
            for key in DROPOUT_KEYS
        }
        for key in ("duration_ms", "left_boundary_ms", "right_boundary_ms"):
            if serialized[key] < 0.0:
                raise ValueError(f"dropout candidate {index}.{key} must be nonnegative")
        parsed_candidates.append(DropoutCandidateMetrics(**serialized))
        serialized_candidates.append(serialized)
    parsed["dropout_candidates"] = parsed_candidates
    transport = {**parsed, "dropout_candidates": serialized_candidates}
    decision = score_integrity_raw_metrics(**parsed)
    return transport, decision


def _normalize_integrity(
    features: Any,
) -> tuple[dict[str, Any], dict[str, bool | None]]:
    raw = require_exact_keys(
        features,
        {"file_validity_failures", "raw_metrics"},
        "integrity features",
    )
    failures = raw["file_validity_failures"]
    if not isinstance(failures, list) or any(
        not isinstance(item, str) or not item for item in failures
    ):
        raise ValueError("file_validity_failures must be a list of nonempty strings")
    if failures:
        if raw["raw_metrics"] is not None:
            raise ValueError("invalid integrity audio must not supply selector raw metrics")
        result = {
            "automatic_result_wording": "OBJECTIVE_DSP_OUTCOME_NOT_HUMAN_AUDIBLE_DEFECT_GOLD",
            "defects": None,
            "file_validity_failures": failures,
            "integrity_failure": None,
            "integrity_raw": None,
        }
        metrics = {f"{name}_defect": None for name in DEFECTS}
        metrics.update({"file_validity_failure": True, "integrity_failure": None})
        return result, metrics
    transport, decision = _parse_integrity_raw(raw["raw_metrics"])
    defects = decision["defects"]
    overall = any(bool(defects[name]["flag"]) for name in DEFECTS)
    result = {
        "automatic_result_wording": "OBJECTIVE_DSP_OUTCOME_NOT_HUMAN_AUDIBLE_DEFECT_GOLD",
        "defects": defects,
        "file_validity_failures": [],
        "integrity_failure": overall,
        "integrity_raw": transport,
    }
    metrics = {f"{name}_defect": bool(defects[name]["flag"]) for name in DEFECTS}
    metrics.update({"file_validity_failure": False, "integrity_failure": overall})
    return result, metrics


def normalize_feature_bundle(
    snapshot: dict[str, Any],
    bundle: dict[str, Any],
    *,
    expected_evaluator_identities: dict[str, Any],
    voice_manifest_path: Path,
    axes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate fresh raw features and recompute every frozen Boolean endpoint."""

    require_exact_keys(bundle, FEATURE_BUNDLE_KEYS, "feature bundle")
    if bundle["schema_version"] != 1 or bundle["status"] != "FEATURE_EXTRACTION_COMPLETE":
        raise ValueError("feature bundle identity/status is invalid")
    if bundle["human_gold_labels_used"] is not False:
        raise ValueError("automatic scoring cannot ingest human-gold labels")
    if bundle["snapshot_sha256"] != snapshot["snapshot_sha256"]:
        raise ValueError("feature bundle is not bound to this completed-shard snapshot")
    if bundle["evaluator_identities"] != expected_evaluator_identities:
        raise ValueError("feature evaluator identities differ from the bound runtime")
    _reject_gold_fields(bundle["evaluator_identities"], "evaluator identities")
    feature_rows = bundle["rows"]
    if not isinstance(feature_rows, list):
        raise ValueError("feature bundle rows must be a list")

    selected_axes = axes or {"vocal_instrumental", "tempo", "integrity"}
    if not selected_axes <= {"vocal_instrumental", "tempo", "integrity"} or not selected_axes:
        raise ValueError("normalization axes must be a nonempty confirmatory subset")
    snapshot_rows = {
        row["request_sha256"]: row
        for row in snapshot["rows"]
        if row["axis"] in selected_axes
    }
    supplied: dict[str, dict[str, Any]] = {}
    for index, feature_row in enumerate(feature_rows):
        require_exact_keys(feature_row, FEATURE_ROW_KEYS, f"feature row {index}")
        _reject_gold_fields(feature_row, f"feature row {index}")
        request = require_sha256(feature_row["request_sha256"], "request_sha256")
        require_sha256(feature_row["audio_sha256"], "audio_sha256")
        if request in supplied:
            raise ValueError("feature request SHA is not unique")
        supplied[request] = feature_row
    if set(supplied) != set(snapshot_rows):
        missing = len(set(snapshot_rows) - set(supplied))
        extra = len(set(supplied) - set(snapshot_rows))
        raise ValueError(
            f"feature rows differ from confirmatory snapshot; missing={missing}, extra={extra}"
        )

    voice_config = load_promoted_or_from_manifest(voice_manifest_path)
    normalized: list[dict[str, Any]] = []
    for request in sorted(snapshot_rows):
        source = snapshot_rows[request]
        raw = supplied[request]
        if raw["axis"] != source["axis"] or raw["audio_sha256"] != source["audio_sha256"]:
            raise ValueError("feature row axis/audio binding differs from snapshot")
        if source["axis"] == "vocal_instrumental":
            result, metrics = _normalize_voice(source, raw["features"], voice_config)
        elif source["axis"] == "tempo":
            result, metrics = _normalize_tempo(source, raw["features"])
        else:
            result, metrics = _normalize_integrity(raw["features"])
        prompt_meta = source["prompt_metadata"]
        stratum = (
            "all"
            if source["axis"] == "vocal_instrumental"
            else prompt_meta.get("salience", prompt_meta.get("profile"))
        )
        normalized.append(
            {
                **{key: value for key, value in source.items() if key != "prompt_metadata"},
                "automatic_result": result,
                "metrics": metrics,
                "prompt_metadata": prompt_meta,
                "stratum": stratum,
            }
        )
    return normalized


def candidate_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build the exact schema-v2 automatic-only candidate transport row."""

    axis = row["axis"]
    result = row["automatic_result"]
    common: dict[str, Any] = {
        "audio_path": row["audio_path"],
        "audio_sha256": row["audio_sha256"],
        "axis": {"vocal_instrumental": "voice", "tempo": "tempo", "integrity": "integrity"}[
            axis
        ],
        "backbone": row["backbone"],
        "cluster_id": row["cluster_id"],
        "condition": row["condition"],
        "defects": None,
        "demucs_vocal_energy_ratio": None,
        "demucs_present": None,
        "integrity_raw": None,
        "integrity_profile": None,
        "mixture_rms": None,
        "panns_max_vocal_probability": None,
        "panns_present": None,
        "prompt_id": row["prompt_id"],
        "request": None,
        "row_id": sha256_json(
            {"namespace": "automatic-scoring-v2-candidate-row", "request": row["request_sha256"]}
        ),
        "salience": None,
        "seed_index": row["root_index"],
        "target_bpm": None,
        "tempo_e_oct": None,
        "tempo_primary_pass": None,
        "tempo_status": None,
        "voice_margin": None,
        "voice_present": None,
    }
    if axis == "vocal_instrumental":
        common.update(
            {
                "demucs_vocal_energy_ratio": result["demucs_vocal_energy_ratio"],
                "demucs_present": result["demucs_present"],
                "mixture_rms": result["mixture_rms"],
                "panns_max_vocal_probability": result["panns_max_vocal_probability"],
                "panns_present": result["panns_present"],
                "request": result["request"],
                "voice_margin": result["voice_margin"],
                "voice_present": result["voice_present"],
            }
        )
    elif axis == "tempo":
        full = result["full_clip"]
        common.update(
            {
                "salience": row["prompt_metadata"]["salience"],
                "target_bpm": result["target_bpm"],
                "tempo_e_oct": full["octave_invariant_error"],
                "tempo_primary_pass": (
                    full["primary_5pct_success"] if full["status"] == "RESOLVED" else None
                ),
                "tempo_status": full["status"],
            }
        )
    else:
        if result["file_validity_failures"]:
            return None
        common.update(
            {
                "defects": result["defects"],
                "integrity_raw": result["integrity_raw"],
                "integrity_profile": row["prompt_metadata"]["profile"],
            }
        )
    return common


def build_candidate_index(
    rows: list[dict[str, Any]], primary_backbones: list[str], source_ledger_sha256: str
) -> dict[str, Any]:
    candidates = [candidate_row(row) for row in rows]
    return {
        "primary_backbones": primary_backbones,
        "rows": sorted(
            (row for row in candidates if row is not None), key=lambda value: value["row_id"]
        ),
        "schema_version": 2,
        "source_ledger_sha256": require_sha256(
            source_ledger_sha256, "source_ledger_sha256"
        ),
    }


def evaluator_audit_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report automatic-operationalization discordance without gold claims."""

    comparisons = {
        "vocal_instrumental": (
            ("demucs_threshold_branch", "automatic_voice_presence", "demucs_present"),
            ("panns_threshold_branch", "automatic_voice_presence", "panns_present"),
        ),
        "tempo": (
            (
                "beat_this_5pct_alone",
                "full_clip_primary_5pct_success",
                "beat_this_primary_5pct_success",
            ),
            (
                "librosa_5pct_alone",
                "full_clip_primary_5pct_success",
                "librosa_primary_5pct_success",
            ),
        ),
        "integrity": tuple(
            (f"{defect}_only", "integrity_failure", f"{defect}_defect") for defect in DEFECTS
        ),
    }
    output: list[dict[str, Any]] = []
    for (axis, backbone), group in sorted(
        {
            (row["axis"], row["backbone"]): [
                item
                for item in rows
                if item["axis"] == row["axis"] and item["backbone"] == row["backbone"]
            ]
            for row in rows
        }.items()
    ):
        for comparator, primary_key, comparator_key in comparisons[axis]:
            pairs = [
                (item["metrics"].get(primary_key), item["metrics"].get(comparator_key))
                for item in group
            ]
            comparable = [
                (bool(left), bool(right))
                for left, right in pairs
                if left is not None and right is not None
            ]
            discordant = sum(left != right for left, right in comparable)
            output.append(
                {
                    "accuracy_claim_authorized": False,
                    "axis": axis,
                    "backbone": backbone,
                    "common_operationalization": comparator,
                    "comparable_count": len(comparable),
                    "comparator_positive_count": sum(right for _, right in comparable),
                    "discordance_count": discordant,
                    "discordance_rate": discordant / len(comparable) if comparable else None,
                    "failure_claim": "NOT_EVALUATED_WITHOUT_POOLED_HUMAN_GOLD",
                    "human_gold_claims": False,
                    "primary_operationalization": primary_key,
                    "primary_positive_count": sum(left for left, _ in comparable),
                    "reference_basis": FRESH_AUTOMATIC_REFERENCE,
                    "row_count": len(group),
                }
            )
    return output

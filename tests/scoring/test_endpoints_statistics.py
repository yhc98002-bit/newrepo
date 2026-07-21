from __future__ import annotations

import math
from pathlib import Path

from rater.build_human_packet import validate_candidate_index
from rater.bundle_common import load_json_strict
from scoring.endpoints import (
    build_candidate_index,
    evaluator_audit_table,
    normalize_feature_bundle,
)
from scoring.statistics import prevalence_table

ROOT = Path(__file__).resolve().parents[2]


def _tempo_window() -> dict[str, object]:
    return {
        "beat_this_events_seconds": [index * 0.5 for index in range(12)],
        "hop_length": 10,
        "librosa_beat_frames": [index * 5 for index in range(12)],
        "librosa_tempo_bpm": 120.0,
        "sample_rate": 100,
    }


def _snapshot() -> dict[str, object]:
    rows = [
        {
            "audio_path": "/immutable/voice.wav",
            "audio_sha256": "a" * 64,
            "axis": "vocal_instrumental",
            "backbone": "stable-audio-3-medium-base",
            "cluster_id": "voice-frame-01",
            "condition": "FIXED",
            "duration_seconds": 30.0,
            "model_id": "model",
            "model_slug": "model",
            "prompt": "prompt",
            "prompt_id": "voice-frame-01-instrumental",
            "prompt_metadata": {"request": "instrumental"},
            "request_sha256": "1" * 64,
            "root_index": 0,
            "seed": 1,
            "source_run_id": "source",
        },
        {
            "audio_path": "/immutable/tempo.wav",
            "audio_sha256": "b" * 64,
            "axis": "tempo",
            "backbone": "stable-audio-3-medium-base",
            "cluster_id": "tempo-120-percussive_regular",
            "condition": "BASE",
            "duration_seconds": 30.0,
            "model_id": "model",
            "model_slug": "model",
            "prompt": "prompt",
            "prompt_id": "tempo-120-percussive_regular",
            "prompt_metadata": {
                "salience": "percussive_regular",
                "target_bpm": 120,
            },
            "request_sha256": "2" * 64,
            "root_index": 0,
            "seed": 2,
            "source_run_id": "source",
        },
        {
            "audio_path": "/immutable/integrity.wav",
            "audio_sha256": "c" * 64,
            "axis": "integrity",
            "backbone": "stable-audio-3-medium-base",
            "cluster_id": "integrity-rock-sharp_percussive_control",
            "condition": "BASE",
            "duration_seconds": 30.0,
            "model_id": "model",
            "model_slug": "model",
            "prompt": "prompt",
            "prompt_id": "integrity-rock-sharp_percussive_control",
            "prompt_metadata": {"profile": "sharp_percussive_control"},
            "request_sha256": "3" * 64,
            "root_index": 0,
            "seed": 3,
            "source_run_id": "source",
        },
    ]
    return {
        "rows": rows,
        "snapshot_sha256": "d" * 64,
        "source_ledger_sha256": "e" * 64,
    }


def _bundle(identities: dict[str, object]) -> dict[str, object]:
    window = _tempo_window()
    return {
        "created_at_utc": "fixture",
        "evaluator_identities": identities,
        "human_gold_labels_used": False,
        "rows": [
            {
                "audio_sha256": "a" * 64,
                "axis": "vocal_instrumental",
                "features": {
                    "demucs_vocal_energy_ratio": 0.0,
                    "mixture_rms": 0.1,
                    "panns_max_vocal_probability": 0.0,
                },
                "request_sha256": "1" * 64,
            },
            {
                "audio_sha256": "b" * 64,
                "axis": "tempo",
                "features": {
                    "first_window": window,
                    "full_clip": window,
                    "second_window": window,
                },
                "request_sha256": "2" * 64,
            },
            {
                "audio_sha256": "c" * 64,
                "axis": "integrity",
                "features": {
                    "file_validity_failures": [],
                    "raw_metrics": {
                        "all_sample_rms": 0.1,
                        "dropout_candidates": [],
                        "hard_clipped_fraction": 0.0,
                        "longest_hard_clip_run_samples": 0,
                        "maximum_channel_crackle_count": 0,
                        "silent_frame_fraction": 0.0,
                        "true_peak": 0.5,
                    },
                },
                "request_sha256": "3" * 64,
            },
        ],
        "schema_version": 1,
        "snapshot_sha256": "d" * 64,
        "status": "FEATURE_EXTRACTION_COMPLETE",
    }


def test_frozen_recomputation_candidate_schema_and_no_gold_audit() -> None:
    identities = {"fixture": "automatic-only"}
    rows = normalize_feature_bundle(
        _snapshot(),
        _bundle(identities),
        expected_evaluator_identities=identities,
        voice_manifest_path=ROOT / "provenance" / "b1" / "voice_source_manifest.json",
    )
    voice = next(row for row in rows if row["axis"] == "vocal_instrumental")
    assert voice["automatic_result"]["automatic_instrument_success"] is True
    assert "AUTOMATIC_INSTRUMENT_OUTCOME" in voice["automatic_result"][
        "automatic_result_wording"
    ]
    tempo = next(row for row in rows if row["axis"] == "tempo")
    assert tempo["automatic_result"]["full_clip"]["primary_5pct_success"] is True
    assert tempo["automatic_result"]["first_window"]["primary_5pct_success"] is True
    assert tempo["automatic_result"]["second_window"]["primary_5pct_success"] is True
    assert math.isclose(tempo["automatic_result"]["window_drift"]["signed_drift_octaves"], 0)

    primary = ["stable-audio-3-medium-base", "stable-audio-open-1.0", "ACE-Step v1"]
    candidate = build_candidate_index(rows, primary, "e" * 64)
    assert candidate["primary_backbones"] == primary
    assert {row["backbone"] for row in candidate["rows"]} == {
        "stable-audio-3-medium-base"
    }
    validate_candidate_index(candidate, load_json_strict(ROOT / "rater" / "schema_v2.json"))

    audit = evaluator_audit_table(rows)
    assert audit and all(row["human_gold_claims"] is False for row in audit)
    assert all(row["accuracy_claim_authorized"] is False for row in audit)


def test_cluster_prevalence_is_deterministic_and_defect_separated() -> None:
    identities = {"fixture": "automatic-only"}
    rows = normalize_feature_bundle(
        _snapshot(),
        _bundle(identities),
        expected_evaluator_identities=identities,
        voice_manifest_path=ROOT / "provenance" / "b1" / "voice_source_manifest.json",
    )
    first = prevalence_table(
        rows,
        replicates=50,
        seed=2026072001,
        confidence_level=0.95,
        headline_only=True,
    )
    second = prevalence_table(
        rows,
        replicates=50,
        seed=2026072001,
        confidence_level=0.95,
        headline_only=True,
    )
    assert first == second
    integrity_metrics = {
        row["metric"] for row in first if row["axis"] == "integrity"
    }
    assert {
        "clipping_defect",
        "dropout_defect",
        "silence_defect",
        "crackle_defect",
        "integrity_failure",
        "file_validity_failure",
    } == integrity_metrics

from __future__ import annotations

import copy

import pytest

from scoring.published_tables import (
    WATERMARK,
    validate_candidate_index_publication,
    validate_evaluator_audit_publication,
    validate_prevalence_publication,
)


def _prevalence_row() -> dict[str, object]:
    return {
        "axis": "integrity",
        "backbone": "stable-audio-open-1.0",
        "bootstrap_replicates": 10_000,
        "bootstrap_seed_namespace": "stable-audio-open-1.0|integrity|BASE",
        "ci_high": 0.2,
        "ci_low": 0.1,
        "cluster_count": 12,
        "condition": "BASE",
        "confidence_level": 0.95,
        "metric": "clipping_defect",
        "missing_count": 0,
        "observed_count": 96,
        "point_prevalence": 0.15,
        "resampling_unit": "PROMPT_CLUSTER_THEN_MATCHED_SEED",
        "row_count": 96,
        "slice": "ALL",
    }


def _prevalence() -> dict[str, object]:
    return {
        "rows": [_prevalence_row()],
        "schema_version": 2,
        "status": "AUTOMATIC_PREVALENCE_COMPLETE",
        "watermark": WATERMARK,
    }


def _audit() -> dict[str, object]:
    return {
        "rows": [
            {
                "axis": "tempo",
                "backbone": "stable-audio-open-1.0",
                "common_operationalization": "beat_this_5pct_alone",
                "comparable_count": 96,
                "comparator_positive_count": 20,
                "discordance_count": 5,
                "discordance_rate": 5 / 96,
                "interpretation": "OPERATIONALIZATION_DISCORDANCE_ONLY",
                "primary_operationalization": "full_clip_primary_5pct_success",
                "primary_positive_count": 21,
                "reference_basis": "FRESH_AUTOMATIC_OUTPUTS_ONLY",
                "row_count": 96,
            }
        ],
        "schema_version": 2,
        "status": "FRESH_OUTPUT_OPERATIONALIZATION_DISCORDANCE_ONLY",
        "watermark": WATERMARK,
    }


def _candidate() -> dict[str, object]:
    return {
        "primary_backbones": [
            "stable-audio-3-medium-base",
            "stable-audio-open-1.0",
            "ACE-Step v1",
        ],
        "rows": [{"row_id": "transport-shape-is-validated-by-the-rater"}],
        "schema_version": 3,
        "source_ledger_sha256": "a" * 64,
        "watermark": WATERMARK,
    }


def test_all_standalone_publication_envelopes_require_exact_watermark() -> None:
    validate_prevalence_publication(_prevalence())
    validate_evaluator_audit_publication(_audit())
    validate_candidate_index_publication(_candidate())

    for value, validator in (
        (_prevalence(), validate_prevalence_publication),
        (_audit(), validate_evaluator_audit_publication),
        (_candidate(), validate_candidate_index_publication),
    ):
        missing = copy.deepcopy(value)
        missing.pop("watermark")
        with pytest.raises(ValueError):
            validator(missing)
        altered = copy.deepcopy(value)
        altered["watermark"] = "AUTOMATIC OUTCOMES"
        with pytest.raises(ValueError, match="watermark"):
            validator(altered)


def test_publications_reject_prohibited_wording_anywhere_in_payload() -> None:
    for token in ("accuracy", "human_gold", "human-gold", "human gold"):
        publication = _audit()
        publication["rows"][0]["interpretation"] = token  # type: ignore[index]
        with pytest.raises(ValueError, match="prohibited publication wording"):
            validate_evaluator_audit_publication(publication)


def test_publications_reject_extra_fields_and_legacy_candidate_schema() -> None:
    prevalence = _prevalence()
    prevalence["claim"] = False
    with pytest.raises(ValueError, match="keys differ"):
        validate_prevalence_publication(prevalence)

    candidate = _candidate()
    candidate["schema_version"] = 2
    with pytest.raises(ValueError, match="schema_version"):
        validate_candidate_index_publication(candidate)

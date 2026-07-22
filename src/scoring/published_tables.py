"""Fail-closed publication contracts for automatic-instrument tables."""

from __future__ import annotations

import json
from typing import Any

from scoring.common import require_exact_keys, require_sha256

WATERMARK = "AUTOMATIC-INSTRUMENT OUTCOMES"
FORBIDDEN_PUBLICATION_TOKENS = (
    "accuracy",
    "human_gold",
    "human-gold",
    "human gold",
)

PREVALENCE_KEYS = {"rows", "schema_version", "status", "watermark"}
INTEGRITY_FIRST_KEYS = {
    "rows",
    "schema_version",
    "source_snapshot_sha256",
    "status",
    "watermark",
}
EVALUATOR_AUDIT_KEYS = {"rows", "schema_version", "status", "watermark"}
CANDIDATE_INDEX_KEYS = {
    "primary_backbones",
    "rows",
    "schema_version",
    "source_ledger_sha256",
    "watermark",
}
PREVALENCE_ROW_KEYS = {
    "axis",
    "backbone",
    "bootstrap_replicates",
    "bootstrap_seed_namespace",
    "ci_high",
    "ci_low",
    "cluster_count",
    "condition",
    "confidence_level",
    "metric",
    "missing_count",
    "observed_count",
    "point_prevalence",
    "resampling_unit",
    "row_count",
    "slice",
}
EVALUATOR_AUDIT_ROW_KEYS = {
    "axis",
    "backbone",
    "common_operationalization",
    "comparable_count",
    "comparator_positive_count",
    "discordance_count",
    "discordance_rate",
    "interpretation",
    "primary_operationalization",
    "primary_positive_count",
    "reference_basis",
    "row_count",
}


def validate_automatic_table_language(value: Any, context: str) -> dict[str, Any]:
    """Require the exact watermark and reject prohibited evaluative wording."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    if value.get("watermark") != WATERMARK:
        raise ValueError(f"{context} lacks the exact automatic-instrument watermark")
    payload = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).lower()
    for token in FORBIDDEN_PUBLICATION_TOKENS:
        if token in payload:
            raise ValueError(f"{context} contains prohibited publication wording {token!r}")
    return value


def _validate_rows(
    value: Any,
    expected_keys: set[str],
    context: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a nonempty list")
    return [
        require_exact_keys(row, expected_keys, f"{context}[{index}]")
        for index, row in enumerate(value)
    ]


def validate_prevalence_publication(
    value: Any,
    *,
    integrity_first: bool = False,
) -> dict[str, Any]:
    """Validate one standalone prevalence publication before no-clobber write."""

    expected_keys = INTEGRITY_FIRST_KEYS if integrity_first else PREVALENCE_KEYS
    table = require_exact_keys(value, expected_keys, "prevalence publication")
    if table["schema_version"] != 2:
        raise ValueError("prevalence publication schema_version must equal 2")
    expected_status = (
        "INTEGRITY_FIRST_PREVALENCE_COMPLETE_AUTOMATIC_DSP_ONLY"
        if integrity_first
        else "AUTOMATIC_PREVALENCE_COMPLETE"
    )
    if table["status"] != expected_status:
        raise ValueError("prevalence publication status is invalid")
    if integrity_first:
        require_sha256(table["source_snapshot_sha256"], "source_snapshot_sha256")
    _validate_rows(table["rows"], PREVALENCE_ROW_KEYS, "prevalence publication rows")
    validate_automatic_table_language(table, "prevalence publication")
    return table


def validate_evaluator_audit_publication(value: Any) -> dict[str, Any]:
    """Validate a fresh-output discordance table without evaluative claims."""

    table = require_exact_keys(value, EVALUATOR_AUDIT_KEYS, "evaluator-audit publication")
    if table["schema_version"] != 2:
        raise ValueError("evaluator-audit publication schema_version must equal 2")
    if table["status"] != "FRESH_OUTPUT_OPERATIONALIZATION_DISCORDANCE_ONLY":
        raise ValueError("evaluator-audit publication status is invalid")
    rows = _validate_rows(
        table["rows"],
        EVALUATOR_AUDIT_ROW_KEYS,
        "evaluator-audit publication rows",
    )
    validate_automatic_table_language(table, "evaluator-audit publication")
    if any(
        row["interpretation"] != "OPERATIONALIZATION_DISCORDANCE_ONLY"
        or row["reference_basis"] != "FRESH_AUTOMATIC_OUTPUTS_ONLY"
        for row in rows
    ):
        raise ValueError("evaluator-audit publication overstates its automatic reference")
    return table


def validate_candidate_index_publication(value: Any) -> dict[str, Any]:
    """Validate the publication envelope around the strict rater transport."""

    table = require_exact_keys(value, CANDIDATE_INDEX_KEYS, "candidate-index publication")
    if table["schema_version"] != 3:
        raise ValueError("candidate-index publication schema_version must equal 3")
    require_sha256(table["source_ledger_sha256"], "source_ledger_sha256")
    if not isinstance(table["primary_backbones"], list) or not table["primary_backbones"]:
        raise ValueError("candidate-index publication primary_backbones must be nonempty")
    if not isinstance(table["rows"], list) or not table["rows"]:
        raise ValueError("candidate-index publication rows must be nonempty")
    validate_automatic_table_language(table, "candidate-index publication")
    return table


__all__ = [
    "CANDIDATE_INDEX_KEYS",
    "FORBIDDEN_PUBLICATION_TOKENS",
    "WATERMARK",
    "validate_automatic_table_language",
    "validate_candidate_index_publication",
    "validate_evaluator_audit_publication",
    "validate_prevalence_publication",
]

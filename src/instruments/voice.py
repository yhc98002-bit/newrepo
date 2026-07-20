"""Promoted-OR vocal-presence readout with artifact-derived thresholds."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

VOCAL_CLASSES = (
    "Singing",
    "Speech",
    "Male singing",
    "Female singing",
    "Child singing",
    "Choir",
    "Rapping",
    "Human voice",
    "Vocal music",
    "A capella",
)

# This is a fixed signal-validity floor from the benchmark protocol, not a
# learned promotion threshold. The two learned thresholds are loaded below.
MIXTURE_RMS_FLOOR = 10.0**-3
VOICE_MARGIN_LOG2_FLOOR = 1e-12


class PromotedORArtifactError(ValueError):
    """Raised when the canonical promotion artifact or its bind is invalid."""


@dataclass(frozen=True)
class PromotedORConfig:
    """Thresholds parsed from a hash-bound canonical promotion artifact."""

    demucs_threshold: float
    panns_threshold: float
    artifact_sha256: str
    source_repository: str
    source_commit: str
    source_path: str


@dataclass(frozen=True)
class PromotedORDecision:
    """Gate-aware decision and normalized margins from the three raw scalars."""

    demucs_present: bool
    panns_present: bool
    voice_present: bool
    demucs_rms_margin: float
    demucs_ratio_margin: float
    demucs_margin: float
    panns_margin: float
    voice_margin: float


@dataclass(frozen=True)
class PromotedORResult:
    """Automatic instrument result; this is not a human voice label."""

    demucs_present: bool
    panns_present: bool
    voice_present: bool
    mixture_rms: float
    demucs_vocal_energy_ratio: float
    panns_max_vocal_probability: float
    panns_top_vocal_class: str
    demucs_rms_margin: float
    demucs_ratio_margin: float
    demucs_margin: float
    panns_margin: float
    voice_margin: float
    threshold_artifact_sha256: str


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file without changing it."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: object, field: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise PromotedORArtifactError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _finite_probability(value: object, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise PromotedORArtifactError(f"{field} is not numeric") from error
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise PromotedORArtifactError(f"{field} must be finite and in [0, 1]")
    return parsed


def load_promoted_or(
    artifact_path: str | Path,
    *,
    expected_sha256: str,
    source_repository: str,
    source_commit: str,
    source_path: str,
) -> PromotedORConfig:
    """Parse promoted thresholds only after validating the canonical bytes.

    The authoritative values are ``heldout.selected_candidate`` in the old
    repository's promotion result. A redundant selected-candidate copy must
    agree, which rejects ambiguous or partially edited artifacts.
    """

    artifact = Path(artifact_path)
    expected = _require_sha256(expected_sha256, "expected_sha256")
    actual = sha256_file(artifact)
    if actual != expected:
        raise PromotedORArtifactError(
            f"promotion artifact SHA-256 mismatch: expected {expected}, got {actual}"
        )
    try:
        record = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromotedORArtifactError("promotion artifact is not valid UTF-8 JSON") from error
    if not isinstance(record, dict):
        raise PromotedORArtifactError("promotion artifact root must be an object")
    if record.get("CORRECTED_INSTRUMENT_STATUS") != "PROMOTED":
        raise PromotedORArtifactError("canonical instrument is not marked PROMOTED")
    try:
        selected = record["heldout"]["selected_candidate"]
        redundant = record["train_selection"]["selected_candidate"]
    except (KeyError, TypeError) as error:
        raise PromotedORArtifactError(
            "promotion artifact lacks selected-candidate records"
        ) from error
    if not isinstance(selected, dict) or not isinstance(redundant, dict):
        raise PromotedORArtifactError("selected-candidate records must be objects")
    if selected.get("family") != "or" or redundant.get("family") != "or":
        raise PromotedORArtifactError("canonical selected family is not promoted OR")

    demucs = _finite_probability(selected.get("demucs_threshold"), "demucs_threshold")
    panns = _finite_probability(selected.get("panns_threshold"), "panns_threshold")
    redundant_demucs = _finite_probability(
        redundant.get("demucs_threshold"), "redundant demucs_threshold"
    )
    redundant_panns = _finite_probability(
        redundant.get("panns_threshold"), "redundant panns_threshold"
    )
    if demucs != redundant_demucs or panns != redundant_panns:
        raise PromotedORArtifactError("selected-candidate threshold copies disagree")

    if not source_repository or not source_commit or not source_path:
        raise PromotedORArtifactError("source repository, commit, and path are required")
    return PromotedORConfig(
        demucs_threshold=demucs,
        panns_threshold=panns,
        artifact_sha256=actual,
        source_repository=source_repository,
        source_commit=source_commit,
        source_path=source_path,
    )


def load_promoted_or_from_manifest(manifest_path: str | Path) -> PromotedORConfig:
    """Load the exact vendored old-repository artifact named by a manifest."""

    manifest_file = Path(manifest_path)
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromotedORArtifactError("source manifest is not valid UTF-8 JSON") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != "benchmark.b1.voice-source.v1":
        raise PromotedORArtifactError("unexpected promoted-OR source-manifest schema")
    artifact_record = manifest.get("promotion_artifact")
    source = manifest.get("source")
    implementation = manifest.get("reference_implementation")
    if not all(isinstance(value, dict) for value in (artifact_record, source, implementation)):
        raise PromotedORArtifactError("source manifest is incomplete")
    assert isinstance(artifact_record, dict)
    assert isinstance(source, dict)
    assert isinstance(implementation, dict)
    _require_sha256(implementation.get("sha256"), "reference implementation sha256")
    relative_path = artifact_record.get("vendored_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise PromotedORArtifactError("manifest vendored_path must be a non-empty string")
    artifact = (manifest_file.parent / relative_path).resolve()
    return load_promoted_or(
        artifact,
        expected_sha256=str(artifact_record.get("sha256", "")),
        source_repository=str(source.get("repository", "")),
        source_commit=str(source.get("commit", "")),
        source_path=str(artifact_record.get("source_path", "")),
    )


def _stable_log2_ratio(value: float, threshold: float) -> float:
    """Return a finite, symmetric threshold margin with a stable zero floor."""

    return math.log2(max(value, VOICE_MARGIN_LOG2_FLOOR) / threshold)


def score_promoted_or_raw(
    config: PromotedORConfig,
    *,
    mixture_rms: float,
    demucs_vocal_energy_ratio: float,
    panns_max_vocal_probability: float,
) -> PromotedORDecision:
    """Recompute the promoted OR and its exact gate-aware combined margin.

    Demucs is an AND gate, so its margin is the minimum of the normalized RMS
    and vocal-energy-ratio margins. The final promoted OR uses their maximum
    with the PANNs margin. Consequently ``voice_margin >= 0`` is exactly the
    inclusive promoted-OR decision, including the near-silence RMS gate.
    """

    rms = float(mixture_rms)
    ratio = float(demucs_vocal_energy_ratio)
    panns_max = _finite_probability(panns_max_vocal_probability, "panns_max_vocal_probability")
    if not math.isfinite(rms) or rms < 0.0:
        raise ValueError("mixture_rms must be finite and nonnegative")
    if not math.isfinite(ratio) or ratio < 0.0:
        raise ValueError("demucs_vocal_energy_ratio must be finite and nonnegative")

    demucs_rms_margin = _stable_log2_ratio(rms, MIXTURE_RMS_FLOOR)
    demucs_ratio_margin = _stable_log2_ratio(ratio, config.demucs_threshold)
    demucs_margin = min(demucs_rms_margin, demucs_ratio_margin)
    panns_margin = _stable_log2_ratio(panns_max, config.panns_threshold)
    voice_margin = max(demucs_margin, panns_margin)
    demucs_present = rms >= MIXTURE_RMS_FLOOR and ratio >= config.demucs_threshold
    panns_present = panns_max >= config.panns_threshold
    voice_present = demucs_present or panns_present
    if voice_present is not (voice_margin >= 0.0):
        raise RuntimeError("gate-aware voice margin disagrees with promoted OR")
    return PromotedORDecision(
        demucs_present=demucs_present,
        panns_present=panns_present,
        voice_present=voice_present,
        demucs_rms_margin=demucs_rms_margin,
        demucs_ratio_margin=demucs_ratio_margin,
        demucs_margin=demucs_margin,
        panns_margin=panns_margin,
        voice_margin=voice_margin,
    )


def score_promoted_or(
    config: PromotedORConfig,
    *,
    mixture_rms: float,
    demucs_vocal_energy_ratio: float,
    panns_probabilities: Mapping[str, float],
) -> PromotedORResult:
    """Apply the inclusive Demucs OR PANNs automatic readout."""

    rms = float(mixture_rms)
    ratio = float(demucs_vocal_energy_ratio)
    if not math.isfinite(rms) or rms < 0.0:
        raise ValueError("mixture_rms must be finite and nonnegative")
    if not math.isfinite(ratio) or ratio < 0.0:
        raise ValueError("demucs_vocal_energy_ratio must be finite and nonnegative")
    missing = [label for label in VOCAL_CLASSES if label not in panns_probabilities]
    if missing:
        raise ValueError(f"PANNs probabilities omit frozen vocal classes: {missing}")
    frozen_scores = {
        label: _finite_probability(panns_probabilities[label], f"PANNs probability {label!r}")
        for label in VOCAL_CLASSES
    }
    top_label, top_probability = max(frozen_scores.items(), key=lambda item: (item[1], item[0]))
    decision = score_promoted_or_raw(
        config,
        mixture_rms=rms,
        demucs_vocal_energy_ratio=ratio,
        panns_max_vocal_probability=top_probability,
    )
    return PromotedORResult(
        demucs_present=decision.demucs_present,
        panns_present=decision.panns_present,
        voice_present=decision.voice_present,
        mixture_rms=rms,
        demucs_vocal_energy_ratio=ratio,
        panns_max_vocal_probability=top_probability,
        panns_top_vocal_class=top_label,
        demucs_rms_margin=decision.demucs_rms_margin,
        demucs_ratio_margin=decision.demucs_ratio_margin,
        demucs_margin=decision.demucs_margin,
        panns_margin=decision.panns_margin,
        voice_margin=decision.voice_margin,
        threshold_artifact_sha256=config.artifact_sha256,
    )

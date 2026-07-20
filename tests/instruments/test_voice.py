from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from instruments.voice import (
    MIXTURE_RMS_FLOOR,
    VOCAL_CLASSES,
    PromotedORArtifactError,
    load_promoted_or,
    load_promoted_or_from_manifest,
    score_promoted_or,
    score_promoted_or_raw,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "provenance" / "b1" / "voice_source_manifest.json"


def _scores(value: float = 0.0) -> dict[str, float]:
    return dict.fromkeys(VOCAL_CLASSES, value)


def test_canonical_artifact_is_hash_bound_and_source_identified() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    artifact = MANIFEST.parent / manifest["promotion_artifact"]["vendored_path"]
    expected = manifest["promotion_artifact"]["sha256"]
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected
    assert expected == "2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2"
    assert manifest["source"] == {
        "repository": "https://github.com/yhc98002-bit/Audio.git",
        "commit": "062d75f4c235ebf306d42e215a74cfbf8c5afe87",
    }
    assert manifest["reference_implementation"]["sha256"] == (
        "3aa68674b9ce919d407f25070a93ca73f14ed39af36f41090a4db000b5df1524"
    )

    config = load_promoted_or_from_manifest(MANIFEST)
    canonical = json.loads(artifact.read_text(encoding="utf-8"))["heldout"]["selected_candidate"]
    assert config.demucs_threshold == canonical["demucs_threshold"]
    assert config.panns_threshold == canonical["panns_threshold"]


def test_learned_thresholds_are_not_hard_coded_in_instrument_source() -> None:
    instrument_sources = sorted((ROOT / "src" / "instruments").glob("*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in instrument_sources)
    assert "0.03161777090281248" not in source
    assert "0.04403413645923138" not in source


def test_loader_really_parses_thresholds_instead_of_substituting_constants(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    artifact = MANIFEST.parent / manifest["promotion_artifact"]["vendored_path"]
    record = json.loads(artifact.read_text(encoding="utf-8"))
    for branch in (record["heldout"], record["train_selection"]):
        branch["selected_candidate"]["demucs_threshold"] = 0.123
        branch["selected_candidate"]["panns_threshold"] = 0.456
    alternate = tmp_path / "alternate.json"
    alternate.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    digest = hashlib.sha256(alternate.read_bytes()).hexdigest()
    parsed = load_promoted_or(
        alternate,
        expected_sha256=digest,
        source_repository="fixture",
        source_commit="fixture",
        source_path="fixture",
    )
    assert (parsed.demucs_threshold, parsed.panns_threshold) == (0.123, 0.456)


def test_tampered_artifact_and_disagreeing_duplicate_are_rejected(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    artifact = MANIFEST.parent / manifest["promotion_artifact"]["vendored_path"]
    tampered = tmp_path / "tampered.json"
    tampered.write_bytes(artifact.read_bytes() + b"\n")
    with pytest.raises(PromotedORArtifactError, match="SHA-256 mismatch"):
        load_promoted_or(
            tampered,
            expected_sha256=manifest["promotion_artifact"]["sha256"],
            source_repository="fixture",
            source_commit="fixture",
            source_path="fixture",
        )

    record = json.loads(artifact.read_text(encoding="utf-8"))
    record["train_selection"]["selected_candidate"]["panns_threshold"] = 0.5
    inconsistent = tmp_path / "inconsistent.json"
    inconsistent.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    digest = hashlib.sha256(inconsistent.read_bytes()).hexdigest()
    with pytest.raises(PromotedORArtifactError, match="copies disagree"):
        load_promoted_or(
            inconsistent,
            expected_sha256=digest,
            source_repository="fixture",
            source_commit="fixture",
            source_path="fixture",
        )


def test_promoted_or_is_inclusive_and_preserves_near_silence_guard() -> None:
    config = load_promoted_or_from_manifest(MANIFEST)
    panns = _scores()
    panns["Singing"] = config.panns_threshold
    result = score_promoted_or(
        config,
        mixture_rms=MIXTURE_RMS_FLOOR,
        demucs_vocal_energy_ratio=config.demucs_threshold,
        panns_probabilities=panns,
    )
    assert result.demucs_present is True
    assert result.panns_present is True
    assert result.voice_present is True
    assert result.demucs_rms_margin == pytest.approx(0.0)
    assert result.demucs_ratio_margin == pytest.approx(0.0)
    assert result.demucs_margin == pytest.approx(0.0)
    assert result.panns_margin == pytest.approx(0.0)
    assert result.voice_margin == pytest.approx(0.0)
    assert result.threshold_artifact_sha256 == config.artifact_sha256

    near_silent = score_promoted_or(
        config,
        mixture_rms=MIXTURE_RMS_FLOOR / 2.0,
        demucs_vocal_energy_ratio=config.demucs_threshold * 10.0,
        panns_probabilities=_scores(),
    )
    assert near_silent.demucs_present is False
    assert near_silent.voice_present is False
    assert near_silent.demucs_ratio_margin > 0.0
    assert near_silent.demucs_rms_margin < 0.0
    assert near_silent.demucs_margin < 0.0
    assert near_silent.voice_margin < 0.0


def test_gate_aware_raw_margin_recomputes_and_cannot_ignore_rms_gate() -> None:
    config = load_promoted_or_from_manifest(MANIFEST)
    decision = score_promoted_or_raw(
        config,
        mixture_rms=MIXTURE_RMS_FLOOR / 4,
        demucs_vocal_energy_ratio=config.demucs_threshold * 8,
        panns_max_vocal_probability=config.panns_threshold / 2,
    )
    assert decision.demucs_ratio_margin == pytest.approx(3.0)
    assert decision.demucs_rms_margin == pytest.approx(-2.0)
    assert decision.demucs_margin == pytest.approx(-2.0)
    assert decision.panns_margin == pytest.approx(-1.0)
    assert decision.voice_margin == pytest.approx(-1.0)
    assert decision.voice_present is False

    panns_rescue = score_promoted_or_raw(
        config,
        mixture_rms=0.0,
        demucs_vocal_energy_ratio=0.0,
        panns_max_vocal_probability=config.panns_threshold * 2,
    )
    assert panns_rescue.panns_margin == pytest.approx(1.0)
    assert panns_rescue.voice_margin == pytest.approx(1.0)
    assert panns_rescue.voice_present is True


def test_panns_max_uses_exact_frozen_class_set_and_rejects_missing_class() -> None:
    config = load_promoted_or_from_manifest(MANIFEST)
    panns = _scores()
    panns["Rapping"] = min(1.0, config.panns_threshold + 0.1)
    panns["Not a frozen vocal class"] = 1.0
    result = score_promoted_or(
        config,
        mixture_rms=0.1,
        demucs_vocal_energy_ratio=0.0,
        panns_probabilities=panns,
    )
    assert result.panns_top_vocal_class == "Rapping"
    assert result.panns_present is True

    del panns["Choir"]
    with pytest.raises(ValueError, match="omit frozen vocal classes"):
        score_promoted_or(
            config,
            mixture_rms=0.1,
            demucs_vocal_energy_ratio=0.0,
            panns_probabilities=panns,
        )

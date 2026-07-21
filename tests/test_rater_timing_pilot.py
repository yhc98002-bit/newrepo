from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from instruments.integrity import DropoutCandidateMetrics, score_integrity_raw_metrics
from instruments.voice import score_promoted_or_raw
from rater.build_human_packet import (
    VOICE_CONFIG,
    _build_layout,
    assemble_human_packet,
    packet_gate,
    select_human_packet,
    validate_packet_audio_duration,
)
from rater.build_timing_pilot import build, collect_build_inputs
from rater.bundle_common import StrictJSONError, sha256_file
from rater.ingest_timing_pilot import ingest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "rater" / "schema_v2.json"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _source_config(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    audio_path = tmp_path / "retained.wav"
    seconds = np.arange(30_000, dtype=np.float32) / 1000.0
    mono = 0.1 * np.sin(2 * np.pi * 7 * seconds)
    sf.write(audio_path, np.column_stack([mono, mono]), 1000, subtype="FLOAT")
    digest = sha256_file(audio_path)
    presentations = []
    tasks = [
        "tempo_tap",
        "tempo_tap",
        "voice_stress",
        "voice_stress",
        "integrity_audit",
        "tempo_tap",
        "voice_stress",
    ]
    for index, task in enumerate(tasks, start=1):
        presentations.append(
            {
                "presentation_id": f"pilot-{index:03d}",
                "source_path": str(audio_path),
                "source_sha256": digest,
                "task": task,
            }
        )
    for index, original in ((8, 1), (9, 5)):
        presentations.append(
            {
                "presentation_id": f"pilot-{index:03d}",
                "repeat_of": f"pilot-{original:03d}",
                "source_path": str(audio_path),
                "source_sha256": digest,
                "task": presentations[original - 1]["task"],
            }
        )
    source_path = tmp_path / "source.json"
    _write_json(
        source_path,
        {
            "bundle_id": "pilot-test-02",
            "expected_minutes": 15,
            "presentation_order": [
                "pilot-001",
                "pilot-003",
                "pilot-005",
                "pilot-002",
                "pilot-008",
                "pilot-004",
                "pilot-006",
                "pilot-009",
                "pilot-007",
            ],
            "presentations": presentations,
            "schema_version": 2,
            "source_scope": "retained_foundation_audio_only_no_model_calls",
            "supersedes": {"status": "TEST_ONLY"},
        },
    )
    template_path = tmp_path / "template.html"
    template_path.write_text(
        "<script>const bundle = __EMBEDDED_PUBLIC_BUNDLE_JSON__;</script>\n",
        encoding="utf-8",
    )
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return source_path, template_path, schema_path, audio_path


def _fake_bundle(tmp_path: Path) -> Path:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    tasks = ["tempo_tap"] * 4 + ["voice_stress"] * 2 + ["integrity_audit"] * 2
    _write_json(
        bundle_dir / "bundle.json",
        {
            "build_identity_sha256": "a" * 64,
            "bundle_id": "pilot-test",
            "expected_minutes": 15,
            "items": [
                {
                    "audio": f"audio/item-{index:03d}.wav",
                    "item_id": f"item-{index:03d}",
                    "task": task,
                }
                for index, task in enumerate(tasks, start=1)
            ],
            "purpose": "BLINDED_TIMING_PILOT",
            "response_schema_version": 2,
            "schema_version": 2,
        },
    )
    return bundle_dir


def _valid_response(bundle_dir: Path) -> dict:
    bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    rows = []
    for item in bundle["items"]:
        task = item["task"]
        taps: list[float] = []
        response: object
        if task == "tempo_tap":
            taps = [*map(float, range(2, 10)), *map(float, range(16, 24))]
            response = {"first_window_tap_count": 8, "second_window_tap_count": 8}
        elif task == "voice_stress":
            response = "present"
        else:
            response = {
                "defect_labels": ["clean"],
                "intentional_musical_content": False,
            }
        rows.append(
            {
                "completed_full_playback": True,
                "elapsed_seconds": 31.0,
                "item_id": item["item_id"],
                "play_events": 1,
                "playback_coverage_seconds": 30.0,
                "response": response,
                "taps_seconds": taps,
                "task": task,
            }
        )
    return {
        "build_identity_sha256": bundle["build_identity_sha256"],
        "bundle_id": bundle["bundle_id"],
        "completed_at_utc": "2026-07-20T12:00:00Z",
        "responses": rows,
        "schema_version": 2,
        "session_elapsed_seconds": 253.0,
        "status": "COMPLETE",
        "user_agent": "pytest-browser",
    }


def _write_attestation(
    path: Path,
    bundle_dir: Path,
    response_path: Path,
    response: dict,
    *,
    usability_status: str = "PASS",
    protocol_deviations: list[str] | None = None,
) -> Path:
    bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    timing = schema["timing_pilot"]
    _write_json(
        path,
        {
            "actual_minutes": response["session_elapsed_seconds"] / 60.0,
            "affirmation": timing["attestation_affirmation"],
            "attestation_schema_version": 1,
            "build_identity_sha256": bundle["build_identity_sha256"],
            "bundle_id": bundle["bundle_id"],
            "pi_identity": timing["required_pi_identity"],
            "protocol_deviations": protocol_deviations or [],
            "response_sha256": sha256_file(response_path),
            "signature": timing["required_pi_identity"],
            "signed_at_utc": "2026-07-20T12:01:00Z",
            "usability_status": usability_status,
        },
    )
    return path


def test_frozen_source_order_has_two_nonadjacent_hidden_repeats() -> None:
    source = json.loads(
        (ROOT / "rater" / "timing_pilot_v2.source.json").read_text(encoding="utf-8")
    )
    assert source["bundle_id"].endswith("-04")
    assert source["supersedes"]["bundle_id"].endswith("-03")
    assert source["source_scope"] == "retained_foundation_audio_only_no_model_calls"
    assert source["expected_minutes"] == 15
    assert len(source["presentations"]) == 9
    by_id = {row["presentation_id"]: row for row in source["presentations"]}
    positions = {item_id: index for index, item_id in enumerate(source["presentation_order"])}
    repeats = [row for row in source["presentations"] if "repeat_of" in row]
    assert len(repeats) == 2
    for repeat in repeats:
        assert positions[repeat["presentation_id"]] - positions[repeat["repeat_of"]] > 1
        assert repeat["source_sha256"] == by_id[repeat["repeat_of"]]["source_sha256"]


def test_build_identity_covers_every_build_input_and_audio(tmp_path: Path) -> None:
    source, template, schema, _audio = _source_config(tmp_path)
    _, inputs_before, _ = collect_build_inputs(source, template, schema)
    assert set(inputs_before["files"]) == {
        "builder",
        "bundle_common",
        "rater_schema",
        "source_config",
        "ui_template",
    }
    assert len(inputs_before["source_audio_sha256"]) == 9
    template.write_text(
        template.read_text(encoding="utf-8") + "<!-- identity change -->\n",
        encoding="utf-8",
    )
    _, inputs_after, _ = collect_build_inputs(source, template, schema)
    assert inputs_before != inputs_after


def test_bundle_is_file_url_self_contained_and_admin_is_private(tmp_path: Path) -> None:
    source, _template, schema, audio = _source_config(tmp_path)
    output_root = tmp_path / "public"
    admin_root = tmp_path / "private"
    result = build(
        source,
        output_root,
        admin_root=admin_root,
        template_path=ROOT / "rater" / "timing_pilot.html",
        schema_path=schema,
    )
    bundle_dir = Path(result["bundle_dir"])
    admin_dir = Path(result["admin_dir"])
    assert bundle_dir.parent == output_root
    assert admin_dir.parent == admin_root
    assert not (bundle_dir / "admin-map.json").exists()
    assert (admin_dir / "admin-map.json").is_file()
    public_text = "\n".join(
        path.read_text(encoding="utf-8") for path in bundle_dir.iterdir() if path.is_file()
    )
    assert str(audio) not in public_text
    assert "repeat_of" not in public_text
    html = (bundle_dir / "index.html").read_text(encoding="utf-8")
    assert "__EMBEDDED_PUBLIC_BUNDLE_JSON__" not in html
    assert "new URL(item.audio, window.location.href)" in html
    match = re.search(r"const bundle = (\{.*?\});\n", html)
    assert match is not None
    assert json.loads(match.group(1)) == json.loads(
        (bundle_dir / "bundle.json").read_text(encoding="utf-8")
    )
    assert bundle_dir.name.endswith(result["build_identity_sha256"][:12])
    with pytest.raises(FileExistsError):
        build(
            source,
            output_root,
            admin_root=admin_root,
            template_path=ROOT / "rater" / "timing_pilot.html",
            schema_path=schema,
        )


def test_strict_ingestion_and_budget_gate(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    response_path = tmp_path / "response.json"
    response = _valid_response(bundle)
    _write_json(response_path, response)
    attestation = _write_attestation(tmp_path / "attestation.json", bundle, response_path, response)
    receipt = ingest(
        bundle,
        response_path,
        tmp_path / "receipt",
        attestation_path=attestation,
    )
    assert receipt["status"] == "TIMING_PILOT_INGESTED"
    assert receipt["total_minutes"] == pytest.approx(253 / 60)
    assert receipt["pi_identity"] == "pxy1289"
    assert receipt["pi_signature"] == "pxy1289"
    assert receipt["attestation_sha256"] == sha256_file(attestation)
    gate = packet_gate(bundle, tmp_path / "receipt" / "receipt.json")
    assert gate["PACKET_ASSEMBLY_STATUS"] == "READY_TO_ASSEMBLE"
    assert gate["planned_presentations"] == 171
    assert gate["projected_minutes"] < 180
    assert packet_gate(bundle, None)["PACKET_ASSEMBLY_STATUS"] == (
        "BLOCKED_ON_TIMING_PILOT_INGESTION"
    )


@pytest.mark.parametrize(
    ("usability_status", "deviations", "message"),
    [
        ("FAIL", [], "does not mark"),
        ("PASS", ["headphones disconnected"], "records protocol deviations"),
    ],
)
def test_ingestion_requires_clean_signed_pi_attestation(
    tmp_path: Path,
    usability_status: str,
    deviations: list[str],
    message: str,
) -> None:
    bundle = _fake_bundle(tmp_path)
    response = _valid_response(bundle)
    response_path = tmp_path / "response.json"
    _write_json(response_path, response)
    with pytest.raises(ValueError, match="signed PI"):
        ingest(bundle, response_path, tmp_path / "missing", attestation_path=None)
    attestation = _write_attestation(
        tmp_path / "attestation.json",
        bundle,
        response_path,
        response,
        usability_status=usability_status,
        protocol_deviations=deviations,
    )
    with pytest.raises(ValueError, match=message):
        ingest(
            bundle,
            response_path,
            tmp_path / "rejected",
            attestation_path=attestation,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(signature="somebody-else"), "signature"),
        (lambda value: value.update(actual_minutes=99.0), "actual minutes disagree"),
    ],
)
def test_ingestion_rejects_forged_or_timer_mismatched_attestation(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    bundle = _fake_bundle(tmp_path)
    response = _valid_response(bundle)
    response_path = tmp_path / "response.json"
    _write_json(response_path, response)
    attestation = _write_attestation(
        tmp_path / "attestation.json", bundle, response_path, response
    )
    attestation_value = json.loads(attestation.read_text(encoding="utf-8"))
    mutation(attestation_value)
    _write_json(attestation, attestation_value)
    with pytest.raises(ValueError, match=message):
        ingest(
            bundle,
            response_path,
            tmp_path / "rejected",
            attestation_path=attestation,
        )


def test_integrity_intentional_content_is_nonexclusive_but_strict(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    response = _valid_response(bundle)
    integrity = next(row for row in response["responses"] if row["task"] == "integrity_audit")
    integrity["response"] = {
        "defect_labels": ["crackle"],
        "intentional_musical_content": True,
    }
    response_path = tmp_path / "response.json"
    _write_json(response_path, response)
    attestation = _write_attestation(tmp_path / "attestation.json", bundle, response_path, response)
    receipt = ingest(
        bundle,
        response_path,
        tmp_path / "receipt",
        attestation_path=attestation,
    )
    assert receipt["status"] == "TIMING_PILOT_INGESTED"

    response = _valid_response(bundle)
    integrity = next(row for row in response["responses"] if row["task"] == "integrity_audit")
    integrity["response"] = {
        "defect_labels": ["clean", "crackle"],
        "intentional_musical_content": True,
    }
    response_path = tmp_path / "bad-response.json"
    _write_json(response_path, response)
    attestation = _write_attestation(
        tmp_path / "bad-attestation.json", bundle, response_path, response
    )
    with pytest.raises(ValueError, match="defect labels only"):
        ingest(
            bundle,
            response_path,
            tmp_path / "bad-receipt",
            attestation_path=attestation,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(status="STOPPED_EARLY"), "COMPLETE"),
        (
            lambda value: value["responses"][0].update(completed_full_playback=False),
            "completed_full_playback",
        ),
        (
            lambda value: value["responses"][0].update(playback_coverage_seconds=20),
            "full 30-second",
        ),
        (
            lambda value: value["responses"][0].update(
                taps_seconds=[*map(float, range(16, 24)), *map(float, range(2, 10))]
            ),
            "monotonically",
        ),
        (
            lambda value: value["responses"][0].update(
                taps_seconds=[*map(float, range(2, 10)), *map(float, range(16, 23)), 29.0]
            ),
            "tap window",
        ),
        (
            lambda value: value["responses"][0]["response"].update(first_window_tap_count=7),
            "tap counts",
        ),
    ],
)
def test_ingestion_rejects_protocol_violations(tmp_path: Path, mutation, message: str) -> None:
    bundle = _fake_bundle(tmp_path)
    response = _valid_response(bundle)
    mutation(response)
    response_path = tmp_path / "response.json"
    _write_json(response_path, response)
    attestation = _write_attestation(tmp_path / "attestation.json", bundle, response_path, response)
    with pytest.raises(ValueError, match=message):
        ingest(
            bundle,
            response_path,
            tmp_path / "receipt",
            attestation_path=attestation,
        )


def test_ingestion_rejects_ambiguous_or_nonfinite_json(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    response = _valid_response(bundle)
    response_path = tmp_path / "nan.json"
    text = json.dumps(response).replace(
        '"session_elapsed_seconds": 253.0', '"session_elapsed_seconds": NaN'
    )
    response_path.write_text(text, encoding="utf-8")
    with pytest.raises(StrictJSONError, match="non-finite"):
        ingest(
            bundle,
            response_path,
            tmp_path / "receipt-a",
            attestation_path=None,
        )
    response_path = tmp_path / "duplicate.json"
    response_path.write_text(
        json.dumps(response)[:-1] + ', "status": "COMPLETE"}', encoding="utf-8"
    )
    with pytest.raises(StrictJSONError, match="duplicate"):
        ingest(
            bundle,
            response_path,
            tmp_path / "receipt-b",
            attestation_path=None,
        )


def _base_row(row_id: str, backbone: str, axis: str, condition: str) -> dict:
    return {
        "audio_path": f"audio/{row_id}.wav",
        "audio_sha256": hashlib.sha256(row_id.encode()).hexdigest(),
        "axis": axis,
        "backbone": backbone,
        "cluster_id": f"cluster-{row_id}",
        "condition": condition,
        "defects": None,
        "demucs_vocal_energy_ratio": None,
        "demucs_present": None,
        "integrity_raw": None,
        "integrity_profile": None,
        "mixture_rms": None,
        "panns_max_vocal_probability": None,
        "panns_present": None,
        "prompt_id": f"prompt-{row_id}",
        "request": None,
        "row_id": row_id,
        "salience": None,
        "seed_index": int(hashlib.sha256(row_id.encode()).hexdigest()[:4], 16),
        "target_bpm": None,
        "tempo_e_oct": None,
        "tempo_primary_pass": None,
        "tempo_status": None,
        "voice_margin": None,
        "voice_present": None,
    }


def _voice_raw(pattern: int, index: int) -> dict[str, object]:
    factor = 1.0 + abs(index - 10) / 10 + 0.01
    demucs_on = pattern in {0, 2}
    panns_on = pattern in {1, 2}
    raw = {
        "mixture_rms": 0.001 * (factor if demucs_on else 0.5),
        "demucs_vocal_energy_ratio": VOICE_CONFIG.demucs_threshold * (factor if demucs_on else 0.5),
        "panns_max_vocal_probability": min(
            1.0,
            VOICE_CONFIG.panns_threshold * (factor if panns_on else 0.5),
        ),
    }
    decision = score_promoted_or_raw(VOICE_CONFIG, **raw)
    return {
        **raw,
        "demucs_present": decision.demucs_present,
        "panns_present": decision.panns_present,
        "voice_margin": decision.voice_margin,
        "voice_present": decision.voice_present,
    }


def _integrity_raw(defect: str | None, side: str, index: int) -> tuple[dict, dict]:
    dropout_candidates: list[DropoutCandidateMetrics] = []
    raw: dict[str, object] = {
        "all_sample_rms": 0.1,
        "dropout_candidates": dropout_candidates,
        "hard_clipped_fraction": 0.0,
        "longest_hard_clip_run_samples": 0,
        "maximum_channel_crackle_count": 0,
        "silent_frame_fraction": 0.0,
        "true_peak": 0.5,
    }
    if defect == "clipping":
        raw["true_peak"] = 1.1 + index / 10 if side == "flagged" else 0.999 - index / 100
    elif defect == "dropout":
        dropout_candidates.append(
            DropoutCandidateMetrics(
                duration_ms=(60.0 + index) if side == "flagged" else (49.0 - index),
                left_boundary_ms=500.0,
                right_boundary_ms=500.0,
                left_level_dbfs=-20.0,
                right_level_dbfs=-20.0,
                low_level_dbfs=-100.0,
            )
        )
    elif defect == "silence":
        raw["silent_frame_fraction"] = (
            0.91 + index / 100 if side == "flagged" else 0.899 - index / 100
        )
    elif defect == "crackle":
        raw["maximum_channel_crackle_count"] = 3 + index if side == "flagged" else 2
    elif defect is None and side == "sharp":
        raw["maximum_channel_crackle_count"] = 2
    scored = score_integrity_raw_metrics(**raw)
    exported = {
        **raw,
        "dropout_candidates": [candidate.to_dict() for candidate in dropout_candidates],
    }
    return exported, scored["defects"]


def _candidate_index() -> tuple[dict, dict]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rows = []
    for backbone_index, backbone in enumerate(schema["human_packet"]["primary_backbones"]):
        for request, conditions in (
            ("vocal", ("BASE", "FIXED")),
            ("instrumental", ("BASE", "FIXED", "NEGATION_DIAGNOSTIC")),
        ):
            for condition in conditions:
                for index in range(20):
                    row = _base_row(
                        f"v-{backbone_index}-{request}-{condition}-{index}",
                        backbone,
                        "voice",
                        condition,
                    )
                    pattern = index % 4
                    row.update(
                        request=request,
                        **_voice_raw(pattern, index),
                    )
                    rows.append(row)
        for condition in ("BASE", "FIXED"):
            categories = [
                ("boundary", 12),
                ("unresolved", 12),
                ("far-pass", 8),
                ("far-fail", 8),
            ]
            for category, count in categories:
                for index in range(count):
                    row = _base_row(
                        f"t-{backbone_index}-{condition}-{category}-{index}",
                        backbone,
                        "tempo",
                        condition,
                    )
                    row.update(
                        salience=(
                            "percussive_regular",
                            "syncopated",
                            "legato_light_percussion",
                        )[index % 3],
                        target_bpm=60 + 12 * (index % 10),
                    )
                    if category == "unresolved":
                        row["tempo_status"] = (
                            "ESTIMATOR_DISAGREEMENT" if index % 2 == 0 else "ESTIMATOR_INVALID"
                        )
                    else:
                        if category == "boundary":
                            error = math.log2(1.05) + (index - 6) / 10000
                        elif category == "far-pass":
                            error = 0.001 + index / 10000
                        else:
                            error = 0.2 + index / 1000
                        row.update(
                            tempo_e_oct=error,
                            tempo_primary_pass=error <= math.log2(1.05),
                            tempo_status="RESOLVED",
                        )
                    rows.append(row)
        for condition in ("BASE", "FIXED"):
            for defect in ("clipping", "dropout", "silence", "crackle"):
                for side in ("flagged", "clean"):
                    for index in range(2):
                        row = _base_row(
                            f"i-{backbone_index}-{condition}-{defect}-{side}-{index}",
                            backbone,
                            "integrity",
                            condition,
                        )
                        raw, defects = _integrity_raw(defect, side, index)
                        row.update(
                            defects=defects,
                            integrity_profile="dense_loud",
                            integrity_raw=raw,
                        )
                        rows.append(row)
            for index in range(3):
                row = _base_row(
                    f"i-{backbone_index}-{condition}-sharp-{index}",
                    backbone,
                    "integrity",
                    condition,
                )
                raw, defects = _integrity_raw(None, "sharp", index)
                row.update(
                    defects=defects,
                    integrity_profile="sharp_percussive_control",
                    integrity_raw=raw,
                )
                rows.append(row)
    return {
        "primary_backbones": schema["human_packet"]["primary_backbones"],
        "rows": rows,
        "schema_version": 2,
        "source_ledger_sha256": "b" * 64,
    }, schema


def test_selector_is_deterministic_balanced_stratified_and_repeatable() -> None:
    candidate, schema = _candidate_index()
    first = select_human_packet(candidate, schema)
    reversed_index = {**candidate, "rows": list(reversed(candidate["rows"]))}
    second = select_human_packet(reversed_index, schema)
    assert first == second
    assert first["selection_status"] == "COMPLETE"
    for backbone in schema["human_packet"]["primary_backbones"]:
        rows = [row for row in first["selected"] if row["backbone"] == backbone]
        assert Counter(row["rating_task"] for row in rows) == {
            "voice_stress": 12,
            "tempo_tap": 30,
            "integrity_audit": 10,
        }
        voice = [row for row in rows if row["axis"] == "voice"]
        assert Counter(row["request"] for row in voice) == {"vocal": 6, "instrumental": 6}
        assert Counter(row["condition"] for row in voice if row["request"] == "vocal") == {
            "BASE": 3,
            "FIXED": 3,
        }
        assert Counter(row["condition"] for row in voice if row["request"] == "instrumental") == {
            "BASE": 2,
            "FIXED": 2,
            "NEGATION_DIAGNOSTIC": 2,
        }
        tempo = [row for row in rows if row["axis"] == "tempo"]
        assert Counter(row["condition"] for row in tempo) == {"BASE": 15, "FIXED": 15}
        integrity = [row for row in rows if row["axis"] == "integrity"]
        assert Counter(row["condition"] for row in integrity) == {"BASE": 5, "FIXED": 5}
        assert sum(":flagged" in row["selector_stratum"] for row in integrity) == 4
        assert sum(":clean_side" in row["selector_stratum"] for row in integrity) == 4
        assert sum(row["selector_stratum"].startswith("sharp_") for row in integrity) == 2

    layout = _build_layout(first, schema["human_packet"])
    assert layout["unique_count"] == 156
    assert layout["repeat_count"] == 15
    assert not layout["missing_repeats"]
    entries = layout["entries"]
    assert len(entries) == 171
    for index, entry in enumerate(entries):
        if entry["is_repeat"]:
            originals = [
                candidate_entry
                for candidate_entry in entries[:index]
                if not candidate_entry["is_repeat"]
                and candidate_entry["row"]["row_id"] == entry["repeat_of_row_id"]
            ]
            assert originals
            assert index == 0 or entries[index - 1]["row"]["row_id"] != entry["repeat_of_row_id"]
            assert entry["block"] > originals[0]["block"]


def test_candidate_transport_recomputes_voice_and_integrity_margins() -> None:
    candidate, schema = _candidate_index()
    voice = next(row for row in candidate["rows"] if row["axis"] == "voice")
    voice["voice_margin"] += 0.01
    with pytest.raises(ValueError, match="voice_margin disagrees"):
        select_human_packet(candidate, schema)

    candidate, schema = _candidate_index()
    integrity = next(row for row in candidate["rows"] if row["axis"] == "integrity")
    integrity["defects"]["clipping"]["margin"] += 0.01
    with pytest.raises(ValueError, match="clipping.margin disagrees"):
        select_human_packet(candidate, schema)

    candidate, schema = _candidate_index()
    voice = next(row for row in candidate["rows"] if row["axis"] == "voice")
    voice["mixture_rms"] = 0.0
    with pytest.raises(ValueError, match="canonical raw recomputation"):
        select_human_packet(candidate, schema)


def test_integrity_severity_outranks_cluster_diversity() -> None:
    candidate, schema = _candidate_index()
    for backbone in schema["human_packet"]["primary_backbones"]:
        high_rows = [
            row
            for row in candidate["rows"]
            if row["axis"] == "integrity"
            and row["backbone"] == backbone
            and any(entry["flag"] for entry in row["defects"].values())
            and row["row_id"].endswith("-1")
        ]
        for row in high_rows:
            row["cluster_id"] = f"shared-high-severity-{backbone}"

    selected = select_human_packet(candidate, schema)["selected"]
    for backbone in schema["human_packet"]["primary_backbones"]:
        for defect in ("clipping", "dropout", "silence", "crackle"):
            chosen = next(
                row
                for row in selected
                if row["backbone"] == backbone and row["selector_stratum"] == f"{defect}:flagged"
            )
            eligible = [
                row
                for row in candidate["rows"]
                if row["axis"] == "integrity"
                and row["backbone"] == backbone
                and row["condition"] == chosen["condition"]
                and row["defects"][defect]["flag"] is True
            ]
            assert chosen["defects"][defect]["margin"] == max(
                row["defects"][defect]["margin"] for row in eligible
            )


def test_integrity_empty_stratum_is_reported_without_cross_fill() -> None:
    candidate, schema = _candidate_index()
    candidate["rows"] = [
        row
        for row in candidate["rows"]
        if not (row["axis"] == "integrity" and row["defects"]["clipping"]["flag"] is True)
    ]
    result = select_human_packet(candidate, schema)
    assert result["selection_status"] == "COMPLETE_WITH_STRATUM_EMPTY"
    assert len(result["empty_strata"]) == 3
    assert all(row["selector_stratum"] == "clipping:flagged" for row in result["empty_strata"])
    integrity_count = sum(row["axis"] == "integrity" for row in result["selected"])
    assert integrity_count == 27


def test_budget_gate_stops_instead_of_trimming(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    bundle_value = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    timing = schema["timing_pilot"]
    receipt = {
        "attestation_schema_version": 1,
        "attestation_sha256": "d" * 64,
        "build_identity_sha256": bundle_value["build_identity_sha256"],
        "bundle_id": bundle_value["bundle_id"],
        "bundle_json_sha256": sha256_file(bundle / "bundle.json"),
        "ingested_at_utc": "2026-07-20T12:01:00+00:00",
        "item_count": 8,
        "pi_affirmation": timing["attestation_affirmation"],
        "pi_identity": timing["required_pi_identity"],
        "pi_signature": timing["required_pi_identity"],
        "protocol_deviations": [],
        "receipt_schema_version": 2,
        "response_schema_version": 2,
        "response_sha256": "c" * 64,
        "session_elapsed_seconds": 3600.0,
        "signed_at_utc": "2026-07-20T12:01:00Z",
        "status": "TIMING_PILOT_INGESTED",
        "task_counts": {"integrity_audit": 2, "tempo_tap": 4, "voice_stress": 2},
        "total_minutes": 60.0,
        "usability_status": "PASS",
    }
    receipt_path = tmp_path / "receipt.json"
    _write_json(receipt_path, receipt)
    gate = packet_gate(bundle, receipt_path)
    assert gate["PACKET_ASSEMBLY_STATUS"] == "BLOCKED_ON_HUMAN_TIME_BUDGET"
    assert gate["planned_presentations"] == 171
    assert gate["projected_minutes"] > 180


def test_gated_future_assembler_builds_public_private_packet(tmp_path: Path) -> None:
    candidate, schema = _candidate_index()
    initial_selection = select_human_packet(candidate, schema)
    selected_ids = {row["row_id"] for row in initial_selection["selected"]}
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    seconds = np.arange(3_000, dtype=np.float32) / 100.0
    for ordinal, row in enumerate(candidate["rows"]):
        if row["row_id"] not in selected_ids:
            continue
        waveform = (0.02 + ordinal / 100_000) * np.sin(2 * np.pi * (1 + ordinal % 19) * seconds)
        path = tmp_path / row["audio_path"]
        sf.write(path, np.column_stack([waveform, waveform]), 100, subtype="FLOAT")
        row["audio_sha256"] = sha256_file(path)
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, candidate)

    pilot_bundle = _fake_bundle(tmp_path)
    response = _valid_response(pilot_bundle)
    response["session_elapsed_seconds"] = 900.0
    response_path = tmp_path / "pilot-response.json"
    _write_json(response_path, response)
    receipt_dir = tmp_path / "pilot-receipt"
    attestation = _write_attestation(
        tmp_path / "pilot-attestation.json",
        pilot_bundle,
        response_path,
        response,
    )
    ingest(
        pilot_bundle,
        response_path,
        receipt_dir,
        attestation_path=attestation,
    )

    result = assemble_human_packet(
        pilot_bundle,
        receipt_dir / "receipt.json",
        candidate_path,
        tmp_path / "human-public",
        tmp_path / "human-private",
    )
    public = Path(result["bundle_dir"])
    private = Path(result["admin_dir"])
    bundle = json.loads((public / "bundle.json").read_text(encoding="utf-8"))
    admin = json.loads((private / "admin-map.json").read_text(encoding="utf-8"))
    assert len(bundle["items"]) == 171
    assert len(admin["items"]) == 171
    assert not (public / "admin-map.json").exists()
    assert sum(row["repeat_of_item_id"] is not None for row in admin["items"]) == 15
    assert bundle["session_limit_seconds"] > 99.75 * 60
    assert bundle["session_limit_seconds"] < 101.6 * 60
    for index, row in enumerate(admin["items"]):
        if row["repeat_of_item_id"] is not None:
            assert index == 0 or admin["items"][index - 1]["item_id"] != row["repeat_of_item_id"]
    with pytest.raises(FileExistsError):
        assemble_human_packet(
            pilot_bundle,
            receipt_dir / "receipt.json",
            candidate_path,
            tmp_path / "human-public",
            tmp_path / "human-private",
        )


def test_packet_duration_uses_d0026_per_backbone_tolerance() -> None:
    validate_packet_audio_duration(30.0)
    validate_packet_audio_duration(29.9073125)
    validate_packet_audio_duration(29.75)
    validate_packet_audio_duration(30.25)
    with pytest.raises(ValueError, match="amended 30-second"):
        validate_packet_audio_duration(29.749999)
    with pytest.raises(ValueError, match="amended 30-second"):
        validate_packet_audio_duration(30.250001)

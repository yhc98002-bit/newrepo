from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_statistics_freezes_cluster_bootstrap_and_gate() -> None:
    config = _read("configs/statistics_v2.json")
    assert config["bootstrap"]["replicates"] == 10_000
    eligibility = config["eligibility"]
    assert eligibility["unit"] == ["prompt", "root", "checkpoint"]
    assert eligibility["gate_order"] == [
        "ELIGIBLE",
        "REPLICATION_ONLY",
        "INCONCLUSIVE_UNDERPOWERED",
        "STOP_AXIS",
    ]
    assert eligibility["cross_fitted_deviation_share_minimum"] == 0.10
    assert eligibility["doubling"]["maximum_doublings"] == 1
    assert eligibility["baseline_name"] == "PROMPT_PLUS_TIME_BUDGET"
    assert [rule["label"] for rule in eligibility["gate_rules"]] == eligibility["gate_order"]
    assert "cross_fitted_deviation_share_gte_0.10" in eligibility["gate_rules"][0]["rule"]
    capture = eligibility["state_capture_contract"]
    assert capture["capture_fractions"] == [0.25, 0.5, 0.75]
    assert capture["feature_source"] == (
        "ONLY_THE_SAME_UNITS_ROOT_LOCAL_PRE_ACTION_DECODED_PREVIEW"
    )
    assert capture["preview_must_be_derived_from_exported_root_state"] is True
    assert capture["restart_outcomes"] == ("FROZEN_PROMPT_LEVEL_POOL_NOT_SINGLE_DRAW_ORACLE")
    assert capture["source_condition"] == "BASE"
    selection = eligibility["prompt_selection"]
    assert selection["namespace"] == "benchmark-v2-eligibility-prompt-selection-20260720"
    assert set(selection["axis_prompt_ids"]) == {
        "vocal_instrumental",
        "tempo",
        "integrity",
    }
    assert all(len(prompt_ids) == 12 for prompt_ids in selection["axis_prompt_ids"].values())
    voice_ids = selection["axis_prompt_ids"]["vocal_instrumental"]
    assert sum(prompt_id.endswith("-vocal") for prompt_id in voice_ids) == 6
    assert sum(prompt_id.endswith("-instrumental") for prompt_id in voice_ids) == 6

    namespace = selection["namespace"]

    def rank(identity: str) -> str:
        return hashlib.sha256(f"{namespace}|{identity}".encode()).hexdigest()

    voice_rows = _read("prompts/v2/vocal_instrumental.json")["rows"]
    ranked_frames = sorted({row["cluster_id"] for row in voice_rows}, key=rank)
    vocal_frames = set(ranked_frames[:6])
    expected_voice = sorted(
        row["prompt_id"]
        for row in voice_rows
        if (row["request"] == "vocal") == (row["cluster_id"] in vocal_frames)
    )
    assert voice_ids == expected_voice

    for axis, filename, stratum in (
        ("tempo", "tempo.json", "salience"),
        ("integrity", "integrity.json", "profile"),
    ):
        rows = _read(f"prompts/v2/{filename}")["rows"]
        expected = sorted(
            row["prompt_id"]
            for value in {row[stratum] for row in rows}
            for row in sorted(
                (candidate for candidate in rows if candidate[stratum] == value),
                key=lambda candidate: rank(candidate["prompt_id"]),
            )[:4]
        )
        assert selection["axis_prompt_ids"][axis] == expected


def test_rater_schema_hard_caps_time_and_tap_windows() -> None:
    schema = _read("rater/schema_v2.json")
    assert schema["maximum_total_pi_minutes"] == 180
    assert schema["tempo_tap_windows_seconds"] == [[2, 14], [16, 28]]
    assert schema["human_packet_gate"]["blocked_status"] == ("BLOCKED_ON_TIMING_PILOT_INGESTION")
    assert schema["human_packet"]["primary_backbones"] == [
        "stable-audio-3-medium-base",
        "stable-audio-open-1.0",
        "ACE-Step v1",
    ]
    assert schema["human_packet"]["maximum_projected_minutes"] == 180.0
    assert schema["timing_pilot"]["single_bundle"] is True
    assert schema["timing_pilot"]["required_pi_identity"] == "pxy1289"
    assert schema["timing_pilot"]["attestation_affirmation"] == (
        "I_ATTEST_THIS_TIMING_PILOT_RESPONSE_IS_COMPLETE_ACCURATE_AND_USABLE"
    )
    assert schema["integrity_response"] == {
        "intentional_musical_content_nonexclusive": True,
        "intentional_musical_content_permitted_with": [
            "defect_labels",
            "clean",
            "unsure",
        ],
    }

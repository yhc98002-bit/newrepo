from __future__ import annotations

import json
from pathlib import Path

import pytest

from rater.autoassemble_human_packet_v2 import (
    cross_instrument_disagreement_coverage,
    inspect_gates,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CONFIG = ROOT / "configs" / "human_packet_autoassembly_v2_sao.json"


def test_committed_arm_is_hash_bound_and_waits_for_pilot() -> None:
    config = load_config(ACTIVE_CONFIG)
    result = inspect_gates(config)
    assert result["packet_assembly_status"] == "ARMED_WAITING_ON_TIMING_PILOT"
    assert result["human_gold_claims"] is False
    assert result["ready"] is False


def test_arm_is_bound_to_exact_sao_final_scoring_root_without_prefix_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    expected_root = Path(
        "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/"
        "runs/scoring-v2/automatic-scoring-v2-sao-final-001"
    )
    assert Path(source["candidate_index"]["path"]) == (
        expected_root / "tables/human-audit-candidate-index.json"
    )
    assert Path(source["candidate_index"]["required_status_path"]) == (
        expected_root / "scoring-status.json"
    )

    exact_root = tmp_path / "automatic-scoring-v2-sao-final-001"
    prefix_root = tmp_path / "automatic-scoring-v2-sao-final-001-prefix"
    (prefix_root / "tables").mkdir(parents=True)
    (prefix_root / "tables" / "human-audit-candidate-index.json").write_text("{}", encoding="utf-8")
    (prefix_root / "scoring-status.json").write_text(
        json.dumps({"status": "SCORING_COMPLETE_ALL_PRIMARY_BACKBONES"}), encoding="utf-8"
    )
    source["candidate_index"]["path"] = str(
        exact_root / "tables" / "human-audit-candidate-index.json"
    )
    source["candidate_index"]["required_status_path"] = str(exact_root / "scoring-status.json")
    monkeypatch.setattr(
        "rater.autoassemble_human_packet_v2.packet_gate",
        lambda *_args, **_kwargs: {"PACKET_ASSEMBLY_STATUS": "READY_TO_ASSEMBLE"},
    )
    result = inspect_gates(source)
    assert result["ready"] is False
    assert result["selection_status"] == "MISSING_SCORING_STRATA"
    assert result["packet_assembly_status"] == "ARMED_WAITING_ON_SCORING_STRATA"


def test_arm_rejects_frozen_builder_hash_drift(tmp_path: Path) -> None:
    source = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    source["frozen_inputs"]["build_human_packet_sha256"] = "0" * 64
    path = tmp_path / "config.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="input hash mismatch"):
        load_config(path)


def test_arm_requires_its_dedicated_decision(tmp_path: Path) -> None:
    source = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    source["authorization_decision"] = "D-0028"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="dedicated opening decision"):
        load_config(path)


def _complete_disagreement_selection() -> dict:
    config = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    rows = []
    for backbone in config["primary_backbones"]:
        for request in ("vocal", "instrumental"):
            for slot in (3, 4):
                rows.append(
                    {
                        "axis": "voice",
                        "backbone": backbone,
                        "demucs_present": slot == 3,
                        "panns_present": slot != 3,
                        "selector_stratum": f"{request}:detector_disagreement:{slot}",
                    }
                )
        for slot in range(1, 11):
            rows.append(
                {
                    "axis": "tempo",
                    "backbone": backbone,
                    "selector_stratum": f"disagreement_or_invalid:{slot}",
                    "tempo_status": (
                        "ESTIMATOR_DISAGREEMENT" if slot == 1 else "ESTIMATOR_INVALID"
                    ),
                }
            )
    return {"selected": rows}


def test_cross_instrument_disagreement_coverage_is_per_backbone_and_fail_closed() -> None:
    config = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    selection = _complete_disagreement_selection()
    coverage = cross_instrument_disagreement_coverage(selection, config["primary_backbones"])
    assert coverage["status"] == "CROSS_INSTRUMENT_DISAGREEMENT_STRATA_READY"
    assert coverage["ready"] is True
    assert all(
        row["voice_actual_detector_disagreement_cells"] == {"vocal": 2, "instrumental": 2}
        and row["tempo_disagreement_or_invalid_slots"] == 10
        and row["tempo_actual_estimator_disagreement_cells"] == 1
        for row in coverage["per_backbone"].values()
    )

    sao = config["primary_backbones"][1]
    for row in selection["selected"]:
        if row["backbone"] == sao and row["axis"] == "tempo":
            row["tempo_status"] = "ESTIMATOR_INVALID"
    failed = cross_instrument_disagreement_coverage(selection, config["primary_backbones"])
    assert failed["ready"] is False
    assert failed["status"] == "INCOMPLETE_CROSS_INSTRUMENT_DISAGREEMENT_STRATA"
    assert failed["per_backbone"][sao]["ready"] is False

    selection = _complete_disagreement_selection()
    for row in selection["selected"]:
        if (
            row["backbone"] == sao
            and row["axis"] == "voice"
            and row["selector_stratum"].startswith("vocal:detector_disagreement:")
        ):
            row["panns_present"] = row["demucs_present"]
    failed = cross_instrument_disagreement_coverage(selection, config["primary_backbones"])
    assert failed["ready"] is False
    assert failed["per_backbone"][sao]["voice_actual_detector_disagreement_cells"]["vocal"] == 0


def test_inspect_gates_requires_pilot_sao_and_disagreement_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    candidate_path = tmp_path / "candidate.json"
    status_path = tmp_path / "status.json"
    candidate_path.write_text("{}", encoding="utf-8")
    status_path.write_text(
        json.dumps({"status": "SCORING_COMPLETE_ALL_PRIMARY_BACKBONES"}),
        encoding="utf-8",
    )
    source["candidate_index"]["path"] = str(candidate_path)
    source["candidate_index"]["required_status_path"] = str(status_path)
    monkeypatch.setattr(
        "rater.autoassemble_human_packet_v2.packet_gate",
        lambda *_args, **_kwargs: {"PACKET_ASSEMBLY_STATUS": "READY_TO_ASSEMBLE"},
    )
    selection = _complete_disagreement_selection()
    expected = {"integrity_audit": 10, "tempo_tap": 30, "voice_stress": 12}
    selection["counts"] = {backbone: dict(expected) for backbone in source["primary_backbones"]}
    selection["empty_strata"] = []
    monkeypatch.setattr(
        "rater.autoassemble_human_packet_v2.select_human_packet",
        lambda *_args, **_kwargs: selection,
    )
    assert inspect_gates(source)["ready"] is True

    sao = source["primary_backbones"][1]
    selection["counts"][sao] = {**expected, "tempo_tap": 0}
    missing_sao = inspect_gates(source)
    assert missing_sao["ready"] is False
    assert missing_sao["packet_assembly_status"] == "ARMED_WAITING_ON_SCORING_STRATA"

    selection["counts"][sao] = dict(expected)
    for row in selection["selected"]:
        if row["backbone"] == sao and row["axis"] == "tempo":
            row["tempo_status"] = "ESTIMATOR_INVALID"
    missing_disagreement = inspect_gates(source)
    assert missing_disagreement["ready"] is False
    assert missing_disagreement["selection_status"] == (
        "INCOMPLETE_CROSS_INSTRUMENT_DISAGREEMENT_STRATA"
    )

    monkeypatch.setattr(
        "rater.autoassemble_human_packet_v2.packet_gate",
        lambda *_args, **_kwargs: {"PACKET_ASSEMBLY_STATUS": "BLOCKED_ON_TIMING_PILOT_INGESTION"},
    )
    missing_pilot = inspect_gates(source)
    assert missing_pilot["ready"] is False
    assert missing_pilot["packet_assembly_status"] == "ARMED_WAITING_ON_TIMING_PILOT"


def test_arm_rejects_missing_opening_decision(tmp_path: Path) -> None:
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text("# Decisions\n", encoding="utf-8")
    with pytest.raises(ValueError, match="opening decision is absent"):
        load_config(
            ACTIVE_CONFIG,
            decisions_path=decisions,
        )


def test_arm_rejects_config_not_bound_by_decision(tmp_path: Path) -> None:
    source = json.loads(
        ACTIVE_CONFIG.read_text(encoding="utf-8")
    )
    source["poll_interval_seconds"] = 31
    path = tmp_path / "config.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="exact assignment"):
        load_config(path)

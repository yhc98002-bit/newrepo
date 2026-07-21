from __future__ import annotations

import json
from pathlib import Path

import pytest

from rater.autoassemble_human_packet_v2 import inspect_gates, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_committed_arm_is_hash_bound_and_waits_for_pilot() -> None:
    config = load_config(ROOT / "configs" / "human_packet_autoassembly_v2.json")
    result = inspect_gates(config)
    assert result["packet_assembly_status"] == "ARMED_WAITING_ON_TIMING_PILOT"
    assert result["human_gold_claims"] is False
    assert result["ready"] is False


def test_arm_rejects_frozen_builder_hash_drift(tmp_path: Path) -> None:
    source = json.loads(
        (ROOT / "configs" / "human_packet_autoassembly_v2.json").read_text(encoding="utf-8")
    )
    source["frozen_inputs"]["build_human_packet_sha256"] = "0" * 64
    path = tmp_path / "config.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="input hash mismatch"):
        load_config(path)


def test_arm_requires_its_dedicated_decision(tmp_path: Path) -> None:
    source = json.loads(
        (ROOT / "configs" / "human_packet_autoassembly_v2.json").read_text(encoding="utf-8")
    )
    source["authorization_decision"] = "D-0028"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="dedicated opening decision"):
        load_config(path)


def test_arm_rejects_missing_opening_decision(tmp_path: Path) -> None:
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text("# Decisions\n", encoding="utf-8")
    with pytest.raises(ValueError, match="opening decision is absent"):
        load_config(
            ROOT / "configs" / "human_packet_autoassembly_v2.json",
            decisions_path=decisions,
        )


def test_arm_rejects_config_not_bound_by_decision(tmp_path: Path) -> None:
    source = json.loads(
        (ROOT / "configs" / "human_packet_autoassembly_v2.json").read_text(
            encoding="utf-8"
        )
    )
    source["poll_interval_seconds"] = 31
    path = tmp_path / "config.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="exact assignment"):
        load_config(path)

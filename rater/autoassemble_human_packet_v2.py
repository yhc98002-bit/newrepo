#!/usr/bin/env python3
"""Fail-closed watcher for the frozen v2 human-audit packet gates."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rater.build_human_packet import (
    assemble_human_packet,
    packet_gate,
    select_human_packet,
)
from rater.bundle_common import load_json_strict, sha256_file, write_json_exclusive

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_CONFIG = ROOT / "configs" / "human_packet_autoassembly_v2.json"
DEFAULT_SCHEMA = HERE / "schema_v2.json"
DEFAULT_TEMPLATE = HERE / "timing_pilot.html"

EXPECTED_CONFIG_KEYS = {
    "authorization_decision",
    "bundle",
    "candidate_index",
    "frozen_inputs",
    "output",
    "pilot_receipt",
    "poll_interval_seconds",
    "primary_backbones",
    "schema_version",
    "status",
}

REQUIRED_DECISION_ASSIGNMENTS = (
    "HUMAN_AUDIT_PACKET_AUTOASSEMBLY = ARMED",
    "HUMAN_AUDIT_PACKET_ASSEMBLY = ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA",
    "HUMAN_AUDIT_PACKET_HUMAN_GOLD_CLAIMS = NO",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_keys(value: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{context} keys differ from the frozen contract")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _validate_opening_decision(
    config: dict[str, Any], config_path: Path, decisions_path: Path
) -> None:
    text = decisions_path.resolve(strict=True).read_text(encoding="utf-8")
    decision_id = config["authorization_decision"]
    match = re.search(
        rf"(?ms)^## {re.escape(decision_id)}\b.*?(?=^## D-\d+\b|\Z)",
        text,
    )
    if match is None:
        raise ValueError("dedicated autoassembly opening decision is absent")
    block = match.group(0)
    required = (
        *REQUIRED_DECISION_ASSIGNMENTS,
        f"HUMAN_AUDIT_PACKET_AUTOASSEMBLY_CONFIG_SHA256 = {sha256_file(config_path)}",
    )
    if any(assignment not in block for assignment in required):
        raise ValueError("autoassembly opening decision lacks an exact assignment")
    if re.search(r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE|UNSET)\b", block, re.IGNORECASE):
        raise ValueError("autoassembly opening decision contains unresolved text")


def load_config(path: Path, *, decisions_path: Path | None = None) -> dict[str, Any]:
    config = _require_keys(load_json_strict(path), EXPECTED_CONFIG_KEYS, "arm config")
    if config["schema_version"] != 1:
        raise ValueError("arm config schema_version must be 1")
    if config["status"] != "ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA":
        raise ValueError("arm config is not in the frozen armed state")
    if config["authorization_decision"] != "D-0032":
        raise ValueError("arm config lacks the dedicated opening decision")
    interval = config["poll_interval_seconds"]
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 5:
        raise ValueError("poll_interval_seconds must be an integer of at least five")
    expected = config["frozen_inputs"]
    observed = {
        "autoassemble_human_packet_sha256": sha256_file(
            HERE / "autoassemble_human_packet_v2.py"
        ),
        "build_human_packet_sha256": sha256_file(HERE / "build_human_packet.py"),
        "prereg_sha256": sha256_file(ROOT / "BENCHMARK_PREREG_v2.md"),
        "rater_schema_sha256": sha256_file(DEFAULT_SCHEMA),
        "timing_pilot_offer_sha256": sha256_file(HERE / "timing_pilot_offer_v2.json"),
        "ui_template_sha256": sha256_file(DEFAULT_TEMPLATE),
    }
    if expected != observed:
        raise ValueError("frozen packet-builder input hash mismatch")
    bundle = _require_keys(
        config["bundle"], {"bundle_dir", "bundle_json_sha256", "bundle_id"}, "bundle"
    )
    bundle_json = Path(bundle["bundle_dir"]).resolve() / "bundle.json"
    if sha256_file(bundle_json) != bundle["bundle_json_sha256"]:
        raise ValueError("offered timing-pilot bundle hash mismatch")
    if load_json_strict(bundle_json).get("bundle_id") != bundle["bundle_id"]:
        raise ValueError("offered timing-pilot bundle ID mismatch")
    _validate_opening_decision(
        config,
        path.resolve(strict=True),
        decisions_path or (ROOT / "DECISIONS.md"),
    )
    return config


def inspect_gates(config: dict[str, Any]) -> dict[str, Any]:
    """Inspect both independent inputs without assembling anything."""

    bundle_dir = Path(config["bundle"]["bundle_dir"])
    receipt_path = Path(config["pilot_receipt"]["path"])
    timing = packet_gate(bundle_dir, receipt_path if receipt_path.is_file() else None)
    candidate_path = Path(config["candidate_index"]["path"])
    scoring_status_path = Path(config["candidate_index"]["required_status_path"])
    scoring_ready = False
    selection_status = "MISSING_SCORING_STRATA"
    missing_strata: list[dict[str, str]] = []
    selection_counts: dict[str, Any] = {}
    if candidate_path.is_file() and scoring_status_path.is_file():
        status = load_json_strict(scoring_status_path)
        scoring_ready = (
            isinstance(status, dict)
            and status.get("status") == config["candidate_index"]["required_status"]
        )
        if scoring_ready:
            schema = load_json_strict(DEFAULT_SCHEMA)
            candidate = load_json_strict(candidate_path)
            selection = select_human_packet(candidate, schema)
            missing_strata = selection["empty_strata"]
            selection_counts = selection["counts"]
            expected = schema["human_packet"]["unique_items_per_backbone"]
            expected_counts = {
                backbone: {
                    "integrity_audit": expected["integrity_audit"],
                    "tempo_tap": expected["tempo_tap"],
                    "voice_stress": expected["voice_stress"],
                }
                for backbone in config["primary_backbones"]
            }
            if not missing_strata and selection_counts == expected_counts:
                selection_status = "SCORING_STRATA_READY"
            else:
                scoring_ready = False
                selection_status = "INCOMPLETE_FROZEN_PRIMARY_BACKBONE_STRATA"
    ready = timing["PACKET_ASSEMBLY_STATUS"] == "READY_TO_ASSEMBLE" and scoring_ready
    if ready:
        status = "READY_TO_AUTOASSEMBLE"
    elif timing["PACKET_ASSEMBLY_STATUS"] != "READY_TO_ASSEMBLE":
        status = "ARMED_WAITING_ON_TIMING_PILOT"
    else:
        status = "ARMED_WAITING_ON_SCORING_STRATA"
    return {
        "checked_at_utc": _utc_now(),
        "human_gold_claims": False,
        "missing_strata": missing_strata,
        "packet_assembly_status": status,
        "ready": ready,
        "schema_version": 1,
        "selection_counts": selection_counts,
        "selection_status": selection_status,
        "timing_gate": timing,
    }


def assemble_if_ready(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    heartbeat_path = Path(config["output"]["heartbeat_path"])
    terminal_path = Path(config["output"]["terminal_receipt_path"])
    gates = inspect_gates(config)
    _atomic_json(heartbeat_path, gates)
    if not gates["ready"]:
        return gates
    if terminal_path.exists():
        terminal = load_json_strict(terminal_path)
        if terminal.get("status") != "HUMAN_AUDIT_PACKET_ASSEMBLED":
            raise RuntimeError("terminal autoassembly receipt has an unexpected status")
        return terminal
    result = assemble_human_packet(
        Path(config["bundle"]["bundle_dir"]),
        Path(config["pilot_receipt"]["path"]),
        Path(config["candidate_index"]["path"]),
        Path(config["output"]["output_root"]),
        Path(config["output"]["admin_root"]),
    )
    terminal = {
        **result,
        "assembled_at_utc": _utc_now(),
        "authorization_decision": config["authorization_decision"],
        "human_gold_claims": False,
        "status": "HUMAN_AUDIT_PACKET_ASSEMBLED",
    }
    write_json_exclusive(terminal_path, terminal)
    _atomic_json(heartbeat_path, terminal)
    return terminal


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--watch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config(args.config.resolve())
    while True:
        result = assemble_if_ready(args.config.resolve())
        print(json.dumps(result, allow_nan=False, sort_keys=True), flush=True)
        if result.get("status") == "HUMAN_AUDIT_PACKET_ASSEMBLED" or not args.watch:
            return 0 if result.get("ready") or result.get("status") else 3
        time.sleep(config["poll_interval_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())

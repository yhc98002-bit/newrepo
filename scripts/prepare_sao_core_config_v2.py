#!/usr/bin/env python3
"""Seal SAO core authorization, amended Phase-B receipt, and incremental config."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbones.contracts import DEFAULT_SAO_CONFIG, sha256_file, strict_json_object  # noqa: E402
from backbones.license_gate import validate_access_receipt  # noqa: E402
from backbones.sao_acquisition import validate_live_config  # noqa: E402
from backbones.sao_mini_smoke import validate_sao_mini_smoke_evidence  # noqa: E402
from benchmark_core.config import ACE_MODEL_ID, SA3_MODEL_ID, SAO_MODEL_ID  # noqa: E402

BASE_CORE = ROOT / "configs" / "benchmark_core_v2_ace_incremental.json"
BASE_TERMINAL = ROOT / "provenance" / "b2" / "build_status_terminal_v2_ace_amendment.json"
SA3_COMPLETION = ROOT / "provenance" / "core" / "sa3_core_completion_v2.json"
ACE_COMPLETION = ROOT / "provenance" / "core" / "ace_core_completion_v2.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"sealed repository artifact must remain under {ROOT}: {path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-config", type=Path, default=ROOT / "configs" / "sao_live_v2.json")
    parser.add_argument("--decisions", type=Path, default=ROOT / "DECISIONS.md")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--mini-smoke-terminal", type=Path, required=True)
    parser.add_argument("--physical-gpu-id", type=int, required=True)
    parser.add_argument("--output-authorization", type=Path, required=True)
    parser.add_argument("--output-terminal", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    args = parser.parse_args()

    validate_live_config(args.live_config, args.decisions)
    if args.physical_gpu_id not in {4, 5, 6, 7}:
        raise ValueError("SAO core placement is restricted to an12 GPU 4..7")
    outputs = (args.output_authorization, args.output_terminal, args.output_config)
    if any(path.exists() for path in outputs):
        raise FileExistsError("SAO sealed package refuses to overwrite an output")
    for output in outputs:
        _repo_relative(output)

    receipt = validate_access_receipt(
        args.access_receipt,
        expected_model_id=SAO_MODEL_ID,
        expected_snapshot_dir=args.snapshot_dir,
    )
    mini = validate_sao_mini_smoke_evidence(
        args.mini_smoke_terminal,
        expected_config_sha256=sha256_file(DEFAULT_SAO_CONFIG),
        expected_receipt=receipt,
        expected_snapshot_dir=args.snapshot_dir,
    )
    cost = mini["cost_calibration"]
    cold = float(cost["cold_plus_first_seconds"])
    resident = float(cost["resident_unit_seconds"])
    cap = float(cost["gpu_seconds_cap"])
    mini_sha = sha256_file(args.mini_smoke_terminal)
    adapter_sha = sha256_file(DEFAULT_SAO_CONFIG)

    authorization = {
        "schema_version": 1,
        "status": "ACCESS_AND_MINI_SMOKE_VERIFIED_CORE_AUTHORIZED",
        "scope": "SAO_BENCHMARK_CORE_GENERATION_ONLY",
        "decision_id": "D-0037",
        "backbone_config_sha256": adapter_sha,
        "access_receipt_sha256": receipt["receipt_sha256"],
        "mini_smoke_result_sha256": mini_sha,
        "exact_generations": 1536,
        "max_clip_seconds": 30,
        "max_gpus_per_worker": 1,
        "state_capability": "NOT_ATTEMPTED",
        "eligibility_scope_expanded": False,
    }
    _write_json_exclusive(args.output_authorization, authorization)

    terminal = copy.deepcopy(strict_json_object(BASE_TERMINAL))
    terminal["created_at_utc"] = _utc_now()
    terminal["accounting_scope"] = "CUMULATIVE_B2_ENGINEERING_SMOKES_THROUGH_SAO_V2"
    terminal["generated_outputs_total"] = int(terminal["generated_outputs_total"]) + 3
    terminal["model_generation_calls_total"] = int(terminal["model_generation_calls_total"]) + 3
    terminal["supersedes"] = {
        "path": _repo_relative(BASE_TERMINAL),
        "sha256": sha256_file(BASE_TERMINAL),
        "status": "TERMINAL",
    }
    terminal["models"][SAO_MODEL_ID] = {
        "build_status": "MEASURED_READY",
        "queue_status": "READY",
        "cost_status": "MEASURED",
        "mini_smoke_status": "MEASURED_MINI_SMOKE_PASS",
        "cold_plus_first_seconds": cold,
        "resident_unit_seconds": resident,
        "access_receipt_sha256": receipt["receipt_sha256"],
        "mini_smoke_result_sha256": mini_sha,
        "generated_outputs": 3,
        "model_calls": 3,
        "state_capability": "NOT_ATTEMPTED",
        "eligibility_scope_expanded": False,
    }
    _write_json_exclusive(args.output_terminal, terminal)

    core = copy.deepcopy(strict_json_object(BASE_CORE))
    core["phase_b_terminal"] = {
        "path": _repo_relative(args.output_terminal),
        "sha256": sha256_file(args.output_terminal),
        "status": "TERMINAL",
    }
    core["execution"]["authorized_model_ids"] = [SAO_MODEL_ID]
    core["execution"]["prior_model_completions"] = {
        SA3_MODEL_ID: {
            "path": _repo_relative(SA3_COMPLETION),
            "sha256": sha256_file(SA3_COMPLETION),
        },
        ACE_MODEL_ID: {
            "path": _repo_relative(ACE_COMPLETION),
            "sha256": sha256_file(ACE_COMPLETION),
        },
    }
    core["execution"]["state_capture"]["eligible_model_ids"] = [SA3_MODEL_ID, ACE_MODEL_ID]
    core["models"][1] = {
        "model_id": SAO_MODEL_ID,
        "queue_status": "READY",
        "slug": "stable-audio-open-1-0",
        "core_execution": {
            "adapter_config_path": "configs/backbones/stable_audio_open_1_0.json",
            "adapter_config_sha256": adapter_sha,
            "budget": {
                "cold_plus_first_seconds": cold,
                "resident_unit_seconds": resident,
                "scheduled_calls": 1536,
                "gpu_seconds_cap": cap,
            },
            "duration_tolerance_seconds": 0.25,
            "expected_channels": 2,
            "placement": {
                "lock_root": (
                    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/"
                    "benchmark_v2_runtime/locks/core-v2"
                ),
                "logical_gpu_id": 0,
                "maximum_idle_utilization_percent": 5,
                "minimum_free_vram_bytes": 60000000000,
                "node": "an12",
                "physical_gpu_id": args.physical_gpu_id,
                "post_load_reserve_bytes": 20000000000,
                "replica_count": 1,
                "required_gpu_name_substring": "A800",
                "tp_width": 1,
            },
            "state_capture_status": "AUTOMATIC_OUTPUT_ONLY",
            "sao_runtime": {
                "snapshot_dir": str(args.snapshot_dir.resolve()),
                "access_receipt_path": str(args.access_receipt.resolve()),
                "access_receipt_sha256": receipt["receipt_sha256"],
                "mini_smoke_result_path": str(args.mini_smoke_terminal.resolve()),
                "mini_smoke_result_sha256": mini_sha,
                "core_authorization_path": _repo_relative(args.output_authorization),
                "core_authorization_sha256": sha256_file(args.output_authorization),
            },
        },
    }
    _write_json_exclusive(args.output_config, core)
    print(
        json.dumps(
            {
                "status": "SEALED_CONFIG_ONLY_NO_MODEL_CALLS",
                "authorization": {
                    "path": str(args.output_authorization.resolve()),
                    "sha256": sha256_file(args.output_authorization),
                },
                "phase_b_terminal": {
                    "path": str(args.output_terminal.resolve()),
                    "sha256": sha256_file(args.output_terminal),
                },
                "core_config": {
                    "path": str(args.output_config.resolve()),
                    "sha256": sha256_file(args.output_config),
                },
                "model_calls": 0,
                "generated_audio": 0,
            },
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

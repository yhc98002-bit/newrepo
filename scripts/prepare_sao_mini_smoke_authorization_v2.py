#!/usr/bin/env python3
"""Seal the non-secret exact-three-call SAO mini-smoke authorization."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbones.contracts import DEFAULT_SAO_CONFIG, sha256_file  # noqa: E402
from backbones.license_gate import validate_access_receipt  # noqa: E402
from backbones.sao_acquisition import validate_live_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-config", type=Path, default=ROOT / "configs" / "sao_live_v2.json")
    parser.add_argument("--decisions", type=Path, default=ROOT / "DECISIONS.md")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate_live_config(args.live_config, args.decisions)
    receipt = validate_access_receipt(
        args.access_receipt,
        expected_model_id="stabilityai/stable-audio-open-1.0",
        expected_snapshot_dir=args.snapshot_dir,
    )
    record = {
        "schema_version": 1,
        "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
        "decision_id": "D-0037",
        "backbone_config_sha256": sha256_file(DEFAULT_SAO_CONFIG),
        "access_receipt_sha256": receipt["receipt_sha256"],
        "max_generations": 3,
        "max_clip_seconds": 30,
        "max_gpus": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(
        json.dumps(
            {
                "status": "MINI_SMOKE_AUTHORIZATION_SEALED_NO_MODEL_CALLS",
                "path": str(args.output.resolve()),
                "sha256": sha256_file(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

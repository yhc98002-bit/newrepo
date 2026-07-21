#!/usr/bin/env python3
"""Prepare, shard, and finalize automatic benchmark-v2 scoring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scoring.pipeline import (  # noqa: E402
    dry_run,
    extract_feature_shard,
    finalize_all,
    finalize_integrity_first,
    prepare_run,
)

DEFAULT_CONFIG = ROOT / "configs" / "automatic_scoring_v2.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument(
        "--extract-axis",
        choices=("integrity", "tempo", "vocal_instrumental"),
    )
    modes.add_argument("--finalize-integrity-first", action="store_true")
    modes.add_argument("--finalize-all", action="store_true")
    parser.add_argument("--part-index", type=int)
    parser.add_argument("--launch-ack")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        result = dry_run(args.config, ROOT)
    elif args.prepare:
        result = prepare_run(
            args.config,
            ROOT,
            launch_ack=args.launch_ack or "",
        )
    elif args.extract_axis:
        if args.part_index is None:
            raise SystemExit("--extract-axis requires --part-index")
        result = extract_feature_shard(
            args.config,
            ROOT,
            axis=args.extract_axis,
            part_index=args.part_index,
        )
    elif args.finalize_integrity_first:
        result = finalize_integrity_first(args.config, ROOT)
    else:
        result = finalize_all(args.config, ROOT)
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    if isinstance(result, dict) and str(result.get("status", "")).startswith("QUEUED_"):
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

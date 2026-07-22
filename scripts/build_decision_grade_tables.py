#!/usr/bin/env python3
"""Build no-clobber decision-grade automatic tables from normalized JSONL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scoring.common import load_json, sha256_file  # noqa: E402
from scoring.decision_grade import (  # noqa: E402
    build_decision_grade_tables,
    load_bound_decision_grade_source,
)

DEFAULT_STATISTICS = ROOT / "configs" / "statistics_v2.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--scoring-config", type=Path, required=True)
    parser.add_argument("--scoring-status", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--statistics-config", type=Path, default=DEFAULT_STATISTICS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    statistics = load_json(args.statistics_config)["bootstrap"]
    rows, source_binding = load_bound_decision_grade_source(
        args.input_jsonl,
        scoring_config_path=args.scoring_config,
        scoring_status_path=args.scoring_status,
        source_snapshot_path=args.source_snapshot,
    )
    tables = build_decision_grade_tables(
        rows,
        source_binding=source_binding,
        replicates=int(statistics["replicates"]),
        seed=int(statistics["seed"]),
        confidence_level=float(statistics["confidence_level"]),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(tables, allow_nan=False, indent=2, sort_keys=True) + "\n"
    with args.output_json.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(
        json.dumps(
            {
                "output_json": str(args.output_json.resolve()),
                "output_sha256": sha256_file(args.output_json),
                "status": tables["status"],
            },
            allow_nan=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare immutable ordinary/state queues and an external launch claim; no model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
DEFAULT_FROZEN_FILES = tuple(
    REPOSITORY / relative
    for relative in (
        "BENCHMARK_PREREG_v2.md",
        "BENCHMARK_CORE_PROTOCOL_v2.md",
        "provenance/b2/build_status_terminal_v2.json",
        "provenance/core/sa3_core_completion_v2.json",
        "configs/backbones/stable_audio_3_medium_base.json",
        "configs/backbones/ace_step_v1.json",
        "src/audio_duration_policy.py",
        "src/backbones/__init__.py",
        "src/backbones/ace_step_v1.py",
        "src/backbones/contracts.py",
        "src/backbones/duration_sanity.py",
        "src/backbones/io.py",
        "src/backbones/license_gate.py",
        "src/backbones/runtime.py",
        "src/backbones/sao_mini_smoke.py",
        "src/backbones/sao_t5.py",
        "src/backbones/stable_audio_3.py",
        "src/backbones/stable_audio_open.py",
        "src/benchmark_core/__init__.py",
        "src/benchmark_core/adapter_bridge.py",
        "src/benchmark_core/artifacts.py",
        "src/benchmark_core/claims.py",
        "src/benchmark_core/config.py",
        "src/benchmark_core/heartbeat.py",
        "src/benchmark_core/launcher.py",
        "src/benchmark_core/ledger.py",
        "src/benchmark_core/placement.py",
        "src/benchmark_core/queue.py",
        "src/benchmark_core/state_queue.py",
        "src/benchmark_core/supervisor.py",
        "src/benchmark_core/worker.py",
        "src/sa3_smoke/__init__.py",
        "src/sa3_smoke/artifacts.py",
        "src/sa3_smoke/audio.py",
        "src/sa3_smoke/budget.py",
        "src/sa3_smoke/environment_validation.py",
        "src/sa3_smoke/model_runtime.py",
        "scripts/prepare_benchmark_core_run.py",
        "scripts/run_benchmark_core_worker.py",
    )
)


def main() -> int:
    from benchmark_core.launcher import prepare_run

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--decisions", type=Path, default=REPOSITORY / "DECISIONS.md")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = prepare_run(
        args.config,
        run_id=args.run_id,
        decisions_path=args.decisions,
        decision_id=args.decision_id,
        frozen_files=DEFAULT_FROZEN_FILES,
        repo_root=REPOSITORY,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

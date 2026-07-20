#!/usr/bin/env python3
"""Run one resident READY-backbone queue; continues after its first ledgered shard."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def _event(handle, event: dict) -> None:
    handle.write(json.dumps(event, allow_nan=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def main() -> int:
    from benchmark_core.adapter_bridge import build_production_bridge
    from benchmark_core.config import READY, load_core_execution_config, sha256_file
    from benchmark_core.launcher import (
        observe_clean_origin_main,
        validate_external_launch_claim,
        validate_run_bundle,
    )
    from benchmark_core.queue import load_queue
    from benchmark_core.worker import BenchmarkWorker

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()

    config = load_core_execution_config(args.config, repo_root=REPOSITORY)
    git_state = observe_clean_origin_main(REPOSITORY)
    run_dir = args.run_dir.resolve(strict=True)
    manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "PREPARED_NO_MODEL_CALLS":
        raise RuntimeError("run manifest is not PREPARED_NO_MODEL_CALLS")
    if manifest.get("config_sha256") != config.source_sha256:
        raise RuntimeError("run/config hash mismatch")
    if manifest.get("git_commit") != git_state.head:
        raise RuntimeError("run/Git identity mismatch")
    launch_claim_path = run_dir / "control" / "launch-claim.json"
    if sha256_file(launch_claim_path) != manifest.get("launch_claim_sha256"):
        raise RuntimeError("external launch claim hash mismatch")
    launch_claim = validate_external_launch_claim(
        launch_claim_path,
        run_id=str(manifest.get("run_id")),
        config_sha256=config.source_sha256,
        git_commit=git_state.head,
        run_dir=run_dir,
    )
    bindings = validate_run_bundle(run_dir, manifest, launch_claim, config=config)
    queue_path = Path(bindings["generation"]["queue_path"])
    all_rows = load_queue(queue_path)
    candidates = [model for model in config.models if model.model_id == args.model_id]
    if len(candidates) != 1 or candidates[0].queue_status != READY:
        raise RuntimeError("requested worker model is not uniquely READY")
    model = candidates[0]
    rows = [row for row in all_rows if row["model_id"] == model.model_id]
    prompt_root = Path(config.raw["prompt_root"])
    if not prompt_root.is_absolute():
        prompt_root = config.repo_root / prompt_root
    prompt_manifest_sha = sha256_file(prompt_root / "manifest.json")
    adapter = build_production_bridge(model, run_dir=run_dir)
    worker = BenchmarkWorker(
        run_dir=run_dir,
        run_id=str(manifest["run_id"]),
        git_commit=git_state.head,
        config_sha256=config.source_sha256,
        prompt_manifest_sha256=prompt_manifest_sha,
        model=model,
        adapter=adapter,
        heartbeat_interval_seconds=config.heartbeat_interval_seconds,
        heartbeat_stale_after_seconds=config.heartbeat_stale_after_seconds,
        launch_claim_path=launch_claim_path,
    )
    log_path = run_dir / "logs" / f"{model.slug}-worker.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        log_path.open("x", encoding="utf-8") as log,
        contextlib.redirect_stdout(log),
        contextlib.redirect_stderr(log),
    ):
        _event(
            log,
            {
                "event": "WORKER_STARTED",
                "git_commit": git_state.head,
                "model_id": model.model_id,
                "pid": os.getpid(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            result = worker.run(rows)
        except BaseException as exc:
            _event(
                log,
                {
                    "error_message": str(exc)[:2000],
                    "error_type": type(exc).__name__,
                    "event": "WORKER_STOPPED_WITH_ERROR",
                    "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            raise
        _event(
            log,
            {
                "event": "WORKER_TERMINAL",
                "result": result,
                "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
    print(json.dumps({"log_path": str(log_path), "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

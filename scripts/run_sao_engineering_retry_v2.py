#!/usr/bin/env python3
"""Run the repaired, exactly three-call SAO mini-smoke on one idle an12 GPU."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbones.contracts import GenerationRequest  # noqa: E402
from backbones.mini_smoke import RunContext  # noqa: E402
from backbones.sao_acquisition import validate_live_config  # noqa: E402
from backbones.sao_engineering_retry import (  # noqa: E402
    SAO_ENGINEERING_ENVIRONMENT_MANIFEST,
    SAO_ENGINEERING_RETRY_RUN_DIR,
    consume_sao_engineering_retry_attempt,
    prepare_sao_engineering_retry_attempt,
    validate_sao_engineering_environment,
)
from backbones.sao_mini_smoke import run_sao_mini_smoke  # noqa: E402
from backbones.sao_operational_claims import SHARED_CORE_DEVICE_LOCK_ROOT  # noqa: E402
from backbones.stable_audio_open import (  # noqa: E402
    HF_TOKEN_ENVIRONMENT_VARIABLES,
    StableAudioOpenAdapter,
)
from benchmark_core.config import PlacementConfig  # noqa: E402
from benchmark_core.placement import DeviceLease, NvidiaSmiProbe  # noqa: E402

DEFAULT_RUN_DIR = SAO_ENGINEERING_RETRY_RUN_DIR
LOCK_ROOT = SHARED_CORE_DEVICE_LOCK_ROOT


def _git_state() -> str:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if head != origin or branch != "main" or dirty:
        raise RuntimeError("SAO generation requires clean local main equal to origin/main")
    return head


def _verify_seeds() -> None:
    text = (ROOT / "SEED_REGISTRY.md").read_text(encoding="utf-8")
    required = (
        "| S-0011 | 73193011 | Stable Audio Open 1.0 mini-smoke calls 0/1, "
        "identical-seed reproducibility pair, non-benchmark | none |",
        "| S-0012 | 73193012 | Stable Audio Open 1.0 mini-smoke call 2, "
        "resident-call cost calibration, non-benchmark | none |",
    )
    if any(row not in text for row in required):
        raise RuntimeError("SAO engineering seeds are absent or changed")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare_fixed_run_parent(run_dir: Path) -> None:
    """Create only the fixed retry parent; never materialize the run itself."""

    expected_run_dir = DEFAULT_RUN_DIR.resolve()
    observed_run_dir = run_dir.resolve()
    if observed_run_dir != expected_run_dir:
        raise RuntimeError("SAO mini-smoke run directory is not the fixed engineering-repair path")
    if os.path.lexists(observed_run_dir):
        raise RuntimeError("SAO mini-smoke fixed run directory already exists")
    parent = expected_run_dir.parent
    if parent.is_symlink():
        raise RuntimeError("SAO mini-smoke parent may not be a symlink")
    if parent.exists():
        if not parent.is_dir():
            raise RuntimeError("SAO mini-smoke parent is not a directory")
    else:
        grandparent = parent.parent.resolve(strict=True)
        if grandparent != DEFAULT_RUN_DIR.parent.parent.resolve(strict=True):
            raise RuntimeError("SAO mini-smoke parent escapes the fixed runtime root")
        parent.mkdir(parents=False, exist_ok=False)
        _fsync_directory(grandparent)
    _fsync_directory(parent)
    if os.path.lexists(observed_run_dir):
        raise RuntimeError("SAO mini-smoke run appeared while preparing its parent")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "sao_live_v2.json")
    parser.add_argument("--decisions", type=Path, default=ROOT / "DECISIONS.md")
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--runtime-authorization", type=Path, required=True)
    parser.add_argument(
        "--engineering-decision-id",
        required=True,
        help="append-only DECISIONS.md block authorizing this exact engineering retry",
    )
    parser.add_argument(
        "--engineering-decision-block-sha256",
        required=True,
        help="SHA-256 of the exact engineering-retry decision block",
    )
    parser.add_argument(
        "--environment-manifest",
        type=Path,
        default=SAO_ENGINEERING_ENVIRONMENT_MANIFEST,
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--physical-gpu-id", type=int, required=True)
    args = parser.parse_args()

    validate_live_config(args.config, args.decisions)
    _verify_seeds()
    environment_evidence = validate_sao_engineering_environment(args.environment_manifest)
    git_commit = _git_state()
    node = socket.gethostname().split(".", 1)[0]
    if node != "an12" or args.physical_gpu_id not in {4, 5, 6, 7}:
        raise RuntimeError("SAO mini-smoke is restricted to an12 physical GPU 4..7")
    present_tokens = [name for name in HF_TOKEN_ENVIRONMENT_VARIABLES if name in os.environ]
    if present_tokens:
        raise RuntimeError("SAO mini-smoke requires all Hugging Face token variables to be absent")
    run_dir = args.run_dir.resolve()
    # Complete every offline receipt/snapshot/authorization check before the
    # one-shot claim. This hashes files but neither imports the model nor
    # touches CUDA, so a clerical path error cannot consume the smoke attempt.
    adapter = StableAudioOpenAdapter(
        snapshot_dir=args.snapshot_dir,
        access_receipt_path=args.access_receipt,
        runtime_authorization_path=args.runtime_authorization,
        execution_scope="MINI_SMOKE",
        device="cuda:0",
    )
    if adapter.preflight().status != "READY_FOR_MINI_SMOKE":
        raise RuntimeError("SAO offline mini-smoke preflight is not ready")
    placement = PlacementConfig(
        node="an12",
        physical_gpu_id=args.physical_gpu_id,
        logical_gpu_id=0,
        tp_width=1,
        replica_count=1,
        minimum_free_vram_bytes=60_000_000_000,
        post_load_reserve_bytes=20_000_000_000,
        lock_root=LOCK_ROOT,
        required_gpu_name_substring="A800",
        maximum_idle_utilization_percent=5,
    )
    prompts = (
        (
            "sao-mini-repro",
            "A purely instrumental arrangement led throughout by piano, upright bass, "
            "and brushed drums, with a clean continuous texture.",
            "S-0011",
            73193011,
        ),
        (
            "sao-mini-repro",
            "A purely instrumental arrangement led throughout by piano, upright bass, "
            "and brushed drums, with a clean continuous texture.",
            "S-0011",
            73193011,
        ),
        (
            "sao-mini-resident-cost",
            "A purely instrumental arrangement led throughout by acoustic guitar, warm "
            "bass, and hand percussion, with a clean continuous texture.",
            "S-0012",
            73193012,
        ),
    )
    requests = [
        GenerationRequest(
            prompt_id=prompt_id,
            prompt=prompt,
            seed_id=seed_id,
            seed=seed,
            duration_seconds=30.0,
            output_path=run_dir / "audio" / f"call-{index:02d}.wav",
        )
        for index, (prompt_id, prompt, seed_id, seed) in enumerate(prompts)
    ]
    command = " ".join(shlex.quote(value) for value in sys.argv)
    context = RunContext(
        run_id=run_dir.name,
        command=command,
        git_commit=git_commit,
        node=node,
        gpu_ids=(str(args.physical_gpu_id),),
        placement_justification=(
            "an12 TP1 single replica on one verified-idle A800; GPUs 0-3 and all "
            "neighbor processes are untouched."
        ),
        package_freeze_sha256=environment_evidence["package_freeze_sha256"],
    )
    _prepare_fixed_run_parent(run_dir)
    attempt_preparation = prepare_sao_engineering_retry_attempt(
        args.runtime_authorization,
        requested_run_dir=run_dir,
        live_config_path=args.config,
        git_commit=git_commit,
        decisions_path=args.decisions,
        decision_id=args.engineering_decision_id,
        decision_block_sha256=args.engineering_decision_block_sha256,
        environment_manifest_path=args.environment_manifest,
    )
    lease = DeviceLease(placement)
    with lease:
        observation = NvidiaSmiProbe(placement).require_safe(
            minimum_free_vram_bytes=placement.minimum_free_vram_bytes,
            maximum_utilization_percent=placement.maximum_idle_utilization_percent,
        )
        placement_observation = {
            "node": observation.node,
            "physical_gpu_id": observation.physical_gpu_id,
            "gpu_uuid": observation.gpu_uuid,
            "gpu_name": observation.gpu_name,
            "free_vram_bytes": observation.free_vram_bytes,
            "total_vram_bytes": observation.total_vram_bytes,
            "utilization_percent": observation.utilization_percent,
            "neighbor_compute_pids": list(observation.compute_pids),
        }
        # The durable claim is the last operation before model loading. A busy
        # device therefore queues/fails without consuming the exact-three-call
        # authority. Every later failure remains immutable under a new run ID.
        attempt_claim = consume_sao_engineering_retry_attempt(
            args.runtime_authorization,
            requested_run_dir=run_dir,
            live_config_path=args.config,
            git_commit=git_commit,
            decisions_path=args.decisions,
            decision_id=args.engineering_decision_id,
            decision_block_sha256=args.engineering_decision_block_sha256,
            environment_manifest_path=args.environment_manifest,
            prepared_attempt=attempt_preparation,
        )
        placement_observation["operational_attempt_claim_path"] = attempt_claim["path"]
        placement_observation["operational_attempt_claim_sha256"] = attempt_claim["sha256"]
        result = run_sao_mini_smoke(
            adapter,
            requests,
            run_dir=run_dir,
            context=context,
            placement_observation=placement_observation,
        )
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONPYCACHEPREFIX", "/tmp/pxy1289-sao-live-v2-003-pycache")
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from backbones.contracts import GenerationMeasurement
from benchmark_core.adapter_bridge import BackboneCoreBridge
from benchmark_core.artifacts import StagedGeneration, basic_audio_sanity, commit_generation
from benchmark_core.claims import AlreadyClaimed, CallClaimStore, HardCapReached
from benchmark_core.config import (
    ACE_MODEL_ID,
    BLOCKED_ON_ENGINEERING_FAILURE,
    BLOCKED_ON_LICENSE,
    RESTART_POOL_LABEL,
    SA3_MODEL_ID,
    SAO_MODEL_ID,
    STATE_CAPTURE_MODE,
    STATE_CORE_LAUNCH_STATUS,
    STATE_PREVIEW_SOURCE,
    BudgetConfig,
    CoreConfigurationError,
    ModelExecutionConfig,
    PlacementConfig,
    load_core_execution_config,
    sha256_file,
)
from benchmark_core.heartbeat import (
    SHA256_ZERO,
    HeartbeatLoop,
    HeartbeatStaleError,
    heartbeat_is_stale,
    utc_now,
    validate_heartbeat,
)
from benchmark_core.launcher import (
    GitLaunchState,
    LaunchAuthorizationError,
    prepare_run,
    validate_external_launch_claim,
    validate_run_bundle,
    verify_decision_authorization,
)
from benchmark_core.ledger import HashChainedLedger, validate_ledger
from benchmark_core.placement import NvidiaSmiProbe, PlacementBlocked, PlacementUnavailable
from benchmark_core.queue import build_queue, canonical_json, load_queue
from benchmark_core.state_queue import (
    build_state_capture_queue,
    load_state_capture_queue,
)
from benchmark_core.supervisor import inspect_worker
from benchmark_core.worker import BenchmarkWorker

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _core_config(tmp_path: Path, *, scheduled_calls: int = 4) -> Path:
    prompts = ROOT / "prompts" / "v2"
    prompt_hashes = {
        name: _sha(prompts / name)
        for name in (
            "vocal_instrumental.json",
            "tempo.json",
            "integrity.json",
            "structure_exploratory.json",
            "seed_registry.json",
        )
    }
    statistics = ROOT / "configs" / "statistics_v2.json"
    adapter = ROOT / "configs" / "backbones" / "stable_audio_3_medium_base.json"
    integrity = ROOT / "provenance" / "b1" / "integrity_synthetic_validation.json"
    cold_plus_first = 10.0
    unit = 2.0
    cap = cold_plus_first + max(scheduled_calls - 1, 0) * 2 * unit
    terminal = tmp_path / "phase-b-terminal.json"
    _write_json(
        terminal,
        {
            "models": {
                ACE_MODEL_ID: {
                    "build_status": "FAIL_ESCALATED",
                    "queue_status": BLOCKED_ON_ENGINEERING_FAILURE,
                },
                SA3_MODEL_ID: {
                    "build_status": "MEASURED_READY",
                    "cold_plus_first_seconds": cold_plus_first,
                    "cost_status": "MEASURED",
                    "queue_status": "READY",
                    "resident_unit_seconds": unit,
                },
                SAO_MODEL_ID: {
                    "build_status": BLOCKED_ON_LICENSE,
                    "queue_status": BLOCKED_ON_LICENSE,
                },
            },
            "schema_version": 1,
            "status": "TERMINAL",
        },
    )
    config = {
        "execution": {
            "heartbeat_interval_seconds": 30,
            "heartbeat_stale_after_seconds": 120,
            "max_duration_seconds": 30.0,
            "run_root": str(tmp_path / "runs"),
            "shard_size": 4,
            "state_capture": {
                "axes": ["vocal_instrumental", "tempo", "integrity"],
                "capture_mode": STATE_CAPTURE_MODE,
                "checkpoint_fractions": [0.25, 0.5, 0.75],
                "conditions": ["BASE"],
                "doubling_root_indices": [4, 5, 6, 7],
                "eligible_model_ids": ["stabilityai/stable-audio-3-medium-base"],
                "initial_root_indices": [0, 1, 2, 3],
                "ordinary_core_launch_status": STATE_CORE_LAUNCH_STATUS,
                "preview_source": STATE_PREVIEW_SOURCE,
                "restart_outcome_label": RESTART_POOL_LABEL,
            },
        },
        "integrity_synthetic_validation": {
            "report_path": str(integrity),
            "report_sha256": _sha(integrity),
            "status": "PASS",
        },
        "phase_b_terminal": {
            "path": "provenance/b2/build_status_terminal_v2.json",
            "sha256": _sha(terminal),
            "status": "TERMINAL",
        },
        "models": [
            {
                "core_execution": {
                    "adapter_config_path": str(adapter),
                    "adapter_config_sha256": _sha(adapter),
                    "budget": {
                        "cold_plus_first_seconds": cold_plus_first,
                        "gpu_seconds_cap": cap,
                        "resident_unit_seconds": unit,
                        "scheduled_calls": scheduled_calls,
                    },
                    "expected_channels": 2,
                    "placement": {
                        "lock_root": str(tmp_path / "locks"),
                        "logical_gpu_id": 0,
                        "maximum_idle_utilization_percent": 5,
                        "minimum_free_vram_bytes": 60_000_000_000,
                        "node": "an12",
                        "physical_gpu_id": 3,
                        "post_load_reserve_bytes": 20_000_000_000,
                        "replica_count": 1,
                        "required_gpu_name_substring": "A800",
                        "tp_width": 1,
                    },
                    "state_capture_status": "READY",
                },
                "model_id": SA3_MODEL_ID,
                "queue_status": "READY",
                "slug": "sa3-medium-base",
            },
            {
                "model_id": SAO_MODEL_ID,
                "queue_status": BLOCKED_ON_LICENSE,
                "slug": "stable-audio-open-1-0",
            },
            {
                "model_id": ACE_MODEL_ID,
                "queue_status": BLOCKED_ON_ENGINEERING_FAILURE,
                "slug": "ace-step-v1",
            },
        ],
        "prompt_root": str(prompts),
        "prompt_sha256": prompt_hashes,
        "schema_version": 2,
        "statistics_config": {"path": str(statistics), "sha256": _sha(statistics)},
    }
    path = tmp_path / "core.json"
    _write_json(path, config)
    return path


def _load_test_config(path: Path):
    return load_core_execution_config(
        path,
        repo_root=ROOT,
        phase_b_terminal_path_override=path.parent / "phase-b-terminal.json",
    )


def _write_completed_sa3_fixture(tmp_path: Path, config_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "completed-sa3-run"
    generation = build_queue(
        config_path,
        run_dir / "queues" / "generation",
        authorized_model_ids=(SA3_MODEL_ID,),
    )
    heartbeat_path = run_dir / "workers" / "sa3-medium-base" / "heartbeat.json"
    tail_sha = "8" * 64
    _write_json(
        heartbeat_path,
        {
            "completed": 1_536,
            "failed": 0,
            "last_ledger_sha256": tail_sha,
            "run_id": "completed-sa3-run",
            "state": "COMPLETE",
        },
    )
    ledger_path = run_dir / "ledger.jsonl"
    ledger_path.write_text(
        json.dumps({"ledger_row_sha256": tail_sha}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    generation_path = Path(generation["queue_path"])
    generation_manifest_path = generation_path.parent / "queue-manifest.json"
    receipt_path = tmp_path / "sa3-completion.json"
    _write_json(
        receipt_path,
        {
            "completed_calls": 1_536,
            "failed_calls": 0,
            "generation_queue": {
                "manifest_path": str(generation_manifest_path),
                "manifest_sha256": _sha(generation_manifest_path),
                "path": str(generation_path),
                "row_count": 1_536,
                "sha256": _sha(generation_path),
            },
            "heartbeat": {
                "path": str(heartbeat_path),
                "sha256": _sha(heartbeat_path),
            },
            "ledger": {
                "path": str(ledger_path),
                "row_count": 1,
                "sha256": _sha(ledger_path),
                "tail_sha256": tail_sha,
            },
            "model_id": SA3_MODEL_ID,
            "retained_counts": {
                "commit_records": 1_536,
                "request_claims": 1_536,
                "wav_files": 1_536,
            },
            "run_dir": str(run_dir),
            "run_id": "completed-sa3-run",
            "schema_version": 1,
            "status": "COMPLETE",
        },
    )
    return receipt_path, generation_path


def _configure_ace_incremental(
    config_path: Path,
    completion_receipt: Path,
) -> None:
    terminal_path = config_path.parent / "phase-b-terminal.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["models"][ACE_MODEL_ID] = {
        "build_status": "MEASURED_READY",
        "cold_plus_first_seconds": 10.0,
        "cost_status": "MEASURED",
        "mini_smoke_status": "MEASURED_MINI_SMOKE_PASS",
        "queue_status": "READY",
        "resident_unit_seconds": 2.0,
    }
    _write_json(terminal_path, terminal)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["phase_b_terminal"]["sha256"] = _sha(terminal_path)
    raw["execution"]["authorized_model_ids"] = [ACE_MODEL_ID]
    raw["execution"]["prior_model_completions"] = {
        SA3_MODEL_ID: {
            "path": str(completion_receipt),
            "sha256": _sha(completion_receipt),
        }
    }
    raw["models"][0]["core_execution"]["duration_tolerance_seconds"] = 0.25
    ace_adapter = ROOT / "configs" / "backbones" / "ace_step_v1.json"
    raw["models"][2]["queue_status"] = "READY"
    raw["models"][2]["core_execution"] = {
        "adapter_config_path": str(ace_adapter),
        "adapter_config_sha256": _sha(ace_adapter),
        "budget": {
            "cold_plus_first_seconds": 10.0,
            "gpu_seconds_cap": 10.0 + 1_535 * 4.0,
            "resident_unit_seconds": 2.0,
            "scheduled_calls": 1_536,
        },
        "duration_tolerance_seconds": 0.25,
        "expected_channels": 2,
        "placement": {
            "lock_root": str(config_path.parent / "locks"),
            "logical_gpu_id": 0,
            "maximum_idle_utilization_percent": 5,
            "minimum_free_vram_bytes": 60_000_000_000,
            "node": "an12",
            "physical_gpu_id": 4,
            "post_load_reserve_bytes": 20_000_000_000,
            "replica_count": 1,
            "required_gpu_name_substring": "A800",
            "tp_width": 1,
        },
        "state_capture_status": "AUTOMATIC_OUTPUT_ONLY",
    }
    _write_json(config_path, raw)


def test_strict_config_binds_statistics_state_and_exact_budget(tmp_path: Path) -> None:
    path = _core_config(tmp_path)
    config = _load_test_config(path)
    model = config.models[0]
    assert model.expected_sample_rate == 44_100
    assert model.expected_channels == 2
    assert model.budget is not None
    assert model.budget.load_reservation_seconds == 8.0
    assert model.budget.reservation_for_call(0) == 2.0
    assert model.budget.reservation_for_call(1) == 4.0
    assert len(config.state_capture.eligible_prompt_ids) == 36
    assert config.state_capture.conditions == ("BASE",)
    assert config.authorized_model_ids == (SA3_MODEL_ID,)
    assert config.prior_model_completions == {}
    assert model.duration_tolerance_seconds == 0.0
    assert config.phase_b_terminal.model_queue_statuses == {
        ACE_MODEL_ID: BLOCKED_ON_ENGINEERING_FAILURE,
        SA3_MODEL_ID: "READY",
        SAO_MODEL_ID: BLOCKED_ON_LICENSE,
    }

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["models"][0]["core_execution"]["budget"]["gpu_seconds_cap"] += 0.01
    _write_json(path, raw)
    with pytest.raises(CoreConfigurationError, match="gpu_seconds_cap"):
        _load_test_config(path)


def test_phase_b_terminal_receipt_controls_exact_model_queue_statuses(tmp_path: Path) -> None:
    path = _core_config(tmp_path)
    receipt_path = tmp_path / "phase-b-terminal.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["models"][ACE_MODEL_ID] = {
        "build_status": "MEASURED_READY",
        "cold_plus_first_seconds": 10.0,
        "cost_status": "MEASURED",
        "mini_smoke_status": "MEASURED_MINI_SMOKE_PASS",
        "queue_status": "READY",
        "resident_unit_seconds": 2.0,
    }
    _write_json(receipt_path, receipt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["phase_b_terminal"]["sha256"] = _sha(receipt_path)
    _write_json(path, raw)
    with pytest.raises(CoreConfigurationError, match="queue statuses drift"):
        _load_test_config(path)


def test_phase_b_measured_ace_pass_can_enter_ready_queue(tmp_path: Path) -> None:
    path = _core_config(tmp_path)
    receipt_path = tmp_path / "phase-b-terminal.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["models"][ACE_MODEL_ID] = {
        "build_status": "MEASURED_READY",
        "cold_plus_first_seconds": 10.0,
        "cost_status": "MEASURED",
        "mini_smoke_status": "MEASURED_MINI_SMOKE_PASS",
        "queue_status": "READY",
        "resident_unit_seconds": 2.0,
    }
    _write_json(receipt_path, receipt)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["phase_b_terminal"]["sha256"] = _sha(receipt_path)
    ace_adapter = ROOT / "configs" / "backbones" / "ace_step_v1.json"
    raw["models"][2]["queue_status"] = "READY"
    raw["models"][2]["core_execution"] = {
        "adapter_config_path": str(ace_adapter),
        "adapter_config_sha256": _sha(ace_adapter),
        "budget": {
            "cold_plus_first_seconds": 10.0,
            "gpu_seconds_cap": 10.0 + 3 * 4.0,
            "resident_unit_seconds": 2.0,
            "scheduled_calls": 4,
        },
        "duration_tolerance_seconds": 0.25,
        "expected_channels": 2,
        "placement": {
            "lock_root": str(tmp_path / "locks"),
            "logical_gpu_id": 0,
            "maximum_idle_utilization_percent": 5,
            "minimum_free_vram_bytes": 60_000_000_000,
            "node": "an29",
            "physical_gpu_id": 4,
            "post_load_reserve_bytes": 20_000_000_000,
            "replica_count": 1,
            "required_gpu_name_substring": "A800",
            "tp_width": 1,
        },
        "state_capture_status": "AUTOMATIC_OUTPUT_ONLY",
    }
    _write_json(path, raw)
    config = _load_test_config(path)
    assert {model.model_id for model in config.models if model.queue_status == "READY"} == {
        ACE_MODEL_ID,
        SA3_MODEL_ID,
    }


def test_incremental_config_requires_completion_and_exact_amended_tolerance(
    tmp_path: Path,
) -> None:
    path = _core_config(tmp_path)
    completion_receipt, _ = _write_completed_sa3_fixture(tmp_path, path)
    _configure_ace_incremental(path, completion_receipt)
    config = _load_test_config(path)
    assert config.authorized_model_ids == (ACE_MODEL_ID,)
    assert set(config.prior_model_completions) == {SA3_MODEL_ID}
    tolerances = {
        model.model_id: model.duration_tolerance_seconds
        for model in config.models
        if model.queue_status == "READY"
    }
    assert tolerances == {SA3_MODEL_ID: 0.25, ACE_MODEL_ID: 0.25}

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["execution"]["prior_model_completions"] = {}
    _write_json(path, raw)
    with pytest.raises(CoreConfigurationError, match="READY-but-excluded"):
        _load_test_config(path)

    raw["execution"]["prior_model_completions"] = {
        SA3_MODEL_ID: {
            "path": str(completion_receipt),
            "sha256": _sha(completion_receipt),
        }
    }
    raw["models"][2]["core_execution"]["duration_tolerance_seconds"] = 0.250001
    _write_json(path, raw)
    with pytest.raises(CoreConfigurationError, match="exceeds"):
        _load_test_config(path)


def test_phase_b_receipt_path_is_flexible_but_hash_bound(tmp_path: Path) -> None:
    path = _core_config(tmp_path)
    source = tmp_path / "phase-b-terminal.json"
    receipt = tmp_path / "receipts" / "phase-b-terminal-amended.json"
    _write_json(receipt, json.loads(source.read_text(encoding="utf-8")))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["execution"]["run_root"] = str(tmp_path.parent / f"{tmp_path.name}-external-runs")
    raw["phase_b_terminal"]["path"] = "receipts/phase-b-terminal-amended.json"
    raw["phase_b_terminal"]["sha256"] = _sha(receipt)
    _write_json(path, raw)
    config = load_core_execution_config(path, repo_root=tmp_path)
    assert config.phase_b_terminal.path == receipt.resolve()


def test_initial_and_supplemental_state_tiers_are_separate_and_locked(
    tmp_path: Path,
) -> None:
    config_path = _core_config(tmp_path)
    config = _load_test_config(config_path)
    generation_manifest = build_queue(config_path, tmp_path / "generation")
    generation = load_queue(Path(generation_manifest["queue_path"]))
    initial = build_state_capture_queue(
        generation,
        config.state_capture,
        tmp_path / "state-initial",
        root_indices=config.state_capture.initial_root_indices,
        tier="INITIAL",
        authorization_status="CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION",
    )
    supplemental = build_state_capture_queue(
        generation,
        config.state_capture,
        tmp_path / "state-supplemental",
        root_indices=config.state_capture.doubling_root_indices,
        tier="SUPPLEMENTAL",
        authorization_status=(
            "SUPPLEMENTAL_LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
        ),
    )
    assert initial["row_count"] == 432
    assert supplemental["row_count"] == 432
    assert initial["authorization_status"].startswith("CLOSED_")
    assert supplemental["authorization_status"].startswith("SUPPLEMENTAL_LOCKED_")
    initial_rows = load_state_capture_queue(Path(initial["queue_path"]))
    supplemental_rows = load_state_capture_queue(Path(supplemental["queue_path"]))
    assert {row["root_index"] for row in initial_rows} == {0, 1, 2, 3}
    assert {row["root_index"] for row in supplemental_rows} == {4, 5, 6, 7}
    assert all(
        row["preview_source_request_sha256"] == row["parent_request_sha256"]
        for row in initial_rows + supplemental_rows
    )


def test_run_bundle_binds_run_root_and_all_generation_and_state_bytes(tmp_path: Path) -> None:
    config_path = _core_config(tmp_path)
    config = _load_test_config(config_path)
    run_dir = tmp_path / "run"
    generation = build_queue(config_path, run_dir / "queues" / "generation")
    generation_rows = load_queue(Path(generation["queue_path"]))
    initial = build_state_capture_queue(
        generation_rows,
        config.state_capture,
        run_dir / "queues" / "state-initial",
        root_indices=config.state_capture.initial_root_indices,
        tier="INITIAL",
        authorization_status="CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION",
    )
    supplemental = build_state_capture_queue(
        generation_rows,
        config.state_capture,
        run_dir / "queues" / "state-supplemental",
        root_indices=config.state_capture.doubling_root_indices,
        tier="SUPPLEMENTAL",
        authorization_status=(
            "SUPPLEMENTAL_LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
        ),
    )

    def binding(record: dict, manifest_name: str) -> dict:
        queue_path = Path(record["queue_path"])
        manifest_path = queue_path.parent / manifest_name
        return {
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "queue_path": str(queue_path.resolve()),
            "queue_sha256": sha256_file(queue_path),
            "row_count": record["row_count"],
        }

    claim = {
        "authorized_model_ids": list(config.authorized_model_ids),
        "config_sha256": config.source_sha256,
        "git_head": "b" * 40,
        "queue_bindings": {
            "generation": binding(generation, "queue-manifest.json"),
            "state_capture_initial": binding(initial, "state-capture-manifest.json"),
            "state_capture_supplemental": binding(supplemental, "state-capture-manifest.json"),
        },
        "run_id": "run",
    }
    manifest = {
        "authorized_model_ids": list(config.authorized_model_ids),
        "config_sha256": config.source_sha256,
        "generation_queue_manifest": generation,
        "git_commit": "b" * 40,
        "run_id": "run",
        "state_capture_initial_manifest": initial,
        "state_capture_supplemental_manifest": supplemental,
        "status": "PREPARED_NO_MODEL_CALLS",
    }
    validated = validate_run_bundle(run_dir, manifest, claim, config=config)
    assert validated["generation"]["row_count"] == 1_536
    assert validated["state_capture_initial"]["row_count"] == 432

    tampered = dict(manifest)
    tampered["generation_queue_manifest"] = dict(generation, row_count=1_535)
    with pytest.raises(LaunchAuthorizationError, match="manifest bytes disagree"):
        validate_run_bundle(run_dir, tampered, claim, config=config)


def test_incremental_bundle_executes_only_ace_and_sources_closed_sa3_state(
    tmp_path: Path,
) -> None:
    config_path = _core_config(tmp_path)
    completion_receipt, completed_sa3_queue = _write_completed_sa3_fixture(
        tmp_path,
        config_path,
    )
    _configure_ace_incremental(config_path, completion_receipt)
    config = _load_test_config(config_path)
    run_dir = tmp_path / "incremental-run"
    generation = build_queue(
        config_path,
        run_dir / "queues" / "generation",
        authorized_model_ids=config.authorized_model_ids,
    )
    generation_rows = load_queue(Path(generation["queue_path"]))
    assert len(generation_rows) == 1_536
    assert {row["model_id"] for row in generation_rows} == {ACE_MODEL_ID}
    state_source_rows = generation_rows + load_queue(completed_sa3_queue)
    initial = build_state_capture_queue(
        state_source_rows,
        config.state_capture,
        run_dir / "queues" / "state-initial",
        root_indices=config.state_capture.initial_root_indices,
        tier="INITIAL",
        authorization_status="CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION",
    )
    supplemental = build_state_capture_queue(
        state_source_rows,
        config.state_capture,
        run_dir / "queues" / "state-supplemental",
        root_indices=config.state_capture.doubling_root_indices,
        tier="SUPPLEMENTAL",
        authorization_status=(
            "SUPPLEMENTAL_LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
        ),
    )

    def binding(record: dict, manifest_name: str) -> dict:
        queue_path = Path(record["queue_path"])
        manifest_path = queue_path.parent / manifest_name
        return {
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha(manifest_path),
            "queue_path": str(queue_path),
            "queue_sha256": _sha(queue_path),
            "row_count": record["row_count"],
        }

    claim = {
        "authorized_model_ids": [ACE_MODEL_ID],
        "config_sha256": config.source_sha256,
        "git_head": "b" * 40,
        "queue_bindings": {
            "generation": binding(generation, "queue-manifest.json"),
            "state_capture_initial": binding(initial, "state-capture-manifest.json"),
            "state_capture_supplemental": binding(
                supplemental,
                "state-capture-manifest.json",
            ),
        },
        "run_id": "incremental-run",
    }
    manifest = {
        "authorized_model_ids": [ACE_MODEL_ID],
        "config_sha256": config.source_sha256,
        "generation_queue_manifest": generation,
        "git_commit": "b" * 40,
        "run_id": "incremental-run",
        "state_capture_initial_manifest": initial,
        "state_capture_supplemental_manifest": supplemental,
        "status": "PREPARED_NO_MODEL_CALLS",
    }
    validated = validate_run_bundle(run_dir, manifest, claim, config=config)
    assert validated["generation"]["row_count"] == 1_536
    initial_rows = load_state_capture_queue(Path(initial["queue_path"]))
    assert {row["model_id"] for row in initial_rows} == {SA3_MODEL_ID}
    assert initial["authorization_status"].startswith("CLOSED_")
    assert supplemental["authorization_status"].startswith("SUPPLEMENTAL_LOCKED_")

    tampered_claim = dict(claim, authorized_model_ids=[SA3_MODEL_ID])
    with pytest.raises(LaunchAuthorizationError, match="allowlist"):
        validate_run_bundle(run_dir, manifest, tampered_claim, config=config)

    sa3_model = next(model for model in config.models if model.model_id == SA3_MODEL_ID)
    with pytest.raises(ValueError, match="authorized-model allowlist"):
        BenchmarkWorker(
            run_dir=run_dir,
            run_id="incremental-run",
            git_commit="b" * 40,
            config_sha256=config.source_sha256,
            prompt_manifest_sha256="d" * 64,
            model=sa3_model,
            adapter=SimpleNamespace(model_id=SA3_MODEL_ID),
            heartbeat_interval_seconds=30,
            heartbeat_stale_after_seconds=90,
            launch_claim_path=run_dir / "unused-claim.json",
            authorized_model_ids=config.authorized_model_ids,
        )


def test_prepare_run_refuses_prior_queue_drift_after_config_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _core_config(tmp_path)
    completion_receipt, completed_sa3_queue = _write_completed_sa3_fixture(
        tmp_path,
        config_path,
    )
    _configure_ace_incremental(config_path, completion_receipt)
    loaded_config = _load_test_config(config_path)

    def load_then_drift(*_args, **_kwargs):
        with completed_sa3_queue.open("a", encoding="utf-8") as handle:
            handle.write("{}\n")
        return loaded_config

    monkeypatch.setattr(
        "benchmark_core.launcher.load_core_execution_config",
        load_then_drift,
    )
    monkeypatch.setattr(
        "benchmark_core.launcher.observe_clean_origin_main",
        lambda _root: GitLaunchState(head="b" * 40, origin_main="b" * 40),
    )
    monkeypatch.setattr(
        "benchmark_core.launcher.verify_decision_authorization",
        lambda *_args, **_kwargs: {},
    )
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text("# test-only authorization stub\n", encoding="utf-8")

    with pytest.raises(LaunchAuthorizationError, match="drifted after config validation"):
        prepare_run(
            config_path,
            run_id="incremental-drift-test",
            decisions_path=decisions,
            decision_id="D-TEST",
            frozen_files=(),
            repo_root=ROOT,
        )


def _request(index: int, model_id: str = "model") -> dict:
    row = {
        "duration_seconds": 30.0,
        "model_id": model_id,
        "output_relpath": f"model/axis/prompt/base/root-{index:02d}.wav",
        "prompt": "prompt",
        "prompt_id": "prompt",
        "root_index": index,
        "seed": index + 1,
        "sequence": index + 1,
    }
    row["request_sha256"] = hashlib.sha256(canonical_json(row).encode()).hexdigest()
    return row


def test_claims_reserve_exact_frozen_formula_and_never_retry(tmp_path: Path) -> None:
    store = CallClaimStore(
        tmp_path / "claims",
        model_id="model",
        gpu_seconds_cap=18.0,
        scheduled_calls=3,
        cold_plus_first_seconds=10.0,
        resident_unit_seconds=2.0,
    )
    load = store.reserve_load({"test": True})
    assert load["reserved_gpu_seconds"] == 8.0
    claims = [store.claim(_request(index), metadata={}) for index in range(3)]
    assert [row["reserved_gpu_seconds"] for row in claims] == [2.0, 4.0, 4.0]
    assert store.usage()["reserved_gpu_seconds"] == 18.0
    with pytest.raises(AlreadyClaimed):
        store.claim(_request(0), metadata={})
    with pytest.raises(HardCapReached):
        store.claim(_request(3), metadata={})

    overrun = CallClaimStore(
        tmp_path / "overrun",
        model_id="model",
        gpu_seconds_cap=18.0,
        scheduled_calls=3,
        cold_plus_first_seconds=10.0,
        resident_unit_seconds=2.0,
    )
    overrun.reserve_load({})
    first = _request(0)
    overrun.claim(first, metadata={})
    overrun.record_call_observed(first["request_sha256"], 6.0)
    overrun.claim(_request(1), metadata={})
    with pytest.raises(HardCapReached):
        overrun.claim(_request(2), metadata={})


def test_ledger_request_state_machine_is_terminal_and_no_skip(tmp_path: Path) -> None:
    ledger = HashChainedLedger(tmp_path / "ledger.jsonl")
    request = "a" * 64
    ledger.transition(request, "CLAIMED")
    with pytest.raises(ValueError, match="invalid request transition"):
        ledger.transition(request, "SUCCEEDED")
    ledger.transition(request, "CALL_STARTED")
    ledger.transition(request, "FAILED")
    with pytest.raises(ValueError, match="invalid request transition"):
        ledger.transition(request, "CALL_STARTED")
    assert ledger.request_states() == {request: "FAILED"}


def test_shared_ledger_initialization_tolerates_competing_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared" / "ledger.jsonl"
    real_open = os.open
    raced = {"created": False}

    def racing_open(target, flags, mode=0o777):
        if Path(target) == path and flags & os.O_EXCL and not raced["created"]:
            raced["created"] = True
            path.touch(exist_ok=False)
            raise FileExistsError(path)
        return real_open(target, flags, mode)

    monkeypatch.setattr("benchmark_core.ledger.os.open", racing_open)
    ledger = HashChainedLedger(path)
    assert ledger.path == path.resolve()
    assert ledger.path.is_file()


def _placement(tmp_path: Path) -> PlacementConfig:
    return PlacementConfig(
        node="an12",
        physical_gpu_id=3,
        logical_gpu_id=0,
        tp_width=1,
        replica_count=1,
        minimum_free_vram_bytes=60_000_000_000,
        post_load_reserve_bytes=20_000_000_000,
        lock_root=tmp_path / "locks",
        required_gpu_name_substring="A800",
        maximum_idle_utilization_percent=5,
    )


def test_gpu_probe_requires_a800_idle_memory_and_no_neighbors(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command):
        commands.append(tuple(command))
        if any(part.startswith("--query-gpu=") for part in command):
            return "3, GPU-abc, NVIDIA A800 80GB, 70000, 80000, 2\n"
        return ""

    probe = NvidiaSmiProbe(
        _placement(tmp_path),
        runner=runner,
        hostname="an12",
        environ={"CUDA_VISIBLE_DEVICES": "3"},
    )
    observed = probe.require_safe(
        minimum_free_vram_bytes=60_000_000_000, maximum_utilization_percent=5
    )
    assert observed.gpu_name == "NVIDIA A800 80GB"
    assert all(command[0] == "nvidia-smi" for command in commands)

    def wrong_gpu(command):
        if any(part.startswith("--query-gpu=") for part in command):
            return "3, GPU-abc, NVIDIA H100, 70000, 80000, 0\n"
        return ""

    bad = NvidiaSmiProbe(
        _placement(tmp_path),
        runner=wrong_gpu,
        hostname="an12",
        environ={"CUDA_VISIBLE_DEVICES": "3"},
    )
    with pytest.raises(PlacementBlocked, match="does not contain"):
        bad.require_safe(minimum_free_vram_bytes=1, maximum_utilization_percent=5)

    def busy_gpu(command):
        if any(part.startswith("--query-gpu=") for part in command):
            return "3, GPU-abc, NVIDIA A800 80GB, 70000, 80000, 6\n"
        return "GPU-abc, 999, 100\n"

    busy = NvidiaSmiProbe(
        _placement(tmp_path),
        runner=busy_gpu,
        hostname="an12",
        environ={"CUDA_VISIBLE_DEVICES": "3"},
    )
    with pytest.raises(PlacementBlocked, match="compute neighbors"):
        busy.require_safe(minimum_free_vram_bytes=1, maximum_utilization_percent=5)

    def utilization_only(command):
        if any(part.startswith("--query-gpu=") for part in command):
            return "3, GPU-abc, NVIDIA A800 80GB, 70000, 80000, 6\n"
        return ""

    utilized = NvidiaSmiProbe(
        _placement(tmp_path),
        runner=utilization_only,
        hostname="an12",
        environ={"CUDA_VISIBLE_DEVICES": "3"},
    )
    with pytest.raises(PlacementBlocked, match="idle threshold"):
        utilized.require_safe(minimum_free_vram_bytes=1, maximum_utilization_percent=5)


def _heartbeat_payload() -> dict:
    return {
        "completed": 0,
        "config_sha256": "a" * 64,
        "cumulative_synchronized_gpu_seconds": 0.0,
        "current_request_sha256": None,
        "current_shard": 0,
        "failed": 0,
        "git_commit": "b" * 40,
        "last_ledger_sha256": SHA256_ZERO,
        "logical_gpu_id": 0,
        "node": "an12",
        "peak_allocated_bytes": 0,
        "peak_reserved_bytes": 0,
        "physical_gpu_id": 3,
        "pid": 123,
        "prompt_manifest_sha256": "c" * 64,
        "run_id": "run",
        "schema_version": 1,
        "state": "RUNNING",
        "updated_at_utc": utc_now(),
    }


def test_heartbeat_schema_loop_snapshot_and_staleness(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    loop = HeartbeatLoop(path, _heartbeat_payload(), 0.05).start()
    loop.flush()
    loop.update(completed=1)
    snapshot = loop.snapshot(tmp_path / "snapshots", 0)
    loop.stop()
    assert snapshot.is_file()
    assert validate_heartbeat(json.loads(path.read_text(encoding="utf-8")))["completed"] == 1
    assert inspect_worker(path, stale_after_seconds=5).assignment_allowed is True
    old = datetime.now(timezone.utc) - timedelta(seconds=10)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["updated_at_utc"] = old.isoformat()
    assert heartbeat_is_stale(path, 5, now=datetime.now(timezone.utc)) is False
    stale_path = tmp_path / "stale.json"
    _write_json(stale_path, value)
    assert heartbeat_is_stale(stale_path, 5, now=datetime.now(timezone.utc)) is True
    decision = inspect_worker(stale_path, stale_after_seconds=5)
    assert decision.assignment_allowed is False
    assert decision.reason == "heartbeat is stale"
    with pytest.raises(ValueError, match="schema mismatch"):
        validate_heartbeat({"state": "RUNNING"})


def test_artifact_commit_enforces_native_stereo_format_and_no_clobber(tmp_path: Path) -> None:
    staged_path = tmp_path / "staged.wav"
    frames = np.sin(np.linspace(0, 100, 4_410, dtype=np.float32))
    stereo = np.column_stack((frames, frames))
    sf.write(staged_path, stereo, 44_100, subtype="FLOAT")
    request = {
        "duration_seconds": 0.1,
        "model_id": "model",
        "output_relpath": "model/axis/prompt/base/root-00.wav",
        "prompt": "prompt",
        "prompt_id": "prompt",
        "root_index": 0,
        "seed": 1,
        "sequence": 1,
    }
    request["request_sha256"] = hashlib.sha256(canonical_json(request).encode()).hexdigest()
    staged = StagedGeneration(
        wav_path=staged_path,
        actual_nfe=10,
        synchronized_wall_seconds=1.0,
        peak_allocated_bytes=100,
        peak_reserved_bytes=200,
        sample_rate=44_100,
        channels=2,
    )
    commit = commit_generation(
        tmp_path / "artifacts",
        request,
        staged,
        expected_sample_rate=44_100,
        expected_channels=2,
    )
    assert commit["status"] == "COMMITTED"
    with pytest.raises(FileExistsError):
        commit_generation(
            tmp_path / "artifacts",
            request,
            staged,
            expected_sample_rate=44_100,
            expected_channels=2,
        )
    wrong = dict(request, output_relpath="model/axis/prompt/base/root-01.wav")
    wrong.pop("request_sha256")
    wrong["request_sha256"] = hashlib.sha256(canonical_json(wrong).encode()).hexdigest()
    with pytest.raises(ValueError, match="format"):
        commit_generation(
            tmp_path / "artifacts",
            wrong,
            staged,
            expected_sample_rate=48_000,
            expected_channels=2,
        )
    long_path = tmp_path / "staged-too-long.wav"
    sf.write(long_path, np.vstack((stereo, stereo[:1])), 44_100, subtype="FLOAT")
    too_long = StagedGeneration(
        wav_path=long_path,
        actual_nfe=10,
        synchronized_wall_seconds=1.0,
        peak_allocated_bytes=100,
        peak_reserved_bytes=200,
        sample_rate=44_100,
        channels=2,
    )
    too_long_request = dict(request, output_relpath="model/axis/prompt/base/root-02.wav")
    too_long_request.pop("request_sha256")
    too_long_request["request_sha256"] = hashlib.sha256(
        canonical_json(too_long_request).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="duration error"):
        commit_generation(
            tmp_path / "artifacts",
            too_long_request,
            too_long,
            expected_sample_rate=44_100,
            expected_channels=2,
        )


def test_ace_native_duration_passes_core_tolerance_and_overage_fails(
    tmp_path: Path,
) -> None:
    sample_rate = 48_000
    native_frames = 1_435_551
    native_path = tmp_path / "ace-native.wav"
    sf.write(
        native_path,
        np.full((native_frames, 2), 0.01, dtype=np.float32),
        sample_rate,
        subtype="FLOAT",
    )
    request = {
        "duration_seconds": 30.0,
        "model_id": ACE_MODEL_ID,
        "output_relpath": "ace-step-v1/axis/prompt/base/root-00.wav",
        "prompt": "prompt",
        "prompt_id": "prompt",
        "root_index": 0,
        "seed": 1,
        "sequence": 1,
    }
    request["request_sha256"] = hashlib.sha256(canonical_json(request).encode()).hexdigest()
    staged = StagedGeneration(
        wav_path=native_path,
        actual_nfe=45,
        synchronized_wall_seconds=1.0,
        peak_allocated_bytes=100,
        peak_reserved_bytes=200,
        sample_rate=sample_rate,
        channels=2,
    )
    commit = commit_generation(
        tmp_path / "ace-artifacts",
        request,
        staged,
        expected_sample_rate=sample_rate,
        expected_channels=2,
        duration_tolerance_seconds=0.25,
    )
    sanity_path = (
        tmp_path / "ace-artifacts" / request["output_relpath"]
    ).with_suffix(".sanity.json")
    sanity = json.loads(sanity_path.read_text(encoding="utf-8"))["sanity"]
    assert commit["status"] == "COMMITTED"
    assert sanity["duration_seconds"] == 29.9073125
    assert sanity["duration_within_tolerance"] is True
    assert sanity["duration_tolerance_seconds"] == 0.25

    boundary_path = tmp_path / "ace-boundary.wav"
    sf.write(
        boundary_path,
        np.full((1_428_000, 2), 0.01, dtype=np.float32),
        sample_rate,
        subtype="FLOAT",
    )
    assert basic_audio_sanity(
        boundary_path,
        expected_duration_seconds=30.0,
        expected_sample_rate=sample_rate,
        expected_channels=2,
        duration_tolerance_seconds=0.25,
    )["duration_within_tolerance"] is True

    outside_path = tmp_path / "ace-outside.wav"
    sf.write(
        outside_path,
        np.full((1_427_999, 2), 0.01, dtype=np.float32),
        sample_rate,
        subtype="FLOAT",
    )
    with pytest.raises(ValueError, match="exceeds"):
        basic_audio_sanity(
            outside_path,
            expected_duration_seconds=30.0,
            expected_sample_rate=sample_rate,
            expected_channels=2,
            duration_tolerance_seconds=0.25,
        )

    for invalid_tolerance in (-0.001, 0.250001, float("nan"), float("inf"), True):
        with pytest.raises((TypeError, ValueError), match="tolerance"):
            basic_audio_sanity(
                native_path,
                expected_duration_seconds=30.0,
                expected_sample_rate=sample_rate,
                expected_channels=2,
                duration_tolerance_seconds=invalid_tolerance,
            )

    with pytest.raises(ValueError, match="artifact maximum"):
        commit_generation(
            tmp_path / "rejected-tolerance-artifacts",
            request,
            staged,
            expected_sample_rate=sample_rate,
            expected_channels=2,
            duration_tolerance_seconds=0.250001,
        )
    assert not (tmp_path / "rejected-tolerance-artifacts").exists()


class _FakeLease:
    def __init__(self) -> None:
        self.held = False
        self.acquire_count = 0
        self.release_count = 0

    def acquire(self):
        self.acquire_count += 1
        self.held = True
        return self

    def release(self):
        if self.held:
            self.release_count += 1
            self.held = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return None


class _FakeProbe:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def require_safe(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace()


class _FakeCoreAdapter:
    model_id = "model"

    def __init__(self) -> None:
        self.load_count = 0
        self.generate_count = 0
        self.close_count = 0
        self.worker = None

    def preflight(self):
        return {"status": "READY"}

    def load(self):
        self.load_count += 1
        return {"load_wall_seconds": 1.0}

    def generate(self, request, staging_dir, state_contracts):
        assert not state_contracts
        assert self.worker is not None
        self.worker.claims.assert_claimed(request["request_sha256"])
        assert self.worker.ledger.request_states()[request["request_sha256"]] == "CALL_STARTED"
        self.generate_count += 1
        path = staging_dir / "waveform.wav"
        path.write_bytes(b"staged")
        return StagedGeneration(
            wav_path=path,
            actual_nfe=10,
            synchronized_wall_seconds=1.0,
            peak_allocated_bytes=100,
            peak_reserved_bytes=200,
            sample_rate=44_100,
            channels=2,
        )

    def close(self):
        self.close_count += 1


def _write_test_launch_claim(path: Path, run_dir: Path) -> None:
    _write_json(
        path,
        {
            "authorized_model_ids": ["model"],
            "config_sha256": "a" * 64,
            "git_head": "b" * 40,
            "git_origin_main": "b" * 40,
            "queue_bindings": {
                "generation": {},
                "state_capture_initial": {},
                "state_capture_supplemental": {},
            },
            "run_dir": str(run_dir.resolve()),
            "run_id": "run",
            "schema_version": 2,
            "status": "AUTHORIZED_CLEAN_ORIGIN_MAIN",
        },
    )


def _worker_model(tmp_path: Path, scheduled_calls: int) -> ModelExecutionConfig:
    cold_plus_first = 10.0
    unit = 1.0
    return ModelExecutionConfig(
        model_id="model",
        slug="model",
        queue_status="READY",
        adapter_config_path=tmp_path / "adapter.json",
        adapter_config_sha256="c" * 64,
        placement=_placement(tmp_path),
        budget=BudgetConfig(
            scheduled_calls=scheduled_calls,
            cold_plus_first_seconds=cold_plus_first,
            resident_unit_seconds=unit,
            gpu_seconds_cap=(cold_plus_first + max(scheduled_calls - 1, 0) * 2 * unit),
            load_reservation_seconds=cold_plus_first - unit,
        ),
        state_capture_status="AUTOMATIC_OUTPUT_ONLY",
        expected_sample_rate=44_100,
        expected_channels=2,
        duration_tolerance_seconds=0.0,
    )


def test_resident_worker_loads_once_and_continues_after_first_batch(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    launch_claim = run_dir / "launch.json"
    _write_test_launch_claim(launch_claim, run_dir)
    model = _worker_model(tmp_path, 8)
    adapter = _FakeCoreAdapter()

    def fake_commit(_root, request, _staged, **kwargs):
        assert kwargs == {
            "duration_tolerance_seconds": 0.0,
            "expected_sample_rate": 44_100,
            "expected_channels": 2,
        }
        return {"request_sha256": request["request_sha256"], "status": "COMMITTED"}

    monkeypatch.setattr("benchmark_core.worker.commit_generation", fake_commit)
    probe = _FakeProbe()
    lease = _FakeLease()
    worker = BenchmarkWorker(
        run_dir=run_dir,
        run_id="run",
        git_commit="b" * 40,
        config_sha256="a" * 64,
        prompt_manifest_sha256="d" * 64,
        model=model,
        adapter=adapter,
        heartbeat_interval_seconds=0.05,
        heartbeat_stale_after_seconds=5,
        launch_claim_path=launch_claim,
        authorized_model_ids=("model",),
        placement_wait_poll_seconds=0,
        probe=probe,
        lease=lease,
    )
    adapter.worker = worker
    result = worker.run([_request(index) for index in range(8)])
    assert result["status"] == "COMPLETE"
    assert adapter.load_count == 1
    assert adapter.generate_count == 8
    assert adapter.close_count == 1
    assert len(result["completed_shards"]) == 2
    assert result["completed_shards"][0]["status"] == "FIRST_LEDGERED_BATCH"
    assert worker.claims.usage()["reserved_gpu_seconds"] == 24.0
    ledger = validate_ledger(worker.ledger.path)
    assert len(ledger) == 24
    assert set(worker.ledger.request_states().values()) == {"SUCCEEDED"}
    assert len(probe.calls) == 11
    assert probe.calls[:2] == [
        {
            "maximum_utilization_percent": 5,
            "minimum_free_vram_bytes": 60_000_000_000,
        },
        {
            "maximum_utilization_percent": 5,
            "minimum_free_vram_bytes": 60_000_000_000,
        },
    ]
    assert lease.acquire_count == 1
    assert lease.release_count == 1


class _TransientLease(_FakeLease):
    def acquire(self):
        self.acquire_count += 1
        if self.acquire_count == 1:
            raise PlacementUnavailable("test lock is occupied")
        self.held = True
        return self


class _TransientProbe(_FakeProbe):
    def require_safe(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 2:
            raise PlacementUnavailable("test neighbor appeared after preflight")
        return SimpleNamespace()


def test_worker_waits_on_lock_and_post_preflight_neighbor_without_preemption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    launch_claim = run_dir / "launch.json"
    _write_test_launch_claim(launch_claim, run_dir)
    adapter = _FakeCoreAdapter()
    probe = _TransientProbe()
    lease = _TransientLease()
    monkeypatch.setattr(
        "benchmark_core.worker.commit_generation",
        lambda _root, request, _staged, **_kwargs: {
            "request_sha256": request["request_sha256"],
            "status": "COMMITTED",
        },
    )
    worker = BenchmarkWorker(
        run_dir=run_dir,
        run_id="run",
        git_commit="b" * 40,
        config_sha256="a" * 64,
        prompt_manifest_sha256="d" * 64,
        model=_worker_model(tmp_path, 4),
        adapter=adapter,
        heartbeat_interval_seconds=0.05,
        heartbeat_stale_after_seconds=5,
        launch_claim_path=launch_claim,
        authorized_model_ids=("model",),
        placement_wait_poll_seconds=0,
        probe=probe,
        lease=lease,
    )
    adapter.worker = worker
    result = worker.run(
        [_request(index) for index in range(4)],
        test_only_max_placement_wait_cycles=3,
    )
    assert result["status"] == "COMPLETE"
    assert adapter.load_count == 1
    assert adapter.generate_count == 4
    assert lease.acquire_count == 3
    assert lease.release_count == 2
    assert len(probe.calls) == 8


def test_stale_heartbeat_halts_before_request_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    launch_claim = run_dir / "launch.json"
    _write_test_launch_claim(launch_claim, run_dir)
    adapter = _FakeCoreAdapter()
    monkeypatch.setattr(
        "benchmark_core.worker.HeartbeatLoop.require_current",
        lambda _self, _stale: (_ for _ in ()).throw(HeartbeatStaleError("test stale heartbeat")),
    )
    worker = BenchmarkWorker(
        run_dir=run_dir,
        run_id="run",
        git_commit="b" * 40,
        config_sha256="a" * 64,
        prompt_manifest_sha256="d" * 64,
        model=_worker_model(tmp_path, 4),
        adapter=adapter,
        heartbeat_interval_seconds=0.05,
        heartbeat_stale_after_seconds=5,
        launch_claim_path=launch_claim,
        authorized_model_ids=("model",),
        placement_wait_poll_seconds=0,
        probe=_FakeProbe(),
        lease=_FakeLease(),
    )
    adapter.worker = worker
    with pytest.raises(HeartbeatStaleError, match="test stale"):
        worker.run([_request(index) for index in range(4)])
    assert adapter.load_count == 0
    assert adapter.generate_count == 0
    assert worker.claims.usage()["claimed_calls"] == 0


class _FakeB2Adapter:
    model_id = "model"

    def __init__(self) -> None:
        self._load_wall_seconds = None
        self.loaded = False

    def preflight(self):
        return SimpleNamespace(
            status="READY_FOR_MINI_SMOKE",
            model_id="model",
            config_sha256="a" * 64,
            details={},
        )

    def _ensure_loaded(self):
        self.loaded = True
        self._load_wall_seconds = 1.0

    def generate(self, request):
        request.output_path.write_bytes(b"wav")
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=44_100,
            requested_steps=10,
            actual_nfe=10,
            wall_seconds=1.0,
            peak_allocated_bytes=1,
            peak_reserved_bytes=2,
            metadata={},
        )


def test_b2_adapter_bridge_is_executable_and_refuses_state_contracts(tmp_path: Path) -> None:
    bridge = BackboneCoreBridge(_FakeB2Adapter(), expected_sample_rate=44_100, expected_channels=2)
    assert bridge.preflight()["status"] == "READY"
    bridge.load()
    staging = tmp_path / "staging"
    staging.mkdir()
    result = bridge.generate(_request(0), staging, ())
    assert result.actual_nfe == 10
    with pytest.raises(RuntimeError, match="separately authorized state queue"):
        bridge.generate(_request(1), tmp_path / "other", ({"state": True},))


def test_decision_and_external_claim_are_hash_bound_and_placeholder_free(
    tmp_path: Path,
) -> None:
    frozen = tmp_path / "runner.py"
    frozen.write_text("pass\n", encoding="utf-8")
    digest = sha256_file(frozen)
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# Decisions\n\n## D-TEST launch\n"
        "BENCHMARK_CORE_GENERATION_AUTHORIZED = YES\n"
        f"runner.py {digest}\n",
        encoding="utf-8",
    )
    assert (
        verify_decision_authorization(decisions, decision_id="D-TEST", frozen_files=[frozen])[
            str(frozen.resolve())
        ]
        == digest
    )
    decisions.write_text(decisions.read_text() + "PENDING\n", encoding="utf-8")
    with pytest.raises(LaunchAuthorizationError, match="placeholders"):
        verify_decision_authorization(decisions, decision_id="D-TEST", frozen_files=[frozen])

    claim = tmp_path / "claim.json"
    _write_test_launch_claim(claim, tmp_path)
    assert (
        validate_external_launch_claim(
            claim,
            run_id="run",
            config_sha256="a" * 64,
            git_commit="b" * 40,
            run_dir=tmp_path,
            authorized_model_ids=("model",),
        )["status"]
        == "AUTHORIZED_CLEAN_ORIGIN_MAIN"
    )

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scoring.config as scoring_config_module
from scoring.config import load_config
from scoring.published_tables import WATERMARK
from scoring.snapshot import completed_shard_prefix_sha256

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "automatic_scoring_v2_sao_shard_000000.json"
SCORING_RUN_ID = (
    "automatic-scoring-v2-sao-"
    "benchmark-core-v2-sao-20260722t165200z-shards-001"
)


def _raw_config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_first_shard_package_is_prospective_and_exactly_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_config()
    gate = raw["sao_gate"]
    binding = SimpleNamespace(
        access_receipt_sha256=gate["access_receipt_sha256"],
        core_authorization_sha256=gate["core_authorization_sha256"],
    )
    monkeypatch.setattr(
        scoring_config_module,
        "load_core_execution_config",
        lambda *_args, **_kwargs: SimpleNamespace(
            models=[
                SimpleNamespace(
                    model_id="stabilityai/stable-audio-open-1.0",
                    sao_runtime=binding,
                )
            ]
        ),
    )

    config = load_config(CONFIG_PATH, repo_root=ROOT)
    assert config["status"] == "IMPLEMENTED_NOT_LAUNCHED"
    assert config["run_id"] == SCORING_RUN_ID
    assert config["execution"]["authorization"] == {
        "decision_id": "D-0059",
        "exact_cli_ack_required": True,
        "requires_live_config_sha256": True,
        "required_assignments": [
            "SAO_AUTOMATIC_SCORING_AUTHORIZED = YES",
            f"AUTOMATIC_ENDPOINT_SCORING_RUN_ID = {SCORING_RUN_ID}",
            "AUDIO_GENERATION_AUTHORIZED_BY_SCORING = NO",
            "QUEUE_DO_NOT_PREEMPT = YES",
        ],
    }
    assert config["feature_contract"]["human_gold_labels_allowed"] is False
    assert WATERMARK == "AUTOMATIC-INSTRUMENT OUTCOMES"


def test_first_shard_package_reads_only_the_sealed_four_row_prefix() -> None:
    config = _raw_config()
    source = config["sources"][2]
    assert source["backbone"] == "stable-audio-open-1.0"
    assert source["completion_mode"] == "INCREMENTAL_PREFIX"
    assert source["expected_completed_shards"] == 1
    assert source["expected_completed_rows"] == 4
    assert source["expected_queue_rows"] == 1536

    shard = (
        Path(source["run_dir"])
        / "workers"
        / source["worker_slug"]
        / "shards"
        / "shard-000000.json"
    )
    assert completed_shard_prefix_sha256([shard]) == source["expected_hashes"][
        "completed_shard_prefix"
    ]
    record = json.loads(shard.read_text(encoding="utf-8"))
    assert record["shard_index"] == 0
    assert record["status"] == "FIRST_LEDGERED_BATCH"
    assert len(record["rows"]) == 4
    assert record["ledger_tail_sha256"] == source["expected_hashes"]["ledger_tail"]


def test_first_shard_package_queues_on_disjoint_idle_capacity() -> None:
    config = _raw_config()
    guard = config["gpu_guard"]
    assert config["execution"]["queue_policy"] == "QUEUE_DONT_PREEMPT"
    assert guard["policy"] == "QUEUE_DONT_PREEMPT"
    assert guard["generation_lock_roots"] == [
        "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/"
        "benchmark_v2_runtime/locks/core-v2"
    ]
    assert guard["candidates"] == [
        {"node": "an12", "physical_gpu_ids": [4, 5, 6, 7]}
    ]
    assert "EXCLUDE_ANY_LIVE_GENERATION_OR_STATE_ALLOCATION" in guard[
        "generation_allocation_rule"
    ]

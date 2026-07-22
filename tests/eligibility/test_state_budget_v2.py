from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from benchmark_core.ledger import HashChainedLedger
from eligibility.state_budget import (
    StateBudgetError,
    _same_root_base_receipt,
    load_state_budget_config,
    validate_budget_package,
)
from scoring.common import sha256_file, sha256_json

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/eligibility_state_budget_v2.json"
SCHEMA = ROOT / "configs/eligibility_state_input_budget_v2.schema.json"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8")


def _budget_package() -> dict[str, object]:
    rows = []
    for index in range(144):
        checkpoint = (0.25, 0.5, 0.75)[index % 3]
        total_nfe = 50.0
        total_seconds = 18.0
        elapsed_nfe = total_nfe * checkpoint
        elapsed_seconds = total_seconds * elapsed_nfe / total_nfe
        rows.append(
            {
                "checkpoint_fraction": checkpoint,
                "condition": "BASE",
                "core_commit_sha256": hashlib.sha256(f"commit|{index}".encode()).hexdigest(),
                "core_ledger_path": "/immutable/core/ledger.jsonl",
                "core_ledger_row_sha256": hashlib.sha256(
                    f"ledger-row|{index}".encode()
                ).hexdigest(),
                "core_ledger_sha256": "1" * 64,
                "core_provenance_sha256": hashlib.sha256(
                    f"provenance|{index}".encode()
                ).hexdigest(),
                "core_queue_path": "/immutable/core/queues/generation/queue.jsonl",
                "core_queue_sha256": "2" * 64,
                "core_request_sha256": hashlib.sha256(f"core|{index}".encode()).hexdigest(),
                "core_wav_sha256": hashlib.sha256(f"wav|{index}".encode()).hexdigest(),
                "elapsed_nfe": elapsed_nfe,
                "elapsed_seconds": elapsed_seconds,
                "lane_request_sha256": hashlib.sha256(f"lane|{index}".encode()).hexdigest(),
                "mapping": "NFE_PROPORTIONAL_SAME_ROOT_BASE_CORE_TIME_BUDGET",
                "prompt_id": f"prompt-{index // 12:02d}",
                "remaining_nfe": total_nfe - elapsed_nfe,
                "remaining_seconds": total_seconds - elapsed_seconds,
                "root_index": (index // 3) % 4,
                "schema_version": 1,
                "synchronized_wall_seconds": total_seconds,
                "total_nfe": total_nfe,
                "total_seconds": total_seconds,
            }
        )
    body = {
        "axis": "vocal_instrumental",
        "backbone": "stable-audio-3-medium-base",
        "human_gold_used": False,
        "row_count": 144,
        "rows": rows,
        "schema_version": 1,
        "status": "FROZEN_PER_UNIT_TIME_BUDGET_COMPLETE",
        "supplemental_roots_used": False,
        "tier": "INITIAL",
    }
    return {**body, "package_sha256": sha256_json(body)}


def _rehash(package: dict[str, object]) -> None:
    body = dict(package)
    body.pop("package_sha256")
    package["package_sha256"] = sha256_json(body)


def test_config_is_cost_only_closed_and_schema_exact() -> None:
    config = load_state_budget_config(CONFIG, repo_root=ROOT)
    assert config["generation_authorized"] is False
    assert config["evaluator_or_outcome_rows_allowed"] is False
    assert config["operationalization"] == {
        "elapsed_nfe": "EXACT_FROZEN_CHECKPOINT_CUMULATIVE_NFE",
        "elapsed_seconds": "TOTAL_SECONDS_TIMES_ELAPSED_NFE_DIVIDED_BY_TOTAL_NFE",
        "keep_incremental": "REMAINING_NFE_AND_REMAINING_SECONDS",
        "remaining_nfe": "TOTAL_NFE_MINUS_ELAPSED_NFE",
        "remaining_seconds": "TOTAL_SECONDS_MINUS_ELAPSED_SECONDS",
        "restart_incremental": "TOTAL_NFE_AND_TOTAL_SECONDS",
        "total_nfe": "BACKBONE_NATIVE_FROZEN_TRANSFORMER_BUDGET_NFE",
        "total_seconds": "SAME_ROOT_BASE_CORE_SYNCHRONIZED_GENERATION_WALL_SECONDS",
    }
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["$defs"]["row"]["additionalProperties"] is False
    assert set(schema["$defs"]["row"]["required"]) == set(schema["$defs"]["row"]["properties"])


def test_cost_module_has_no_evaluator_or_outcome_reader_import() -> None:
    source = (ROOT / "src/eligibility/state_budget.py").read_text(encoding="utf-8")
    for forbidden in (
        "instruments.",
        "scoring.endpoints",
        "scoring.feature_worker",
        "automatic_result",
        "outcome_success",
    ):
        assert forbidden not in source


def test_budget_package_uses_exact_nfe_proportional_base_equations() -> None:
    assert len(validate_budget_package(_budget_package())) == 144


@pytest.mark.parametrize(
    ("field", "value"),
    (("condition", "FIXED"), ("total_seconds", 23.75), ("elapsed_seconds", 1.0)),
)
def test_budget_package_rejects_base_or_time_equation_drift(field: str, value: object) -> None:
    package = _budget_package()
    package["rows"][0][field] = value  # type: ignore[index]
    _rehash(package)
    with pytest.raises(StateBudgetError, match="equation|BASE"):
        validate_budget_package(package)


def _core_fixture(tmp_path: Path) -> tuple[dict[str, object], Path, dict[str, object]]:
    run = tmp_path / "run"
    relative = Path("sa3-medium-base/integrity/prompt-01/base/root-00.wav")
    wav = run / "artifacts" / relative
    wav.parent.mkdir(parents=True)
    sf.write(wav, np.zeros((4, 2), dtype=np.float32), 44100, subtype="FLOAT")
    request = "a" * 64
    provenance_path = wav.with_suffix(".provenance.json")
    provenance = {
        "actual_nfe": 50,
        "model_id": "stabilityai/stable-audio-3-medium-base",
        "request_sha256": request,
        "root_index": 0,
        "synchronized_wall_seconds": 3.5,
        "upstream": {"adapter_metadata": {"generation_parameters": {"prompt": "frozen prompt"}}},
        "wav_sha256": sha256_file(wav),
    }
    _write_json(provenance_path, provenance)
    commit_path = wav.with_suffix(".commit.json")
    commit = {
        "output_relpath": str(relative),
        "provenance_sha256": sha256_file(provenance_path),
        "request_sha256": request,
        "status": "COMMITTED",
        "wav_sha256": sha256_file(wav),
    }
    _write_json(commit_path, commit)
    queue_path = run / "queues/generation/queue.jsonl"
    queue_path.parent.mkdir(parents=True)
    queue_row = {
        "axis": "integrity",
        "condition": "BASE",
        "model_id": "stabilityai/stable-audio-3-medium-base",
        "output_relpath": str(relative),
        "prompt": "frozen prompt",
        "prompt_id": "prompt-01",
        "request_sha256": request,
        "root_index": 0,
    }
    queue_path.write_text(json.dumps(queue_row, sort_keys=True) + "\n", encoding="utf-8")
    ledger = HashChainedLedger(run / "ledger.jsonl")
    ledger.transition(request, "CLAIMED")
    ledger.transition(request, "CALL_STARTED")
    ledger.transition(
        request,
        "SUCCEEDED",
        {"actual_nfe": 50, "commit": commit, "synchronized_wall_seconds": 3.5},
    )
    unit = {
        "axis": "integrity",
        "parent_core_artifact": {
            "commit_path": str(commit_path),
            "commit_sha256": sha256_file(commit_path),
            "output_relpath": str(relative),
            "provenance_sha256": sha256_file(provenance_path),
            "request_sha256": request,
            "wav_sha256": sha256_file(wav),
        },
        "parent_request_sha256": request,
        "prompt": "frozen prompt",
        "prompt_id": "prompt-01",
        "root_index": 0,
    }
    return unit, queue_path, queue_row


def test_core_cost_receipt_binds_terminal_queue_ledger_prompt_root_and_base(
    tmp_path: Path,
) -> None:
    unit, queue_path, queue_row = _core_fixture(tmp_path)
    receipt = _same_root_base_receipt(
        unit,
        backbone="stable-audio-3-medium-base",
        total_nfe=50,
        cache={},
    )
    assert receipt["synchronized_wall_seconds"] == 3.5
    for field, value in (
        ("condition", "FIXED"),
        ("prompt", "mismatched prompt"),
        ("root_index", 1),
    ):
        changed = deepcopy(queue_row)
        changed[field] = value
        queue_path.write_text(json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(StateBudgetError, match="queue/ledger"):
            _same_root_base_receipt(
                unit,
                backbone="stable-audio-3-medium-base",
                total_nfe=50,
                cache={},
            )

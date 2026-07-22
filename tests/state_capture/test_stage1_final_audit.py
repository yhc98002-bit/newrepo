from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scoring.common import load_json, load_jsonl, sha256_file
from stage1.gates import AXES, BACKBONES
from state_capture.stage1_final_audit import (
    Stage1FinalAuditError,
    audit_stage1_state_artifacts,
)
from tests.stage1.terminal_support import (
    build_terminal,
    queue_binding,
    rewrite_immutable_json,
    write_jsonl,
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _record(path: Path, row_count: int) -> dict[str, Any]:
    return {"path": str(path.resolve()), "row_count": row_count, "sha256": sha256_file(path)}


def _queue_package(tmp_path: Path, backbone: str) -> dict[str, str]:
    slug = "ace" if backbone == "ACE-Step v1" else "sa3"
    queue_root = tmp_path / "source" / slug / "queues" / "initial"
    units: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    sequence = 0
    for axis in AXES:
        for prompt_index in range(12):
            prompt = f"{axis}-prompt-{prompt_index:02d}"
            for root in range(4):
                member_ids: list[str] = []
                for checkpoint in (0.25, 0.5, 0.75):
                    sequence += 1
                    raw = f"{backbone}|{axis}|{prompt}|{root}|{checkpoint}"
                    identity = hashlib.sha256(raw.encode()).hexdigest()
                    member_ids.append(identity)
                    token = f"q-{int(checkpoint * 100):03d}"
                    base = f"state/{axis}/{prompt}/root-{root:02d}/{token}"
                    units.append(
                        {
                            "axis": axis,
                            "checkpoint_relpath": f"{base}/checkpoint.pt",
                            "eligibility_unit": {
                                "checkpoint": checkpoint,
                                "prompt": prompt,
                                "root": root,
                            },
                            "lane_request_sha256": identity,
                            "preview_relpath": f"{base}/preview.wav",
                            "resumed_terminal_relpath": f"{base}/resumed-terminal.wav",
                            "root_index": root,
                            "tier": "INITIAL",
                        }
                    )
                    for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED"):
                        actions.append(
                            {
                                "action": action,
                                "axis": axis,
                                "lane_request_sha256": identity,
                                "root_index": root,
                                "tier": "INITIAL",
                            }
                        )
                group_raw = f"{backbone}|{axis}|{prompt}|{root}|group"
                groups.append(
                    {
                        "axis": axis,
                        "group_request_sha256": hashlib.sha256(group_raw.encode()).hexdigest(),
                        "lane_request_sha256s": member_ids,
                        "reference_terminal_relpath": (
                            f"state/{axis}/{prompt}/root-{root:02d}/reference-terminal.wav"
                        ),
                        "root_index": root,
                        "tier": "INITIAL",
                    }
                )
    units_path = queue_root / "initial-units.jsonl"
    groups_path = queue_root / "prefix-groups.jsonl"
    actions_path = queue_root / "replicated-action-map.jsonl"
    folds_path = queue_root / "prompt-grouped-folds.json"
    lock_path = queue_root / "supplemental-lock.json"
    write_jsonl(units_path, units)
    write_jsonl(groups_path, groups)
    write_jsonl(actions_path, actions)
    _write_json(folds_path, {"rows": [], "schema_version": 1})
    _write_json(
        lock_path,
        {
            "authorized": False,
            "root_indices": [4, 5, 6, 7],
            "schema_version": 1,
            "status": "LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED",
        },
    )
    manifest = {
        "action_map": _record(actions_path, len(actions)),
        "eligibility_unit": ["prompt", "root", "checkpoint"],
        "folds": _record(folds_path, 0),
        "prefix_groups": _record(groups_path, len(groups)),
        "schema_version": 1,
        "status": "PREPARED_NO_MODEL_CALLS",
        "supplemental_lock": _record(lock_path, 1),
        "tier": "INITIAL",
        "units": _record(units_path, len(units)),
    }
    _write_json(queue_root / "state-capture-manifest.json", manifest)
    return queue_binding(units_path, backbone)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    bindings = [_queue_package(tmp_path, backbone) for backbone in BACKBONES]
    result, summary, config = build_terminal(
        tmp_path,
        queue_bindings=bindings,
        stopped_cells={
            ("ACE-Step v1", "tempo"),
            ("ACE-Step v1", "vocal_instrumental"),
            ("stable-audio-3-medium-base", "integrity"),
            ("stable-audio-3-medium-base", "tempo"),
        },
    )
    artifact_root = tmp_path / "state-attempt"
    artifact_root.mkdir()
    return result, summary, config, artifact_root


def _ids(result: Path, backbone_slug: str) -> tuple[str, str]:
    survivor = load_jsonl(result.parent / "survivors" / backbone_slug / "units.jsonl")[0]
    cancelled = next(
        row
        for row in load_jsonl(result.parent / "cancellations" / "units.jsonl")
        if row["backbone"]
        == ("ACE-Step v1" if backbone_slug == "ace-step-v1" else "stable-audio-3-medium-base")
    )
    return survivor["lane_request_sha256"], cancelled["lane_request_sha256"]


def _audit(result: Path, summary: Path, config: Path, artifact_root: Path) -> dict[str, Any]:
    return audit_stage1_state_artifacts(
        result_path=result,
        summary_path=summary,
        config_path=config,
        artifact_roots={"materialized": [artifact_root]},
    )


def test_final_audit_is_read_only_and_accepts_only_exact_survivor_artifacts(
    tmp_path: Path,
) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    survivor, _ = _ids(result, "ace-step-v1")
    artifact = artifact_root / "ledger.jsonl"
    write_jsonl(artifact, [{"lane_request_sha256": survivor, "status": "COMMITTED"}])
    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    report = _audit(result, summary, config, artifact_root)
    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert report["status"] == "PASS_STAGE1_STATE_ENFORCEMENT_AUDIT"
    assert report["read_only"] is True
    assert report["survivor_unit_count"] == 288
    assert report["cancelled_unit_count"] == 576
    assert before == after


def test_mixed_process_log_is_opaque_but_still_scanned_for_cancelled_ids(
    tmp_path: Path,
) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    survivor, cancelled = _ids(result, "ace-step-v1")
    logs = artifact_root / "logs"
    logs.mkdir()
    mixed = logs / "worker.jsonl"
    mixed.write_text(
        '{"event":"WORKER_STARTED"}\n'
        "2026-07-22 23:56:11 | INFO | upstream model loader\n"
        f"completed survivor {survivor}\n",
        encoding="utf-8",
    )
    report = _audit(result, summary, config, artifact_root)
    assert report["artifact_roots"][0]["opaque_log_file_count"] == 1

    contaminated = logs / "cancelled-unit.log"
    contaminated.write_text(
        f"unexpected request identity {cancelled}\n",
        encoding="utf-8",
    )
    with pytest.raises(Stage1FinalAuditError, match="cancelled identity appears in state log"):
        _audit(result, summary, config, artifact_root)


@pytest.mark.parametrize("role", ["materialized", "executed", "scored"])
def test_cancelled_unit_never_enters_any_state_artifact_role(tmp_path: Path, role: str) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    _, cancelled = _ids(result, "ace-step-v1")
    write_jsonl(
        artifact_root / "state-ledger.jsonl",
        [{"lane_request_sha256": cancelled, "status": "COMMITTED"}],
    )
    with pytest.raises(Stage1FinalAuditError, match="cancelled state unit"):
        audit_stage1_state_artifacts(
            result_path=result,
            summary_path=summary,
            config_path=config,
            artifact_roots={role: [artifact_root]},
        )


def test_registered_source_queue_cancellations_are_exempt_but_its_ledger_is_not(
    tmp_path: Path,
) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    source_run = Path(load_json(config)["bindings"]["state_queues"][0]["path"]).parents[2]
    survivor, cancelled = _ids(result, "ace-step-v1")
    write_jsonl(source_run / "state-ledger.jsonl", [{"lane_request_sha256": survivor}])
    report = audit_stage1_state_artifacts(
        result_path=result,
        summary_path=summary,
        config_path=config,
        artifact_roots={"materialized": [source_run], "scored": [artifact_root]},
    )
    assert report["status"] == "PASS_STAGE1_STATE_ENFORCEMENT_AUDIT"
    write_jsonl(source_run / "bad-ledger.jsonl", [{"lane_request_sha256": cancelled}])
    with pytest.raises(Stage1FinalAuditError, match="cancelled state unit"):
        audit_stage1_state_artifacts(
            result_path=result,
            summary_path=summary,
            config_path=config,
            artifact_roots={"materialized": [source_run]},
        )


def test_supplemental_row_or_root_fails_closed(tmp_path: Path) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    _write_json(
        artifact_root / "supplemental-queue.json",
        {
            "eligibility_unit": {"checkpoint": 0.25, "prompt": "new", "root": 4},
            "lane_request_sha256": "a" * 64,
            "supplemental_authorized": True,
            "tier": "SUPPLEMENTAL",
        },
    )
    with pytest.raises(Stage1FinalAuditError, match="supplemental"):
        _audit(result, summary, config, artifact_root)


def test_survivor_manifest_tamper_fails_before_artifact_scan(tmp_path: Path) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    manifest_path = result.parent / "survivors" / "ace-step-v1" / "manifest.json"
    manifest = load_json(manifest_path)
    manifest["unit_count"] = 143
    rewrite_immutable_json(manifest_path, manifest)
    index_path = result.parent / "survivors" / "manifest.json"
    index = load_json(index_path)
    index["backbones"]["ACE-Step v1"]["manifest_sha256"] = sha256_file(manifest_path)
    rewrite_immutable_json(index_path, index)
    with pytest.raises(Stage1FinalAuditError, match="survivor publication is not exact"):
        _audit(result, summary, config, artifact_root)


def test_survivor_units_cannot_be_rebound_to_an_identical_copy(tmp_path: Path) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    manifest_path = result.parent / "survivors" / "ace-step-v1" / "manifest.json"
    manifest = load_json(manifest_path)
    original_units = Path(manifest["units_path"])
    copied_units = tmp_path / "unregistered-copy" / "units.jsonl"
    copied_units.parent.mkdir()
    copied_units.write_bytes(original_units.read_bytes())
    manifest["units_path"] = str(copied_units.resolve())
    manifest["units_sha256"] = sha256_file(copied_units)
    rewrite_immutable_json(manifest_path, manifest)
    index_path = result.parent / "survivors" / "manifest.json"
    index = load_json(index_path)
    index["backbones"]["ACE-Step v1"]["manifest_sha256"] = sha256_file(manifest_path)
    rewrite_immutable_json(index_path, index)
    with pytest.raises(Stage1FinalAuditError, match="survivor publication is not exact"):
        _audit(result, summary, config, artifact_root)


def test_cancelled_prefix_group_never_enters_an_execution_artifact(tmp_path: Path) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    cancelled = {
        row["lane_request_sha256"]
        for row in load_jsonl(result.parent / "cancellations" / "units.jsonl")
        if row["backbone"] == "ACE-Step v1"
    }
    queue_path = Path(load_json(config)["bindings"]["state_queues"][0]["path"])
    cancelled_group = next(
        row["group_request_sha256"]
        for row in load_jsonl(queue_path.parent / "prefix-groups.jsonl")
        if set(row["lane_request_sha256s"]) <= cancelled
    )
    _write_json(
        artifact_root / "group.commit.json",
        {"group_request_sha256": cancelled_group, "status": "COMMITTED"},
    )
    with pytest.raises(Stage1FinalAuditError, match="cancelled state group"):
        _audit(result, summary, config, artifact_root)


def test_only_complete_cancellation_denylist_is_allowed_in_control_plan(
    tmp_path: Path,
) -> None:
    result, summary, config, artifact_root = _fixture(tmp_path)
    cancelled = [
        row["lane_request_sha256"]
        for row in load_jsonl(result.parent / "cancellations" / "units.jsonl")
        if row["backbone"] == "ACE-Step v1"
    ]
    _write_json(
        artifact_root / "stage1-survivor-execution-plan.json",
        {"cancelled_lane_request_sha256s": sorted(cancelled), "survivors_only": True},
    )
    assert _audit(result, summary, config, artifact_root)["status"].startswith("PASS")
    cancelled.pop()
    _write_json(
        artifact_root / "partial-plan.json",
        {"cancelled_lane_request_sha256s": sorted(cancelled)},
    )
    with pytest.raises(Stage1FinalAuditError, match="partial or fabricated"):
        _audit(result, summary, config, artifact_root)

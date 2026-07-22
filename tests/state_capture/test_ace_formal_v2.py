from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import state_capture.ace_formal_engine as formal_engine_module
from benchmark_core.launcher import GitLaunchState
from benchmark_core.ledger import HashChainedLedger, validate_ledger
from scoring.common import load_json, sha256_file
from state_capture.ace_contract import json_sha256
from state_capture.ace_engine import AceEngineError, formal_engine_factory
from state_capture.ace_formal_claims import (
    AceFormalAlreadyClaimed,
    AceFormalClaimStore,
    AceFormalHardCapReached,
    AceFormalPeerFailed,
)
from state_capture.ace_formal_contract import (
    GPU_SECONDS_CAP,
    GROUP_RESERVATION_SECONDS,
    MODEL_ID,
    AceFormalConfig,
    AceFormalContractError,
    D0036Authorization,
    load_formal_config,
    load_source_bundle,
    package_hashes,
    survivor_bundle,
    validate_formal_backend_invocation,
    verify_d0036,
)
from state_capture.ace_formal_engine import ProductionAceFormalGroupEngine
from state_capture.ace_formal_worker import (
    AceFormalWorker,
    AceFormalWorkerStopped,
    DurableCallBoundary,
)
from tests.stage1.terminal_support import build_terminal, queue_binding, write_jsonl

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "ace_state_formal_v2.json"


def _stage1_fixture(
    tmp_path: Path,
    *,
    stopped_ace_axis: str | None = "tempo",
) -> tuple[AceFormalConfig, dict[str, Any], D0036Authorization, Path]:
    config = load_formal_config(CONFIG, repo_root=ROOT)
    bundle = load_source_bundle(config)
    sa3_queue = tmp_path / "queues" / "sa3.jsonl"
    write_jsonl(sa3_queue, [])
    stopped_cells = (
        set() if stopped_ace_axis is None else {("ACE-Step v1", stopped_ace_axis)}
    )
    result_path, summary_path, gate_config_path = build_terminal(
        tmp_path,
        queue_bindings=[
            queue_binding(config.units_path, "ACE-Step v1"),
            queue_binding(sa3_queue, "stable-audio-3-medium-base"),
        ],
        stopped_cells=stopped_cells,
    )
    raw = dict(config.raw)
    raw["stage1"] = {
        **raw["stage1"],
        "expected_result_path": str(result_path),
        "expected_summary_path": str(summary_path),
        "gate_config_path": str(gate_config_path),
    }
    fixture_config = replace(config, raw=raw)
    decisions = tmp_path / "DECISIONS.md"
    assignments = {
        "ACE_STATE_FORMAL_INITIAL_AUTHORIZED": "YES",
        "ACE_STATE_FORMAL_SURVIVORS_ONLY": "YES",
        "ACE_STATE_FORMAL_STOP_UNITS_PROHIBITED": "EXECUTE,SCORE",
        "ACE_STATE_FORMAL_CONFIG": "configs/ace_state_formal_v2.json",
        "ACE_STATE_FORMAL_CONFIG_SHA256": fixture_config.sha256,
        "STAGE1_RESULT_PATH": str(result_path.resolve()),
        "STAGE1_CANCELLATION_SUMMARY_PATH": str(summary_path.resolve()),
        "STAGE1_RUNTIME_SHA256_BINDING": "VERIFIED_AND_RECORDED_AT_LAUNCH",
        "ACE_STATE_SUPPLEMENTAL_AUTHORIZED": "NO",
        "NO_AUTOMATIC_RETRY": "YES",
        "ACE_STATE_FORMAL_PLACEMENT": "an12:[4,5,6,7]",
        "ACE_STATE_FORMAL_MAX_PARALLEL_REPLICAS": "4",
        "ACE_STATE_FORMAL_INITIAL_GPU_SECONDS_CAP": json.dumps(GPU_SECONDS_CAP),
        "ACE_STATE_FORMAL_FRESH_QUEUE_MANIFEST_SHA256": (
            "62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a"
        ),
        "ACE_STATE_FORMAL_INITIAL_UNITS_SHA256": (
            "9218cd0ce81bda171230a4bed40c75c67ade08cd359a4da4b569a8365155923f"
        ),
    }
    decisions.write_text(
        "## D-0036 — ACE formal initial opening\n\n"
        + "\n".join(f"`{key} = {value}`" for key, value in assignments.items())
        + "\n",
        encoding="utf-8",
    )
    authorization = verify_d0036(
        fixture_config,
        decisions_path=decisions,
        bundle=bundle,
    )
    return fixture_config, bundle, authorization, decisions


def test_committed_formal_config_is_inert_and_binds_exact_d0033_queue() -> None:
    config = load_formal_config(CONFIG, repo_root=ROOT)
    bundle = load_source_bundle(config)

    assert config.raw["execution_status"] == "CLOSED_PENDING_STAGE1_RESULT_AND_D0036"
    assert config.raw["supplemental_queue_status"] == "LOCKED_NOT_AUTHORIZED"
    assert config.raw["placement"]["allowed_nodes"] == ["an12"]
    assert config.raw["placement"]["allowed_physical_gpu_ids"] == [4, 5, 6, 7]
    assert config.raw["placement"]["tensor_parallel_width"] == 1
    assert config.raw["budget"]["maximum_model_calls"] == 576
    assert config.raw["budget"]["no_automatic_retry"] is True
    assert config.raw["source_queue"]["manifest"]["sha256"] == (
        "62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a"
    )
    assert config.raw["source_queue"]["units"]["sha256"] == (
        "9218cd0ce81bda171230a4bed40c75c67ade08cd359a4da4b569a8365155923f"
    )
    assert (len(bundle["groups"]), len(bundle["units"]), len(bundle["actions"])) == (
        144,
        432,
        1296,
    )
    hashes = package_hashes(config)
    assert "src/state_capture/ace_formal_engine.py" in hashes
    assert "src/state_capture/ace_formal_launcher.py" in hashes
    assert set(hashes.values()) <= {sha256_file(ROOT / path) for path in hashes}


def test_d0036_binds_stage1_hashes_at_launch_and_filters_exact_survivors(
    tmp_path: Path,
) -> None:
    config, bundle, authorization, decisions = _stage1_fixture(tmp_path)

    assert authorization.stage1.survivor_axes == ("vocal_instrumental", "integrity")
    assert authorization.stage1.stopped_axes == ("tempo",)
    filtered = survivor_bundle(bundle, authorization.stage1)
    assert len(filtered["groups"]) == 96
    assert len(filtered["units"]) == 288
    assert len(filtered["actions"]) == 864
    assert {row["axis"] for rows in filtered.values() for row in rows} == {
        "vocal_instrumental",
        "integrity",
    }

    assert authorization.stage1.result_sha256 == sha256_file(authorization.stage1.result_path)
    assert authorization.stage1.summary_sha256 == sha256_file(authorization.stage1.summary_path)
    assert "STAGE1_RESULT_SHA256" not in decisions.read_text(encoding="utf-8")

    decisions.write_text(
        decisions.read_text(encoding="utf-8").replace(
            "STAGE1_RUNTIME_SHA256_BINDING = VERIFIED_AND_RECORDED_AT_LAUNCH",
            "STAGE1_RUNTIME_SHA256_BINDING = PRECOMPUTED",
        ),
        encoding="utf-8",
    )
    with pytest.raises(AceFormalContractError, match="exact formal assignments"):
        verify_d0036(config, decisions_path=decisions, bundle=bundle)


def test_missing_or_tampered_stop_cancellation_is_rejected(tmp_path: Path) -> None:
    config, bundle, _authorization, decisions = _stage1_fixture(tmp_path)
    event = sorted((tmp_path / "stage1" / "cancellations" / "events").glob("[0-9]*-*.json"))[0]
    value = load_json(event)
    value["payload"]["prohibited_operations"] = ["SCORE"]
    event.chmod(0o644)
    event.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(AceFormalContractError, match="immutable no-clobber"):
        verify_d0036(config, decisions_path=decisions, bundle=bundle)


def test_group_and_per_call_claims_are_survivor_only_no_retry_and_cap_bound(
    tmp_path: Path,
) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path)
    group = next(row for row in bundle["groups"] if row["axis"] == "vocal_instrumental")
    units = {
        row["lane_request_sha256"]: row
        for row in bundle["units"]
        if row["axis"] == "vocal_instrumental"
    }
    claims = AceFormalClaimStore(tmp_path / "claims", config=config)
    group_claim = claims.reserve_group(
        group,
        authorization=authorization,
        git_commit="a" * 40,
        replica_index=0,
        physical_gpu_id=4,
    )
    assert group_claim["retry_allowed"] is False
    prefix = claims.claim_call(
        group,
        kind="PREFIX_GROUP",
        group_claim=group_claim,
        survivor_axes=authorization.stage1.survivor_axes,
        replica_index=0,
        physical_gpu_id=4,
    )
    resumes = [
        claims.claim_call(
            units[identity],
            kind="RESUME_UNIT",
            group_claim=group_claim,
            survivor_axes=authorization.stage1.survivor_axes,
            replica_index=0,
            physical_gpu_id=4,
        )
        for identity in group["lane_request_sha256s"]
    ]
    assert prefix["retry_allowed"] is False
    assert len(resumes) == 3
    assert all(row["retry_allowed"] is False for row in resumes)
    with pytest.raises(AceFormalAlreadyClaimed):
        claims.claim_call(
            group,
            kind="PREFIX_GROUP",
            group_claim=group_claim,
            survivor_axes=authorization.stage1.survivor_axes,
            replica_index=0,
            physical_gpu_id=4,
        )
    foreign_group = next(
        row
        for row in bundle["groups"]
        if row["axis"] == group["axis"]
        and row["group_request_sha256"] != group["group_request_sha256"]
    )
    foreign_unit = units[foreign_group["lane_request_sha256s"][0]]
    with pytest.raises(ValueError, match="not a member of its parent group"):
        claims.claim_call(
            foreign_unit,
            kind="RESUME_UNIT",
            group_claim=group_claim,
            survivor_axes=authorization.stage1.survivor_axes,
            replica_index=0,
            physical_gpu_id=4,
        )
    with pytest.raises(AceFormalHardCapReached, match="exceeded its frozen"):
        claims.record_observed(group["group_request_sha256"], GROUP_RESERVATION_SECONDS + 0.001)
    assert claims.usage()["effective_gpu_seconds"] == GROUP_RESERVATION_SECONDS

    stopped = next(row for row in bundle["groups"] if row["axis"] == "tempo")
    with pytest.raises(ValueError, match="Stage-1 survivor"):
        claims.reserve_group(
            stopped,
            authorization=authorization,
            git_commit="a" * 40,
            replica_index=0,
            physical_gpu_id=4,
        )
    assert len(list((tmp_path / "claims" / "group-claims").glob("*.json"))) == 1


class _SafeProbe:
    def require_safe(self, **_kwargs: Any) -> None:
        return None


class _Lease:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> _Lease:
        if self.held:
            raise RuntimeError("test lease already held")
        self.held = True
        return self

    def release(self) -> None:
        self.held = False

    def __enter__(self) -> _Lease:
        return self if self.held else self.acquire()

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.release()


class _SuccessfulEngine:
    model_id = MODEL_ID

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.preflight_calls = 0
        self.load_calls = 0
        self.run_calls = 0
        self.closed = False

    def preflight(self) -> dict[str, Any]:
        self.preflight_calls += 1
        return {"status": "READY"}

    def load(self) -> dict[str, Any]:
        self.load_calls += 1
        return {"status": "READY"}

    def run_group(
        self,
        group: dict[str, Any],
        units: list[dict[str, Any]],
        _claim: dict[str, Any],
        boundary: Any,
    ) -> dict[str, Any]:
        self.run_calls += 1
        boundary.start("PREFIX_GROUP", group)
        boundary.succeed("PREFIX_GROUP", group, {"gpu_seconds": 0.4})
        for unit in units:
            boundary.start("RESUME_UNIT", unit)
            boundary.succeed("RESUME_UNIT", unit, {"gpu_seconds": 0.2})
        commit = self.run_dir / "fixture-artifacts" / f"{group['group_request_sha256']}.json"
        with boundary.publish_guard():
            commit.parent.mkdir(parents=True, exist_ok=True)
            commit.write_text("{}\n", encoding="utf-8")
        return {
            "artifact_commit_path": str(commit),
            "artifact_commit_sha256": sha256_file(commit),
            "completed_units": 3,
            "gpu_seconds": 1.0,
            "group_request_sha256": group["group_request_sha256"],
            "model_calls": 4,
            "peak_allocated_bytes": 10,
            "peak_reserved_bytes": 20,
            "same_root_previews": True,
            "status": "PASS",
        }

    def close(self) -> None:
        self.closed = True


class _FailingEngine(_SuccessfulEngine):
    def run_group(
        self,
        group: dict[str, Any],
        _units: list[dict[str, Any]],
        _claim: dict[str, Any],
        boundary: Any,
    ) -> dict[str, Any]:
        self.run_calls += 1
        boundary.start("PREFIX_GROUP", group)
        raise RuntimeError("new formal failure class")


def _worker(
    *,
    config: AceFormalConfig,
    authorization: D0036Authorization,
    run_dir: Path,
    engine: Any,
) -> AceFormalWorker:
    return AceFormalWorker(
        config=config,
        authorization=authorization,
        run_dir=run_dir,
        git_commit="a" * 40,
        queue_manifest_sha256=config.raw["source_queue"]["manifest"]["sha256"],
        replica_index=0,
        physical_gpu_id=4,
        engine=engine,
        probe=_SafeProbe(),
        lease=_Lease(),
        placement_poll_seconds=0,
    )


def test_worker_ledgers_four_distinct_calls_before_success_and_never_scores_stop(
    tmp_path: Path,
) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path / "gate")
    filtered = survivor_bundle(bundle, authorization.stage1)
    group = next(
        row
        for row in filtered["groups"]
        if row["axis"] == "vocal_instrumental" and row["group_sequence"] == 1
    )
    unit_ids = set(group["lane_request_sha256s"])
    units = [row for row in filtered["units"] if row["lane_request_sha256"] in unit_ids]
    run_dir = tmp_path / "run"
    engine = _SuccessfulEngine(run_dir)
    worker = _worker(
        config=config,
        authorization=authorization,
        run_dir=run_dir,
        engine=engine,
    )

    result = worker.run(groups=[group], units=units, max_new_groups=1)

    assert result["status"] == "BOUNDED_BATCH_COMPLETE"
    assert engine.run_calls == 1
    assert engine.closed is True
    ledger = validate_ledger(run_dir / "formal-state-ledger.jsonl")
    request_rows = [row for row in ledger if row["event_kind"] == "REQUEST_STATE"]
    assert len(request_rows) == 12
    call_ids = {group["group_request_sha256"], *group["lane_request_sha256s"]}
    assert {row["request_sha256"] for row in request_rows} == call_ids
    assert [
        row["request_state"]
        for row in request_rows
        if row["request_sha256"] == group["group_request_sha256"]
    ] == ["CLAIMED", "CALL_STARTED", "SUCCEEDED"]
    assert {row["request_state"] for row in request_rows} == {
        "CLAIMED",
        "CALL_STARTED",
        "SUCCEEDED",
    }
    assert sum(row.get("event_kind") == "FORMAL_GROUP_COMMITTED" for row in ledger) == 1
    claim_root = run_dir / "control" / "shared-formal-claims"
    assert len(list((claim_root / "prefix-call-claims").glob("*.json"))) == 1
    assert len(list((claim_root / "resume-call-claims").glob("*.json"))) == 3
    stopped_ids = {row["lane_request_sha256"] for row in bundle["units"] if row["axis"] == "tempo"}
    assert {row["request_sha256"] for row in request_rows}.isdisjoint(stopped_ids)


def test_new_failure_is_failed_stopped_and_cannot_retry(tmp_path: Path) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path / "gate")
    filtered = survivor_bundle(bundle, authorization.stage1)
    group = next(row for row in filtered["groups"] if row["group_sequence"] == 1)
    unit_ids = set(group["lane_request_sha256s"])
    units = [row for row in filtered["units"] if row["lane_request_sha256"] in unit_ids]
    run_dir = tmp_path / "run"
    engine = _FailingEngine(run_dir)
    worker = _worker(
        config=config,
        authorization=authorization,
        run_dir=run_dir,
        engine=engine,
    )

    with pytest.raises(AceFormalWorkerStopped, match="permanently stopped"):
        worker.run(groups=[group], units=units, max_new_groups=1)
    terminal = load_json(run_dir / "control" / "formal-terminal-failure.json")
    assert terminal["status"] == "FAILED_STOPPED"
    assert terminal["retry_allowed"] is False
    rows = validate_ledger(run_dir / "formal-state-ledger.jsonl")
    states = [
        row["request_state"]
        for row in rows
        if row.get("request_sha256") == group["group_request_sha256"]
    ]
    assert states == ["CLAIMED", "CALL_STARTED", "FAILED"]
    claims_before = list(
        (run_dir / "control" / "shared-formal-claims" / "group-claims").glob("*.json")
    )
    with pytest.raises(AceFormalWorkerStopped, match="terminal FAILED_STOPPED"):
        worker.run(groups=[group], units=units, max_new_groups=1)
    assert (
        list((run_dir / "control" / "shared-formal-claims" / "group-claims").glob("*.json"))
        == claims_before
    )
    assert engine.run_calls == 1


def test_stop_group_is_rejected_before_preflight_or_claim(tmp_path: Path) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path / "gate")
    stopped = next(row for row in bundle["groups"] if row["axis"] == "tempo")
    unit_ids = set(stopped["lane_request_sha256s"])
    units = [row for row in bundle["units"] if row["lane_request_sha256"] in unit_ids]
    run_dir = tmp_path / "run"
    engine = _SuccessfulEngine(run_dir)
    worker = _worker(
        config=config,
        authorization=authorization,
        run_dir=run_dir,
        engine=engine,
    )

    with pytest.raises(ValueError, match="STOP-axis group"):
        worker.run(groups=[stopped], units=units, max_new_groups=1)
    assert engine.preflight_calls == 0
    assert engine.run_calls == 0
    assert not list((run_dir / "control" / "shared-formal-claims" / "group-claims").glob("*.json"))
    assert validate_ledger(run_dir / "formal-state-ledger.jsonl") == []


def test_peer_failure_blocks_call_start_backend_and_both_commit_surfaces(
    tmp_path: Path,
) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path / "gate")
    group = next(row for row in bundle["groups"] if row["group_sequence"] == 1)
    claims = AceFormalClaimStore(
        tmp_path / "run" / "control" / "shared-formal-claims", config=config
    )
    group_claim = claims.reserve_group(
        group,
        authorization=authorization,
        git_commit="a" * 40,
        replica_index=0,
        physical_gpu_id=4,
    )
    ledger = HashChainedLedger(tmp_path / "run" / "ledger.jsonl")
    boundary = DurableCallBoundary(
        claims=claims,
        ledger=ledger,
        group_claim=group_claim,
        survivor_axes=authorization.stage1.survivor_axes,
        replica_index=0,
        physical_gpu_id=4,
    )
    claims.latch_failure(
        identity=group["group_request_sha256"],
        replica_index=1,
        exc=RuntimeError("peer failure"),
    )

    with pytest.raises(AceFormalPeerFailed, match="terminal FAILED_STOPPED"):
        boundary.start("PREFIX_GROUP", group)
    assert validate_ledger(ledger.path) == []
    assert not list(claims.prefix_call_dir.glob("*.json"))
    with (
        pytest.raises(AceFormalPeerFailed, match="terminal FAILED_STOPPED"),
        boundary.publish_guard(),
    ):
        raise AssertionError("publish body must never run")
    committed = False

    def commit_callback() -> None:
        nonlocal committed
        committed = True

    with pytest.raises(AceFormalPeerFailed, match="terminal FAILED_STOPPED"):
        claims.commit_group(group["group_request_sha256"], 1.0, commit_callback)
    assert committed is False
    assert not list(claims.observation_dir.glob("*.json"))


def test_backend_requires_exact_per_call_claim_and_rechecks_peer_latch(
    tmp_path: Path,
) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path / "gate")
    group = next(row for row in bundle["groups"] if row["group_sequence"] == 1)
    claims = AceFormalClaimStore(
        tmp_path / "run" / "control" / "shared-formal-claims", config=config
    )
    group_claim = claims.reserve_group(
        group,
        authorization=authorization,
        git_commit="a" * 40,
        replica_index=0,
        physical_gpu_id=4,
    )
    call_claim = claims.claim_call(
        group,
        kind="PREFIX_GROUP",
        group_claim=group_claim,
        survivor_axes=authorization.stage1.survivor_axes,
        replica_index=0,
        physical_gpu_id=4,
    )
    context = formal_engine_module._engine_context(
        config,
        run_dir=tmp_path / "run",
        claim=group_claim,
        call_claim=call_claim,
    )
    observed_group, observed_call = validate_formal_backend_invocation(context)
    assert observed_group["group_request_sha256"] == group["group_request_sha256"]
    assert observed_call["call_kind"] == "PREFIX_GROUP"

    changed = {**context, "formal_call_claim_sha256": "0" * 64}
    with pytest.raises(AceFormalContractError, match="group/call binding drifted"):
        validate_formal_backend_invocation(changed)

    claims.latch_failure(
        identity=group["group_request_sha256"],
        replica_index=1,
        exc=RuntimeError("peer failure after call claim"),
    )
    with pytest.raises(AceFormalContractError, match="peer FAILED_STOPPED"):
        validate_formal_backend_invocation(context)


class _LowLevelParent:
    def __init__(self) -> None:
        self.closed = False

    def run_reference(
        self,
        *,
        request: dict[str, Any],
        output_path: Path,
        state_dir: Path,
    ) -> dict[str, Any]:
        assert request["prompt"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fixture-reference")
        checkpoints = []
        for fraction, transitions, nfe in zip(
            (0.25, 0.5, 0.75), (9, 15, 20), (11, 23, 33), strict=True
        ):
            checkpoint = state_dir / f"checkpoint-{int(fraction * 100):03d}.pt"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_bytes(f"checkpoint-{fraction}".encode())
            metadata = {
                "artifact_path": str(checkpoint.resolve()),
                "artifact_sha256": sha256_file(checkpoint),
                "artifact_size_bytes": checkpoint.stat().st_size,
                "schema_version": 1,
            }
            metadata["state_identity_sha256"] = json_sha256(metadata)
            sidecar = checkpoint.with_name(f"{checkpoint.name}.state.json")
            sidecar.write_text(
                json.dumps(metadata, allow_nan=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            checkpoints.append(
                {
                    "checkpoint_fraction": fraction,
                    "completed_scheduler_transitions": transitions,
                    "cumulative_transformer_nfe": nfe,
                    "path": str(checkpoint.resolve()),
                    "sha256": sha256_file(checkpoint),
                    "state_metadata_sha256": sha256_file(sidecar),
                }
            )
        return {
            "actual_nfe": 45,
            "checkpoint_source_path": None,
            "checkpoint_source_sha256": None,
            "checkpoints": checkpoints,
            "format": "ace-step-v1-state-engine-result-v2",
            "gpu_seconds": 1.0,
            "mode": "REFERENCE",
            "model_id": MODEL_ID,
            "output_path": str(output_path.resolve()),
            "output_sha256": sha256_file(output_path),
            "peak_allocated_bytes": 10,
            "peak_reserved_bytes": 20,
            "pid": os.getpid(),
            "status": "PASS",
        }

    def decode_preview(
        self,
        *,
        checkpoint_path: Path,
        checkpoint_sha256: str,
        output_path: Path,
    ) -> dict[str, Any]:
        assert sha256_file(checkpoint_path) == checkpoint_sha256
        output_path.write_bytes(b"fixture-preview")
        return {
            "gpu_seconds": 0.1,
            "output_path": str(output_path.resolve()),
            "output_sha256": sha256_file(output_path),
            "peak_allocated_bytes": 11,
            "peak_reserved_bytes": 21,
            "root_local_only": True,
        }

    def close(self) -> None:
        self.closed = True


class _BoundaryRecorder:
    def __init__(
        self,
        *,
        claims: AceFormalClaimStore,
        group_claim: dict[str, Any],
        authorization: D0036Authorization,
    ) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.active: tuple[str, str] | None = None
        self.claims = claims
        self.group_claim = group_claim
        self.authorization = authorization

    def start(self, kind: str, row: dict[str, Any]) -> dict[str, Any]:
        field = "group_request_sha256" if kind == "PREFIX_GROUP" else "lane_request_sha256"
        self.active = (kind, row[field])
        self.events.append(("START", kind, row[field]))
        return self.claims.claim_call(
            row,
            kind=kind,
            group_claim=self.group_claim,
            survivor_axes=self.authorization.stage1.survivor_axes,
            replica_index=0,
            physical_gpu_id=4,
        )

    def succeed(self, kind: str, row: dict[str, Any], _payload: dict[str, Any]) -> None:
        field = "group_request_sha256" if kind == "PREFIX_GROUP" else "lane_request_sha256"
        assert self.active == (kind, row[field])
        self.events.append(("SUCCEED", kind, row[field]))
        self.active = None

    def publish_guard(self) -> Any:
        return self.claims.publish_guard()


def test_group_engine_binds_exact_resume_nfe_child_identity_and_preview_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, bundle, authorization, _decisions = _stage1_fixture(tmp_path / "gate")
    group = next(row for row in bundle["groups"] if row["group_sequence"] == 1)
    unit_index = {row["lane_request_sha256"]: row for row in bundle["units"]}
    units = [unit_index[identity] for identity in group["lane_request_sha256s"]]
    run_dir = tmp_path / "run"
    claims = AceFormalClaimStore(run_dir / "control" / "shared-formal-claims", config=config)
    claim = claims.reserve_group(
        group,
        authorization=authorization,
        git_commit="a" * 40,
        replica_index=0,
        physical_gpu_id=4,
    )
    parent = _LowLevelParent()
    monkeypatch.setattr(
        formal_engine_module,
        "inspect_production_capability",
        lambda _contract: {"failures": [], "status": "READY"},
    )
    monkeypatch.setattr(
        formal_engine_module,
        "resolve_engine_factory",
        lambda _name: lambda context: validate_formal_backend_invocation(context) and parent,
    )
    monkeypatch.setattr(
        formal_engine_module,
        "basic_audio_sanity",
        lambda path, **_kwargs: {"path": str(Path(path)), "status": "PASS"},
    )
    monkeypatch.setattr(
        formal_engine_module,
        "compare_audio_equivalence",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )
    remaining = {
        unit["lane_request_sha256"]: 45 - unit["checkpoint_cumulative_transformer_nfe"]
        for unit in units
    }

    def launch_child(_self: Any, request_path: Path, _timeout_seconds: float) -> None:
        request = load_json(request_path)
        validate_formal_backend_invocation(request["engine_context"])
        output = Path(request["output_path"])
        output.write_bytes(b"fixture-resume")
        child_pid = os.getpid() + 100_000
        engine_result = {
            "actual_nfe": remaining[request["request_id"]],
            "checkpoint_source_path": request["checkpoint_path"],
            "checkpoint_source_sha256": request["checkpoint_sha256"],
            "format": "ace-step-v1-state-engine-result-v2",
            "gpu_seconds": 0.2,
            "mode": "RESUME",
            "model_id": MODEL_ID,
            "output_path": str(output.resolve()),
            "output_sha256": sha256_file(output),
            "peak_allocated_bytes": 12,
            "peak_reserved_bytes": 22,
            "pid": child_pid,
            "status": "PASS",
        }
        child = {
            "checkpoint_path": request["checkpoint_path"],
            "checkpoint_sha256": request["checkpoint_sha256"],
            "child_pid": child_pid,
            "engine_result": engine_result,
            "format": "ace-step-v1-resume-child-result-v2",
            "os_parent_pid": os.getpid(),
            "parent_pid": os.getpid(),
            "request_identity_sha256": request["request_identity_sha256"],
            "request_path": str(request_path.resolve()),
            "request_sha256": sha256_file(request_path),
            "status": "PASS",
        }
        child["result_identity_sha256"] = json_sha256(child)
        Path(request["result_path"]).write_text(
            json.dumps(child, allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(ProductionAceFormalGroupEngine, "_launch_child", launch_child)
    engine = ProductionAceFormalGroupEngine(config, run_dir=run_dir)
    assert engine.preflight()["status"] == "READY"
    boundary = _BoundaryRecorder(
        claims=claims,
        group_claim=claim,
        authorization=authorization,
    )

    result = engine.run_group(group, units, claim, boundary)

    assert result["status"] == "PASS"
    assert result["model_calls"] == 4
    assert result["same_root_previews"] is True
    assert parent.closed is True
    assert [event[:2] for event in boundary.events] == [
        ("START", "PREFIX_GROUP"),
        ("SUCCEED", "PREFIX_GROUP"),
        ("START", "RESUME_UNIT"),
        ("SUCCEED", "RESUME_UNIT"),
        ("START", "RESUME_UNIT"),
        ("SUCCEED", "RESUME_UNIT"),
        ("START", "RESUME_UNIT"),
        ("SUCCEED", "RESUME_UNIT"),
    ]
    commit = load_json(Path(result["artifact_commit_path"]))
    assert [
        load_json(Path(row["path"]))["resume_actual_nfe"] for row in commit["unit_commits"]
    ] == [34, 22, 12]
    assert all(
        load_json(Path(row["path"]))["preview_sanity"]["status"] == "PASS"
        for row in commit["unit_commits"]
    )


def test_formal_factory_refuses_nonformal_context() -> None:
    with pytest.raises(AceEngineError, match="lacks formal execution scope"):
        formal_engine_factory({})


def test_preparation_git_identity_type_is_frozen() -> None:
    state = GitLaunchState(head="a" * 40, origin_main="a" * 40)
    assert state.head == state.origin_main

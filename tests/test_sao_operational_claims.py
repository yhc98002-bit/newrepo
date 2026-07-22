from __future__ import annotations

import hashlib
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import backbones.sao_operational_claims as claims_module
import benchmark_core.launcher as launcher_module
from backbones.sao_operational_claims import (
    SAO_MODEL_ID,
    SaoOperationalAuthorizationError,
    consume_sao_core_run_claim,
    consume_sao_mini_smoke_attempt,
    sao_core_global_claim_path,
    validate_sao_core_run_claim,
    validate_sao_mini_smoke_attempt_claim,
    verify_exact_sao_core_decision,
)
from benchmark_core.launcher import GitLaunchState, LaunchAuthorizationError, prepare_run


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mini_authorization(path: Path) -> None:
    _write_json(
        path,
        {
            "access_receipt_sha256": "b" * 64,
            "backbone_config_sha256": "a" * 64,
            "decision_id": "D-0037",
            "max_clip_seconds": 30,
            "max_generations": 3,
            "max_gpus": 1,
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
        },
    )


def _patch_smoke_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "runs" / "sao-mini-smoke-v2-001"
    claim = tmp_path / "claims" / "sao-mini-smoke-v2-001.attempt.claim.json"
    monkeypatch.setattr(claims_module, "SAO_MINI_SMOKE_RUN_DIR", run_dir)
    monkeypatch.setattr(claims_module, "SAO_MINI_SMOKE_ATTEMPT_CLAIM", claim)
    return run_dir, claim


def test_mini_smoke_authority_is_one_global_fixed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, claim_path = _patch_smoke_paths(monkeypatch, tmp_path)
    authorization = tmp_path / "authorization.json"
    copied_authorization = tmp_path / "copied-authorization.json"
    live_config = tmp_path / "sao-live.json"
    _mini_authorization(authorization)
    copied_authorization.write_bytes(authorization.read_bytes())
    _write_json(live_config, {"fixture": True})

    with pytest.raises(SaoOperationalAuthorizationError, match="fixed authorized run path"):
        consume_sao_mini_smoke_attempt(
            authorization,
            requested_run_dir=tmp_path / "alternate-run",
            live_config_path=live_config,
            git_commit="c" * 40,
        )
    assert not claim_path.exists()

    claimed = consume_sao_mini_smoke_attempt(
        authorization,
        requested_run_dir=run_dir,
        live_config_path=live_config,
        git_commit="c" * 40,
    )
    assert claimed["run_id"] == "sao-mini-smoke-v2-001"
    assert claimed["run_dir"] == str(run_dir.resolve())
    assert claimed["authorized_calls"] == 3
    assert claimed["retry_allowed"] is False
    assert claimed["path"] == str(claim_path.resolve())
    assert validate_sao_mini_smoke_attempt_claim(claim_path)["sha256"] == _sha(claim_path)

    with pytest.raises(SaoOperationalAuthorizationError, match="already consumed"):
        consume_sao_mini_smoke_attempt(
            copied_authorization,
            requested_run_dir=run_dir,
            live_config_path=live_config,
            git_commit="c" * 40,
        )


def test_mini_smoke_rejects_authorization_cap_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, claim_path = _patch_smoke_paths(monkeypatch, tmp_path)
    authorization = tmp_path / "authorization.json"
    live_config = tmp_path / "sao-live.json"
    _mini_authorization(authorization)
    value = json.loads(authorization.read_text(encoding="utf-8"))
    value["max_generations"] = 4
    _write_json(authorization, value)
    _write_json(live_config, {"fixture": True})
    with pytest.raises(SaoOperationalAuthorizationError, match="max_generations"):
        consume_sao_mini_smoke_attempt(
            authorization,
            requested_run_dir=run_dir,
            live_config_path=live_config,
            git_commit="c" * 40,
        )
    assert not claim_path.exists()


def test_mini_smoke_attempt_claim_is_atomic_under_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, claim_path = _patch_smoke_paths(monkeypatch, tmp_path)
    authorization = tmp_path / "authorization.json"
    live_config = tmp_path / "sao-live.json"
    _mini_authorization(authorization)
    _write_json(live_config, {"fixture": True})

    def attempt() -> str:
        try:
            consume_sao_mini_smoke_attempt(
                authorization,
                requested_run_dir=run_dir,
                live_config_path=live_config,
                git_commit="c" * 40,
            )
        except SaoOperationalAuthorizationError:
            return "REPLAY_REFUSED"
        return "CLAIMED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: attempt(), range(2)))
    assert sorted(results) == ["CLAIMED", "REPLAY_REFUSED"]
    assert claim_path.is_file()


def test_mini_smoke_runner_claims_only_after_offline_preflight_and_safe_device_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = importlib.import_module("scripts.run_sao_mini_smoke_v2")
    assert runner.LOCK_ROOT.name == "core-v2"
    assert runner.LOCK_ROOT.parent.name == "locks"

    events: list[str] = []
    monkeypatch.setattr(runner, "validate_live_config", lambda *_args: None)
    monkeypatch.setattr(runner, "_verify_seeds", lambda: None)
    monkeypatch.setattr(runner, "_git_state", lambda: "c" * 40)
    monkeypatch.setattr(runner.socket, "gethostname", lambda: "an12")
    class FakeAdapter:
        def __init__(self, **_kwargs: object) -> None:
            events.append("adapter-created")

        def preflight(self) -> SimpleNamespace:
            events.append("offline-preflight")
            return SimpleNamespace(status="READY_FOR_MINI_SMOKE")

    class FakeLease:
        def __init__(self, _placement: object) -> None:
            events.append("lease-created")

        def __enter__(self) -> FakeLease:
            events.append("lease-entered")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("lease-exited")

    class FakeProbe:
        def __init__(self, _placement: object) -> None:
            pass

        def require_safe(self, **_kwargs: object) -> SimpleNamespace:
            events.append("gpu-safety-verified")
            return SimpleNamespace()

    def stop_at_claim(*_args: object, **_kwargs: object) -> dict[str, str]:
        events.append("attempt-claimed")
        raise RuntimeError("test stop at attempt claim")

    monkeypatch.setattr(runner, "StableAudioOpenAdapter", FakeAdapter)
    monkeypatch.setattr(runner, "DeviceLease", FakeLease)
    monkeypatch.setattr(runner, "NvidiaSmiProbe", FakeProbe)
    monkeypatch.setattr(runner, "consume_sao_mini_smoke_attempt", stop_at_claim)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_sao_mini_smoke_v2.py",
            "--snapshot-dir",
            str(tmp_path / "snapshot"),
            "--access-receipt",
            str(tmp_path / "receipt.json"),
            "--runtime-authorization",
            str(tmp_path / "authorization.json"),
            "--physical-gpu-id",
            "4",
        ],
    )
    with pytest.raises(RuntimeError, match="test stop at attempt claim"):
        runner.main()
    assert events == [
        "adapter-created",
        "offline-preflight",
        "lease-created",
        "lease-entered",
        "gpu-safety-verified",
        "attempt-claimed",
        "lease-exited",
    ]


def _decision(path: Path, *, run_id: str, duplicate_run: bool = False) -> str:
    lines = [
        "# Decisions",
        "",
        "## D-SAO — fixture SAO core authorization",
        "`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`",
        f"`BENCHMARK_CORE_AUTHORIZED_MODEL_IDS = {SAO_MODEL_ID}`",
        f"`BENCHMARK_CORE_AUTHORIZED_RUN_ID = {run_id}`",
    ]
    if duplicate_run:
        lines.append(f"`BENCHMARK_CORE_AUTHORIZED_RUN_ID = {run_id}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(lines[2:])


def test_exact_sao_core_decision_requires_one_run_and_sao_only(tmp_path: Path) -> None:
    decisions = tmp_path / "DECISIONS.md"
    block = _decision(decisions, run_id="sao-core-v2-001")
    block_sha = hashlib.sha256(block.encode()).hexdigest()
    result = verify_exact_sao_core_decision(
        decisions,
        decision_id="D-SAO",
        requested_run_id="sao-core-v2-001",
        expected_decision_block_sha256=block_sha,
    )
    assert result["authorized_run_id"] == "sao-core-v2-001"

    with pytest.raises(SaoOperationalAuthorizationError, match="requested run ID"):
        verify_exact_sao_core_decision(
            decisions,
            decision_id="D-SAO",
            requested_run_id="sao-core-v2-002",
            expected_decision_block_sha256=block_sha,
        )

    duplicate_block = _decision(decisions, run_id="sao-core-v2-001", duplicate_run=True)
    with pytest.raises(SaoOperationalAuthorizationError, match="exactly one"):
        verify_exact_sao_core_decision(
            decisions,
            decision_id="D-SAO",
            requested_run_id="sao-core-v2-001",
            expected_decision_block_sha256=hashlib.sha256(duplicate_block.encode()).hexdigest(),
        )


def test_sao_core_global_claim_is_external_and_replay_proof(tmp_path: Path) -> None:
    run_root = (tmp_path / "runtime" / "runs" / "core-v2").resolve()
    config = tmp_path / "sao-core.json"
    decisions = tmp_path / "DECISIONS.md"
    _write_json(config, {"fixture": "sao-only-core"})
    block = _decision(decisions, run_id="sao-core-v2-001")
    decision_sha = hashlib.sha256(block.encode()).hexdigest()
    config_sha = _sha(config)
    expected_claim_path = sao_core_global_claim_path(
        run_root,
        config_sha256=config_sha,
        decision_block_sha256=decision_sha,
    )
    assert expected_claim_path.parent == tmp_path / "runtime" / "claims" / "core-v2" / (
        "sao-one-shot"
    )

    first_run = run_root / "sao-core-v2-001"
    claimed = consume_sao_core_run_claim(
        run_id=first_run.name,
        run_dir=first_run,
        run_root=run_root,
        config_path=config,
        config_sha256=config_sha,
        decisions_path=decisions,
        decision_id="D-SAO",
        decision_block_sha256=decision_sha,
        git_commit="c" * 40,
    )
    assert claimed["path"] == str(expected_claim_path)
    assert claimed["exact_generations"] == 1_536
    validated = validate_sao_core_run_claim(
        expected_claim_path,
        run_id=first_run.name,
        run_dir=first_run,
        config_sha256=config_sha,
        decision_id="D-SAO",
        decision_block_sha256=decision_sha,
        git_commit="c" * 40,
    )
    assert validated["sha256"] == _sha(expected_claim_path)

    with pytest.raises(SaoOperationalAuthorizationError, match="already consumed"):
        consume_sao_core_run_claim(
            run_id="sao-core-v2-alternate",
            run_dir=run_root / "sao-core-v2-alternate",
            run_root=run_root,
            config_path=config,
            config_sha256=config_sha,
            decisions_path=decisions,
            decision_id="D-SAO",
            decision_block_sha256=decision_sha,
            git_commit="c" * 40,
        )


def test_launcher_consumes_sao_global_claim_before_queue_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = (tmp_path / "runtime" / "runs" / "core-v2").resolve()
    config_path = tmp_path / "sao-core.json"
    phase_terminal = tmp_path / "phase-b-terminal.json"
    decisions = tmp_path / "DECISIONS.md"
    _write_json(config_path, {"fixture": "sao-only-core"})
    _write_json(phase_terminal, {"status": "TERMINAL"})
    block = _decision(decisions, run_id="sao-core-v2-001")
    decision_sha = hashlib.sha256(block.encode()).hexdigest()
    config = SimpleNamespace(
        authorized_model_ids=(SAO_MODEL_ID,),
        models=(),
        phase_b_terminal=SimpleNamespace(path=phase_terminal),
        prior_model_completions={},
        repo_root=tmp_path,
        run_root=run_root,
        source_path=config_path,
        source_sha256=_sha(config_path),
    )
    monkeypatch.setattr(
        launcher_module,
        "load_core_execution_config",
        lambda *_args, **_kwargs: config,
    )
    monkeypatch.setattr(
        launcher_module,
        "observe_clean_origin_main",
        lambda _root: GitLaunchState(head="c" * 40, origin_main="c" * 40),
    )
    frozen_inputs: list[Path] = []

    def authorize(*_args: object, **kwargs: object) -> dict[str, str]:
        frozen_inputs.extend(kwargs["frozen_files"])
        return {"DECISION_BLOCK::D-SAO": decision_sha}

    monkeypatch.setattr(launcher_module, "verify_decision_authorization", authorize)
    queue_calls: list[str] = []

    def stop_at_queue(*_args: object, **_kwargs: object) -> dict[str, object]:
        queue_calls.append("queue")
        raise RuntimeError("test stop at queue materialization")

    monkeypatch.setattr(launcher_module, "build_queue", stop_at_queue)
    with pytest.raises(RuntimeError, match="test stop at queue"):
        prepare_run(
            config_path,
            run_id="sao-core-v2-001",
            decisions_path=decisions,
            decision_id="D-SAO",
            frozen_files=(),
            repo_root=tmp_path,
        )
    claim_path = sao_core_global_claim_path(
        run_root,
        config_sha256=config.source_sha256,
        decision_block_sha256=decision_sha,
    )
    assert claim_path.is_file()
    assert queue_calls == ["queue"]
    assert launcher_module.SAO_OPERATIONAL_CLAIMS_SOURCE in frozen_inputs

    queue_calls.clear()
    with pytest.raises(LaunchAuthorizationError, match="already consumed"):
        prepare_run(
            config_path,
            run_id="sao-core-v2-001",
            decisions_path=decisions,
            decision_id="D-SAO",
            frozen_files=(),
            repo_root=tmp_path,
        )
    assert queue_calls == []

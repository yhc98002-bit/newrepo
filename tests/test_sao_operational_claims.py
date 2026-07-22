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
    prepare_sao_mini_smoke_attempt,
    sao_core_global_claim_path,
    sao_mini_smoke_pre_model_replacement_decision_assignments,
    validate_sao_core_run_claim,
    validate_sao_mini_smoke_attempt_claim,
    validate_sao_mini_smoke_pre_model_failure_observation,
    verify_exact_sao_core_decision,
)
from benchmark_core.launcher import GitLaunchState, LaunchAuthorizationError, prepare_run

ROOT = Path(__file__).resolve().parents[1]


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


def _pre_model_replacement_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    original_run, original_claim = _patch_smoke_paths(monkeypatch, tmp_path)
    replacement_run = tmp_path / "runs" / "sao-mini-smoke-v2-002"
    replacement_claim = (
        tmp_path / "claims" / "sao-mini-smoke-v2-002.pre-model-replacement.claim.json"
    )
    failure_log = tmp_path / "logs" / "sao-mini-smoke-v2-001.launch.log"
    decisions = tmp_path / "DECISIONS.md"
    monkeypatch.setattr(claims_module, "SAO_MINI_SMOKE_REPLACEMENT_RUN_DIR", replacement_run)
    monkeypatch.setattr(
        claims_module,
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM",
        replacement_claim,
    )
    monkeypatch.setattr(claims_module, "SAO_MINI_SMOKE_FAILURE_LOG", failure_log)
    monkeypatch.setattr(claims_module, "SAO_DECISIONS_PATH", decisions)

    authorization = tmp_path / "authorization.json"
    live_config = tmp_path / "sao-live.json"
    _mini_authorization(authorization)
    _write_json(live_config, {"fixture": True})
    original = consume_sao_mini_smoke_attempt(
        authorization,
        requested_run_dir=original_run,
        live_config_path=live_config,
        git_commit="c" * 40,
    )
    monkeypatch.setattr(
        claims_module, "SAO_MINI_SMOKE_ORIGINAL_ATTEMPT_CLAIM_SHA256", original["sha256"]
    )
    monkeypatch.setattr(
        claims_module,
        "SAO_MINI_SMOKE_ORIGINAL_CLAIM_IDENTITY_SHA256",
        original["claim_identity_sha256"],
    )
    monkeypatch.setattr(
        claims_module,
        "SAO_MINI_SMOKE_ORIGINAL_RUNTIME_AUTHORIZATION_SHA256",
        _sha(authorization),
    )
    monkeypatch.setattr(claims_module, "SAO_MINI_SMOKE_ORIGINAL_GIT_COMMIT", "c" * 40)
    failure_log.parent.mkdir(parents=True)
    failure_log.write_text(
        claims_module._expected_pre_model_failure_log_text(), encoding="utf-8"
    )
    monkeypatch.setattr(
        claims_module, "SAO_MINI_SMOKE_FAILURE_LOG_SHA256", _sha(failure_log)
    )
    assignments = sao_mini_smoke_pre_model_replacement_decision_assignments()
    decisions.write_text(
        "# Decisions\n\n## D-0042 — fixture pre-model replacement\n"
        + "\n".join(f"`{key} = {value}`" for key, value in assignments.items())
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(claims_module, "_verify_clean_main_revision", lambda _git: None)
    return {
        "authorization": authorization,
        "decisions": decisions,
        "failure_log": failure_log,
        "live_config": live_config,
        "original_claim": original_claim,
        "original_run": original_run,
        "replacement_claim": replacement_claim,
        "replacement_run": replacement_run,
    }


def test_zero_call_observation_replacement_claim_and_no_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _pre_model_replacement_fixture(tmp_path, monkeypatch)
    observation = validate_sao_mini_smoke_pre_model_failure_observation()
    assert observation["cumulative_model_loads_before_replacement"] == 0
    assert observation["cumulative_model_calls_before_replacement"] == 0
    assert observation["cumulative_audio_outputs_before_replacement"] == 0

    decisions = fixture["decisions"]
    assert isinstance(decisions, Path)
    first_block_sha = claims_module.verify_sao_mini_smoke_pre_model_replacement_decision(
        decisions
    )["decision_block_sha256"]
    with decisions.open("a", encoding="utf-8") as handle:
        handle.write("\n## D-0043 — later append-only fixture\n`FIXTURE = YES`\n")
    assert (
        claims_module.verify_sao_mini_smoke_pre_model_replacement_decision(decisions)[
            "decision_block_sha256"
        ]
        == first_block_sha
    )

    preparation = prepare_sao_mini_smoke_attempt(
        fixture["authorization"],
        requested_run_dir=fixture["replacement_run"],
        live_config_path=fixture["live_config"],
        git_commit="d" * 40,
        decisions_path=decisions,
    )
    claimed = consume_sao_mini_smoke_attempt(
        fixture["authorization"],
        requested_run_dir=fixture["replacement_run"],
        live_config_path=fixture["live_config"],
        git_commit="d" * 40,
        decisions_path=decisions,
        prepared_attempt=preparation,
    )
    assert claimed["run_id"] == "sao-mini-smoke-v2-002"
    assert claimed["retry_allowed"] is False
    assert claimed["authorized_seed_schedule"][0]["seed"] == 73193011
    assert validate_sao_mini_smoke_attempt_claim(fixture["replacement_claim"])[
        "sha256"
    ] == _sha(fixture["replacement_claim"])
    with pytest.raises(SaoOperationalAuthorizationError, match="already consumed"):
        consume_sao_mini_smoke_attempt(
            fixture["authorization"],
            requested_run_dir=fixture["replacement_run"],
            live_config_path=fixture["live_config"],
            git_commit="d" * 40,
            decisions_path=decisions,
        )


def test_prepared_replacement_rejects_drift_and_self_consistent_forgery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _pre_model_replacement_fixture(tmp_path, monkeypatch)
    preparation = prepare_sao_mini_smoke_attempt(
        fixture["authorization"],
        requested_run_dir=fixture["replacement_run"],
        live_config_path=fixture["live_config"],
        git_commit="d" * 40,
        decisions_path=fixture["decisions"],
    )
    forged = json.loads(json.dumps(preparation))
    forged["record"]["authorized_calls"] = 4
    forged["preparation_identity_sha256"] = claims_module._preparation_identity(forged)
    with pytest.raises(SaoOperationalAuthorizationError, match="not the canonical"):
        consume_sao_mini_smoke_attempt(
            fixture["authorization"],
            requested_run_dir=fixture["replacement_run"],
            live_config_path=fixture["live_config"],
            git_commit="d" * 40,
            decisions_path=fixture["decisions"],
            prepared_attempt=forged,
        )
    assert not fixture["replacement_claim"].exists()

    _write_json(fixture["live_config"], {"fixture": "drifted"})
    with pytest.raises(SaoOperationalAuthorizationError, match="not the canonical"):
        consume_sao_mini_smoke_attempt(
            fixture["authorization"],
            requested_run_dir=fixture["replacement_run"],
            live_config_path=fixture["live_config"],
            git_commit="d" * 40,
            decisions_path=fixture["decisions"],
            prepared_attempt=preparation,
        )
    assert not fixture["replacement_claim"].exists()


def test_zero_call_observation_rejects_failure_log_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _pre_model_replacement_fixture(tmp_path, monkeypatch)
    failure_log = fixture["failure_log"]
    assert isinstance(failure_log, Path)
    failure_log.write_text(failure_log.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    with pytest.raises(SaoOperationalAuthorizationError, match="failure log hash mismatch"):
        validate_sao_mini_smoke_pre_model_failure_observation()


def test_runner_prepares_only_fixed_parent_and_never_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = importlib.import_module("scripts.run_sao_mini_smoke_v2")
    live_root = tmp_path / "runs" / "sao-live-v2"
    live_root.mkdir(parents=True)
    fixed_run = live_root / "mini-smoke" / "sao-mini-smoke-v2-002"
    monkeypatch.setattr(runner, "DEFAULT_RUN_DIR", fixed_run)
    runner._prepare_fixed_run_parent(fixed_run)
    assert fixed_run.parent.is_dir()
    assert not fixed_run.exists()
    runner._prepare_fixed_run_parent(fixed_run)
    assert not fixed_run.exists()
    with pytest.raises(RuntimeError, match="fixed replacement path"):
        runner._prepare_fixed_run_parent(fixed_run.with_name("sao-mini-smoke-v2-003"))


def test_repository_d0042_binds_the_final_replacement_sources() -> None:
    observed = claims_module.verify_sao_mini_smoke_pre_model_replacement_decision(
        claims_module.SAO_DECISIONS_PATH
    )
    assert observed["decision_id"] == "D-0042"
    assert len(observed["decision_block_sha256"]) == 64
    assignments = sao_mini_smoke_pre_model_replacement_decision_assignments()
    assert assignments["SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_IMPLEMENTATION_SHA256"] == (
        claims_module.SAO_D0042_REPLACEMENT_IMPLEMENTATION_SHA256
    )
    assert assignments["SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_IMPLEMENTATION_SHA256"] != _sha(
        ROOT / "src/backbones/sao_mini_smoke.py"
    )
    assert assignments["SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIMS_SHA256"] == (
        claims_module.SAO_D0042_REPLACEMENT_CLAIMS_SHA256
    )


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
            return SimpleNamespace(
                node="an12",
                physical_gpu_id=4,
                gpu_uuid="GPU-fixture",
                gpu_name="NVIDIA A800 fixture",
                free_vram_bytes=79_000_000_000,
                total_vram_bytes=80_000_000_000,
                utilization_percent=0,
                compute_pids=(),
            )

    def stop_at_claim(*_args: object, **_kwargs: object) -> dict[str, str]:
        events.append("attempt-claimed")
        raise RuntimeError("test stop at attempt claim")

    def prepare_parent(_run_dir: Path) -> None:
        events.append("parent-prepared")

    def prepare_attempt(*_args: object, **_kwargs: object) -> dict[str, object]:
        events.append("attempt-prepared")
        return {"sealed": True}

    monkeypatch.setattr(runner, "StableAudioOpenAdapter", FakeAdapter)
    monkeypatch.setattr(runner, "DeviceLease", FakeLease)
    monkeypatch.setattr(runner, "NvidiaSmiProbe", FakeProbe)
    monkeypatch.setattr(runner, "_prepare_fixed_run_parent", prepare_parent)
    monkeypatch.setattr(runner, "prepare_sao_mini_smoke_attempt", prepare_attempt)
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
        "parent-prepared",
        "attempt-prepared",
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


def test_committed_d0052_opens_only_the_hash_bound_sao_core_run() -> None:
    decisions = ROOT / "DECISIONS.md"
    block = claims_module._decision_block(decisions.read_text(encoding="utf-8"), "D-0052")
    block_sha256 = hashlib.sha256(block.encode()).hexdigest()

    observed = verify_exact_sao_core_decision(
        decisions,
        decision_id="D-0052",
        requested_run_id="benchmark-core-v2-sao-20260722t162200z",
        expected_decision_block_sha256=block_sha256,
    )
    assert observed["authorized_run_id"] == "benchmark-core-v2-sao-20260722t162200z"
    assert _sha(ROOT / "configs/benchmark_core_v2_sao_incremental.json") == (
        "4e96142e35553d391f89ad98b6c8bd055a5583746d15b2461f145713297a7713"
    )
    assert _sha(ROOT / "provenance/b2/sao_core_authorization_v2.json") == (
        "01c93e72bf6d110a310442cf20a8d5c7ab1991db6915b0dc82400f5c290f7b84"
    )
    assert _sha(ROOT / "provenance/b2/build_status_terminal_v2_sao_amendment.json") == (
        "e51057d133684b607473629f8791244216b8cbc18939f47558753fd16949e977"
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

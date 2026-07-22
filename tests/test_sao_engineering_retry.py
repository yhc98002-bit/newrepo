from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backbones import sao_engineering_retry as retry
from backbones.sao_operational_claims import SaoOperationalAuthorizationError

ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _decision(path: Path, decision_id: str) -> tuple[str, str]:
    assignments = retry.sao_engineering_retry_decision_assignments()
    lines = [f"## {decision_id} — fixture engineering repair", ""]
    lines.extend(f"`{key} = {value}`" for key, value in assignments.items())
    block = "\n".join(lines)
    path.write_text(f"# Decisions\n\n{block}\n", encoding="utf-8")
    return block, hashlib.sha256(block.encode()).hexdigest()


def test_retry_decision_vocabulary_freezes_scientific_request_and_new_identity() -> None:
    assignments = retry.sao_engineering_retry_decision_assignments()

    assert assignments["SAO_ENGINEERING_REPAIR_RUN_ID"] == "sao-mini-smoke-v2-003"
    assert assignments["SAO_ENGINEERING_REPAIR_EXACT_CALLS"] == "3"
    assert assignments["SAO_ENGINEERING_REPAIR_MAX_CLIP_SECONDS"] == "30"
    assert assignments["SAO_ENGINEERING_REPAIR_MAX_GPUS"] == "1"
    assert assignments["SAO_ENGINEERING_REPAIR_SCIENTIFIC_CONFIGURATION_CHANGED"] == "NO"
    assert assignments["SAO_ENGINEERING_REPAIR_PROMPTS_SEEDS_BUDGETS_CHANGED"] == "NO"
    assert assignments["SAO_ENGINEERING_FAILURES_REPAIRABLE"] == "YES"
    assert assignments["SAO_ENGINEERING_FUTURE_RETRY_REQUIRES_NEW_RUN_AND_CLAIM"] == "YES"
    assert all(len(value) == 64 for key, value in assignments.items() if key.endswith("_SHA256"))


def test_committed_cpu_receipt_binds_zero_gpu_repair_and_exact_patch() -> None:
    receipt = json.loads(
        (ROOT / "provenance/b2/sao_environment_repair_v2.json").read_text(encoding="utf-8")
    )

    assert receipt["status"] == "CPU_VALIDATED_READY_FOR_GOVERNED_MINI_SMOKE"
    assert receipt["scientific_result"] == "NONE_CPU_ENGINEERING_VALIDATION_ONLY"
    assert receipt["resource_use"] == {
        "generated_audio": 0,
        "gpu_calls": 0,
        "gpu_minutes": 0,
        "network_used": False,
        "token_used": False,
    }
    assert receipt["environment"]["complete_freeze_sha256"] == (
        "705a0c9d8be50b23b118422e00256661ac837780dec544755dec9dce228dd108"
    )
    assert receipt["license_and_snapshot"]["resolved_provider_revision"] == (
        retry.EXPECTED_SAO_REVISION
    )
    patch = ROOT / receipt["compatibility_choices"]["inference_import_repair"]["patch_path"]
    assert (
        hashlib.sha256(patch.read_bytes()).hexdigest()
        == (receipt["compatibility_choices"]["inference_import_repair"]["patch_sha256"])
    )
    assert receipt["attempts"][-1]["run_id"] == "sao-mini-smoke-v2-003"
    assert receipt["attempts"][-1]["run_exists_at_receipt_time"] is False
    assert receipt["attempts"][-1]["claim_exists_at_receipt_time"] is False


def test_retry_decision_requires_exact_single_append_only_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = tmp_path / "DECISIONS.md"
    decision_id = "D-SAO-ENGINEERING-REPAIR"
    block, block_sha256 = _decision(decisions, decision_id)
    monkeypatch.setattr(retry, "SAO_DECISIONS_PATH", decisions)

    observed = retry.verify_sao_engineering_retry_decision(
        decisions,
        decision_id=decision_id,
        expected_decision_block_sha256=block_sha256,
    )
    assert observed["decision_id"] == decision_id
    assert observed["decision_block_sha256"] == block_sha256

    decisions.write_text(
        f"# Decisions\n\n{block.replace('EXACT_CALLS = 3', 'EXACT_CALLS = 4')}\n",
        encoding="utf-8",
    )
    with pytest.raises(SaoOperationalAuthorizationError, match="decision block changed"):
        retry.verify_sao_engineering_retry_decision(
            decisions,
            decision_id=decision_id,
            expected_decision_block_sha256=block_sha256,
        )


def _claim_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path | str]:
    run_dir = tmp_path / "runtime/runs/sao-live-v2/mini-smoke/sao-mini-smoke-v2-003"
    claim = tmp_path / "runtime/claims/sao-live-v2/v2-003.claim.json"
    environment_manifest = tmp_path / "external/environment-manifest.json"
    previous_terminal = tmp_path / "external/sao-mini-smoke-v2-002-terminal.json"
    cpu_failure = tmp_path / "external/sao-engineering-env-v2-001-failure.json"
    authorization = tmp_path / "external/runtime-authorization.json"
    live_config = tmp_path / "repo/configs/sao_live_v2.json"
    decisions = tmp_path / "repo/DECISIONS.md"
    for path, payload in (
        (environment_manifest, {"fixture": "environment"}),
        (previous_terminal, {"fixture": "terminal"}),
        (cpu_failure, {"fixture": "cpu-failure"}),
        (live_config, {"fixture": "config"}),
    ):
        _write_json(path, payload)
    _write_json(
        authorization,
        {
            "access_receipt_sha256": "1" * 64,
            "backbone_config_sha256": "2" * 64,
            "decision_id": "D-0037",
            "max_clip_seconds": 30,
            "max_generations": 3,
            "max_gpus": 1,
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
        },
    )
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text("# Decisions\n", encoding="utf-8")

    monkeypatch.setattr(retry, "SAO_ENGINEERING_RETRY_RUN_DIR", run_dir)
    monkeypatch.setattr(retry, "SAO_ENGINEERING_RETRY_CLAIM_PATH", claim)
    monkeypatch.setattr(retry, "SAO_ENGINEERING_ENVIRONMENT_MANIFEST", environment_manifest)
    monkeypatch.setattr(retry, "SAO_ENGINEERING_ENVIRONMENT_PATH", tmp_path / "environment")
    monkeypatch.setattr(retry, "SAO_PREVIOUS_MINI_SMOKE_TERMINAL", previous_terminal)
    monkeypatch.setattr(retry, "SAO_ENGINEERING_CPU_FACTORY_FAILURE", cpu_failure)
    monkeypatch.setattr(retry, "SAO_RUNTIME_AUTHORIZATION_PATH", authorization)
    monkeypatch.setattr(
        retry,
        "SAO_RUNTIME_AUTHORIZATION_SHA256",
        hashlib.sha256(authorization.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(retry, "SAO_ENGINEERING_ENVIRONMENT_MANIFEST_SHA256", "3" * 64)
    monkeypatch.setattr(retry, "SAO_PREVIOUS_MINI_SMOKE_TERMINAL_SHA256", "4" * 64)
    monkeypatch.setattr(retry, "SAO_ENGINEERING_CPU_FACTORY_FAILURE_SHA256", "5" * 64)
    monkeypatch.setattr(
        retry,
        "validate_sao_engineering_environment",
        lambda *_args, **_kwargs: {
            "environment_path": str(tmp_path / "environment"),
            "manifest_identity_sha256": "6" * 64,
            "package_freeze_sha256": "7" * 64,
            "path": str(environment_manifest.resolve()),
            "sha256": "3" * 64,
        },
    )
    monkeypatch.setattr(
        retry,
        "validate_sao_engineering_failure_lineage",
        lambda: {
            "cpu_factory_failure_path": str(cpu_failure.resolve()),
            "cpu_factory_failure_sha256": "5" * 64,
            "previous_terminal_path": str(previous_terminal.resolve()),
            "previous_terminal_sha256": "4" * 64,
        },
    )
    monkeypatch.setattr(
        retry,
        "verify_sao_engineering_retry_decision",
        lambda *_args, **_kwargs: {
            "decision_block_sha256": "8" * 64,
            "decision_id": "D-SAO-REPAIR",
            "decisions_path": str(decisions.resolve()),
        },
    )
    monkeypatch.setattr(retry, "_verify_clean_main_revision", lambda *_args: None)
    return {
        "authorization": authorization,
        "claim": claim,
        "decisions": decisions,
        "environment_manifest": environment_manifest,
        "live_config": live_config,
        "run_dir": run_dir,
    }


def _prepare(fixture: dict[str, Path | str]) -> dict[str, object]:
    return retry.prepare_sao_engineering_retry_attempt(
        Path(fixture["authorization"]),
        requested_run_dir=Path(fixture["run_dir"]),
        live_config_path=Path(fixture["live_config"]),
        git_commit="a" * 40,
        decisions_path=Path(fixture["decisions"]),
        decision_id="D-SAO-REPAIR",
        decision_block_sha256="8" * 64,
        environment_manifest_path=Path(fixture["environment_manifest"]),
    )


def test_retry_claim_is_atomic_replay_proof_and_lineage_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _claim_fixture(tmp_path, monkeypatch)
    preparation = _prepare(fixture)

    observed = retry.consume_sao_engineering_retry_attempt(
        Path(fixture["authorization"]),
        requested_run_dir=Path(fixture["run_dir"]),
        live_config_path=Path(fixture["live_config"]),
        git_commit="a" * 40,
        decisions_path=Path(fixture["decisions"]),
        decision_id="D-SAO-REPAIR",
        decision_block_sha256="8" * 64,
        environment_manifest_path=Path(fixture["environment_manifest"]),
        prepared_attempt=preparation,
    )

    assert observed["run_id"] == "sao-mini-smoke-v2-003"
    assert observed["previous_terminal_sha256"] == "4" * 64
    assert observed["cpu_factory_failure_sha256"] == "5" * 64
    assert observed["scientific_configuration_changed"] is False
    assert observed["prompts_seeds_budgets_changed"] is False
    assert observed["future_engineering_retry_requires_new_run_and_claim"] is True
    assert Path(fixture["claim"]).stat().st_mode & 0o777 == 0o444
    assert not Path(fixture["run_dir"]).exists()

    with pytest.raises(SaoOperationalAuthorizationError, match="already consumed"):
        _prepare(fixture)


def test_retry_preparation_rejects_bound_input_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _claim_fixture(tmp_path, monkeypatch)
    preparation = _prepare(fixture)
    _write_json(Path(fixture["live_config"]), {"fixture": "drifted"})

    with pytest.raises(SaoOperationalAuthorizationError, match="prepared attempt is not canonical"):
        retry.consume_sao_engineering_retry_attempt(
            Path(fixture["authorization"]),
            requested_run_dir=Path(fixture["run_dir"]),
            live_config_path=Path(fixture["live_config"]),
            git_commit="a" * 40,
            decisions_path=Path(fixture["decisions"]),
            decision_id="D-SAO-REPAIR",
            decision_block_sha256="8" * 64,
            environment_manifest_path=Path(fixture["environment_manifest"]),
            prepared_attempt=preparation,
        )
    assert not Path(fixture["claim"]).exists()


def test_retry_runner_prepares_only_new_fixed_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = importlib.import_module("scripts.run_sao_engineering_retry_v2")
    live_root = tmp_path / "runs/sao-live-v2"
    live_root.mkdir(parents=True)
    fixed_run = live_root / "mini-smoke/sao-mini-smoke-v2-003"
    monkeypatch.setattr(runner, "DEFAULT_RUN_DIR", fixed_run)

    runner._prepare_fixed_run_parent(fixed_run)
    assert fixed_run.parent.is_dir()
    assert not fixed_run.exists()
    with pytest.raises(RuntimeError, match="fixed engineering-repair path"):
        runner._prepare_fixed_run_parent(fixed_run.with_name("sao-mini-smoke-v2-004"))


def test_retry_runner_claims_after_cpu_gate_offline_preflight_and_safe_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = importlib.import_module("scripts.run_sao_engineering_retry_v2")
    events: list[str] = []
    monkeypatch.setattr(runner, "validate_live_config", lambda *_args: None)
    monkeypatch.setattr(runner, "_verify_seeds", lambda: None)
    monkeypatch.setattr(runner, "_git_state", lambda: "c" * 40)
    monkeypatch.setattr(runner.socket, "gethostname", lambda: "an12")
    monkeypatch.setattr(runner, "HF_TOKEN_ENVIRONMENT_VARIABLES", ())

    def validate_environment(*_args: object) -> dict[str, str]:
        events.append("cpu-environment-gate")
        return {"package_freeze_sha256": "f" * 64}

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
                physical_gpu_id=7,
                gpu_uuid="GPU-fixture",
                gpu_name="NVIDIA A800 fixture",
                free_vram_bytes=79_000_000_000,
                total_vram_bytes=80_000_000_000,
                utilization_percent=0,
                compute_pids=(),
            )

    def prepare_parent(_run_dir: Path) -> None:
        events.append("parent-prepared")

    def prepare_attempt(*_args: object, **_kwargs: object) -> dict[str, object]:
        events.append("attempt-prepared")
        return {"sealed": True}

    def stop_at_claim(*_args: object, **_kwargs: object) -> dict[str, str]:
        events.append("attempt-claimed")
        raise RuntimeError("test stop at attempt claim")

    monkeypatch.setattr(runner, "validate_sao_engineering_environment", validate_environment)
    monkeypatch.setattr(runner, "StableAudioOpenAdapter", FakeAdapter)
    monkeypatch.setattr(runner, "DeviceLease", FakeLease)
    monkeypatch.setattr(runner, "NvidiaSmiProbe", FakeProbe)
    monkeypatch.setattr(runner, "_prepare_fixed_run_parent", prepare_parent)
    monkeypatch.setattr(runner, "prepare_sao_engineering_retry_attempt", prepare_attempt)
    monkeypatch.setattr(runner, "consume_sao_engineering_retry_attempt", stop_at_claim)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_sao_engineering_retry_v2.py",
            "--snapshot-dir",
            str(tmp_path / "snapshot"),
            "--access-receipt",
            str(tmp_path / "receipt.json"),
            "--runtime-authorization",
            str(tmp_path / "authorization.json"),
            "--engineering-decision-id",
            "D-SAO-REPAIR",
            "--engineering-decision-block-sha256",
            "e" * 64,
            "--physical-gpu-id",
            "7",
        ],
    )

    with pytest.raises(RuntimeError, match="test stop at attempt claim"):
        runner.main()
    assert events == [
        "cpu-environment-gate",
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

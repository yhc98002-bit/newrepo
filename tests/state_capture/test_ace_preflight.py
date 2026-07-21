from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from scripts import run_ace_state_preflight_v2_with_timeout as timeout_wrapper
from state_capture.ace_artifacts import (
    ArtifactValidationError,
    AttemptConsumed,
    HashChainedLedger,
    OneShotAttemptStore,
    basic_audio_sanity,
    compare_audio_equivalence,
    sha256_file,
    validate_adjacent_provenance,
    validate_ledger,
    write_adjacent_provenance,
)
from state_capture.ace_child import (
    RESUME_CHILD_REQUEST_FORMAT,
    execute_request,
)
from state_capture.ace_contract import (
    ATTEMPT_ID,
    AUTHORIZATION_ID,
    CHECKPOINT_COMPLETED_TRANSITIONS,
    CHECKPOINT_CUMULATIVE_NFE,
    EXECUTE_PHRASE,
    OUTER_KILL_GRACE_SECONDS,
    OUTER_SOFT_TIMEOUT_SECONDS,
    PACKAGE_RELATIVE_PATHS,
    RUN_ID,
    SCOPE,
    AceContractError,
    Authorization,
    json_sha256,
    static_readiness_report,
    validate_static_config,
)
from state_capture.ace_engine import (
    ENGINE_RESULT_FORMAT,
    AceEngineError,
    ProductionAceStateEngine,
    inspect_production_capability,
    load_ace_checkpoint,
    save_ace_checkpoint,
)
from state_capture.ace_runner import package_hashes, run_dry_preflight

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/ace_state_preflight_v2.json"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n")


def _authorization(path: Path, contract: Any) -> Authorization:
    raw = {
        "authorization_id": AUTHORIZATION_ID,
        "scope": SCOPE,
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
    }
    _write_json(path, raw)
    return Authorization(
        path=path.resolve(),
        raw=raw,
        sha256=sha256_file(path),
        attempt_token_sha256="1" * 64,
        git_commit="2" * 40,
        node="an12",
        physical_gpu_id=4,
    )


def _fixture_audio(path: Path, *, delta: float = 0.0) -> None:
    sample_rate = 48_000
    frames = sample_rate // 10
    time = np.arange(frames, dtype=np.float64) / sample_rate
    left = 0.1 * np.sin(2 * np.pi * 220 * time) + delta
    right = 0.08 * np.sin(2 * np.pi * 330 * time) - delta
    sf.write(path, np.stack((left, right), axis=1), sample_rate, subtype="FLOAT")


def test_static_contract_freezes_nfe_checkpoints_caps_and_scientific_boundary() -> None:
    contract = validate_static_config(CONFIG, repository_root=ROOT)

    assert contract.raw["protocol_status"] == "PREPARED_NOT_AUTHORIZED"
    assert contract.raw["authorization"]["execution_authorized_by_this_config_alone"] is False
    assert contract.raw["checkpoint_contract"]["completed_scheduler_transitions"] == [9, 15, 20]
    assert contract.raw["checkpoint_contract"]["cumulative_transformer_nfe"] == [11, 23, 33]
    assert tuple(contract.raw["checkpoint_contract"]["completed_scheduler_transitions"]) == (
        CHECKPOINT_COMPLETED_TRANSITIONS
    )
    assert tuple(contract.raw["checkpoint_contract"]["cumulative_transformer_nfe"]) == (
        CHECKPOINT_CUMULATIVE_NFE
    )
    assert contract.raw["caps"] == {
        "exact_model_calls_if_completed": 4,
        "exact_retained_audio_outputs_if_completed": 4,
        "max_clip_seconds_requested": 30.0,
        "max_generations_absolute": 8,
        "max_gpu_seconds": 600.0,
        "max_gpus": 1,
        "max_model_calls": 4,
        "max_retries": 0,
        "max_state_exports": 3,
        "replica_count": 1,
        "tensor_parallel_width": 1,
    }
    assert contract.raw["placement"]["node_priority"][0] == "an12"
    assert contract.raw["placement"]["candidate_physical_gpu_ids"] == [4, 5, 6, 7]
    assert contract.raw["scientific_boundary"]["state_queue_access"] == "FORBIDDEN"
    assert contract.raw["proposed_reference_request"]["registration_status"] == (
        "REGISTERED_AS_S0010_FOR_D0031_ONE_ATTEMPT_PREFLIGHT"
    )


def test_static_contract_rejects_retry_or_budget_drift(tmp_path: Path) -> None:
    value = json.loads(CONFIG.read_text())
    value["caps"]["max_retries"] = 1
    changed = tmp_path / "changed.json"
    _write_json(changed, value)

    with pytest.raises(AceContractError, match="no-retry caps changed"):
        validate_static_config(changed, repository_root=ROOT)


def test_read_only_dry_run_never_authorizes_or_touches_cuda() -> None:
    result = run_dry_preflight(
        config_path=CONFIG,
        repository_root=ROOT,
        environ={},
    )

    assert result["status"] == "PREPARED_NOT_AUTHORIZED"
    assert result["model_calls"] == 0
    assert result["generated_outputs"] == 0
    assert result["writes_performed"] is False
    assert result["cuda_touched"] is False
    assert result["state_queue_accessed"] is False
    assert result["engine_capability"]["native_upstream_resume_argument"] is False
    assert result["engine_capability"]["status"] == "BLOCKED"
    assert "EXTERNAL_AUTHORIZATION_ABSENT" in result["blocking_gates"]
    assert set(result["package_sha256"]) == set(PACKAGE_RELATIVE_PATHS)


def test_registered_s0010_is_explicit_in_static_readiness() -> None:
    contract = validate_static_config(CONFIG, repository_root=ROOT)
    report = static_readiness_report(contract, repository_root=ROOT)

    assert report["reference_request_registration"] == {
        "seed_id": "S-0010",
        "seed": 73193010,
        "registration_status": "REGISTERED_AS_S0010_FOR_D0031_ONE_ATTEMPT_PREFLIGHT",
        "append_only_seed_registry_row_present": True,
        "authorizing_decision": "D-0031",
    }
    assert report["postfreeze_decision"]["exact_latest_assignments_present"] is True
    assert report["postfreeze_decision"]["execution_authority_effect"] == (
        "NONE_WITHOUT_COMPLETED_EXTERNAL_AUTHORIZATION"
    )
    assert "POSTFREEZE_DECISION_ABSENT" not in report["blocking_gates"]
    assert "EXTERNAL_AUTHORIZATION_ABSENT" in report["blocking_gates"]


def test_one_shot_claim_cryptographically_blocks_second_attempt(tmp_path: Path) -> None:
    contract = validate_static_config(CONFIG, repository_root=ROOT)
    authorization = _authorization(tmp_path / "authorization.json", contract)
    store = OneShotAttemptStore(
        tmp_path / "claims",
        claim_filename="ace-state-preflight-v2-one-attempt.claim.json",
        repository_root=ROOT,
    )
    packages = package_hashes(ROOT)

    first = store.consume(
        authorization=authorization,
        contract=contract,
        package_sha256=packages,
    )
    first_bytes = store.claim_path.read_bytes()
    with pytest.raises(AttemptConsumed, match="already consumed"):
        store.consume(
            authorization=authorization,
            contract=contract,
            package_sha256=packages,
        )
    assert store.claim_path.read_bytes() == first_bytes

    terminal = store.write_terminal(
        status="FAIL",
        claim_sha256=first["sha256"],
        ledger_path=None,
        payload={"error": "fixture failure", "model_call_count": 0},
    )
    assert terminal["status"] == "FAIL"
    assert terminal["retry_allowed"] is False
    with pytest.raises(AttemptConsumed, match="already has a terminal"):
        store.write_terminal(
            status="PASS",
            claim_sha256=first["sha256"],
            ledger_path=None,
            payload={},
        )


def test_hash_chained_call_ledger_rejects_retry_transition(tmp_path: Path) -> None:
    ledger = HashChainedLedger(tmp_path / "ledger.jsonl")
    ledger.transition("reference", "CLAIMED", {"call_index": 0})
    ledger.transition("reference", "CALL_STARTED")
    ledger.transition("reference", "FAILED", {"error": "fixture"})

    rows = validate_ledger(ledger.path)
    assert [row["call_state"] for row in rows] == ["CLAIMED", "CALL_STARTED", "FAILED"]
    assert rows[0]["previous_row_sha256"] == "0" * 64
    assert ledger.tail_sha256() == rows[-1]["ledger_row_sha256"]
    with pytest.raises(ArtifactValidationError, match="invalid call transition"):
        ledger.transition("reference", "CLAIMED")


def test_audio_sanity_equivalence_and_adjacent_provenance(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    resumed = tmp_path / "resumed.wav"
    _fixture_audio(reference)
    _fixture_audio(resumed)

    sanity = basic_audio_sanity(reference, requested_duration_seconds=0.1)
    comparison = compare_audio_equivalence(
        reference,
        resumed,
        max_absolute_error=1e-5,
        minimum_snr_db=80.0,
    )
    provenance = write_adjacent_provenance(
        resumed,
        label="synthetic_model_output",
        run_id=RUN_ID,
        creating_call_id="fixture",
        model_revision="3" * 40,
        source_ids={"fixture": True},
    )

    assert sanity["status"] == "PASS"
    assert comparison["status"] == "PASS"
    assert comparison["max_absolute_error"] == 0.0
    assert comparison["snr_db_infinite"] is True
    assert provenance["label"] == "synthetic_model_output"
    assert validate_adjacent_provenance(resumed)["sha256"] == sha256_file(resumed)


def test_cpu_checkpoint_round_trip_binds_fp32_schedule_rng_and_metadata(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    contract = validate_static_config(CONFIG, repository_root=ROOT)
    path = tmp_path / "checkpoint-09.pt"
    latent = torch.arange(12, dtype=torch.float32).reshape(1, 3, 4)
    timesteps = torch.linspace(1.0, 0.0, 30, dtype=torch.float32)
    sigmas = torch.linspace(1.0, 0.0, 31, dtype=torch.float32)
    generator_state = torch.Generator().manual_seed(17).get_state()
    metadata = {
        "schema_version": 2,
        "model_id": "ACE-Step/ACE-Step-v1-3.5B",
        "config_sha256": contract.sha256,
        "request_sha256": "4" * 64,
        "checkpoint_fraction": 0.25,
        "completed_scheduler_transitions": 9,
        "next_scheduler_index": 9,
        "cumulative_transformer_nfe": 11,
        "conditioning_sha256": "5" * 64,
        "runtime_schedule_sha256": "6" * 64,
        "runtime_rng_state_sha256": "7" * 64,
    }

    saved = save_ace_checkpoint(
        path,
        latent=latent,
        timesteps=timesteps,
        sigmas=sigmas,
        generator_state=generator_state,
        metadata=metadata,
    )
    loaded = load_ace_checkpoint(
        path,
        expected_artifact_sha256=saved["sha256"],
        expected_config_sha256=contract.sha256,
    )

    assert loaded.latent.dtype == torch.float32
    assert loaded.latent.device.type == "cpu"
    assert torch.equal(loaded.latent, latent)
    assert loaded.metadata["next_scheduler_index"] == 9
    assert loaded.metadata["tensor_sha256"]["generator_state"]


class _FakeChildEngine:
    def __init__(self, _context: Mapping[str, Any]) -> None:
        self.closed = False

    def run_reference(self, **_kwargs: Any) -> Mapping[str, Any]:
        raise AssertionError("child fixture must not run a reference")

    def run_resume(
        self,
        *,
        request: Mapping[str, Any],
        checkpoint_path: Path,
        output_path: Path,
    ) -> Mapping[str, Any]:
        assert sha256_file(checkpoint_path) == request["checkpoint_sha256"]
        _fixture_audio(output_path)
        return {
            "format": ENGINE_RESULT_FORMAT,
            "status": "PASS",
            "pid": os.getpid(),
            "mode": "RESUME",
            "model_id": "ACE-Step/ACE-Step-v1-3.5B",
            "output_path": str(output_path.resolve()),
            "output_sha256": sha256_file(output_path),
            "checkpoint_source_path": str(checkpoint_path.resolve()),
            "checkpoint_source_sha256": sha256_file(checkpoint_path),
            "checkpoints": [],
            "conditioning_sha256": "8" * 64,
            "runtime_schedule_sha256": "9" * 64,
            "runtime_rng_state_sha256": "a" * 64,
            "terminal_latent_sha256": "b" * 64,
            "actual_nfe": 34,
            "load_seconds": 0.01,
            "gpu_seconds": 0.02,
            "peak_allocated_bytes": 1,
            "peak_reserved_bytes": 2,
        }

    def close(self) -> None:
        self.closed = True


def fake_child_engine_factory(context: Mapping[str, Any]) -> _FakeChildEngine:
    return _FakeChildEngine(context)


def test_resume_child_runs_in_a_distinct_interpreter_and_binds_artifacts(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"fixture checkpoint")
    sidecar = checkpoint.with_name(f"{checkpoint.name}.state.json")
    _write_json(sidecar, {"fixture": True})
    output = tmp_path / "resume.wav"
    result = tmp_path / "resume-result.json"
    request = {
        "format": RESUME_CHILD_REQUEST_FORMAT,
        "request_id": "resume-25",
        "parent_pid": os.getpid(),
        "engine_factory": (
            "tests.state_capture.test_ace_preflight:fake_child_engine_factory"
        ),
        "engine_context": {"fixture": True},
        "engine_context_sha256": json_sha256({"fixture": True}),
        "checkpoint_path": str(checkpoint.resolve()),
        "checkpoint_sha256": sha256_file(checkpoint),
        "checkpoint_state_metadata_sha256": sha256_file(sidecar),
        "output_path": str(output.resolve()),
        "result_path": str(result.resolve()),
        "reference_request": {"prompt": "fixture", "seed": 1},
        "config_sha256": "c" * 64,
    }
    request["request_identity_sha256"] = json_sha256(request)
    request_path = tmp_path / "request.json"
    _write_json(request_path, request)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT), environment.get("PYTHONPATH", "")]
    )

    process = subprocess.run(
        [sys.executable, "-B", "-m", "state_capture.ace_child", "--request", str(request_path)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    child = json.loads(process.stdout)

    assert child["status"] == "PASS"
    assert child["child_pid"] != os.getpid()
    assert child["engine_result"]["pid"] == child["child_pid"]
    assert child["request_sha256"] == sha256_file(request_path)
    assert child["result_sha256"] == sha256_file(result)
    assert basic_audio_sanity(output, requested_duration_seconds=0.1)["status"] == "PASS"


def test_direct_child_executor_rejects_same_process_parent_pid(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"fixture")
    sidecar = checkpoint.with_name(f"{checkpoint.name}.state.json")
    _write_json(sidecar, {})
    request = {
        "format": RESUME_CHILD_REQUEST_FORMAT,
        "request_id": "resume-25",
        "parent_pid": os.getpid(),
        "engine_factory": "tests.state_capture.test_ace_preflight:fake_child_engine_factory",
        "engine_context": {},
        "engine_context_sha256": json_sha256({}),
        "checkpoint_path": str(checkpoint),
        "checkpoint_sha256": sha256_file(checkpoint),
        "checkpoint_state_metadata_sha256": sha256_file(sidecar),
        "output_path": str(tmp_path / "out.wav"),
        "result_path": str(tmp_path / "result.json"),
        "reference_request": {},
        "config_sha256": "d" * 64,
    }
    request["request_identity_sha256"] = json_sha256(request)
    request_path = tmp_path / "request.json"
    _write_json(request_path, request)

    with pytest.raises(RuntimeError, match="distinct from its parent"):
        execute_request(request_path)


def test_capability_probe_documents_native_engine_limitation_without_importing_ace() -> None:
    contract = validate_static_config(CONFIG, repository_root=ROOT)
    report = inspect_production_capability(contract, environ={})

    assert report["model_calls"] == 0
    assert report["generated_outputs"] == 0
    assert report["native_upstream_checkpoint_callback"] is False
    assert report["native_upstream_resume_argument"] is False
    assert report["execution_surface"] == (
        "HASH_GUARDED_CONTROLLED_DIFFUSION_METHOD_INTERPOSITION"
    )
    assert any("no native checkpoint callback" in row for row in report["engine_limitations"])


def test_interposition_recreates_no_grad_and_requires_resident_no_offload_transformer() -> None:
    torch = pytest.importorskip("torch")

    class FakePipeline:
        def __init__(self) -> None:
            self.cpu_offload = False
            self.device = torch.device("cpu")
            self.ace_step_transformer = torch.nn.Linear(2, 2)

        def __call__(self, **_kwargs: Any) -> bool:
            return torch.is_grad_enabled()

    pipeline = FakePipeline()
    residency = ProductionAceStateEngine._verify_transformer_residency(pipeline)

    assert residency["all_parameters_and_buffers_on_expected_device"] is True
    assert residency["upstream_cpu_offload_decorator_effect"] == (
        "NO_OP_WHEN_CPU_OFFLOAD_IS_FALSE"
    )
    assert ProductionAceStateEngine._invoke_pipeline_no_grad(pipeline, {}) is False

    pipeline.cpu_offload = True
    with pytest.raises(AceEngineError, match="cpu_offload=False"):
        ProductionAceStateEngine._verify_transformer_residency(pipeline)


def test_exact_execute_phrase_and_outer_timeout_fit_the_600_second_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert EXECUTE_PHRASE == (
        "I_UNDERSTAND_THIS_CONSUMES_THE_ONLY_ACE_STATE_PREFLIGHT_ATTEMPT"
    )
    authorization = tmp_path / "authorization.json"
    _write_json(authorization, {})

    monkeypatch.setattr(timeout_wrapper.sys, "executable", str(Path("/usr/bin/true")))
    with pytest.raises(RuntimeError, match="wrapper must run with"):
        timeout_wrapper.build_timeout_command(
            config_path=CONFIG,
            authorization_path=authorization,
            run_id=RUN_ID,
            execute_phrase=EXECUTE_PHRASE,
        )

    monkeypatch.setattr(
        timeout_wrapper.sys,
        "executable",
        str(timeout_wrapper.PYTHON_PATH),
    )
    command = timeout_wrapper.build_timeout_command(
        config_path=CONFIG,
        authorization_path=authorization,
        run_id=RUN_ID,
        execute_phrase=EXECUTE_PHRASE,
    )
    assert command[1:4] == [
        "-k",
        f"{OUTER_KILL_GRACE_SECONDS}s",
        f"{OUTER_SOFT_TIMEOUT_SECONDS}s",
    ]
    assert OUTER_SOFT_TIMEOUT_SECONDS + OUTER_KILL_GRACE_SECONDS == 600

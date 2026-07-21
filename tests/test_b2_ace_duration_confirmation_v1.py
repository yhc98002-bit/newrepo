from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from audio_duration_policy import duration_within_tolerance
from backbones.duration_sanity import duration_tolerant_audio_sanity
from sa3_smoke.artifacts import write_adjacent_provenance
from sa3_smoke.audio import save_float_wav_exclusive
from scripts.run_b2_ace_duration_confirmation_v1 import (
    DEFAULT_CONFIG,
    EXPECTED_AUDIO_SANITY_POLICY,
    EXPECTED_AUTHORIZATION_CAPS,
    EXPECTED_DURATION_POLICY,
    EXPECTED_FROZEN_PATHS,
    EXPECTED_JOB,
    AuthorizedConfirmationFailure,
    B2ExecutionError,
    B2GateError,
    DurableLog,
    OneCallClaimingAdapter,
    _append_ledger_row,
    _expected_decisions_assignments,
    confirmation_row_status,
    consume_authorized_attempt,
    expected_outer_commands,
    sha256_file,
    terminal_failure_record,
    validate_external_authorization,
    validate_one_row_ledger,
    validate_prior_consumed_evidence,
    validate_static_config,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FROZEN_V2_HASHES = {
    "B2_MINI_SMOKE_PROTOCOL_v2.md": (
        "2338cc92b1be99ce011902f9f7429976657ccb8ce2a791634d965096ce9c6118"
    ),
    "configs/b2_mini_smoke_v2.json": (
        "01a1bd650dbe3f23eeb60c07c46c4a9d66750f4d8070f5e872604c7c4142f632"
    ),
    "scripts/run_b2_mini_smoke_v2.py": (
        "040d0f75280c7adfbe614f74dab4a236b70068325ea4f85fe20b4b98ad56baff"
    ),
    "scripts/run_b2_mini_smoke_v2_with_timeout.py": (
        "1ba0dcd7f35e4f56a0f836da10491f440eed12689ca83cca47fbd56aeb47400f"
    ),
    "src/backbones/mini_smoke.py": (
        "d7b810a1f1e35a7193ea2bf3ac34a5071c017c415407b90cf203737f9fed20e5"
    ),
    "src/sa3_smoke/audio.py": ("c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24"),
}


def _attach_provenance(path: Path) -> None:
    write_adjacent_provenance(
        path,
        {
            "label": "synthetic_model_output",
            "created_at_utc": "2026-07-21T00:00:00+00:00",
            "creating_command": "duration-confirmation unit fixture",
            "run_id": "duration-confirmation-test",
            "source_ids": ["test/ace@fixed"],
            "model_revision": "fixed",
            "license_identifier": "test-only",
            "transformation": "constant non-silent unit fixture",
        },
    )


def _write_wav(
    path: Path,
    *,
    frames: int,
    sample_rate: int = 48_000,
    channels: int = 2,
    value: float = 0.1,
    provenance: bool = True,
) -> None:
    samples = np.full((frames, channels), value, dtype=np.float32)
    save_float_wav_exclusive(path, samples, sample_rate)
    if provenance:
        _attach_provenance(path)


def test_frozen_v2_package_remains_byte_exact() -> None:
    for relative, expected in FROZEN_V2_HASHES.items():
        assert sha256_file(REPOSITORY_ROOT / relative) == expected


def test_static_package_is_exactly_one_s0009_job_at_exact_policy() -> None:
    config, hashes = validate_static_config()
    assert config["jobs"] == [EXPECTED_JOB]
    assert config["caps"]["exact_model_calls"] == 1
    assert config["caps"]["exact_generated_outputs"] == 1
    assert config["caps"]["max_retries"] == 0
    assert config["audio_sanity"] == EXPECTED_AUDIO_SANITY_POLICY
    assert config["scoring"] == {
        "benchmark_endpoints_scored": False,
        "human_packet_member": False,
        "instrument_evaluation_allowed": False,
    }
    assert "S-0008" not in json.dumps(config["jobs"])
    assert hashes["duration_readjudication"] == (
        "be4e3a9d705c1e8cb627b08fec3be28fad6ff4623d530283b7f32056a031129e"
    )


@pytest.mark.parametrize(
    ("observed", "expected"),
    [(30.0, True), (29.75, True), (30.25, True), (29.749999, False), (30.250001, False)],
)
def test_generic_duration_predicate_has_inclusive_boundary(observed: float, expected: bool) -> None:
    assert duration_within_tolerance(observed, 30.0, 0.25) is expected


@pytest.mark.parametrize("tolerance", [0.2500001, float("inf"), float("nan"), -0.1])
def test_backbone_duration_wrapper_rejects_looser_or_invalid_policy(
    tmp_path: Path, tolerance: float
) -> None:
    with pytest.raises(ValueError):
        duration_tolerant_audio_sanity(
            tmp_path / "unused.wav",
            30.0,
            duration_tolerance_seconds=tolerance,
            require_provenance=False,
        )


def test_native_ace_duration_and_inclusive_boundaries_pass(tmp_path: Path) -> None:
    frame_counts = [1_435_551, 1_428_000, 1_452_000]
    for index, frames in enumerate(frame_counts):
        wav = tmp_path / f"boundary-{index}.wav"
        _write_wav(wav, frames=frames)
        result = duration_tolerant_audio_sanity(
            wav,
            30.0,
            duration_tolerance_seconds=0.25,
            expected_sample_rate=48_000,
            expected_channels=2,
        )
        assert result["pass"] is True
        assert result["legacy_exact_sample_count_pass"] is False
        assert result["duration_within_tolerance"] is True
    assert result["absolute_duration_error_seconds"] == pytest.approx(0.25)


def test_one_frame_outside_and_wrong_rate_or_channels_remain_failures(tmp_path: Path) -> None:
    outside = tmp_path / "outside.wav"
    _write_wav(outside, frames=1_427_999)
    outside_result = duration_tolerant_audio_sanity(
        outside,
        30.0,
        duration_tolerance_seconds=0.25,
        expected_sample_rate=48_000,
        expected_channels=2,
    )
    assert outside_result["pass"] is False
    assert {row["check"] for row in outside_result["failures"]} == {"duration_tolerance"}

    wrong_rate = tmp_path / "wrong-rate.wav"
    _write_wav(wrong_rate, frames=1_323_000, sample_rate=44_100)
    wrong_rate_result = duration_tolerant_audio_sanity(
        wrong_rate,
        30.0,
        duration_tolerance_seconds=0.25,
        expected_sample_rate=48_000,
        expected_channels=2,
    )
    assert wrong_rate_result["pass"] is False
    assert "sample_rate" in {row["check"] for row in wrong_rate_result["failures"]}
    status, matches = confirmation_row_status(
        wrong_rate_result,
        44_100,
        EXPECTED_AUDIO_SANITY_POLICY,
    )
    assert status == "ADAPTER_MEASUREMENT_SAMPLE_RATE_FAILED"
    assert matches is False

    mono = tmp_path / "mono.wav"
    _write_wav(mono, frames=1_440_000, channels=1)
    mono_result = duration_tolerant_audio_sanity(
        mono,
        30.0,
        duration_tolerance_seconds=0.25,
        expected_sample_rate=48_000,
        expected_channels=2,
    )
    assert mono_result["pass"] is False
    assert "channels" in {row["check"] for row in mono_result["failures"]}


def test_adapter_measurement_rate_disagreement_fails_even_when_wav_is_valid(
    tmp_path: Path,
) -> None:
    wav = tmp_path / "native.wav"
    _write_wav(wav, frames=1_435_551)
    sanity = duration_tolerant_audio_sanity(
        wav,
        30.0,
        duration_tolerance_seconds=0.25,
        expected_sample_rate=48_000,
        expected_channels=2,
    )
    assert sanity["pass"] is True
    status, matches = confirmation_row_status(sanity, 44_100, EXPECTED_AUDIO_SANITY_POLICY)
    assert status == "ADAPTER_MEASUREMENT_SAMPLE_RATE_FAILED"
    assert matches is False


def test_silence_and_missing_provenance_are_not_forgiven(tmp_path: Path) -> None:
    wav = tmp_path / "silence.wav"
    _write_wav(wav, frames=1_435_551, value=0.0, provenance=False)
    result = duration_tolerant_audio_sanity(
        wav,
        30.0,
        duration_tolerance_seconds=0.25,
        expected_sample_rate=48_000,
        expected_channels=2,
    )
    failed = {row["check"] for row in result["failures"]}
    assert result["pass"] is False
    assert {"rms", "peak_abs", "active_fraction", "provenance"}.issubset(failed)
    assert "sample_count" not in failed


def test_retained_call_is_read_only_revalidated_under_amendment() -> None:
    config, _ = validate_static_config()
    evidence = validate_prior_consumed_evidence(config)
    sanity = evidence["retained_call_readjudication"]
    assert sanity["pass"] is True
    assert sanity["legacy_exact_sample_count_pass"] is False
    assert sanity["duration_seconds"] == 29.9073125
    assert sanity["absolute_duration_error_seconds"] == pytest.approx(0.0926875)
    assert evidence["duration_quantization_replicated_seed_count"] == 8


class _FakeDelegate:
    model_id = "test/ace"
    logical_name = "ACE-Step v1"
    config_sha256 = "a" * 64
    license_identifier = "test-only"

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def preflight(self) -> SimpleNamespace:
        return SimpleNamespace(status="READY_FOR_MINI_SMOKE")

    def generate(self, request: Any) -> str:
        self.calls.append(request)
        return "measurement"


def _request(tmp_path: Path, **changes: Any) -> SimpleNamespace:
    values = {
        "prompt_id": EXPECTED_JOB["prompt_id"],
        "prompt": EXPECTED_JOB["prompt"],
        "seed_id": EXPECTED_JOB["seed_id"],
        "seed": EXPECTED_JOB["seed"],
        "duration_seconds": EXPECTED_JOB["duration_seconds"],
        "lyrics": EXPECTED_JOB["lyrics"],
        "output_path": tmp_path / EXPECTED_JOB["output_relative_path"],
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _claiming_adapter(
    tmp_path: Path,
    delegate: _FakeDelegate,
    *,
    identity_probe: Any = lambda: {"checkpoint": "bound", "source": "bound"},
) -> tuple[OneCallClaimingAdapter, DurableLog]:
    claim_dir = tmp_path / "claims"
    claim_dir.mkdir(parents=True)
    logger = DurableLog(tmp_path / "events.jsonl")
    adapter = OneCallClaimingAdapter(
        delegate,
        job=EXPECTED_JOB,
        output_path=tmp_path / EXPECTED_JOB["output_relative_path"],
        claim_dir=claim_dir,
        claim_context={"global_claim_sha256": "b" * 64},
        placement={
            "minimum_free_memory_before_claim_mib": 60_000,
            "max_idle_utilization_percent": 5,
            "required_gpu_name_substring": "A800",
        },
        physical_gpu_id=7,
        deadline_monotonic=float("inf"),
        logger=logger,
        gpu_probe=lambda *_args, **_kwargs: {"checks": {"safe": True}},
        behavior_identity_probe=identity_probe,
    )
    return adapter, logger


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_id", "wrong"),
        ("prompt", "wrong"),
        ("seed_id", "S-9999"),
        ("seed", 1),
        ("duration_seconds", 29.0),
        ("lyrics", "not empty"),
        ("output_path", Path("/tmp/wrong-output.wav")),
    ],
)
def test_claiming_adapter_rejects_every_request_mismatch_before_delegate(
    tmp_path: Path, field: str, value: Any
) -> None:
    delegate = _FakeDelegate()
    adapter, logger = _claiming_adapter(tmp_path, delegate)
    try:
        with pytest.raises(B2ExecutionError, match="exact S-0009"):
            adapter.generate(_request(tmp_path, **{field: value}))
    finally:
        logger.close()
    assert delegate.calls == []
    assert not (tmp_path / "claims" / "call-00.claim.json").exists()


def test_identity_or_claim_collision_never_reaches_delegate(tmp_path: Path) -> None:
    delegate = _FakeDelegate()

    def fail_identity() -> dict[str, Any]:
        raise B2GateError("identity mismatch")

    adapter, logger = _claiming_adapter(
        tmp_path / "identity", delegate, identity_probe=fail_identity
    )
    try:
        with pytest.raises(B2GateError, match="identity"):
            adapter.generate(_request(tmp_path / "identity"))
    finally:
        logger.close()
    assert delegate.calls == []

    collision_root = tmp_path / "collision"
    delegate = _FakeDelegate()
    adapter, logger = _claiming_adapter(collision_root, delegate)
    (collision_root / "claims" / "call-00.claim.json").write_text("occupied\n", encoding="utf-8")
    try:
        with pytest.raises(FileExistsError):
            adapter.generate(_request(collision_root))
    finally:
        logger.close()
    assert delegate.calls == []


def test_successful_fake_claim_is_exclusive_and_retry_is_refused(tmp_path: Path) -> None:
    delegate = _FakeDelegate()
    adapter, logger = _claiming_adapter(tmp_path, delegate)
    request = _request(tmp_path)
    try:
        assert adapter.generate(request) == "measurement"
        claim = json.loads((tmp_path / "claims" / "call-00.claim.json").read_text())
        assert claim["request"]["seed_id"] == "S-0009"
        assert claim["original_b2_call_index"] == 1
        with pytest.raises(B2ExecutionError, match="retry forbidden"):
            adapter.generate(request)
    finally:
        logger.close()
    assert delegate.calls == [request]


def test_one_row_ledger_is_canonical_strict_and_tamper_evident(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    row = _append_ledger_row(ledger, {"status": "PASS", "value": 1})
    verified = validate_one_row_ledger(ledger)
    assert verified["row"] == row

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        '{"previous_row_sha256":"' + "0" * 64 + '","value":1,"value":2}\n',
        encoding="utf-8",
    )
    with pytest.raises(B2ExecutionError, match="duplicate"):
        validate_one_row_ledger(duplicate)

    ledger.write_bytes(ledger.read_bytes() + ledger.read_bytes())
    with pytest.raises(B2ExecutionError, match="one complete row"):
        validate_one_row_ledger(ledger)


def test_template_is_inert_and_in_repo_completed_auth_is_rejected() -> None:
    config, hashes = validate_static_config()
    template = REPOSITORY_ROOT / config["authorization"]["template"]["path"]
    assert read_json(template)["execution_authorized"] is not True
    with pytest.raises(B2GateError, match="outside the repository"):
        validate_external_authorization(template, config=config, hashes=hashes)


def test_completed_external_authorization_binds_live_package_and_latest_decisions(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    paths = {
        *EXPECTED_FROZEN_PATHS.values(),
        "configs/b2_ace_duration_confirmation_v1.json",
        "BENCHMARK_PREREG_v2.md",
    }
    for relative in paths:
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)

    config, hashes = validate_static_config(
        repository / "configs/b2_ace_duration_confirmation_v1.json",
        repository_root=repository,
    )
    now = datetime.now(timezone.utc)
    commit = "a" * 40
    frozen_paths = {
        **EXPECTED_FROZEN_PATHS,
        "confirmation_config": "configs/b2_ace_duration_confirmation_v1.json",
        "benchmark_prereg_v2": "BENCHMARK_PREREG_v2.md",
    }
    authorization = {
        "schema_version": 1,
        "authorization_id": "B2-ACE-V1-DURATION-CONFIRMATION-V1-ONE-SHOT",
        "scope": "ACE_STEP_V1_DURATION_CONFIRMATION_NON_BENCHMARK",
        "execution_authorized": True,
        "benchmark_endpoint": False,
        "required_prereg_status": "FROZEN_PROSPECTIVE_DESIGN",
        "run_id": "b2-ace-v1-duration-confirmation-v1-001",
        "authorized_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "caps": EXPECTED_AUTHORIZATION_CAPS,
        "duration_policy": EXPECTED_DURATION_POLICY,
        "prior_consumed_evidence": config["prior_consumed_evidence"],
        "reserved_non_benchmark_seeds": [
            {
                "prompt_id": EXPECTED_JOB["prompt_id"],
                "seed": EXPECTED_JOB["seed"],
                "seed_id": EXPECTED_JOB["seed_id"],
            }
        ],
        "runtime_environment": config["runtime_environment"],
        "source_bindings": config["source_bindings"],
        "placement": {
            "node": "an12",
            "physical_gpu_id": 7,
            "placement_justification": "test-only exact TP1/R1 placement",
            "tensor_parallel_width": 1,
            "replica_count": 1,
        },
        "origin": {
            "branch": "main",
            "commit": commit,
            "remote_tracking_ref": "origin/main",
        },
        "frozen_artifacts": {
            name: {"path": relative, "sha256": sha256_file(repository / relative)}
            for name, relative in frozen_paths.items()
        },
    }
    expected = _expected_decisions_assignments(config, hashes, authorization)
    decisions = repository / "DECISIONS.md"
    decisions.write_text(
        "# Test decisions\n\n"
        + "\n".join(f"`{name} = {value}`" for name, value in expected.items())
        + "\n",
        encoding="utf-8",
    )
    authorization["decisions_sha256"] = sha256_file(decisions)
    authorization_path = tmp_path / "external-authorization.json"
    authorization_path.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validated, evidence = validate_external_authorization(
        authorization_path,
        config=config,
        hashes=hashes,
        repository_root=repository,
        runner_path=repository / EXPECTED_FROZEN_PATHS["confirmation_runner"],
        now=now,
        git_evidence={
            "branch": "main",
            "head": commit,
            "origin_main": commit,
            "clean": True,
            "status_porcelain_v1": [],
        },
    )
    assert validated["execution_authorized"] is True
    assert evidence["decisions_sha256"] == authorization["decisions_sha256"]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_wrapper_command_is_exactly_one_call_and_unique_paths(tmp_path: Path) -> None:
    config, _ = validate_static_config()
    authorization = tmp_path / "authorization.json"
    authorization.write_text("{}\n", encoding="utf-8")
    commands = expected_outer_commands(
        config=config,
        config_path=DEFAULT_CONFIG,
        authorization_path=authorization,
    )
    timeout = commands["outer_timeout_command"]
    assert timeout[:4] == ["/usr/bin/timeout", "-k", "30s", "1800s"]
    assert (
        timeout.count("I_UNDERSTAND_THIS_MAKES_EXACTLY_ONE_ACE_DURATION_CONFIRMATION_MODEL_CALL")
        == 1
    )
    assert "run_b2_mini_smoke_v2.py" not in " ".join(timeout)
    assert config["run"]["fixed_run_id"] != "b2-ace-v1-mini-smoke-v2-001"


def test_preclaim_failure_and_consumed_failure_have_exclusive_terminal_states(
    tmp_path: Path,
) -> None:
    preflight = terminal_failure_record(
        B2GateError("refused"), claim_root=tmp_path / "claims", run_root=tmp_path / "runs"
    )
    assert preflight["status"] == "REFUSED_PREFLIGHT"
    assert preflight["model_call_count"] == 0

    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "b2-ace-v1-duration-confirmation-v1-authorized-attempt.claim.json").write_text(
        "{}\n", encoding="utf-8"
    )
    consumed = terminal_failure_record(
        RuntimeError("new failure"), claim_root=claims, run_root=tmp_path / "runs"
    )
    assert consumed["status"] == "BLOCKED_ON_ENGINEERING_FAILURE"
    assert consumed["authorization_attempt_claim_consumed"] is True
    assert consumed["global_claim_consumed"] is False
    assert consumed["no_retry"] is True


def test_valid_authorization_attempt_is_durable_exclusive_and_terminal(tmp_path: Path) -> None:
    config, hashes = validate_static_config()
    claims = tmp_path / "claims"
    authorization = tmp_path / "authorization.json"
    authorization.write_text("{}\n", encoding="utf-8")
    evidence = consume_authorized_attempt(
        claim_root=claims,
        config=config,
        hashes=hashes,
        authorization={"placement": {"node": "an12", "physical_gpu_id": 7}},
        authorization_path=authorization,
        governance={"decisions_sha256": "a" * 64, "git": {"head": "b" * 40}},
    )
    assert Path(evidence["path"]).is_file()
    assert sha256_file(evidence["path"]) == evidence["sha256"]
    with pytest.raises(FileExistsError):
        consume_authorized_attempt(
            claim_root=claims,
            config=config,
            hashes=hashes,
            authorization={"placement": {"node": "an12", "physical_gpu_id": 7}},
            authorization_path=authorization,
            governance={"decisions_sha256": "a" * 64, "git": {"head": "b" * 40}},
        )
    terminal = terminal_failure_record(
        AuthorizedConfirmationFailure("preflight failed"),
        claim_root=claims,
        run_root=tmp_path / "runs",
    )
    assert terminal["status"] == "BLOCKED_ON_ENGINEERING_FAILURE"
    assert terminal["authorization_attempt_claim_consumed"] is True

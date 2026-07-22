from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.run_b2_mini_smoke_v2 import (
    DEFAULT_CONFIG,
    DEFAULT_RUNNER,
    EXPECTED_SEEDS,
    REPOSITORY_ROOT,
    B2ExecutionError,
    B2GateError,
    ClaimingAdapter,
    DurableLog,
    _canonical_json,
    _expected_decisions_assignments,
    _latest_assignment,
    capture_outer_timeout_boundary,
    exclusive_write_json,
    expected_outer_commands,
    probe_gpu,
    sha256_file,
    terminal_failure_record,
    validate_external_authorization,
    validate_ledger_chain,
    validate_static_config,
)
from tests.seed_registry_history import (
    AUTHORIZED_S0010_SUFFIX,
    AUTHORIZED_SAO_SUFFIX,
    FROZEN_B2_SEED_REGISTRY_SHA256,
    frozen_b2_seed_registry_prefix,
)


def test_live_append_only_registry_preserves_b2_prefix_but_consumed_package_refuses_it() -> None:
    registry = REPOSITORY_ROOT / "SEED_REGISTRY.md"
    payload = registry.read_bytes()
    prefix = frozen_b2_seed_registry_prefix(registry)
    assert hashlib.sha256(prefix).hexdigest() == FROZEN_B2_SEED_REGISTRY_SHA256
    assert payload[len(prefix) :] == AUTHORIZED_S0010_SUFFIX + AUTHORIZED_SAO_SUFFIX
    assert sha256_file(registry) != FROZEN_B2_SEED_REGISTRY_SHA256
    with pytest.raises(B2GateError, match="frozen_sources.seed_registry SHA-256 mismatch"):
        validate_static_config()


def test_static_package_is_exactly_two_unscored_30_second_registered_seed_jobs(
    tmp_path: Path,
) -> None:
    config, hashes = _copy_static_package(tmp_path)
    assert config["scoring"] == {
        "benchmark_endpoints_scored": False,
        "human_packet_member": False,
        "instrument_evaluation_allowed": False,
    }
    assert config["caps"]["exact_model_calls"] == 2
    assert config["caps"]["max_model_calls"] == 2
    assert config["caps"]["max_retries"] == 0
    assert config["caps"]["shared_b2_generation_ceiling"] == 10
    assert config["placement"]["minimum_free_memory_before_claim_mib"] >= 60_000
    assert config["placement"]["minimum_free_memory_before_subsequent_call_mib"] >= 16_000
    assert [(job["seed_id"], job["seed"], job["prompt_id"]) for job in config["jobs"]] == list(
        EXPECTED_SEEDS
    )
    assert all(job["duration_seconds"] == 30.0 for job in config["jobs"])
    assert hashes["seed_registry"] == FROZEN_B2_SEED_REGISTRY_SHA256


def test_committed_authorization_template_is_inert(tmp_path: Path) -> None:
    config, hashes = _copy_static_package(tmp_path)
    template = tmp_path / config["authorization"]["template"]["path"]
    with pytest.raises(B2GateError, match="template|placeholder"):
        validate_external_authorization(
            template,
            config=config,
            hashes=hashes,
            git_evidence={
                "branch": "main",
                "head": "a" * 40,
                "origin_main": "a" * 40,
                "clean": True,
                "status_porcelain_v1": [],
            },
        )


def test_latest_assignment_does_not_accept_an_earlier_yes() -> None:
    text = """
`B2_MINI_SMOKE_V2_AUTHORIZED = YES`
later prose
`B2_MINI_SMOKE_V2_AUTHORIZED = NO`
"""
    assert _latest_assignment(text, "B2_MINI_SMOKE_V2_AUTHORIZED") == "NO"


def _copy_static_package(destination: Path) -> tuple[dict[str, Any], dict[str, str]]:
    paths = [
        "configs/b2_mini_smoke_v2.json",
        "configs/backbones/ace_step_v1.json",
        "B2_MINI_SMOKE_PROTOCOL_v2.md",
        "provenance/b2/b2_mini_smoke_authorization.template.json",
        "src/backbones/ace_step_v1.py",
        "src/backbones/__init__.py",
        "src/backbones/contracts.py",
        "src/backbones/factory.py",
        "src/backbones/io.py",
        "src/backbones/mini_smoke.py",
        "src/backbones/runtime.py",
        "src/sa3_smoke/artifacts.py",
        "src/sa3_smoke/audio.py",
        "scripts/run_b2_mini_smoke_v2.py",
        "scripts/run_b2_mini_smoke_v2_with_timeout.py",
        "SEED_REGISTRY.md",
    ]
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / relative, target)
    registry = destination / "SEED_REGISTRY.md"
    registry.write_bytes(frozen_b2_seed_registry_prefix(REPOSITORY_ROOT / "SEED_REGISTRY.md"))
    (destination / "scripts" / "run_b2_mini_smoke_v2_with_timeout.py").chmod(0o755)
    (destination / "prompts" / "v2").mkdir(parents=True)
    return validate_static_config(
        destination / "configs" / "b2_mini_smoke_v2.json",
        repository_root=destination,
    )


def _valid_authorization_fixture(
    repository: Path,
    config: dict[str, Any],
    hashes: dict[str, str],
    *,
    now: datetime,
) -> Path:
    prereg = repository / "BENCHMARK_PREREG_v2.md"
    prereg.write_text(
        "# frozen-by-decision test prereg\n\n"
        "- Status: `FROZEN_PROSPECTIVE_DESIGN`\n"
        "- `BENCHMARK_PREREG_V2_FROZEN = YES`\n",
        encoding="utf-8",
    )
    template_path = repository / config["authorization"]["template"]["path"]
    authorization = json.loads(template_path.read_text(encoding="utf-8"))
    authorization.update(
        {
            "authorized_at_utc": (now - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
            "execution_authorized": True,
            "runtime_environment": config["runtime_environment"],
        }
    )
    commit = "a" * 40
    authorization["origin"]["commit"] = commit
    authorization["placement"]["node"] = "an12"
    authorization["placement"]["physical_gpu_id"] = 7
    replacements = {
        "authorization_template": hashes["authorization_template"],
        "benchmark_prereg_v2": sha256_file(prereg),
        "b2_config": hashes["b2_config"],
        "b2_runner": sha256_file(repository / "scripts" / "run_b2_mini_smoke_v2.py"),
    }
    for name, digest in replacements.items():
        authorization["frozen_artifacts"][name]["sha256"] = digest
    authorization["frozen_artifacts"]["benchmark_prereg_v2"]["path"] = "BENCHMARK_PREREG_v2.md"
    expected = _expected_decisions_assignments(config, hashes, authorization)
    decisions = repository / "DECISIONS.md"
    decisions.write_text(
        "# Decisions\n\n"
        + "\n".join(f"`{key} = {value}`" for key, value in expected.items())
        + "\n",
        encoding="utf-8",
    )
    authorization["decisions_sha256"] = sha256_file(decisions)
    authorization_path = repository / "external-authorization.json"
    authorization_path.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return authorization_path


def test_completed_authorization_binds_clean_origin_but_not_a_decisions_self_hash(
    tmp_path: Path,
) -> None:
    config, hashes = _copy_static_package(tmp_path)
    now = datetime.now(timezone.utc)
    authorization_path = _valid_authorization_fixture(tmp_path, config, hashes, now=now)
    git = {
        "branch": "main",
        "head": "a" * 40,
        "origin_main": "a" * 40,
        "clean": True,
        "status_porcelain_v1": [],
    }
    authorization, evidence = validate_external_authorization(
        authorization_path,
        config=config,
        hashes=hashes,
        repository_root=tmp_path,
        runner_path=tmp_path / "scripts" / "run_b2_mini_smoke_v2.py",
        now=now,
        git_evidence=git,
    )
    assert authorization["origin"]["commit"] == git["head"]
    assert (
        "B2_MINI_SMOKE_V2_ORIGIN_COMMIT"
        not in config["authorization"]["required_decisions_assignments"]
    )
    assert evidence["git"]["head"] == evidence["git"]["origin_main"]


def test_dirty_or_non_origin_worktree_refuses_before_execution(tmp_path: Path) -> None:
    config, hashes = _copy_static_package(tmp_path)
    now = datetime.now(timezone.utc)
    authorization_path = _valid_authorization_fixture(tmp_path, config, hashes, now=now)
    with pytest.raises(B2GateError, match="not clean"):
        validate_external_authorization(
            authorization_path,
            config=config,
            hashes=hashes,
            repository_root=tmp_path,
            runner_path=tmp_path / "scripts" / "run_b2_mini_smoke_v2.py",
            now=now,
            git_evidence={
                "branch": "main",
                "head": "a" * 40,
                "origin_main": "a" * 40,
                "clean": False,
                "status_porcelain_v1": ["?? stray"],
            },
        )


@pytest.mark.parametrize(
    ("prereg_text", "message"),
    [
        (
            "# prereg\n\n- Status: `ADJUDICATED_DESIGN_READY_FOR_FREEZE_DECISION`\n"
            "- `BENCHMARK_PREREG_V2_FROZEN = YES`\n",
            "status is not frozen",
        ),
        (
            "# prereg\n\n- Status: `FROZEN_PROSPECTIVE_DESIGN`\n"
            "- `BENCHMARK_PREREG_V2_FROZEN = NO`\n",
            "frozen marker YES",
        ),
    ],
)
def test_authorization_rechecks_live_prereg_status_and_self_marker(
    tmp_path: Path, prereg_text: str, message: str
) -> None:
    config, hashes = _copy_static_package(tmp_path)
    now = datetime.now(timezone.utc)
    authorization_path = _valid_authorization_fixture(tmp_path, config, hashes, now=now)
    prereg = tmp_path / "BENCHMARK_PREREG_v2.md"
    prereg.write_text(prereg_text, encoding="utf-8")
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["frozen_artifacts"]["benchmark_prereg_v2"]["sha256"] = sha256_file(prereg)
    expected = _expected_decisions_assignments(config, hashes, authorization)
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# Decisions\n\n"
        + "\n".join(f"`{key} = {value}`" for key, value in expected.items())
        + "\n",
        encoding="utf-8",
    )
    authorization["decisions_sha256"] = sha256_file(decisions)
    authorization_path.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(B2GateError, match=message):
        validate_external_authorization(
            authorization_path,
            config=config,
            hashes=hashes,
            repository_root=tmp_path,
            runner_path=tmp_path / "scripts" / "run_b2_mini_smoke_v2.py",
            now=now,
            git_evidence={
                "branch": "main",
                "head": "a" * 40,
                "origin_main": "a" * 40,
                "clean": True,
                "status_porcelain_v1": [],
            },
        )


def _fake_nvidia_smi(neighbor_pid: int | None = None):
    def run(command: list[str] | tuple[str, ...]) -> str:
        if "--query-gpu=index,uuid,name,memory.free,memory.total,utilization.gpu" in command:
            return "7, GPU-test, NVIDIA A800-SXM4-80GB, 81200, 81920, 0\n"
        if neighbor_pid is None:
            return ""
        return f"GPU-test, {neighbor_pid}, 1024\n"

    return run


def test_gpu_probe_requires_headroom_and_rejects_neighbor_without_preemption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "7")
    passed = probe_gpu(
        7,
        minimum_free_mib=60_000,
        maximum_utilization_percent=5,
        required_name_substring="A800",
        allowed_compute_pids=set(),
        command_runner=_fake_nvidia_smi(),
    )
    assert passed["checks"]["no_neighbor_compute_process"] is True
    with pytest.raises(B2GateError, match="neighbor"):
        probe_gpu(
            7,
            minimum_free_mib=60_000,
            maximum_utilization_percent=5,
            required_name_substring="A800",
            allowed_compute_pids=set(),
            command_runner=_fake_nvidia_smi(987654),
        )


class _FakeDelegate:
    model_id = "test/fake"
    logical_name = "fake"
    config_sha256 = "a" * 64
    license_identifier = "test-only"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def preflight(self) -> SimpleNamespace:
        return SimpleNamespace(status="READY_FOR_MINI_SMOKE")

    def generate(self, request: Any) -> str:
        self.calls.append(request.prompt_id)
        return "fake-measurement"


def test_each_fake_call_gets_fsynced_exclusive_claim_and_retry_is_refused(
    tmp_path: Path,
) -> None:
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    delegate = _FakeDelegate()
    claim_dir = tmp_path / "claims"
    claim_dir.mkdir()
    logger = DurableLog(tmp_path / "events.jsonl")

    def fake_probe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"checks": {"safe": True}}

    identity_calls: list[int] = []

    def fake_identity() -> dict[str, Any]:
        identity_calls.append(len(identity_calls))
        return {"checkpoint_tree": "bound", "source_tree": "bound"}

    wrapped = ClaimingAdapter(
        delegate,
        jobs=config["jobs"],
        claim_dir=claim_dir,
        claim_context={"global_claim_sha256": "b" * 64},
        placement=config["placement"],
        physical_gpu_id=7,
        deadline_monotonic=float("inf"),
        logger=logger,
        gpu_probe=fake_probe,
        behavior_identity_probe=fake_identity,
    )
    requests = [
        SimpleNamespace(
            prompt_id=job["prompt_id"],
            seed_id=job["seed_id"],
            seed=job["seed"],
            duration_seconds=job["duration_seconds"],
            output_path=tmp_path / job["output_relative_path"],
        )
        for job in config["jobs"]
    ]
    assert wrapped.generate(requests[0]) == "fake-measurement"
    assert (claim_dir / "call-00.claim.json").is_file()
    assert wrapped.generate(requests[1]) == "fake-measurement"
    assert (claim_dir / "call-01.claim.json").is_file()
    with pytest.raises(B2ExecutionError, match="retry forbidden"):
        wrapped.generate(requests[0])
    logger.close()
    assert delegate.calls == [job["prompt_id"] for job in config["jobs"]]
    assert identity_calls == [0, 1]
    second_claim = json.loads((claim_dir / "call-01.claim.json").read_text(encoding="utf-8"))
    assert second_claim["immediate_behavior_identity"]["checkpoint_tree"] == "bound"


def test_exclusive_claim_write_fsyncs_file_and_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    exclusive_write_json(tmp_path / "claim.json", {"claim": 1})
    assert any(stat.S_ISREG(mode) for mode in modes)
    assert any(stat.S_ISDIR(mode) for mode in modes)


def test_ledger_hash_chain_validator_detects_tampering(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    previous = "0" * 64
    lines: list[str] = []
    for index in range(2):
        unhashed = {"index": index, "previous_row_sha256": previous}
        digest = hashlib.sha256(_canonical_json(unhashed)).hexdigest()
        row = {**unhashed, "row_sha256": digest}
        lines.append(json.dumps(row, sort_keys=True))
        previous = digest
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert validate_ledger_chain(ledger)["ledger_tail_sha256"] == previous
    tampered = json.loads(lines[1])
    tampered["index"] = 99
    ledger.write_text(lines[0] + "\n" + json.dumps(tampered) + "\n", encoding="utf-8")
    with pytest.raises(B2ExecutionError, match="row SHA-256"):
        validate_ledger_chain(ledger)


def test_runner_source_has_no_generation_at_import_and_requires_exact_phrase() -> None:
    source = DEFAULT_RUNNER.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__"' in source
    assert "required_execute_phrase" in source
    assert "AceStepV1Adapter(" in source
    assert source.index("def execute_b2_mini_smoke") < source.index("AceStepV1Adapter(")


def test_frozen_wrapper_builds_exact_gnu_timeout_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.run_b2_mini_smoke_v2_with_timeout as wrapper

    authorization = tmp_path / "authorization.json"
    authorization.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(wrapper.sys, "executable", str(wrapper.PYTHON_PATH))
    production, timeout = wrapper.build_commands(
        config_path=wrapper.CONFIG_PATH,
        authorization_path=authorization,
        run_id=wrapper.FIXED_RUN_ID,
        execute_phrase=wrapper.EXECUTE_PHRASE,
    )
    assert production[0:2] == [str(wrapper.PYTHON_PATH), str(wrapper.WRAPPER_PATH)]
    assert timeout[0:4] == ["/usr/bin/timeout", "-k", "30s", "1800s"]
    assert timeout[4:8] == [
        str(wrapper.PYTHON_PATH),
        "-B",
        "-X",
        f"pycache_prefix={wrapper.PYCACHE_PREFIX}",
    ]
    refusal = wrapper._terminal_refusal(RuntimeError("test"))
    assert refusal["status"] == "REFUSED_PREFLIGHT"
    assert refusal["MEASUREMENT_STATUS"] == "NOT_MEASURED_NO_MODEL_CALL"
    assert refusal["model_call_count"] == 0


def test_runner_proves_parent_timeout_argv_and_records_both_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _hashes = _copy_static_package(tmp_path / "historical-package")
    authorization = tmp_path / "authorization.json"
    authorization.write_text("{}\n", encoding="utf-8")
    commands = expected_outer_commands(
        config=config,
        config_path=DEFAULT_CONFIG,
        authorization_path=authorization,
    )
    wrapper_path = REPOSITORY_ROOT / config["outer_timeout"]["wrapper"]["path"]
    monkeypatch.setenv(
        "B2_OUTER_PRODUCTION_COMMAND_JSON",
        json.dumps(commands["production_wrapper_command"], separators=(",", ":")),
    )
    monkeypatch.setenv(
        "B2_OUTER_TIMEOUT_COMMAND_JSON",
        json.dumps(commands["outer_timeout_command"], separators=(",", ":")),
    )
    monkeypatch.setenv("B2_PRODUCTION_WRAPPER_PATH", str(wrapper_path.resolve()))
    monkeypatch.setenv("B2_PRODUCTION_WRAPPER_SHA256", sha256_file(wrapper_path))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setattr("sys.dont_write_bytecode", True)
    monkeypatch.setattr("sys.pycache_prefix", config["outer_timeout"]["pycache_prefix"])
    evidence = capture_outer_timeout_boundary(
        config=config,
        config_path=DEFAULT_CONFIG,
        authorization_path=authorization,
        parent_pid=123,
        proc_executable="/usr/bin/timeout",
        proc_command=commands["outer_timeout_command"],
        timeout_version="timeout (GNU coreutils) 9.1",
    )
    assert evidence["parent_argv"] == commands["outer_timeout_command"]
    assert evidence["outer_timeout_command_shell"].startswith("/usr/bin/timeout -k 30s 1800s")


def test_standard_terminal_preflight_record_is_exactly_zero_before_claim(tmp_path: Path) -> None:
    record = terminal_failure_record(
        B2GateError("test refusal"),
        claim_root=tmp_path / "claims",
        run_root=tmp_path / "runs",
    )
    assert record["status"] == "REFUSED_PREFLIGHT"
    assert record["MEASUREMENT_STATUS"] == "NOT_MEASURED_NO_MODEL_CALL"
    assert record["global_claim_consumed"] is False
    assert record["model_call_count"] == 0
    assert record["generated_output_count"] == 0


def test_committed_ace_checkpoint_binding_is_full_tree_without_exclusions() -> None:
    config = json.loads(
        (REPOSITORY_ROOT / "configs/backbones/ace_step_v1.json").read_text(encoding="utf-8")
    )
    checkpoint = config["checkpoint"]
    paths = [row["path"] for row in checkpoint["required_files"]]
    assert len(paths) == 17
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert "ace_step_transformer/config.json" in paths
    assert "music_dcae_f8c8/config.json" in paths
    assert "music_vocoder/config.json" in paths
    assert "umt5-base/tokenizer.json" in paths
    assert "umt5-base/tokenizer_config.json" in paths
    assert checkpoint["content_identity"] == "exact_full_tree_sha256_no_exclusions"
    assert checkpoint["exact_tree_sha256"] == (
        "124f8267d6c19f992e8b79880cc59e1ec1104439e6150312ebc94d7563d260fc"
    )

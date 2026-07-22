from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest

import backbones.sao_acquisition as acquisition_module
from backbones.contracts import DEFAULT_SAO_CONFIG, sha256_file
from backbones.license_gate import validate_access_receipt
from backbones.sao_acquisition import (
    EXECUTE_ACK,
    RECOVERY_REVISION,
    RECOVERY_RUN_ID,
    RECOVERY_SOURCE_RUN_ID,
    SaoAcquisitionError,
    acquire_snapshot,
    finalize_retained_acquisition_recovery,
)

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
TOKEN_SENTINEL = "TEST_CREDENTIAL_SENTINEL_MUST_NEVER_PERSIST"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _config(tmp_path: Path) -> Path:
    source = json.loads((ROOT / "configs" / "sao_live_v2.json").read_text(encoding="utf-8"))
    source["acquisition"]["run_root"] = str(tmp_path / "runs")
    source["acquisition"]["snapshot_root"] = str(tmp_path / "models")
    path = tmp_path / "config.json"
    _write_json(path, source)
    return path


def _decisions(tmp_path: Path, config: Path) -> Path:
    path = tmp_path / "DECISIONS.md"
    path.write_text(
        "\n".join(
            (
                "## D-0037 — fixture",
                "SAO_ACQUISITION_AUTHORIZED = YES",
                "SAO_MINI_SMOKE_EXACT_CALLS = 3",
                "SAO_CORE_EXACT_ROWS = 1536",
                "SAO_STATE_CAPABILITY = NOT_ATTEMPTED",
                "SAO_ELIGIBILITY_SCOPE_EXPANDED = NO",
                f"SAO_LIVE_CONFIG_SHA256 = {sha256_file(config)}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def _download(**kwargs) -> str:
    assert kwargs["repo_id"] == "stabilityai/stable-audio-open-1.0"
    assert kwargs["revision"] == REVISION
    assert kwargs["token"] == TOKEN_SENTINEL
    root = Path(kwargs["local_dir"])
    root.mkdir(parents=True)
    (root / "model_config.json").write_text("{}\n", encoding="utf-8")
    (root / "model.safetensors").write_bytes(b"fixture-weight")
    (root / "model.ckpt").write_bytes(b"fixture-legacy-weight")
    (root / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    control = root / ".cache" / "huggingface"
    control.mkdir(parents=True)
    (control / "download.metadata").write_text("ephemeral\n", encoding="utf-8")
    return str(root)


class FakeApi:
    def model_info(self, repo_id: str, *, revision: str, token: str):
        assert repo_id == "stabilityai/stable-audio-open-1.0"
        assert revision == "main"
        assert token == TOKEN_SENTINEL
        return SimpleNamespace(sha=REVISION)


def test_acquisition_consumes_env_token_and_persists_only_nonsecret_receipt(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    decisions = _decisions(tmp_path, config)
    environment = {"HF_TOKEN": TOKEN_SENTINEL, "HTTPS_PROXY": "http://proxy.invalid"}
    result = acquire_snapshot(
        config,
        decisions,
        execute_ack=EXECUTE_ACK,
        accepted_by="PI",
        accepted_at_utc="2026-07-22T00:00:00Z",
        environment=environment,
        api_factory=FakeApi,
        snapshot_download_fn=_download,
    )
    assert result["status"] == "ACCESS_RECEIPT_VERIFIED_NO_GENERATION"
    assert result["model_calls"] == 0 and result["generated_audio"] == 0
    assert "HF_TOKEN" not in environment
    assert environment["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
    snapshot = Path(result["snapshot_dir"])
    assert not (snapshot / ".cache").exists()
    receipt = Path(result["access_receipt_path"])
    verified = validate_access_receipt(
        receipt,
        expected_model_id="stabilityai/stable-audio-open-1.0",
        expected_snapshot_dir=snapshot,
    )
    assert verified["resolved_provider_revision"] == REVISION
    assert {row["path"] for row in verified["verified_files"]}.issuperset(
        {"model.safetensors", "model.ckpt"}
    )
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert TOKEN_SENTINEL.encode() not in persisted


def test_missing_environment_token_refuses_before_provider_or_artifacts(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decisions = _decisions(tmp_path, config)
    called = False

    def api_factory():
        nonlocal called
        called = True
        return FakeApi()

    with pytest.raises(SaoAcquisitionError, match="HF_TOKEN is absent"):
        acquire_snapshot(
            config,
            decisions,
            execute_ack=EXECUTE_ACK,
            accepted_by="PI",
            accepted_at_utc="2026-07-22T00:00:00Z",
            environment={"HTTPS_PROXY": "http://proxy.invalid"},
            api_factory=api_factory,
            snapshot_download_fn=_download,
        )
    assert called is False
    assert not (tmp_path / "runs").exists()


def test_d0037_hash_binding_is_checked_before_token_consumption(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decisions = _decisions(tmp_path, config)
    config_value = json.loads(config.read_text(encoding="utf-8"))
    config_value["acquisition"]["max_download_workers"] = 3
    _write_json(config, config_value)
    environment = {"HF_TOKEN": TOKEN_SENTINEL, "HTTPS_PROXY": "http://proxy.invalid"}
    with pytest.raises(SaoAcquisitionError, match="SAO_LIVE_CONFIG_SHA256"):
        acquire_snapshot(
            config,
            decisions,
            execute_ack=EXECUTE_ACK,
            accepted_by="PI",
            accepted_at_utc="2026-07-22T00:00:00Z",
            environment=environment,
            api_factory=FakeApi,
            snapshot_download_fn=_download,
        )
    assert environment["HF_TOKEN"] == TOKEN_SENTINEL
    assert not (tmp_path / "runs").exists()


def test_production_config_stays_closed_and_binds_frozen_adapter() -> None:
    config = json.loads((ROOT / "configs" / "sao_live_v2.json").read_text(encoding="utf-8"))
    assert config["status"] == "CLOSED_UNTIL_D0037_LIVE_BINDING"
    assert config["backbone_config"]["sha256"] == sha256_file(DEFAULT_SAO_CONFIG)
    assert config["mini_smoke"]["seed_ids"] == ["S-0011", "S-0011", "S-0012"]
    assert config["core"]["state_capability"] == "NOT_ATTEMPTED"
    assert config["core"]["eligibility_scope_expanded"] is False


def test_provider_exception_cannot_expose_consumed_token(tmp_path: Path) -> None:
    config = _config(tmp_path)
    decisions = _decisions(tmp_path, config)
    environment = {"HF_TOKEN": TOKEN_SENTINEL, "HTTPS_PROXY": "http://proxy.invalid"}

    class LeakyApi:
        def model_info(self, _repo_id: str, *, revision: str, token: str):
            assert revision == "main" and token == TOKEN_SENTINEL
            raise RuntimeError(f"provider rejected Authorization: Bearer {token}")

    with pytest.raises(SaoAcquisitionError) as caught:
        acquire_snapshot(
            config,
            decisions,
            execute_ack=EXECUTE_ACK,
            accepted_by="PI",
            accepted_at_utc="2026-07-22T00:00:00Z",
            environment=environment,
            api_factory=LeakyApi,
            snapshot_download_fn=_download,
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert TOKEN_SENTINEL not in str(caught.value)
    assert TOKEN_SENTINEL not in rendered
    assert "HF_TOKEN" not in environment
    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert TOKEN_SENTINEL.encode() not in persisted


def _recovery_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    config = _config(tmp_path)
    config_value = json.loads(config.read_text(encoding="utf-8"))
    run_root = Path(config_value["acquisition"]["run_root"])
    snapshot_root = Path(config_value["acquisition"]["snapshot_root"])
    source_run = run_root / RECOVERY_SOURCE_RUN_ID
    source_run.mkdir(parents=True)
    stage = snapshot_root / f".{RECOVERY_SOURCE_RUN_ID}.partial"
    stage.mkdir(parents=True)
    (snapshot_root / ".sao-acquisition.lock").write_bytes(b"")
    (stage / "model_config.json").write_text("{}\n", encoding="utf-8")
    (stage / "model.safetensors").write_bytes(b"preferred-weight")
    (stage / "model.ckpt").write_bytes(b"legacy-weight")
    (stage / "LICENSE.md").write_text("fixture license\n", encoding="utf-8")
    nested = stage / "tokenizer"
    nested.mkdir()
    (nested / "tokenizer.json").write_text("{}\n", encoding="utf-8")

    started = "2026-07-22T08:25:24.996923Z"
    acquisition_manifest = source_run / "acquisition-manifest.json"
    _write_json(
        acquisition_manifest,
        {
            "schema_version": 1,
            "status": "STARTED_NO_MODEL_CALLS",
            "run_id": RECOVERY_SOURCE_RUN_ID,
            "started_at_utc": started,
            "node": "fixture-node",
            "command": (
                "scripts/acquire_sao_live_v2.py --config configs/sao_live_v2.json "
                "--decisions DECISIONS.md --accepted-by 'Fixture PI' "
                "--accepted-at-utc 2026-07-22T08:25:24Z --execute-ack fixture"
            ),
            "git_commit": "1" * 40,
            "live_config_path": str(config.resolve()),
            "live_config_sha256": sha256_file(config),
            "model_id": "stabilityai/stable-audio-open-1.0",
            "provider": "huggingface_hub",
            "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
            "gpu_count": 0,
            "model_calls": 0,
            "generated_audio": 0,
        },
    )
    monkeypatch.setattr(
        acquisition_module,
        "RECOVERY_ACQUISITION_MANIFEST_SHA256",
        sha256_file(acquisition_manifest),
    )
    failure = source_run / "terminal-failure.json"
    _write_json(
        failure,
        {
            "schema_version": 1,
            "status": "ACQUISITION_FAILED_STOPPED",
            "run_id": RECOVERY_SOURCE_RUN_ID,
            "started_at_utc": started,
            "finished_at_utc": "2026-07-22T08:41:41.717344Z",
            "error_type": "SaoAcquisitionError",
            "acquisition_manifest_path": str(acquisition_manifest.resolve()),
            "acquisition_manifest_sha256": sha256_file(acquisition_manifest),
            "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
            "partial_snapshot_retained": True,
            "model_calls": 0,
            "generated_audio": 0,
        },
    )
    failure_sha256 = sha256_file(failure)
    monkeypatch.setattr(
        acquisition_module,
        "RECOVERY_FAILURE_TERMINAL_SHA256",
        failure_sha256,
    )
    decisions = _decisions(tmp_path, config)
    decisions.write_text(
        decisions.read_text(encoding="utf-8")
        + "\n".join(
            (
                "## D-0039 — fixture retained-stage recovery",
                "SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES",
                f"SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID = {RECOVERY_SOURCE_RUN_ID}",
                f"SAO_ACQUISITION_RECOVERY_RUN_ID = {RECOVERY_RUN_ID}",
                f"SAO_ACQUISITION_RECOVERY_REVISION = {RECOVERY_REVISION}",
                "SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256 = "
                f"{failure_sha256}",
                "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO",
                "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO",
                "SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0",
                "",
            )
        ),
        encoding="utf-8",
    )
    return {
        "config": config,
        "decisions": decisions,
        "run_root": run_root,
        "snapshot_root": snapshot_root,
        "source_run": source_run,
        "stage": stage,
        "failure": failure,
    }


def _run_recovery(paths: dict[str, Path]) -> dict[str, object]:
    return finalize_retained_acquisition_recovery(
        paths["config"],
        paths["decisions"],
        command="scripts/finalize_sao_acquisition_recovery_v2.py --config fixture",
        git_commit="2" * 40,
    )


def test_retained_dual_format_stage_recovers_offline_and_preserves_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _recovery_fixture(tmp_path, monkeypatch)
    source_before = {
        path.name: path.read_bytes() for path in paths["source_run"].iterdir()
    }
    monkeypatch.setenv("HF_TOKEN", TOKEN_SENTINEL)

    result = _run_recovery(paths)

    assert os.environ["HF_TOKEN"] == TOKEN_SENTINEL
    assert result["status"] == "ACCESS_RECEIPT_RECOVERED_OFFLINE_NO_GENERATION"
    assert result["network_access"] is False
    assert result["token_access"] is False
    assert result["gpu_count"] == result["model_calls"] == result["generated_audio"] == 0
    assert result["original_failed_run_preserved"] is True
    assert {
        path.name: path.read_bytes() for path in paths["source_run"].iterdir()
    } == source_before
    final_snapshot = paths["snapshot_root"] / RECOVERY_REVISION
    assert final_snapshot.is_dir()
    assert not os.path.lexists(paths["stage"])
    assert (final_snapshot / "model.safetensors").read_bytes() == b"preferred-weight"
    assert (final_snapshot / "model.ckpt").read_bytes() == b"legacy-weight"
    manifest = json.loads(Path(result["snapshot_manifest_path"]).read_text(encoding="utf-8"))
    assert {row["path"] for row in manifest["files"]} == {
        "LICENSE.md",
        "model.ckpt",
        "model.safetensors",
        "model_config.json",
        "tokenizer/tokenizer.json",
    }
    verified = validate_access_receipt(
        Path(result["access_receipt_path"]),
        expected_model_id="stabilityai/stable-audio-open-1.0",
        expected_snapshot_dir=final_snapshot,
    )
    assert {row["path"] for row in verified["verified_files"]} == {
        row["path"] for row in manifest["files"]
    }
    assert {path.name for path in (paths["run_root"] / RECOVERY_RUN_ID).iterdir()} == {
        "access-receipt.json",
        "snapshot-manifest.json",
        "terminal.json",
    }


@pytest.mark.parametrize("forbidden", ["cache", "incomplete", "symlink"])
def test_recovery_rejects_control_residue_and_symlinks_without_moving_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forbidden: str,
) -> None:
    paths = _recovery_fixture(tmp_path, monkeypatch)
    if forbidden == "cache":
        residue = paths["stage"] / ".cache" / "huggingface"
        residue.mkdir(parents=True)
        (residue / "metadata").write_text("residue\n", encoding="utf-8")
        match = "provider cache"
    elif forbidden == "incomplete":
        (paths["stage"] / "model.safetensors.incomplete").write_bytes(b"partial")
        match = "incomplete entry"
    else:
        (paths["stage"] / "linked-weight").symlink_to(
            paths["stage"] / "model.safetensors"
        )
        match = "forbidden symlink"

    with pytest.raises(SaoAcquisitionError, match=match):
        _run_recovery(paths)
    assert paths["stage"].is_dir()
    assert not (paths["run_root"] / RECOVERY_RUN_ID).exists()
    assert not (paths["snapshot_root"] / RECOVERY_REVISION).exists()


def test_recovery_rejects_changed_failure_even_when_decision_hash_is_rebound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _recovery_fixture(tmp_path, monkeypatch)
    failure = json.loads(paths["failure"].read_text(encoding="utf-8"))
    failure["model_calls"] = 1
    _write_json(paths["failure"], failure)
    changed_sha = sha256_file(paths["failure"])
    monkeypatch.setattr(
        acquisition_module,
        "RECOVERY_FAILURE_TERMINAL_SHA256",
        changed_sha,
    )
    decisions_text = paths["decisions"].read_text(encoding="utf-8")
    decisions_text = re.sub(
        r"SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256 = [0-9a-f]{64}",
        f"SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256 = {changed_sha}",
        decisions_text,
    )
    paths["decisions"].write_text(decisions_text, encoding="utf-8")

    with pytest.raises(SaoAcquisitionError, match="failure terminal mismatch: model_calls"):
        _run_recovery(paths)
    assert paths["stage"].is_dir()
    assert not (paths["run_root"] / RECOVERY_RUN_ID).exists()


def test_recovery_rejects_wrong_d0039_assignment_before_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _recovery_fixture(tmp_path, monkeypatch)
    decisions = paths["decisions"].read_text(encoding="utf-8").replace(
        "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO",
        "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = YES",
    )
    paths["decisions"].write_text(decisions, encoding="utf-8")
    with pytest.raises(SaoAcquisitionError, match="TOKEN_ACCESS"):
        _run_recovery(paths)
    assert paths["stage"].is_dir()
    assert not (paths["run_root"] / RECOVERY_RUN_ID).exists()


def test_recovery_is_no_clobber_and_cannot_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _recovery_fixture(tmp_path, monkeypatch)
    first = _run_recovery(paths)
    terminal_before = Path(first["terminal_path"]).read_bytes()
    with pytest.raises(FileExistsError):
        _run_recovery(paths)
    assert Path(first["terminal_path"]).read_bytes() == terminal_before

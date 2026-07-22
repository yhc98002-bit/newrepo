from __future__ import annotations

import json
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest

from backbones.contracts import DEFAULT_SAO_CONFIG, sha256_file
from backbones.license_gate import validate_access_receipt
from backbones.sao_acquisition import (
    EXECUTE_ACK,
    SaoAcquisitionError,
    acquire_snapshot,
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

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backbones.contracts import DEFAULT_SAO_CONFIG, BackboneConfigurationError, LicenseGateBlocked
from backbones.license_gate import validate_access_receipt
from backbones.stable_audio_open import StableAudioOpenAdapter
from sa3_smoke.artifacts import sha256_file


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _access_fixture(tmp_path: Path) -> tuple[Path, Path]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"offline-test-snapshot")
    revision = "a" * 40
    manifest = tmp_path / "snapshot-manifest.json"
    _write_json(
        manifest,
        {
            "model_id": "stabilityai/stable-audio-open-1.0",
            "revision": revision,
            "files": [
                {
                    "path": "model.safetensors",
                    "size_bytes": weight.stat().st_size,
                    "sha256": sha256_file(weight),
                }
            ],
        },
    )
    receipt = tmp_path / "receipt.json"
    _write_json(
        receipt,
        {
            "schema_version": 1,
            "model_id": "stabilityai/stable-audio-open-1.0",
            "resolved_provider_revision": revision,
            "accepted_by": "PI",
            "accepted_at_utc": "2026-07-20T00:00:00Z",
            "user_confirmed_acceptance": True,
            "license_identifier": "human-reviewed-test-license",
            "license_text_sha256": "b" * 64,
            "snapshot_manifest_path": str(manifest),
            "snapshot_manifest_sha256": sha256_file(manifest),
        },
    )
    return snapshot, receipt


def test_sao_is_fail_closed_with_exact_human_steps(tmp_path: Path) -> None:
    adapter = StableAudioOpenAdapter(evidence_dir=tmp_path)
    with pytest.raises(LicenseGateBlocked) as caught:
        adapter.preflight()
    block = caught.value.as_dict()
    assert block["status"] == "BLOCKED_ON_LICENSE"
    assert block["model_id"] == "stabilityai/stable-audio-open-1.0"
    assert len(block["human_steps"]) == 7
    assert "https://huggingface.co/stabilityai/stable-audio-open-1.0" in block["human_steps"][1]
    assert not list(tmp_path.iterdir())


def test_sao_requires_receipt_and_separate_runtime_decision(tmp_path: Path) -> None:
    snapshot, receipt = _access_fixture(tmp_path)
    adapter = StableAudioOpenAdapter(
        snapshot_dir=snapshot,
        access_receipt_path=receipt,
        evidence_dir=tmp_path / "evidence",
    )
    with pytest.raises(LicenseGateBlocked):
        adapter.preflight()


def test_sao_offline_receipt_and_runtime_gate_can_preflight(tmp_path: Path) -> None:
    snapshot, receipt = _access_fixture(tmp_path)
    config_sha = sha256_file(DEFAULT_SAO_CONFIG)
    authorization = tmp_path / "authorization.json"
    _write_json(
        authorization,
        {
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
            "decision_id": "D-TEST",
            "backbone_config_sha256": config_sha,
            "access_receipt_sha256": sha256_file(receipt),
            "max_generations": 1,
            "max_clip_seconds": 30,
            "max_gpus": 1,
        },
    )
    adapter = StableAudioOpenAdapter(
        snapshot_dir=snapshot,
        access_receipt_path=receipt,
        runtime_authorization_path=authorization,
        evidence_dir=tmp_path / "evidence",
    )
    preflight = adapter.preflight()
    assert preflight.status == "READY_FOR_MINI_SMOKE"
    assert preflight.details["receipt"]["verified_files"][0]["hash_verified"] is True
    assert preflight.details["runtime_authorization"]["decision_id"] == "D-TEST"


def test_access_receipt_rejects_secret_material(tmp_path: Path) -> None:
    snapshot, receipt = _access_fixture(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["hf_token"] = "must-never-be-recorded"
    _write_json(receipt, value)
    with pytest.raises(BackboneConfigurationError, match="secret-like field"):
        validate_access_receipt(
            receipt,
            expected_model_id="stabilityai/stable-audio-open-1.0",
            expected_snapshot_dir=snapshot,
        )

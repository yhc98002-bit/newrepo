from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import backbones.stable_audio_open as sao_module
from backbones.contracts import (
    DEFAULT_SAO_CONFIG,
    BackboneConfigurationError,
    BackbonePreflight,
    GenerationRequest,
    LicenseGateBlocked,
)
from backbones.license_gate import validate_access_receipt, validate_core_authorization
from backbones.sao_t5 import T5_BUNDLE_LAYOUT, conditioning_bundle_record
from backbones.stable_audio_open import StableAudioOpenAdapter
from sa3_smoke.artifacts import sha256_file


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_sao_t5_loader_fixture(snapshot: Path) -> list[dict[str, object]]:
    text_encoder = snapshot / "text_encoder"
    tokenizer = snapshot / "tokenizer"
    text_encoder.mkdir()
    tokenizer.mkdir()
    _write_json(
        text_encoder / "config.json",
        {
            "_name_or_path": "t5-base",
            "architectures": ["T5EncoderModel"],
            "d_model": 768,
            "model_type": "t5",
        },
    )
    (text_encoder / "model.safetensors").write_bytes(b"fixture-t5-encoder")
    _write_json(tokenizer / "special_tokens_map.json", {"eos_token": "</s>"})
    (tokenizer / "spiece.model").write_bytes(b"fixture-sentencepiece")
    _write_json(tokenizer / "tokenizer.json", {"version": "1.0"})
    _write_json(tokenizer / "tokenizer_config.json", {"tokenizer_class": "T5Tokenizer"})
    rows: list[dict[str, object]] = []
    for _bundle_name, relative in T5_BUNDLE_LAYOUT:
        path = snapshot / relative
        rows.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "hash_verified": True,
            }
        )
    return rows


def _sao_model_config() -> dict[str, object]:
    return {
        "model_type": "diffusion_cond",
        "model": {
            "conditioning": {
                "cond_dim": 768,
                "configs": [
                    {
                        "id": "prompt",
                        "type": "t5",
                        "config": {"t5_model_name": "t5-base", "max_length": 128},
                    },
                    {
                        "id": "seconds_start",
                        "type": "number",
                        "config": {"min_val": 0, "max_val": 512},
                    },
                ],
            }
        },
    }


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
            "decision_id": "D-0037",
            "backbone_config_sha256": config_sha,
            "access_receipt_sha256": sha256_file(receipt),
            "max_generations": 3,
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
    assert preflight.details["runtime_authorization"]["decision_id"] == "D-0037"


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


def test_access_receipt_requires_exact_snapshot_file_closure(tmp_path: Path) -> None:
    snapshot, receipt = _access_fixture(tmp_path)
    (snapshot / "unlisted.bin").write_bytes(b"not-in-the-receipt")
    with pytest.raises(BackboneConfigurationError, match="exact file closure"):
        validate_access_receipt(
            receipt,
            expected_model_id="stabilityai/stable-audio-open-1.0",
            expected_snapshot_dir=snapshot,
        )


def test_sao_mini_smoke_gate_requires_d0037_and_exactly_three_calls(tmp_path: Path) -> None:
    snapshot, receipt = _access_fixture(tmp_path)
    authorization = tmp_path / "authorization.json"
    _write_json(
        authorization,
        {
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
            "decision_id": "D-WRONG",
            "backbone_config_sha256": sha256_file(DEFAULT_SAO_CONFIG),
            "access_receipt_sha256": sha256_file(receipt),
            "max_generations": 3,
            "max_clip_seconds": 30,
            "max_gpus": 1,
        },
    )
    adapter = StableAudioOpenAdapter(
        snapshot_dir=snapshot,
        access_receipt_path=receipt,
        runtime_authorization_path=authorization,
    )
    with pytest.raises(BackboneConfigurationError, match="decision_id mismatch"):
        adapter.preflight()

    value = json.loads(authorization.read_text(encoding="utf-8"))
    value["decision_id"] = "D-0037"
    value["max_generations"] = 2
    _write_json(tmp_path / "authorization-two.json", value)
    adapter = StableAudioOpenAdapter(
        snapshot_dir=snapshot,
        access_receipt_path=receipt,
        runtime_authorization_path=tmp_path / "authorization-two.json",
    )
    with pytest.raises(BackboneConfigurationError, match="generation count mismatch"):
        adapter.preflight()


def test_core_authorization_cannot_enable_state_or_expand_eligibility(tmp_path: Path) -> None:
    record = {
        "schema_version": 1,
        "status": "ACCESS_AND_MINI_SMOKE_VERIFIED_CORE_AUTHORIZED",
        "scope": "SAO_BENCHMARK_CORE_GENERATION_ONLY",
        "decision_id": "D-0037",
        "backbone_config_sha256": "a" * 64,
        "access_receipt_sha256": "b" * 64,
        "mini_smoke_result_sha256": "c" * 64,
        "exact_generations": 1536,
        "max_clip_seconds": 30,
        "max_gpus_per_worker": 1,
        "state_capability": "NOT_ATTEMPTED",
        "eligibility_scope_expanded": False,
    }
    path = tmp_path / "core.json"
    _write_json(path, record)
    assert validate_core_authorization(
        path,
        expected_config_sha256="a" * 64,
        expected_receipt_sha256="b" * 64,
        expected_mini_smoke_result_sha256="c" * 64,
    )["exact_generations"] == 1536

    record["state_capability"] = "READY"
    _write_json(tmp_path / "state-enabled.json", record)
    with pytest.raises(BackboneConfigurationError, match="NOT_ATTEMPTED"):
        validate_core_authorization(
            tmp_path / "state-enabled.json",
            expected_config_sha256="a" * 64,
            expected_receipt_sha256="b" * 64,
            expected_mini_smoke_result_sha256="c" * 64,
        )


def test_sao_generation_freezes_exact_30s_signature_without_generator_kwarg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class Hook:
        def remove(self) -> None:
            return None

    class Diffusion:
        def register_forward_hook(self, callback):
            captured["hook_callback"] = callback
            return Hook()

    class Telemetry:
        def __init__(self, device: str) -> None:
            assert device == "cuda:0"

        @contextmanager
        def measured(self):
            yield {
                "wall_seconds": 1.25,
                "peak_allocated_bytes": 1024,
                "peak_reserved_bytes": 2048,
            }

    def fake_generate(model, **kwargs):
        captured.update(kwargs)
        captured["hook_callback"](None, None, None)
        return np.zeros((1, 2, 32), dtype=np.float32)

    monkeypatch.setattr(sao_module, "CudaTelemetry", Telemetry)
    monkeypatch.setitem(
        sys.modules,
        "stable_audio_tools.inference.generation",
        SimpleNamespace(generate_diffusion_cond=fake_generate),
    )
    adapter = StableAudioOpenAdapter(device="cuda:0")
    adapter._model = SimpleNamespace(model=Diffusion())
    adapter._weight_file_sha256 = "d" * 64
    adapter._preflight = BackbonePreflight(
        status="READY_FOR_MINI_SMOKE",
        model_id=adapter.model_id,
        config_sha256=adapter.config_sha256,
        details={"receipt": {"resolved_provider_revision": "e" * 40}},
    )
    output = tmp_path / "sample.wav"
    adapter.generate(
        GenerationRequest(
            prompt_id="sao-signature-test",
            prompt="A purely instrumental test passage",
            seed_id="S-TEST",
            seed=73193011,
            duration_seconds=30.0,
            output_path=output,
        )
    )
    assert captured["sample_size"] == 1_323_000
    assert captured["sample_rate"] == 44_100
    assert captured["seed"] == 73193011
    assert captured["device"] == "cuda:0"
    assert captured["adapt_duration_to_conditioning"] is False
    assert captured["batch_size"] == 1
    assert "generator" not in captured


def test_sao_loader_uses_only_receipt_bound_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    model_config_path = snapshot / "model_config.json"
    _write_json(model_config_path, _sao_model_config())
    original_config_bytes = model_config_path.read_bytes()
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"local-only-weight")
    checkpoint = snapshot / "model.ckpt"
    checkpoint.write_bytes(b"legacy-weight-must-not-load")
    t5_rows = _write_sao_t5_loader_fixture(snapshot)
    source_bytes = {
        relative: (snapshot / relative).read_bytes() for _bundle, relative in T5_BUNDLE_LAYOUT
    }
    observed: dict[str, object] = {}

    class Model:
        sample_rate = 44_100

        def load_state_dict(self, state) -> None:
            observed["state"] = state

        def to(self, device: str):
            observed["device"] = device
            return self

        def eval(self):
            observed["eval"] = True
            return self

    def fake_factory(config: dict[str, object]) -> Model:
        observed["offline_environment"] = {
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": os.environ.get(
                "HF_HUB_DISABLE_IMPLICIT_TOKEN"
            ),
        }
        assert not any(
            name in os.environ
            for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACEHUB_API_TOKEN")
        )
        resolved = config["model"]["conditioning"]["configs"][0]["config"]
        bundle = Path(str(resolved["model_path"]))
        assert bundle.is_absolute() and bundle.is_dir()
        assert {path.name for path in bundle.iterdir()} == {
            bundle_name for bundle_name, _source in T5_BUNDLE_LAYOUT
        }
        for bundle_name, relative in T5_BUNDLE_LAYOUT:
            linked = bundle / bundle_name
            assert linked.is_symlink()
            assert linked.resolve() == (snapshot / relative).resolve()
            assert linked.read_bytes() == source_bytes[relative]
        assert resolved == {
            "t5_model_name": "t5-base",
            "max_length": 128,
            "model_path": str(bundle),
        }
        observed["resolved_conditioner"] = dict(resolved)
        return Model()

    monkeypatch.setitem(
        sys.modules,
        "stable_audio_tools.models.factory",
        SimpleNamespace(create_model_from_config=fake_factory),
    )
    monkeypatch.setitem(
        sys.modules,
        "stable_audio_tools.models.utils",
        SimpleNamespace(load_ckpt_state_dict=lambda path: {"loaded_from": path}),
    )
    for name in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACEHUB_API_TOKEN",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    adapter = StableAudioOpenAdapter(snapshot_dir=snapshot, device="cuda:0")
    adapter._preflight = BackbonePreflight(
        status="READY_FOR_MINI_SMOKE",
        model_id=adapter.model_id,
        config_sha256=adapter.config_sha256,
        details={
            "receipt": {
                "verified_files": [
                    {
                        "path": "model.safetensors",
                        "size_bytes": weight.stat().st_size,
                        "sha256": sha256_file(weight),
                        "hash_verified": True,
                    },
                    {
                        "path": "model.ckpt",
                        "size_bytes": checkpoint.stat().st_size,
                        "sha256": sha256_file(checkpoint),
                        "hash_verified": True,
                    },
                    {
                        "path": "model_config.json",
                        "size_bytes": model_config_path.stat().st_size,
                        "sha256": sha256_file(model_config_path),
                        "hash_verified": True,
                    },
                    *t5_rows,
                ]
            }
        },
    )
    adapter._ensure_loaded()
    assert observed["offline_environment"] == {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    }
    assert observed["device"] == "cuda:0"
    assert observed["eval"] is True
    assert observed["state"] == {"loaded_from": str(weight)}
    assert adapter._weight_file_sha256 == sha256_file(weight)
    assert adapter._conditioning_bundle_sha256 == conditioning_bundle_record(t5_rows)[
        "conditioning_bundle_sha256"
    ]
    assert not Path(observed["resolved_conditioner"]["model_path"]).exists()
    assert model_config_path.read_bytes() == original_config_bytes
    assert {
        relative: (snapshot / relative).read_bytes() for _bundle, relative in T5_BUNDLE_LAYOUT
    } == source_bytes
    assert "model_path" not in _sao_model_config()["model"]["conditioning"]["configs"][0][
        "config"
    ]
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    assert "HF_HUB_DISABLE_IMPLICIT_TOKEN" not in os.environ


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "source file is absent"),
        ("drift", "changed after receipt"),
        ("unbound", "does not uniquely bind T5 file"),
        ("config-drift", "model config changed after receipt preflight"),
        ("wrong-root-model", "conditioner config is unexpected"),
        ("wrong-encoder-model", "not the expected T5-base"),
    ],
)
def test_sao_t5_binding_failures_stop_before_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    model_config_path = snapshot / "model_config.json"
    model_config = _sao_model_config()
    _write_json(model_config_path, model_config)
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"root-weight")
    t5_rows = _write_sao_t5_loader_fixture(snapshot)
    model_config_row = {
        "path": "model_config.json",
        "size_bytes": model_config_path.stat().st_size,
        "sha256": sha256_file(model_config_path),
        "hash_verified": True,
    }

    if mutation == "missing":
        (snapshot / "tokenizer" / "spiece.model").unlink()
    elif mutation == "drift":
        (snapshot / "tokenizer" / "tokenizer.json").write_text(
            '{"changed":true}\n', encoding="utf-8"
        )
    elif mutation == "unbound":
        t5_rows = [row for row in t5_rows if row["path"] != "tokenizer/tokenizer.json"]
    elif mutation == "config-drift":
        model_config["drift_after_cached_preflight"] = True
        _write_json(model_config_path, model_config)
    elif mutation == "wrong-root-model":
        model_config["model"]["conditioning"]["configs"][0]["config"][
            "t5_model_name"
        ] = "t5-large"
        _write_json(model_config_path, model_config)
        model_config_row["size_bytes"] = model_config_path.stat().st_size
        model_config_row["sha256"] = sha256_file(model_config_path)
    else:
        encoder_config = snapshot / "text_encoder" / "config.json"
        value = json.loads(encoder_config.read_text(encoding="utf-8"))
        value["_name_or_path"] = "t5-large"
        _write_json(encoder_config, value)
        row = next(row for row in t5_rows if row["path"] == "text_encoder/config.json")
        row["size_bytes"] = encoder_config.stat().st_size
        row["sha256"] = sha256_file(encoder_config)

    factory_called = False

    def forbidden_factory(_config):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("factory must not run after a T5 binding failure")

    monkeypatch.setitem(
        sys.modules,
        "stable_audio_tools.models.factory",
        SimpleNamespace(create_model_from_config=forbidden_factory),
    )
    adapter = StableAudioOpenAdapter(snapshot_dir=snapshot, device="cuda:0")
    adapter._preflight = BackbonePreflight(
        status="READY_FOR_MINI_SMOKE",
        model_id=adapter.model_id,
        config_sha256=adapter.config_sha256,
        details={
            "receipt": {
                "verified_files": [
                    {
                        "path": "model.safetensors",
                        "size_bytes": weight.stat().st_size,
                        "sha256": sha256_file(weight),
                        "hash_verified": True,
                    },
                    model_config_row,
                    *t5_rows,
                ]
            }
        },
    )
    with pytest.raises(BackboneConfigurationError, match=message):
        adapter._ensure_loaded()
    assert factory_called is False


def test_sao_loader_rejects_token_environment_before_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    model_config_path = snapshot / "model_config.json"
    _write_json(model_config_path, _sao_model_config())
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"root-weight")
    t5_rows = _write_sao_t5_loader_fixture(snapshot)
    factory_called = False

    def forbidden_factory(_config):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("factory must not run with a token environment")

    monkeypatch.setitem(
        sys.modules,
        "stable_audio_tools.models.factory",
        SimpleNamespace(create_model_from_config=forbidden_factory),
    )
    monkeypatch.setenv("HF_TOKEN", "SENTINEL_MUST_NOT_APPEAR_IN_ERRORS")
    adapter = StableAudioOpenAdapter(snapshot_dir=snapshot, device="cuda:0")
    adapter._preflight = BackbonePreflight(
        status="READY_FOR_MINI_SMOKE",
        model_id=adapter.model_id,
        config_sha256=adapter.config_sha256,
        details={
            "receipt": {
                "verified_files": [
                    {
                        "path": "model.safetensors",
                        "size_bytes": weight.stat().st_size,
                        "sha256": sha256_file(weight),
                        "hash_verified": True,
                    },
                    {
                        "path": "model_config.json",
                        "size_bytes": model_config_path.stat().st_size,
                        "sha256": sha256_file(model_config_path),
                        "hash_verified": True,
                    },
                    *t5_rows,
                ]
            }
        },
    )
    with pytest.raises(BackboneConfigurationError) as caught:
        adapter._ensure_loaded()
    assert "SENTINEL_MUST_NOT_APPEAR_IN_ERRORS" not in str(caught.value)
    assert "HF_TOKEN" in str(caught.value)
    assert factory_called is False

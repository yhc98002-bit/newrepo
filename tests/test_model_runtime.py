"""CPU-only tests for the immutable local Stable Audio 3 loader."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

from sa3_smoke.artifacts import sha256_file
from sa3_smoke.model_runtime import load_local_model, resolve_local_model_config


def make_local_snapshot(tmp_path: Path) -> tuple[Path, Path]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    original = snapshot / "model_config.json"
    original.write_text(
        json.dumps(
            {
                "model_type": "diffusion_cond_inpaint",
                "sample_size": 16_777_216,
                "model": {
                    "conditioning": {
                        "configs": [
                            {
                                "id": "prompt",
                                "type": "t5gemma",
                                "config": {
                                    "max_length": 256,
                                    "padding_mode": "learned",
                                    "repo_id": "stabilityai/stable-audio-3-medium",
                                    "subfolder": "t5gemma-b-b-ul2",
                                },
                            }
                        ]
                    }
                },
            },
            indent=4,
        ),
        encoding="utf-8",
    )
    conditioner = snapshot / "t5gemma-b-b-ul2"
    conditioner.mkdir()
    (conditioner / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["T5GemmaForConditionalGeneration"],
                "encoder": {"hidden_size": 768},
                "model_type": "t5gemma",
            }
        ),
        encoding="utf-8",
    )
    (conditioner / "model.safetensors").write_bytes(b"test conditioner weights")
    return original, conditioner


def resolve_fixture(tmp_path: Path):
    original, conditioner = make_local_snapshot(tmp_path)
    resolution = resolve_local_model_config(
        original,
        conditioner,
        tmp_path / "evidence",
        required_t5_files=("config.json", "model.safetensors"),
    )
    return original, conditioner, resolution


def test_resolution_retains_original_diff_hashes_and_only_local_path(tmp_path: Path) -> None:
    original, conditioner, resolution = resolve_fixture(tmp_path)
    original_bytes = original.read_bytes()

    assert Path(resolution.original_copy_path).read_bytes() == original_bytes
    assert resolution.original_sha256 == sha256_file(original)
    assert resolution.resolved_sha256 == sha256_file(resolution.resolved_config_path)
    assert resolution.diff_sha256 == sha256_file(resolution.diff_path)
    assert resolution.resolution_manifest_sha256 == sha256_file(resolution.resolution_manifest_path)

    upstream = json.loads(original_bytes)
    resolved = json.loads(Path(resolution.resolved_config_path).read_text(encoding="utf-8"))
    before = upstream["model"]["conditioning"]["configs"][0]["config"]
    after = resolved["model"]["conditioning"]["configs"][0]["config"]
    assert before["repo_id"] == "stabilityai/stable-audio-3-medium"
    assert before["subfolder"] == "t5gemma-b-b-ul2"
    assert "model_path" not in before
    assert after["model_path"] == str(conditioner.resolve())
    assert "repo_id" not in after
    assert "subfolder" not in after
    assert {**after, "repo_id": before["repo_id"], "subfolder": before["subfolder"]} == {
        **before,
        "model_path": str(conditioner.resolve()),
    }

    diff = Path(resolution.diff_path).read_text(encoding="utf-8")
    assert '-                        "repo_id": "stabilityai/stable-audio-3-medium"' in diff
    assert '-                        "subfolder": "t5gemma-b-b-ul2"' in diff
    assert f'+                        "model_path": "{conditioner.resolve()}"' in diff
    manifest = json.loads(Path(resolution.resolution_manifest_path).read_text(encoding="utf-8"))
    assert manifest["network_access"] == "none"
    assert manifest["t5_snapshot_file_sha256s"]["model.safetensors"] == sha256_file(
        conditioner / "model.safetensors"
    )
    json.dumps(resolution.to_dict(), allow_nan=False)


def test_resolution_is_no_clobber_and_rejects_nonembedded_conditioner(
    tmp_path: Path,
) -> None:
    original, conditioner, _resolution = resolve_fixture(tmp_path)
    with pytest.raises(FileExistsError):
        resolve_local_model_config(
            original,
            conditioner,
            tmp_path / "evidence",
            required_t5_files=("config.json", "model.safetensors"),
        )
    assert json.loads(original.read_text(encoding="utf-8"))["model_type"] == (
        "diffusion_cond_inpaint"
    )

    external = tmp_path / "external" / "t5gemma-b-b-ul2"
    external.mkdir(parents=True)
    (external / "config.json").write_bytes((conditioner / "config.json").read_bytes())
    (external / "model.safetensors").write_bytes(b"test conditioner weights")
    with pytest.raises(ValueError, match="embedded next to"):
        resolve_local_model_config(
            original,
            external,
            tmp_path / "other-evidence",
            required_t5_files=("config.json", "model.safetensors"),
        )


def test_load_is_offline_uses_upstream_constructor_and_verifies_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _original, conditioner, resolution = resolve_fixture(tmp_path)
    checkpoint = tmp_path / "model.safetensors"
    checkpoint.write_bytes(b"small fake checkpoint; never interpreted as weights")
    checkpoint_digest = sha256_file(checkpoint)
    observed: dict[str, object] = {}

    class FakeConditionedModel:
        pass

    def fake_load_diffusion_cond(
        config: dict[str, object],
        checkpoint_path: str,
        *,
        device: str,
        model_half: bool,
    ) -> FakeConditionedModel:
        observed["offline_during_load"] = {
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
        }
        observed["config"] = config
        observed["checkpoint"] = checkpoint_path
        observed["device"] = device
        observed["model_half"] = model_half
        return FakeConditionedModel()

    class FakeStableAudioModel:
        def __init__(self, model, model_config, device, model_half):
            observed["official_constructor_called"] = True
            self.model = model
            self.model_config = model_config
            self.device = device
            self.model_half = model_half
            self.dit = object()

        def generate(self, **kwargs):
            return kwargs

    package = types.ModuleType("stable_audio_3")
    package.__path__ = []  # type: ignore[attr-defined]
    loading = types.ModuleType("stable_audio_3.loading_utils")
    loading.load_diffusion_cond = fake_load_diffusion_cond  # type: ignore[attr-defined]
    model_module = types.ModuleType("stable_audio_3.model")
    model_module.StableAudioModel = FakeStableAudioModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stable_audio_3", package)
    monkeypatch.setitem(sys.modules, "stable_audio_3.loading_utils", loading)
    monkeypatch.setitem(sys.modules, "stable_audio_3.model", model_module)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    runtime = load_local_model(
        resolution,
        checkpoint,
        device="cuda:0",
        model_half=True,
        expected_checkpoint_sha256=checkpoint_digest,
    )

    assert observed["offline_during_load"] == {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    assert observed["official_constructor_called"] is True
    assert observed["checkpoint"] == str(checkpoint.resolve())
    assert runtime.checkpoint_sha256 == checkpoint_digest
    assert runtime.generate(marker="official-generate") == {"marker": "official-generate"}
    config = observed["config"]
    assert isinstance(config, dict)
    prompt_config = config["model"]["conditioning"]["configs"][0]["config"]
    assert prompt_config == {
        "max_length": 256,
        "padding_mode": "learned",
        "model_path": str(conditioner.resolve()),
    }
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ

    with pytest.raises(ValueError, match="checkpoint SHA-256 mismatch"):
        load_local_model(
            resolution,
            checkpoint,
            expected_checkpoint_sha256="0" * 64,
        )

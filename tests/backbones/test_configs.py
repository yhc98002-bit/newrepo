from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import backbones.stable_audio_3 as stable_audio_3_module
from backbones.ace_step_v1 import AceStepV1Adapter, _canonical_manifest_sha256
from backbones.contracts import (
    DEFAULT_ACE_CONFIG,
    DEFAULT_SAO_CONFIG,
    REPOSITORY_ROOT,
    BackboneConfigurationError,
    GenerationRequest,
    load_backbone_config,
    sha256_file,
)
from backbones.factory import create_adapter
from backbones.stable_audio_3 import DEFAULT_SA3_CONFIG, StableAudio3MediumBaseAdapter
from backbones.stable_audio_open import StableAudioOpenAdapter
from sa3_smoke.audio import save_float_wav_exclusive
from scripts.prepare_benchmark_core_run import DEFAULT_FROZEN_FILES


@pytest.mark.parametrize(
    "path",
    [DEFAULT_ACE_CONFIG, DEFAULT_SAO_CONFIG, DEFAULT_SA3_CONFIG],
)
def test_committed_backbone_configs_are_strict_and_capped(path: Path) -> None:
    config, digest = load_backbone_config(path)
    assert len(digest) == 64
    assert config["adapter"]["network_downloads_allowed"] is False
    assert config["mini_smoke_caps"] == {
        "max_clip_seconds": 30.0,
        "max_generations_shared_across_b2": 10,
        "max_gpus_per_job": 1,
    }


def test_ace_port_records_frozen_source_identities_without_old_results() -> None:
    config, _ = load_backbone_config(DEFAULT_ACE_CONFIG)
    provenance = config["provenance"]
    assert provenance["frozen_config_source"] == {
        "git_commit": "7f63ab79948736c5bb6bd0d733c3eb570a1a2ac6",
        "path": (
            "orbit-research/adsr_phase2_20260604/paper_prep/"
            "w2_execution_20260712/spine_reconstruction_torch251_recovery/"
            "SPINE_TORCH251_FULL_REPLAY_PROTOCOL.md"
        ),
        "sha256": "e20e0fbeff2cd98acd7df765ad042336a56cbe910547c64e53cf87be65a15176",
    }
    assert config["generation"]["inference_steps"] == 30
    assert config["generation"]["cfg_type"] == "cfg"
    port = json.loads(
        (REPOSITORY_ROOT / "provenance/b2/ace_step_v1_port.json").read_text(encoding="utf-8")
    )
    assert "old generated media" in port["what_was_not_imported"]


def test_sa3_config_pins_current_project_local_foundation_records() -> None:
    config, _ = load_backbone_config(DEFAULT_SA3_CONFIG)
    assert config["model_id"] == "stabilityai/stable-audio-3-medium-base"
    assert config["provenance"]["state_capability"] == "PASS"
    for key in (
        "foundation_config",
        "foundation_report",
        "model_runtime_source",
        "weights_manifest",
        "cross_provider_verification",
    ):
        record = config["provenance"][key]
        assert sha256_file(REPOSITORY_ROOT / record["path"]) == record["sha256"]
    for key in ("package_freeze", "runtime_record", "licenses"):
        record = config["runtime"][key]
        assert sha256_file(REPOSITORY_ROOT / record["path"]) == record["sha256"]


def test_sa3_runtime_pins_public_metadata_and_local_module_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = StableAudio3MediumBaseAdapter(validate_environment=False)
    runtime = adapter.config["runtime"]
    environment_root = Path(runtime["environment_path"])
    module_root = environment_root / "lib/python3.10/site-packages"
    probe = {
        "python_version": runtime["python"],
        "sys_prefix": str(environment_root),
        "torch_cuda_version": runtime["cuda_build"],
        "modules": {
            "torch": {
                "file": str(module_root / "torch/__init__.py"),
                "version": runtime["distributions"]["torch"],
            },
            "torchaudio": {
                "file": str(module_root / "torchaudio/__init__.py"),
                "version": runtime["distributions"]["torchaudio"],
            },
            "flash_attn": {
                "file": str(module_root / "flash_attn/__init__.py"),
                "version": "2.6.3",
            },
            "stable_audio_3": {
                "file": str(module_root / "stable_audio_3/__init__.py"),
                "version": None,
            },
            "stable_audio_tools": {
                "file": str(module_root / "stable_audio_tools/__init__.py"),
                "version": None,
            },
            "sa3_smoke": {
                "file": str(REPOSITORY_ROOT / "src/sa3_smoke/__init__.py"),
                "version": None,
            },
        },
    }
    metadata_versions = {
        name: expected.partition("+")[0] if name in {"torch", "torchaudio"} else expected
        for name, expected in runtime["distributions"].items()
    }
    monkeypatch.setattr(stable_audio_3_module, "collect_runtime_probe", lambda: probe)
    monkeypatch.setattr(
        stable_audio_3_module.importlib.metadata,
        "version",
        metadata_versions.__getitem__,
    )

    result = adapter._validate_benchmark_runtime()
    assert result["distributions"]["torch"] == "2.7.1"
    assert result["module_versions"]["torch"] == "2.7.1+cu126"

    probe["modules"]["torch"]["version"] = "2.7.1+cu128"
    with pytest.raises(BackboneConfigurationError, match="torch module build drift"):
        adapter._validate_benchmark_runtime()

    probe["modules"]["torch"]["version"] = runtime["distributions"]["torch"]
    metadata_versions["torch"] = "2.7.2"
    with pytest.raises(BackboneConfigurationError, match="torch distribution metadata drift"):
        adapter._validate_benchmark_runtime()

    metadata_versions["torch"] = "2.7.1"
    metadata_versions["flash-attn"] = "2.6.3"
    with pytest.raises(BackboneConfigurationError, match="flash-attn distribution metadata drift"):
        adapter._validate_benchmark_runtime()


def test_core_launch_directly_freezes_the_sa3_project_runtime_closure() -> None:
    frozen = {path.resolve() for path in DEFAULT_FROZEN_FILES}
    required = {
        REPOSITORY_ROOT / "configs/backbones/stable_audio_3_medium_base.json",
        REPOSITORY_ROOT / "src/benchmark_core/__init__.py",
        REPOSITORY_ROOT / "src/backbones/__init__.py",
        REPOSITORY_ROOT / "src/backbones/contracts.py",
        REPOSITORY_ROOT / "src/backbones/io.py",
        REPOSITORY_ROOT / "src/backbones/runtime.py",
        REPOSITORY_ROOT / "src/backbones/stable_audio_3.py",
        REPOSITORY_ROOT / "src/sa3_smoke/__init__.py",
        REPOSITORY_ROOT / "src/sa3_smoke/artifacts.py",
        REPOSITORY_ROOT / "src/sa3_smoke/audio.py",
        REPOSITORY_ROOT / "src/sa3_smoke/budget.py",
        REPOSITORY_ROOT / "src/sa3_smoke/environment_validation.py",
        REPOSITORY_ROOT / "src/sa3_smoke/model_runtime.py",
    }
    assert {path.resolve() for path in required} <= frozen


def test_pre_generation_status_binds_all_three_config_hashes() -> None:
    status = json.loads(
        (REPOSITORY_ROOT / "provenance/b2/build_status_pre_generation.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["model_generation_calls_total"] == 0
    assert status["build_generated_audio"] is False
    expected = {
        "ACE-Step v1": DEFAULT_ACE_CONFIG,
        "stable-audio-open-1.0": DEFAULT_SAO_CONFIG,
        "stable-audio-3-medium-base": DEFAULT_SA3_CONFIG,
    }
    for logical_name, path in expected.items():
        assert status["adapters"][logical_name]["config_sha256"] == sha256_file(path)


def test_strict_config_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(BackboneConfigurationError, match="duplicate JSON key"):
        load_backbone_config(path)


def test_ace_preflight_verifies_content_pins_with_injected_factory(tmp_path: Path) -> None:
    source = json.loads(DEFAULT_ACE_CONFIG.read_text(encoding="utf-8"))
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    weight = checkpoint / "tiny.bin"
    weight.write_bytes(b"content-pinned-test-weight")
    source["checkpoint"]["required_files"] = [
        {
            "path": "tiny.bin",
            "size_bytes": weight.stat().st_size,
            "sha256": sha256_file(weight),
        }
    ]
    source["checkpoint"]["exact_tree_sha256"] = _canonical_manifest_sha256(
        source["checkpoint"]["required_files"]
    )
    config_path = tmp_path / "ace.json"
    config_path.write_text(json.dumps(source), encoding="utf-8")
    adapter = AceStepV1Adapter(
        config_path=config_path,
        checkpoint_dir=checkpoint,
        pipeline_factory=lambda **_kwargs: object(),
    )
    preflight = adapter.preflight()
    assert preflight.status == "READY_FOR_MINI_SMOKE"
    assert preflight.details["checkpoint_tree"]["files"][0]["hash_verified"] is True
    assert preflight.details["checkpoint_tree"]["exact_tree_no_exclusions"] is True
    weight.write_bytes(b"tampered-content")
    fresh = AceStepV1Adapter(
        config_path=config_path,
        checkpoint_dir=checkpoint,
        pipeline_factory=lambda **_kwargs: object(),
    )
    with pytest.raises(BackboneConfigurationError, match="size mismatch|SHA-256 mismatch"):
        fresh.preflight()


def test_uniform_factory_selects_without_loading_models(tmp_path: Path) -> None:
    ace = create_adapter(DEFAULT_ACE_CONFIG, evidence_dir=tmp_path / "ace")
    sao = create_adapter(DEFAULT_SAO_CONFIG, evidence_dir=tmp_path / "sao")
    sa3 = create_adapter(
        DEFAULT_SA3_CONFIG,
        evidence_dir=tmp_path / "sa3",
        validate_environment=False,
    )
    assert isinstance(ace, AceStepV1Adapter)
    assert isinstance(sao, StableAudioOpenAdapter)
    assert isinstance(sa3, StableAudio3MediumBaseAdapter)
    assert sa3.config_resolution_dir == tmp_path / "sa3" / "model-config-resolution"
    assert not list(tmp_path.iterdir())


def test_unknown_factory_model_is_rejected(tmp_path: Path) -> None:
    source = copy.deepcopy(json.loads(DEFAULT_ACE_CONFIG.read_text(encoding="utf-8")))
    source["logical_name"] = "unknown"
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(BackboneConfigurationError, match="no adapter registered"):
        create_adapter(path, evidence_dir=tmp_path / "evidence")


def test_ace_adapter_keeps_fake_pipeline_resident_across_requests(tmp_path: Path) -> None:
    source = json.loads(DEFAULT_ACE_CONFIG.read_text(encoding="utf-8"))
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    weight = checkpoint / "tiny.bin"
    weight.write_bytes(b"resident-pipeline-test")
    source["checkpoint"]["required_files"] = [
        {
            "path": "tiny.bin",
            "size_bytes": weight.stat().st_size,
            "sha256": sha256_file(weight),
        }
    ]
    source["checkpoint"]["exact_tree_sha256"] = _canonical_manifest_sha256(
        source["checkpoint"]["required_files"]
    )
    source["generation"]["inference_steps"] = 3
    config_path = tmp_path / "ace-resident.json"
    config_path.write_text(json.dumps(source), encoding="utf-8")

    class FakeTransformer:
        def decode(self) -> None:
            return None

    class FakePipeline:
        def __init__(self) -> None:
            self.ace_step_transformer = FakeTransformer()
            self.load_calls = 0
            self.generation_calls = 0

        def load_checkpoint(self, _path: str) -> None:
            self.load_calls += 1

        def __call__(self, **kwargs: Any) -> None:
            self.generation_calls += 1
            for _ in range(kwargs["infer_step"]):
                self.ace_step_transformer.decode()
            sample_rate = 48000
            frames = round(kwargs["audio_duration"] * sample_rate)
            samples = np.full((frames, 2), 0.01, dtype=np.float32)
            save_float_wav_exclusive(kwargs["save_path"], samples, sample_rate)

    class FakeTelemetry:
        def __init__(self, device: str) -> None:
            assert device == "cuda"

        @contextmanager
        def measured(self):
            measured: dict[str, float | int] = {}
            yield measured
            measured.update(
                wall_seconds=0.1,
                peak_allocated_bytes=100,
                peak_reserved_bytes=200,
            )

    pipelines: list[FakePipeline] = []

    def factory(**_kwargs: Any) -> FakePipeline:
        pipeline = FakePipeline()
        pipelines.append(pipeline)
        return pipeline

    adapter = AceStepV1Adapter(
        config_path=config_path,
        checkpoint_dir=checkpoint,
        pipeline_factory=factory,
        telemetry_factory=FakeTelemetry,
    )
    for index in range(2):
        measurement = adapter.generate(
            GenerationRequest(
                prompt_id=f"p-{index}",
                prompt="fake",
                seed_id=f"s-{index}",
                seed=index,
                duration_seconds=0.1,
                output_path=tmp_path / f"out-{index}.wav",
            )
        )
        assert measurement.actual_nfe == 3
    assert len(pipelines) == 1
    assert pipelines[0].load_calls == 1
    assert pipelines[0].generation_calls == 2

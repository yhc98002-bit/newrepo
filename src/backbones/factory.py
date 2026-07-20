"""Uniform constructor for the three frozen benchmark backbone configs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backbones.ace_step_v1 import AceStepV1Adapter
from backbones.contracts import BackboneAdapter, BackboneConfigurationError, load_backbone_config
from backbones.stable_audio_3 import StableAudio3MediumBaseAdapter
from backbones.stable_audio_open import StableAudioOpenAdapter


def create_adapter(
    config_path: str | Path,
    *,
    evidence_dir: str | Path,
    **runtime_overrides: Any,
) -> BackboneAdapter:
    """Construct, but do not load, the adapter identified by a frozen config.

    ``evidence_dir`` is run-local. SA3 uses a child directory for its immutable
    conditioner-resolution evidence; ACE and SAO reserve the path for the
    common outer runner's manifests. Provider access and model loading remain
    deferred until ``preflight``/``generate``.
    """

    config_file = Path(config_path)
    config, _config_sha256 = load_backbone_config(config_file)
    evidence = Path(evidence_dir)
    logical_name = config["logical_name"]
    if logical_name == "stable-audio-3-medium-base":
        if "config_resolution_dir" in runtime_overrides:
            raise TypeError("create_adapter owns SA3 config_resolution_dir under evidence_dir")
        return StableAudio3MediumBaseAdapter(
            config_path=config_file,
            config_resolution_dir=evidence / "model-config-resolution",
            **runtime_overrides,
        )
    if logical_name == "stable-audio-open-1.0":
        return StableAudioOpenAdapter(
            config_path=config_file,
            evidence_dir=evidence,
            **runtime_overrides,
        )
    if logical_name == "ACE-Step v1":
        return AceStepV1Adapter(
            config_path=config_file,
            evidence_dir=evidence,
            **runtime_overrides,
        )
    raise BackboneConfigurationError(f"no adapter registered for {logical_name!r}")

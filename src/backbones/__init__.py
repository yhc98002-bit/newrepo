"""Fail-closed benchmark backbone adapters and bounded mini-smoke support.

Exports are lazy so importing the ACE-only B2 path does not execute unrelated
backbone modules. This keeps the production behavior surface small enough to
content-bind completely.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "AceStepV1Adapter",
    "BackboneConfigurationError",
    "BackbonePreflight",
    "GenerationMeasurement",
    "GenerationRequest",
    "LicenseGateBlocked",
    "StableAudioOpenAdapter",
    "StableAudio3MediumBaseAdapter",
    "load_backbone_config",
    "create_adapter",
]

_EXPORTS = {
    "AceStepV1Adapter": ("backbones.ace_step_v1", "AceStepV1Adapter"),
    "BackboneConfigurationError": ("backbones.contracts", "BackboneConfigurationError"),
    "BackbonePreflight": ("backbones.contracts", "BackbonePreflight"),
    "GenerationMeasurement": ("backbones.contracts", "GenerationMeasurement"),
    "GenerationRequest": ("backbones.contracts", "GenerationRequest"),
    "LicenseGateBlocked": ("backbones.contracts", "LicenseGateBlocked"),
    "StableAudioOpenAdapter": ("backbones.stable_audio_open", "StableAudioOpenAdapter"),
    "StableAudio3MediumBaseAdapter": (
        "backbones.stable_audio_3",
        "StableAudio3MediumBaseAdapter",
    ),
    "load_backbone_config": ("backbones.contracts", "load_backbone_config"),
    "create_adapter": ("backbones.factory", "create_adapter"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

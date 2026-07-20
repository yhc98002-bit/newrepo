"""Shared, network-free contracts for benchmark backbone adapters."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
TERMINAL_ENTRY_STATUSES = frozenset({"READY_FOR_MINI_SMOKE", "BLOCKED_ON_LICENSE"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACE_CONFIG = REPOSITORY_ROOT / "configs" / "backbones" / "ace_step_v1.json"
DEFAULT_SAO_CONFIG = REPOSITORY_ROOT / "configs" / "backbones" / "stable_audio_open_1_0.json"


class BackboneConfigurationError(ValueError):
    """Raised when a backbone config or local snapshot is incomplete or inconsistent."""


class LicenseGateBlocked(RuntimeError):
    """Fail-closed license/access boundary with user-actionable remediation."""

    status = "BLOCKED_ON_LICENSE"

    def __init__(self, *, model_id: str, reason: str, human_steps: Sequence[str]) -> None:
        self.model_id = model_id
        self.reason = reason
        self.human_steps = tuple(human_steps)
        super().__init__(f"{self.status}: {model_id}: {reason}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_id": self.model_id,
            "reason": self.reason,
            "human_steps": list(self.human_steps),
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackboneConfigurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def sha256_file(path: str | Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Hash a file without loading checkpoint-sized artifacts into memory."""

    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def strict_json_object(path: str | Path) -> dict[str, Any]:
    """Load a UTF-8 JSON object while rejecting duplicate keys and non-finite numbers."""

    source = Path(path)
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                BackboneConfigurationError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackboneConfigurationError(f"cannot load {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise BackboneConfigurationError(f"JSON root must be an object: {source}")
    return value


def _require_nonempty_string(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BackboneConfigurationError(f"{key} must be a non-empty string")
    return value


def _require_positive_number(record: Mapping[str, Any], key: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BackboneConfigurationError(f"{key} must be a positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise BackboneConfigurationError(f"{key} must be a positive finite number")
    return number


def load_backbone_config(path: str | Path) -> tuple[dict[str, Any], str]:
    """Load and minimally validate a committed backbone config plus its content hash."""

    source = Path(path)
    config = strict_json_object(source)
    if config.get("schema_version") != 1:
        raise BackboneConfigurationError("backbone schema_version must equal 1")
    _require_nonempty_string(config, "logical_name")
    _require_nonempty_string(config, "model_id")
    _require_nonempty_string(config, "license_identifier")
    status = config.get("entry_status")
    if status not in TERMINAL_ENTRY_STATUSES:
        raise BackboneConfigurationError(
            f"entry_status must be one of {sorted(TERMINAL_ENTRY_STATUSES)}"
        )
    adapter = config.get("adapter")
    if not isinstance(adapter, dict) or adapter.get("network_downloads_allowed") is not False:
        raise BackboneConfigurationError("adapter must explicitly forbid network downloads")
    generation = config.get("generation")
    if not isinstance(generation, dict):
        raise BackboneConfigurationError("generation must be an object")
    duration = _require_positive_number(generation, "benchmark_duration_seconds")
    caps = config.get("mini_smoke_caps")
    if not isinstance(caps, dict):
        raise BackboneConfigurationError("mini_smoke_caps must be an object")
    max_duration = _require_positive_number(caps, "max_clip_seconds")
    max_generations = caps.get("max_generations_shared_across_b2")
    if isinstance(max_generations, bool) or not isinstance(max_generations, int):
        raise BackboneConfigurationError("shared mini-smoke generation cap must be an integer")
    if not 1 <= max_generations <= 10:
        raise BackboneConfigurationError("shared mini-smoke generation cap must be in [1, 10]")
    if caps.get("max_gpus_per_job") != 1:
        raise BackboneConfigurationError("B2 mini-smokes require exactly one GPU per job")
    if duration > max_duration or max_duration > 30:
        raise BackboneConfigurationError("B2 clip duration exceeds the 30-second hard cap")
    return config, sha256_file(source)


@dataclass(frozen=True)
class GenerationRequest:
    """One immutable generation request; destination is chosen before model invocation."""

    prompt_id: str
    prompt: str
    seed_id: str
    seed: int
    duration_seconds: float
    output_path: Path
    lyrics: str = ""

    def __post_init__(self) -> None:
        for name in ("prompt_id", "prompt", "seed_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if isinstance(self.duration_seconds, bool) or not isinstance(
            self.duration_seconds, (int, float)
        ):
            raise ValueError("duration_seconds must be a finite positive number")
        duration = float(self.duration_seconds)
        if not math.isfinite(duration) or not 0 < duration <= 30:
            raise ValueError("duration_seconds must be in (0, 30]")
        output = Path(self.output_path)
        if output.suffix.lower() != ".wav":
            raise ValueError("output_path must have a .wav suffix")
        object.__setattr__(self, "duration_seconds", duration)
        object.__setattr__(self, "output_path", output)


@dataclass(frozen=True)
class BackbonePreflight:
    """Network-free adapter readiness result."""

    status: str
    model_id: str
    config_sha256: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationMeasurement:
    """Measured metadata for a retained waveform created by one model call."""

    output_path: Path
    sample_rate: int
    requested_steps: int
    actual_nfe: int
    wall_seconds: float
    peak_allocated_bytes: int | None
    peak_reserved_bytes: int | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not Path(self.output_path).is_file():
            raise ValueError(f"generated output is absent: {self.output_path}")
        if self.sample_rate <= 0 or self.requested_steps <= 0 or self.actual_nfe <= 0:
            raise ValueError("sample rate, requested steps, and actual NFE must be positive")
        if not math.isfinite(self.wall_seconds) or self.wall_seconds <= 0:
            raise ValueError("wall_seconds must be finite and positive")
        try:
            json.dumps(dict(self.metadata), allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("generation metadata must be strict-JSON-compatible") from exc


class BackboneAdapter(Protocol):
    """Small adapter interface consumed by the bounded mini-smoke runner."""

    model_id: str
    logical_name: str
    config_sha256: str
    license_identifier: str

    def preflight(self) -> BackbonePreflight: ...

    def generate(self, request: GenerationRequest) -> GenerationMeasurement: ...


PipelineFactory = Callable[..., Any]

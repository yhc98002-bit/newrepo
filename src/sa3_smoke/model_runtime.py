"""Offline, provenance-preserving loader for the official Stable Audio 3 API.

The upstream base-model config refers to the text conditioner through the
separately gated ``stabilityai/stable-audio-3-medium`` repository.  The exact
base snapshot already embeds that conditioner under ``t5gemma-b-b-ul2``.  This
module makes the one permitted loading deviation explicit: it retains a
byte-identical copy of the upstream config, creates a second config whose
conditioner points at that embedded directory, and retains the unified diff and
hashes.  It never calls a hub API and never changes the upstream snapshot.

Model construction uses upstream ``load_diffusion_cond`` and wraps the result
in upstream ``StableAudioModel``.  Smoke callers therefore exercise the
official :meth:`StableAudioModel.generate` implementation.
"""

from __future__ import annotations

import difflib
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sa3_smoke.artifacts import exclusive_write_bytes, exclusive_write_json, sha256_file

EXPECTED_BASE_MODEL_TYPE = "diffusion_cond_inpaint"
EXPECTED_T5_REPO_ID = "stabilityai/stable-audio-3-medium"
EXPECTED_T5_SUBFOLDER = "t5gemma-b-b-ul2"
EXPECTED_T5_ARCHITECTURES = frozenset({"T5GemmaForConditionalGeneration", "T5GemmaEncoderModel"})
DEFAULT_REQUIRED_T5_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
)


@dataclass(frozen=True)
class ResolvedModelConfig:
    """Immutable evidence emitted while resolving the embedded conditioner."""

    original_source_path: str
    original_copy_path: str
    resolved_config_path: str
    diff_path: str
    resolution_manifest_path: str
    original_sha256: str
    resolved_sha256: str
    diff_sha256: str
    resolution_manifest_sha256: str
    t5_snapshot_path: str
    t5_snapshot_file_sha256s: Mapping[str, str]
    conditioning_before: Mapping[str, Any]
    conditioning_after: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a strict-JSON-compatible copy."""

        return asdict(self)


@dataclass(frozen=True)
class ModelRuntime:
    """Loaded official model plus the local-resolution identity used to build it."""

    stable_audio_model: Any
    config_resolution: ResolvedModelConfig
    checkpoint_path: str
    checkpoint_sha256: str | None
    device: str
    model_half: bool

    @property
    def model_config(self) -> Mapping[str, Any]:
        """Expose the official wrapper's config for smoke orchestration."""

        return self.stable_audio_model.model_config

    @property
    def model(self) -> Any:
        """Expose the official conditioned model wrapper."""

        return self.stable_audio_model.model

    @property
    def dit(self) -> Any:
        """Expose the exact diffusion backbone passed to the upstream sampler."""

        return self.stable_audio_model.dit

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate directly to upstream ``StableAudioModel.generate``."""

        return self.stable_audio_model.generate(*args, **kwargs)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _prompt_t5_conditioner(config: Mapping[str, Any]) -> dict[str, Any]:
    try:
        conditioners = config["model"]["conditioning"]["configs"]
    except (KeyError, TypeError) as exc:
        raise ValueError("model config is missing model.conditioning.configs") from exc
    if not isinstance(conditioners, list):
        raise ValueError("model.conditioning.configs must be a list")
    matches = [
        entry
        for entry in conditioners
        if isinstance(entry, dict)
        and entry.get("id") == "prompt"
        and entry.get("type") == "t5gemma"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one prompt/t5gemma conditioner, found {len(matches)}")
    conditioner = matches[0]
    conditioner_config = conditioner.get("config")
    if not isinstance(conditioner_config, dict):
        raise ValueError("prompt/t5gemma conditioner config must be an object")
    return conditioner_config


def _validate_embedded_t5_snapshot(
    snapshot: Path,
    *,
    required_files: Sequence[str],
) -> dict[str, str]:
    if not snapshot.is_dir():
        raise FileNotFoundError(f"embedded T5Gemma snapshot is missing: {snapshot}")
    if snapshot.name != EXPECTED_T5_SUBFOLDER:
        raise ValueError(
            f"embedded conditioner directory must be named {EXPECTED_T5_SUBFOLDER!r}, "
            f"got {snapshot.name!r}"
        )
    if not required_files:
        raise ValueError("required_t5_files must not be empty")

    digests: dict[str, str] = {}
    for relative_name in required_files:
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid required T5Gemma relative path: {relative_name!r}")
        artifact = snapshot / relative
        if not artifact.is_file():
            raise FileNotFoundError(f"embedded T5Gemma file is missing: {artifact}")
        if artifact.name.endswith(".incomplete"):
            raise ValueError(f"incomplete T5Gemma artifact is not loadable: {artifact}")
        digests[relative.as_posix()] = sha256_file(artifact)

    t5_config = _read_json_object(snapshot / "config.json")
    if t5_config.get("model_type") != "t5gemma":
        raise ValueError("embedded conditioner config does not identify model_type=t5gemma")
    architectures = t5_config.get("architectures")
    if not isinstance(architectures, list) or not EXPECTED_T5_ARCHITECTURES.intersection(
        architectures
    ):
        raise ValueError("embedded conditioner config has an unexpected architecture")
    encoder = t5_config.get("encoder")
    if not isinstance(encoder, dict) or encoder.get("hidden_size") != 768:
        raise ValueError("embedded T5Gemma encoder hidden_size must be 768")
    return digests


def resolve_local_model_config(
    original_config_path: str | os.PathLike[str],
    embedded_t5_snapshot_path: str | os.PathLike[str],
    evidence_dir: str | os.PathLike[str],
    *,
    required_t5_files: Sequence[str] = DEFAULT_REQUIRED_T5_FILES,
    require_snapshot_embedded_next_to_config: bool = True,
) -> ResolvedModelConfig:
    """Create immutable original/resolved configs and their audit evidence.

    ``original_config_path`` must be the untouched config in the exact base
    snapshot.  By default the T5Gemma directory must be its sibling, which
    prevents this helper from silently substituting a similarly named model
    from another checkout.  Every output uses exclusive creation; callers must
    allocate a fresh evidence directory when superseding an earlier attempt.
    """

    original = Path(original_config_path).resolve(strict=True)
    if not original.is_file():
        raise FileNotFoundError(original)
    embedded_t5 = Path(embedded_t5_snapshot_path).resolve(strict=True)
    if require_snapshot_embedded_next_to_config and embedded_t5.parent != original.parent:
        raise ValueError("T5Gemma snapshot must be embedded next to the immutable upstream config")

    output_dir = Path(evidence_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise NotADirectoryError(output_dir)

    original_bytes = original.read_bytes()
    try:
        original_text = original_bytes.decode("utf-8")
        config = json.loads(original_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid upstream model config {original}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("upstream model config root must be an object")
    if config.get("model_type") != EXPECTED_BASE_MODEL_TYPE:
        raise ValueError(
            f"expected model_type={EXPECTED_BASE_MODEL_TYPE!r}, got {config.get('model_type')!r}"
        )

    conditioner = _prompt_t5_conditioner(config)
    before = dict(conditioner)
    if before.get("repo_id") != EXPECTED_T5_REPO_ID:
        raise ValueError(f"unexpected upstream T5Gemma repo_id: {before.get('repo_id')!r}")
    if before.get("subfolder") != EXPECTED_T5_SUBFOLDER:
        raise ValueError(f"unexpected upstream T5Gemma subfolder: {before.get('subfolder')!r}")
    if "model_path" in before:
        raise ValueError("upstream config is already locally rewritten; original required")

    t5_digests = _validate_embedded_t5_snapshot(
        embedded_t5,
        required_files=required_t5_files,
    )
    conditioner.pop("repo_id")
    conditioner.pop("subfolder")
    conditioner["model_path"] = str(embedded_t5)
    after = dict(conditioner)

    trailing_newline = original_text.endswith("\n")
    resolved_text = json.dumps(config, ensure_ascii=False, indent=4)
    if trailing_newline:
        resolved_text += "\n"
    resolved_bytes = resolved_text.encode("utf-8")
    diff_text = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            resolved_text.splitlines(keepends=True),
            fromfile="model_config.original.json",
            tofile="model_config.resolved.json",
        )
    )
    if not diff_text:
        raise ValueError("local config resolution unexpectedly produced no diff")

    original_copy = output_dir / "model_config.original.json"
    resolved_path = output_dir / "model_config.resolved.json"
    diff_path = output_dir / "model_config.original-to-resolved.diff"
    manifest_path = output_dir / "model_config.resolution.json"
    exclusive_write_bytes(original_copy, original_bytes)
    exclusive_write_bytes(resolved_path, resolved_bytes)
    exclusive_write_bytes(diff_path, diff_text.encode("utf-8"))

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "deviation": (
            "Replaced only the upstream prompt conditioner repo_id/subfolder with "
            "model_path pointing to the conditioner embedded in the exact base snapshot."
        ),
        "network_access": "none",
        "original_source_path": str(original),
        "original_copy_path": str(original_copy.resolve()),
        "resolved_config_path": str(resolved_path.resolve()),
        "diff_path": str(diff_path.resolve()),
        "original_sha256": sha256_file(original_copy),
        "resolved_sha256": sha256_file(resolved_path),
        "diff_sha256": sha256_file(diff_path),
        "t5_snapshot_path": str(embedded_t5),
        "t5_snapshot_file_sha256s": t5_digests,
        "conditioning_before": before,
        "conditioning_after": after,
    }
    exclusive_write_json(manifest_path, manifest)

    return ResolvedModelConfig(
        original_source_path=str(original),
        original_copy_path=str(original_copy.resolve()),
        resolved_config_path=str(resolved_path.resolve()),
        diff_path=str(diff_path.resolve()),
        resolution_manifest_path=str(manifest_path.resolve()),
        original_sha256=manifest["original_sha256"],
        resolved_sha256=manifest["resolved_sha256"],
        diff_sha256=manifest["diff_sha256"],
        resolution_manifest_sha256=sha256_file(manifest_path),
        t5_snapshot_path=str(embedded_t5),
        t5_snapshot_file_sha256s=t5_digests,
        conditioning_before=before,
        conditioning_after=after,
    )


@contextmanager
def _offline_transformers_environment() -> Iterator[None]:
    """Prevent an accidental network fallback while loading the local snapshot."""

    requested = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    }
    previous = {name: os.environ.get(name) for name in requested}
    os.environ.update(requested)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def load_local_model(
    config_resolution: ResolvedModelConfig,
    checkpoint_path: str | os.PathLike[str],
    *,
    device: str = "cuda",
    model_half: bool = True,
    expected_checkpoint_sha256: str | None = None,
) -> ModelRuntime:
    """Load the verified local files through the official SA3 implementation.

    This function deliberately has no repository identifier, token, or download
    option.  A missing checkpoint is surfaced to the caller (and therefore to
    the license gate) instead of triggering a network workaround.
    """

    resolved_path = Path(config_resolution.resolved_config_path)
    if sha256_file(resolved_path) != config_resolution.resolved_sha256:
        raise ValueError("resolved model config changed after immutable resolution")
    if sha256_file(config_resolution.original_copy_path) != config_resolution.original_sha256:
        raise ValueError("retained original model config changed after resolution")
    if sha256_file(config_resolution.diff_path) != config_resolution.diff_sha256:
        raise ValueError("retained model config diff changed after resolution")

    checkpoint = Path(checkpoint_path).resolve(strict=True)
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    if checkpoint.name.endswith(".incomplete"):
        raise ValueError(f"refusing to load an incomplete checkpoint: {checkpoint}")

    checkpoint_sha256 = sha256_file(checkpoint)
    if expected_checkpoint_sha256 is not None:
        if len(expected_checkpoint_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in expected_checkpoint_sha256
        ):
            raise ValueError("expected_checkpoint_sha256 must be 64 lowercase hex characters")
        if checkpoint_sha256 != expected_checkpoint_sha256:
            raise ValueError(
                "checkpoint SHA-256 mismatch: "
                f"expected {expected_checkpoint_sha256}, got {checkpoint_sha256}"
            )

    model_config = _read_json_object(resolved_path)
    conditioner = _prompt_t5_conditioner(model_config)
    if conditioner.get("model_path") != config_resolution.t5_snapshot_path:
        raise ValueError("resolved config no longer points at the verified embedded T5Gemma")
    if "repo_id" in conditioner or "subfolder" in conditioner:
        raise ValueError("resolved config still contains a remote conditioner reference")

    # Imports stay local so repository validation and license-gate reporting do
    # not initialize CUDA or import the model stack.
    with _offline_transformers_environment():
        from stable_audio_3.loading_utils import load_diffusion_cond
        from stable_audio_3.model import StableAudioModel

        model = load_diffusion_cond(
            model_config,
            str(checkpoint),
            device=device,
            model_half=model_half,
        )
    model.use_lora = False
    model.lora_names = []
    official_model = StableAudioModel(model, model_config, device, model_half)
    # The proxy is activated only for the one run that initialized the shared
    # budget environment. CPU contract tests and ordinary imports remain
    # side-effect free; every parent/child live ``generate`` call is metered.
    from sa3_smoke.budget import BudgetedStableAudioModel, ExecutionBudget

    if ExecutionBudget.from_environment() is not None:
        official_model = BudgetedStableAudioModel(official_model)
    return ModelRuntime(
        stable_audio_model=official_model,
        config_resolution=config_resolution,
        checkpoint_path=str(checkpoint),
        checkpoint_sha256=checkpoint_sha256,
        device=str(device),
        model_half=bool(model_half),
    )


__all__ = [
    "DEFAULT_REQUIRED_T5_FILES",
    "ModelRuntime",
    "ResolvedModelConfig",
    "load_local_model",
    "resolve_local_model_config",
]

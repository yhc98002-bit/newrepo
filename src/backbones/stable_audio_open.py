"""License-gated, offline-only Stable Audio Open 1.0 adapter."""

from __future__ import annotations

import copy
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from backbones.contracts import (
    DEFAULT_SAO_CONFIG,
    BackboneConfigurationError,
    BackbonePreflight,
    GenerationMeasurement,
    GenerationRequest,
    load_backbone_config,
    sha256_file,
    strict_json_object,
)
from backbones.license_gate import (
    license_block_from_config,
    validate_access_receipt,
    validate_core_authorization,
    validate_runtime_authorization,
)
from backbones.runtime import CudaTelemetry
from backbones.sao_mini_smoke import validate_sao_mini_smoke_evidence
from backbones.sao_t5 import T5_BUNDLE_LAYOUT, T5_MODEL_NAME, conditioning_bundle_record
from sa3_smoke.audio import save_float_wav_exclusive

HF_TOKEN_ENVIRONMENT_VARIABLES = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)


def _prompt_t5_conditioner(model_config: dict[str, Any]) -> dict[str, Any]:
    try:
        conditioning = model_config["model"]["conditioning"]
        conditioners = conditioning["configs"]
    except (KeyError, TypeError) as exc:
        raise BackboneConfigurationError(
            "SAO model config is missing model.conditioning.configs"
        ) from exc
    if conditioning.get("cond_dim") != 768 or not isinstance(conditioners, list):
        raise BackboneConfigurationError("SAO T5 conditioning layout is invalid")
    prompt_entries = [
        entry for entry in conditioners if isinstance(entry, dict) and entry.get("id") == "prompt"
    ]
    t5_entries = [
        entry for entry in conditioners if isinstance(entry, dict) and entry.get("type") == "t5"
    ]
    if len(prompt_entries) != 1 or len(t5_entries) != 1 or prompt_entries[0] is not t5_entries[0]:
        raise BackboneConfigurationError("SAO config requires exactly one prompt/T5 conditioner")
    conditioner = prompt_entries[0]
    configuration = conditioner.get("config")
    if configuration != {"t5_model_name": T5_MODEL_NAME, "max_length": 128}:
        raise BackboneConfigurationError("SAO prompt/T5 conditioner config is unexpected")
    return configuration


def _verify_receipt_file(
    snapshot: Path,
    row: dict[str, Any],
) -> Path:
    relative = Path(str(row["snapshot_path"]))
    source = snapshot / relative
    cursor = snapshot
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise BackboneConfigurationError(f"SAO T5 source may not be a symlink: {relative}")
    if not source.is_file():
        raise BackboneConfigurationError(f"SAO T5 source file is absent: {relative}")
    if source.stat().st_size != row["size_bytes"] or sha256_file(source) != row["sha256"]:
        raise BackboneConfigurationError(f"SAO T5 source changed after receipt: {relative}")
    return source.resolve(strict=True)


@contextmanager
def _local_t5_factory_config(
    snapshot: Path,
    model_config: dict[str, Any],
    verified_files: list[dict[str, Any]],
):
    """Yield an in-memory config pointing at one ephemeral receipt-bound bundle."""

    _prompt_t5_conditioner(model_config)
    bundle_record = conditioning_bundle_record(verified_files)
    verified_sources = {
        row["bundle_path"]: _verify_receipt_file(snapshot, row)
        for row in bundle_record["files"]
    }
    encoder_config = strict_json_object(verified_sources["config.json"])
    if (
        encoder_config.get("_name_or_path") != T5_MODEL_NAME
        or encoder_config.get("model_type") != "t5"
        or encoder_config.get("architectures") != ["T5EncoderModel"]
        or encoder_config.get("d_model") != 768
    ):
        raise BackboneConfigurationError("SAO local text encoder is not the expected T5-base")
    tokenizer_config = strict_json_object(verified_sources["tokenizer_config.json"])
    if tokenizer_config.get("tokenizer_class") != "T5Tokenizer":
        raise BackboneConfigurationError("SAO local tokenizer is not the expected T5 tokenizer")

    resolved_config = copy.deepcopy(model_config)
    resolved_conditioner = _prompt_t5_conditioner(resolved_config)
    with tempfile.TemporaryDirectory(prefix="sao-t5-base-") as temporary:
        bundle = Path(temporary).resolve()
        for bundle_name, _snapshot_name in T5_BUNDLE_LAYOUT:
            (bundle / bundle_name).symlink_to(verified_sources[bundle_name])
        if {path.name for path in bundle.iterdir()} != set(verified_sources):
            raise BackboneConfigurationError("SAO ephemeral T5 bundle closure is invalid")
        resolved_conditioner["model_path"] = str(bundle)
        yield resolved_config, str(bundle_record["conditioning_bundle_sha256"])


@contextmanager
def _offline_transformers_environment():
    """Reject credentials and make local-only factory resolution fail closed."""

    present_tokens = [name for name in HF_TOKEN_ENVIRONMENT_VARIABLES if name in os.environ]
    if present_tokens:
        raise BackboneConfigurationError(
            f"SAO model loading refuses token environment variables: {present_tokens}"
        )
    requested = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
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


class StableAudioOpenAdapter:
    """SAO adapter that cannot reach loading without two explicit offline gate records."""

    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_SAO_CONFIG,
        evidence_dir: str | Path | None = None,
        snapshot_dir: str | Path | None = None,
        access_receipt_path: str | Path | None = None,
        runtime_authorization_path: str | Path | None = None,
        execution_scope: str = "MINI_SMOKE",
        mini_smoke_result_path: str | Path | None = None,
        mini_smoke_result_sha256: str | None = None,
        device: str = "cuda",
    ) -> None:
        self.config, self.config_sha256 = load_backbone_config(config_path)
        if self.config["logical_name"] != "stable-audio-open-1.0":
            raise BackboneConfigurationError("SAO adapter received a different model config")
        self.logical_name = self.config["logical_name"]
        self.model_id = self.config["model_id"]
        self.license_identifier = self.config["license_identifier"]
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        snapshot_env = self.config["adapter"]["local_snapshot_environment_variable"]
        snapshot_value = snapshot_dir or os.environ.get(snapshot_env)
        self.snapshot_dir = Path(snapshot_value) if snapshot_value else None
        self.access_receipt_path = Path(access_receipt_path) if access_receipt_path else None
        self.runtime_authorization_path = (
            Path(runtime_authorization_path) if runtime_authorization_path else None
        )
        if execution_scope not in {"MINI_SMOKE", "BENCHMARK_CORE"}:
            raise ValueError("SAO execution_scope must be MINI_SMOKE or BENCHMARK_CORE")
        self.execution_scope = execution_scope
        self.mini_smoke_result_path = (
            Path(mini_smoke_result_path) if mini_smoke_result_path is not None else None
        )
        self.mini_smoke_result_sha256 = mini_smoke_result_sha256
        if device != "cuda" and not (device.startswith("cuda:") and device[5:].isdigit()):
            raise ValueError("Stable Audio Open requires device='cuda' or 'cuda:N'")
        self.device = device
        self._preflight: BackbonePreflight | None = None
        self._model: Any | None = None
        self._load_wall_seconds: float | None = None
        self._weight_file_sha256: str | None = None
        self._conditioning_bundle_sha256: str | None = None

    def preflight(self) -> BackbonePreflight:
        """Return the adjudicated blocker or verify both later offline gate records."""

        if self._preflight is not None:
            return self._preflight
        blocker = license_block_from_config(self.config)
        if (
            self.access_receipt_path is None
            or self.runtime_authorization_path is None
            or self.snapshot_dir is None
        ):
            raise blocker
        receipt = validate_access_receipt(
            self.access_receipt_path,
            expected_model_id=self.model_id,
            expected_snapshot_dir=self.snapshot_dir,
        )
        if self.execution_scope == "MINI_SMOKE":
            authorization = validate_runtime_authorization(
                self.runtime_authorization_path,
                expected_config_sha256=self.config_sha256,
                expected_receipt_sha256=receipt["receipt_sha256"],
                expected_decision_id="D-0037",
                expected_generations=3,
            )
            status = "READY_FOR_MINI_SMOKE"
        else:
            if self.mini_smoke_result_path is None or self.mini_smoke_result_sha256 is None:
                raise BackboneConfigurationError(
                    "SAO core preflight requires a measured mini-smoke result path and SHA-256"
                )
            if sha256_file(self.mini_smoke_result_path) != self.mini_smoke_result_sha256:
                raise BackboneConfigurationError("SAO core mini-smoke result hash mismatch")
            validate_sao_mini_smoke_evidence(
                self.mini_smoke_result_path,
                expected_config_sha256=self.config_sha256,
                expected_receipt=receipt,
                expected_snapshot_dir=self.snapshot_dir,
            )
            authorization = validate_core_authorization(
                self.runtime_authorization_path,
                expected_config_sha256=self.config_sha256,
                expected_receipt_sha256=receipt["receipt_sha256"],
                expected_mini_smoke_result_sha256=self.mini_smoke_result_sha256,
            )
            status = "READY_FOR_CORE"
        self.license_identifier = receipt["license_identifier"]
        self._preflight = BackbonePreflight(
            status=status,
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={
                "receipt": receipt,
                "runtime_authorization": authorization,
                "runtime_authorization_path": str(self.runtime_authorization_path.resolve()),
                "runtime_authorization_sha256": sha256_file(self.runtime_authorization_path),
                "snapshot_dir": str(self.snapshot_dir.resolve()),
                "network_downloads_allowed": False,
            },
        )
        return self._preflight

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self.preflight()
        present_tokens = [name for name in HF_TOKEN_ENVIRONMENT_VARIABLES if name in os.environ]
        if present_tokens:
            raise BackboneConfigurationError(
                f"SAO model loading refuses token environment variables: {present_tokens}"
            )
        assert self.snapshot_dir is not None
        started = time.perf_counter()
        snapshot = self.snapshot_dir.resolve()
        config_path = snapshot / "model_config.json"
        safetensors_path = snapshot / "model.safetensors"
        checkpoint_path = snapshot / "model.ckpt"
        if not config_path.is_file():
            raise BackboneConfigurationError("SAO snapshot lacks model_config.json")
        if safetensors_path.is_file():
            weight_path = safetensors_path
        elif checkpoint_path.is_file():
            weight_path = checkpoint_path
        else:
            raise BackboneConfigurationError(
                "SAO snapshot lacks model.safetensors and model.ckpt"
            )
        weight_relative = weight_path.relative_to(snapshot).as_posix()
        verified_files = self._preflight.details["receipt"]["verified_files"]
        weight_rows = [row for row in verified_files if row["path"] == weight_relative]
        if len(weight_rows) != 1:
            raise BackboneConfigurationError("SAO weight is not uniquely bound by receipt")
        weight_row = weight_rows[0]
        if (
            weight_row.get("hash_verified") is not True
            or weight_row.get("size_bytes") != weight_path.stat().st_size
            or weight_row.get("sha256") != sha256_file(weight_path)
        ):
            raise BackboneConfigurationError("SAO selected weight changed after receipt preflight")
        self._weight_file_sha256 = str(weight_row["sha256"])
        config_rows = [row for row in verified_files if row["path"] == "model_config.json"]
        if len(config_rows) != 1:
            raise BackboneConfigurationError("SAO model config is not uniquely bound by receipt")
        config_row = config_rows[0]
        if (
            config_row.get("hash_verified") is not True
            or config_row.get("size_bytes") != config_path.stat().st_size
            or config_row.get("sha256") != sha256_file(config_path)
        ):
            raise BackboneConfigurationError("SAO model config changed after receipt preflight")
        model_config = strict_json_object(config_path)
        with _local_t5_factory_config(
            snapshot,
            model_config,
            verified_files,
        ) as (resolved_config, conditioning_bundle_sha256), _offline_transformers_environment():
            try:
                from stable_audio_tools.models.factory import create_model_from_config
                from stable_audio_tools.models.utils import load_ckpt_state_dict
            except ImportError as exc:
                raise ImportError(
                    "stable-audio-tools local model factory is required after the license "
                    "gate clears"
                ) from exc
            model = create_model_from_config(resolved_config)
            model.load_state_dict(load_ckpt_state_dict(str(weight_path)))
        self._conditioning_bundle_sha256 = conditioning_bundle_sha256
        expected_sample_rate = int(self.config["generation"]["sample_rate"])
        if getattr(model, "sample_rate", None) != expected_sample_rate:
            raise BackboneConfigurationError("SAO local model sample rate differs from config")
        self._model = model.to(self.device).eval()
        self._load_wall_seconds = time.perf_counter() - started

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        """Run one official offline SAO call and retain its waveform without clobbering."""

        if os.path.lexists(request.output_path):
            raise FileExistsError(request.output_path)
        max_duration = float(self.config["mini_smoke_caps"]["max_clip_seconds"])
        if request.duration_seconds > max_duration:
            raise ValueError(f"request exceeds {max_duration}-second SAO mini-smoke cap")
        if request.duration_seconds != 30.0:
            raise ValueError("SAO v2 execution is frozen to exactly 30-second requests")
        self._ensure_loaded()
        try:
            from stable_audio_tools.inference.generation import generate_diffusion_cond
        except ImportError as exc:
            raise ImportError("stable-audio-tools generation helper is unavailable") from exc
        diffusion = getattr(self._model, "model", None)
        if diffusion is None or not hasattr(diffusion, "register_forward_hook"):
            raise RuntimeError("cannot measure SAO NFE: diffusion forward-hook surface is absent")
        nfe = {"calls": 0}

        def count_forward(_module: Any, _inputs: Any, _output: Any) -> None:
            nfe["calls"] += 1

        hook = diffusion.register_forward_hook(count_forward)
        generation = self.config["generation"]
        telemetry = CudaTelemetry(self.device)
        try:
            import torch

            with telemetry.measured() as measured:
                output = generate_diffusion_cond(
                    self._model,
                    steps=int(generation["inference_steps"]),
                    cfg_scale=float(generation["cfg_scale"]),
                    conditioning=[
                        {
                            "prompt": request.prompt,
                            "seconds_start": 0,
                            "seconds_total": request.duration_seconds,
                        }
                    ],
                    batch_size=1,
                    sample_size=1_323_000,
                    sample_rate=int(generation["sample_rate"]),
                    seed=request.seed,
                    device=self.device,
                    adapt_duration_to_conditioning=False,
                    sampler_type=generation["sampler_type"],
                )
        finally:
            hook.remove()
        if nfe["calls"] <= 0:
            raise RuntimeError("SAO call produced no measured diffusion forwards")
        waveform = output.audio if hasattr(output, "audio") else output
        if hasattr(waveform, "detach"):
            waveform = waveform.detach().to("cpu", dtype=torch.float32).numpy()
        array = np.asarray(waveform, dtype=np.float32)
        while array.ndim > 2:
            if array.shape[0] != 1:
                raise RuntimeError(f"SAO mini-smoke expected batch one, got shape {array.shape}")
            array = array[0]
        if array.ndim != 2:
            raise RuntimeError(f"SAO output must be channels x frames, got shape {array.shape}")
        save_float_wav_exclusive(
            request.output_path,
            array,
            int(generation["sample_rate"]),
            channels_first=True,
        )
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=int(generation["sample_rate"]),
            requested_steps=int(generation["inference_steps"]),
            actual_nfe=nfe["calls"],
            wall_seconds=float(measured["wall_seconds"]),
            peak_allocated_bytes=int(measured["peak_allocated_bytes"]),
            peak_reserved_bytes=int(measured["peak_reserved_bytes"]),
            metadata={
                "load_wall_seconds": self._load_wall_seconds,
                "config_sha256": self.config_sha256,
                "execution_scope": self.execution_scope,
                "requested_sample_size": 1_323_000,
                "weight_file_sha256": self._weight_file_sha256,
                "conditioning_bundle_sha256": self._conditioning_bundle_sha256,
                "resolved_provider_revision": self._preflight.details["receipt"][
                    "resolved_provider_revision"
                ],
                "sampler_type": generation["sampler_type"],
            },
        )

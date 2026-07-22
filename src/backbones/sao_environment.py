"""CPU-only validation for the dedicated Stable Audio Open runtime.

The shared SA3 runtime intentionally uses NumPy 2.  Stable Audio Tools at the
registered commit, however, pins the binary PyWavelets 1.4.1 wheel.  This
module validates the dedicated SAO closure before any CUDA device is exposed.
It never downloads packages, loads the SAO checkpoint, or generates audio.
"""

from __future__ import annotations

import gc
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import resource
import sys
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from backbones.contracts import sha256_file, strict_json_object

EXPECTED_DISTRIBUTIONS = {
    "numpy": "1.26.4",
    "pywavelets": "1.4.1",
    "safetensors": "0.7.0",
    "scipy": "1.15.3",
    "sentencepiece": "0.1.99",
    "soundfile": "0.13.1",
    "stable-audio-tools": "0.0.20",
    "torch": "2.7.1",
    "torchaudio": "2.7.1",
    "transformers": "5.8.0",
}
EXPECTED_PYTHON = "3.10.12"
EXPECTED_STABLE_AUDIO_TOOLS_URL = (
    "https://github.com/Stability-AI/stable-audio-tools/archive/"
    "3241adba4fc2a85cf5b29d9eb68d42f40a28e820.tar.gz"
)
EXPECTED_SAO_REVISION = "f21265c1e2710b3bd2386596943f0007f55f802e"
STABLE_AUDIO_TOOLS_LORA_RELATIVE_PATH = Path(
    "lib/python3.10/site-packages/stable_audio_tools/models/lora/__init__.py"
)
EXPECTED_STABLE_AUDIO_TOOLS_LORA_ORIGINAL_SHA256 = (
    "ec32c74f7884a0928889aaef90a054229a8fa2354eb001fae9f8e9222775cbf1"
)
EXPECTED_STABLE_AUDIO_TOOLS_LORA_PATCHED_SHA256 = (
    "104174f6acabb438e652fe3c76889988dee4b9e5f38b8d2d9893a47f01ace595"
)
EXPECTED_INFERENCE_IMPORT_PATCH_SHA256 = (
    "df732865be587fa63fca797cdc19679254b15a86c30b0575b701a0a51c3677c1"
)
TOKEN_ENVIRONMENT_VARIABLES = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)
REQUIRED_IMPORTS = (
    "numpy",
    "pywt",
    "safetensors",
    "scipy",
    "sentencepiece",
    "soundfile",
    "torch",
    "torchaudio",
    "transformers",
    "stable_audio_tools",
    "stable_audio_tools.inference.generation",
    "stable_audio_tools.models.conditioners",
    "stable_audio_tools.models.factory",
    "stable_audio_tools.models.pretransforms",
    "stable_audio_tools.models.utils",
    "stable_audio_tools.models.wavelets",
    "backbones.sao_mini_smoke",
    "backbones.sao_t5",
    "backbones.stable_audio_open",
)


class SaoEnvironmentError(RuntimeError):
    """Raised when the dedicated SAO runtime is not CPU-ready."""


def _canonical_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _module_path(module: Any) -> str | None:
    location = getattr(module, "__file__", None)
    if isinstance(location, str) and location:
        return str(Path(location).resolve())
    paths = getattr(module, "__path__", None)
    if paths:
        first = next(iter(paths), None)
        if first:
            return str(Path(first).resolve())
    return None


def _within(path: str | Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def collect_distribution_records() -> list[dict[str, Any]]:
    """Return installed versions, sources, requirements, and metadata hashes."""

    records: list[dict[str, Any]] = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not isinstance(name, str) or not name:
            continue
        direct_text = distribution.read_text("direct_url.json")
        direct_url = json.loads(direct_text) if direct_text is not None else None
        metadata_path = Path(distribution._path) / "METADATA"  # type: ignore[attr-defined]
        record_path = Path(distribution._path) / "RECORD"  # type: ignore[attr-defined]
        records.append(
            {
                "name": _canonical_name(name),
                "metadata_name": name,
                "version": distribution.version,
                "location": str(Path(distribution.locate_file("")).resolve()),
                "direct_url": direct_url,
                "requires_dist": sorted(distribution.requires or ()),
                "metadata_sha256": (
                    sha256_file(metadata_path) if metadata_path.is_file() else None
                ),
                "record_sha256": sha256_file(record_path) if record_path.is_file() else None,
            }
        )
    return sorted(records, key=lambda row: row["name"])


def validate_distribution_records(
    records: Iterable[Mapping[str, Any]], environment_prefix: Path
) -> dict[str, Any]:
    """Fail closed on version, source, ABI-pair, or prefix drift."""

    by_name: dict[str, Mapping[str, Any]] = {}
    failures: list[str] = []
    if platform.python_version() != EXPECTED_PYTHON:
        failures.append(f"Python must equal {EXPECTED_PYTHON}, got {platform.python_version()}")
    for record in records:
        name = record.get("name")
        if not isinstance(name, str):
            failures.append("distribution record lacks a canonical name")
            continue
        if name in by_name:
            failures.append(f"duplicate distribution: {name}")
            continue
        by_name[name] = record

    for name, expected_version in EXPECTED_DISTRIBUTIONS.items():
        record = by_name.get(name)
        if record is None:
            failures.append(f"missing required distribution: {name}")
            continue
        if record.get("version") != expected_version:
            failures.append(
                f"{name} version must equal {expected_version}, got {record.get('version')}"
            )
        location = record.get("location")
        if not isinstance(location, str) or not _within(location, environment_prefix):
            failures.append(f"{name} is imported outside the dedicated environment")

    stable_tools = by_name.get("stable-audio-tools")
    if stable_tools is not None:
        direct = stable_tools.get("direct_url")
        observed_url = direct.get("url") if isinstance(direct, Mapping) else None
        if observed_url != EXPECTED_STABLE_AUDIO_TOOLS_URL:
            failures.append("stable-audio-tools source URL or registered commit drifted")

    numpy_version = by_name.get("numpy", {}).get("version")
    wavelet_version = by_name.get("pywavelets", {}).get("version")
    abi_pair = {
        "numpy": numpy_version,
        "pywavelets": wavelet_version,
        "reason": (
            "Stable Audio Tools 3241adba pins the PyWavelets 1.4.1 binary wheel; "
            "NumPy 1.26.4 retains the matching NumPy 1.x C ABI."
        ),
    }
    if (numpy_version, wavelet_version) != ("1.26.4", "1.4.1"):
        failures.append("SAO NumPy/PyWavelets ABI pair must be exactly 1.26.4/1.4.1")
    return {"passed": not failures, "failures": failures, "abi_pair": abi_pair}


def run_cpu_import_probe(environment_prefix: Path) -> dict[str, Any]:
    """Exercise the repaired ABI and every required import with CUDA hidden."""

    environment_prefix = environment_prefix.resolve(strict=True)
    failures: list[str] = []
    if Path(sys.prefix).resolve() != environment_prefix:
        failures.append(
            f"sys.prefix must equal {environment_prefix}, got {Path(sys.prefix).resolve()}"
        )
    present_tokens = [name for name in TOKEN_ENVIRONMENT_VARIABLES if name in os.environ]
    if present_tokens:
        failures.append(f"token environment variables are present: {present_tokens}")
    if os.environ.get("CUDA_VISIBLE_DEVICES") not in {"", "-1"}:
        failures.append("CPU validation requires CUDA_VISIBLE_DEVICES='' or '-1'")
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
        if os.environ.get(name) != "1":
            failures.append(f"{name} must equal 1")

    modules: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_IMPORTS:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - evidence preserves the precise import class
            failures.append(f"import {name} failed: {type(exc).__name__}: {exc}")
            continue
        modules[name] = {
            "path": _module_path(module),
            "version": getattr(module, "__version__", None),
        }

    try:
        import numpy as np
        import pywt

        signal = np.arange(32, dtype=np.float64)
        coefficients = pywt.dwt(signal, "db1")
        if not all(np.isfinite(coefficient).all() for coefficient in coefficients):
            failures.append("PyWavelets DWT returned non-finite coefficients")
    except Exception as exc:  # noqa: BLE001 - this is the repaired binary-ABI boundary
        failures.append(f"NumPy/PyWavelets ABI exercise failed: {type(exc).__name__}: {exc}")

    try:
        import torch

        if torch.cuda.is_available():
            failures.append("CUDA became available during the CPU-only validation")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"torch CPU availability check failed: {type(exc).__name__}: {exc}")

    distributions = collect_distribution_records()
    closure = validate_distribution_records(distributions, environment_prefix)
    failures.extend(closure["failures"])
    lora_init = environment_prefix / STABLE_AUDIO_TOOLS_LORA_RELATIVE_PATH
    lora_init_sha256 = sha256_file(lora_init)
    if lora_init_sha256 != EXPECTED_STABLE_AUDIO_TOOLS_LORA_PATCHED_SHA256:
        failures.append("Stable Audio Tools inference-only import patch identity drifted")
    return {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "passed": not failures,
        "failures": failures,
        "python": platform.python_version(),
        "sys_executable": str(Path(sys.executable).resolve()),
        "sys_prefix": str(Path(sys.prefix).resolve()),
        "modules": modules,
        "closure": closure,
        "distributions": distributions,
        "stable_audio_tools_lora_init": {
            "path": str(lora_init.resolve()),
            "original_sha256": EXPECTED_STABLE_AUDIO_TOOLS_LORA_ORIGINAL_SHA256,
            "patched_sha256": lora_init_sha256,
        },
    }


def run_cpu_factory_probe(
    *,
    snapshot_dir: Path,
    access_receipt_path: Path,
    runtime_authorization_path: Path,
    backbone_config_path: Path,
) -> dict[str, Any]:
    """Construct the official factory graph on CPU without loading SAO weights."""

    import torch

    if torch.cuda.is_available():
        raise SaoEnvironmentError("factory validation requires CUDA to remain hidden")
    if any(name in os.environ for name in TOKEN_ENVIRONMENT_VARIABLES):
        raise SaoEnvironmentError("factory validation refuses token environment variables")

    from backbones.stable_audio_open import (
        StableAudioOpenAdapter,
        _local_t5_factory_config,
        _offline_transformers_environment,
    )

    adapter = StableAudioOpenAdapter(
        config_path=backbone_config_path,
        snapshot_dir=snapshot_dir,
        access_receipt_path=access_receipt_path,
        runtime_authorization_path=runtime_authorization_path,
        execution_scope="MINI_SMOKE",
        device="cuda",
    )
    preflight = adapter.preflight()
    receipt = preflight.details["receipt"]
    if receipt["resolved_provider_revision"] != EXPECTED_SAO_REVISION:
        raise SaoEnvironmentError("official SAO snapshot revision drifted")
    model_config_path = snapshot_dir / "model_config.json"
    model_config = strict_json_object(model_config_path)

    started = time.perf_counter()
    with (
        _local_t5_factory_config(
            snapshot_dir.resolve(strict=True),
            model_config,
            receipt["verified_files"],
        ) as (resolved_config, conditioning_bundle_sha256),
        _offline_transformers_environment(),
    ):
        from stable_audio_tools.models.factory import create_model_from_config

        model = create_model_from_config(resolved_config)
    elapsed = time.perf_counter() - started
    sample_rate = getattr(model, "sample_rate", None)
    audio_channels = getattr(model, "io_channels", None)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    if sample_rate != 44_100:
        raise SaoEnvironmentError(f"factory sample rate is {sample_rate}, expected 44100")
    if parameter_count <= 0:
        raise SaoEnvironmentError("factory graph has no parameters")
    model_class = f"{type(model).__module__}.{type(model).__qualname__}"
    del model
    gc.collect()
    return {
        "schema_version": 1,
        "status": "PASS",
        "factory_model_class": model_class,
        "factory_wall_seconds": elapsed,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "sample_rate": sample_rate,
        "audio_channels": audio_channels,
        "parameter_count": parameter_count,
        "model_config_path": str(model_config_path.resolve(strict=True)),
        "model_config_sha256": sha256_file(model_config_path),
        "conditioning_bundle_sha256": conditioning_bundle_sha256,
        "resolved_provider_revision": receipt["resolved_provider_revision"],
        "checkpoint_loaded": False,
        "generation_calls": 0,
        "cuda_available": torch.cuda.is_available(),
    }


def environment_manifest(
    *,
    import_probe: Mapping[str, Any],
    factory_probe: Mapping[str, Any],
    package_freeze_path: Path,
    base_lock_path: Path,
    numpy_wheel_path: Path,
    inference_import_patch_path: Path,
) -> dict[str, Any]:
    """Bind CPU evidence to the complete freeze, base lock, and ABI wheel."""

    freeze = package_freeze_path.resolve(strict=True)
    lock = base_lock_path.resolve(strict=True)
    wheel = numpy_wheel_path.resolve(strict=True)
    inference_patch = inference_import_patch_path.resolve(strict=True)
    patch_sha256 = sha256_file(inference_patch)
    if patch_sha256 != EXPECTED_INFERENCE_IMPORT_PATCH_SHA256:
        raise SaoEnvironmentError("inference-only import patch file identity drifted")
    payload = {
        "schema_version": 1,
        "status": "CPU_VALIDATED_READY_FOR_GOVERNED_MINI_SMOKE",
        "import_probe": dict(import_probe),
        "factory_probe": dict(factory_probe),
        "package_freeze_path": str(freeze),
        "package_freeze_sha256": sha256_file(freeze),
        "base_lock_path": str(lock),
        "base_lock_sha256": sha256_file(lock),
        "numpy_wheel_path": str(wheel),
        "numpy_wheel_sha256": sha256_file(wheel),
        "inference_import_patch_path": str(inference_patch),
        "inference_import_patch_sha256": patch_sha256,
        "network_used": False,
        "token_used": False,
        "gpu_used": False,
        "generation_calls": 0,
    }
    payload["manifest_identity_sha256"] = hashlib.sha256(
        json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return payload

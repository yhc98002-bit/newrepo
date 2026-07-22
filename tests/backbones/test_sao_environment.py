from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from backbones.sao_environment import (
    EXPECTED_DISTRIBUTIONS,
    EXPECTED_INFERENCE_IMPORT_PATCH_SHA256,
    EXPECTED_PYTHON,
    EXPECTED_STABLE_AUDIO_TOOLS_LORA_ORIGINAL_SHA256,
    EXPECTED_STABLE_AUDIO_TOOLS_LORA_PATCHED_SHA256,
    EXPECTED_STABLE_AUDIO_TOOLS_URL,
    validate_distribution_records,
)

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_is_pinned_to_project_python() -> None:
    assert EXPECTED_PYTHON == "3.10.12"


def test_inference_import_patch_only_guards_missing_training_dependency() -> None:
    patch_path = ROOT / "environment/sao/stable_audio_tools_inference_import.patch"
    patch = patch_path.read_text(encoding="utf-8")

    assert 'if exc.name != "pytorch_lightning":' in patch
    assert "from .callbacks import LoRASafetensorsCheckpoint, StepOffsetCallback" in patch
    assert "from .loader import load_and_apply_loras" in patch
    assert "models/dit.py" not in patch
    assert hashlib.sha256(patch_path.read_bytes()).hexdigest() == (
        EXPECTED_INFERENCE_IMPORT_PATCH_SHA256
    )
    assert EXPECTED_STABLE_AUDIO_TOOLS_LORA_ORIGINAL_SHA256 != (
        EXPECTED_STABLE_AUDIO_TOOLS_LORA_PATCHED_SHA256
    )


def _records(prefix: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, version in EXPECTED_DISTRIBUTIONS.items():
        result.append(
            {
                "name": name,
                "version": version,
                "location": str(prefix / "lib/python3.10/site-packages"),
                "direct_url": (
                    {"url": EXPECTED_STABLE_AUDIO_TOOLS_URL, "archive_info": {}}
                    if name == "stable-audio-tools"
                    else None
                ),
            }
        )
    return result


def test_exact_upstream_pin_and_numpy1_abi_pair_pass(tmp_path: Path) -> None:
    result = validate_distribution_records(_records(tmp_path), tmp_path)

    assert result["passed"] is True
    assert result["failures"] == []
    assert result["abi_pair"] == {
        "numpy": "1.26.4",
        "pywavelets": "1.4.1",
        "reason": (
            "Stable Audio Tools 3241adba pins the PyWavelets 1.4.1 binary wheel; "
            "NumPy 1.26.4 retains the matching NumPy 1.x C ABI."
        ),
    }


def test_regression_rejects_original_numpy2_pywavelets14_pair(tmp_path: Path) -> None:
    records = _records(tmp_path)
    next(row for row in records if row["name"] == "numpy")["version"] = "2.2.6"

    result = validate_distribution_records(records, tmp_path)

    assert result["passed"] is False
    assert any("numpy version must equal 1.26.4" in failure for failure in result["failures"])
    assert any("ABI pair must be exactly" in failure for failure in result["failures"])


def test_pywavelets_upgrade_is_not_silently_substituted(tmp_path: Path) -> None:
    records = _records(tmp_path)
    next(row for row in records if row["name"] == "pywavelets")["version"] = "1.8.0"

    result = validate_distribution_records(records, tmp_path)

    assert result["passed"] is False
    assert any("pywavelets version must equal 1.4.1" in failure for failure in result["failures"])


def test_registered_stable_audio_tools_commit_is_required(tmp_path: Path) -> None:
    records = copy.deepcopy(_records(tmp_path))
    stable_tools = next(row for row in records if row["name"] == "stable-audio-tools")
    stable_tools["direct_url"] = {"url": "https://example.invalid/substitute.tar.gz"}

    result = validate_distribution_records(records, tmp_path)

    assert result["passed"] is False
    assert any("registered commit drifted" in failure for failure in result["failures"])


def test_foreign_site_package_is_rejected(tmp_path: Path) -> None:
    records = _records(tmp_path)
    next(row for row in records if row["name"] == "numpy")["location"] = "/tmp/foreign"

    result = validate_distribution_records(records, tmp_path)

    assert result["passed"] is False
    assert any("outside the dedicated environment" in failure for failure in result["failures"])

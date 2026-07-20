from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts" / "v2"


def _json(name: str):
    return json.loads((PROMPTS / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _builder_module():
    path = ROOT / "prompts" / "build_v2_prompts.py"
    spec = importlib.util.spec_from_file_location("build_v2_prompts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_prompt_package_counts_and_unique_ids() -> None:
    expected = {
        "vocal_instrumental.json": 24,
        "tempo.json": 30,
        "integrity.json": 18,
        "structure_exploratory.json": 18,
    }
    all_ids: list[str] = []
    for name, count in expected.items():
        rows = _json(name)["rows"]
        assert len(rows) == count
        assert all(row["base_prompt"] and row["fixed_suffix"] for row in rows)
        all_ids.extend(row["prompt_id"] for row in rows)
    assert len(all_ids) == 90
    assert len(set(all_ids)) == 90


def test_instrumental_primary_intervention_is_positive_only() -> None:
    payload = _json("vocal_instrumental.json")
    assert payload["primary_instrumental_intervention"] == "positive_only"
    instrumental = [row for row in payload["rows"] if row["request"] == "instrumental"]
    assert len(instrumental) == 12
    for row in instrumental:
        suffix = row["fixed_suffix"]
        assert suffix.startswith("A purely instrumental arrangement led throughout by ")
        assert all(token not in suffix.lower() for token in (" no ", "without", "exclude"))
        assert row["diagnostic_negation_suffix"].startswith("Instrumental only; no singing")


def test_tempo_bands_and_integrity_fixture_gate_are_frozen() -> None:
    tempo = _json("tempo.json")
    assert tempo["primary_octave_tolerance_ratio"] == 1.05
    assert tempo["sensitivity_octave_tolerance_ratio"] == 1.10
    assert sorted({row["target_bpm"] for row in tempo["rows"]}) == [
        60,
        72,
        84,
        96,
        108,
        120,
        132,
        144,
        156,
        168,
    ]
    assert _json("integrity.json")["synthetic_fixture_validation_required"] is True


def test_seed_registry_vectors_follow_builder_rule() -> None:
    registry = _json("seed_registry.json")
    builder = _builder_module()
    assert registry["root_indices"] == list(range(8))
    assert len(registry["models"]) == 3
    for row in registry["test_vectors"]:
        assert row["seed"] == builder.derive_seed(
            row["model_id"], row["prompt_id"], row["root_index"]
        )


def test_manifest_hashes_every_frozen_prompt_file() -> None:
    manifest = _json("manifest.json")
    assert manifest["total_prompt_rows"] == 90
    assert manifest["axis_row_counts"] == {
        "integrity": 18,
        "structure_exploratory": 18,
        "tempo": 30,
        "vocal_instrumental": 24,
    }
    for name, expected in manifest["files"].items():
        assert _sha256(PROMPTS / name) == expected

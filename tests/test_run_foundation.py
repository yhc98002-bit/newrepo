from __future__ import annotations

import inspect
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sa3_smoke.run_foundation as run_foundation_module
from sa3_smoke.artifacts import sha256_file
from sa3_smoke.run_foundation import (
    EXPECTED_CONFIG_SHA256,
    EXPECTED_HUGGINGFACE_REVISION,
    EXPECTED_MODEL_ID,
    EXPECTED_MODELSCOPE_REVISION,
    EXPECTED_STABLE_AUDIO_3_COMMIT,
    EXPECTED_STABLE_AUDIO_TOOLS_COMMIT,
    REQUIRED_T5_MANIFEST_FILES,
    SMOKE_NAMES,
    OrchestrationDependencies,
    _run_foundation_for_testing,
    _same_filesystem_object,
    _smoke_e_kwargs,
    run_foundation,
)

SNAPSHOT_FILES = (
    ".gitattributes",
    "LICENSE.md",
    "LICENSE_GEMMA.md",
    "NOTICE",
    "README.md",
    "Stable_Audio_3.0_Thumbnail_1x1.png",
    "configuration.json",
    "model.safetensors",
    "model_config.json",
    "svd_bases.pt",
    "t5gemma-b-b-ul2/README.md",
    *(f"t5gemma-b-b-ul2/{name}" for name in REQUIRED_T5_MANIFEST_FILES),
)


def test_live_entrypoint_hardcodes_authorization_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameters = inspect.signature(run_foundation).parameters

    assert "dependencies" not in parameters
    assert "expected_config_sha256" not in parameters
    assert "process_context" not in parameters
    assert "require_clean_git" not in parameters

    sentinel_dependencies = object()
    sentinel_outcome = object()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        run_foundation_module,
        "default_dependencies",
        lambda: sentinel_dependencies,
    )

    def fake_core(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return sentinel_outcome

    monkeypatch.setattr(run_foundation_module, "_run_foundation_core", fake_core)
    outcome = run_foundation(
        config_path=tmp_path / "config.json",
        repository_root=tmp_path,
        run_root=tmp_path / "runs",
    )

    assert outcome is sentinel_outcome
    assert captured["dependencies"] is sentinel_dependencies
    assert captured["expected_config_sha256"] == EXPECTED_CONFIG_SHA256
    assert captured["process_context"] is None
    assert captured["require_clean_git"] is True
    assert captured["live_execution"] is True


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_same_filesystem_object_accepts_distinct_paths_for_one_inode(tmp_path: Path) -> None:
    original = tmp_path / "original"
    alias = tmp_path / "alias"
    original.write_bytes(b"same artifact\n")
    alias.hardlink_to(original)

    assert original.resolve() != alias.resolve()
    assert _same_filesystem_object(original.resolve(), alias.resolve()) is True


def _foundation_fixture(tmp_path: Path) -> SimpleNamespace:
    repo = tmp_path / "repository"
    snapshot = tmp_path / "snapshot"
    repo.mkdir()
    snapshot.mkdir()
    (repo / "environment").mkdir()
    (repo / "provenance").mkdir()

    protocol = repo / "SMOKE_PROTOCOL.md"
    protocol.write_text("# frozen protocol v1\n", encoding="utf-8")
    (repo / "DECISIONS.md").write_text(
        "# append-only decisions\n"
        "SA3_FOUNDATION_SMOKE_AUTHORIZED = NO\n"
        "SA3_FOUNDATION_SMOKE_AUTHORIZED = YES\n",
        encoding="utf-8",
    )
    (repo / "SEED_REGISTRY.md").write_text(
        "# Seed registry (append-only)\n\n"
        "| Seed ID | Integer | Intended use | Supersedes |\n"
        "| --- | ---: | --- | --- |\n"
        "| S-0001 | 73193001 | fixture | none |\n"
        "| S-0002 | 73193002 | fixture | none |\n"
        "| S-0003 | 73193003 | fixture | none |\n"
        "| S-0004 | 73193004 | fixture | none |\n"
        "| S-0005 | 73193005 | fixture batch-one cost | none |\n"
        "| S-0006 | 73193006 | fixture | none |\n"
        "| S-0007 | 73193007 | fixture | none |\n",
        encoding="utf-8",
    )

    for relative in SNAPSHOT_FILES:
        artifact = snapshot / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"fixture:{relative}\n".encode())
    (snapshot / "weights.manifest.json").write_text("{}\n", encoding="utf-8")

    file_rows = [
        {
            "byte_size": (snapshot / relative).stat().st_size,
            "cross_provider_verified": False,
            "label": "external_upstream",
            "path": relative,
            "role": "fixture",
            "sha256": sha256_file(snapshot / relative),
        }
        for relative in SNAPSHOT_FILES
    ]
    v1 = {
        "artifact_root": str(snapshot),
        "files": file_rows,
        "huggingface": {
            "provider_role": "UPSTREAM",
            "repo_id": EXPECTED_MODEL_ID,
            "revision": EXPECTED_HUGGINGFACE_REVISION,
        },
        "label": "external_upstream",
        "licenses": [
            "Stability AI Community License Agreement (2024-07-05)",
            "Gemma Terms of Use",
            "Gemma Prohibited Use Policy",
        ],
        "modelscope": {
            "provider_role": "MIRROR",
            "repo_id": EXPECTED_MODEL_ID,
            "revision": EXPECTED_MODELSCOPE_REVISION,
        },
        "schema_version": 1,
    }
    v1_path = repo / "provenance" / "weights.manifest.json"
    _write_json(v1_path, v1)
    substantive = [
        row for row in file_rows if row["path"] not in {".gitattributes", "configuration.json"}
    ]
    v2 = {
        "huggingface": {
            "gated": False,
            "private": False,
            "provider_role": "UPSTREAM",
            "repo_id": EXPECTED_MODEL_ID,
            "revision": EXPECTED_HUGGINGFACE_REVISION,
        },
        "label": "external_upstream",
        "modelscope": {
            "provider_role": "MIRROR",
            "repo_id": EXPECTED_MODEL_ID,
            "revision": EXPECTED_MODELSCOPE_REVISION,
        },
        "provider_metadata": {
            "excluded_from_content_equivalence": [
                {"path": ".gitattributes", "reason": "provider metadata"},
                {"path": "configuration.json", "reason": "provider metadata"},
                {
                    "path": "t5gemma-b-b-ul2/.gitattributes",
                    "reason": "provider metadata",
                },
            ],
            "runtime_required": False,
        },
        "schema_version": 2,
        "status": "PASS",
        "supersedes": {
            "path": "provenance/weights.manifest.json",
            "scope": "cross_provider_verified flags only",
            "sha256": sha256_file(v1_path),
        },
        "verification": {"verified_common_file_count": len(substantive)},
        "verified_files": [
            {
                "byte_size": row["byte_size"],
                "cross_provider_verified": True,
                "path": row["path"],
                "sha256": row["sha256"],
            }
            for row in substantive
        ],
    }
    v2_path = repo / "provenance" / "weights.cross-provider-verification.v2.json"
    _write_json(v2_path, v2)

    freeze_path = repo / "environment" / "package-freeze.txt"
    freeze_path.write_text(
        "\n".join(
            (
                "stable-audio-3 @ https://github.com/Stability-AI/"
                f"stable-audio-3/archive/{EXPECTED_STABLE_AUDIO_3_COMMIT}.tar.gz",
                "stable-audio-tools @ https://github.com/Stability-AI/"
                f"stable-audio-tools/archive/{EXPECTED_STABLE_AUDIO_TOOLS_COMMIT}.tar.gz",
                "torch==2.7.1",
                "torchaudio==2.7.1",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_path = repo / "environment" / "runtime.json"
    _write_json(
        runtime_path,
        {
            "freeze_sha256": sha256_file(freeze_path),
            "gpu_validation": {
                "cuda_visible_devices": "4",
                "device": "NVIDIA A800 80GB PCIe",
                "gpu_ids": [4],
                "node": "an12",
                "replica_count": 1,
                "tensor_parallel_width": 1,
            },
            "python": "3.10.12",
            "torch": "2.7.1+cu126",
            "torchaudio": "2.7.1+cu126",
        },
    )

    config = {
        "audio": {"channels": 2, "sample_rate": 44_100, "subtype": "FLOAT"},
        "model": {
            "huggingface_revision": EXPECTED_HUGGINGFACE_REVISION,
            "id": EXPECTED_MODEL_ID,
            "model_half": True,
            "modelscope_revision": EXPECTED_MODELSCOPE_REVISION,
            "snapshot": str(snapshot),
        },
        "placement": {
            "gpu_ids": [4],
            "justification": "fixture uses one A800 with TP1 and one replica",
            "node": "an12",
            "replica_count": 1,
            "tensor_parallel_width": 1,
        },
        "protocol": {
            "path": "SMOKE_PROTOCOL.md",
            "sha256": sha256_file(protocol),
        },
        "run_root": str(tmp_path / "configured-runs"),
        "sampling": {
            "cfg_scale": 7.0,
            "chunked_decode": True,
            "duration_padding_sec": 6.0,
            "duration_seconds": 30,
            "negative_prompt": "low quality, clipping, silence",
            "prompt": (
                "A steady instrumental electronic music loop with drums, bass, and "
                "warm synthesizer, clean studio recording, 120 BPM"
            ),
            "sampler_type": "euler",
            "steps": 50,
        },
        "smokes": {
            "a": {"repeat_count": 2, "seed": 73_193_001, "seed_id": "S-0001"},
            "b": {
                "continuation_mask_seconds": [10, 30],
                "prompt": (
                    "Continue the same instrumental electronic music with consistent "
                    "rhythm and instrumentation"
                ),
                "seed": 73_193_002,
                "seed_id": "S-0002",
                "source_seconds": 10,
            },
            "c": {
                "multi_mask_seconds": [[4, 6], [20, 23]],
                "multi_seed": 73_193_004,
                "multi_seed_id": "S-0004",
                "prompt": (
                    "A seamless instrumental electronic music passage with steady drums "
                    "and warm synthesizer"
                ),
                "single_mask_seconds": [[8, 12]],
                "single_seed": 73_193_003,
                "single_seed_id": "S-0003",
            },
            "d": {
                "batch_duration_seconds": 10,
                "batch_prompts": [
                    "Steady electronic drums and warm synthesizer, 100 BPM",
                    "Clean acoustic guitar rhythm with light percussion, 110 BPM",
                    "Ambient synthesizer pulse with a steady beat, 90 BPM",
                    "Bright piano groove with bass and drums, 120 BPM",
                ],
                "batch_seed": 73_193_006,
                "batch_seed_id": "S-0006",
                "batch_size": 4,
                "single_seed": 73_193_005,
                "single_seed_id": "S-0005",
            },
            "e": {
                "checkpoint_completed_steps": [15, 30, 40],
                "seed": 73_193_007,
                "seed_id": "S-0007",
                "waveform_max_abs_tolerance": 1e-5,
                "waveform_min_snr_db": 80.0,
            },
        },
        "version": 2,
    }
    config_path = repo / "configs" / "foundation_v2.json"
    _write_json(config_path, config)
    process_context = {
        "argv": ["python", "-m", "sa3_smoke.run_foundation"],
        "cwd": str(repo.resolve()),
        "environment": {
            "full_environment_sha256": "0" * 64,
            "safe_values": {"CUDA_VISIBLE_DEVICES": "4"},
            "sensitive_value_sha256s": {},
            "variable_count": 1,
        },
        "exact_command": "python -m sa3_smoke.run_foundation",
        "executable": sys.executable,
        "pid": 10,
        "python_version": sys.version,
    }
    return SimpleNamespace(
        config=config,
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        process_context=process_context,
        repo=repo,
        snapshot=snapshot,
        v1_path=v1_path,
        v2_path=v2_path,
    )


def _dependencies(
    fixture: SimpleNamespace,
    *,
    load_error: BaseException | None = None,
    a_status: str = "PASS",
    a_has_artifact: bool = True,
    environment_passed: bool = True,
) -> tuple[OrchestrationDependencies, list[tuple[str, tuple[Any, ...], dict[str, Any]]]]:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def resolve(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("resolve", args, kwargs))
        return {
            "diff_path": str(args[2] / "model_config.diff"),
            "diff_sha256": "d" * 64,
            "original_sha256": sha256_file(fixture.snapshot / "model_config.json"),
            "resolved_config_path": str(args[2] / "model_config.resolved.json"),
            "resolved_sha256": "r" * 64,
            "t5_snapshot_file_sha256s": {
                name: sha256_file(fixture.snapshot / "t5gemma-b-b-ul2" / name)
                for name in REQUIRED_T5_MANIFEST_FILES
            },
        }

    def load(*args: Any, **kwargs: Any) -> object:
        calls.append(("load", args, kwargs))
        if load_error is not None:
            raise load_error
        return object()

    def smoke_a(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("A", args, kwargs))
        wav_path = Path(args[1]) / "a.wav"
        wav_path.write_bytes(b"fake wav")
        return {
            "artifacts": [{"path": str(wav_path)}] if a_has_artifact else [],
            "checks": {"fixture": a_status == "PASS"},
            "status": a_status,
        }

    def smoke_b(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("B", args, kwargs))
        return {"artifacts": [], "checks": {"fixture": True}, "status": "PASS"}

    def smoke_c(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("C", args, kwargs))
        return {"artifacts": [], "checks": {"fixture": True}, "status": "PASS"}

    def smoke_d(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("D", args, kwargs))
        return {"artifacts": [], "checks": {"fixture": True}, "status": "PASS"}

    def smoke_e(
        model_runtime: Any,
        output_dir: Path,
        *,
        frozen_config_path: Path,
        provenance: dict[str, Any],
        python_executable: str | None = None,
    ) -> dict[str, Any]:
        args = (model_runtime, output_dir)
        kwargs = {
            "frozen_config_path": frozen_config_path,
            "provenance": provenance,
            "python_executable": python_executable,
        }
        calls.append(("E", args, kwargs))
        return {"artifacts": {}, "checks": {"fixture": True}, "status": "PASS"}

    def hardware() -> dict[str, Any]:
        return {
            "cuda_available": True,
            "cuda_visible_devices": "4",
            "devices": [{"name": "NVIDIA A800 80GB PCIe"}],
            "node": "an12",
            "visible_device_count": 1,
        }

    def environment(_repository_root: Path) -> dict[str, Any]:
        return {
            "passed": environment_passed,
            "failures": [] if environment_passed else ["fixture package version drift"],
            "evidence": {"fixture": True},
        }

    def git(_repo: Path) -> dict[str, Any]:
        return {
            "branch": "main",
            "clean": True,
            "head": "a" * 40,
            "head_matches_origin_main": True,
            "origin_main": "a" * 40,
            "porcelain_v1": [],
        }

    return (
        OrchestrationDependencies(
            testing_only=True,
            resolve_model_config=resolve,
            load_model=load,
            run_smoke_a=smoke_a,
            run_smoke_b=smoke_b,
            run_smoke_c=smoke_c,
            run_smoke_d=smoke_d,
            run_smoke_e=smoke_e,
            environment_validator=environment,
            hardware_probe=hardware,
            git_probe=git,
        ),
        calls,
    )


def _run(
    fixture: SimpleNamespace,
    tmp_path: Path,
    dependencies: OrchestrationDependencies,
):
    return _run_foundation_for_testing(
        fixture.config_path,
        repository_root=fixture.repo,
        run_root=tmp_path / "runs",
        expected_config_sha256=fixture.config_sha256,
        dependencies=dependencies,
        process_context=fixture.process_context,
    )


def test_private_test_entry_rejects_live_dependencies(tmp_path: Path) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, _ = _dependencies(fixture)
    live_dependencies = replace(dependencies, testing_only=False)

    with pytest.raises(ValueError, match="requires testing-only dependencies"):
        _run(fixture, tmp_path, live_dependencies)

    assert not (tmp_path / "runs").exists()


def test_orchestrator_runs_all_smokes_once_with_explicit_frozen_values(
    tmp_path: Path,
) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture)

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 0
    assert outcome.result["SMOKE_STATUS"] == "PASS"
    assert outcome.result["summary"]["statuses"] == dict.fromkeys(SMOKE_NAMES, "PASS")
    assert outcome.result["summary"]["all_five_terminal"] is True
    assert [name for name, _, _ in calls] == ["resolve", "load", "A", "B", "C", "D", "E"]
    assert outcome.result["model_setup"]["load_attempt_count"] == 1
    assert outcome.result["model_setup"]["load_success_count"] == 1
    assert len(list((tmp_path / "runs").iterdir())) == 1

    call_map = {name: (args, kwargs) for name, args, kwargs in calls}
    assert call_map["A"][1] == {
        "cfg_scale": 7.0,
        "chunked_decode": True,
        "duration": 30,
        "negative_prompt": "low quality, clipping, silence",
        "prompt": fixture.config["sampling"]["prompt"],
        "provenance": call_map["A"][1]["provenance"],
        "seed": 73_193_001,
        "steps": 50,
    }
    assert call_map["B"][1]["source_duration"] == 10
    assert call_map["B"][1]["seed"] == 73_193_002
    assert call_map["C"][1]["single_seed"] == 73_193_003
    assert call_map["C"][1]["multi_seed"] == 73_193_004
    assert call_map["D"][1]["batch1_seed"] == 73_193_005
    assert call_map["D"][1]["batch4_seed"] == 73_193_006
    assert call_map["D"][1]["batch4_prompts"] == fixture.config["smokes"]["d"]["batch_prompts"]
    assert set(call_map["E"][1]) == {
        "frozen_config_path",
        "provenance",
        "python_executable",
    }
    assert call_map["E"][1]["frozen_config_path"] == fixture.config_path

    manifest_required = {
        "artifact_paths",
        "configuration_sha256",
        "deviations",
        "exact_command",
        "frozen_configuration",
        "frozen_protocol_fields",
        "governance_authorization",
        "gpu_ids",
        "model_artifact_sha256s",
        "node",
        "package_freeze_sha256",
        "process",
        "protocol_sha256",
        "replica_count",
        "repository_git_clean",
        "repository_git_hash",
        "seeds",
        "started_at_utc",
        "status",
        "tensor_parallel_width",
        "weights_manifests",
    }
    for smoke in SMOKE_NAMES:
        manifest_path = Path(outcome.result["smokes"][smoke]["manifest"]["path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest_required <= set(manifest)
        assert manifest["status"] == "PASS"
        assert (
            manifest["frozen_protocol_fields"]["smoke"] == fixture.config["smokes"][smoke.lower()]
        )
        json.dumps(manifest, allow_nan=False)

    evidence = outcome.result["preflight"]["evidence"]
    manifests = evidence["weights_manifests"]
    assert manifests["local_snapshot_v1"]["sha256"] == sha256_file(fixture.v1_path)
    assert manifests["cross_provider_v2"]["sha256"] == sha256_file(fixture.v2_path)
    assert manifests["cross_provider_v2"]["v1_cross_provider_flags_trusted"] is False
    assert evidence["governance_authorization"]["latest_state"] == "YES"
    assert json.loads(outcome.result_path.read_text(encoding="utf-8")) == outcome.result


def test_model_load_failure_fans_out_five_terminal_results(tmp_path: Path) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture, load_error=RuntimeError("load exploded"))

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 1
    assert outcome.result["SMOKE_STATUS"] == "FAIL_ESCALATED"
    assert outcome.result["summary"]["statuses"] == dict.fromkeys(SMOKE_NAMES, "FAIL")
    assert outcome.result["summary"]["all_five_terminal"] is True
    assert [name for name, _, _ in calls] == ["resolve", "load"]
    assert outcome.result["model_setup"]["load_attempt_count"] == 1
    assert outcome.result["model_setup"]["load_success_count"] == 0
    assert "load exploded" in outcome.result["model_setup"]["error"]
    for smoke in SMOKE_NAMES:
        assert Path(outcome.result["smokes"][smoke]["manifest"]["path"]).is_file()


def test_snapshot_hash_drift_is_terminal_before_resolution_or_load(tmp_path: Path) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture)
    checkpoint = fixture.snapshot / "model.safetensors"
    checkpoint.write_bytes(b"x" * checkpoint.stat().st_size)

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 1
    assert calls == []
    assert outcome.result["preflight"]["evidence"]["live_snapshot_verification"]["status"] == "FAIL"
    assert any(
        "live snapshot SHA-256 mismatch" in failure
        for failure in outcome.result["preflight"]["failures"]
    )
    assert outcome.result["summary"]["statuses"] == dict.fromkeys(SMOKE_NAMES, "FAIL")


def test_snapshot_mount_alias_is_accepted_by_filesystem_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture)
    alias = tmp_path / "snapshot-mount-alias"
    alias.symlink_to(fixture.snapshot, target_is_directory=True)

    manifest = json.loads(fixture.v1_path.read_text(encoding="utf-8"))
    manifest["artifact_root"] = str(alias)
    _write_json(fixture.v1_path, manifest)
    overlay = json.loads(fixture.v2_path.read_text(encoding="utf-8"))
    overlay["supersedes"]["sha256"] = sha256_file(fixture.v1_path)
    _write_json(fixture.v2_path, overlay)

    real_resolve = Path.resolve

    def resolve_with_mount_alias(self: Path, strict: bool = False) -> Path:
        if self == alias:
            return self.absolute()
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_with_mount_alias)
    assert alias.samefile(fixture.snapshot)
    assert alias.resolve() != fixture.snapshot.resolve()

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 0
    assert outcome.result["preflight"]["evidence"]["live_snapshot_verification"]["status"] == "PASS"
    assert not any(
        "configured snapshot differs from weights manifest artifact_root" in failure
        for failure in outcome.result["preflight"]["failures"]
    )
    assert [name for name, _, _ in calls] == ["resolve", "load", "A", "B", "C", "D", "E"]


def test_live_environment_drift_is_terminal_before_resolution_or_load(
    tmp_path: Path,
) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture, environment_passed=False)

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 1
    assert calls == []
    validation = outcome.result["preflight"]["evidence"]["live_environment"]
    assert validation["passed"] is False
    assert validation["failures"] == ["fixture package version drift"]
    assert any(
        failure == "live environment drift: fixture package version drift"
        for failure in outcome.result["preflight"]["failures"]
    )
    assert outcome.result["model_setup"]["load_attempt_count"] == 0
    assert outcome.result["summary"]["statuses"] == dict.fromkeys(SMOKE_NAMES, "FAIL")


def test_latest_append_only_authorization_revocation_stops_before_load(
    tmp_path: Path,
) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture)
    with (fixture.repo / "DECISIONS.md").open("a", encoding="utf-8") as handle:
        handle.write("SA3_FOUNDATION_SMOKE_AUTHORIZED = NO\n")

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 1
    assert calls == []
    authorization = outcome.result["preflight"]["evidence"]["governance_authorization"]
    assert authorization["latest_state"] == "NO"
    assert authorization["authorized"] is False
    assert outcome.result["model_setup"]["load_attempt_count"] == 0


def test_smoke_e_adapter_binds_the_live_function_signature(tmp_path: Path) -> None:
    from sa3_smoke.smoke_e import run_smoke_e

    keyword_arguments = _smoke_e_kwargs(
        frozen_config_path=tmp_path / "foundation.json",
        provenance={"run_id": "run-e"},
    )
    bound = inspect.signature(run_smoke_e).bind(
        object(),
        tmp_path / "smoke-e",
        **keyword_arguments,
    )

    assert bound.arguments["model_runtime"] is not None
    assert bound.arguments["frozen_config_path"] == tmp_path / "foundation.json"
    assert set(keyword_arguments) == {
        "frozen_config_path",
        "provenance",
        "python_executable",
    }


def test_a_failure_skips_only_dependent_b_and_c(tmp_path: Path) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(
        fixture,
        a_status="FAIL",
        a_has_artifact=False,
    )

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 1
    assert [name for name, _, _ in calls] == ["resolve", "load", "A", "D", "E"]
    assert outcome.result["summary"]["statuses"] == {
        "A": "FAIL",
        "B": "FAIL",
        "C": "FAIL",
        "D": "PASS",
        "E": "PASS",
    }
    assert outcome.result["smokes"]["B"]["result"]["error"]["stage"] == "dependency"
    assert outcome.result["smokes"]["C"]["result"]["error"]["stage"] == "dependency"


@pytest.mark.parametrize("field", ["sha256", "byte_size"])
def test_cross_provider_overlay_drift_is_terminal_preload(
    tmp_path: Path,
    field: str,
) -> None:
    fixture = _foundation_fixture(tmp_path)
    dependencies, calls = _dependencies(fixture)
    overlay = json.loads(fixture.v2_path.read_text(encoding="utf-8"))
    overlay["verified_files"][0][field] = (
        "f" * 64 if field == "sha256" else overlay["verified_files"][0][field] + 1
    )
    _write_json(fixture.v2_path, overlay)

    outcome = _run(fixture, tmp_path, dependencies)

    assert outcome.exit_code == 1
    assert calls == []
    assert any(
        "cross-provider verification failed" in failure
        for failure in outcome.result["preflight"]["failures"]
    )

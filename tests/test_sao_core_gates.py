from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backbones import sao_operational_claims
from backbones.contracts import (
    DEFAULT_SAO_CONFIG,
    BackbonePreflight,
    GenerationMeasurement,
    GenerationRequest,
    sha256_file,
)
from backbones.license_gate import validate_access_receipt
from backbones.mini_smoke import RunContext
from backbones.sao_mini_smoke import EXPECTED_PROMPTS, EXPECTED_SEEDS, run_sao_mini_smoke
from backbones.sao_t5 import conditioning_bundle_record
from benchmark_core.adapter_bridge import build_production_bridge
from benchmark_core.config import (
    ACE_MODEL_ID,
    SA3_MODEL_ID,
    SAO_MODEL_ID,
    CoreConfigurationError,
)
from sa3_smoke.audio import save_float_wav_exclusive
from tests.test_benchmark_core_safety import (
    _configure_ace_incremental,
    _core_config,
    _load_test_config,
    _write_completed_sa3_fixture,
    _write_json,
)


class _EvidenceSao:
    logical_name = "stable-audio-open-1.0"
    model_id = SAO_MODEL_ID
    config_sha256 = sha256_file(DEFAULT_SAO_CONFIG)
    license_identifier = "fixture-license"

    def __init__(self, receipt: dict[str, object], authorization: Path, weight_sha: str) -> None:
        self.receipt = receipt
        self.authorization = authorization
        self.weight_sha = weight_sha
        self.calls = 0

    def preflight(self) -> BackbonePreflight:
        authorization = json.loads(self.authorization.read_text(encoding="utf-8"))
        return BackbonePreflight(
            status="READY_FOR_MINI_SMOKE",
            model_id=self.model_id,
            config_sha256=self.config_sha256,
            details={
                "network_downloads_allowed": False,
                "receipt": self.receipt,
                "runtime_authorization": authorization,
                "runtime_authorization_path": str(self.authorization.resolve()),
                "runtime_authorization_sha256": sha256_file(self.authorization),
                "snapshot_dir": str(
                    Path(str(self.receipt["receipt_path"])).parent.joinpath("sao-snapshot").resolve()
                ),
            },
        )

    def generate(self, request: GenerationRequest) -> GenerationMeasurement:
        self.calls += 1
        frames = np.arange(1_323_000, dtype=np.float32)
        frequency = 220.0 if request.prompt_id == "sao-mini-repro" else 330.0
        tone = (0.02 * np.sin(2 * np.pi * frequency * frames / 44_100)).astype(np.float32)
        save_float_wav_exclusive(
            request.output_path,
            np.stack([tone, tone]),
            44_100,
            channels_first=True,
        )
        return GenerationMeasurement(
            output_path=request.output_path,
            sample_rate=44_100,
            requested_steps=100,
            actual_nfe=100,
            wall_seconds=float(self.calls),
            peak_allocated_bytes=1024,
            peak_reserved_bytes=2048,
            metadata={
                "load_wall_seconds": 10.0,
                "config_sha256": self.config_sha256,
                "conditioning_bundle_sha256": conditioning_bundle_record(
                    self.receipt["verified_files"]
                )["conditioning_bundle_sha256"],
                "execution_scope": "MINI_SMOKE",
                "requested_sample_size": 1_323_000,
                "weight_file_sha256": self.weight_sha,
                "resolved_provider_revision": "a" * 40,
                "sampler_type": "dpmpp-3m-sde",
            },
        )


def _write_mini_evidence(
    tmp_path: Path,
    *,
    snapshot: Path,
    receipt_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    receipt = validate_access_receipt(
        receipt_path,
        expected_model_id=SAO_MODEL_ID,
        expected_snapshot_dir=snapshot,
    )
    authorization = tmp_path / "sao-mini-authorization.json"
    _write_json(
        authorization,
        {
            "schema_version": 1,
            "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
            "decision_id": "D-0037",
            "backbone_config_sha256": sha256_file(DEFAULT_SAO_CONFIG),
            "access_receipt_sha256": receipt["receipt_sha256"],
            "max_generations": 3,
            "max_clip_seconds": 30,
            "max_gpus": 1,
        },
    )
    run = tmp_path / "sao-mini-smoke-v2-001"
    claim_path = tmp_path / "sao-mini-smoke-v2-001.attempt.claim.json"
    monkeypatch.setattr(sao_operational_claims, "SAO_MINI_SMOKE_RUN_DIR", run)
    monkeypatch.setattr(sao_operational_claims, "SAO_MINI_SMOKE_ATTEMPT_CLAIM", claim_path)
    live_config = tmp_path / "sao-live-fixture.json"
    _write_json(live_config, {"fixture": "SAO live config hash binding"})
    attempt_claim = sao_operational_claims.consume_sao_mini_smoke_attempt(
        authorization,
        requested_run_dir=run,
        live_config_path=live_config,
        git_commit="c" * 40,
    )
    request_values = [
        (prompt_id, prompt, seed_id, seed)
        for (prompt_id, prompt), (seed_id, seed) in zip(
            EXPECTED_PROMPTS,
            EXPECTED_SEEDS,
            strict=True,
        )
    ]
    requests = [
        GenerationRequest(
            prompt_id=prompt_id,
            prompt=prompt,
            seed_id=seed_id,
            seed=seed,
            duration_seconds=30,
            output_path=run / "audio" / f"call-{index:02d}.wav",
        )
        for index, (prompt_id, prompt, seed_id, seed) in enumerate(request_values)
    ]
    run_sao_mini_smoke(
        _EvidenceSao(
            receipt,
            authorization,
            sha256_file(snapshot / "model.safetensors"),
        ),
        requests,
        run_dir=run,
        context=RunContext(
            run_id=run.name,
            command="pytest SAO evidence fixture",
            git_commit="c" * 40,
            node="an12",
            gpu_ids=("4",),
            placement_justification="Single fake TP1 fixture on the frozen SAO placement.",
            package_freeze_sha256="d" * 64,
        ),
        require_visible_gpu=False,
        placement_observation={
            "node": "an12",
            "physical_gpu_id": 4,
            "gpu_uuid": "GPU-fixture-a800",
            "gpu_name": "NVIDIA A800 fixture",
            "free_vram_bytes": 79_000_000_000,
            "total_vram_bytes": 80_000_000_000,
            "utilization_percent": 0,
            "neighbor_compute_pids": [],
            "operational_attempt_claim_path": attempt_claim["path"],
            "operational_attempt_claim_sha256": attempt_claim["sha256"],
        },
    )
    return run / "sao-mini-smoke-terminal.json"


def _sao_ready_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = _core_config(tmp_path, scheduled_calls=1536)
    sa3_receipt, _queue = _write_completed_sa3_fixture(tmp_path, config_path)
    _configure_ace_incremental(config_path, sa3_receipt)

    snapshot = tmp_path / "sao-snapshot"
    snapshot.mkdir()
    (snapshot / "model_config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"fixture-sao-weight")
    (snapshot / "model.ckpt").write_bytes(b"fixture-sao-legacy-weight")
    (snapshot / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    (snapshot / "text_encoder").mkdir()
    (snapshot / "tokenizer").mkdir()
    _write_json(
        snapshot / "text_encoder" / "config.json",
        {
            "_name_or_path": "t5-base",
            "architectures": ["T5EncoderModel"],
            "d_model": 768,
            "model_type": "t5",
        },
    )
    (snapshot / "text_encoder" / "model.safetensors").write_bytes(b"fixture-t5-weight")
    _write_json(snapshot / "tokenizer" / "special_tokens_map.json", {"eos": "</s>"})
    (snapshot / "tokenizer" / "spiece.model").write_bytes(b"fixture-spiece")
    _write_json(snapshot / "tokenizer" / "tokenizer.json", {"version": "1.0"})
    _write_json(
        snapshot / "tokenizer" / "tokenizer_config.json",
        {"tokenizer_class": "T5Tokenizer"},
    )
    files = [
        {
            "path": path.relative_to(snapshot).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(snapshot.rglob("*"))
        if path.is_file()
    ]
    manifest = tmp_path / "sao-snapshot-manifest.json"
    _write_json(
        manifest,
        {
            "model_id": SAO_MODEL_ID,
            "revision": "a" * 40,
            "files": files,
        },
    )
    receipt = tmp_path / "sao-access-receipt.json"
    _write_json(
        receipt,
        {
            "schema_version": 1,
            "model_id": SAO_MODEL_ID,
            "resolved_provider_revision": "a" * 40,
            "accepted_by": "PI",
            "accepted_at_utc": "2026-07-22T00:00:00Z",
            "user_confirmed_acceptance": True,
            "license_identifier": "fixture-license",
            "license_text_sha256": sha256_file(snapshot / "LICENSE"),
            "snapshot_manifest_path": str(manifest),
            "snapshot_manifest_sha256": sha256_file(manifest),
        },
    )
    mini = _write_mini_evidence(
        tmp_path,
        snapshot=snapshot,
        receipt_path=receipt,
        monkeypatch=monkeypatch,
    )
    core_authorization = tmp_path / "sao-core-authorization.json"
    _write_json(
        core_authorization,
        {
            "schema_version": 1,
            "status": "ACCESS_AND_MINI_SMOKE_VERIFIED_CORE_AUTHORIZED",
            "scope": "SAO_BENCHMARK_CORE_GENERATION_ONLY",
            "decision_id": "D-0037",
            "backbone_config_sha256": sha256_file(DEFAULT_SAO_CONFIG),
            "access_receipt_sha256": sha256_file(receipt),
            "mini_smoke_result_sha256": sha256_file(mini),
            "exact_generations": 1536,
            "max_clip_seconds": 30,
            "max_gpus_per_worker": 1,
            "state_capability": "NOT_ATTEMPTED",
            "eligibility_scope_expanded": False,
        },
    )

    terminal_path = tmp_path / "phase-b-terminal.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["models"][SAO_MODEL_ID] = {
        "build_status": "MEASURED_READY",
        "queue_status": "READY",
        "cost_status": "MEASURED",
        "mini_smoke_status": "MEASURED_MINI_SMOKE_PASS",
        "cold_plus_first_seconds": 11.0,
        "resident_unit_seconds": 3.0,
        "access_receipt_sha256": sha256_file(receipt),
        "mini_smoke_result_sha256": sha256_file(mini),
        "state_capability": "NOT_ATTEMPTED",
        "eligibility_scope_expanded": False,
    }
    _write_json(terminal_path, terminal)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["phase_b_terminal"]["sha256"] = sha256_file(terminal_path)
    raw["execution"]["authorized_model_ids"] = [SA3_MODEL_ID, ACE_MODEL_ID, SAO_MODEL_ID]
    raw["execution"]["prior_model_completions"] = {}
    raw["models"][1] = {
        "model_id": SAO_MODEL_ID,
        "queue_status": "READY",
        "slug": "stable-audio-open-1-0",
        "core_execution": {
            "adapter_config_path": str(DEFAULT_SAO_CONFIG),
            "adapter_config_sha256": sha256_file(DEFAULT_SAO_CONFIG),
            "budget": {
                "cold_plus_first_seconds": 11.0,
                "resident_unit_seconds": 3.0,
                "scheduled_calls": 1536,
                "gpu_seconds_cap": 9221.0,
            },
            "duration_tolerance_seconds": 0.25,
            "expected_channels": 2,
            "placement": raw["models"][0]["core_execution"]["placement"],
            "state_capture_status": "AUTOMATIC_OUTPUT_ONLY",
            "sao_runtime": {
                "snapshot_dir": str(snapshot),
                "access_receipt_path": str(receipt),
                "access_receipt_sha256": sha256_file(receipt),
                "mini_smoke_result_path": str(mini),
                "mini_smoke_result_sha256": sha256_file(mini),
                "core_authorization_path": str(core_authorization),
                "core_authorization_sha256": sha256_file(core_authorization),
            },
        },
    }
    _write_json(config_path, raw)
    return config_path


def _rebind_mini_outer_hashes(config_path: Path) -> None:
    """Model an attacker who updates every shallow hash after changing the terminal."""

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = raw["models"][1]["core_execution"]["sao_runtime"]
    mini_path = Path(runtime["mini_smoke_result_path"])
    mini_sha = sha256_file(mini_path)
    authorization_path = Path(runtime["core_authorization_path"])
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["mini_smoke_result_sha256"] = mini_sha
    _write_json(authorization_path, authorization)
    runtime["mini_smoke_result_sha256"] = mini_sha
    runtime["core_authorization_sha256"] = sha256_file(authorization_path)

    phase_path = config_path.parent / "phase-b-terminal.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["models"][SAO_MODEL_ID]["mini_smoke_result_sha256"] = mini_sha
    _write_json(phase_path, phase)
    raw["phase_b_terminal"]["sha256"] = sha256_file(phase_path)
    _write_json(config_path, raw)


def test_sao_dual_format_receipt_selects_safetensors_through_smoke_and_core(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _sao_ready_config(tmp_path, monkeypatch)
    config = _load_test_config(path)
    sao = next(model for model in config.models if model.model_id == SAO_MODEL_ID)
    assert sao.sao_runtime is not None
    assert sao.state_capture_status == "AUTOMATIC_OUTPUT_ONLY"
    assert config.phase_b_terminal.model_queue_statuses[SAO_MODEL_ID] == "READY"
    bridge = build_production_bridge(sao, run_dir=tmp_path / "run")
    assert bridge.model_id == SAO_MODEL_ID
    assert bridge.backbone.execution_scope == "BENCHMARK_CORE"
    assert bridge.backbone.mini_smoke_result_sha256 == sao.sao_runtime.mini_smoke_result_sha256
    assert bridge.backbone.preflight().status == "READY_FOR_CORE"
    assert sao.sao_runtime is not None
    receipt = validate_access_receipt(
        sao.sao_runtime.access_receipt_path,
        expected_model_id=SAO_MODEL_ID,
        expected_snapshot_dir=Path(sao.sao_runtime.snapshot_dir),
    )
    assert {row["path"] for row in receipt["verified_files"]}.issuperset(
        {"model.safetensors", "model.ckpt"}
    )
    selected_sha = sha256_file(Path(sao.sao_runtime.snapshot_dir) / "model.safetensors")
    terminal = json.loads(
        Path(sao.sao_runtime.mini_smoke_result_path).read_text(encoding="utf-8")
    )
    assert {
        row["measurement_metadata"]["weight_file_sha256"] for row in terminal["rows"]
    } == {selected_sha}


def test_sao_core_gate_fails_closed_on_state_scope_or_receipt_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _sao_ready_config(tmp_path, monkeypatch)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["models"][1]["core_execution"]["state_capture_status"] = "READY"
    _write_json(path, raw)
    with pytest.raises(CoreConfigurationError, match="state capability"):
        _load_test_config(path)

    path = _sao_ready_config(tmp_path / "second", monkeypatch)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["models"][1]["core_execution"]["sao_runtime"]["access_receipt_sha256"] = "f" * 64
    _write_json(path, raw)
    with pytest.raises(CoreConfigurationError, match="access receipt hash mismatch"):
        _load_test_config(path)


def test_sao_core_rejects_fabricated_summary_even_if_all_outer_hashes_are_resealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _sao_ready_config(tmp_path, monkeypatch)
    raw = json.loads(path.read_text(encoding="utf-8"))
    mini_path = Path(
        raw["models"][1]["core_execution"]["sao_runtime"]["mini_smoke_result_path"]
    )
    _write_json(
        mini_path,
        {
            "status": "PASS_MEASURED_READY",
            "model_calls": 3,
            "reproducibility_hash_pass": True,
            "state_capability": "NOT_ATTEMPTED",
            "eligibility_scope_expanded": False,
        },
    )
    _rebind_mini_outer_hashes(path)
    with pytest.raises(CoreConfigurationError, match="PASS terminal keys drifted"):
        _load_test_config(path)


def test_sao_core_redecodes_retained_audio_and_rejects_byte_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _sao_ready_config(tmp_path, monkeypatch)
    raw = json.loads(path.read_text(encoding="utf-8"))
    mini_path = Path(
        raw["models"][1]["core_execution"]["sao_runtime"]["mini_smoke_result_path"]
    )
    terminal = json.loads(mini_path.read_text(encoding="utf-8"))
    wav_path = Path(terminal["rows"][2]["output_path"])
    with wav_path.open("r+b") as handle:
        handle.seek(-1, 2)
        value = handle.read(1)
        handle.seek(-1, 2)
        handle.write(bytes([value[0] ^ 1]))
    with pytest.raises(CoreConfigurationError, match="retained WAV hash mismatch"):
        _load_test_config(path)


def test_sao_core_rejects_receipt_unlink_after_manifest_and_outer_hash_reseal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _sao_ready_config(tmp_path, monkeypatch)
    raw = json.loads(path.read_text(encoding="utf-8"))
    mini_path = Path(
        raw["models"][1]["core_execution"]["sao_runtime"]["mini_smoke_result_path"]
    )
    terminal = json.loads(mini_path.read_text(encoding="utf-8"))
    manifest_path = Path(terminal["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preflight"]["details"]["receipt"]["receipt_sha256"] = "f" * 64
    _write_json(manifest_path, manifest)
    terminal["manifest_sha256"] = sha256_file(manifest_path)
    _write_json(mini_path, terminal)
    _rebind_mini_outer_hashes(path)
    with pytest.raises(CoreConfigurationError, match="receipt linkage mismatch"):
        _load_test_config(path)

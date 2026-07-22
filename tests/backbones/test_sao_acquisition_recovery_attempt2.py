from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import backbones.sao_acquisition as acquisition
from backbones.contracts import sha256_file
from backbones.license_gate import validate_access_receipt
from backbones.sao_acquisition import (
    RECOVERY_ATTEMPT2_MATERIALIZATION,
    RECOVERY_ATTEMPT2_RUN_ID,
    RECOVERY_REVISION,
    RECOVERY_RUN_ID,
    RECOVERY_SOURCE_RUN_ID,
    SaoAcquisitionError,
    finalize_retained_acquisition_recovery_attempt2,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    runtime = tmp_path / "runtime"
    run_root = runtime / "runs" / "sao-live-v2" / "acquisition"
    snapshot_root = runtime / "models" / "stable-audio-open-1.0"
    run_root.mkdir(parents=True)
    snapshot_root.mkdir(parents=True)
    (snapshot_root / ".sao-acquisition.lock").write_bytes(b"")

    config_value = json.loads(
        (ROOT / "configs" / "sao_live_v2.json").read_text(encoding="utf-8")
    )
    config_value["acquisition"]["run_root"] = str(run_root)
    config_value["acquisition"]["snapshot_root"] = str(snapshot_root)
    config = tmp_path / "config.json"
    _write_json(config, config_value)

    source_run = run_root / RECOVERY_SOURCE_RUN_ID
    source_run.mkdir()
    started = "2026-07-22T08:25:24.996923Z"
    source_manifest = source_run / "acquisition-manifest.json"
    _write_json(
        source_manifest,
        {
            "schema_version": 1,
            "status": "STARTED_NO_MODEL_CALLS",
            "run_id": RECOVERY_SOURCE_RUN_ID,
            "started_at_utc": started,
            "node": "fixture-node",
            "command": (
                "scripts/acquire_sao_live_v2.py --config configs/sao_live_v2.json "
                "--decisions DECISIONS.md --accepted-by 'Fixture PI' "
                "--accepted-at-utc 2026-07-22T08:25:24Z --execute-ack fixture"
            ),
            "git_commit": "1" * 40,
            "live_config_path": str(config.resolve()),
            "live_config_sha256": sha256_file(config),
            "model_id": acquisition.MODEL_ID,
            "provider": "huggingface_hub",
            "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
            "gpu_count": 0,
            "model_calls": 0,
            "generated_audio": 0,
        },
    )
    monkeypatch.setattr(
        acquisition,
        "RECOVERY_ACQUISITION_MANIFEST_SHA256",
        sha256_file(source_manifest),
    )
    source_failure = source_run / "terminal-failure.json"
    _write_json(
        source_failure,
        {
            "schema_version": 1,
            "status": "ACQUISITION_FAILED_STOPPED",
            "run_id": RECOVERY_SOURCE_RUN_ID,
            "started_at_utc": started,
            "finished_at_utc": "2026-07-22T08:41:41.717344Z",
            "error_type": "SaoAcquisitionError",
            "acquisition_manifest_path": str(source_manifest.resolve()),
            "acquisition_manifest_sha256": sha256_file(source_manifest),
            "credential_mechanism": "HF_TOKEN_ENV_CONSUMED_AND_UNSET",
            "partial_snapshot_retained": True,
            "model_calls": 0,
            "generated_audio": 0,
        },
    )
    monkeypatch.setattr(
        acquisition,
        "RECOVERY_FAILURE_TERMINAL_SHA256",
        sha256_file(source_failure),
    )

    stage = snapshot_root / f".{RECOVERY_SOURCE_RUN_ID}.partial"
    stage.mkdir()
    (stage / "model_config.json").write_text("{}\n", encoding="utf-8")
    (stage / "model.safetensors").write_bytes(b"preferred-weight")
    (stage / "model.ckpt").write_bytes(b"legacy-weight")
    (stage / "LICENSE.md").write_text("fixture license\n", encoding="utf-8")
    (stage / "tokenizer").mkdir()
    (stage / "tokenizer" / "tokenizer.json").write_text("{}\n", encoding="utf-8")
    retained_files = acquisition._snapshot_files(stage)

    d37 = "\n".join(
        (
            "## D-0037 — fixture",
            "SAO_ACQUISITION_AUTHORIZED = YES",
            "SAO_MINI_SMOKE_EXACT_CALLS = 3",
            "SAO_CORE_EXACT_ROWS = 1536",
            "SAO_STATE_CAPABILITY = NOT_ATTEMPTED",
            "SAO_ELIGIBILITY_SCOPE_EXPANDED = NO",
            f"SAO_LIVE_CONFIG_SHA256 = {sha256_file(config)}",
            "",
        )
    )
    d39 = "\n".join(
        (
            "## D-0039 — fixture failed rename recovery",
            "SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES",
            f"SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID = {RECOVERY_SOURCE_RUN_ID}",
            f"SAO_ACQUISITION_RECOVERY_RUN_ID = {RECOVERY_RUN_ID}",
            f"SAO_ACQUISITION_RECOVERY_REVISION = {RECOVERY_REVISION}",
            "SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256 = "
            f"{sha256_file(source_failure)}",
            "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO",
            "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO",
            "SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0",
            "",
        )
    )
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(d37 + d39 + "## D-0041 — fixture\n", encoding="utf-8")
    failed_decision = acquisition.validate_recovery_decision(decisions)

    failed_run = run_root / RECOVERY_RUN_ID
    failed_run.mkdir()
    failed_manifest = failed_run / "snapshot-manifest.json"
    final_snapshot = snapshot_root / RECOVERY_REVISION
    _write_json(
        failed_manifest,
        {
            "schema_version": 1,
            "provider": "huggingface_hub",
            "acquisition_mode": "OFFLINE_RETAINED_STAGE_RECOVERY",
            "model_id": acquisition.MODEL_ID,
            "revision": RECOVERY_REVISION,
            "snapshot_dir": str(final_snapshot),
            "snapshot_tree_sha256": acquisition._tree_sha256(retained_files),
            "files": retained_files,
            "source_run_id": RECOVERY_SOURCE_RUN_ID,
            "source_failure_terminal_path": str(source_failure.resolve()),
            "source_failure_terminal_sha256": sha256_file(source_failure),
            "recovery_decision_id": acquisition.RECOVERY_DECISION_ID,
            "recovery_decision_block_sha256": failed_decision[
                "decision_block_sha256"
            ],
        },
    )
    failed_receipt = failed_run / "access-receipt.json"
    _write_json(
        failed_receipt,
        {
            "schema_version": 1,
            "model_id": acquisition.MODEL_ID,
            "resolved_provider_revision": RECOVERY_REVISION,
            "accepted_by": "Fixture PI",
            "accepted_at_utc": "2026-07-22T08:25:24Z",
            "user_confirmed_acceptance": True,
            "license_identifier": "Stability AI Community License",
            "license_text_sha256": sha256_file(stage / "LICENSE.md"),
            "snapshot_manifest_path": str(failed_manifest.resolve()),
            "snapshot_manifest_sha256": sha256_file(failed_manifest),
        },
    )
    failed_files = acquisition._snapshot_files(failed_run)
    monkeypatch.setattr(
        acquisition,
        "RECOVERY_ATTEMPT1_ACCESS_RECEIPT_SHA256",
        sha256_file(failed_receipt),
    )
    monkeypatch.setattr(
        acquisition,
        "RECOVERY_ATTEMPT1_SNAPSHOT_MANIFEST_SHA256",
        sha256_file(failed_manifest),
    )
    monkeypatch.setattr(
        acquisition,
        "RECOVERY_ATTEMPT1_TREE_SHA256",
        acquisition._tree_sha256(failed_files),
    )
    failure_log = runtime / "logs" / "sao-live-v2" / f"{RECOVERY_RUN_ID}.log"
    failure_log.parent.mkdir(parents=True)
    failure_log.write_text(
        "SaoAcquisitionError: filesystem lacks atomic no-replace rename support\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        acquisition,
        "RECOVERY_ATTEMPT1_FAILURE_LOG_SHA256",
        sha256_file(failure_log),
    )
    d41 = "\n".join(
        (
            "## D-0041 — fixture hard-link recovery",
            "SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES",
            f"SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID = {RECOVERY_SOURCE_RUN_ID}",
            f"SAO_ACQUISITION_RECOVERY_FAILED_RECOVERY_RUN_ID = {RECOVERY_RUN_ID}",
            f"SAO_ACQUISITION_RECOVERY_RUN_ID = {RECOVERY_ATTEMPT2_RUN_ID}",
            f"SAO_ACQUISITION_RECOVERY_REVISION = {RECOVERY_REVISION}",
            "SAO_ACQUISITION_RECOVERY_FAILED_ACCESS_RECEIPT_SHA256 = "
            f"{sha256_file(failed_receipt)}",
            "SAO_ACQUISITION_RECOVERY_FAILED_SNAPSHOT_MANIFEST_SHA256 = "
            f"{sha256_file(failed_manifest)}",
            "SAO_ACQUISITION_RECOVERY_FAILED_RECOVERY_TREE_SHA256 = "
            f"{acquisition._tree_sha256(failed_files)}",
            "SAO_ACQUISITION_RECOVERY_FAILURE_LOG_SHA256 = "
            f"{sha256_file(failure_log)}",
            "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO",
            "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO",
            "SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0",
            "SAO_ACQUISITION_RECOVERY_MATERIALIZATION = "
            f"{RECOVERY_ATTEMPT2_MATERIALIZATION}",
            "",
        )
    )
    decisions.write_text(d37 + d39 + d41, encoding="utf-8")
    assert acquisition.validate_recovery_decision(decisions)[
        "decision_block_sha256"
    ] == failed_decision["decision_block_sha256"]
    return {
        "config": config,
        "decisions": decisions,
        "run_root": run_root,
        "snapshot_root": snapshot_root,
        "source_run": source_run,
        "failed_run": failed_run,
        "stage": stage,
        "final_snapshot": final_snapshot,
        "failure_log": failure_log,
    }


def _run(paths: dict[str, Path]) -> dict[str, object]:
    return finalize_retained_acquisition_recovery_attempt2(
        paths["config"],
        paths["decisions"],
        command="scripts/finalize_sao_acquisition_recovery_v2_attempt2.py --fixture",
        git_commit="2" * 40,
    )


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_attempt2_hardlinks_exact_receipt_and_preserves_all_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    source_before = _file_bytes(paths["source_run"])
    failed_before = _file_bytes(paths["failed_run"])
    stage_before = _file_bytes(paths["stage"])

    result = _run(paths)

    assert result["status"] == "ACCESS_RECEIPT_RECOVERED_OFFLINE_HARDLINK_NO_GENERATION"
    assert result["materialization"] == RECOVERY_ATTEMPT2_MATERIALIZATION
    assert result["source_stage_retained"] is True
    assert result["network_access"] is result["token_access"] is False
    assert result["gpu_count"] == result["model_calls"] == result["generated_audio"] == 0
    assert _file_bytes(paths["source_run"]) == source_before
    assert _file_bytes(paths["failed_run"]) == failed_before
    assert _file_bytes(paths["stage"]) == stage_before
    for relative in stage_before:
        assert (paths["stage"] / relative).stat().st_ino == (
            paths["final_snapshot"] / relative
        ).stat().st_ino
    verified = validate_access_receipt(
        Path(result["access_receipt_path"]),
        expected_model_id=acquisition.MODEL_ID,
        expected_snapshot_dir=paths["final_snapshot"],
    )
    assert verified["receipt_sha256"] == result["access_receipt_sha256"]
    assert {path.name for path in (paths["run_root"] / RECOVERY_ATTEMPT2_RUN_ID).iterdir()} == {
        "access-receipt.json",
        "snapshot-manifest.json",
        "terminal.json",
    }


def test_attempt2_is_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["final_snapshot"].mkdir()
    sentinel = paths["final_snapshot"] / "sentinel"
    sentinel.write_bytes(b"do-not-overwrite")
    with pytest.raises(FileExistsError):
        _run(paths)
    assert sentinel.read_bytes() == b"do-not-overwrite"
    assert not (paths["run_root"] / RECOVERY_ATTEMPT2_RUN_ID).exists()


@pytest.mark.parametrize("drift", ["receipt", "extra"])
def test_attempt2_rejects_attempt1_closure_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    if drift == "receipt":
        receipt = paths["failed_run"] / "access-receipt.json"
        receipt.write_bytes(receipt.read_bytes() + b"\n")
        match = "access receipt SHA-256 mismatch"
    else:
        (paths["failed_run"] / "unexpected").write_bytes(b"drift")
        match = "closure changed"
    with pytest.raises(SaoAcquisitionError, match=match):
        _run(paths)
    assert not paths["final_snapshot"].exists()
    assert not (paths["run_root"] / RECOVERY_ATTEMPT2_RUN_ID).exists()


def test_attempt2_rejects_failure_log_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["failure_log"].write_bytes(paths["failure_log"].read_bytes() + b"drift\n")
    with pytest.raises(SaoAcquisitionError, match="recovery log path or SHA-256"):
        _run(paths)
    assert not paths["final_snapshot"].exists()
    assert not (paths["run_root"] / RECOVERY_ATTEMPT2_RUN_ID).exists()


def test_attempt2_retains_partial_and_writes_failure_terminal_after_link_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    real_link = acquisition.os.link

    def fail_after_probe(source, destination, *, follow_symlinks=True):
        if ".sao-hardlink-probe-recovery-v2-002" in str(source):
            return real_link(source, destination, follow_symlinks=follow_symlinks)
        raise OSError("fixture hard-link failure")

    monkeypatch.setattr(acquisition.os, "link", fail_after_probe)
    with pytest.raises(OSError, match="fixture hard-link failure"):
        _run(paths)
    attempt2 = paths["run_root"] / RECOVERY_ATTEMPT2_RUN_ID
    failure = json.loads((attempt2 / "terminal-failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "RECOVERY_FAILED_STOPPED_ARTIFACTS_RETAINED"
    assert failure["partial_snapshot_retained"] is True
    assert failure["source_stage_retained"] is True
    assert paths["stage"].is_dir() and paths["final_snapshot"].is_dir()


def test_attempt2_rejects_nonregular_stage_before_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    os.mkfifo(paths["stage"] / "forbidden-fifo")
    with pytest.raises(SaoAcquisitionError, match="non-regular entry"):
        _run(paths)
    assert not paths["final_snapshot"].exists()
    assert not (paths["run_root"] / RECOVERY_ATTEMPT2_RUN_ID).exists()

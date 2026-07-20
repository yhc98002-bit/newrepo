"""Fail-closed, one-claim live runner for the D-0019 Smoke E repair retry."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
import traceback
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sa3_smoke.artifacts import (
    create_immutable_directory,
    create_immutable_run_dir,
    exclusive_write_json,
    sha256_file,
)
from sa3_smoke.budget import ExecutionBudget, smoke_context
from sa3_smoke.run_foundation import (
    EXPECTED_CONFIG_SHA256,
    REPOSITORY_ROOT,
    _common_manifest,
    _provenance_context,
    _resolution_dict,
    _smoke_e_kwargs,
    _verify_resolution_against_manifest,
    capture_process_context,
    default_dependencies,
    validate_preflight,
)

DEFAULT_RETRY_CONFIG = REPOSITORY_ROOT / "configs" / "smoke_e_retry_v1.json"
RETRY_DECISION = "D-0019"
RETRY_CLAIM_NAME = ".sa3-smoke-e-d0019-retry-claim.json"
RETRY_CAPS: Mapping[str, int | float] = {
    "max_generations": 8,
    "max_clip_seconds": 30.0,
    "max_gpus": 1,
    "max_gpu_seconds": 540.0,
}
RETRY_PLAN: Mapping[str, Any] = {
    "official_generate_calls": 4,
    "generated_outputs": 4,
    "calls_by_smoke": {"E": 4},
    "generations_by_smoke": {"E": 4},
    "seed_calls": {"E": {"S-0007": 4}},
}


@dataclass(frozen=True)
class RetryOutcome:
    exit_code: int
    run_dir: Path
    result_path: Path
    result: Mapping[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _repo_path(repository_root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty repository-relative path")
    candidate = (repository_root / value).resolve(strict=True)
    try:
        candidate.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes the repository") from exc
    return candidate


def validate_retry_control(
    *,
    config_path: Path,
    repository_root: Path,
    process_context: Mapping[str, Any],
) -> tuple[dict[str, Any], Any, dict[str, Any], tuple[str, ...]]:
    """Validate the retry wrapper and the complete foundation provenance inputs."""

    failures: list[str] = []
    evidence: dict[str, Any] = {}
    try:
        control = _read_json(config_path)
        control_sha256 = sha256_file(config_path)
    except (OSError, ValueError) as exc:
        control = {}
        control_sha256 = None
        failures.append(str(exc))
    evidence["retry_configuration"] = {
        "path": str(config_path.resolve()),
        "sha256": control_sha256,
    }

    expected_scalars = {
        "version": 1,
        "decision": RETRY_DECISION,
        "scope": "SMOKE_E_ONLY",
        "claim_name": RETRY_CLAIM_NAME,
        "benchmark_execution_authorized": False,
    }
    for name, expected in expected_scalars.items():
        if control.get(name) != expected:
            failures.append(f"retry configuration {name} differs from {expected!r}")
    if control.get("caps") != dict(RETRY_CAPS):
        failures.append("retry caps differ from the code-frozen D-0019 profile")
    if control.get("exact_plan") != dict(RETRY_PLAN):
        failures.append("retry exact plan differs from four E/S-0007 calls and outputs")

    base = control.get("base_configuration")
    base = base if isinstance(base, Mapping) else {}
    try:
        base_path = _repo_path(repository_root, base.get("path"), "base_configuration.path")
        if base.get("sha256") != EXPECTED_CONFIG_SHA256:
            failures.append("retry wrapper names an unexpected foundation config SHA-256")
    except (OSError, ValueError) as exc:
        failures.append(str(exc))
        base_path = repository_root / "configs" / "foundation_v2.json"

    protocol = control.get("protocol")
    protocol = protocol if isinstance(protocol, Mapping) else {}
    try:
        protocol_path = _repo_path(repository_root, protocol.get("path"), "protocol.path")
        protocol_sha256 = sha256_file(protocol_path)
        if protocol.get("sha256") != protocol_sha256:
            failures.append("retry protocol SHA-256 mismatch")
    except (OSError, ValueError) as exc:
        failures.append(str(exc))
        protocol_path = repository_root / "SMOKE_E_RETRY_PROTOCOL_v1.md"
        protocol_sha256 = None
    evidence["retry_protocol"] = {
        "path": str(protocol_path.resolve()),
        "sha256": protocol_sha256,
    }

    repair = control.get("repair")
    repair = repair if isinstance(repair, Mapping) else {}
    if repair.get("strategy") != "export_and_preserve_runtime_latent_dtype_without_cast":
        failures.append("retry repair strategy is not the reviewed no-cast dtype boundary")
    if repair.get("expected_checkpoint_latent_dtype") != "torch.float32":
        failures.append("retry expected checkpoint runtime dtype must be torch.float32")
    for field in ("latent_source", "resume_child_source"):
        record = repair.get(field)
        record = record if isinstance(record, Mapping) else {}
        try:
            source = _repo_path(repository_root, record.get("path"), f"repair.{field}.path")
            if sha256_file(source) != record.get("sha256"):
                failures.append(f"reviewed repair source hash mismatch: {field}")
        except (OSError, ValueError) as exc:
            failures.append(str(exc))

    source_failure = control.get("source_failure")
    source_failure = source_failure if isinstance(source_failure, Mapping) else {}
    for field in ("result", "smoke_e_manifest"):
        record = source_failure.get(field)
        record = record if isinstance(record, Mapping) else {}
        try:
            source = Path(str(record.get("path"))).resolve(strict=True)
            if sha256_file(source) != record.get("sha256"):
                failures.append(f"source failure evidence hash mismatch: {field}")
        except (OSError, ValueError) as exc:
            failures.append(f"invalid source failure evidence {field}: {exc}")

    decisions_path = repository_root / "DECISIONS.md"
    try:
        decisions_text = decisions_path.read_text(encoding="utf-8")
        if "## D-0019" not in decisions_text:
            failures.append("append-only D-0019 retry decision is absent")
        if (
            control_sha256 is None
            or f"RETRY_CONFIG_SHA256 = {control_sha256}" not in decisions_text
        ):
            failures.append("D-0019 does not bind the live retry configuration SHA-256")
        if "SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZED = YES" not in decisions_text:
            failures.append("D-0019 one-shot retry authorization is not open")
    except (OSError, UnicodeDecodeError) as exc:
        failures.append(f"could not validate D-0019: {exc}")

    deps = default_dependencies()
    base_preflight = validate_preflight(
        config_path=base_path,
        repository_root=repository_root,
        expected_config_sha256=EXPECTED_CONFIG_SHA256,
        dependencies=deps,
        process_context=process_context,
        require_clean_git=True,
        authorization_profile="smoke_e_retry",
    )
    failures.extend(base_preflight.failures)
    evidence["base_preflight"] = dict(base_preflight.evidence)
    return control, base_preflight, evidence, tuple(failures)


@contextmanager
def _device_lock(physical_gpu_id: int) -> Iterator[Path]:
    lock_path = Path(f"/tmp/pxy1289-sa3-smoke-e-gpu-{physical_gpu_id}.lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"authorized GPU lock is already held: {lock_path}") from exc
        yield lock_path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _live_placement_evidence(physical_gpu_id: int, minimum_free_mib: int) -> dict[str, Any]:
    query = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.free,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[dict[str, Any]] = []
    for line in query.stdout.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 6:
            raise RuntimeError(f"unexpected nvidia-smi GPU row: {line!r}")
        rows.append(
            {
                "index": int(fields[0]),
                "uuid": fields[1],
                "name": fields[2],
                "memory_free_mib": int(fields[3]),
                "memory_total_mib": int(fields[4]),
                "utilization_gpu_percent": int(fields[5]),
            }
        )
    selected = [row for row in rows if row["index"] == physical_gpu_id]
    if len(selected) != 1:
        raise RuntimeError(f"physical GPU {physical_gpu_id} not found")
    gpu = selected[0]
    processes = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    active = []
    for line in processes.stdout.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) == 3 and fields[0] == gpu["uuid"]:
            active.append(
                {"gpu_uuid": fields[0], "pid": int(fields[1]), "used_memory_mib": int(fields[2])}
            )
    checks = {
        "a800": "A800" in gpu["name"],
        "no_compute_processes": not active,
        "minimum_free_memory": gpu["memory_free_mib"] >= minimum_free_mib,
        "low_idle_utilization": gpu["utilization_gpu_percent"] <= 5,
        "one_visible_gpu": os.environ.get("CUDA_VISIBLE_DEVICES") == str(physical_gpu_id),
    }
    if not all(checks.values()):
        raise RuntimeError(
            f"selected GPU is not safely idle: gpu={gpu}, active={active}, checks={checks}"
        )
    return {
        "captured_at_utc": _utc_now(),
        "selected_gpu": gpu,
        "active_compute_processes": active,
        "minimum_free_memory_mib": minimum_free_mib,
        "checks": checks,
    }


def run_smoke_e_retry(
    config_path: str | os.PathLike[str] = DEFAULT_RETRY_CONFIG,
    *,
    repository_root: str | os.PathLike[str] = REPOSITORY_ROOT,
) -> RetryOutcome:
    """Consume the one D-0019 claim and run Smoke E, and only Smoke E, once."""

    started_at = _utc_now()
    repo = Path(repository_root).resolve()
    control_path = Path(config_path).resolve()
    initial_control = _read_json(control_path)
    placement = initial_control.get("placement")
    if not isinstance(placement, Mapping):
        raise ValueError("retry placement must be an object")
    gpu_ids = placement.get("gpu_ids")
    if not isinstance(gpu_ids, list) or len(gpu_ids) != 1 or not isinstance(gpu_ids[0], int):
        raise ValueError("retry placement must bind exactly one physical GPU ID")
    physical_gpu_id = gpu_ids[0]
    minimum_free_mib = int(placement.get("minimum_free_memory_mib", 60_000))

    with _device_lock(physical_gpu_id) as lock_path:
        context = capture_process_context()
        control, preflight, retry_evidence, failures = validate_retry_control(
            config_path=control_path,
            repository_root=repo,
            process_context=context,
        )
        if failures:
            raise RuntimeError(
                "retry preflight failed before claim creation: " + "; ".join(failures)
            )
        placement_evidence = _live_placement_evidence(physical_gpu_id, minimum_free_mib)
        placement_evidence["lock_path"] = str(lock_path)
        placement_evidence["lock_held_during_probe_and_execution"] = True

        run_root = Path(str(control["run_root"])).resolve()
        run_dir = create_immutable_run_dir(run_root, prefix="sa3-smoke-e-retry")
        smoke_dir = create_immutable_directory(run_dir / "smoke-e")
        resolution_dir = create_immutable_directory(run_dir / "model-config-resolution")
        placement_path = run_dir / "live-placement-preflight.json"
        exclusive_write_json(placement_path, placement_evidence)

        budget = ExecutionBudget.initialize(
            run_dir=run_dir,
            run_root=run_root,
            claim_identity={
                "repository_git_hash": preflight.evidence["git"]["head"],
                "retry_configuration_sha256": sha256_file(control_path),
                "foundation_configuration_sha256": EXPECTED_CONFIG_SHA256,
                "retry_protocol_sha256": retry_evidence["retry_protocol"]["sha256"],
                "decisions_sha256": preflight.evidence["governance_authorization"]["sha256"],
                "seed_registry_sha256": preflight.evidence["seed_registry"]["sha256"],
                "weights_manifest_sha256": preflight.evidence["weights_manifests"][
                    "local_snapshot_v1"
                ]["sha256"],
                "live_placement_preflight_sha256": sha256_file(placement_path),
            },
            decision=RETRY_DECISION,
            claim_name=RETRY_CLAIM_NAME,
            caps=RETRY_CAPS,
            exact_plan=RETRY_PLAN,
        )

        setup_error: str | None = None
        runtime = None
        resolution = None
        resolution_verification = None
        model_load_seconds = None
        try:
            snapshot = Path(str(preflight.config["model"]["snapshot"])).resolve(strict=True)
            deps = default_dependencies()
            resolution = deps.resolve_model_config(
                snapshot / "model_config.json",
                snapshot / "t5gemma-b-b-ul2",
                resolution_dir,
            )
            resolution_verification = _verify_resolution_against_manifest(
                resolution, preflight.model_artifact_sha256s
            )
            load_started = time.perf_counter()
            runtime = deps.load_model(
                resolution,
                snapshot / "model.safetensors",
                device="cuda:0",
                model_half=bool(preflight.config["model"]["model_half"]),
                expected_checkpoint_sha256=preflight.model_artifact_sha256s["model.safetensors"],
            )
            import torch

            torch.cuda.synchronize(torch.device("cuda:0"))
            model_load_seconds = float(time.perf_counter() - load_started)
        except Exception as exc:  # noqa: BLE001 - terminal retry evidence
            setup_error = f"{type(exc).__name__}: {exc}"

        if runtime is None:
            smoke_result: dict[str, Any] = {
                "smoke": "E",
                "status": "FAIL",
                "started_at_utc": started_at,
                "ended_at_utc": _utc_now(),
                "parameters": {},
                "checks": {},
                "metrics": {},
                "artifacts": {},
                "error": {"stage": "model_setup", "message": setup_error},
            }
        else:
            try:
                with smoke_context("E"):
                    smoke_result = (
                        default_dependencies()
                        .run_smoke_e(
                            runtime,
                            smoke_dir,
                            **_smoke_e_kwargs(
                                frozen_config_path=repo / "configs" / "foundation_v2.json",
                                provenance=_provenance_context(
                                    run_dir=run_dir,
                                    smoke="E",
                                    config=preflight.config,
                                    command=str(context["exact_command"]),
                                ),
                            ),
                            child_timeout_seconds=120.0,
                        )
                        .to_dict()
                    )
                checkpoints = smoke_result.get("artifacts", {}).get("checkpoints", [])
                resumes = smoke_result.get("artifacts", {}).get("resumes", [])
                retry_dtype_gate = bool(
                    len(checkpoints) == 3
                    and all(row.get("latent_dtype") == "torch.float32" for row in checkpoints)
                    and len(resumes) == 3
                    and all(
                        row.get("fresh_initial_latent_dtype") == "torch.float16"
                        and row.get("checkpoint_latent_dtype") == "torch.float32"
                        and row.get("resume_latent_dtype_preserved") is True
                        for row in resumes
                    )
                )
                smoke_checks = dict(smoke_result.get("checks", {}))
                smoke_checks["d0019_runtime_float32_checkpoint_dtype_preserved_without_cast"] = (
                    retry_dtype_gate
                )
                smoke_result["checks"] = smoke_checks
                if not retry_dtype_gate:
                    smoke_result["status"] = "FAIL"
            except Exception as exc:  # noqa: BLE001 - terminal retry evidence
                smoke_result = {
                    "smoke": "E",
                    "status": "FAIL",
                    "started_at_utc": started_at,
                    "ended_at_utc": _utc_now(),
                    "parameters": {},
                    "checks": {},
                    "metrics": {},
                    "artifacts": {},
                    "error": {
                        "stage": "smoke_e",
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                }

        budget_summary = budget.finalize()
        passed = smoke_result["status"] == "PASS" and budget_summary["status"] == "PASS"
        smoke_status = "PASS" if passed else "FAIL"
        state_capability = "PASS" if passed else "NOT_IDENTIFIABLE"
        manifest = _common_manifest(
            smoke="E",
            result=smoke_result,
            run_dir=run_dir,
            preflight=preflight,
            config_path=repo / "configs" / "foundation_v2.json",
            process_context=context,
            resolution=resolution,
            deviations=[
                {
                    "checkpoint_dtype_boundary": (
                        "exported evolved runtime latent remains torch.float32; resume ignores "
                        "disposable fresh FP16 values and preserves checkpoint dtype without cast"
                    )
                },
                {"scope": "Smoke E only; A-D and benchmark execution were closed"},
            ],
        )
        manifest.update(
            {
                "schema_version": 2,
                "retry_decision": RETRY_DECISION,
                "retry_configuration": {
                    "path": str(control_path),
                    "sha256": sha256_file(control_path),
                    "frozen": control,
                },
                "retry_protocol": retry_evidence["retry_protocol"],
                "live_placement_preflight": {
                    "path": str(placement_path),
                    "sha256": sha256_file(placement_path),
                    "evidence": placement_evidence,
                },
                "execution_budget": budget_summary,
                "model_setup": {
                    "status": "PASS" if runtime is not None else "FAIL",
                    "error": setup_error,
                    "load_wall_seconds": model_load_seconds,
                    "config_resolution": _resolution_dict(resolution) if resolution else None,
                    "resolution_verification": resolution_verification,
                },
                "benchmark_execution_authorized": False,
            }
        )
        manifest_path = smoke_dir / "manifest.json"
        exclusive_write_json(manifest_path, manifest)

        terminal = {
            "schema_version": 1,
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "started_at_utc": started_at,
            "ended_at_utc": _utc_now(),
            "SA3_SMOKE_E_RETRY_STATUS": "PASS" if passed else "FAIL_ESCALATED",
            "SMOKE_E": smoke_status,
            "SA3_STATE_CAPABILITY": state_capability,
            "exit_code": 0 if passed else 1,
            "benchmark_execution_authorized": False,
            "retry_configuration": retry_evidence["retry_configuration"],
            "base_preflight": {
                "status": "PASS",
                "evidence": dict(preflight.evidence),
            },
            "live_placement_preflight": {
                "path": str(placement_path),
                "sha256": sha256_file(placement_path),
            },
            "model_setup": manifest["model_setup"],
            "execution_budget": budget_summary,
            "smoke_e": {
                "status": smoke_status,
                "result": smoke_result,
                "manifest_path": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
            },
        }
        result_path = run_dir / "result.json"
        exclusive_write_json(result_path, terminal)
        return RetryOutcome(
            exit_code=int(terminal["exit_code"]),
            run_dir=run_dir,
            result_path=result_path,
            result=terminal,
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_RETRY_CONFIG)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.preflight_only:
        control = _read_json(args.config.resolve())
        placement = control.get("placement", {})
        gpu_ids = placement.get("gpu_ids") if isinstance(placement, Mapping) else None
        if not isinstance(gpu_ids, list) or len(gpu_ids) != 1:
            raise ValueError("retry config must select one GPU")
        with _device_lock(int(gpu_ids[0])) as lock_path:
            context = capture_process_context()
            _, preflight, evidence, failures = validate_retry_control(
                config_path=args.config.resolve(),
                repository_root=args.repository_root.resolve(),
                process_context=context,
            )
            placement_evidence = None
            if not failures:
                placement_evidence = _live_placement_evidence(
                    int(gpu_ids[0]), int(placement.get("minimum_free_memory_mib", 60_000))
                )
            print(
                json.dumps(
                    {
                        "status": "PASS" if not failures else "FAIL",
                        "failures": list(failures),
                        "retry_evidence": evidence,
                        "base_preflight_passed": preflight.passed,
                        "live_placement": placement_evidence,
                        "lock_path": str(lock_path),
                        "claim_created": False,
                    },
                    allow_nan=False,
                    sort_keys=True,
                )
            )
            return 0 if not failures else 2
    outcome = run_smoke_e_retry(args.config, repository_root=args.repository_root)
    print(json.dumps(outcome.result, allow_nan=False, sort_keys=True))
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

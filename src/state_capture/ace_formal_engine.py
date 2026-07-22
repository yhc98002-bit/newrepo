"""Production ACE formal group orchestration using the preflight-proven engine."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scoring.common import load_json, sha256_file
from scoring.storage import write_json_exclusive
from state_capture.ace_artifacts import (
    basic_audio_sanity,
    compare_audio_equivalence,
    write_bytes_exclusive,
)
from state_capture.ace_child import (
    RESUME_CHILD_REQUEST_FORMAT,
    RESUME_CHILD_RESULT_FORMAT,
)
from state_capture.ace_contract import json_sha256, validate_static_config
from state_capture.ace_engine import (
    MODEL_ID,
    inspect_production_capability,
    resolve_engine_factory,
    validate_engine_result,
)
from state_capture.ace_formal_contract import (
    AceFormalConfig,
    validate_formal_call_claim,
    validate_formal_engine_claim,
)


class AceFormalEngineError(RuntimeError):
    """A formal group violated checkpoint, preview, child, or artifact identity."""


def _copy_exclusive(source: Path, destination: Path) -> None:
    if not source.is_file() or source.stat().st_size <= 0:
        raise AceFormalEngineError(f"staged formal artifact is absent: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_bytes_exclusive(destination, source.read_bytes())


def _relocate_checkpoint(source: Path, destination: Path) -> dict[str, str]:
    sidecar_source = source.with_name(f"{source.name}.state.json")
    metadata = load_json(sidecar_source)
    claimed = metadata.get("state_identity_sha256")
    unhashed = dict(metadata)
    unhashed.pop("state_identity_sha256", None)
    if claimed != json_sha256(unhashed) or metadata.get("artifact_path") != str(source.resolve()):
        raise AceFormalEngineError("staged ACE checkpoint sidecar identity drifted")
    _copy_exclusive(source, destination)
    relocated = dict(metadata)
    relocated["artifact_path"] = str(destination.resolve())
    relocated["artifact_sha256"] = sha256_file(destination)
    relocated["artifact_size_bytes"] = destination.stat().st_size
    relocated.pop("state_identity_sha256", None)
    relocated["state_identity_sha256"] = json_sha256(relocated)
    sidecar_destination = destination.with_name(f"{destination.name}.state.json")
    write_json_exclusive(sidecar_destination, relocated)
    return {
        "checkpoint_sha256": sha256_file(destination),
        "state_metadata_sha256": sha256_file(sidecar_destination),
    }


def _engine_context(
    config: AceFormalConfig,
    *,
    run_dir: Path,
    claim: Mapping[str, Any],
    call_claim: Mapping[str, Any],
) -> dict[str, Any]:
    claim_path = Path(str(claim["path"])).resolve(strict=True)
    validate_formal_engine_claim(claim_path)
    call_claim_path = Path(str(call_claim["path"])).resolve(strict=True)
    validated_call = validate_formal_call_claim(call_claim_path)
    claim_root = call_claim_path.parent.parent
    return {
        "config_path": str(config.preflight_config_path),
        "config_sha256": config.raw["engine"]["preflight_config"]["sha256"],
        "execution_scope": "FORMAL_INITIAL_SURVIVOR_GROUP",
        "formal_claim_path": str(claim_path),
        "formal_claim_sha256": sha256_file(claim_path),
        "formal_call_claim_path": str(call_claim_path),
        "formal_call_claim_sha256": sha256_file(call_claim_path),
        "formal_call_kind": validated_call["call_kind"],
        "formal_coordination_lock_path": str(claim_root / "reservation.lock"),
        "formal_failure_latch_path": str(claim_root.parent / "formal-terminal-failure.json"),
        "formal_request_sha256": validated_call["request_sha256"],
        "repository_root": str(config.repo_root),
        "run_dir": str(run_dir.resolve()),
    }


def _child_request(
    *,
    request_id: str,
    engine_context: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    reference_request: Mapping[str, Any],
    output_path: Path,
    result_path: Path,
    config_sha256: str,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "checkpoint_path": checkpoint["path"],
        "checkpoint_sha256": checkpoint["sha256"],
        "checkpoint_state_metadata_sha256": checkpoint["state_metadata_sha256"],
        "config_sha256": config_sha256,
        "engine_context": dict(engine_context),
        "engine_context_sha256": json_sha256(dict(engine_context)),
        "engine_factory": "state_capture.ace_engine:formal_engine_factory",
        "format": RESUME_CHILD_REQUEST_FORMAT,
        "output_path": str(output_path.resolve()),
        "parent_pid": os.getpid(),
        "reference_request": dict(reference_request),
        "request_id": request_id,
        "result_path": str(result_path.resolve()),
    }
    request["request_identity_sha256"] = json_sha256(request)
    return request


def _validated_child_result(
    child: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    request_path: Path,
    checkpoint: Mapping[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    required = {
        "checkpoint_path",
        "checkpoint_sha256",
        "child_pid",
        "engine_result",
        "format",
        "os_parent_pid",
        "parent_pid",
        "request_identity_sha256",
        "request_path",
        "request_sha256",
        "result_identity_sha256",
        "status",
    }
    value = dict(child)
    claimed = value.pop("result_identity_sha256", None)
    if set(child) != required or claimed != json_sha256(value):
        raise AceFormalEngineError("formal resume child result identity drifted")
    child_pid = child.get("child_pid")
    if (
        child.get("format") != RESUME_CHILD_RESULT_FORMAT
        or child.get("status") != "PASS"
        or child.get("request_path") != str(request_path.resolve())
        or child.get("request_sha256") != sha256_file(request_path)
        or child.get("request_identity_sha256") != request["request_identity_sha256"]
        or child.get("parent_pid") != os.getpid()
        or child.get("os_parent_pid") != os.getpid()
        or isinstance(child_pid, bool)
        or not isinstance(child_pid, int)
        or child_pid <= 0
        or child_pid == os.getpid()
        or child.get("checkpoint_path") != checkpoint["path"]
        or child.get("checkpoint_sha256") != checkpoint["sha256"]
    ):
        raise AceFormalEngineError("formal resume child provenance drifted")
    engine_result = validate_engine_result(child["engine_result"], mode="RESUME")
    if (
        engine_result.get("pid") != child_pid
        or Path(str(engine_result["output_path"])).resolve(strict=True)
        != output_path.resolve(strict=True)
        or engine_result.get("checkpoint_source_path") != checkpoint["path"]
        or engine_result.get("checkpoint_source_sha256") != checkpoint["sha256"]
    ):
        raise AceFormalEngineError("formal child engine result differs from its request")
    return engine_result


class ProductionAceFormalGroupEngine:
    """One reference/export plus three separate-process resumes per survivor root."""

    model_id = MODEL_ID

    def __init__(self, config: AceFormalConfig, *, run_dir: Path) -> None:
        self.config = config
        self.run_dir = run_dir.resolve()
        self.preflight_contract = validate_static_config(
            config.preflight_config_path, repository_root=config.repo_root
        )
        self._preflight: dict[str, Any] | None = None

    def preflight(self) -> Mapping[str, Any]:
        capability = inspect_production_capability(self.preflight_contract)
        if capability["status"] != "READY":
            raise AceFormalEngineError(
                "ACE formal production capability is blocked: " + "; ".join(capability["failures"])
            )
        self._preflight = capability
        return {"capability": capability, "model_id": MODEL_ID, "status": "READY"}

    def load(self) -> Mapping[str, Any]:
        if self._preflight is None:
            raise AceFormalEngineError("formal engine must preflight before load boundary")
        return {"mode": "LOAD_PER_REFERENCE_AND_SEPARATE_RESUME_CHILD", "status": "READY"}

    def _launch_child(self, request_path: Path, timeout_seconds: float) -> None:
        environment = dict(os.environ)
        source_root = self.config.repo_root / "src"
        prefixes = [str(source_root), os.environ.get("ACE_STEP_V1_SOURCE_DIR", "")]
        if environment.get("PYTHONPATH"):
            prefixes.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(value for value in prefixes if value)
        subprocess.run(
            [sys.executable, "-B", "-m", "state_capture.ace_child", "--request", str(request_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=self.config.repo_root,
            env=environment,
        )

    def run_group(
        self,
        group: Mapping[str, Any],
        units: Sequence[Mapping[str, Any]],
        claim: Mapping[str, Any],
        boundary: Any,
    ) -> Mapping[str, Any]:
        if self._preflight is None or len(units) != 3:
            raise AceFormalEngineError("formal group lacks preflight or three checkpoint units")
        validated_claim = validate_formal_engine_claim(Path(str(claim["path"])))
        if (
            validated_claim["group_request_sha256"] != group["group_request_sha256"]
            or validated_claim["axis"] != group["axis"]
        ):
            raise AceFormalEngineError("formal claim/group identity drifted")
        expected_ids = list(group["lane_request_sha256s"])
        if expected_ids != [unit["lane_request_sha256"] for unit in units]:
            raise AceFormalEngineError("formal group/unit order drifted")
        identity = str(group["group_request_sha256"])
        staging = self.run_dir / "staging" / identity
        staging.mkdir(parents=True, exist_ok=False)
        state_dir = staging / "state"
        reference_path = staging / "reference.wav"
        factory = resolve_engine_factory("state_capture.ace_engine:formal_engine_factory")
        reference_request = {"prompt": group["prompt"], "seed": group["seed"]}
        gpu_seconds = 0.0
        peak_allocated = 0
        peak_reserved = 0
        started = time.monotonic()
        parent: Any | None = None
        try:
            prefix_call_claim = boundary.start("PREFIX_GROUP", group)
            context = _engine_context(
                self.config,
                run_dir=self.run_dir,
                claim=claim,
                call_claim=prefix_call_claim,
            )
            parent = factory(context)
            reference = validate_engine_result(
                parent.run_reference(
                    request=reference_request,
                    output_path=reference_path,
                    state_dir=state_dir,
                ),
                mode="REFERENCE",
            )
            if (
                reference["actual_nfe"] != 45
                or len(reference["checkpoints"]) != 3
                or reference.get("pid") != os.getpid()
                or Path(str(reference["output_path"])).resolve(strict=True)
                != reference_path.resolve(strict=True)
                or reference.get("checkpoint_source_path") is not None
                or reference.get("checkpoint_source_sha256") is not None
            ):
                raise AceFormalEngineError("formal reference did not export the exact 45-NFE set")
            gpu_seconds += float(reference["gpu_seconds"])
            peak_allocated = max(peak_allocated, int(reference["peak_allocated_bytes"]))
            peak_reserved = max(peak_reserved, int(reference["peak_reserved_bytes"]))
            checkpoints = sorted(
                reference["checkpoints"], key=lambda row: row["checkpoint_fraction"]
            )
            preview_records: list[dict[str, Any]] = []
            for unit, checkpoint in zip(units, checkpoints, strict=True):
                if (
                    checkpoint["checkpoint_fraction"] != unit["checkpoint_fraction"]
                    or checkpoint["completed_scheduler_transitions"]
                    != unit["checkpoint_completed_scheduler_transitions"]
                    or checkpoint["cumulative_transformer_nfe"]
                    != unit["checkpoint_cumulative_transformer_nfe"]
                ):
                    raise AceFormalEngineError("formal checkpoint mapping drifted")
                preview_path = staging / f"preview-{int(unit['checkpoint_fraction'] * 100):03d}.wav"
                preview = dict(
                    parent.decode_preview(
                        checkpoint_path=Path(checkpoint["path"]),
                        checkpoint_sha256=checkpoint["sha256"],
                        output_path=preview_path,
                    )
                )
                if (
                    preview.get("root_local_only") is not True
                    or Path(str(preview.get("output_path"))).resolve(strict=True)
                    != preview_path.resolve(strict=True)
                    or preview.get("output_sha256") != sha256_file(preview_path)
                ):
                    raise AceFormalEngineError("formal preview is not same-root only")
                preview["sanity"] = basic_audio_sanity(
                    preview_path, requested_duration_seconds=30.0
                )
                gpu_seconds += float(preview["gpu_seconds"])
                peak_allocated = max(peak_allocated, int(preview["peak_allocated_bytes"]))
                peak_reserved = max(peak_reserved, int(preview["peak_reserved_bytes"]))
                preview_records.append(preview)
            boundary.succeed(
                "PREFIX_GROUP",
                group,
                {
                    "actual_nfe": reference["actual_nfe"],
                    "checkpoint_count": len(checkpoints),
                    "gpu_seconds": (
                        float(reference["gpu_seconds"])
                        + sum(float(row["gpu_seconds"]) for row in preview_records)
                    ),
                    "preview_count": len(preview_records),
                    "reference_sha256": reference["output_sha256"],
                    "same_root_previews": True,
                },
            )
        finally:
            if parent is not None:
                parent.close()
        reference_sanity = basic_audio_sanity(reference_path, requested_duration_seconds=30.0)
        child_records: list[dict[str, Any]] = []
        for index, (unit, checkpoint) in enumerate(zip(units, checkpoints, strict=True)):
            output = staging / f"resume-{int(unit['checkpoint_fraction'] * 100):03d}.wav"
            result_path = staging / f"resume-{int(unit['checkpoint_fraction'] * 100):03d}.json"
            resume_call_claim = boundary.start("RESUME_UNIT", unit)
            resume_context = _engine_context(
                self.config,
                run_dir=self.run_dir,
                claim=claim,
                call_claim=resume_call_claim,
            )
            request = _child_request(
                request_id=str(unit["lane_request_sha256"]),
                engine_context=resume_context,
                checkpoint=checkpoint,
                reference_request=reference_request,
                output_path=output,
                result_path=result_path,
                config_sha256=self.preflight_contract.sha256,
            )
            request_path = staging / f"resume-{index:02d}.request.json"
            write_json_exclusive(request_path, request)
            remaining = max(
                1.0,
                float(self.config.raw["budget"]["group_reservation_gpu_seconds"])
                - (time.monotonic() - started),
            )
            self._launch_child(request_path, remaining)
            child = load_json(result_path)
            engine_result = _validated_child_result(
                child,
                request=request,
                request_path=request_path,
                checkpoint=checkpoint,
                output_path=output,
            )
            expected_remaining_nfe = int(unit["total_transformer_nfe"]) - int(
                unit["checkpoint_cumulative_transformer_nfe"]
            )
            if engine_result["actual_nfe"] != expected_remaining_nfe:
                raise AceFormalEngineError("formal resume used the wrong remaining NFE budget")
            equivalence = compare_audio_equivalence(
                reference_path,
                output,
                max_absolute_error=float(
                    self.preflight_contract.raw["equivalence"]["max_absolute_error"]
                ),
                minimum_snr_db=float(self.preflight_contract.raw["equivalence"]["minimum_snr_db"]),
            )
            if equivalence["status"] != "PASS":
                raise AceFormalEngineError("formal reload-and-continue equivalence failed")
            resumed_sanity = basic_audio_sanity(output, requested_duration_seconds=30.0)
            gpu_seconds += float(engine_result["gpu_seconds"])
            peak_allocated = max(peak_allocated, int(engine_result["peak_allocated_bytes"]))
            peak_reserved = max(peak_reserved, int(engine_result["peak_reserved_bytes"]))
            child_records.append(
                {
                    "child_pid": child["child_pid"],
                    "engine_result": engine_result,
                    "equivalence": equivalence,
                    "output_path": str(output),
                    "request_path": str(request_path),
                    "result_path": str(result_path),
                    "sanity": resumed_sanity,
                }
            )
            boundary.succeed(
                "RESUME_UNIT",
                unit,
                {
                    "actual_nfe": engine_result["actual_nfe"],
                    "child_pid": child["child_pid"],
                    "equivalence_status": equivalence["status"],
                    "gpu_seconds": engine_result["gpu_seconds"],
                    "output_sha256": engine_result["output_sha256"],
                },
            )

        artifact_root = self.run_dir / "artifacts"
        reference_destination = artifact_root / str(group["reference_terminal_relpath"])
        unit_commits: list[dict[str, Any]] = []
        with boundary.publish_guard():
            _copy_exclusive(reference_path, reference_destination)
            for unit, checkpoint, preview, child in zip(
                units, checkpoints, preview_records, child_records, strict=True
            ):
                checkpoint_destination = artifact_root / str(unit["checkpoint_relpath"])
                checkpoint_binding = _relocate_checkpoint(
                    Path(checkpoint["path"]), checkpoint_destination
                )
                preview_destination = artifact_root / str(unit["preview_relpath"])
                resumed_destination = artifact_root / str(unit["resumed_terminal_relpath"])
                _copy_exclusive(Path(preview["output_path"]), preview_destination)
                _copy_exclusive(Path(child["output_path"]), resumed_destination)
                feature_path = preview_destination.with_suffix(".feature-contract.json")
                feature = {
                    "axis": unit["axis"],
                    "checkpoint_fraction": unit["checkpoint_fraction"],
                    "feature_contract": unit["feature_contract"],
                    "lane_request_sha256": unit["lane_request_sha256"],
                    "preview_sha256": sha256_file(preview_destination),
                    "preview_source_request_sha256": unit["preview_source_request_sha256"],
                    "root_index": unit["root_index"],
                    "root_local_only": True,
                    "schema_version": 1,
                    "sanity": preview["sanity"],
                }
                write_json_exclusive(feature_path, feature)
                unit_commit = {
                    "child_pid": child["child_pid"],
                    "child_request_path": child["request_path"],
                    "child_request_sha256": sha256_file(Path(child["request_path"])),
                    "child_result_path": child["result_path"],
                    "child_result_sha256": sha256_file(Path(child["result_path"])),
                    "checkpoint": checkpoint_binding,
                    "checkpoint_fraction": unit["checkpoint_fraction"],
                    "equivalence": child["equivalence"],
                    "feature_contract_path": str(feature_path),
                    "feature_contract_sha256": sha256_file(feature_path),
                    "lane_request_sha256": unit["lane_request_sha256"],
                    "preview_path": str(preview_destination),
                    "preview_sanity": preview["sanity"],
                    "preview_sha256": sha256_file(preview_destination),
                    "resume_actual_nfe": child["engine_result"]["actual_nfe"],
                    "resumed_terminal_path": str(resumed_destination),
                    "resumed_terminal_sanity": child["sanity"],
                    "resumed_terminal_sha256": sha256_file(resumed_destination),
                    "same_root_preview": True,
                    "schema_version": 1,
                    "status": "COMMITTED",
                }
                unit_commit_path = resumed_destination.with_suffix(".commit.json")
                write_json_exclusive(unit_commit_path, unit_commit)
                unit_commits.append(
                    {
                        "lane_request_sha256": unit["lane_request_sha256"],
                        "path": str(unit_commit_path),
                        "sha256": sha256_file(unit_commit_path),
                    }
                )
            group_commit = {
                "axis": group["axis"],
                "claim_sha256": claim["sha256"],
                "group_request_sha256": identity,
                "model_calls": 4,
                "reference_path": str(reference_destination),
                "reference_sanity": reference_sanity,
                "reference_sha256": sha256_file(reference_destination),
                "same_root_previews": True,
                "schema_version": 1,
                "status": "COMMITTED",
                "unit_commits": unit_commits,
            }
            commit_path = reference_destination.with_suffix(".formal-group.commit.json")
            write_json_exclusive(commit_path, group_commit)
        return {
            "artifact_commit_path": str(commit_path),
            "artifact_commit_sha256": sha256_file(commit_path),
            "completed_units": 3,
            "gpu_seconds": gpu_seconds,
            "group_request_sha256": identity,
            "model_calls": 4,
            "peak_allocated_bytes": peak_allocated,
            "peak_reserved_bytes": peak_reserved,
            "same_root_previews": True,
            "status": "PASS",
        }

    def close(self) -> None:
        return None


__all__ = ["AceFormalEngineError", "ProductionAceFormalGroupEngine"]

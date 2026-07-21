"""Terminal orchestration for the sole authorized ACE state-preflight attempt."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from state_capture.ace_artifacts import (
    ArtifactValidationError,
    HashChainedLedger,
    Heartbeat,
    OneShotAttemptStore,
    aggregate_gpu_measurements,
    basic_audio_sanity,
    compare_audio_equivalence,
    safe_external_path,
    sha256_file,
    utc_now,
    validate_adjacent_provenance,
    validate_ledger,
    write_adjacent_provenance,
    write_json_exclusive,
)
from state_capture.ace_child import (
    RESUME_CHILD_REQUEST_FORMAT,
    RESUME_CHILD_RESULT_FORMAT,
)
from state_capture.ace_contract import (
    ATTEMPT_ID,
    CHECKPOINT_COMPLETED_TRANSITIONS,
    CHECKPOINT_CUMULATIVE_NFE,
    CHECKPOINT_FRACTIONS,
    EXECUTE_PHRASE,
    MAX_GPU_SECONDS,
    MAX_MODEL_CALLS,
    OUTER_KILL_GRACE_SECONDS,
    OUTER_SOFT_TIMEOUT_SECONDS,
    PACKAGE_RELATIVE_PATHS,
    RUN_ID,
    Authorization,
    LoadedContract,
    json_sha256,
    load_json_object,
    static_readiness_report,
    validate_external_authorization,
    validate_static_config,
)
from state_capture.ace_engine import (
    AceStateEngine,
    build_engine_context,
    inspect_production_capability,
    resolve_engine_factory,
    validate_engine_result,
)


class AuthorizedAttemptFailed(RuntimeError):
    """A failure after the external authority was irreversibly consumed."""

    def __init__(self, message: str, terminal: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.terminal = dict(terminal)


def package_hashes(repository_root: str | Path) -> dict[str, str]:
    root = Path(repository_root).resolve(strict=True)
    result: dict[str, str] = {}
    for relative in PACKAGE_RELATIVE_PATHS:
        path = (root / relative).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ArtifactValidationError(f"package path escapes repository: {relative}") from exc
        result[relative] = sha256_file(path)
    return result


def run_dry_preflight(
    *,
    config_path: str | Path,
    repository_root: str | Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run read-only static and engine-surface checks with zero model calls."""

    contract = validate_static_config(config_path, repository_root=repository_root)
    readiness = static_readiness_report(contract, repository_root=repository_root)
    capability = inspect_production_capability(contract, environ=environ)
    blockers = list(readiness["blocking_gates"])
    if capability["status"] != "READY":
        blockers.append("ACE_ENGINE_CAPABILITY_BLOCKED")
    return {
        **readiness,
        "status": "PREPARED_NOT_AUTHORIZED",
        "engine_capability": capability,
        "blocking_gates": blockers,
        "package_sha256": package_hashes(repository_root),
        "writes_performed": False,
        "cuda_touched": False,
    }


def _placement_config(contract: LoadedContract, authorization: Authorization) -> Any:
    from benchmark_core.config import PlacementConfig

    placement = contract.raw["placement"]
    return PlacementConfig(
        node=authorization.node,
        physical_gpu_id=authorization.physical_gpu_id,
        logical_gpu_id=0,
        tp_width=1,
        replica_count=1,
        minimum_free_vram_bytes=int(placement["minimum_free_vram_bytes"]),
        post_load_reserve_bytes=int(placement["post_load_reserve_bytes"]),
        lock_root=Path(placement["cooperative_lock_root"]),
        required_gpu_name_substring=str(placement["required_gpu_name_substring"]),
        maximum_idle_utilization_percent=int(placement["maximum_idle_utilization_percent"]),
    )


def _observation_dict(observation: Any) -> dict[str, Any]:
    return {
        "node": observation.node,
        "physical_gpu_id": observation.physical_gpu_id,
        "logical_gpu_id": observation.logical_gpu_id,
        "gpu_uuid": observation.gpu_uuid,
        "gpu_name": observation.gpu_name,
        "free_vram_bytes": observation.free_vram_bytes,
        "total_vram_bytes": observation.total_vram_bytes,
        "utilization_percent": observation.utilization_percent,
        "compute_pids": list(observation.compute_pids),
    }


@contextmanager
def production_placement(
    contract: LoadedContract, authorization: Authorization
) -> Iterator[tuple[Any, Any, dict[str, Any]]]:
    """Acquire the ordinary-core cooperative lock and never alter neighbors."""

    from benchmark_core.placement import DeviceLease, NvidiaSmiProbe

    hostname = socket.gethostname().split(".", 1)[0]
    if hostname != authorization.node:
        raise ArtifactValidationError(
            f"live node {hostname} differs from authorized node {authorization.node}"
        )
    if os.environ.get("CUDA_VISIBLE_DEVICES") != str(authorization.physical_gpu_id):
        raise ArtifactValidationError(
            "CUDA_VISIBLE_DEVICES must expose exactly the authorized physical GPU"
        )
    configured = _placement_config(contract, authorization)
    lease = DeviceLease(configured)
    with lease:
        probe = NvidiaSmiProbe(configured)
        observation = probe.require_safe(
            minimum_free_vram_bytes=configured.minimum_free_vram_bytes,
            allowed_pids=(),
            maximum_utilization_percent=configured.maximum_idle_utilization_percent,
        )
        yield configured, probe, _observation_dict(observation)


def _write_call_claim(
    *,
    claim_dir: Path,
    ledger: HashChainedLedger,
    call_id: str,
    call_index: int,
    request: Mapping[str, Any],
    attempt_claim_sha256: str,
    config_sha256: str,
) -> dict[str, Any]:
    if call_index not in range(MAX_MODEL_CALLS):
        raise ArtifactValidationError("model-call index exceeds the frozen four-call schedule")
    identity = json_sha256(dict(request))
    record: dict[str, Any] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "call_id": call_id,
        "call_index": call_index,
        "claimed_at_utc": utc_now(),
        "request": dict(request),
        "request_sha256": identity,
        "attempt_claim_sha256": attempt_claim_sha256,
        "config_sha256": config_sha256,
        "retry_allowed": False,
    }
    record["claim_identity_sha256"] = json_sha256(record)
    path = claim_dir / f"{call_index:02d}-{call_id}.claim.json"
    write_json_exclusive(path, record)
    claim_sha = sha256_file(path)
    row = ledger.transition(
        call_id,
        "CLAIMED",
        {
            "call_index": call_index,
            "call_claim_path": str(path.resolve()),
            "call_claim_sha256": claim_sha,
            "request_sha256": identity,
        },
    )
    return {
        **record,
        "path": str(path.resolve()),
        "sha256": claim_sha,
        "ledger_row_sha256": row["ledger_row_sha256"],
    }


def _validate_checkpoint_set(
    result: Mapping[str, Any], contract: LoadedContract
) -> list[dict[str, Any]]:
    checkpoints = result.get("checkpoints")
    if not isinstance(checkpoints, list) or len(checkpoints) != 3:
        raise ArtifactValidationError("reference did not export exactly three checkpoints")
    ordered = sorted(checkpoints, key=lambda row: row["completed_scheduler_transitions"])
    for index, artifact in enumerate(ordered):
        if (
            artifact.get("completed_scheduler_transitions")
            != CHECKPOINT_COMPLETED_TRANSITIONS[index]
        ):
            raise ArtifactValidationError("reference checkpoint transition mapping changed")
        if artifact.get("cumulative_transformer_nfe") != CHECKPOINT_CUMULATIVE_NFE[index]:
            raise ArtifactValidationError("reference checkpoint NFE mapping changed")
        if artifact.get("checkpoint_fraction") != CHECKPOINT_FRACTIONS[index]:
            raise ArtifactValidationError("reference checkpoint fraction mapping changed")
        path = Path(artifact["path"]).resolve(strict=True)
        if sha256_file(path) != artifact.get("sha256"):
            raise ArtifactValidationError("reference checkpoint artifact hash changed")
        metadata_path = Path(artifact["state_metadata_path"]).resolve(strict=True)
        if sha256_file(metadata_path) != artifact.get("state_metadata_sha256"):
            raise ArtifactValidationError("reference checkpoint metadata hash changed")
        metadata = load_json_object(metadata_path)
        if metadata.get("config_sha256") != contract.sha256:
            raise ArtifactValidationError("checkpoint metadata configuration changed")
    return ordered


def _build_child_request(
    *,
    call_id: str,
    parent_pid: int,
    factory_reference: str,
    engine_context: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    output_path: Path,
    result_path: Path,
    reference_request: Mapping[str, Any],
    config_sha256: str,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "format": RESUME_CHILD_REQUEST_FORMAT,
        "request_id": call_id,
        "parent_pid": parent_pid,
        "engine_factory": factory_reference,
        "engine_context": dict(engine_context),
        "engine_context_sha256": json_sha256(dict(engine_context)),
        "checkpoint_path": checkpoint["path"],
        "checkpoint_sha256": checkpoint["sha256"],
        "checkpoint_state_metadata_sha256": checkpoint["state_metadata_sha256"],
        "output_path": str(output_path.resolve()),
        "result_path": str(result_path.resolve()),
        "reference_request": dict(reference_request),
        "config_sha256": config_sha256,
    }
    request["request_identity_sha256"] = json_sha256(request)
    return request


def _validate_child_result(
    result_path: Path,
    *,
    request_path: Path,
    request: Mapping[str, Any],
    prior_child_pids: set[int],
) -> dict[str, Any]:
    result = load_json_object(result_path)
    if result.get("format") != RESUME_CHILD_RESULT_FORMAT or result.get("status") != "PASS":
        raise ArtifactValidationError("resume child result format/status is invalid")
    claimed = result.get("result_identity_sha256")
    unhashed = dict(result)
    unhashed.pop("result_identity_sha256", None)
    if claimed != json_sha256(unhashed):
        raise ArtifactValidationError("resume child result identity hash changed")
    if result.get("request_path") != str(request_path.resolve()):
        raise ArtifactValidationError("resume child result request path changed")
    if result.get("request_sha256") != sha256_file(request_path):
        raise ArtifactValidationError("resume child request artifact changed")
    if result.get("request_identity_sha256") != request["request_identity_sha256"]:
        raise ArtifactValidationError("resume child request identity changed")
    child_pid = result.get("child_pid")
    if (
        isinstance(child_pid, bool)
        or not isinstance(child_pid, int)
        or child_pid <= 0
        or child_pid == os.getpid()
        or child_pid in prior_child_pids
    ):
        raise ArtifactValidationError("resume child PID is not a fresh separate process")
    engine_result = validate_engine_result(result["engine_result"], mode="RESUME")
    if engine_result.get("pid") != child_pid:
        raise ArtifactValidationError("resume engine PID differs from child PID")
    return {**result, "engine_result": engine_result}


ChildLauncher = Callable[[Path, float, Path], subprocess.CompletedProcess[str]]


def launch_resume_child(
    request_path: Path,
    timeout_seconds: float,
    repository_root: Path,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise TimeoutError("ACE GPU-time budget elapsed before resume child")
    source_root = repository_root / "src"
    environment = dict(os.environ)
    prefixes = [str(source_root), os.environ.get("ACE_STEP_V1_SOURCE_DIR", "")]
    existing = environment.get("PYTHONPATH")
    if existing:
        prefixes.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(item for item in prefixes if item)
    return subprocess.run(
        [sys.executable, "-B", "-m", "state_capture.ace_child", "--request", str(request_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        cwd=repository_root,
        env=environment,
    )


def validate_outer_timeout_boundary(
    *,
    repository_root: Path,
    config_path: Path,
    authorization_path: Path,
    execute_phrase: str,
    parent_pid: int | None = None,
) -> dict[str, Any]:
    """Require the frozen GNU-timeout wrapper around all production execution."""

    wrapper = repository_root / "scripts/run_ace_state_preflight_v2_with_timeout.py"
    if os.environ.get("ACE_STATE_PREFLIGHT_WRAPPER_SHA256") != sha256_file(wrapper):
        raise ArtifactValidationError("outer timeout wrapper hash evidence is absent")
    observed_parent = os.getppid() if parent_pid is None else parent_pid
    executable = Path(f"/proc/{observed_parent}/exe").resolve(strict=True)
    if executable != Path("/usr/bin/timeout"):
        raise ArtifactValidationError("production runner parent is not /usr/bin/timeout")
    raw = Path(f"/proc/{observed_parent}/cmdline").read_bytes()
    argv = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    required_fragments = {
        "-k",
        f"{OUTER_KILL_GRACE_SECONDS}s",
        f"{OUTER_SOFT_TIMEOUT_SECONDS}s",
        str(config_path.resolve(strict=True)),
        str(authorization_path.resolve(strict=True)),
        execute_phrase,
    }
    if not required_fragments.issubset(argv):
        raise ArtifactValidationError("outer timeout argv does not bind the frozen execution")
    return {
        "parent_pid": observed_parent,
        "parent_executable": str(executable),
        "parent_argv": argv,
        "wrapper_path": str(wrapper.resolve()),
        "wrapper_sha256": sha256_file(wrapper),
        "soft_timeout_seconds": OUTER_SOFT_TIMEOUT_SECONDS,
        "kill_grace_seconds": OUTER_KILL_GRACE_SECONDS,
        "hard_process_lifetime_seconds": (
            OUTER_SOFT_TIMEOUT_SECONDS + OUTER_KILL_GRACE_SECONDS
        ),
        "gpu_seconds_cap": MAX_GPU_SECONDS,
    }


def execute_authorized_preflight(
    *,
    config_path: str | Path,
    authorization_path: str | Path,
    execute_phrase: str,
    repository_root: str | Path,
    placement_context: Callable[[LoadedContract, Authorization], Any] = production_placement,
    child_launcher: ChildLauncher = launch_resume_child,
    engine_factory_override: Callable[[Mapping[str, Any]], AceStateEngine] | None = None,
    factory_reference_override: str | None = None,
    require_outer_boundary: bool = True,
    git_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Consume and complete the only attempt, terminal PASS or terminal FAIL."""

    root = Path(repository_root).resolve(strict=True)
    contract = validate_static_config(config_path, repository_root=root)
    if execute_phrase != EXECUTE_PHRASE:
        raise ArtifactValidationError("exact one-attempt execute phrase is absent")
    authorization = validate_external_authorization(
        authorization_path,
        contract=contract,
        repository_root=root,
        git_evidence=git_evidence,
    )
    boundary: Mapping[str, Any]
    if require_outer_boundary:
        boundary = validate_outer_timeout_boundary(
            repository_root=root,
            config_path=Path(config_path),
            authorization_path=Path(authorization_path),
            execute_phrase=execute_phrase,
        )
    else:
        boundary = {"test_only_boundary_bypass": True}
    frozen_package_hashes = package_hashes(root)
    if authorization.raw["package_sha256"] != frozen_package_hashes:
        raise ArtifactValidationError("authorization package hashes differ from live files")

    run_control = contract.raw["run"]
    attempt_store = OneShotAttemptStore(
        run_control["claim_root"],
        claim_filename=run_control["attempt_claim_filename"],
        repository_root=root,
    )
    consumed = attempt_store.consume(
        authorization=authorization,
        contract=contract,
        package_sha256=frozen_package_hashes,
    )
    attempt_claim_sha = consumed["sha256"]

    run_dir: Path | None = None
    ledger: HashChainedLedger | None = None
    heartbeat: Heartbeat | None = None
    engine: AceStateEngine | None = None
    call_results: list[dict[str, Any]] = []
    completed_calls = 0
    failed_calls = 0
    call_started_count = 0
    lease_started: float | None = None
    try:
        run_root = safe_external_path(
            run_control["run_root"], repository_root=root, name="run_root"
        )
        run_root.mkdir(parents=True, exist_ok=True)
        run_dir = run_root / RUN_ID
        run_dir.mkdir(parents=False, exist_ok=False)
        claim_dir = run_dir / "call-claims"
        request_dir = run_dir / "resume-requests"
        child_result_dir = run_dir / "resume-results"
        audio_dir = run_dir / "audio"
        for directory in (claim_dir, request_dir, child_result_dir, audio_dir):
            directory.mkdir(parents=False, exist_ok=False)
        ledger = HashChainedLedger(run_dir / "ledger.jsonl")

        manifest = {
            "schema_version": 1,
            "scope": contract.raw["scope"],
            "run_id": RUN_ID,
            "attempt_id": ATTEMPT_ID,
            "started_at_utc": utc_now(),
            "git_commit": authorization.git_commit,
            "config_path": str(contract.path),
            "config_sha256": contract.sha256,
            "authorization_path": str(authorization.path),
            "authorization_sha256": authorization.sha256,
            "attempt_claim_path": consumed["path"],
            "attempt_claim_sha256": attempt_claim_sha,
            "package_sha256": frozen_package_hashes,
            "caps": dict(contract.raw["caps"]),
            "checkpoint_contract": dict(contract.raw["checkpoint_contract"]),
            "equivalence": dict(contract.raw["equivalence"]),
            "reference_request": dict(contract.raw["proposed_reference_request"]),
            "scientific_boundary": dict(contract.raw["scientific_boundary"]),
            "placement": {
                "node": authorization.node,
                "physical_gpu_id": authorization.physical_gpu_id,
                "logical_gpu_id": 0,
                "tensor_parallel_width": 1,
                "replica_count": 1,
                "placement_justification": authorization.raw["placement"][
                    "placement_justification"
                ],
                "nonpreemption_policy": contract.raw["placement"]["nonpreemption_policy"],
            },
            "outer_timeout_boundary": dict(boundary),
            "planned_call_ids": ["reference", "resume-25", "resume-50", "resume-75"],
            "state_queue_access": "FORBIDDEN_AND_NOT_PERFORMED",
        }
        write_json_exclusive(run_dir / "manifest.json", manifest)

        with placement_context(contract, authorization) as placement_bundle:
            _configured, probe, initial_observation = placement_bundle
            lease_started = time.monotonic()
            write_json_exclusive(run_dir / "initial-placement.json", initial_observation)
            heartbeat = Heartbeat(
                run_dir / "heartbeat.json",
                base={
                    "schema_version": 1,
                    "run_id": RUN_ID,
                    "attempt_id": ATTEMPT_ID,
                    "node": authorization.node,
                    "physical_gpu_id": authorization.physical_gpu_id,
                    "logical_gpu_id": 0,
                    "pid": os.getpid(),
                    "git_commit": authorization.git_commit,
                    "config_sha256": contract.sha256,
                    "attempt_claim_sha256": attempt_claim_sha,
                },
                interval_seconds=float(run_control["heartbeat_interval_seconds"]),
            ).start()

            engine_context = build_engine_context(
                contract=contract,
                repository_root=root,
                run_dir=run_dir,
                attempt_claim_path=Path(consumed["path"]),
            )
            factory_reference = factory_reference_override or contract.raw["engine"][
                "production_factory"
            ]
            factory = engine_factory_override or resolve_engine_factory(factory_reference)
            engine = factory(engine_context)

            reference_request = dict(contract.raw["proposed_reference_request"])
            reference_claim_request = {
                "kind": "UNINTERRUPTED_REFERENCE_WITH_THREE_EXPORTS",
                "reference_request": reference_request,
                "output_relative_path": "audio/reference.wav",
                "checkpoint_fractions": list(CHECKPOINT_FRACTIONS),
            }
            reference_claim = _write_call_claim(
                claim_dir=claim_dir,
                ledger=ledger,
                call_id="reference",
                call_index=0,
                request=reference_claim_request,
                attempt_claim_sha256=attempt_claim_sha,
                config_sha256=contract.sha256,
            )
            ledger.transition(
                "reference",
                "CALL_STARTED",
                {"call_claim_sha256": reference_claim["sha256"]},
            )
            call_started_count += 1
            heartbeat.update(
                current_call_id="reference",
                last_ledger_sha256=ledger.tail_sha256(),
                state="RUNNING",
            )
            try:
                reference = validate_engine_result(
                    engine.run_reference(
                        request=reference_request,
                        output_path=audio_dir / "reference.wav",
                        state_dir=run_dir / "state",
                    ),
                    mode="REFERENCE",
                )
                if reference["actual_nfe"] != 45:
                    raise ArtifactValidationError("reference actual NFE is not exactly 45")
                checkpoints = _validate_checkpoint_set(reference, contract)
                reference_sanity = basic_audio_sanity(
                    reference["output_path"],
                    requested_duration_seconds=30.0,
                )
                reference_provenance = write_adjacent_provenance(
                    reference["output_path"],
                    label="synthetic_model_output",
                    run_id=RUN_ID,
                    creating_call_id="reference",
                    model_revision=contract.raw["engine"]["source_commit"],
                    source_ids={
                        "attempt_claim_sha256": attempt_claim_sha,
                        "config_sha256": contract.sha256,
                        "request_sha256": reference_claim["request_sha256"],
                    },
                    extra={"terminal_latent_sha256": reference["terminal_latent_sha256"]},
                )
                checkpoint_provenance = []
                for checkpoint in checkpoints:
                    checkpoint_provenance.append(
                        write_adjacent_provenance(
                            checkpoint["path"],
                            label="latent_checkpoint",
                            run_id=RUN_ID,
                            creating_call_id="reference",
                            model_revision=contract.raw["engine"]["source_commit"],
                            source_ids={
                                "attempt_claim_sha256": attempt_claim_sha,
                                "config_sha256": contract.sha256,
                                "state_metadata_sha256": checkpoint[
                                    "state_metadata_sha256"
                                ],
                            },
                            extra={
                                "checkpoint_fraction": checkpoint["checkpoint_fraction"],
                                "cumulative_transformer_nfe": checkpoint[
                                    "cumulative_transformer_nfe"
                                ],
                            },
                        )
                    )
                reference_record = {
                    **reference,
                    "audio_sanity": reference_sanity,
                    "provenance": reference_provenance,
                    "checkpoint_provenance": checkpoint_provenance,
                }
                call_results.append(reference_record)
                completed_calls += 1
                ledger.transition(
                    "reference",
                    "SUCCEEDED",
                    {
                        "output_sha256": reference["output_sha256"],
                        "actual_nfe": reference["actual_nfe"],
                        "gpu_seconds": reference["gpu_seconds"],
                        "checkpoint_sha256": [row["sha256"] for row in checkpoints],
                    },
                )
            except Exception as exc:
                failed_calls += 1
                ledger.transition(
                    "reference",
                    "FAILED",
                    {"error_type": type(exc).__name__, "error": str(exc)},
                )
                raise
            finally:
                engine.close()
                engine = None
            measurements = aggregate_gpu_measurements(call_results)
            heartbeat.update(
                current_call_id=None,
                completed_calls=completed_calls,
                failed_calls=failed_calls,
                cumulative_gpu_seconds=measurements["cumulative_gpu_seconds"],
                peak_allocated_bytes=measurements["peak_allocated_bytes"],
                peak_reserved_bytes=measurements["peak_reserved_bytes"],
                last_ledger_sha256=ledger.tail_sha256(),
                state="RUNNING",
            )

            child_pids: set[int] = set()
            equivalence_rows: list[dict[str, Any]] = []
            for checkpoint_index, checkpoint in enumerate(checkpoints):
                call_index = checkpoint_index + 1
                fraction_label = ("25", "50", "75")[checkpoint_index]
                call_id = f"resume-{fraction_label}"
                if call_started_count >= MAX_MODEL_CALLS:
                    raise ArtifactValidationError("four-call hard cap reached before resume")
                elapsed = time.monotonic() - lease_started
                remaining = MAX_GPU_SECONDS - elapsed
                if remaining <= 0:
                    raise TimeoutError("600-GPU-second cap reached before resume claim")
                observation = probe.require_safe(
                    minimum_free_vram_bytes=int(
                        contract.raw["placement"]["minimum_free_vram_bytes"]
                    ),
                    allowed_pids={os.getpid()},
                    # Initial placement was idle.  While the same exclusive
                    # lease remains held, utilization may reflect only our
                    # just-finished call; neighbor PIDs and headroom remain
                    # hard gates before every child.
                    maximum_utilization_percent=None,
                )
                write_json_exclusive(
                    run_dir / f"pre-{call_id}-placement.json", _observation_dict(observation)
                )
                output_path = audio_dir / f"{call_id}.wav"
                result_path = child_result_dir / f"{call_id}.json"
                child_request = _build_child_request(
                    call_id=call_id,
                    parent_pid=os.getpid(),
                    factory_reference=factory_reference,
                    engine_context=engine_context,
                    checkpoint=checkpoint,
                    output_path=output_path,
                    result_path=result_path,
                    reference_request=reference_request,
                    config_sha256=contract.sha256,
                )
                request_path = request_dir / f"{call_id}.json"
                write_json_exclusive(request_path, child_request)
                call_claim = _write_call_claim(
                    claim_dir=claim_dir,
                    ledger=ledger,
                    call_id=call_id,
                    call_index=call_index,
                    request=child_request,
                    attempt_claim_sha256=attempt_claim_sha,
                    config_sha256=contract.sha256,
                )
                ledger.transition(
                    call_id,
                    "CALL_STARTED",
                    {
                        "call_claim_sha256": call_claim["sha256"],
                        "child_request_sha256": sha256_file(request_path),
                    },
                )
                call_started_count += 1
                heartbeat.update(
                    current_call_id=call_id,
                    last_ledger_sha256=ledger.tail_sha256(),
                    state="RUNNING",
                )
                try:
                    process = child_launcher(request_path, remaining, root)
                    child = _validate_child_result(
                        result_path,
                        request_path=request_path,
                        request=child_request,
                        prior_child_pids=child_pids,
                    )
                    child_pids.add(child["child_pid"])
                    resumed = child["engine_result"]
                    expected_nfe = 45 - CHECKPOINT_CUMULATIVE_NFE[checkpoint_index]
                    if resumed["actual_nfe"] != expected_nfe:
                        raise ArtifactValidationError(
                            f"{call_id} actual NFE {resumed['actual_nfe']} != {expected_nfe}"
                        )
                    if resumed["terminal_latent_sha256"] != reference["terminal_latent_sha256"]:
                        raise ArtifactValidationError(f"{call_id} terminal latent hash differs")
                    sanity = basic_audio_sanity(
                        resumed["output_path"], requested_duration_seconds=30.0
                    )
                    provenance = write_adjacent_provenance(
                        resumed["output_path"],
                        label="synthetic_model_output",
                        run_id=RUN_ID,
                        creating_call_id=call_id,
                        model_revision=contract.raw["engine"]["source_commit"],
                        source_ids={
                            "attempt_claim_sha256": attempt_claim_sha,
                            "config_sha256": contract.sha256,
                            "checkpoint_sha256": checkpoint["sha256"],
                            "child_request_sha256": sha256_file(request_path),
                        },
                        extra={
                            "child_pid": child["child_pid"],
                            "terminal_latent_sha256": resumed["terminal_latent_sha256"],
                        },
                    )
                    tolerance = contract.raw["equivalence"]
                    equivalence = compare_audio_equivalence(
                        reference["output_path"],
                        resumed["output_path"],
                        max_absolute_error=float(tolerance["max_absolute_error"]),
                        minimum_snr_db=float(tolerance["minimum_snr_db"]),
                    )
                    equivalence_rows.append(
                        {
                            **equivalence,
                            "checkpoint_fraction": CHECKPOINT_FRACTIONS[checkpoint_index],
                            "completed_scheduler_transitions": checkpoint[
                                "completed_scheduler_transitions"
                            ],
                            "cumulative_transformer_nfe": checkpoint[
                                "cumulative_transformer_nfe"
                            ],
                            "child_pid": child["child_pid"],
                        }
                    )
                    call_results.append(
                        {
                            **resumed,
                            "child_process": {
                                "pid": child["child_pid"],
                                "os_parent_pid": child["os_parent_pid"],
                                "request_path": str(request_path.resolve()),
                                "request_sha256": sha256_file(request_path),
                                "result_path": str(result_path.resolve()),
                                "result_sha256": sha256_file(result_path),
                                "returncode": process.returncode,
                            },
                            "audio_sanity": sanity,
                            "provenance": provenance,
                            "equivalence": equivalence,
                        }
                    )
                    completed_calls += 1
                    ledger.transition(
                        call_id,
                        "SUCCEEDED",
                        {
                            "output_sha256": resumed["output_sha256"],
                            "actual_nfe": resumed["actual_nfe"],
                            "gpu_seconds": resumed["gpu_seconds"],
                            "child_pid": child["child_pid"],
                            "equivalence_status": equivalence["status"],
                        },
                    )
                except Exception as exc:
                    failed_calls += 1
                    ledger.transition(
                        call_id,
                        "FAILED",
                        {"error_type": type(exc).__name__, "error": str(exc)},
                    )
                    raise
                measurements = aggregate_gpu_measurements(call_results)
                if measurements["cumulative_gpu_seconds"] > MAX_GPU_SECONDS:
                    raise TimeoutError("measured GPU seconds exceeded the hard cap")
                if time.monotonic() - lease_started > MAX_GPU_SECONDS:
                    raise TimeoutError("exclusive GPU occupancy exceeded the hard cap")
                heartbeat.update(
                    current_call_id=None,
                    completed_calls=completed_calls,
                    failed_calls=failed_calls,
                    cumulative_gpu_seconds=measurements["cumulative_gpu_seconds"],
                    peak_allocated_bytes=measurements["peak_allocated_bytes"],
                    peak_reserved_bytes=measurements["peak_reserved_bytes"],
                    last_ledger_sha256=ledger.tail_sha256(),
                    state="RUNNING",
                )

            if call_started_count != 4 or completed_calls != 4 or failed_calls != 0:
                raise ArtifactValidationError(
                    "completed attempt did not contain exactly four successes"
                )
            if len(child_pids) != 3 or os.getpid() in child_pids:
                raise ArtifactValidationError(
                    "three distinct resume child processes were not observed"
                )
            if len(equivalence_rows) != 3 or any(
                row["status"] != "PASS" for row in equivalence_rows
            ):
                raise ArtifactValidationError("all three checkpoint equivalence rows did not pass")
            measurements = aggregate_gpu_measurements(call_results)
            occupancy_seconds = time.monotonic() - lease_started
            if measurements["cumulative_gpu_seconds"] > MAX_GPU_SECONDS:
                raise TimeoutError("measured GPU seconds exceeded 600 at terminal boundary")
            if occupancy_seconds > MAX_GPU_SECONDS:
                raise TimeoutError("exclusive GPU occupancy exceeded 600 seconds")
            for row in call_results:
                validate_adjacent_provenance(row["output_path"])
            ledger_rows = validate_ledger(ledger.path)
            result = {
                "schema_version": 1,
                "status": "PASS",
                "capability_status": "PASS",
                "scientific_claim": "TECHNICAL_CAPABILITY_ONLY",
                "run_id": RUN_ID,
                "attempt_id": ATTEMPT_ID,
                "finished_at_utc": utc_now(),
                "model_call_count": call_started_count,
                "generated_output_count": len(call_results),
                "checkpoint_export_count": len(checkpoints),
                "resume_child_process_count": len(child_pids),
                "resume_child_pids": sorted(child_pids),
                "reference_pid": os.getpid(),
                "call_results": call_results,
                "equivalence": equivalence_rows,
                "gpu_measurements": {
                    **measurements,
                    "exclusive_gpu_occupancy_seconds": occupancy_seconds,
                    "cap_seconds": MAX_GPU_SECONDS,
                },
                "ledger_path": str(ledger.path.resolve()),
                "ledger_sha256": sha256_file(ledger.path),
                "ledger_tail_sha256": ledger_rows[-1]["ledger_row_sha256"],
                "state_queue_accessed": False,
                "retry_allowed": False,
                "engine_limitations": inspect_production_capability(contract)[
                    "engine_limitations"
                ],
            }
            write_json_exclusive(run_dir / "result.json", result)
            heartbeat.close(final_state="COMPLETE")
            heartbeat = None

        terminal = attempt_store.write_terminal(
            status="PASS",
            claim_sha256=attempt_claim_sha,
            ledger_path=ledger.path,
            payload={
                "run_result_path": str((run_dir / "result.json").resolve()),
                "run_result_sha256": sha256_file(run_dir / "result.json"),
                "model_call_count": call_started_count,
                "generated_output_count": len(call_results),
                "gpu_measurements": result["gpu_measurements"],
                "capability_status": "PASS",
                "scientific_claim": "TECHNICAL_CAPABILITY_ONLY",
            },
        )
        return terminal
    except Exception as exc:
        if engine is not None:
            with suppress(Exception):
                engine.close()
        if heartbeat is not None:
            with suppress(Exception):
                heartbeat.update(
                    current_call_id=None,
                    completed_calls=completed_calls,
                    failed_calls=failed_calls,
                    last_ledger_sha256=ledger.tail_sha256() if ledger is not None else "0" * 64,
                    state="FAILED",
                )
                heartbeat.close(final_state="FAILED")
        failure_payload = {
            "error_type": type(exc).__name__,
            "error": str(exc),
            "model_call_count": call_started_count,
            "generated_output_count": len(call_results),
            "completed_calls": completed_calls,
            "failed_calls": failed_calls,
            "retry_allowed": False,
            "state_queue_accessed": False,
        }
        if run_dir is not None:
            failure_path = run_dir / "failure.json"
            if not failure_path.exists():
                with suppress(Exception):
                    write_json_exclusive(failure_path, failure_payload)
                    failure_payload["failure_path"] = str(failure_path.resolve())
                    failure_payload["failure_sha256"] = sha256_file(failure_path)
        try:
            terminal = attempt_store.write_terminal(
                status="FAIL",
                claim_sha256=attempt_claim_sha,
                ledger_path=ledger.path if ledger is not None else None,
                payload=failure_payload,
            )
        except Exception as terminal_error:
            raise AuthorizedAttemptFailed(
                f"authorized attempt failed and terminalization also failed: {terminal_error}",
                {
                    "status": "FAIL",
                    "attempt_claim_path": consumed["path"],
                    "attempt_claim_sha256": attempt_claim_sha,
                    "retry_allowed": False,
                    "original_error": failure_payload,
                    "terminalization_error": str(terminal_error),
                },
            ) from exc
        raise AuthorizedAttemptFailed(str(exc), terminal) from exc

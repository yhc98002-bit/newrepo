"""Strict, side-effect-free validation for benchmark-core execution config."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_duration_policy import duration_within_tolerance
from backbones.license_gate import validate_access_receipt, validate_core_authorization
from backbones.sao_mini_smoke import (
    SaoMiniSmokeEvidenceError,
    validate_sao_mini_smoke_evidence,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
READY = "READY"
BLOCKED_ON_LICENSE = "BLOCKED_ON_LICENSE"
BLOCKED_ON_ENGINEERING_FAILURE = "BLOCKED_ON_ENGINEERING_FAILURE"
NON_EXECUTABLE_QUEUE_STATUSES = frozenset({BLOCKED_ON_LICENSE, BLOCKED_ON_ENGINEERING_FAILURE})
QUEUE_STATUSES = frozenset({READY, *NON_EXECUTABLE_QUEUE_STATUSES})
SA3_MODEL_ID = "stabilityai/stable-audio-3-medium-base"
SAO_MODEL_ID = "stabilityai/stable-audio-open-1.0"
ACE_MODEL_ID = "ACE-Step/ACE-Step-v1-3.5B"
REQUIRED_MODEL_IDS = frozenset({SA3_MODEL_ID, SAO_MODEL_ID, ACE_MODEL_ID})
PHASE_B_TERMINAL_PATH = Path("provenance/b2/build_status_terminal_v2.json")
PHASE_B_TERMINAL_STATUS = "TERMINAL"
MAX_DURATION_TOLERANCE_SECONDS = 0.25
REQUIRED_PROMPT_HASHES = frozenset(
    {
        "vocal_instrumental.json",
        "tempo.json",
        "integrity.json",
        "structure_exploratory.json",
        "seed_registry.json",
    }
)
STATE_PREVIEW_SOURCE = "ONLY_THE_SAME_UNITS_ROOT_LOCAL_PRE_ACTION_DECODED_PREVIEW"
STATE_CAPTURE_MODE = "SEPARATE_LEDGERED_STATE_CAPTURE_QUEUE"
STATE_CORE_LAUNCH_STATUS = "CLOSED_AT_ORDINARY_CORE_LAUNCH"
RESTART_POOL_LABEL = "RESTART_POOL_SHARED_AT_PROMPT_LEVEL"


class CoreConfigurationError(ValueError):
    """Raised when launch configuration is incomplete or internally unsafe."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoreConfigurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(path: Path) -> dict[str, Any]:
    """Read a strict JSON object, rejecting duplicates and non-finite values."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                CoreConfigurationError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoreConfigurationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CoreConfigurationError(f"JSON root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    if not isinstance(value, dict):
        raise CoreConfigurationError(f"{key} must be an object")
    return value


def _string(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CoreConfigurationError(f"{key} must be a non-empty string")
    return value


def _sha256(record: dict[str, Any], key: str) -> str:
    value = _string(record, key)
    if SHA256_RE.fullmatch(value) is None:
        raise CoreConfigurationError(f"{key} must be a lowercase SHA-256")
    return value


def _positive_number(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreConfigurationError(f"{key} must be a positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise CoreConfigurationError(f"{key} must be a positive finite number")
    return result


def _positive_int(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CoreConfigurationError(f"{key} must be a positive integer")
    return value


def _nonnegative_number(record: dict[str, Any], key: str, *, default: float | None = None) -> float:
    value = record.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreConfigurationError(f"{key} must be a non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise CoreConfigurationError(f"{key} must be a non-negative finite number")
    return result


def _resolve_repo_path(repo_root: Path, value: str, *, key: str) -> Path:
    candidate = (
        (repo_root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    )
    if not candidate.is_file():
        raise CoreConfigurationError(f"{key} is not a file: {candidate}")
    return candidate


@dataclass(frozen=True)
class PlacementConfig:
    node: str
    physical_gpu_id: int
    logical_gpu_id: int
    tp_width: int
    replica_count: int
    minimum_free_vram_bytes: int
    post_load_reserve_bytes: int
    lock_root: Path
    required_gpu_name_substring: str
    maximum_idle_utilization_percent: int


@dataclass(frozen=True)
class BudgetConfig:
    scheduled_calls: int
    cold_plus_first_seconds: float
    resident_unit_seconds: float
    gpu_seconds_cap: float
    load_reservation_seconds: float

    def reservation_for_call(self, call_index: int) -> float:
        if not 0 <= call_index < self.scheduled_calls:
            raise IndexError("call index is outside the frozen schedule")
        return self.resident_unit_seconds if call_index == 0 else 2 * self.resident_unit_seconds


@dataclass(frozen=True)
class ModelExecutionConfig:
    model_id: str
    slug: str
    queue_status: str
    adapter_config_path: Path | None
    adapter_config_sha256: str | None
    placement: PlacementConfig | None
    budget: BudgetConfig | None
    state_capture_status: str
    expected_sample_rate: int | None
    expected_channels: int | None
    duration_tolerance_seconds: float | None = 0.0
    sao_runtime: SaoRuntimeBinding | None = None


@dataclass(frozen=True)
class SaoRuntimeBinding:
    snapshot_dir: Path
    access_receipt_path: Path
    access_receipt_sha256: str
    mini_smoke_result_path: Path
    mini_smoke_result_sha256: str
    core_authorization_path: Path
    core_authorization_sha256: str


@dataclass(frozen=True)
class PhaseBTerminalBinding:
    path: Path
    sha256: str
    status: str
    model_queue_statuses: dict[str, str]
    ready_costs: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class PriorCompletionBinding:
    model_id: str
    path: Path
    sha256: str
    run_dir: Path
    generation_queue_path: Path
    generation_queue_sha256: str


@dataclass(frozen=True)
class StateCapturePolicy:
    axes: tuple[str, ...]
    conditions: tuple[str, ...]
    checkpoint_fractions: tuple[float, ...]
    eligible_model_ids: tuple[str, ...]
    eligible_prompt_ids: tuple[str, ...]
    initial_root_indices: tuple[int, ...]
    doubling_root_indices: tuple[int, ...]
    preview_source: str
    capture_mode: str
    restart_outcome_label: str
    ordinary_core_launch_status: str


@dataclass(frozen=True)
class CoreExecutionConfig:
    source_path: Path
    source_sha256: str
    repo_root: Path
    run_root: Path
    max_duration_seconds: float
    shard_size: int
    heartbeat_interval_seconds: float
    heartbeat_stale_after_seconds: float
    authorized_model_ids: tuple[str, ...]
    models: tuple[ModelExecutionConfig, ...]
    phase_b_terminal: PhaseBTerminalBinding
    prior_model_completions: dict[str, PriorCompletionBinding]
    state_capture: StateCapturePolicy
    raw: dict[str, Any]


def _validate_placement(value: dict[str, Any]) -> PlacementConfig:
    node = _string(value, "node")
    if node not in {"an12", "an29"}:
        raise CoreConfigurationError("placement.node must be an12 or an29")
    physical = value.get("physical_gpu_id")
    logical = value.get("logical_gpu_id")
    if isinstance(physical, bool) or not isinstance(physical, int) or not 0 <= physical <= 7:
        raise CoreConfigurationError("physical_gpu_id must be an integer in 0..7")
    if logical != 0:
        raise CoreConfigurationError("logical_gpu_id must equal 0 for a one-device worker")
    if value.get("tp_width") != 1 or value.get("replica_count") != 1:
        raise CoreConfigurationError("benchmark workers require TP1 and one replica")
    minimum = _positive_int(value, "minimum_free_vram_bytes")
    reserve = _positive_int(value, "post_load_reserve_bytes")
    lock_root = Path(_string(value, "lock_root"))
    if not lock_root.is_absolute():
        raise CoreConfigurationError("placement.lock_root must be absolute")
    required_name = _string(value, "required_gpu_name_substring")
    if required_name != "A800":
        raise CoreConfigurationError("required_gpu_name_substring must equal A800")
    idle_utilization = value.get("maximum_idle_utilization_percent")
    if (
        isinstance(idle_utilization, bool)
        or not isinstance(idle_utilization, int)
        or not 0 <= idle_utilization <= 5
    ):
        raise CoreConfigurationError("maximum idle GPU utilization must be an integer in 0..5")
    return PlacementConfig(
        node=node,
        physical_gpu_id=physical,
        logical_gpu_id=logical,
        tp_width=1,
        replica_count=1,
        minimum_free_vram_bytes=minimum,
        post_load_reserve_bytes=reserve,
        lock_root=lock_root,
        required_gpu_name_substring=required_name,
        maximum_idle_utilization_percent=idle_utilization,
    )


def _validate_budget(value: dict[str, Any]) -> BudgetConfig:
    scheduled = _positive_int(value, "scheduled_calls")
    if scheduled > 1_536:
        raise CoreConfigurationError("scheduled_calls exceeds the per-model 1,536-call cap")
    cold_plus_first = _positive_number(value, "cold_plus_first_seconds")
    resident_unit = _positive_number(value, "resident_unit_seconds")
    if cold_plus_first < resident_unit:
        raise CoreConfigurationError(
            "cold_plus_first_seconds must be at least resident_unit_seconds"
        )
    cap = _positive_number(value, "gpu_seconds_cap")
    expected_cap = cold_plus_first + max(scheduled - 1, 0) * (2 * resident_unit)
    if not math.isclose(cap, expected_cap, rel_tol=0, abs_tol=1e-9):
        raise CoreConfigurationError("gpu_seconds_cap must equal c_m + max(n_m-1,0) * (2*u_m)")
    return BudgetConfig(
        scheduled_calls=scheduled,
        cold_plus_first_seconds=cold_plus_first,
        resident_unit_seconds=resident_unit,
        gpu_seconds_cap=cap,
        load_reservation_seconds=cold_plus_first - resident_unit,
    )


def _validate_state_capture(
    value: dict[str, Any], statistics_config: dict[str, Any]
) -> StateCapturePolicy:
    axes = value.get("axes")
    conditions = value.get("conditions")
    fractions = value.get("checkpoint_fractions")
    model_ids = value.get("eligible_model_ids")
    for name, candidate in (
        ("axes", axes),
        ("conditions", conditions),
        ("eligible_model_ids", model_ids),
    ):
        if (
            not isinstance(candidate, list)
            or not candidate
            or not all(isinstance(item, str) and item for item in candidate)
        ):
            raise CoreConfigurationError(f"state_capture.{name} must be a non-empty string list")
        if len(set(candidate)) != len(candidate):
            raise CoreConfigurationError(f"state_capture.{name} contains duplicates")
    if not isinstance(fractions, list) or not fractions:
        raise CoreConfigurationError("state_capture.checkpoint_fractions must be non-empty")
    normalized: list[float] = []
    for fraction in fractions:
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
            raise CoreConfigurationError("checkpoint fractions must be numbers")
        number = float(fraction)
        if not math.isfinite(number) or not 0 < number < 1:
            raise CoreConfigurationError("checkpoint fractions must be finite and in (0,1)")
        normalized.append(number)
    if normalized != sorted(set(normalized)):
        raise CoreConfigurationError("checkpoint fractions must be unique and increasing")
    initial_roots = value.get("initial_root_indices")
    doubling_roots = value.get("doubling_root_indices")
    if initial_roots != [0, 1, 2, 3] or doubling_roots != [4, 5, 6, 7]:
        raise CoreConfigurationError("state roots must freeze initial 0..3 and doubling 4..7")
    eligibility = _object(statistics_config, "eligibility")
    selection = _object(eligibility, "prompt_selection")
    axis_prompt_ids = _object(selection, "axis_prompt_ids")
    if set(axis_prompt_ids) != {"vocal_instrumental", "tempo", "integrity"}:
        raise CoreConfigurationError("statistics prompt selection must bind three axes")
    prompt_ids: list[str] = []
    for axis in ("vocal_instrumental", "tempo", "integrity"):
        selected = axis_prompt_ids.get(axis)
        if (
            not isinstance(selected, list)
            or len(selected) != 12
            or not all(isinstance(item, str) and item for item in selected)
        ):
            raise CoreConfigurationError("statistics must freeze 12 prompt IDs per axis")
        prompt_ids.extend(selected)
    if len(set(prompt_ids)) != 36:
        raise CoreConfigurationError("statistics eligibility prompt IDs must be unique")
    if set(axes) != set(axis_prompt_ids):
        raise CoreConfigurationError("state_capture axes drift from statistics prompt selection")
    if conditions != ["BASE"]:
        raise CoreConfigurationError("formal state capture must observe BASE-root prefixes")
    if normalized != [0.25, 0.5, 0.75]:
        raise CoreConfigurationError("formal state checkpoints must equal 25/50/75 percent")
    if eligibility.get("checkpoint_fractions") != normalized:
        raise CoreConfigurationError("state checkpoints drift from statistics config")
    preview_source = _string(value, "preview_source")
    capture_mode = _string(value, "capture_mode")
    restart_label = _string(value, "restart_outcome_label")
    core_status = _string(value, "ordinary_core_launch_status")
    if preview_source != STATE_PREVIEW_SOURCE:
        raise CoreConfigurationError(f"preview_source must equal {STATE_PREVIEW_SOURCE}")
    if capture_mode != STATE_CAPTURE_MODE:
        raise CoreConfigurationError(f"capture_mode must equal {STATE_CAPTURE_MODE}")
    if restart_label != RESTART_POOL_LABEL:
        raise CoreConfigurationError(f"restart_outcome_label must equal {RESTART_POOL_LABEL}")
    if core_status != STATE_CORE_LAUNCH_STATUS:
        raise CoreConfigurationError(
            f"ordinary_core_launch_status must equal {STATE_CORE_LAUNCH_STATUS}"
        )
    state_contract = _object(eligibility, "state_capture_contract")
    if state_contract.get("feature_source") != preview_source:
        raise CoreConfigurationError("state preview source drifts from statistics config")
    if eligibility.get("restart_outcome_label") != restart_label:
        raise CoreConfigurationError("restart outcome label drifts from statistics config")
    return StateCapturePolicy(
        axes=tuple(axes),
        conditions=tuple(conditions),
        checkpoint_fractions=tuple(normalized),
        eligible_model_ids=tuple(model_ids),
        eligible_prompt_ids=tuple(prompt_ids),
        initial_root_indices=tuple(initial_roots),
        doubling_root_indices=tuple(doubling_roots),
        preview_source=preview_source,
        capture_mode=capture_mode,
        restart_outcome_label=restart_label,
        ordinary_core_launch_status=core_status,
    )


def _validate_phase_b_terminal(
    raw: dict[str, Any],
    *,
    repo_root: Path,
    path_override: Path | None,
) -> PhaseBTerminalBinding:
    """Bind the terminal Phase-B receipt and its exact executable model set."""

    binding = _object(raw, "phase_b_terminal")
    declared_path = _string(binding, "path")
    declared_path_object = Path(declared_path)
    if declared_path_object.is_absolute() or ".." in declared_path_object.parts:
        raise CoreConfigurationError("phase_b_terminal.path must be a safe repository path")
    declared_sha = _sha256(binding, "sha256")
    declared_status = _string(binding, "status")
    if declared_status != PHASE_B_TERMINAL_STATUS:
        raise CoreConfigurationError(
            f"phase_b_terminal.status must equal {PHASE_B_TERMINAL_STATUS}"
        )
    receipt_path = (
        path_override.resolve(strict=True)
        if path_override is not None
        else _resolve_repo_path(repo_root, declared_path, key="phase_b_terminal.path")
    )
    if sha256_file(receipt_path) != declared_sha:
        raise CoreConfigurationError("Phase-B terminal receipt hash mismatch")
    receipt = strict_json(receipt_path)
    if receipt.get("schema_version") != 1 or receipt.get("status") != declared_status:
        raise CoreConfigurationError("Phase-B receipt is not schema-v1 TERMINAL")
    records = _object(receipt, "models")
    if set(records) != REQUIRED_MODEL_IDS:
        raise CoreConfigurationError("Phase-B receipt must contain exactly the three backbones")

    statuses: dict[str, str] = {}
    ready_costs: dict[str, tuple[float, float]] = {}
    for model_id in sorted(REQUIRED_MODEL_IDS):
        record = records.get(model_id)
        if not isinstance(record, dict):
            raise CoreConfigurationError(f"Phase-B model record is invalid: {model_id}")
        queue_status = _string(record, "queue_status")
        build_status = _string(record, "build_status")
        statuses[model_id] = queue_status
        if model_id == SA3_MODEL_ID:
            if queue_status != READY or build_status != "MEASURED_READY":
                raise CoreConfigurationError("SA3 Phase-B terminal state must be MEASURED_READY")
        elif model_id == SAO_MODEL_ID:
            if queue_status == BLOCKED_ON_LICENSE:
                if build_status != BLOCKED_ON_LICENSE:
                    raise CoreConfigurationError("blocked stable-audio-open build status drifted")
            elif queue_status == READY:
                if (
                    build_status != "MEASURED_READY"
                    or record.get("mini_smoke_status") != "MEASURED_MINI_SMOKE_PASS"
                    or record.get("state_capability") != "NOT_ATTEMPTED"
                    or record.get("eligibility_scope_expanded") is not False
                ):
                    raise CoreConfigurationError(
                        "SAO READY requires measured smoke and generation-only scope"
                    )
                for key in ("access_receipt_sha256", "mini_smoke_result_sha256"):
                    _sha256(record, key)
            else:
                raise CoreConfigurationError("SAO must be READY or BLOCKED_ON_LICENSE")
        elif queue_status == READY:
            if (
                build_status != "MEASURED_READY"
                or record.get("mini_smoke_status") != "MEASURED_MINI_SMOKE_PASS"
            ):
                raise CoreConfigurationError(
                    "ACE READY requires MEASURED_READY and MEASURED_MINI_SMOKE_PASS"
                )
        elif queue_status == BLOCKED_ON_ENGINEERING_FAILURE:
            if build_status != "FAIL_ESCALATED":
                raise CoreConfigurationError("blocked ACE requires terminal FAIL_ESCALATED")
        else:
            raise CoreConfigurationError("ACE must be READY or BLOCKED_ON_ENGINEERING_FAILURE")

        if queue_status == READY:
            if record.get("cost_status") != "MEASURED":
                raise CoreConfigurationError(f"READY model lacks MEASURED cost: {model_id}")
            cold_plus_first = _positive_number(record, "cold_plus_first_seconds")
            resident_unit = _positive_number(record, "resident_unit_seconds")
            if cold_plus_first < resident_unit:
                raise CoreConfigurationError(
                    f"Phase-B cold-plus-first cost is below resident cost: {model_id}"
                )
            ready_costs[model_id] = (cold_plus_first, resident_unit)

    return PhaseBTerminalBinding(
        path=receipt_path,
        sha256=declared_sha,
        status=declared_status,
        model_queue_statuses=statuses,
        ready_costs=ready_costs,
    )


def _exact_nonnegative_int(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoreConfigurationError(f"{key} must be a non-negative integer")
    return value


def _validate_sao_runtime(
    core: dict[str, Any],
    *,
    repo_root: Path,
    adapter_config_sha256: str,
) -> SaoRuntimeBinding:
    value = _object(core, "sao_runtime")
    required = {
        "snapshot_dir",
        "access_receipt_path",
        "access_receipt_sha256",
        "mini_smoke_result_path",
        "mini_smoke_result_sha256",
        "core_authorization_path",
        "core_authorization_sha256",
    }
    if set(value) != required:
        raise CoreConfigurationError("SAO runtime binding keys are incomplete or unexpected")
    snapshot_dir = Path(_string(value, "snapshot_dir")).resolve()
    if not snapshot_dir.is_dir() or snapshot_dir == Path("/"):
        raise CoreConfigurationError("SAO snapshot_dir is absent or unsafe")
    access_path = _resolve_repo_path(
        repo_root,
        _string(value, "access_receipt_path"),
        key="sao_runtime.access_receipt_path",
    )
    access_sha = _sha256(value, "access_receipt_sha256")
    if sha256_file(access_path) != access_sha:
        raise CoreConfigurationError("SAO access receipt hash mismatch")
    mini_path = _resolve_repo_path(
        repo_root,
        _string(value, "mini_smoke_result_path"),
        key="sao_runtime.mini_smoke_result_path",
    )
    mini_sha = _sha256(value, "mini_smoke_result_sha256")
    if sha256_file(mini_path) != mini_sha:
        raise CoreConfigurationError("SAO mini-smoke result hash mismatch")
    authorization_path = _resolve_repo_path(
        repo_root,
        _string(value, "core_authorization_path"),
        key="sao_runtime.core_authorization_path",
    )
    authorization_sha = _sha256(value, "core_authorization_sha256")
    if sha256_file(authorization_path) != authorization_sha:
        raise CoreConfigurationError("SAO core authorization hash mismatch")
    receipt = validate_access_receipt(
        access_path,
        expected_model_id=SAO_MODEL_ID,
        expected_snapshot_dir=snapshot_dir,
    )
    try:
        validate_sao_mini_smoke_evidence(
            mini_path,
            expected_config_sha256=adapter_config_sha256,
            expected_receipt=receipt,
            expected_snapshot_dir=snapshot_dir,
        )
    except SaoMiniSmokeEvidenceError as exc:
        raise CoreConfigurationError(f"SAO mini-smoke evidence is invalid: {exc}") from exc
    validate_core_authorization(
        authorization_path,
        expected_config_sha256=adapter_config_sha256,
        expected_receipt_sha256=receipt["receipt_sha256"],
        expected_mini_smoke_result_sha256=mini_sha,
    )
    return SaoRuntimeBinding(
        snapshot_dir=snapshot_dir,
        access_receipt_path=access_path,
        access_receipt_sha256=access_sha,
        mini_smoke_result_path=mini_path,
        mini_smoke_result_sha256=mini_sha,
        core_authorization_path=authorization_path,
        core_authorization_sha256=authorization_sha,
    )


def _completion_external_file(
    record: dict[str, Any],
    *,
    path_key: str,
    sha_key: str,
    run_dir: Path,
) -> Path:
    path = Path(_string(record, path_key)).resolve(strict=True)
    try:
        path.relative_to(run_dir)
    except ValueError as exc:
        raise CoreConfigurationError(f"completion {path_key} escapes its immutable run") from exc
    if sha256_file(path) != _sha256(record, sha_key):
        raise CoreConfigurationError(f"completion {path_key} hash mismatch")
    return path


def _validate_prior_completion(
    model_id: str,
    binding: dict[str, Any],
    *,
    repo_root: Path,
) -> PriorCompletionBinding:
    """Verify a project receipt and the immutable external completion evidence it binds."""

    declared_path = _string(binding, "path")
    receipt_path = _resolve_repo_path(repo_root, declared_path, key="prior completion receipt")
    declared_sha = _sha256(binding, "sha256")
    if sha256_file(receipt_path) != declared_sha:
        raise CoreConfigurationError("prior completion receipt hash mismatch")
    receipt = strict_json(receipt_path)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "COMPLETE"
        or receipt.get("model_id") != model_id
    ):
        raise CoreConfigurationError("prior completion receipt identity/status mismatch")
    if _exact_nonnegative_int(receipt, "completed_calls") != 1_536:
        raise CoreConfigurationError("prior completion must contain 1,536 completed calls")
    if _exact_nonnegative_int(receipt, "failed_calls") != 0:
        raise CoreConfigurationError("prior completion must contain zero failed calls")
    run_dir = Path(_string(receipt, "run_dir")).resolve(strict=True)
    if run_dir == Path("/") or not run_dir.is_dir():
        raise CoreConfigurationError("prior completion run_dir is invalid")

    generation = _object(receipt, "generation_queue")
    queue_path = _completion_external_file(
        generation,
        path_key="path",
        sha_key="sha256",
        run_dir=run_dir,
    )
    manifest_path = _completion_external_file(
        generation,
        path_key="manifest_path",
        sha_key="manifest_sha256",
        run_dir=run_dir,
    )
    if _exact_nonnegative_int(generation, "row_count") != 1_536:
        raise CoreConfigurationError("prior completion generation queue must have 1,536 rows")
    manifest = strict_json(manifest_path)
    if (
        manifest.get("queue_path") != str(queue_path)
        or manifest.get("queue_sha256") != generation.get("sha256")
        or manifest.get("row_count") != 1_536
        or manifest.get("model_row_counts") != {model_id: 1_536}
    ):
        raise CoreConfigurationError("prior completion generation manifest mismatch")
    queue_lines = queue_path.read_text(encoding="utf-8").splitlines()
    if len(queue_lines) != 1_536:
        raise CoreConfigurationError("prior completion generation queue line count mismatch")
    for expected_sequence, line in enumerate(queue_lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CoreConfigurationError("prior completion generation queue is invalid") from exc
        if (
            not isinstance(row, dict)
            or row.get("sequence") != expected_sequence
            or row.get("model_id") != model_id
            or not isinstance(row.get("request_sha256"), str)
            or SHA256_RE.fullmatch(row["request_sha256"]) is None
        ):
            raise CoreConfigurationError("prior completion generation queue row mismatch")

    heartbeat_record = _object(receipt, "heartbeat")
    heartbeat_path = _completion_external_file(
        heartbeat_record,
        path_key="path",
        sha_key="sha256",
        run_dir=run_dir,
    )
    heartbeat = strict_json(heartbeat_path)
    if (
        heartbeat.get("state") != "COMPLETE"
        or heartbeat.get("completed") != 1_536
        or heartbeat.get("failed") != 0
        or heartbeat.get("model_id", model_id) != model_id
        or heartbeat.get("run_id") != receipt.get("run_id")
    ):
        raise CoreConfigurationError("prior completion heartbeat is not terminal COMPLETE")

    ledger_record = _object(receipt, "ledger")
    ledger_path = _completion_external_file(
        ledger_record,
        path_key="path",
        sha_key="sha256",
        run_dir=run_dir,
    )
    ledger_lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if len(ledger_lines) != _exact_nonnegative_int(ledger_record, "row_count"):
        raise CoreConfigurationError("prior completion ledger row count mismatch")
    try:
        ledger_tail = json.loads(ledger_lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise CoreConfigurationError("prior completion ledger has no valid tail") from exc
    if ledger_tail.get("ledger_row_sha256") != _sha256(ledger_record, "tail_sha256"):
        raise CoreConfigurationError("prior completion ledger tail mismatch")
    if heartbeat.get("last_ledger_sha256") != ledger_record.get("tail_sha256"):
        raise CoreConfigurationError("prior completion heartbeat/ledger tail mismatch")

    counts = _object(receipt, "retained_counts")
    if counts != {
        "commit_records": 1_536,
        "request_claims": 1_536,
        "wav_files": 1_536,
    }:
        raise CoreConfigurationError("prior completion retained counts are incomplete")
    return PriorCompletionBinding(
        model_id=model_id,
        path=receipt_path,
        sha256=declared_sha,
        run_dir=run_dir,
        generation_queue_path=queue_path,
        generation_queue_sha256=str(generation["sha256"]),
    )


def load_core_execution_config(
    path: Path,
    *,
    repo_root: Path | None = None,
    verify_files: bool = True,
    phase_b_terminal_path_override: Path | None = None,
) -> CoreExecutionConfig:
    """Validate all launch-critical fields without probing a GPU or writing files."""

    source = path.resolve(strict=True)
    root = (repo_root or source.parent.parent).resolve()
    raw = strict_json(source)
    if raw.get("schema_version") != 2:
        raise CoreConfigurationError("core schema_version must equal 2")
    if not verify_files:
        raise CoreConfigurationError("launch-critical file verification cannot be disabled")
    phase_b_terminal = _validate_phase_b_terminal(
        raw,
        repo_root=root,
        path_override=phase_b_terminal_path_override,
    )
    prompt_hashes = _object(raw, "prompt_sha256")
    if set(prompt_hashes) != REQUIRED_PROMPT_HASHES:
        raise CoreConfigurationError("prompt_sha256 must contain exactly the five frozen inputs")
    for name in REQUIRED_PROMPT_HASHES:
        _sha256(prompt_hashes, name)

    statistics_record = _object(raw, "statistics_config")
    statistics_path_value = _string(statistics_record, "path")
    statistics_sha = _sha256(statistics_record, "sha256")
    statistics_path = (
        _resolve_repo_path(root, statistics_path_value, key="statistics config")
        if verify_files
        else (root / statistics_path_value).resolve()
    )
    if verify_files and sha256_file(statistics_path) != statistics_sha:
        raise CoreConfigurationError("statistics config hash mismatch")
    statistics_config = strict_json(statistics_path)
    if statistics_config.get("schema_version") != 2:
        raise CoreConfigurationError("statistics schema_version must equal two")

    execution = _object(raw, "execution")
    run_root = Path(_string(execution, "run_root"))
    if not run_root.is_absolute():
        raise CoreConfigurationError("execution.run_root must be absolute")
    resolved_run_root = run_root.resolve()
    if resolved_run_root == Path("/"):
        raise CoreConfigurationError("execution.run_root cannot be the filesystem root")
    try:
        resolved_run_root.relative_to(root)
    except ValueError:
        pass
    else:
        raise CoreConfigurationError("execution.run_root must remain outside the Git repository")
    max_duration = _positive_number(execution, "max_duration_seconds")
    if max_duration != 30.0:
        raise CoreConfigurationError("max_duration_seconds must equal 30.0")
    shard_size = _positive_int(execution, "shard_size")
    if shard_size != 4:
        raise CoreConfigurationError("shard_size must equal four")
    interval = _positive_number(execution, "heartbeat_interval_seconds")
    stale = _positive_number(execution, "heartbeat_stale_after_seconds")
    if interval > 60:
        raise CoreConfigurationError("heartbeat interval exceeds 60 seconds")
    if stale <= interval:
        raise CoreConfigurationError("heartbeat stale threshold must exceed its interval")
    state_policy = _validate_state_capture(_object(execution, "state_capture"), statistics_config)

    integrity = _object(raw, "integrity_synthetic_validation")
    if integrity.get("status") != "PASS":
        raise CoreConfigurationError("integrity synthetic validation must be PASS")
    integrity_path = _string(integrity, "report_path")
    integrity_sha = _sha256(integrity, "report_sha256")
    if verify_files:
        resolved = _resolve_repo_path(root, integrity_path, key="integrity report_path")
        if sha256_file(resolved) != integrity_sha:
            raise CoreConfigurationError("integrity validation report hash mismatch")

    model_values = raw.get("models")
    if not isinstance(model_values, list) or not model_values:
        raise CoreConfigurationError("models must be a non-empty list")
    models: list[ModelExecutionConfig] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for value in model_values:
        if not isinstance(value, dict):
            raise CoreConfigurationError("each model must be an object")
        model_id = _string(value, "model_id")
        slug = _string(value, "slug")
        status = _string(value, "queue_status")
        if status not in QUEUE_STATUSES:
            raise CoreConfigurationError(f"unsupported queue_status for {model_id}: {status}")
        if model_id in seen_ids or slug in seen_slugs:
            raise CoreConfigurationError("model IDs and slugs must be unique")
        seen_ids.add(model_id)
        seen_slugs.add(slug)
        if status in NON_EXECUTABLE_QUEUE_STATUSES:
            models.append(
                ModelExecutionConfig(
                    model_id,
                    slug,
                    status,
                    None,
                    None,
                    None,
                    None,
                    "BLOCKED",
                    None,
                    None,
                    None,
                )
            )
            continue
        core = _object(value, "core_execution")
        adapter_path_value = _string(core, "adapter_config_path")
        adapter_sha = _sha256(core, "adapter_config_sha256")
        adapter_path = (
            _resolve_repo_path(root, adapter_path_value, key="adapter_config_path")
            if verify_files
            else (root / adapter_path_value).resolve()
        )
        if verify_files and sha256_file(adapter_path) != adapter_sha:
            raise CoreConfigurationError(f"adapter config hash mismatch for {model_id}")
        adapter_config = strict_json(adapter_path) if verify_files else None
        if adapter_config is not None:
            generation = _object(adapter_config, "generation")
            sample_rate = _positive_int(generation, "sample_rate")
            duration = _positive_number(generation, "benchmark_duration_seconds")
            if duration != 30.0:
                raise CoreConfigurationError("adapter benchmark duration must equal 30 seconds")
        else:
            sample_rate = _positive_int(core, "expected_sample_rate")
        expected_channels = core.get("expected_channels")
        if expected_channels != 2:
            raise CoreConfigurationError("core expected_channels must equal stereo (2)")
        state_status = _string(core, "state_capture_status")
        if state_status not in {"READY", "AUTOMATIC_OUTPUT_ONLY"}:
            raise CoreConfigurationError("state_capture_status has an unsupported value")
        duration_tolerance = _nonnegative_number(
            core,
            "duration_tolerance_seconds",
            default=0.0,
        )
        if duration_tolerance > MAX_DURATION_TOLERANCE_SECONDS:
            raise CoreConfigurationError(
                "duration_tolerance_seconds exceeds the adjudicated 0.25-second maximum"
            )
        if (
            "duration_tolerance_seconds" in core
            and duration_tolerance != MAX_DURATION_TOLERANCE_SECONDS
        ):
            raise CoreConfigurationError(
                "an explicit duration_tolerance_seconds must equal the adjudicated 0.25"
            )
        # Exercise the shared policy validator at configuration load rather than first audio.
        duration_within_tolerance(30.0, 30.0, duration_tolerance)
        if model_id == SAO_MODEL_ID:
            if state_status != "AUTOMATIC_OUTPUT_ONLY":
                raise CoreConfigurationError("SAO state capability must remain NOT_ATTEMPTED")
            sao_runtime = _validate_sao_runtime(
                core,
                repo_root=root,
                adapter_config_sha256=adapter_sha,
            )
        else:
            if "sao_runtime" in core:
                raise CoreConfigurationError("non-SAO model may not carry sao_runtime gates")
            sao_runtime = None
        models.append(
            ModelExecutionConfig(
                model_id=model_id,
                slug=slug,
                queue_status=status,
                adapter_config_path=adapter_path,
                adapter_config_sha256=adapter_sha,
                placement=_validate_placement(_object(core, "placement")),
                budget=_validate_budget(_object(core, "budget")),
                state_capture_status=state_status,
                expected_sample_rate=sample_rate,
                expected_channels=expected_channels,
                duration_tolerance_seconds=duration_tolerance,
                sao_runtime=sao_runtime,
            )
        )
    ready_ids = {model.model_id for model in models if model.queue_status == READY}
    configured_statuses = {model.model_id: model.queue_status for model in models}
    if set(configured_statuses) != REQUIRED_MODEL_IDS:
        raise CoreConfigurationError("core models must contain exactly the three backbones")
    if configured_statuses != phase_b_terminal.model_queue_statuses:
        raise CoreConfigurationError("core queue statuses drift from Phase-B terminal receipt")
    for model in models:
        if model.queue_status != READY:
            continue
        assert model.budget is not None
        terminal_cost = phase_b_terminal.ready_costs.get(model.model_id)
        if terminal_cost is None:
            raise CoreConfigurationError("READY model lacks terminal measured cost")
        if not math.isclose(
            model.budget.cold_plus_first_seconds,
            terminal_cost[0],
            rel_tol=0,
            abs_tol=1e-9,
        ) or not math.isclose(
            model.budget.resident_unit_seconds,
            terminal_cost[1],
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise CoreConfigurationError(
                f"core budget costs drift from Phase-B receipt: {model.model_id}"
            )
    if not ready_ids:
        raise CoreConfigurationError("at least one model must be READY")

    authorized_value = execution.get("authorized_model_ids")
    if authorized_value is None:
        authorized_model_ids = tuple(
            model.model_id for model in models if model.queue_status == READY
        )
    else:
        if (
            not isinstance(authorized_value, list)
            or not authorized_value
            or not all(isinstance(item, str) and item for item in authorized_value)
            or len(set(authorized_value)) != len(authorized_value)
        ):
            raise CoreConfigurationError(
                "execution.authorized_model_ids must be a non-empty unique string list"
            )
        if not set(authorized_value).issubset(ready_ids):
            raise CoreConfigurationError("authorized_model_ids must be a subset of READY models")
        authorized_model_ids = tuple(authorized_value)

    completion_values = execution.get("prior_model_completions", {})
    if not isinstance(completion_values, dict):
        raise CoreConfigurationError("execution.prior_model_completions must be an object")
    excluded_ready_ids = ready_ids - set(authorized_model_ids)
    if set(completion_values) != excluded_ready_ids:
        raise CoreConfigurationError(
            "prior_model_completions must exactly bind every READY-but-excluded model"
        )
    prior_model_completions: dict[str, PriorCompletionBinding] = {}
    for model_id, completion_value in completion_values.items():
        if not isinstance(completion_value, dict):
            raise CoreConfigurationError("each prior model completion binding must be an object")
        prior_model_completions[model_id] = _validate_prior_completion(
            model_id,
            completion_value,
            repo_root=root,
        )
    if not set(state_policy.eligible_model_ids).issubset(ready_ids):
        raise CoreConfigurationError("state-capture model IDs must be READY")
    for model in models:
        if (
            model.model_id in state_policy.eligible_model_ids
            and model.state_capture_status != "READY"
        ):
            raise CoreConfigurationError(
                "state-capture policy includes a model without READY state"
            )

    return CoreExecutionConfig(
        source_path=source,
        source_sha256=sha256_file(source),
        repo_root=root,
        run_root=run_root,
        max_duration_seconds=max_duration,
        shard_size=shard_size,
        heartbeat_interval_seconds=interval,
        heartbeat_stale_after_seconds=stale,
        authorized_model_ids=authorized_model_ids,
        models=tuple(models),
        phase_b_terminal=phase_b_terminal,
        prior_model_completions=prior_model_completions,
        state_capture=state_policy,
        raw=raw,
    )

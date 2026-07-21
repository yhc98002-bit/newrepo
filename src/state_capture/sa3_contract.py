"""Frozen queue and action contracts for the SA3 benchmark-v2 state screen.

This module is deliberately CPU-only.  It binds an already completed ordinary
core run to a separate queue namespace, but it neither imports a backbone nor
initializes CUDA.  The resulting bundle remains closed until a distinct state
authorization is validated by the worker boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from benchmark_core.ledger import TERMINAL_REQUEST_STATES, validate_ledger
from benchmark_core.queue import canonical_json, load_queue
from benchmark_core.state_queue import load_state_capture_queue

SA3_MODEL_ID = "stabilityai/stable-audio-3-medium-base"
LANE_ID = "sa3-state-capture-v2"
INITIAL_TIER = "INITIAL"
LANE_CLOSED_STATUS = "CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION"
SOURCE_QUEUE_CLOSED_STATUS = "CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION"
CAPTURE_MODE = "SEPARATE_LEDGERED_STATE_CAPTURE_QUEUE"
PREVIEW_SOURCE = "ONLY_THE_SAME_UNITS_ROOT_LOCAL_PRE_ACTION_DECODED_PREVIEW"
RESTART_LABEL = "RESTART_POOL_SHARED_AT_PROMPT_LEVEL"
ELIGIBILITY_UNIT_FIELDS = ("prompt", "root", "checkpoint")
AXES = ("vocal_instrumental", "tempo", "integrity")
CHECKPOINT_FRACTIONS = (0.25, 0.5, 0.75)
INITIAL_ROOTS = (0, 1, 2, 3)
SUPPLEMENTAL_ROOTS = (4, 5, 6, 7)
ACTIONS = ("KEEP", "RESTART_BASE", "RESTART_FIXED")
FOLD_COUNT = 6
EXPECTED_PROMPTS_PER_AXIS = 12
EXPECTED_GROUPS = len(AXES) * EXPECTED_PROMPTS_PER_AXIS * len(INITIAL_ROOTS)
EXPECTED_UNITS = EXPECTED_GROUPS * len(CHECKPOINT_FRACTIONS)
EXPECTED_ACTION_ROWS = EXPECTED_UNITS * len(ACTIONS)
SHA256_ZERO = "0" * 64


class StateCaptureConfigurationError(ValueError):
    """A frozen source, design field, or execution boundary drifted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StateCaptureConfigurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                StateCaptureConfigurationError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateCaptureConfigurationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateCaptureConfigurationError(f"JSON root must be an object: {path}")
    return value


def _require_sha256(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StateCaptureConfigurationError(f"{name} must be a lowercase SHA-256")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateCaptureConfigurationError(f"{name} must be a non-empty string")
    return value


def _resolve_file(repo_root: Path, value: Any, name: str) -> Path:
    text = _require_string(value, name)
    candidate = Path(text)
    path = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    if not path.is_file():
        raise StateCaptureConfigurationError(f"{name} is not a file: {path}")
    return path


def _resolve_dir(value: Any, name: str, *, must_exist: bool = True) -> Path:
    path = Path(_require_string(value, name)).resolve()
    if must_exist and not path.is_dir():
        raise StateCaptureConfigurationError(f"{name} is not a directory: {path}")
    return path


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_jsonl_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


@dataclass(frozen=True)
class SourceCoreRun:
    run_dir: Path
    run_manifest_path: Path
    run_manifest_sha256: str
    generation_queue_path: Path
    generation_queue_sha256: str
    initial_state_queue_path: Path
    initial_state_queue_sha256: str
    ledger_path: Path
    ledger_sha256: str
    artifact_root: Path


@dataclass(frozen=True)
class PlacementPolicy:
    allowed_nodes: tuple[str, ...]
    allowed_physical_gpu_ids: tuple[int, ...]
    shared_core_lock_root: Path
    minimum_free_vram_bytes: int
    post_load_reserve_bytes: int
    maximum_idle_utilization_percent: int
    required_gpu_name_substring: str
    tp_width: int
    maximum_parallel_replicas: int
    replica_count_per_worker: int


@dataclass(frozen=True)
class SA3StateCaptureConfig:
    source_path: Path
    source_sha256: str
    repo_root: Path
    statistics_path: Path
    statistics_sha256: str
    prereg_path: Path
    prereg_sha256: str
    d0020_result_path: Path
    d0020_result_sha256: str
    smoke_e_sources: tuple[tuple[Path, str], ...]
    core_source: SourceCoreRun
    placement: PlacementPolicy
    run_root: Path
    heartbeat_interval_seconds: float
    heartbeat_stale_after_seconds: float
    initial_gpu_seconds_cap: float
    prefix_group_reservation_seconds: float
    resume_unit_reservation_seconds: float
    transformer_budget_nfe: int
    checkpoint_completed_steps: tuple[int, ...]
    checkpoint_rounding_rule: str
    fold_namespace: str
    restart_namespace: str
    checkpoint_token_rule: str
    preview_feature_groups: tuple[str, ...]
    forbidden_feature_sources: tuple[str, ...]
    axis_evaluator_groups: dict[str, tuple[str, ...]]
    raw: dict[str, Any]


def _half_up_steps(fractions: Sequence[float], budget: int) -> tuple[int, ...]:
    return tuple(
        int(
            (Decimal(str(fraction)) * Decimal(budget)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        for fraction in fractions
    )


def load_sa3_state_capture_config(path: Path, *, repo_root: Path) -> SA3StateCaptureConfig:
    """Load and content-bind the closed SA3 state lane without touching CUDA."""

    source = path.resolve(strict=True)
    root = repo_root.resolve(strict=True)
    raw = strict_json(source)
    if raw.get("schema_version") != 1 or raw.get("lane_id") != LANE_ID:
        raise StateCaptureConfigurationError("SA3 state config schema/lane identity mismatch")
    if raw.get("model_id") != SA3_MODEL_ID or raw.get("tier") != INITIAL_TIER:
        raise StateCaptureConfigurationError("SA3 state config model/tier mismatch")
    if raw.get("execution_status") != LANE_CLOSED_STATUS:
        raise StateCaptureConfigurationError("committed SA3 state config must remain closed")

    sources = raw.get("frozen_sources")
    if not isinstance(sources, dict):
        raise StateCaptureConfigurationError("frozen_sources must be an object")
    bound: dict[str, tuple[Path, str]] = {}
    for name in ("prereg_v2", "statistics_v2", "smoke_e", "latent", "resume_child"):
        record = sources.get(name)
        if not isinstance(record, dict):
            raise StateCaptureConfigurationError(f"frozen source is absent: {name}")
        source_path = _resolve_file(root, record.get("path"), f"frozen_sources.{name}.path")
        expected = _require_sha256(record.get("sha256"), f"frozen_sources.{name}.sha256")
        observed = sha256_file(source_path)
        if observed != expected:
            raise StateCaptureConfigurationError(
                f"frozen source hash mismatch for {name}: {observed} != {expected}"
            )
        bound[name] = (source_path, expected)

    d0020 = raw.get("d0020_capability_evidence")
    if not isinstance(d0020, dict):
        raise StateCaptureConfigurationError("D-0020 capability evidence is absent")
    d0020_path = _resolve_file(root, d0020.get("path"), "d0020_capability_evidence.path")
    d0020_sha256 = _require_sha256(d0020.get("sha256"), "d0020_capability_evidence.sha256")
    if sha256_file(d0020_path) != d0020_sha256:
        raise StateCaptureConfigurationError("D-0020 result hash mismatch")
    d0020_result = strict_json(d0020_path)
    if (
        d0020_result.get("run_id") != "sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24"
        or d0020_result.get("SA3_SMOKE_E_RETRY_STATUS") != "PASS"
        or d0020_result.get("SA3_STATE_CAPABILITY") != "PASS"
        or d0020_result.get("exit_code") != 0
    ):
        raise StateCaptureConfigurationError("D-0020 is not the accepted terminal PASS")
    d0020_smoke = d0020_result.get("smoke_e")
    checks = (
        d0020_smoke.get("result", {}).get("checks", {}) if isinstance(d0020_smoke, dict) else {}
    )
    required_d0020_checks = {
        "all_children_terminal_pass",
        "all_waveform_equivalence_checks_pass",
        "all_child_pids_differ_from_reference_pid",
        "all_checkpoints_record_runtime_dtype_at_export",
        "remaining_forward_calls_are_35_20_10",
        "three_children_launched_sequentially",
    }
    if any(checks.get(name) is not True for name in required_d0020_checks):
        raise StateCaptureConfigurationError("D-0020 lacks required state/resume PASS checks")

    statistics = strict_json(bound["statistics_v2"][0])
    eligibility = statistics.get("eligibility")
    if not isinstance(eligibility, dict):
        raise StateCaptureConfigurationError("statistics eligibility contract is absent")
    if eligibility.get("unit") != list(ELIGIBILITY_UNIT_FIELDS):
        raise StateCaptureConfigurationError("eligibility unit must be prompt/root/checkpoint")
    if eligibility.get("checkpoint_fractions") != list(CHECKPOINT_FRACTIONS):
        raise StateCaptureConfigurationError("eligibility checkpoints drift from 25/50/75")
    if eligibility.get("actions") != list(ACTIONS):
        raise StateCaptureConfigurationError("eligibility action order drift")
    if eligibility.get("fold_count") != FOLD_COUNT:
        raise StateCaptureConfigurationError("eligibility fold count drift")
    if eligibility.get("restart_outcome_label") != RESTART_LABEL:
        raise StateCaptureConfigurationError("restart prompt-pool label drift")
    capture = eligibility.get("state_capture_contract")
    if not isinstance(capture, dict):
        raise StateCaptureConfigurationError("state capture source contract is absent")
    if (
        capture.get("feature_source") != PREVIEW_SOURCE
        or capture.get("source_condition") != "BASE"
        or capture.get("preview_must_be_derived_from_exported_root_state") is not True
        or capture.get("one_capture_per_prompt_root_checkpoint") is not True
    ):
        raise StateCaptureConfigurationError("root-local BASE preview contract drift")

    design = raw.get("frozen_design")
    if not isinstance(design, dict):
        raise StateCaptureConfigurationError("frozen_design must be an object")
    expected_design = {
        "actions": list(ACTIONS),
        "axes": list(AXES),
        "capture_mode": CAPTURE_MODE,
        "checkpoint_fractions": list(CHECKPOINT_FRACTIONS),
        "condition": "BASE",
        "eligibility_unit": list(ELIGIBILITY_UNIT_FIELDS),
        "fold_count": FOLD_COUNT,
        "initial_root_indices": list(INITIAL_ROOTS),
        "preview_source": PREVIEW_SOURCE,
        "restart_outcome_label": RESTART_LABEL,
        "restart_pool_root_indices": list(SUPPLEMENTAL_ROOTS),
    }
    for key, expected in expected_design.items():
        if design.get(key) != expected:
            raise StateCaptureConfigurationError(f"frozen_design.{key} drift")
    if design.get("prompt_count_per_axis") != EXPECTED_PROMPTS_PER_AXIS:
        raise StateCaptureConfigurationError("frozen_design prompt count drift")
    if design.get("expected_prefix_groups") != EXPECTED_GROUPS:
        raise StateCaptureConfigurationError("frozen_design prefix group count drift")
    if design.get("expected_initial_units") != EXPECTED_UNITS:
        raise StateCaptureConfigurationError("frozen_design unit count drift")
    if design.get("expected_action_rows") != EXPECTED_ACTION_ROWS:
        raise StateCaptureConfigurationError("frozen_design action row count drift")

    sa3 = raw.get("sa3_checkpoint_mapping")
    if not isinstance(sa3, dict):
        raise StateCaptureConfigurationError("sa3_checkpoint_mapping must be an object")
    budget = sa3.get("transformer_budget_nfe")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise StateCaptureConfigurationError("SA3 transformer budget must be positive integer NFE")
    rounding = sa3.get("rounding_rule")
    if rounding != "ROUND_HALF_UP_FRACTION_TIMES_FROZEN_NFE":
        raise StateCaptureConfigurationError("SA3 checkpoint rounding rule drift")
    observed_steps = _half_up_steps(CHECKPOINT_FRACTIONS, budget)
    if sa3.get("completed_steps") != list(observed_steps):
        raise StateCaptureConfigurationError("SA3 checkpoint step mapping is inconsistent")
    if not all(0 < step < budget for step in observed_steps):
        raise StateCaptureConfigurationError("SA3 checkpoint step mapping is out of range")

    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        raise StateCaptureConfigurationError("mapping must be an object")
    if mapping.get("fold_namespace") != "benchmark-v2-eligibility-folds-20260720":
        raise StateCaptureConfigurationError("fold namespace drift")
    if mapping.get("restart_namespace") != "benchmark-v2-restart-map-20260720":
        raise StateCaptureConfigurationError("restart namespace drift")
    if mapping.get("rotation_direction") != "LEFT":
        raise StateCaptureConfigurationError("restart rotation direction must be LEFT")
    if mapping.get("checkpoint_token_rule") != "SHORTEST_DECIMAL_JSON_NUMBER":
        raise StateCaptureConfigurationError("checkpoint token rule drift")

    feature = raw.get("feature_contract")
    if not isinstance(feature, dict):
        raise StateCaptureConfigurationError("feature_contract must be an object")
    groups = feature.get("required_feature_groups")
    forbidden = feature.get("forbidden_sources")
    axis_groups = feature.get("axis_evaluator_groups")
    if not isinstance(groups, list) or groups != [
        "AXIS_EVALUATOR_VALUES",
        "INTEGRITY_VALUES",
        "WITHIN_PREVIEW_SUMMARIES",
        "FROZEN_DECODER_METADATA",
    ]:
        raise StateCaptureConfigurationError("required preview feature groups drift")
    if not isinstance(forbidden, list) or forbidden != capture.get("forbidden_sources"):
        raise StateCaptureConfigurationError("forbidden feature sources drift from statistics")
    if not isinstance(axis_groups, dict) or set(axis_groups) != set(AXES):
        raise StateCaptureConfigurationError("axis evaluator feature groups are incomplete")
    normalized_axis_groups: dict[str, tuple[str, ...]] = {}
    for axis in AXES:
        values = axis_groups[axis]
        if (
            not isinstance(values, list)
            or not values
            or len(set(values)) != len(values)
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise StateCaptureConfigurationError(f"invalid evaluator groups for {axis}")
        normalized_axis_groups[axis] = tuple(values)

    core = raw.get("source_core_run")
    if not isinstance(core, dict):
        raise StateCaptureConfigurationError("source_core_run must be an object")
    run_dir = _resolve_dir(core.get("run_dir"), "source_core_run.run_dir")
    core_paths: dict[str, tuple[Path, str]] = {}
    for name in (
        "run_manifest",
        "generation_queue",
        "initial_state_queue",
        "ledger",
    ):
        record = core.get(name)
        if not isinstance(record, dict):
            raise StateCaptureConfigurationError(f"source_core_run.{name} must be an object")
        bound_path = _resolve_file(root, record.get("path"), f"source_core_run.{name}.path")
        try:
            bound_path.relative_to(run_dir)
        except ValueError as exc:
            raise StateCaptureConfigurationError(f"source core {name} escapes run_dir") from exc
        expected = _require_sha256(record.get("sha256"), f"source_core_run.{name}.sha256")
        observed = sha256_file(bound_path)
        if observed != expected:
            raise StateCaptureConfigurationError(
                f"source core {name} hash mismatch: {observed} != {expected}"
            )
        core_paths[name] = (bound_path, expected)
    artifact_root = _resolve_dir(core.get("artifact_root"), "source_core_run.artifact_root")
    try:
        artifact_root.relative_to(run_dir)
    except ValueError as exc:
        raise StateCaptureConfigurationError("source core artifact_root escapes run_dir") from exc

    execution = raw.get("execution")
    placement = raw.get("placement")
    if not isinstance(execution, dict) or not isinstance(placement, dict):
        raise StateCaptureConfigurationError("execution and placement must be objects")
    interval = execution.get("heartbeat_interval_seconds")
    stale = execution.get("heartbeat_stale_after_seconds")
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not math.isfinite(float(interval))
        or not 0 < float(interval) <= 60
        or isinstance(stale, bool)
        or not isinstance(stale, (int, float))
        or not math.isfinite(float(stale))
        or float(stale) <= float(interval)
    ):
        raise StateCaptureConfigurationError("heartbeat interval/stale threshold is invalid")
    run_root = _resolve_dir(execution.get("run_root"), "execution.run_root", must_exist=False)

    budget_record = execution.get("state_gpu_budget")
    if not isinstance(budget_record, dict):
        raise StateCaptureConfigurationError("prospective state GPU budget is absent")
    cold_reference = 116.34399104863405
    group_residency = 249.481707109
    expected_budget_fields = {
        "d0020_cold_load_plus_reference_seconds": cold_reference,
        "d0020_group_gpu_residency_upper_bound_seconds": group_residency,
        "evidence_status": "MEASURED_D0020_SINGLE_GROUP_CONSERVATIVE_TIMES_TWO",
        "factor": 2.0,
        "initial_group_count": EXPECTED_GROUPS,
        "resume_units_per_group": 3,
    }
    for name, expected in expected_budget_fields.items():
        if budget_record.get(name) != expected:
            raise StateCaptureConfigurationError(f"state_gpu_budget.{name} drift")
    prefix_reservation = 2 * cold_reference
    resume_reservation = 2 * (group_residency - cold_reference) / 3
    initial_cap = EXPECTED_GROUPS * (prefix_reservation + 3 * resume_reservation)
    for name, expected in (
        ("prefix_group_reservation_seconds", prefix_reservation),
        ("resume_unit_reservation_seconds", resume_reservation),
        ("initial_gpu_seconds_cap", initial_cap),
        ("initial_gpu_hour_cap", initial_cap / 3600),
    ):
        value = budget_record.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isclose(float(value), expected, rel_tol=0, abs_tol=1e-9)
        ):
            raise StateCaptureConfigurationError(f"state_gpu_budget.{name} formula drift")

    nodes = placement.get("allowed_nodes")
    gpu_ids = placement.get("allowed_physical_gpu_ids")
    if nodes != ["an12"]:
        raise StateCaptureConfigurationError("SA3 state workers must run on an12 only")
    if gpu_ids != [4, 5, 6, 7]:
        raise StateCaptureConfigurationError("allowed state GPUs must be an12 physical 4..7")
    lock_root = Path(
        _require_string(placement.get("shared_core_lock_root"), "placement.shared_core_lock_root")
    ).resolve()
    if lock_root.name != "core-v2":
        raise StateCaptureConfigurationError("state lane must use the ordinary core lock namespace")
    positive_ints: dict[str, int] = {}
    for name in (
        "minimum_free_vram_bytes",
        "post_load_reserve_bytes",
        "maximum_idle_utilization_percent",
        "tp_width",
        "maximum_parallel_replicas",
        "replica_count_per_worker",
    ):
        value = placement.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise StateCaptureConfigurationError(f"placement.{name} must be a positive integer")
        positive_ints[name] = value
    if positive_ints["maximum_idle_utilization_percent"] > 5:
        raise StateCaptureConfigurationError("state lane idle utilization threshold exceeds 5%")
    if (
        positive_ints["tp_width"] != 1
        or positive_ints["replica_count_per_worker"] != 1
        or positive_ints["maximum_parallel_replicas"] != 4
    ):
        raise StateCaptureConfigurationError("SA3 state work must be four disjoint TP1 workers")

    return SA3StateCaptureConfig(
        source_path=source,
        source_sha256=sha256_file(source),
        repo_root=root,
        statistics_path=bound["statistics_v2"][0],
        statistics_sha256=bound["statistics_v2"][1],
        prereg_path=bound["prereg_v2"][0],
        prereg_sha256=bound["prereg_v2"][1],
        d0020_result_path=d0020_path,
        d0020_result_sha256=d0020_sha256,
        smoke_e_sources=(bound["smoke_e"], bound["latent"], bound["resume_child"]),
        core_source=SourceCoreRun(
            run_dir=run_dir,
            run_manifest_path=core_paths["run_manifest"][0],
            run_manifest_sha256=core_paths["run_manifest"][1],
            generation_queue_path=core_paths["generation_queue"][0],
            generation_queue_sha256=core_paths["generation_queue"][1],
            initial_state_queue_path=core_paths["initial_state_queue"][0],
            initial_state_queue_sha256=core_paths["initial_state_queue"][1],
            ledger_path=core_paths["ledger"][0],
            ledger_sha256=core_paths["ledger"][1],
            artifact_root=artifact_root,
        ),
        placement=PlacementPolicy(
            allowed_nodes=tuple(nodes),
            allowed_physical_gpu_ids=tuple(gpu_ids),
            shared_core_lock_root=lock_root,
            minimum_free_vram_bytes=positive_ints["minimum_free_vram_bytes"],
            post_load_reserve_bytes=positive_ints["post_load_reserve_bytes"],
            maximum_idle_utilization_percent=positive_ints["maximum_idle_utilization_percent"],
            required_gpu_name_substring=_require_string(
                placement.get("required_gpu_name_substring"),
                "placement.required_gpu_name_substring",
            ),
            tp_width=positive_ints["tp_width"],
            maximum_parallel_replicas=positive_ints["maximum_parallel_replicas"],
            replica_count_per_worker=positive_ints["replica_count_per_worker"],
        ),
        run_root=run_root,
        heartbeat_interval_seconds=float(interval),
        heartbeat_stale_after_seconds=float(stale),
        initial_gpu_seconds_cap=initial_cap,
        prefix_group_reservation_seconds=prefix_reservation,
        resume_unit_reservation_seconds=resume_reservation,
        transformer_budget_nfe=budget,
        checkpoint_completed_steps=observed_steps,
        checkpoint_rounding_rule=rounding,
        fold_namespace=mapping["fold_namespace"],
        restart_namespace=mapping["restart_namespace"],
        checkpoint_token_rule=mapping["checkpoint_token_rule"],
        preview_feature_groups=tuple(groups),
        forbidden_feature_sources=tuple(forbidden),
        axis_evaluator_groups=normalized_axis_groups,
        raw=raw,
    )


def _checkpoint_token(fraction: float) -> str:
    return json.dumps(fraction, allow_nan=False, separators=(",", ":"))


def _folds(
    config: SA3StateCaptureConfig, prompt_ids: Mapping[str, Sequence[str]]
) -> dict[str, int]:
    result: dict[str, int] = {}
    for axis in AXES:
        ids = tuple(prompt_ids[axis])
        if len(ids) != EXPECTED_PROMPTS_PER_AXIS or len(set(ids)) != len(ids):
            raise StateCaptureConfigurationError(f"{axis} does not contain 12 unique prompts")
        ordered = sorted(
            ids,
            key=lambda prompt_id: hashlib.sha256(
                f"{config.fold_namespace}|{prompt_id}".encode()
            ).hexdigest(),
        )
        for index, prompt_id in enumerate(ordered):
            result[f"{axis}|{prompt_id}"] = index % FOLD_COUNT
    return result


def _restart_root(
    config: SA3StateCaptureConfig,
    *,
    prompt_id: str,
    fraction: float,
    action: str,
    root_index: int,
) -> tuple[int, int]:
    if action not in {"RESTART_BASE", "RESTART_FIXED"}:
        raise ValueError("restart mapping accepts only restart actions")
    root_position = INITIAL_ROOTS.index(root_index)
    material = f"{config.restart_namespace}|{prompt_id}|{_checkpoint_token(fraction)}|{action}"
    offset = int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 4
    rotated = SUPPLEMENTAL_ROOTS[offset:] + SUPPLEMENTAL_ROOTS[:offset]
    return rotated[root_position], offset


def _validate_core_artifact(artifact_root: Path, generation: Mapping[str, Any]) -> dict[str, Any]:
    output = Path(str(generation.get("output_relpath", "")))
    if output.is_absolute() or ".." in output.parts or output.suffix.lower() != ".wav":
        raise StateCaptureConfigurationError("source generation output path is unsafe")
    wav = (artifact_root / output).resolve()
    try:
        wav.relative_to(artifact_root)
    except ValueError as exc:
        raise StateCaptureConfigurationError(
            "source generation output escapes artifact root"
        ) from exc
    commit_path = wav.with_suffix(".commit.json")
    provenance_path = wav.with_suffix(".provenance.json")
    sanity_path = wav.with_suffix(".sanity.json")
    for path in (wav, commit_path, provenance_path, sanity_path):
        if not path.is_file():
            raise StateCaptureConfigurationError(f"completed core artifact is absent: {path}")
    commit = strict_json(commit_path)
    provenance = strict_json(provenance_path)
    sanity = strict_json(sanity_path)
    request_sha = generation.get("request_sha256")
    if (
        commit.get("status") != "COMMITTED"
        or commit.get("request_sha256") != request_sha
        or commit.get("output_relpath") != output.as_posix()
    ):
        raise StateCaptureConfigurationError("source core commit identity mismatch")
    recorded_wav_sha256 = _require_sha256(commit.get("wav_sha256"), "core commit wav_sha256")
    if (
        provenance.get("wav_sha256") != recorded_wav_sha256
        or sanity.get("wav_sha256") != recorded_wav_sha256
        or wav.stat().st_size <= 0
    ):
        raise StateCaptureConfigurationError("source core WAV identity chain drift")
    observed = {
        "commit_path": str(commit_path),
        "commit_sha256": sha256_file(commit_path),
        "output_relpath": output.as_posix(),
        "provenance_sha256": sha256_file(provenance_path),
        "request_sha256": request_sha,
        "sanity_sha256": sha256_file(sanity_path),
        # The source worker already hashed every retained WAV before writing
        # provenance, sanity, commit, and the hash-chained terminal ledger row.
        # Rebind that three-file consensus plus the immutable ledger hash here;
        # do not reread several gigabytes of audio during a CPU-only queue build.
        "wav_sha256": recorded_wav_sha256,
    }
    for key in ("provenance_sha256", "sanity_sha256", "wav_sha256"):
        if commit.get(key) != observed[key]:
            raise StateCaptureConfigurationError(f"source core commit hash drift at {key}")
    return observed


def _source_records(
    config: SA3StateCaptureConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    source = config.core_source
    manifest = strict_json(source.run_manifest_path)
    if manifest.get("status") != "PREPARED_NO_MODEL_CALLS":
        raise StateCaptureConfigurationError("source core run manifest status drift")
    state_manifest = manifest.get("state_capture_initial_manifest")
    generation_manifest = manifest.get("generation_queue_manifest")
    if not isinstance(state_manifest, dict) or not isinstance(generation_manifest, dict):
        raise StateCaptureConfigurationError("source run omits queue manifests")
    if (
        state_manifest.get("authorization_status") != SOURCE_QUEUE_CLOSED_STATUS
        or state_manifest.get("capture_mode") != CAPTURE_MODE
        or state_manifest.get("preview_source") != PREVIEW_SOURCE
        or state_manifest.get("restart_outcome_label") != RESTART_LABEL
        or state_manifest.get("tier") != INITIAL_TIER
        or state_manifest.get("row_count") != EXPECTED_UNITS
        or state_manifest.get("queue_sha256") != source.initial_state_queue_sha256
    ):
        raise StateCaptureConfigurationError("source initial state queue contract drift")
    if generation_manifest.get(
        "queue_sha256"
    ) != source.generation_queue_sha256 or generation_manifest.get("model_row_counts") != {
        SA3_MODEL_ID: 1536
    }:
        raise StateCaptureConfigurationError("source generation queue identity drift")

    generation_rows = load_queue(source.generation_queue_path)
    generation_by_sha = {row["request_sha256"]: row for row in generation_rows}
    if len(generation_rows) != 1536 or len(generation_by_sha) != 1536:
        raise StateCaptureConfigurationError("source SA3 core queue must contain 1536 rows")
    state_rows = load_state_capture_queue(source.initial_state_queue_path)
    if len(state_rows) != EXPECTED_UNITS:
        raise StateCaptureConfigurationError("source initial state queue must contain 432 rows")

    ledger_rows = validate_ledger(source.ledger_path)
    latest: dict[str, str] = {}
    for row in ledger_rows:
        if row.get("event_kind") == "REQUEST_STATE":
            latest[str(row["request_sha256"])] = str(row["request_state"])
    if set(latest) != set(generation_by_sha) or set(latest.values()) != {"SUCCEEDED"}:
        raise StateCaptureConfigurationError("source core ledger is not 1536/1536 SUCCEEDED")
    if any(value not in TERMINAL_REQUEST_STATES for value in latest.values()):
        raise StateCaptureConfigurationError("source core ledger contains nonterminal requests")

    parent_rows: dict[str, dict[str, Any]] = {}
    for state in state_rows:
        parent_sha = state.get("parent_request_sha256")
        generation = generation_by_sha.get(parent_sha)
        if generation is None:
            raise StateCaptureConfigurationError("state unit parent is absent from core queue")
        if (
            generation.get("model_id") != SA3_MODEL_ID
            or generation.get("condition") != "BASE"
            or generation.get("axis") not in AXES
            or generation.get("root_index") not in INITIAL_ROOTS
            or state.get("preview_source_request_sha256") != parent_sha
            or state.get("restart_outcome_label") != RESTART_LABEL
            or state.get("authorization_status") != SOURCE_QUEUE_CLOSED_STATUS
        ):
            raise StateCaptureConfigurationError(
                "source state unit violates frozen BASE/root contract"
            )
        parent_rows[parent_sha] = generation
    if len(parent_rows) != EXPECTED_GROUPS:
        raise StateCaptureConfigurationError("source state units do not form 144 root groups")
    return generation_rows, state_rows, parent_rows


def _hashed_row(row: dict[str, Any], identity_field: str) -> dict[str, Any]:
    if identity_field in row:
        raise ValueError(f"row already contains {identity_field}")
    result = dict(row)
    result[identity_field] = hashlib.sha256(canonical_json(result).encode()).hexdigest()
    return result


def _build_rows(
    config: SA3StateCaptureConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    generation_rows, state_rows, parent_rows = _source_records(config)
    statistics = strict_json(config.statistics_path)["eligibility"]
    selection = statistics["prompt_selection"]["axis_prompt_ids"]
    prompt_ids = {axis: tuple(selection[axis]) for axis in AXES}
    folds = _folds(config, prompt_ids)
    selected = {prompt_id for ids in prompt_ids.values() for prompt_id in ids}
    if len(selected) != len(AXES) * EXPECTED_PROMPTS_PER_AXIS:
        raise StateCaptureConfigurationError("selected prompt IDs must be unique across axes")

    generation_index: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in generation_rows:
        key = (str(row["prompt_id"]), str(row["condition"]), int(row["root_index"]))
        if key in generation_index:
            raise StateCaptureConfigurationError("source core generation key is duplicated")
        generation_index[key] = row

    state_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in state_rows:
        state_by_parent[str(row["parent_request_sha256"])].append(row)

    unit_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    artifact_cache: dict[str, dict[str, Any]] = {}
    lane_sequence = 0
    action_sequence = 0

    def core_artifact(generation: Mapping[str, Any]) -> dict[str, Any]:
        identity = str(generation["request_sha256"])
        if identity not in artifact_cache:
            artifact_cache[identity] = _validate_core_artifact(
                config.core_source.artifact_root, generation
            )
        return artifact_cache[identity]

    for group_sequence, parent_sha in enumerate(
        sorted(
            parent_rows,
            key=lambda identity: (
                AXES.index(str(parent_rows[identity]["axis"])),
                str(parent_rows[identity]["prompt_id"]),
                int(parent_rows[identity]["root_index"]),
            ),
        ),
        start=1,
    ):
        parent = parent_rows[parent_sha]
        axis = str(parent["axis"])
        prompt_id = str(parent["prompt_id"])
        root_index = int(parent["root_index"])
        if prompt_id not in prompt_ids[axis]:
            raise StateCaptureConfigurationError("source state queue selected an unfrozen prompt")
        group_units: list[dict[str, Any]] = []
        state_candidates = sorted(
            state_by_parent[parent_sha], key=lambda row: float(row["checkpoint_fraction"])
        )
        if [row["checkpoint_fraction"] for row in state_candidates] != list(CHECKPOINT_FRACTIONS):
            raise StateCaptureConfigurationError("state group lacks exact 25/50/75 checkpoints")
        parent_core_artifact = core_artifact(parent)
        for source_state, completed_steps in zip(
            state_candidates, config.checkpoint_completed_steps, strict=True
        ):
            lane_sequence += 1
            fraction = float(source_state["checkpoint_fraction"])
            base = Path("sa3-state-capture-v2") / axis / prompt_id / f"root-{root_index:02d}"
            token = f"q-{round(fraction * 100):03d}"
            unit = {
                "action_set": list(ACTIONS),
                "authorization_status": LANE_CLOSED_STATUS,
                "axis": axis,
                "capture_mode": CAPTURE_MODE,
                "checkpoint_completed_steps": completed_steps,
                "checkpoint_fraction": fraction,
                "checkpoint_relpath": (base / token / "checkpoint.pt").as_posix(),
                "condition": "BASE",
                "duration_seconds": float(parent["duration_seconds"]),
                "eligibility_unit": {
                    "checkpoint": fraction,
                    "prompt": prompt_id,
                    "root": root_index,
                },
                "eligibility_unit_fields": list(ELIGIBILITY_UNIT_FIELDS),
                "feature_contract": {
                    "axis_evaluator_groups": list(config.axis_evaluator_groups[axis]),
                    "forbidden_sources": list(config.forbidden_feature_sources),
                    "preview_source": PREVIEW_SOURCE,
                    "preview_source_parent_request_sha256": parent_sha,
                    "required_feature_groups": list(config.preview_feature_groups),
                    "root_local_only": True,
                },
                "feature_contract_relpath": (base / token / "feature-contract.json").as_posix(),
                "fold_id": folds[f"{axis}|{prompt_id}"],
                "lane_id": LANE_ID,
                "lane_sequence": lane_sequence,
                "model_id": SA3_MODEL_ID,
                "parent_core_artifact": parent_core_artifact,
                "parent_request_sha256": parent_sha,
                "preview_relpath": (base / token / "preview.wav").as_posix(),
                "preview_source": PREVIEW_SOURCE,
                "preview_source_request_sha256": parent_sha,
                "prompt": parent["prompt"],
                "prompt_id": prompt_id,
                "restart_outcome_label": RESTART_LABEL,
                "resumed_terminal_relpath": (base / token / "resumed-terminal.wav").as_posix(),
                "root_index": root_index,
                "seed": int(parent["seed"]),
                "source_state_request_sha256": source_state["state_request_sha256"],
                "source_state_queue_sha256": config.core_source.initial_state_queue_sha256,
                "tier": INITIAL_TIER,
                "transformer_budget_nfe": config.transformer_budget_nfe,
            }
            unit = _hashed_row(unit, "lane_request_sha256")
            unit_rows.append(unit)
            group_units.append(unit)

            for action in ACTIONS:
                action_sequence += 1
                action_row: dict[str, Any] = {
                    "action": action,
                    "action_sequence": action_sequence,
                    "axis": axis,
                    "checkpoint_fraction": fraction,
                    "fold_id": unit["fold_id"],
                    "lane_request_sha256": unit["lane_request_sha256"],
                    "prompt_id": prompt_id,
                    "root_index": root_index,
                    "tier": INITIAL_TIER,
                }
                if action == "KEEP":
                    action_row.update(
                        {
                            "incremental_cost": "MEASURED_REMAINING_NFE_AND_TIME",
                            "outcome_label": "KEEP_TRUE_ROOT_STATE",
                            "outcome_relpath": unit["resumed_terminal_relpath"],
                            "outcome_source": "ROOT_LOCAL_TRUE_STATE_RESUME",
                            "outcome_source_root_index": root_index,
                        }
                    )
                else:
                    pool_root, rotation_offset = _restart_root(
                        config,
                        prompt_id=prompt_id,
                        fraction=fraction,
                        action=action,
                        root_index=root_index,
                    )
                    condition = "BASE" if action == "RESTART_BASE" else "FIXED"
                    outcome = generation_index.get((prompt_id, condition, pool_root))
                    if outcome is None or outcome.get("axis") != axis:
                        raise StateCaptureConfigurationError("restart pool outcome is absent")
                    action_row.update(
                        {
                            "incremental_cost": "ONE_FULL_NATIVE_GENERATION",
                            "outcome_label": RESTART_LABEL,
                            "outcome_source": "FROZEN_PROMPT_LEVEL_CORE_TERMINAL_POOL",
                            "outcome_source_condition": condition,
                            "outcome_source_core_artifact": core_artifact(outcome),
                            "outcome_source_request_sha256": outcome["request_sha256"],
                            "outcome_source_root_index": pool_root,
                            "restart_pool_root_indices": list(SUPPLEMENTAL_ROOTS),
                            "rotation_direction": "LEFT",
                            "rotation_offset": rotation_offset,
                        }
                    )
                action_rows.append(_hashed_row(action_row, "action_mapping_sha256"))

        group = {
            "authorization_status": LANE_CLOSED_STATUS,
            "axis": axis,
            "capture_call_contract": "ONE_PREFIX_REFERENCE_EXPORTS_ALL_THREE_CHECKPOINTS",
            "checkpoint_completed_steps": list(config.checkpoint_completed_steps),
            "checkpoint_fractions": list(CHECKPOINT_FRACTIONS),
            "condition": "BASE",
            "duration_seconds": float(parent["duration_seconds"]),
            "group_sequence": group_sequence,
            "lane_id": LANE_ID,
            "lane_request_sha256s": [row["lane_request_sha256"] for row in group_units],
            "model_id": SA3_MODEL_ID,
            "parent_core_artifact": parent_core_artifact,
            "parent_request_sha256": parent_sha,
            "prompt": parent["prompt"],
            "prompt_id": prompt_id,
            "reference_terminal_relpath": (
                Path("sa3-state-capture-v2")
                / axis
                / prompt_id
                / f"root-{root_index:02d}"
                / "reference-terminal.wav"
            ).as_posix(),
            "root_index": root_index,
            "seed": int(parent["seed"]),
            "separate_process_resume_required": True,
            "tier": INITIAL_TIER,
        }
        group_rows.append(_hashed_row(group, "group_request_sha256"))

    fold_rows = [
        {"axis": axis, "fold_id": folds[f"{axis}|{prompt_id}"], "prompt_id": prompt_id}
        for axis in AXES
        for prompt_id in sorted(prompt_ids[axis])
    ]
    fold_contract = {
        "assignment": "WHOLE_PROMPT_GROUPED",
        "fold_count": FOLD_COUNT,
        "fold_namespace": config.fold_namespace,
        "rows": fold_rows,
        "schema_version": 1,
    }
    _validate_built_rows(config, unit_rows, group_rows, action_rows, fold_contract)
    return unit_rows, group_rows, action_rows, fold_contract


def _validate_row_hash(row: Mapping[str, Any], field: str) -> None:
    claimed = _require_sha256(row.get(field), field)
    unhashed = dict(row)
    unhashed.pop(field)
    observed = hashlib.sha256(canonical_json(unhashed).encode()).hexdigest()
    if observed != claimed:
        raise StateCaptureConfigurationError(f"{field} mismatch")


def _validate_built_rows(
    config: SA3StateCaptureConfig,
    units: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]],
    folds: Mapping[str, Any],
) -> None:
    if len(units) != EXPECTED_UNITS or len(groups) != EXPECTED_GROUPS:
        raise StateCaptureConfigurationError("state unit/group count drift")
    if len(actions) != EXPECTED_ACTION_ROWS:
        raise StateCaptureConfigurationError("state action-row count drift")
    unit_keys: set[tuple[str, int, float]] = set()
    unit_hashes: set[str] = set()
    axis_unit_counts: Counter[str] = Counter()
    for expected_sequence, row in enumerate(units, start=1):
        _validate_row_hash(row, "lane_request_sha256")
        if row.get("lane_sequence") != expected_sequence:
            raise StateCaptureConfigurationError("state unit sequence is not contiguous")
        if row.get("authorization_status") != LANE_CLOSED_STATUS:
            raise StateCaptureConfigurationError("state unit is not closed")
        if row.get("condition") != "BASE" or row.get("preview_source") != PREVIEW_SOURCE:
            raise StateCaptureConfigurationError("state unit source condition/preview drift")
        if row.get("preview_source_request_sha256") != row.get("parent_request_sha256"):
            raise StateCaptureConfigurationError("state preview is not root-local")
        unit = row.get("eligibility_unit")
        if not isinstance(unit, dict):
            raise StateCaptureConfigurationError("eligibility unit is absent")
        key = (
            str(unit.get("prompt")),
            int(unit.get("root", -1)),
            float(unit.get("checkpoint", -1)),
        )
        if key in unit_keys:
            raise StateCaptureConfigurationError("duplicate (prompt,root,checkpoint) unit")
        unit_keys.add(key)
        unit_hashes.add(str(row["lane_request_sha256"]))
        axis_unit_counts[str(row["axis"])] += 1
        if row.get("feature_contract", {}).get("root_local_only") is not True:
            raise StateCaptureConfigurationError("state feature contract is not root-local")
    if axis_unit_counts != Counter({axis: 144 for axis in AXES}):
        raise StateCaptureConfigurationError("per-axis state unit counts drift")

    group_unit_hashes: list[str] = []
    for expected_sequence, row in enumerate(groups, start=1):
        _validate_row_hash(row, "group_request_sha256")
        if row.get("group_sequence") != expected_sequence:
            raise StateCaptureConfigurationError("prefix group sequence is not contiguous")
        members = row.get("lane_request_sha256s")
        if not isinstance(members, list) or len(members) != 3 or len(set(members)) != 3:
            raise StateCaptureConfigurationError("prefix group must bind three unique units")
        group_unit_hashes.extend(members)
    if Counter(group_unit_hashes) != Counter(unit_hashes):
        raise StateCaptureConfigurationError("prefix groups do not partition state units")

    action_sets: dict[str, set[str]] = defaultdict(set)
    restart_usage: dict[tuple[str, float, str], list[int]] = defaultdict(list)
    for expected_sequence, row in enumerate(actions, start=1):
        _validate_row_hash(row, "action_mapping_sha256")
        if row.get("action_sequence") != expected_sequence:
            raise StateCaptureConfigurationError("action sequence is not contiguous")
        identity = str(row.get("lane_request_sha256"))
        if identity not in unit_hashes:
            raise StateCaptureConfigurationError("action maps an unknown state unit")
        action = str(row.get("action"))
        action_sets[identity].add(action)
        if action.startswith("RESTART_"):
            if row.get("outcome_label") != RESTART_LABEL:
                raise StateCaptureConfigurationError("restart row lost prompt-level label")
            restart_key = (
                str(row["prompt_id"]),
                float(row["checkpoint_fraction"]),
                action,
            )
            restart_usage[restart_key].append(int(row["outcome_source_root_index"]))
    if set(action_sets) != unit_hashes or any(
        value != set(ACTIONS) for value in action_sets.values()
    ):
        raise StateCaptureConfigurationError("every state unit must map all three actions")
    if any(sorted(roots) != list(SUPPLEMENTAL_ROOTS) for roots in restart_usage.values()):
        raise StateCaptureConfigurationError("restart mapping does not use every pool member once")

    fold_rows = folds.get("rows")
    if not isinstance(fold_rows, list) or len(fold_rows) != 36:
        raise StateCaptureConfigurationError("fold contract must contain 36 prompts")
    fold_counts: Counter[tuple[str, int]] = Counter(
        (str(row["axis"]), int(row["fold_id"])) for row in fold_rows
    )
    if any(fold_counts[(axis, fold)] != 2 for axis in AXES for fold in range(FOLD_COUNT)):
        raise StateCaptureConfigurationError("prompt-grouped folds must hold two prompts per axis")

    if config.checkpoint_completed_steps != _half_up_steps(
        CHECKPOINT_FRACTIONS, config.transformer_budget_nfe
    ):
        raise StateCaptureConfigurationError("checkpoint mapping changed during queue build")


def build_sa3_state_capture_bundle(
    config: SA3StateCaptureConfig,
    output_dir: Path,
    *,
    git_commit: str,
) -> dict[str, Any]:
    """Materialize a no-clobber, still-closed queue bundle; invoke no model."""

    if len(git_commit) != 40 or any(
        character not in "0123456789abcdef" for character in git_commit
    ):
        raise StateCaptureConfigurationError("git_commit must be a lowercase 40-hex identity")
    units, groups, actions, folds = _build_rows(config)
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    _fsync_directory(output.parent)
    unit_path = output / "initial-units.jsonl"
    group_path = output / "prefix-groups.jsonl"
    action_path = output / "replicated-action-map.jsonl"
    fold_path = output / "prompt-grouped-folds.json"
    _write_jsonl_exclusive(unit_path, units)
    _write_jsonl_exclusive(group_path, groups)
    _write_jsonl_exclusive(action_path, actions)
    _write_json_exclusive(fold_path, folds)
    manifest = {
        "action_map": {
            "path": str(action_path),
            "row_count": len(actions),
            "sha256": sha256_file(action_path),
        },
        "authorization_status": LANE_CLOSED_STATUS,
        "config_path": str(config.source_path),
        "config_sha256": config.source_sha256,
        "eligibility_unit": list(ELIGIBILITY_UNIT_FIELDS),
        "folds": {"path": str(fold_path), "row_count": 36, "sha256": sha256_file(fold_path)},
        "git_commit": git_commit,
        "lane_id": LANE_ID,
        "model_id": SA3_MODEL_ID,
        "prefix_groups": {
            "path": str(group_path),
            "row_count": len(groups),
            "sha256": sha256_file(group_path),
        },
        "schema_version": 1,
        "state_gpu_budget": {
            "initial_gpu_seconds_cap": config.initial_gpu_seconds_cap,
            "prefix_group_reservation_seconds": config.prefix_group_reservation_seconds,
            "resume_unit_reservation_seconds": config.resume_unit_reservation_seconds,
        },
        "source_core": {
            "generation_queue_sha256": config.core_source.generation_queue_sha256,
            "initial_state_queue_sha256": config.core_source.initial_state_queue_sha256,
            "ledger_sha256": config.core_source.ledger_sha256,
            "run_manifest_sha256": config.core_source.run_manifest_sha256,
        },
        "status": "PREPARED_CLOSED_NO_MODEL_CALLS",
        "tier": INITIAL_TIER,
        "units": {
            "path": str(unit_path),
            "row_count": len(units),
            "sha256": sha256_file(unit_path),
        },
    }
    manifest_path = output / "state-capture-manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    result = dict(manifest)
    result["manifest_path"] = str(manifest_path)
    result["manifest_sha256"] = sha256_file(manifest_path)
    return result


def _load_jsonl(path: Path, identity_field: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not isinstance(row, dict):
            raise StateCaptureConfigurationError(f"JSONL row is not an object: {path}")
        _validate_row_hash(row, identity_field)
        rows.append(row)
    return rows


def load_sa3_state_capture_bundle(
    manifest_path: Path, *, config: SA3StateCaptureConfig
) -> dict[str, Any]:
    """Revalidate every closed queue byte before any later authorization boundary."""

    path = manifest_path.resolve(strict=True)
    manifest = strict_json(path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("lane_id") != LANE_ID
        or manifest.get("model_id") != SA3_MODEL_ID
        or manifest.get("tier") != INITIAL_TIER
        or manifest.get("status") != "PREPARED_CLOSED_NO_MODEL_CALLS"
        or manifest.get("authorization_status") != LANE_CLOSED_STATUS
        or manifest.get("config_sha256") != config.source_sha256
    ):
        raise StateCaptureConfigurationError("state bundle manifest identity/status drift")
    root = path.parent
    loaded: dict[str, Any] = {"manifest": manifest, "manifest_sha256": sha256_file(path)}
    specs = {
        "units": ("lane_request_sha256", EXPECTED_UNITS),
        "prefix_groups": ("group_request_sha256", EXPECTED_GROUPS),
        "action_map": ("action_mapping_sha256", EXPECTED_ACTION_ROWS),
    }
    for name, (identity_field, expected_count) in specs.items():
        record = manifest.get(name)
        if not isinstance(record, dict):
            raise StateCaptureConfigurationError(f"manifest record is absent: {name}")
        candidate = Path(str(record.get("path", ""))).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise StateCaptureConfigurationError(f"bundle {name} escapes manifest root") from exc
        if sha256_file(candidate) != record.get("sha256"):
            raise StateCaptureConfigurationError(f"bundle {name} hash mismatch")
        rows = _load_jsonl(candidate, identity_field)
        if len(rows) != expected_count or record.get("row_count") != expected_count:
            raise StateCaptureConfigurationError(f"bundle {name} row count mismatch")
        loaded[name] = rows
    fold_record = manifest.get("folds")
    if not isinstance(fold_record, dict):
        raise StateCaptureConfigurationError("bundle folds record is absent")
    fold_path = Path(str(fold_record.get("path", ""))).resolve(strict=True)
    try:
        fold_path.relative_to(root)
    except ValueError as exc:
        raise StateCaptureConfigurationError("bundle folds path escapes manifest root") from exc
    if sha256_file(fold_path) != fold_record.get("sha256"):
        raise StateCaptureConfigurationError("bundle fold hash mismatch")
    folds = strict_json(fold_path)
    _validate_built_rows(
        config,
        loaded["units"],
        loaded["prefix_groups"],
        loaded["action_map"],
        folds,
    )
    loaded["folds"] = folds
    return loaded


__all__ = [
    "ACTIONS",
    "AXES",
    "CHECKPOINT_FRACTIONS",
    "EXPECTED_ACTION_ROWS",
    "EXPECTED_GROUPS",
    "EXPECTED_UNITS",
    "INITIAL_ROOTS",
    "LANE_CLOSED_STATUS",
    "LANE_ID",
    "PREVIEW_SOURCE",
    "RESTART_LABEL",
    "SA3_MODEL_ID",
    "SA3StateCaptureConfig",
    "StateCaptureConfigurationError",
    "build_sa3_state_capture_bundle",
    "load_sa3_state_capture_bundle",
    "load_sa3_state_capture_config",
    "sha256_file",
    "strict_json",
]

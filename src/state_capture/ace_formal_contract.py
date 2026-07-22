"""Fail-closed D-0036 and Stage-1 contract for ACE formal initial state work."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_core.queue import canonical_json
from scoring.common import load_json, load_jsonl, require_sha256, sha256_file
from stage1.terminal import Stage1TerminalError, validate_stage1_terminal
from state_capture.ace_queue import MODEL_ID, validate_rows

LANE_ID = "ace-step-v1-formal-initial-state-v2"
CLOSED_STATUS = "CLOSED_PENDING_STAGE1_RESULT_AND_D0036"
RUN_ID = "ace-state-formal-v2-001"
AXES = ("vocal_instrumental", "tempo", "integrity")
GPU_IDS = (4, 5, 6, 7)
MAXIMUM_GROUPS = 144
MAXIMUM_UNITS = 432
MAXIMUM_ACTION_ROWS = 1296
GPU_SECONDS_CAP = 104870.90144741535
GROUP_RESERVATION_SECONDS = 728.2701489403844
PASS = "OUTCOME_SCREEN_PASS"
STOP = "STOP_AXIS_STAGE1"
ENGINEERING_GOVERNANCE_DECISION_ID = "D-0045"
ENGINEERING_GOVERNANCE_ASSIGNMENTS = {
    "ENGINEERING_FAILURES_REPAIRABLE": "YES",
    "WITHIN_ATTEMPT_RETRY": "NO",
    "ENGINEERING_REPAIR_REQUIRES_NEW_RUN_ID": "YES",
    "ENGINEERING_REPAIR_REQUIRES_NEW_CLAIM": "YES",
    "SCIENTIFIC_RERUNS_FOR_WEAK_RESULTS": "NO",
    "FROZEN_SCIENTIFIC_DESIGN_CHANGES_AUTHORIZED": "NO",
    "FAILED_ATTEMPTS_IMMUTABLE": "YES",
    "STOP_AXIS_UNITS_EXECUTABLE": "NO",
}


class AceFormalContractError(RuntimeError):
    """A frozen input, Stage-1 gate, or D-0036 binding is invalid."""


@dataclass(frozen=True)
class AceFormalConfig:
    path: Path
    sha256: str
    repo_root: Path
    raw: Mapping[str, Any]
    run_root: Path
    preflight_config_path: Path
    queue_manifest_path: Path
    units_path: Path
    groups_path: Path
    actions_path: Path
    supplemental_lock_path: Path

    @property
    def heartbeat_interval_seconds(self) -> float:
        return float(self.raw["heartbeat"]["interval_seconds"])

    @property
    def heartbeat_stale_after_seconds(self) -> float:
        return float(self.raw["heartbeat"]["stale_after_seconds"])


@dataclass(frozen=True)
class Stage1Gate:
    result_path: Path
    result_sha256: str
    summary_path: Path
    summary_sha256: str
    survivor_axes: tuple[str, ...]
    stopped_axes: tuple[str, ...]
    result: Mapping[str, Any]
    summary: Mapping[str, Any]


@dataclass(frozen=True)
class D0036Authorization:
    decision_block_sha256: str
    decisions_path: Path
    decisions_sha256: str
    engineering_governance_block_sha256: str
    stage1: Stage1Gate


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AceFormalContractError(f"{label} must be an object")
    return value


def _file_binding(record: Any, label: str, *, repo_root: Path | None = None) -> Path:
    value = _mapping(record, label)
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise AceFormalContractError(f"{label}.path must be nonempty")
    candidate = Path(raw_path)
    path = (
        (repo_root / candidate).resolve(strict=True)
        if repo_root is not None and not candidate.is_absolute()
        else candidate.resolve(strict=True)
    )
    expected = require_sha256(value.get("sha256"), f"{label}.sha256")
    if not path.is_file() or sha256_file(path) != expected:
        raise AceFormalContractError(f"{label} SHA-256 binding drifted")
    return path


def load_formal_config(path: Path, *, repo_root: Path) -> AceFormalConfig:
    """Validate the inert formal config without resolving D-0036 or touching CUDA."""

    root = repo_root.resolve(strict=True)
    source = path.resolve(strict=True)
    raw = load_json(source)
    if (
        raw.get("schema_version") != 1
        or raw.get("lane_id") != LANE_ID
        or raw.get("model_id") != MODEL_ID
        or raw.get("execution_status") != CLOSED_STATUS
        or raw.get("required_decision_id") != "D-0036"
        or raw.get("supplemental_queue_status") != "LOCKED_NOT_AUTHORIZED"
    ):
        raise AceFormalContractError("ACE formal config identity/closed boundary drifted")
    budget = _mapping(raw.get("budget"), "budget")
    if budget != {
        "group_reservation_gpu_seconds": GROUP_RESERVATION_SECONDS,
        "initial_gpu_seconds_cap": GPU_SECONDS_CAP,
        "maximum_groups": MAXIMUM_GROUPS,
        "maximum_model_calls": 576,
        "no_automatic_retry": True,
    } or not math.isclose(
        GROUP_RESERVATION_SECONDS * MAXIMUM_GROUPS,
        GPU_SECONDS_CAP,
        rel_tol=0,
        abs_tol=1e-8,
    ):
        raise AceFormalContractError("ACE formal hard-cap contract drifted")
    placement = _mapping(raw.get("placement"), "placement")
    if (
        placement.get("allowed_nodes") != ["an12"]
        or placement.get("allowed_physical_gpu_ids") != list(GPU_IDS)
        or placement.get("maximum_parallel_replicas") != 4
        or placement.get("tensor_parallel_width") != 1
    ):
        raise AceFormalContractError("ACE formal placement must be four independent an12 TP1")
    heartbeat = _mapping(raw.get("heartbeat"), "heartbeat")
    if heartbeat != {"interval_seconds": 30, "stale_after_seconds": 180}:
        raise AceFormalContractError("ACE formal heartbeat contract drifted")
    run = _mapping(raw.get("run"), "run")
    if run.get("run_id") != RUN_ID:
        raise AceFormalContractError("ACE formal run identity drifted")
    run_root = Path(str(run.get("run_root"))).resolve()
    if run_root == Path("/") or len(run_root.parts) < 4:
        raise AceFormalContractError("ACE formal run root is unsafe")
    for name, record in _mapping(raw.get("frozen_sources"), "frozen_sources").items():
        _file_binding(record, f"frozen_sources.{name}", repo_root=root)
    engine = _mapping(raw.get("engine"), "engine")
    if (
        engine.get("formal_factory") != "state_capture.ace_engine:formal_engine_factory"
        or engine.get("resume_child_module") != "state_capture.ace_child"
    ):
        raise AceFormalContractError("ACE formal engine surface drifted")
    preflight = _file_binding(
        engine.get("preflight_config"), "engine.preflight_config", repo_root=root
    )
    queue = _mapping(raw.get("source_queue"), "source_queue")
    manifest = _file_binding(queue.get("manifest"), "source_queue.manifest")
    units = _file_binding(queue.get("units"), "source_queue.units")
    groups = _file_binding(queue.get("prefix_groups"), "source_queue.prefix_groups")
    actions = _file_binding(queue.get("action_map"), "source_queue.action_map")
    supplemental = _file_binding(queue.get("supplemental_lock"), "source_queue.supplemental_lock")
    stage1 = _mapping(raw.get("stage1"), "stage1")
    if (
        stage1.get("gate_config_path") != "configs/stage1_outcome_gates_v2.json"
        or stage1.get("pass_label") != PASS
        or stage1.get("stop_label") != STOP
    ):
        raise AceFormalContractError("ACE formal Stage-1 contract drifted")
    if (
        queue["manifest"].get("sha256")
        != "62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a"
        or queue["units"].get("sha256")
        != "9218cd0ce81bda171230a4bed40c75c67ade08cd359a4da4b569a8365155923f"
    ):
        raise AceFormalContractError("D-0033 fresh queue identities drifted")
    lock = load_json(supplemental)
    if lock.get("authorized") is not False or not str(lock.get("status", "")).startswith(
        "LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
    ):
        raise AceFormalContractError("supplemental queue is not locked")
    package = raw.get("package_files")
    if not isinstance(package, list) or len(package) != len(set(package)) or not package:
        raise AceFormalContractError("formal package file list is invalid")
    return AceFormalConfig(
        path=source,
        sha256=sha256_file(source),
        repo_root=root,
        raw=raw,
        run_root=run_root,
        preflight_config_path=preflight,
        queue_manifest_path=manifest,
        units_path=units,
        groups_path=groups,
        actions_path=actions,
        supplemental_lock_path=supplemental,
    )


def load_source_bundle(config: AceFormalConfig) -> dict[str, Any]:
    """Load and revalidate all exact D-0033 queue rows."""

    manifest = load_json(config.queue_manifest_path)
    units = load_jsonl(config.units_path)
    groups = load_jsonl(config.groups_path)
    actions = load_jsonl(config.actions_path)
    folds_path = Path(str(manifest["folds"]["path"])).resolve(strict=True)
    if sha256_file(folds_path) != manifest["folds"]["sha256"]:
        raise AceFormalContractError("fresh queue fold binding drifted")
    folds = load_json(folds_path)
    validate_rows(units, groups, actions, folds)
    if (len(units), len(groups), len(actions)) != (
        MAXIMUM_UNITS,
        MAXIMUM_GROUPS,
        MAXIMUM_ACTION_ROWS,
    ):
        raise AceFormalContractError("fresh queue row counts drifted")
    if (
        manifest.get("status") != "PREPARED_AUTHORIZED_QUEUE_ONLY_NO_MODEL_CALLS"
        or manifest.get("source_queue_derivation") != "FRESH_ACE_CORE_GENERATION_QUEUE"
        or manifest.get("execution_started") is not False
        or manifest.get("model_calls") != 0
    ):
        raise AceFormalContractError("D-0033 manifest is not the untouched fresh queue")
    return {
        "actions": actions,
        "folds": folds,
        "groups": groups,
        "manifest": manifest,
        "units": units,
    }


def validate_stage1_gate(
    config: AceFormalConfig,
    *,
    result_path: Path,
    result_sha256: str,
    summary_path: Path,
    summary_sha256: str,
    bundle: Mapping[str, Any],
) -> Stage1Gate:
    """Return only ACE survivor axes after exact result/cancellation validation."""

    expected_result = Path(config.raw["stage1"]["expected_result_path"]).resolve()
    expected_summary = Path(config.raw["stage1"]["expected_summary_path"]).resolve()
    if result_path.resolve() != expected_result or summary_path.resolve() != expected_summary:
        raise AceFormalContractError("D-0036 Stage-1 paths differ from the expected run root")
    raw_gate_config = config.raw["stage1"]["gate_config_path"]
    gate_config_path = Path(str(raw_gate_config))
    if not gate_config_path.is_absolute():
        gate_config_path = config.repo_root / gate_config_path
    try:
        terminal = validate_stage1_terminal(
            result_path,
            summary_path,
            expected_config_path=gate_config_path,
            expected_result_sha256=result_sha256,
            expected_summary_sha256=summary_sha256,
        )
    except Stage1TerminalError as exc:
        raise AceFormalContractError(f"Stage-1 terminal validation failed: {exc}") from exc
    result_path = terminal.result_path
    summary_path = terminal.summary_path
    result_sha256 = terminal.result_sha256
    summary_sha256 = terminal.summary_sha256
    result = terminal.result
    rows = list(terminal.rows)
    ace_rows = [row for row in rows if row["backbone"] == "ACE-Step v1"]
    survivor_axes = tuple(
        axis
        for axis in AXES
        if next(row for row in ace_rows if row["axis"] == axis)["verdict"] == PASS
    )
    stopped_axes = tuple(axis for axis in AXES if axis not in survivor_axes)
    summary = terminal.summary
    cancellations = list(terminal.cancellations)
    units = bundle["units"]
    stopped_identities = {
        (
            unit["axis"],
            unit["eligibility_unit"]["prompt"],
            unit["eligibility_unit"]["root"],
            unit["eligibility_unit"]["checkpoint"],
        )
        for unit in units
        if unit["axis"] in stopped_axes
    }
    ace_cancelled = {
        (
            row.get("axis"),
            _mapping(row.get("eligibility_unit"), "cancelled eligibility_unit").get("prompt"),
            row["eligibility_unit"].get("root"),
            row["eligibility_unit"].get("checkpoint"),
        )
        for row in cancellations
        if row.get("backbone") == "ACE-Step v1"
    }
    if ace_cancelled != stopped_identities:
        raise AceFormalContractError("ACE STOP units do not exactly equal the cancellation chain")
    if any(
        row.get("axis") in survivor_axes
        for row in cancellations
        if row.get("backbone") == "ACE-Step v1"
    ):
        raise AceFormalContractError("Stage-1 chain cancels an ACE survivor unit")
    return Stage1Gate(
        result_path=result_path,
        result_sha256=result_sha256,
        summary_path=summary_path,
        summary_sha256=summary_sha256,
        survivor_axes=survivor_axes,
        stopped_axes=stopped_axes,
        result=result,
        summary=summary,
    )


def _decision_block(path: Path, decision_id: str) -> str:
    text = path.resolve(strict=True).read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^##\s+{re.escape(decision_id)}\b.*?(?=^##\s+D-\d+\b|\Z)", text)
    if match is None:
        raise AceFormalContractError(f"decision block is absent: {decision_id}")
    return match.group(0)


def verify_engineering_governance(decisions_path: Path) -> str:
    """Require the append-only D-0045 attempt-repair correction."""

    path = decisions_path.resolve(strict=True)
    text = path.read_text(encoding="utf-8")
    block = _decision_block(path, ENGINEERING_GOVERNANCE_DECISION_ID)
    assignments: dict[str, str] = {}
    for key, value in re.findall(r"`?([A-Z0-9_]+)\s*=\s*([^`\n]+?)`?(?=\n|$)", block):
        if key in assignments:
            raise AceFormalContractError(f"duplicate D-0045 assignment: {key}")
        assignments[key] = value.strip()
    missing = [
        key
        for key, value in ENGINEERING_GOVERNANCE_ASSIGNMENTS.items()
        if assignments.get(key) != value
    ]
    if missing:
        raise AceFormalContractError(f"D-0045 lacks exact engineering assignments: {missing}")
    d0036 = text.find("## D-0036")
    d0045 = text.find("## D-0045")
    if d0036 < 0 or d0045 <= d0036:
        raise AceFormalContractError("D-0045 must append after the D-0036 scientific opening")
    return hashlib.sha256(block.encode()).hexdigest()


def verify_d0036(
    config: AceFormalConfig,
    *,
    decisions_path: Path,
    bundle: Mapping[str, Any],
) -> D0036Authorization:
    """Require exact survivor-only, STOP-deny, queue, cap and Stage-1 bindings."""

    block = _decision_block(decisions_path, "D-0036")
    engineering_governance_block_sha256 = verify_engineering_governance(decisions_path)
    assignments: dict[str, str] = {}
    for key, value in re.findall(r"`?([A-Z0-9_]+)\s*=\s*([^`\n]+?)`?(?=\n|$)", block):
        if key in assignments:
            raise AceFormalContractError(f"duplicate D-0036 assignment: {key}")
        assignments[key] = value.strip()
    expected_result = str(Path(config.raw["stage1"]["expected_result_path"]).resolve())
    expected_summary = str(Path(config.raw["stage1"]["expected_summary_path"]).resolve())
    required_static = {
        "ACE_STATE_FORMAL_INITIAL_AUTHORIZED": "YES",
        "ACE_STATE_FORMAL_SURVIVORS_ONLY": "YES",
        "ACE_STATE_FORMAL_STOP_UNITS_PROHIBITED": "EXECUTE,SCORE",
        "ACE_STATE_FORMAL_CONFIG": "configs/ace_state_formal_v2.json",
        "ACE_STATE_FORMAL_CONFIG_SHA256": config.sha256,
        "STAGE1_RESULT_PATH": expected_result,
        "STAGE1_CANCELLATION_SUMMARY_PATH": expected_summary,
        "STAGE1_RUNTIME_SHA256_BINDING": "VERIFIED_AND_RECORDED_AT_LAUNCH",
        "ACE_STATE_SUPPLEMENTAL_AUTHORIZED": "NO",
        "NO_AUTOMATIC_RETRY": "YES",
        "ACE_STATE_FORMAL_PLACEMENT": "an12:[4,5,6,7]",
        "ACE_STATE_FORMAL_MAX_PARALLEL_REPLICAS": "4",
        "ACE_STATE_FORMAL_INITIAL_GPU_SECONDS_CAP": json.dumps(GPU_SECONDS_CAP),
        "ACE_STATE_FORMAL_FRESH_QUEUE_MANIFEST_SHA256": (
            "62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a"
        ),
        "ACE_STATE_FORMAL_INITIAL_UNITS_SHA256": (
            "9218cd0ce81bda171230a4bed40c75c67ade08cd359a4da4b569a8365155923f"
        ),
    }
    missing = [key for key, value in required_static.items() if assignments.get(key) != value]
    if missing:
        raise AceFormalContractError(f"D-0036 lacks exact formal assignments: {missing}")
    forbidden_future_hashes = {
        "STAGE1_RESULT_SHA256",
        "STAGE1_CANCELLATION_SUMMARY_SHA256",
    }
    if forbidden_future_hashes.intersection(assignments) or re.search(
        r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE|UNSET)\b", block, re.IGNORECASE
    ):
        raise AceFormalContractError("D-0036 must use the prospective Stage-1 runtime-hash binding")
    result_path = Path(assignments["STAGE1_RESULT_PATH"])
    summary_path = Path(assignments["STAGE1_CANCELLATION_SUMMARY_PATH"])
    stage1 = validate_stage1_gate(
        config,
        result_path=result_path,
        result_sha256=sha256_file(result_path),
        summary_path=summary_path,
        summary_sha256=sha256_file(summary_path),
        bundle=bundle,
    )
    return D0036Authorization(
        decision_block_sha256=hashlib.sha256(block.encode()).hexdigest(),
        decisions_path=decisions_path.resolve(strict=True),
        decisions_sha256=sha256_file(decisions_path),
        engineering_governance_block_sha256=engineering_governance_block_sha256,
        stage1=stage1,
    )


def survivor_bundle(bundle: Mapping[str, Any], gate: Stage1Gate) -> dict[str, Any]:
    """Filter without rewriting any row; STOP rows are absent from every surface."""

    groups = [row for row in bundle["groups"] if row["axis"] in gate.survivor_axes]
    units = [row for row in bundle["units"] if row["axis"] in gate.survivor_axes]
    actions = [row for row in bundle["actions"] if row["axis"] in gate.survivor_axes]
    expected_groups = 48 * len(gate.survivor_axes)
    if (
        len(groups) != expected_groups
        or len(units) != expected_groups * 3
        or len(actions) != expected_groups * 9
    ):
        raise AceFormalContractError("survivor filtering changed frozen per-axis row counts")
    survivor_unit_ids = {row["lane_request_sha256"] for row in units}
    if any(
        identity not in survivor_unit_ids
        for group in groups
        for identity in group["lane_request_sha256s"]
    ):
        raise AceFormalContractError("survivor group references a STOP unit")
    if any(row["lane_request_sha256"] not in survivor_unit_ids for row in actions):
        raise AceFormalContractError("survivor action map references a STOP unit")
    return {"actions": actions, "groups": groups, "units": units}


def package_hashes(config: AceFormalConfig) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in config.raw["package_files"]:
        path = (config.repo_root / relative).resolve(strict=True)
        try:
            path.relative_to(config.repo_root)
        except ValueError as exc:
            raise AceFormalContractError("formal package path escapes repository") from exc
        result[relative] = sha256_file(path)
    return result


def validate_formal_engine_claim(path: Path) -> dict[str, Any]:
    """Validate a distinct formal group claim consumed by parent and child engines."""

    claim = load_json(path.resolve(strict=True))
    claimed = claim.get("claim_identity_sha256")
    unhashed = dict(claim)
    unhashed.pop("claim_identity_sha256", None)
    if claimed != hashlib.sha256(canonical_json(unhashed).encode()).hexdigest():
        raise AceFormalContractError("formal engine claim identity mismatch")
    if (
        claim.get("claim_type") != "ACE_FORMAL_INITIAL_SURVIVOR_GROUP"
        or claim.get("model_id") != MODEL_ID
        or claim.get("retry_allowed") is not False
        or claim.get("stage1_verdict") != PASS
        or claim.get("physical_gpu_id") not in GPU_IDS
        or claim.get("node") != "an12"
    ):
        raise AceFormalContractError("formal engine claim boundary drifted")
    for key in (
        "config_sha256",
        "decision_block_sha256",
        "engineering_governance_block_sha256",
        "group_request_sha256",
        "preflight_config_sha256",
        "stage1_result_sha256",
        "stage1_summary_sha256",
    ):
        require_sha256(claim.get(key), f"formal claim {key}")
    members = claim.get("lane_request_sha256s")
    if (
        not isinstance(members, list)
        or len(members) != 3
        or len(set(members)) != 3
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in members
        )
    ):
        raise AceFormalContractError("formal group claim lacks three exact resume members")
    return claim


def validate_formal_call_claim(
    path: Path,
    *,
    expected_kind: str | None = None,
    expected_request_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the distinct claim passed into one backend model invocation."""

    claim = load_json(path.resolve(strict=True))
    claimed = claim.get("claim_identity_sha256")
    unhashed = dict(claim)
    unhashed.pop("claim_identity_sha256", None)
    if claimed != hashlib.sha256(canonical_json(unhashed).encode()).hexdigest():
        raise AceFormalContractError("formal per-call claim identity mismatch")
    if (
        claim.get("claim_type") != "ACE_FORMAL_INITIAL_MODEL_CALL"
        or claim.get("call_kind") not in {"PREFIX_GROUP", "RESUME_UNIT"}
        or claim.get("model_id") != MODEL_ID
        or claim.get("retry_allowed") is not False
        or claim.get("physical_gpu_id") not in GPU_IDS
        or claim.get("replica_index") not in range(4)
    ):
        raise AceFormalContractError("formal per-call claim boundary drifted")
    for key in (
        "claim_identity_sha256",
        "engineering_governance_block_sha256",
        "group_claim_sha256",
        "group_request_sha256",
        "request_sha256",
        "stage1_result_sha256",
    ):
        require_sha256(claim.get(key), f"formal per-call claim {key}")
    if expected_kind is not None and claim["call_kind"] != expected_kind:
        raise AceFormalContractError("formal per-call kind differs from backend invocation")
    if expected_request_sha256 is not None and claim["request_sha256"] != expected_request_sha256:
        raise AceFormalContractError("formal per-call request differs from backend invocation")
    return claim


def validate_formal_backend_invocation(
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically reject a backend invocation after any peer terminal failure."""

    group_path = Path(str(context.get("formal_claim_path"))).resolve(strict=True)
    call_path = Path(str(context.get("formal_call_claim_path"))).resolve(strict=True)
    group = validate_formal_engine_claim(group_path)
    call = validate_formal_call_claim(
        call_path,
        expected_kind=str(context.get("formal_call_kind")),
        expected_request_sha256=str(context.get("formal_request_sha256")),
    )
    if (
        sha256_file(group_path) != context.get("formal_claim_sha256")
        or sha256_file(call_path) != context.get("formal_call_claim_sha256")
        or call["group_claim_sha256"] != sha256_file(group_path)
        or call["engineering_governance_block_sha256"]
        != group["engineering_governance_block_sha256"]
        or call["group_request_sha256"] != group["group_request_sha256"]
        or call["stage1_result_sha256"] != group["stage1_result_sha256"]
        or call["physical_gpu_id"] != group["physical_gpu_id"]
        or call["replica_index"] != group["replica_index"]
        or (
            call["call_kind"] == "PREFIX_GROUP"
            and call["request_sha256"] != group["group_request_sha256"]
        )
        or (
            call["call_kind"] == "RESUME_UNIT"
            and call["request_sha256"] not in group["lane_request_sha256s"]
        )
    ):
        raise AceFormalContractError("formal backend group/call binding drifted")
    claim_root = call_path.parent.parent
    run_dir = Path(str(context.get("run_dir"))).resolve(strict=True)
    lock_path = Path(str(context.get("formal_coordination_lock_path"))).resolve(strict=True)
    latch_path = Path(str(context.get("formal_failure_latch_path"))).resolve()
    expected_call_dir = (
        "prefix-call-claims" if call["call_kind"] == "PREFIX_GROUP" else "resume-call-claims"
    )
    if (
        claim_root != (run_dir / "control" / "shared-formal-claims").resolve(strict=True)
        or group_path
        != (claim_root / "group-claims" / f"{group['group_request_sha256']}.json").resolve(
            strict=True
        )
        or call_path
        != (claim_root / expected_call_dir / f"{call['request_sha256']}.json").resolve(strict=True)
        or lock_path != (claim_root / "reservation.lock").resolve(strict=True)
        or latch_path != (claim_root.parent / "formal-terminal-failure.json").resolve()
    ):
        raise AceFormalContractError("formal backend coordination paths drifted")
    with lock_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            if latch_path.exists():
                raise AceFormalContractError(
                    "formal backend invocation is closed by peer FAILED_STOPPED"
                )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return group, call


__all__ = [
    "AceFormalConfig",
    "AceFormalContractError",
    "D0036Authorization",
    "GPU_IDS",
    "GPU_SECONDS_CAP",
    "GROUP_RESERVATION_SECONDS",
    "LANE_ID",
    "PASS",
    "RUN_ID",
    "STOP",
    "Stage1Gate",
    "load_formal_config",
    "load_source_bundle",
    "package_hashes",
    "survivor_bundle",
    "validate_formal_engine_claim",
    "validate_formal_backend_invocation",
    "validate_formal_call_claim",
    "validate_stage1_gate",
    "verify_d0036",
    "verify_engineering_governance",
]

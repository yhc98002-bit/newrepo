"""CPU-only ACE-Step v1 Section-11 queue materialization.

The ordinary ACE core run accidentally contains a closed state queue copied
from the SA3 model.  This module treats that queue as an explicitly rejected
artifact and derives fresh ACE units from the completed ACE generation queue.
It cannot prepare an opened package until both the sole ACE state preflight is
terminal PASS and D-0033 binds that exact terminal and this exact config.

Nothing in this module imports a model runtime, initializes CUDA, or generates
audio.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_core.ledger import validate_ledger
from benchmark_core.queue import canonical_json, load_queue

MODEL_ID = "ACE-Step/ACE-Step-v1-3.5B"
LANE_ID = "ace-step-v1-state-capture-v2"
TIER = "INITIAL"
CONFIG_CLOSED = "CLOSED_PENDING_SOLE_PREFLIGHT_PASS_AND_D0033"
PACKAGE_AUTHORIZED = "AUTHORIZED_SEPARATE_ACE_STATE_CAPTURE_INITIAL"
PACKAGE_STATUS = "PREPARED_AUTHORIZED_QUEUE_ONLY_NO_MODEL_CALLS"
CAPTURE_MODE = "SEPARATE_LEDGERED_STATE_CAPTURE_QUEUE"
PREVIEW_SOURCE = "ONLY_THE_SAME_UNITS_ROOT_LOCAL_PRE_ACTION_DECODED_PREVIEW"
RESTART_LABEL = "RESTART_POOL_SHARED_AT_PROMPT_LEVEL"
AXES = ("vocal_instrumental", "tempo", "integrity")
FRACTIONS = (0.25, 0.5, 0.75)
INITIAL_ROOTS = (0, 1, 2, 3)
RESTART_ROOTS = (4, 5, 6, 7)
ACTIONS = ("KEEP", "RESTART_BASE", "RESTART_FIXED")
CHECKPOINT_TRANSITIONS = (9, 15, 20)
CHECKPOINT_NFE = (11, 23, 33)
EXPECTED_CORE_ROWS = 1536
EXPECTED_LEDGER_ROWS = EXPECTED_CORE_ROWS * 3
EXPECTED_PROMPTS_PER_AXIS = 12
EXPECTED_PROMPTS = len(AXES) * EXPECTED_PROMPTS_PER_AXIS
EXPECTED_GROUPS = EXPECTED_PROMPTS * len(INITIAL_ROOTS)
EXPECTED_UNITS = EXPECTED_GROUPS * len(FRACTIONS)
EXPECTED_ACTION_ROWS = EXPECTED_UNITS * len(ACTIONS)
FOLD_COUNT = 6
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class AceStateQueueError(RuntimeError):
    """A frozen input, PASS gate, decision assignment, or queue row drifted."""


@dataclass(frozen=True)
class QueueConfig:
    """Validated static config.  A value here never itself opens execution."""

    path: Path
    sha256: str
    repo_root: Path
    raw: dict[str, Any]
    statistics_path: Path
    generation_queue_path: Path
    generation_queue_manifest_path: Path
    ledger_path: Path
    run_manifest_path: Path
    artifact_root: Path
    legacy_state_queue_path: Path
    preflight_claim_root: Path
    preflight_terminal_path: Path
    run_root: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AceStateQueueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AceStateQueueError(f"non-finite JSON value: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AceStateQueueError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AceStateQueueError(f"JSON root must be an object: {path}")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AceStateQueueError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AceStateQueueError(f"{label} must be a non-empty string")
    return value


def _sha256(value: Any, label: str) -> str:
    text = _string(value, label)
    if SHA256_PATTERN.fullmatch(text) is None:
        raise AceStateQueueError(f"{label} must be a lowercase SHA-256")
    return text


def _repo_file(repo_root: Path, value: Any, label: str) -> Path:
    candidate = Path(_string(value, label))
    path = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    if not path.is_file():
        raise AceStateQueueError(f"{label} is not a file: {path}")
    return path


def _external_file(value: Any, label: str) -> Path:
    path = Path(_string(value, label)).resolve(strict=True)
    if not path.is_file():
        raise AceStateQueueError(f"{label} is not a regular file: {path}")
    return path


def _external_dir(value: Any, label: str, *, must_exist: bool = True) -> Path:
    path = Path(_string(value, label)).resolve(strict=must_exist)
    if must_exist and not path.is_dir():
        raise AceStateQueueError(f"{label} is not a directory: {path}")
    if path == Path("/") or len(path.parts) < 4:
        raise AceStateQueueError(f"{label} is an unsafe broad path: {path}")
    return path


def _bind_file(path: Path, expected: Any, label: str) -> str:
    frozen = _sha256(expected, label)
    observed = sha256_file(path)
    if observed != frozen:
        raise AceStateQueueError(f"{label} drifted: {observed} != {frozen}")
    return observed


def load_queue_config(path: Path, *, repo_root: Path) -> QueueConfig:
    """Validate static inputs while keeping both opening gates closed."""

    root = repo_root.resolve(strict=True)
    source = path.resolve(strict=True)
    raw = strict_json(source)
    if (
        raw.get("schema_version") != 1
        or raw.get("lane_id") != LANE_ID
        or raw.get("model_id") != MODEL_ID
        or raw.get("tier") != TIER
        or raw.get("execution_status") != CONFIG_CLOSED
    ):
        raise AceStateQueueError("ACE state config identity or closed status drifted")

    design = _object(raw.get("frozen_design"), "frozen_design")
    expected_design = {
        "actions": list(ACTIONS),
        "axes": list(AXES),
        "capture_mode": CAPTURE_MODE,
        "condition": "BASE",
        "eligibility_unit": ["prompt", "root", "checkpoint"],
        "expected_action_rows": EXPECTED_ACTION_ROWS,
        "expected_initial_units": EXPECTED_UNITS,
        "expected_prefix_groups": EXPECTED_GROUPS,
        "fold_count": FOLD_COUNT,
        "initial_root_indices": list(INITIAL_ROOTS),
        "preview_source": PREVIEW_SOURCE,
        "prompt_count_per_axis": EXPECTED_PROMPTS_PER_AXIS,
        "restart_outcome_label": RESTART_LABEL,
        "restart_pool_root_indices": list(RESTART_ROOTS),
        "source_queue_rule": (
            "DERIVE_FRESH_FROM_THE_COMPLETED_ACE_CORE_GENERATION_QUEUE; "
            "NEVER_REUSE_THE_SA3_DERIVED_STATE_QUEUE"
        ),
        "supplemental_root_indices": list(RESTART_ROOTS),
        "tier": TIER,
    }
    if design != expected_design:
        raise AceStateQueueError("frozen ACE Section-11 design drifted")

    checkpoint = _object(raw.get("checkpoint_mapping"), "checkpoint_mapping")
    if (
        checkpoint.get("capture_fractions") != list(FRACTIONS)
        or checkpoint.get("completed_scheduler_transitions") != list(CHECKPOINT_TRANSITIONS)
        or checkpoint.get("cumulative_transformer_nfe") != list(CHECKPOINT_NFE)
        or checkpoint.get("total_scheduler_transitions") != 30
        or checkpoint.get("total_transformer_nfe") != 45
    ):
        raise AceStateQueueError("ACE checkpoint mapping drifted")

    mapping = _object(raw.get("mapping"), "mapping")
    if mapping != {
        "checkpoint_token_rule": "SHORTEST_DECIMAL_JSON_NUMBER",
        "fold_namespace": "benchmark-v2-eligibility-folds-20260720",
        "restart_namespace": "benchmark-v2-restart-map-20260720",
        "rotation_direction": "LEFT",
    }:
        raise AceStateQueueError("fold/restart mapping contract drifted")

    authority = _object(raw.get("authorization_contract"), "authorization_contract")
    if (
        authority.get("automatic_retry_allowed") is not False
        or authority.get("execution_authorized_by_this_config_alone") is not False
        or authority.get("required_decision_id") != "D-0033"
        or authority.get("supplemental_queue_status")
        != (
            "LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED_AND_A_SEPARATE_"
            "AMENDMENT_OPENS_THE_SINGLE_DOUBLING"
        )
    ):
        raise AceStateQueueError("authorization boundary drifted")
    sole = _object(authority.get("sole_preflight_terminal"), "sole_preflight_terminal")
    if (
        sole.get("run_id") != "ace-state-preflight-v2-001"
        or sole.get("attempt_id") != "ace-state-preflight-v2-attempt-001"
        or sole.get("status_required") != "PASS"
    ):
        raise AceStateQueueError("sole preflight identity drifted")

    frozen_sources = _object(raw.get("frozen_sources"), "frozen_sources")
    bound_sources: dict[str, Path] = {}
    for name in ("benchmark_prereg_v2", "statistics_v2", "incremental_core_config"):
        record = _object(frozen_sources.get(name), f"frozen_sources.{name}")
        source_path = _repo_file(root, record.get("path"), f"frozen_sources.{name}.path")
        _bind_file(source_path, record.get("sha256"), f"frozen_sources.{name}.sha256")
        bound_sources[name] = source_path

    core = _object(raw.get("source_core_run"), "source_core_run")
    queue_record = _object(core.get("generation_queue"), "source_core_run.generation_queue")
    queue_path = _external_file(queue_record.get("path"), "generation queue")
    _bind_file(queue_path, queue_record.get("sha256"), "generation queue sha256")
    if queue_record.get("row_count") != EXPECTED_CORE_ROWS:
        raise AceStateQueueError("generation queue row-count binding drifted")
    queue_manifest_record = _object(
        core.get("generation_queue_manifest"), "source_core_run.generation_queue_manifest"
    )
    queue_manifest_path = _external_file(
        queue_manifest_record.get("path"), "generation queue manifest"
    )
    _bind_file(
        queue_manifest_path,
        queue_manifest_record.get("sha256"),
        "generation queue manifest sha256",
    )
    ledger_record = _object(core.get("ledger"), "source_core_run.ledger")
    ledger_path = _external_file(ledger_record.get("path"), "core ledger")
    _bind_file(ledger_path, ledger_record.get("sha256"), "core ledger sha256")
    if ledger_record.get("row_count") != EXPECTED_LEDGER_ROWS:
        raise AceStateQueueError("core ledger row-count binding drifted")
    run_manifest_record = _object(core.get("run_manifest"), "source_core_run.run_manifest")
    run_manifest_path = _external_file(run_manifest_record.get("path"), "core run manifest")
    _bind_file(run_manifest_path, run_manifest_record.get("sha256"), "run manifest sha256")
    artifact_root = _external_dir(core.get("artifact_root"), "core artifact root")

    legacy = _object(core.get("legacy_initial_state_queue"), "legacy_initial_state_queue")
    legacy_path = _external_file(legacy.get("path"), "legacy initial state queue")
    _bind_file(legacy_path, legacy.get("sha256"), "legacy initial state queue sha256")
    if legacy.get("disposition") != "REJECT_MODEL_ID_IS_SA3_NOT_ACE":
        raise AceStateQueueError("legacy SA3-derived queue is not explicitly rejected")
    first_legacy = json.loads(legacy_path.read_text(encoding="utf-8").splitlines()[0])
    if first_legacy.get("model_id") == MODEL_ID:
        raise AceStateQueueError("legacy queue unexpectedly claims ACE; explicit audit required")

    claim_root = _external_dir(sole.get("claim_root"), "preflight claim root", must_exist=False)
    terminal_path = Path(_string(sole.get("expected_path"), "preflight terminal path")).resolve()
    if terminal_path.parent != claim_root or terminal_path.name != (
        "ace-state-preflight-v2-one-attempt.terminal.json"
    ):
        raise AceStateQueueError("preflight terminal path is not the sole fixed location")
    output = _object(raw.get("output"), "output")
    run_root = _external_dir(output.get("run_root"), "state run root", must_exist=False)

    placement = _object(raw.get("placement"), "placement")
    if (
        placement.get("allowed_nodes") != ["an12"]
        or placement.get("allowed_physical_gpu_ids") != [4, 5, 6, 7]
        or placement.get("tp_width") != 1
        or placement.get("replica_count_per_worker") != 1
        or placement.get("maximum_parallel_replicas") != 4
    ):
        raise AceStateQueueError("an12 four-GPU TP1 placement contract drifted")

    return QueueConfig(
        path=source,
        sha256=sha256_file(source),
        repo_root=root,
        raw=raw,
        statistics_path=bound_sources["statistics_v2"],
        generation_queue_path=queue_path,
        generation_queue_manifest_path=queue_manifest_path,
        ledger_path=ledger_path,
        run_manifest_path=run_manifest_path,
        artifact_root=artifact_root,
        legacy_state_queue_path=legacy_path,
        preflight_claim_root=claim_root,
        preflight_terminal_path=terminal_path,
        run_root=run_root,
    )


def _json_identity(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _validate_identity(record: Mapping[str, Any], field: str, label: str) -> None:
    claimed = record.get(field)
    unhashed = dict(record)
    unhashed.pop(field, None)
    if claimed != _json_identity(unhashed):
        raise AceStateQueueError(f"{label} identity hash mismatch")


def validate_preflight_pass(
    config: QueueConfig,
    *,
    terminal_path: Path,
    expected_terminal_sha256: str,
) -> dict[str, Any]:
    """Validate the unique no-retry PASS terminal and its result hash chain."""

    path = terminal_path.resolve(strict=True)
    if path != config.preflight_terminal_path:
        raise AceStateQueueError("provided preflight terminal is not the frozen sole path")
    supplied_sha = _sha256(expected_terminal_sha256, "preflight terminal sha256")
    if sha256_file(path) != supplied_sha:
        raise AceStateQueueError("preflight terminal bytes differ from the supplied PASS hash")
    terminals = sorted(config.preflight_claim_root.glob("*.terminal.json"))
    if terminals != [path]:
        raise AceStateQueueError("the claim root does not contain exactly the sole terminal")

    terminal = strict_json(path)
    _validate_identity(terminal, "terminal_identity_sha256", "preflight terminal")
    authority = config.raw["authorization_contract"]["sole_preflight_terminal"]
    payload = _object(terminal.get("payload"), "preflight terminal payload")
    if (
        terminal.get("schema_version") != 1
        or terminal.get("run_id") != authority["run_id"]
        or terminal.get("attempt_id") != authority["attempt_id"]
        or terminal.get("status") != "PASS"
        or terminal.get("retry_allowed") is not False
        or payload.get("capability_status") != "PASS"
        or payload.get("scientific_claim") != "TECHNICAL_CAPABILITY_ONLY"
        or payload.get("model_call_count") != 4
        or payload.get("generated_output_count") != 4
    ):
        raise AceStateQueueError("sole ACE preflight is not the exact terminal PASS")

    claim_path = _external_file(terminal.get("attempt_claim_path"), "preflight attempt claim")
    expected_claim_path = (
        config.preflight_claim_root / "ace-state-preflight-v2-one-attempt.claim.json"
    )
    if claim_path != expected_claim_path:
        raise AceStateQueueError("preflight attempt claim is not the sole fixed claim")
    if sha256_file(claim_path) != terminal.get("attempt_claim_sha256"):
        raise AceStateQueueError("preflight attempt claim hash chain drifted")
    claim = strict_json(claim_path)
    _validate_identity(claim, "claim_identity_sha256", "preflight attempt claim")
    if (
        claim.get("run_id") != authority["run_id"]
        or claim.get("attempt_id") != authority["attempt_id"]
        or claim.get("retry_allowed") is not False
        or claim.get("claim_type") != "SOLE_ACE_STATE_PREFLIGHT_AUTHORIZED_ATTEMPT"
    ):
        raise AceStateQueueError("preflight attempt claim identity drifted")

    preflight_config_path = _external_file(
        claim.get("config_path"), "claimed preflight config"
    )
    expected_config_path = (config.repo_root / "configs/ace_state_preflight_v2.json").resolve()
    if preflight_config_path != expected_config_path:
        raise AceStateQueueError("preflight claim used an unexpected config path")
    preflight_config_sha = _sha256(
        claim.get("config_sha256"), "preflight config sha256"
    )
    if sha256_file(preflight_config_path) != preflight_config_sha:
        raise AceStateQueueError("claimed preflight config bytes drifted after PASS")

    result_path = _external_file(payload.get("run_result_path"), "preflight PASS result")
    if sha256_file(result_path) != payload.get("run_result_sha256"):
        raise AceStateQueueError("preflight PASS result hash chain drifted")
    result = strict_json(result_path)
    if (
        result.get("status") != "PASS"
        or result.get("capability_status") != "PASS"
        or result.get("run_id") != authority["run_id"]
        or result.get("attempt_id") != authority["attempt_id"]
        or result.get("scientific_claim") != "TECHNICAL_CAPABILITY_ONLY"
        or result.get("model_call_count") != 4
        or result.get("generated_output_count") != 4
        or result.get("checkpoint_export_count") != 3
        or result.get("resume_child_process_count") != 3
        or result.get("state_queue_accessed") is not False
        or result.get("retry_allowed") is not False
    ):
        raise AceStateQueueError("preflight result is not the frozen four-call PASS")
    equivalence = result.get("equivalence")
    if (
        not isinstance(equivalence, list)
        or len(equivalence) != 3
        or any(row.get("status") != "PASS" for row in equivalence if isinstance(row, dict))
        or any(not isinstance(row, dict) for row in equivalence)
    ):
        raise AceStateQueueError("preflight result lacks three PASS equivalence rows")
    result_ledger_path = _external_file(result.get("ledger_path"), "preflight result ledger")
    if (
        result_ledger_path != Path(str(terminal.get("ledger_path"))).resolve()
        or sha256_file(result_ledger_path) != terminal.get("ledger_sha256")
        or result.get("ledger_sha256") != terminal.get("ledger_sha256")
        or result.get("ledger_tail_sha256") != terminal.get("ledger_tail_sha256")
    ):
        raise AceStateQueueError("preflight PASS ledger hash chain drifted")
    return {
        "terminal": terminal,
        "terminal_path": str(path),
        "terminal_sha256": supplied_sha,
        "attempt_claim_path": str(claim_path),
        "attempt_claim_sha256": sha256_file(claim_path),
        "preflight_config_sha256": preflight_config_sha,
        "result_path": str(result_path),
        "result_sha256": sha256_file(result_path),
        "result": result,
    }


def _decision_block(text: str, decision_id: str) -> str:
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(decision_id)}\b.*?(?=^##\s+D-\d+\b|\Z)")
    match = pattern.search(text)
    if match is None:
        raise AceStateQueueError(f"decision block is absent: {decision_id}")
    return match.group(0)


def _assignment(block: str, key: str) -> str | None:
    matches = re.findall(
        rf"(?m)^\s*`?{re.escape(key)}\s*=\s*([^`\r\n]+?)`?\s*$", block
    )
    return matches[-1].strip() if matches else None


def validate_d0033_opening(
    config: QueueConfig,
    *,
    decisions_path: Path,
    decision_id: str,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Require D-0033 to assign every dynamic PASS/config/core binding exactly."""

    if decision_id != "D-0033":
        raise AceStateQueueError("ACE initial queue can be opened only by exact D-0033")
    path = decisions_path.resolve(strict=True)
    block = _decision_block(path.read_text(encoding="utf-8"), decision_id)
    core = config.raw["source_core_run"]
    expected = {
        "ACE_STATE_CAPABILITY": "PASS",
        "ACE_STATE_CAPTURE_INITIAL_AUTHORIZED": "YES",
        "ACE_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED": "NO",
        "NO_AUTOMATIC_RETRY": "YES",
        "ACE_STATE_CAPTURE_CONFIG": "configs/ace_state_capture_v2.json",
        "ACE_STATE_CAPTURE_CONFIG_SHA256": config.sha256,
        "ACE_STATE_PREFLIGHT_TERMINAL": str(config.preflight_terminal_path),
        "ACE_STATE_PREFLIGHT_TERMINAL_SHA256": str(preflight["terminal_sha256"]),
        "ACE_STATE_PREFLIGHT_RESULT_SHA256": str(preflight["result_sha256"]),
        "ACE_STATE_PREFLIGHT_CONFIG_SHA256": str(preflight["preflight_config_sha256"]),
        "ACE_STATE_CAPTURE_CORE_QUEUE_SHA256": core["generation_queue"]["sha256"],
        "ACE_STATE_CAPTURE_CORE_LEDGER_SHA256": core["ledger"]["sha256"],
    }
    missing = {
        key: value for key, value in expected.items() if _assignment(block, key) != value
    }
    if missing:
        raise AceStateQueueError(f"D-0033 lacks exact ACE state assignments: {missing}")
    cap_text = _assignment(block, "ACE_STATE_CAPTURE_INITIAL_GPU_SECONDS_CAP")
    try:
        cap = float(cap_text) if cap_text is not None else math.nan
    except ValueError as exc:
        raise AceStateQueueError("D-0033 state GPU cap is not numeric") from exc
    if not math.isfinite(cap) or cap <= 0:
        raise AceStateQueueError("D-0033 must assign a finite positive state GPU cap")
    return {
        "decision_block_sha256": hashlib.sha256(block.encode()).hexdigest(),
        "decision_id": decision_id,
        "decisions_path": str(path),
        "decisions_sha256": sha256_file(path),
        "initial_gpu_seconds_cap": cap,
    }


def _validate_core_artifact(artifact_root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    relative = Path(_string(row.get("output_relpath"), "core output_relpath"))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".wav":
        raise AceStateQueueError("core output_relpath is unsafe")
    wav = (artifact_root / relative).resolve()
    try:
        wav.relative_to(artifact_root)
    except ValueError as exc:
        raise AceStateQueueError("core output escapes the artifact root") from exc
    commit_path = wav.with_suffix(".commit.json")
    provenance_path = wav.with_suffix(".provenance.json")
    sanity_path = wav.with_suffix(".sanity.json")
    for path in (wav, commit_path, provenance_path, sanity_path):
        if not path.is_file():
            raise AceStateQueueError(f"completed core artifact is absent: {path}")
    commit = strict_json(commit_path)
    provenance = strict_json(provenance_path)
    sanity = strict_json(sanity_path)
    wav_sha = _sha256(commit.get("wav_sha256"), "core commit wav_sha256")
    if (
        commit.get("status") != "COMMITTED"
        or commit.get("request_sha256") != row.get("request_sha256")
        or commit.get("output_relpath") != relative.as_posix()
        or commit.get("provenance_sha256") != sha256_file(provenance_path)
        or commit.get("sanity_sha256") != sha256_file(sanity_path)
        or provenance.get("wav_sha256") != wav_sha
        or sanity.get("wav_sha256") != wav_sha
        or wav.stat().st_size <= 0
    ):
        raise AceStateQueueError("completed core artifact identity chain drifted")
    return {
        "commit_path": str(commit_path),
        "commit_sha256": sha256_file(commit_path),
        "output_relpath": relative.as_posix(),
        "provenance_sha256": sha256_file(provenance_path),
        "request_sha256": row["request_sha256"],
        "sanity_sha256": sha256_file(sanity_path),
        "wav_sha256": wav_sha,
    }


def _load_completed_core(config: QueueConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    queue_manifest = strict_json(config.generation_queue_manifest_path)
    core = config.raw["source_core_run"]
    if (
        queue_manifest.get("queue_sha256") != core["generation_queue"]["sha256"]
        or queue_manifest.get("row_count") != EXPECTED_CORE_ROWS
        or queue_manifest.get("model_row_counts") != {MODEL_ID: EXPECTED_CORE_ROWS}
    ):
        raise AceStateQueueError("ACE core queue manifest drifted")
    run_manifest = strict_json(config.run_manifest_path)
    if (
        run_manifest.get("status") != "PREPARED_NO_MODEL_CALLS"
        or run_manifest.get("authorized_model_ids") != [MODEL_ID]
        or run_manifest.get("generation_queue_manifest", {}).get("queue_sha256")
        != core["generation_queue"]["sha256"]
    ):
        raise AceStateQueueError("ACE core run manifest identity drifted")

    rows = load_queue(config.generation_queue_path)
    by_sha = {row["request_sha256"]: row for row in rows}
    if (
        len(rows) != EXPECTED_CORE_ROWS
        or len(by_sha) != EXPECTED_CORE_ROWS
        or {row.get("model_id") for row in rows} != {MODEL_ID}
    ):
        raise AceStateQueueError("ACE core generation queue is not the exact 1536-row source")
    ledger = validate_ledger(config.ledger_path)
    latest: dict[str, str] = {}
    success_commits: dict[str, Mapping[str, Any]] = {}
    for record in ledger:
        if record.get("event_kind") != "REQUEST_STATE":
            continue
        identity = str(record.get("request_sha256"))
        latest[identity] = str(record.get("request_state"))
        if record.get("request_state") == "SUCCEEDED":
            success_commits[identity] = _object(record.get("commit"), "ledger success commit")
    if (
        len(ledger) != EXPECTED_LEDGER_ROWS
        or set(latest) != set(by_sha)
        or set(latest.values()) != {"SUCCEEDED"}
        or set(success_commits) != set(by_sha)
        or ledger[-1].get("ledger_row_sha256") != core["ledger"]["tail_sha256"]
    ):
        raise AceStateQueueError("ACE core ledger is not terminal 1536/1536 SUCCEEDED")
    for identity, commit in success_commits.items():
        if (
            commit.get("status") != "COMMITTED"
            or commit.get("request_sha256") != identity
            or commit.get("output_relpath") != by_sha[identity].get("output_relpath")
        ):
            raise AceStateQueueError("ACE core terminal ledger commit drifted")
    return rows, {
        "ledger_row_count": len(ledger),
        "ledger_tail_sha256": ledger[-1]["ledger_row_sha256"],
    }


def _selected_prompts(config: QueueConfig) -> dict[str, tuple[str, ...]]:
    statistics = strict_json(config.statistics_path)
    eligibility = _object(statistics.get("eligibility"), "statistics eligibility")
    selection = _object(
        _object(eligibility.get("prompt_selection"), "prompt_selection").get("axis_prompt_ids"),
        "axis_prompt_ids",
    )
    prompts: dict[str, tuple[str, ...]] = {}
    for axis in AXES:
        values = selection.get(axis)
        if (
            not isinstance(values, list)
            or len(values) != EXPECTED_PROMPTS_PER_AXIS
            or len(set(values)) != EXPECTED_PROMPTS_PER_AXIS
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise AceStateQueueError(f"{axis} does not bind 12 unique prompt IDs")
        prompts[axis] = tuple(values)
    if len({prompt for values in prompts.values() for prompt in values}) != EXPECTED_PROMPTS:
        raise AceStateQueueError("eligibility prompt IDs overlap across axes")
    contract = _object(eligibility.get("state_capture_contract"), "state_capture_contract")
    if (
        contract.get("capture_fractions") != list(FRACTIONS)
        or contract.get("feature_source") != PREVIEW_SOURCE
        or contract.get("source_condition") != "BASE"
        or contract.get("one_capture_per_prompt_root_checkpoint") is not True
        or eligibility.get("actions") != list(ACTIONS)
        or eligibility.get("restart_outcome_label") != RESTART_LABEL
    ):
        raise AceStateQueueError("statistics Section-11 state contract drifted")
    return prompts


def _fold_map(
    config: QueueConfig, prompts: Mapping[str, Sequence[str]]
) -> dict[tuple[str, str], int]:
    namespace = config.raw["mapping"]["fold_namespace"]
    result: dict[tuple[str, str], int] = {}
    for axis in AXES:
        ordered = sorted(
            prompts[axis],
            key=lambda prompt: hashlib.sha256(f"{namespace}|{prompt}".encode()).hexdigest(),
        )
        for index, prompt in enumerate(ordered):
            result[(axis, prompt)] = index % FOLD_COUNT
    return result


def _restart_root(
    config: QueueConfig, *, prompt_id: str, fraction: float, action: str, root: int
) -> tuple[int, int]:
    if action not in {"RESTART_BASE", "RESTART_FIXED"} or root not in INITIAL_ROOTS:
        raise AceStateQueueError("invalid restart-map request")
    checkpoint = json.dumps(fraction, allow_nan=False, separators=(",", ":"))
    material = (
        f"{config.raw['mapping']['restart_namespace']}|{prompt_id}|{checkpoint}|{action}"
    )
    offset = int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 4
    rotated = RESTART_ROOTS[offset:] + RESTART_ROOTS[:offset]
    return rotated[INITIAL_ROOTS.index(root)], offset


def _hashed(row: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(row)
    if field in result:
        raise AceStateQueueError(f"row already has identity field: {field}")
    result[field] = _json_identity(result)
    return result


def build_rows(
    config: QueueConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Build all initial rows from the ACE core queue; no write and no model call."""

    generation_rows, _ledger_evidence = _load_completed_core(config)
    prompts = _selected_prompts(config)
    folds = _fold_map(config, prompts)
    selected = {(axis, prompt) for axis in AXES for prompt in prompts[axis]}

    index: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for row in generation_rows:
        key = (
            str(row.get("axis")),
            str(row.get("prompt_id")),
            str(row.get("condition")),
            int(row.get("root_index", -1)),
        )
        if key in index:
            raise AceStateQueueError("ACE core queue has a duplicate axis/prompt/condition/root")
        index[key] = row

    units: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    artifact_cache: dict[str, dict[str, Any]] = {}

    def artifact(row: Mapping[str, Any]) -> dict[str, Any]:
        identity = str(row["request_sha256"])
        if identity not in artifact_cache:
            artifact_cache[identity] = _validate_core_artifact(config.artifact_root, row)
        return artifact_cache[identity]

    lane_sequence = 0
    action_sequence = 0
    group_sequence = 0
    for axis in AXES:
        for prompt_id in sorted(prompts[axis]):
            for root in INITIAL_ROOTS:
                group_sequence += 1
                parent = index.get((axis, prompt_id, "BASE", root))
                if parent is None or (axis, prompt_id) not in selected:
                    raise AceStateQueueError("selected ACE BASE prefix is absent")
                parent_artifact = artifact(parent)
                group_unit_ids: list[str] = []
                for fraction, transition, cumulative_nfe in zip(
                    FRACTIONS, CHECKPOINT_TRANSITIONS, CHECKPOINT_NFE, strict=True
                ):
                    lane_sequence += 1
                    token = f"q-{round(fraction * 100):03d}"
                    base = Path(LANE_ID) / axis / prompt_id / f"root-{root:02d}" / token
                    unit = _hashed(
                        {
                            "action_set": list(ACTIONS),
                            "authorization_status": PACKAGE_AUTHORIZED,
                            "axis": axis,
                            "capture_mode": CAPTURE_MODE,
                            "checkpoint_completed_scheduler_transitions": transition,
                            "checkpoint_cumulative_transformer_nfe": cumulative_nfe,
                            "checkpoint_fraction": fraction,
                            "checkpoint_relpath": (base / "checkpoint.pt").as_posix(),
                            "condition": "BASE",
                            "eligibility_unit": {
                                "checkpoint": fraction,
                                "prompt": prompt_id,
                                "root": root,
                            },
                            "eligibility_unit_fields": ["prompt", "root", "checkpoint"],
                            "feature_contract": {
                                "forbidden_sources": [
                                    "OTHER_ROOT_PREVIEWS",
                                    "ACTION_OUTCOMES",
                                    "TERMINAL_AUDIO_FEATURES",
                                    "HUMAN_GOLD",
                                    "HELD_OUT_FITTED_VALUES",
                                ],
                                "preview_source": PREVIEW_SOURCE,
                                "preview_source_parent_request_sha256": parent[
                                    "request_sha256"
                                ],
                                "root_local_only": True,
                            },
                            "fold_id": folds[(axis, prompt_id)],
                            "lane_id": LANE_ID,
                            "lane_sequence": lane_sequence,
                            "model_id": MODEL_ID,
                            "parent_core_artifact": parent_artifact,
                            "parent_request_sha256": parent["request_sha256"],
                            "preview_relpath": (base / "preview.wav").as_posix(),
                            "preview_source": PREVIEW_SOURCE,
                            "preview_source_request_sha256": parent["request_sha256"],
                            "prompt": parent["prompt"],
                            "prompt_id": prompt_id,
                            "restart_outcome_label": RESTART_LABEL,
                            "resumed_terminal_relpath": (base / "resumed-terminal.wav").as_posix(),
                            "root_index": root,
                            "seed": parent["seed"],
                            "source_condition": "BASE",
                            "source_generation_queue_sha256": config.raw["source_core_run"][
                                "generation_queue"
                            ]["sha256"],
                            "source_queue_derivation": "FRESH_ACE_CORE_GENERATION_QUEUE",
                            "tier": TIER,
                            "total_scheduler_transitions": 30,
                            "total_transformer_nfe": 45,
                        },
                        "lane_request_sha256",
                    )
                    units.append(unit)
                    group_unit_ids.append(unit["lane_request_sha256"])

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
                            "root_index": root,
                            "tier": TIER,
                        }
                        if action == "KEEP":
                            action_row.update(
                                {
                                    "incremental_cost": "MEASURED_REMAINING_NFE_AND_TIME",
                                    "outcome_label": "KEEP_TRUE_ROOT_STATE",
                                    "outcome_relpath": unit["resumed_terminal_relpath"],
                                    "outcome_source": "ROOT_LOCAL_TRUE_STATE_RESUME",
                                    "outcome_source_root_index": root,
                                }
                            )
                        else:
                            pool_root, offset = _restart_root(
                                config,
                                prompt_id=prompt_id,
                                fraction=fraction,
                                action=action,
                                root=root,
                            )
                            condition = "BASE" if action == "RESTART_BASE" else "FIXED"
                            outcome = index.get((axis, prompt_id, condition, pool_root))
                            if outcome is None:
                                raise AceStateQueueError(
                                    "frozen prompt-level restart outcome absent"
                                )
                            action_row.update(
                                {
                                    "incremental_cost": "ONE_FULL_NATIVE_GENERATION",
                                    "outcome_label": RESTART_LABEL,
                                    "outcome_source": "FROZEN_PROMPT_LEVEL_CORE_TERMINAL_POOL",
                                    "outcome_source_condition": condition,
                                    "outcome_source_core_artifact": artifact(outcome),
                                    "outcome_source_request_sha256": outcome["request_sha256"],
                                    "outcome_source_root_index": pool_root,
                                    "restart_pool_root_indices": list(RESTART_ROOTS),
                                    "rotation_direction": "LEFT",
                                    "rotation_offset": offset,
                                }
                            )
                        actions.append(_hashed(action_row, "action_mapping_sha256"))

                groups.append(
                    _hashed(
                        {
                            "authorization_status": PACKAGE_AUTHORIZED,
                            "axis": axis,
                            "capture_call_contract": (
                                "ONE_BASE_PREFIX_REFERENCE_EXPORTS_ALL_THREE_CHECKPOINTS"
                            ),
                            "checkpoint_completed_scheduler_transitions": list(
                                CHECKPOINT_TRANSITIONS
                            ),
                            "checkpoint_cumulative_transformer_nfe": list(CHECKPOINT_NFE),
                            "checkpoint_fractions": list(FRACTIONS),
                            "condition": "BASE",
                            "group_sequence": group_sequence,
                            "lane_id": LANE_ID,
                            "lane_request_sha256s": group_unit_ids,
                            "model_id": MODEL_ID,
                            "parent_core_artifact": parent_artifact,
                            "parent_request_sha256": parent["request_sha256"],
                            "prompt": parent["prompt"],
                            "prompt_id": prompt_id,
                            "reference_terminal_relpath": (
                                Path(LANE_ID)
                                / axis
                                / prompt_id
                                / f"root-{root:02d}"
                                / "reference-terminal.wav"
                            ).as_posix(),
                            "root_index": root,
                            "seed": parent["seed"],
                            "separate_process_resume_required": True,
                            "source_condition": "BASE",
                            "source_queue_derivation": "FRESH_ACE_CORE_GENERATION_QUEUE",
                            "tier": TIER,
                        },
                        "group_request_sha256",
                    )
                )

    fold_rows = [
        {"axis": axis, "fold_id": folds[(axis, prompt)], "prompt_id": prompt}
        for axis in AXES
        for prompt in sorted(prompts[axis])
    ]
    fold_contract = {
        "assignment": "WHOLE_PROMPT_GROUPED",
        "fold_count": FOLD_COUNT,
        "fold_namespace": config.raw["mapping"]["fold_namespace"],
        "rows": fold_rows,
        "schema_version": 1,
    }
    validate_rows(units, groups, actions, fold_contract)
    return units, groups, actions, fold_contract


def validate_rows(
    units: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    actions: Sequence[Mapping[str, Any]],
    folds: Mapping[str, Any],
) -> None:
    """Recheck cardinality, root locality, replicated pools, and grouped folds."""

    if len(units) != EXPECTED_UNITS or len(groups) != EXPECTED_GROUPS:
        raise AceStateQueueError("initial unit/prefix-group count drifted")
    if len(actions) != EXPECTED_ACTION_ROWS:
        raise AceStateQueueError("replicated-action row count drifted")
    unit_ids: set[str] = set()
    identities: set[tuple[str, str, int, float]] = set()
    per_axis: Counter[str] = Counter()
    for sequence, row in enumerate(units, start=1):
        _validate_identity(row, "lane_request_sha256", "state unit")
        if row.get("lane_sequence") != sequence:
            raise AceStateQueueError("state unit sequence is not contiguous")
        if (
            row.get("model_id") != MODEL_ID
            or row.get("condition") != "BASE"
            or row.get("source_condition") != "BASE"
            or row.get("preview_source_request_sha256") != row.get("parent_request_sha256")
            or row.get("preview_source") != PREVIEW_SOURCE
            or row.get("feature_contract", {}).get("root_local_only") is not True
            or row.get("source_queue_derivation") != "FRESH_ACE_CORE_GENERATION_QUEUE"
        ):
            raise AceStateQueueError("state unit lost ACE BASE/root-local provenance")
        identity = (
            str(row.get("axis")),
            str(row.get("prompt_id")),
            int(row.get("root_index", -1)),
            float(row.get("checkpoint_fraction", -1)),
        )
        if identity in identities:
            raise AceStateQueueError("duplicate (prompt,root,checkpoint) unit")
        identities.add(identity)
        unit_ids.add(str(row["lane_request_sha256"]))
        per_axis[str(row["axis"])] += 1
    if per_axis != Counter({axis: 144 for axis in AXES}):
        raise AceStateQueueError("each axis must have exactly 144 initial units")

    grouped_ids: list[str] = []
    for sequence, group in enumerate(groups, start=1):
        _validate_identity(group, "group_request_sha256", "prefix group")
        if (
            group.get("group_sequence") != sequence
            or group.get("condition") != "BASE"
            or group.get("source_queue_derivation") != "FRESH_ACE_CORE_GENERATION_QUEUE"
        ):
            raise AceStateQueueError("prefix group identity/source drifted")
        members = group.get("lane_request_sha256s")
        if not isinstance(members, list) or len(members) != 3 or len(set(members)) != 3:
            raise AceStateQueueError("each prefix group must bind exactly three units")
        grouped_ids.extend(members)
    if Counter(grouped_ids) != Counter(unit_ids):
        raise AceStateQueueError("prefix groups do not partition the initial units")

    action_sets: defaultdict[str, set[str]] = defaultdict(set)
    restart_usage: defaultdict[tuple[str, float, str], list[int]] = defaultdict(list)
    for sequence, action in enumerate(actions, start=1):
        _validate_identity(action, "action_mapping_sha256", "action row")
        if action.get("action_sequence") != sequence:
            raise AceStateQueueError("action sequence is not contiguous")
        identity = str(action.get("lane_request_sha256"))
        if identity not in unit_ids:
            raise AceStateQueueError("action row maps an unknown state unit")
        name = str(action.get("action"))
        action_sets[identity].add(name)
        if name.startswith("RESTART_"):
            if (
                action.get("outcome_label") != RESTART_LABEL
                or action.get("outcome_source")
                != "FROZEN_PROMPT_LEVEL_CORE_TERMINAL_POOL"
            ):
                raise AceStateQueueError("restart action lost prompt-level pool labeling")
            key = (
                str(action["prompt_id"]),
                float(action["checkpoint_fraction"]),
                name,
            )
            restart_usage[key].append(int(action["outcome_source_root_index"]))
    if set(action_sets) != unit_ids or any(value != set(ACTIONS) for value in action_sets.values()):
        raise AceStateQueueError("each state unit must have exactly the three frozen actions")
    if any(sorted(roots) != list(RESTART_ROOTS) for roots in restart_usage.values()):
        raise AceStateQueueError("restart rotation does not use all four pool roots exactly once")

    fold_rows = folds.get("rows")
    if not isinstance(fold_rows, list) or len(fold_rows) != EXPECTED_PROMPTS:
        raise AceStateQueueError("prompt-fold table must contain exactly 36 rows")
    fold_counts = Counter((row["axis"], row["fold_id"]) for row in fold_rows)
    if any(fold_counts[(axis, fold)] != 2 for axis in AXES for fold in range(FOLD_COUNT)):
        raise AceStateQueueError("prompt-grouped folds must hold two prompts per axis")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _artifact_record(path: Path, count: int) -> dict[str, Any]:
    return {"path": str(path), "row_count": count, "sha256": sha256_file(path)}


def prepare_opened_queue_package(
    config_path: Path,
    *,
    repo_root: Path,
    decisions_path: Path,
    decision_id: str,
    preflight_terminal_path: Path,
    preflight_terminal_sha256: str,
    output_dir: Path,
    git_commit: str,
) -> dict[str, Any]:
    """Materialize the post-PASS, D-0033-bound initial package with zero generation."""

    if COMMIT_PATTERN.fullmatch(git_commit) is None:
        raise AceStateQueueError("git_commit must be a lowercase 40-hex identity")
    config = load_queue_config(config_path, repo_root=repo_root)
    preflight = validate_preflight_pass(
        config,
        terminal_path=preflight_terminal_path,
        expected_terminal_sha256=preflight_terminal_sha256,
    )
    decision = validate_d0033_opening(
        config,
        decisions_path=decisions_path,
        decision_id=decision_id,
        preflight=preflight,
    )
    units, groups, actions, folds = build_rows(config)

    output = output_dir.resolve()
    try:
        output.relative_to(config.run_root)
    except ValueError as exc:
        raise AceStateQueueError("output_dir must be inside the frozen state run root") from exc
    output.mkdir(parents=True, exist_ok=False)
    _fsync_directory(output.parent)
    unit_path = output / "initial-units.jsonl"
    group_path = output / "prefix-groups.jsonl"
    action_path = output / "replicated-action-map.jsonl"
    fold_path = output / "prompt-grouped-folds.json"
    supplemental_path = output / "supplemental-lock.json"
    _write_jsonl(unit_path, units)
    _write_jsonl(group_path, groups)
    _write_jsonl(action_path, actions)
    _write_json(fold_path, folds)
    _write_json(
        supplemental_path,
        {
            "authorized": False,
            "maximum_doublings": 1,
            "only_trigger": "INCONCLUSIVE_UNDERPOWERED",
            "root_indices": list(RESTART_ROOTS),
            "schema_version": 1,
            "status": config.raw["authorization_contract"]["supplemental_queue_status"],
        },
    )
    manifest: dict[str, Any] = {
        "action_map": _artifact_record(action_path, EXPECTED_ACTION_ROWS),
        "authorization_status": PACKAGE_AUTHORIZED,
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "decision": decision,
        "eligibility_unit": ["prompt", "root", "checkpoint"],
        "execution_started": False,
        "folds": _artifact_record(fold_path, EXPECTED_PROMPTS),
        "git_commit": git_commit,
        "lane_id": LANE_ID,
        "model_calls": 0,
        "model_id": MODEL_ID,
        "prefix_groups": _artifact_record(group_path, EXPECTED_GROUPS),
        "preflight_pass": {
            key: preflight[key]
            for key in (
                "attempt_claim_path",
                "attempt_claim_sha256",
                "preflight_config_sha256",
                "result_path",
                "result_sha256",
                "terminal_path",
                "terminal_sha256",
            )
        },
        "schema_version": 1,
        "source_core": {
            "generation_queue_sha256": config.raw["source_core_run"]["generation_queue"][
                "sha256"
            ],
            "ledger_sha256": config.raw["source_core_run"]["ledger"]["sha256"],
            "legacy_state_queue_disposition": "REJECT_MODEL_ID_IS_SA3_NOT_ACE",
            "run_manifest_sha256": config.raw["source_core_run"]["run_manifest"]["sha256"],
        },
        "source_queue_derivation": "FRESH_ACE_CORE_GENERATION_QUEUE",
        "status": PACKAGE_STATUS,
        "supplemental_lock": _artifact_record(supplemental_path, 1),
        "tier": TIER,
        "units": _artifact_record(unit_path, EXPECTED_UNITS),
    }
    manifest_path = output / "state-capture-manifest.json"
    _write_json(manifest_path, manifest)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
    }


__all__ = [
    "AceStateQueueError",
    "EXPECTED_ACTION_ROWS",
    "EXPECTED_GROUPS",
    "EXPECTED_UNITS",
    "LANE_ID",
    "MODEL_ID",
    "PACKAGE_STATUS",
    "QueueConfig",
    "build_rows",
    "load_queue_config",
    "prepare_opened_queue_package",
    "sha256_file",
    "validate_d0033_opening",
    "validate_preflight_pass",
    "validate_rows",
]

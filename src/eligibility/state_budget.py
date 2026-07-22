"""Outcome-blind construction of frozen eligibility time-budget coordinates.

This module reads only registered Stage-1 survivor units and their same-root
BASE ordinary-core receipts.  It never imports an evaluator, opens an evaluator
row, inspects a state outcome, or generates audio.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmark_core.ledger import validate_ledger
from eligibility.contract import (
    EXPECTED_INITIAL_UNITS,
    INITIAL_ROOTS,
    WATERMARK,
    AnalysisConfig,
    _validate_queue_unit,
    load_analysis_config,
    validate_prospective_opening,
)
from scoring.common import (
    canonical_json,
    load_json,
    load_jsonl,
    require_sha256,
    sha256_file,
    sha256_json,
)

_BACKBONE_MODEL = {
    "stable-audio-3-medium-base": "stabilityai/stable-audio-3-medium-base",
    "ACE-Step v1": "ACE-Step/ACE-Step-v1-3.5B",
}
_DECISION_HEADER = re.compile(r"(?m)^## (?P<id>D-[0-9]{4})\b[^\n]*$")
_PACKAGE_KEYS = {
    "axis",
    "backbone",
    "human_gold_used",
    "package_sha256",
    "row_count",
    "rows",
    "schema_version",
    "status",
    "supplemental_roots_used",
    "tier",
}
_EVIDENCE_KEYS = {
    "checkpoint_fraction",
    "condition",
    "core_commit_sha256",
    "core_ledger_path",
    "core_ledger_row_sha256",
    "core_ledger_sha256",
    "core_provenance_sha256",
    "core_queue_path",
    "core_queue_sha256",
    "core_request_sha256",
    "core_wav_sha256",
    "elapsed_nfe",
    "elapsed_seconds",
    "lane_request_sha256",
    "mapping",
    "prompt_id",
    "remaining_nfe",
    "remaining_seconds",
    "root_index",
    "schema_version",
    "synchronized_wall_seconds",
    "total_nfe",
    "total_seconds",
}
_COST_KEYS = {
    "elapsed_nfe",
    "elapsed_seconds",
    "lane_request_sha256",
    "remaining_nfe",
    "remaining_seconds",
    "schema_version",
    "total_nfe",
    "total_seconds",
}


class StateBudgetError(RuntimeError):
    """A prospective freeze, survivor, or ordinary-core cost binding drifted."""


def _decision_block(text: str, decision_id: str) -> str:
    headers = list(_DECISION_HEADER.finditer(text))
    selected = [index for index, match in enumerate(headers) if match.group("id") == decision_id]
    if len(selected) != 1:
        raise StateBudgetError(f"expected exactly one {decision_id} decision block")
    index = selected[0]
    start = headers[index].start()
    end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
    return text[start:end]


def _assignments(block: str) -> dict[str, str]:
    pairs = re.findall(r"(?m)^`?([A-Z][A-Z0-9_]*)\s*=\s*([^`\n]+)`?\s*$", block)
    result = {name: value.strip() for name, value in pairs}
    if len(result) != len(pairs):
        raise StateBudgetError("state-budget decision assignment is duplicated")
    return result


def load_state_budget_config(path: Path, *, repo_root: Path) -> dict[str, Any]:
    """Load the closed cost-only operationalization and verify frozen sources."""

    source = path.resolve(strict=True)
    root = repo_root.resolve(strict=True)
    raw = load_json(source)
    if (
        raw.get("schema_version") != 1
        or raw.get("status") != "PROSPECTIVE_CLOSED_REQUIRES_APPEND_ONLY_BUDGET_OPENING"
        or raw.get("generation_authorized") is not False
        or raw.get("evaluator_or_outcome_rows_allowed") is not False
    ):
        raise StateBudgetError("state-budget config identity/scope drifted")
    if raw.get("scope") != {
        "human_gold_used": False,
        "roots": [0, 1, 2, 3],
        "stop_or_cancelled_units_allowed": False,
        "supplemental_roots_allowed": False,
        "tier": "INITIAL",
    }:
        raise StateBudgetError("state-budget initial survivor scope drifted")
    if raw.get("operationalization") != {
        "elapsed_nfe": "EXACT_FROZEN_CHECKPOINT_CUMULATIVE_NFE",
        "elapsed_seconds": "TOTAL_SECONDS_TIMES_ELAPSED_NFE_DIVIDED_BY_TOTAL_NFE",
        "keep_incremental": "REMAINING_NFE_AND_REMAINING_SECONDS",
        "remaining_nfe": "TOTAL_NFE_MINUS_ELAPSED_NFE",
        "remaining_seconds": "TOTAL_SECONDS_MINUS_ELAPSED_SECONDS",
        "restart_incremental": "TOTAL_NFE_AND_TOTAL_SECONDS",
        "total_nfe": "BACKBONE_NATIVE_FROZEN_TRANSFORMER_BUDGET_NFE",
        "total_seconds": "SAME_ROOT_BASE_CORE_SYNCHRONIZED_GENERATION_WALL_SECONDS",
    }:
        raise StateBudgetError("state-budget operationalization drifted")
    schema = raw.get("budget_package_schema", {})
    schema_path = (root / str(schema.get("path", ""))).resolve(strict=True)
    if schema_path != (
        root / "configs/eligibility_state_input_budget_v2.schema.json"
    ) or sha256_file(schema_path) != require_sha256(
        schema.get("sha256"), "state-budget schema SHA"
    ):
        raise StateBudgetError("state-budget schema binding drifted")
    frozen = raw.get("frozen_repository_sources")
    if not isinstance(frozen, list) or not frozen:
        raise StateBudgetError("state-budget frozen source list is absent")
    seen: set[str] = set()
    for record in frozen:
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise StateBudgetError("state-budget frozen source record drifted")
        relative = record["path"]
        if not isinstance(relative, str) or Path(relative).is_absolute() or relative in seen:
            raise StateBudgetError("state-budget frozen source path is invalid")
        seen.add(relative)
        candidate = (root / relative).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise StateBudgetError("state-budget frozen source escapes repository") from exc
        if sha256_file(candidate) != require_sha256(record["sha256"], "frozen source SHA"):
            raise StateBudgetError(f"state-budget frozen source changed: {relative}")
    return raw


def validate_state_budget_opening(
    budget_config_path: Path,
    analysis_config_path: Path,
    *,
    repo_root: Path,
    decisions_path: Path,
    analysis_decision_id: str,
    budget_decision_id: str,
) -> tuple[dict[str, Any], AnalysisConfig]:
    """Prove both pushed freezes before accepting any queue/core input path."""

    root = repo_root.resolve(strict=True)
    analysis = load_analysis_config(analysis_config_path, repo_root=root)
    validate_prospective_opening(
        analysis,
        decisions_path=decisions_path,
        decision_id=analysis_decision_id,
    )
    config = load_state_budget_config(budget_config_path, repo_root=root)
    decisions = decisions_path.resolve(strict=True)
    if decisions != (root / "DECISIONS.md").resolve(strict=True):
        raise StateBudgetError("state-budget opening must use repository DECISIONS.md")
    local_block = _decision_block(decisions.read_text(encoding="utf-8"), budget_decision_id)
    observed = _assignments(local_block)
    opening = config["opening_contract"]
    if set(observed) != set(opening["required_assignment_names"]):
        raise StateBudgetError("state-budget opening assignment set drifted")
    for name, expected in opening["required_assignment_values"].items():
        if observed.get(name) != expected:
            raise StateBudgetError(f"state-budget opening assignment drifted: {name}")
    if observed.get("ELIGIBILITY_STATE_BUDGET_CONFIG_SHA256") != sha256_file(
        budget_config_path.resolve(strict=True)
    ):
        raise StateBudgetError("state-budget decision does not bind the config")
    if observed.get("ELIGIBILITY_ANALYSIS_CONFIG_SHA256") != analysis.sha256:
        raise StateBudgetError("state-budget decision does not bind D-0060 analysis bytes")
    if re.search(r"\b(?:PENDING|PLACEHOLDER|TBD|ESTIMATE)\b", local_block, re.IGNORECASE):
        raise StateBudgetError("state-budget opening contains an unresolved marker")

    remote_ref = opening["remote_ref"]

    def git_show(relative: str) -> bytes:
        completed = subprocess.run(
            ["git", "show", f"{remote_ref}:{relative}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise StateBudgetError(f"cannot read {relative} from {remote_ref}")
        return completed.stdout

    config_relative = budget_config_path.resolve(strict=True).relative_to(root).as_posix()
    decision_relative = decisions.relative_to(root).as_posix()
    if hashlib.sha256(git_show(config_relative)).hexdigest() != sha256_file(
        budget_config_path.resolve(strict=True)
    ):
        raise StateBudgetError("state-budget config is not on origin/main")
    if _decision_block(git_show(decision_relative).decode(), budget_decision_id) != local_block:
        raise StateBudgetError("state-budget decision block is not on origin/main")
    return config, analysis


def _bound_file(manifest: Mapping[str, Any], name: str) -> Path:
    record = manifest.get(name)
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise StateBudgetError(f"manifest lacks {name} binding")
    path = Path(record["path"]).resolve(strict=True)
    if sha256_file(path) != require_sha256(record.get("sha256"), f"{name} SHA"):
        raise StateBudgetError(f"manifest {name} binding drifted")
    return path


def _load_survivor_units(
    queue_manifest_path: Path,
    survivor_manifest_path: Path,
    cancellation_manifest_path: Path,
    *,
    backbone: str,
    axis: str,
) -> tuple[list[dict[str, Any]], Path, Path]:
    queue_manifest = load_json(queue_manifest_path.resolve(strict=True))
    queue_units_path = _bound_file(queue_manifest, "units")
    queue: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(load_jsonl(queue_units_path)):
        identity = _validate_queue_unit(unit, f"queue unit {index}")
        if identity in queue:
            raise StateBudgetError("queue unit identity is duplicated")
        queue[identity] = unit

    survivor = load_json(survivor_manifest_path.resolve(strict=True))
    survivor_units_path = Path(str(survivor.get("units_path", ""))).resolve(strict=True)
    if (
        survivor.get("status") != "STAGE1_SURVIVOR_MANIFEST_COMPLETE"
        or survivor.get("watermark") != WATERMARK
        or survivor.get("human_gold_claims") is not False
        or survivor.get("backbone") != backbone
        or survivor.get("pass_axes") != [axis]
        or axis in survivor.get("stop_axes", [])
        or sha256_file(survivor_units_path) != survivor.get("units_sha256")
    ):
        raise StateBudgetError("Stage-1 survivor manifest does not authorize this cell")
    survivor_units = load_jsonl(survivor_units_path)
    survivors: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(survivor_units):
        identity = _validate_queue_unit(unit, f"survivor unit {index}")
        if identity in survivors or queue.get(identity) != unit:
            raise StateBudgetError("survivor is duplicated or differs from registered queue")
        survivors[identity] = unit
    expected = {identity for identity, unit in queue.items() if unit.get("axis") == axis}
    if len(survivors) != EXPECTED_INITIAL_UNITS or set(survivors) != expected:
        raise StateBudgetError("survivor cell is not the exact 144 registered initial units")

    cancellation = load_json(cancellation_manifest_path.resolve(strict=True))
    cancelled_path = Path(str(cancellation.get("units_path", ""))).resolve(strict=True)
    if (
        cancellation.get("status") != "STAGE1_CANCELLATION_MANIFEST_COMPLETE"
        or cancellation.get("watermark") != WATERMARK
        or cancellation.get("human_gold_claims") is not False
        or cancellation.get("prohibited_operations") != ["EXECUTE", "SCORE"]
        or sha256_file(cancelled_path) != cancellation.get("units_sha256")
    ):
        raise StateBudgetError("Stage-1 cancellation manifest drifted")
    cancelled = {
        require_sha256(row.get("lane_request_sha256"), "cancelled lane")
        for row in load_jsonl(cancelled_path)
    }
    if set(survivors) & cancelled:
        raise StateBudgetError("STOP/cancelled unit entered state-budget assembly")
    return (
        sorted(survivors.values(), key=lambda row: row["lane_request_sha256"]),
        queue_units_path,
        cancelled_path,
    )


def _provenance_prompt(provenance: Mapping[str, Any]) -> str | None:
    adapter = provenance.get("upstream", {}).get("adapter_metadata", {})
    return adapter.get("upstream_kwargs", {}).get(
        "prompt", adapter.get("generation_parameters", {}).get("prompt")
    )


def _core_run_cache(artifact_root: Path, cache: dict[Path, dict[str, Any]]) -> dict[str, Any]:
    run_root = artifact_root.parent
    if run_root in cache:
        return cache[run_root]
    ledger_path = (run_root / "ledger.jsonl").resolve(strict=True)
    ledger = validate_ledger(ledger_path)
    succeeded_rows = [
        row
        for row in ledger
        if row.get("event_kind") == "REQUEST_STATE" and row.get("request_state") == "SUCCEEDED"
    ]
    succeeded = {row["request_sha256"]: row for row in succeeded_rows}
    if len(succeeded) != len(succeeded_rows):
        raise StateBudgetError("ordinary-core ledger duplicates a successful request")
    queue_path = (run_root / "queues/generation/queue.jsonl").resolve(strict=True)
    queue_rows = load_jsonl(queue_path)
    queue = {row.get("request_sha256"): row for row in queue_rows}
    if len(queue) != len(queue_rows):
        raise StateBudgetError("ordinary-core queue duplicates a request")
    cached = {
        "ledger_path": ledger_path,
        "ledger_sha256": sha256_file(ledger_path),
        "queue": queue,
        "queue_path": queue_path,
        "queue_sha256": sha256_file(queue_path),
        "succeeded": succeeded,
    }
    cache[run_root] = cached
    return cached


def _same_root_base_receipt(
    unit: Mapping[str, Any],
    *,
    backbone: str,
    total_nfe: int,
    cache: dict[Path, dict[str, Any]],
) -> dict[str, Any]:
    record = unit.get("parent_core_artifact")
    if not isinstance(record, dict):
        raise StateBudgetError("unit lacks its same-root BASE core artifact")
    request = require_sha256(unit.get("parent_request_sha256"), "parent core request")
    if record.get("request_sha256") != request:
        raise StateBudgetError("parent core request binding drifted")
    commit_path = Path(str(record.get("commit_path", ""))).resolve(strict=True)
    if not commit_path.name.endswith(".commit.json") or sha256_file(commit_path) != require_sha256(
        record.get("commit_sha256"), "parent core commit"
    ):
        raise StateBudgetError("parent core commit binding drifted")
    stem = commit_path.name.removesuffix(".commit.json")
    wav_path = commit_path.with_name(f"{stem}.wav")
    provenance_path = commit_path.with_name(f"{stem}.provenance.json")
    commit = load_json(commit_path)
    if (
        commit.get("status") != "COMMITTED"
        or commit.get("request_sha256") != request
        or commit.get("output_relpath") != record.get("output_relpath")
        or commit.get("provenance_sha256") != record.get("provenance_sha256")
        or commit.get("wav_sha256") != record.get("wav_sha256")
        or sha256_file(wav_path) != record.get("wav_sha256")
        or sha256_file(provenance_path) != record.get("provenance_sha256")
    ):
        raise StateBudgetError("parent core terminal/commit/provenance binding drifted")
    output_relpath = Path(str(commit["output_relpath"]))
    expected_tail = (
        unit["axis"],
        unit["prompt_id"],
        "base",
        f"root-{unit['root_index']:02d}.wav",
    )
    if (
        output_relpath.is_absolute()
        or ".." in output_relpath.parts
        or len(output_relpath.parts) < 5
        or output_relpath.parts[-4:] != expected_tail
    ):
        raise StateBudgetError("parent core path differs from axis/prompt/root/BASE")
    roots = [parent for parent in wav_path.parents if parent.name == "artifacts"]
    if len(roots) != 1 or (roots[0] / output_relpath).resolve() != wav_path:
        raise StateBudgetError("parent core output escapes its run artifact root")
    provenance = load_json(provenance_path)
    seconds = provenance.get("synchronized_wall_seconds")
    if (
        provenance.get("request_sha256") != request
        or provenance.get("model_id") != _BACKBONE_MODEL[backbone]
        or provenance.get("root_index") != unit["root_index"]
        or provenance.get("actual_nfe") != total_nfe
        or provenance.get("wav_sha256") != record.get("wav_sha256")
        or _provenance_prompt(provenance) != unit["prompt"]
        or isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or float(seconds) <= 0.0
    ):
        raise StateBudgetError("parent core provenance differs from model/prompt/root/budget")
    cached = _core_run_cache(roots[0], cache)
    queue_row = cached["queue"].get(request)
    ledger_row = cached["succeeded"].get(request)
    if (
        queue_row is None
        or ledger_row is None
        or queue_row.get("model_id") != _BACKBONE_MODEL[backbone]
        or queue_row.get("axis") != unit["axis"]
        or queue_row.get("prompt_id") != unit["prompt_id"]
        or queue_row.get("prompt") != unit["prompt"]
        or queue_row.get("root_index") != unit["root_index"]
        or queue_row.get("condition") != "BASE"
        or queue_row.get("output_relpath") != str(output_relpath)
        or ledger_row.get("commit") != commit
        or ledger_row.get("actual_nfe") != total_nfe
        or float(ledger_row.get("synchronized_wall_seconds", -1.0)) != float(seconds)
    ):
        raise StateBudgetError("parent core queue/ledger differs from prompt/root/BASE receipt")
    return {
        "condition": "BASE",
        "core_commit_sha256": sha256_file(commit_path),
        "core_ledger_path": str(cached["ledger_path"]),
        "core_ledger_row_sha256": ledger_row["ledger_row_sha256"],
        "core_ledger_sha256": cached["ledger_sha256"],
        "core_provenance_sha256": sha256_file(provenance_path),
        "core_queue_path": str(cached["queue_path"]),
        "core_queue_sha256": cached["queue_sha256"],
        "core_request_sha256": request,
        "core_wav_sha256": sha256_file(wav_path),
        "prompt_id": unit["prompt_id"],
        "root_index": unit["root_index"],
        "synchronized_wall_seconds": float(seconds),
    }


def validate_budget_package(package: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the package identity and exact outcome-blind cost equations."""

    if set(package) != _PACKAGE_KEYS:
        raise StateBudgetError("state-budget package keys drifted")
    body = dict(package)
    claimed = require_sha256(body.pop("package_sha256"), "state-budget package SHA")
    rows = package.get("rows")
    if (
        sha256_json(body) != claimed
        or package.get("schema_version") != 1
        or package.get("status") != "FROZEN_PER_UNIT_TIME_BUDGET_COMPLETE"
        or package.get("tier") != "INITIAL"
        or package.get("supplemental_roots_used") is not False
        or package.get("human_gold_used") is not False
        or package.get("backbone") not in _BACKBONE_MODEL
        or package.get("axis") not in {"vocal_instrumental", "tempo", "integrity"}
        or not isinstance(rows, list)
        or package.get("row_count") != EXPECTED_INITIAL_UNITS
        or len(rows) != EXPECTED_INITIAL_UNITS
    ):
        raise StateBudgetError("state-budget package identity/scope drifted")
    lanes: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict) or set(raw) != _EVIDENCE_KEYS:
            raise StateBudgetError(f"state-budget evidence row {index} keys drifted")
        row = dict(raw)
        lane = require_sha256(row["lane_request_sha256"], "state-budget lane")
        if lane in lanes:
            raise StateBudgetError("state-budget lane is duplicated")
        lanes.add(lane)
        for field in (
            "core_commit_sha256",
            "core_ledger_row_sha256",
            "core_ledger_sha256",
            "core_provenance_sha256",
            "core_queue_sha256",
            "core_request_sha256",
            "core_wav_sha256",
        ):
            require_sha256(row[field], f"state-budget {field}")
        numeric: dict[str, float] = {}
        for field in (
            "elapsed_nfe",
            "elapsed_seconds",
            "remaining_nfe",
            "remaining_seconds",
            "synchronized_wall_seconds",
            "total_nfe",
            "total_seconds",
        ):
            value = row[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
            ):
                raise StateBudgetError(f"state-budget {field} is invalid")
            numeric[field] = float(value)
        if (
            row["schema_version"] != 1
            or row["condition"] != "BASE"
            or row["mapping"] != "NFE_PROPORTIONAL_SAME_ROOT_BASE_CORE_TIME_BUDGET"
            or row["checkpoint_fraction"] not in (0.25, 0.5, 0.75)
            or row["root_index"] not in INITIAL_ROOTS
            or not isinstance(row["prompt_id"], str)
            or not row["prompt_id"]
            or not Path(row["core_ledger_path"]).is_absolute()
            or not Path(row["core_queue_path"]).is_absolute()
            or not math.isclose(
                numeric["elapsed_nfe"] + numeric["remaining_nfe"],
                numeric["total_nfe"],
                abs_tol=1e-9,
            )
            or not math.isclose(
                numeric["elapsed_seconds"] + numeric["remaining_seconds"],
                numeric["total_seconds"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or not math.isclose(
                numeric["elapsed_seconds"],
                numeric["total_seconds"] * numeric["elapsed_nfe"] / numeric["total_nfe"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or numeric["total_seconds"] != numeric["synchronized_wall_seconds"]
        ):
            raise StateBudgetError("state-budget equation or prompt/root/BASE binding drifted")
        normalized.append(row)
    return normalized


def assemble_state_budget(
    *,
    backbone: str,
    axis: str,
    queue_manifest_path: Path,
    survivor_manifest_path: Path,
    cancellation_manifest_path: Path,
) -> dict[str, Any]:
    """Assemble one 144-unit budget package without opening evaluator outcomes."""

    if backbone not in _BACKBONE_MODEL:
        raise StateBudgetError("backbone is not in the frozen eligibility scope")
    units, queue_units_path, cancelled_path = _load_survivor_units(
        queue_manifest_path,
        survivor_manifest_path,
        cancellation_manifest_path,
        backbone=backbone,
        axis=axis,
    )
    cost_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    cache: dict[Path, dict[str, Any]] = {}
    for unit in units:
        lane = unit["lane_request_sha256"]
        completed = unit.get(
            "checkpoint_completed_steps", unit.get("checkpoint_cumulative_transformer_nfe")
        )
        total = unit.get("transformer_budget_nfe", unit.get("total_transformer_nfe"))
        if (
            isinstance(completed, bool)
            or not isinstance(completed, int)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or completed <= 0
            or total <= completed
        ):
            raise StateBudgetError("registered checkpoint NFE partition is invalid")
        core = _same_root_base_receipt(
            unit,
            backbone=backbone,
            total_nfe=total,
            cache=cache,
        )
        total_seconds = core["synchronized_wall_seconds"]
        elapsed_seconds = total_seconds * completed / total
        remaining_seconds = total_seconds - elapsed_seconds
        cost = {
            "elapsed_nfe": float(completed),
            "elapsed_seconds": elapsed_seconds,
            "lane_request_sha256": lane,
            "remaining_nfe": float(total - completed),
            "remaining_seconds": remaining_seconds,
            "schema_version": 1,
            "total_nfe": float(total),
            "total_seconds": total_seconds,
        }
        if set(cost) != _COST_KEYS:
            raise StateBudgetError("builder cost-row projection drifted")
        cost_rows.append(cost)
        evidence_rows.append(
            {
                **core,
                "checkpoint_fraction": unit["checkpoint_fraction"],
                "elapsed_nfe": cost["elapsed_nfe"],
                "elapsed_seconds": cost["elapsed_seconds"],
                "lane_request_sha256": lane,
                "mapping": "NFE_PROPORTIONAL_SAME_ROOT_BASE_CORE_TIME_BUDGET",
                "remaining_nfe": cost["remaining_nfe"],
                "remaining_seconds": cost["remaining_seconds"],
                "schema_version": 1,
                "total_nfe": cost["total_nfe"],
                "total_seconds": cost["total_seconds"],
            }
        )
    body = {
        "axis": axis,
        "backbone": backbone,
        "human_gold_used": False,
        "row_count": len(evidence_rows),
        "rows": evidence_rows,
        "schema_version": 1,
        "status": "FROZEN_PER_UNIT_TIME_BUDGET_COMPLETE",
        "supplemental_roots_used": False,
        "tier": "INITIAL",
    }
    package = {**body, "package_sha256": sha256_json(body)}
    validated = validate_budget_package(package)
    expected_costs = {
        row["lane_request_sha256"]: {
            "elapsed_nfe": row["elapsed_nfe"],
            "elapsed_seconds": row["elapsed_seconds"],
            "lane_request_sha256": row["lane_request_sha256"],
            "remaining_nfe": row["remaining_nfe"],
            "remaining_seconds": row["remaining_seconds"],
            "schema_version": 1,
            "total_nfe": row["total_nfe"],
            "total_seconds": row["total_seconds"],
        }
        for row in validated
    }
    if any(expected_costs[row["lane_request_sha256"]] != row for row in cost_rows):
        raise StateBudgetError("builder cost rows differ from provenance evidence")
    return {
        "budget_package": package,
        "cancellation_manifest_path": str(cancellation_manifest_path.resolve(strict=True)),
        "cancellation_units_path": str(cancelled_path),
        "cost_rows": cost_rows,
        "queue_manifest_path": str(queue_manifest_path.resolve(strict=True)),
        "queue_units_path": str(queue_units_path),
        "survivor_manifest_path": str(survivor_manifest_path.resolve(strict=True)),
    }


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)


def _write_jsonl_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o444)


def publish_state_budget(
    result: Mapping[str, Any],
    *,
    config_path: Path,
    schema_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Publish immutable evidence and D-0060-compatible per-unit cost rows."""

    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    costs_path = output / "measured-costs.jsonl"
    package_path = output / "budget-evidence.json"
    _write_jsonl_exclusive(costs_path, result["cost_rows"])
    _write_json_exclusive(package_path, result["budget_package"])
    manifest = {
        "budget_evidence": {"path": str(package_path), "sha256": sha256_file(package_path)},
        "budget_schema": {
            "path": str(schema_path.resolve(strict=True)),
            "sha256": sha256_file(schema_path.resolve(strict=True)),
        },
        "config": {
            "path": str(config_path.resolve(strict=True)),
            "sha256": sha256_file(config_path.resolve(strict=True)),
        },
        "human_gold_used": False,
        "measured_costs": {
            "path": str(costs_path),
            "row_count": len(result["cost_rows"]),
            "sha256": sha256_file(costs_path),
        },
        "schema_version": 1,
        "source_bindings": {
            name: {"path": result[name], "sha256": sha256_file(Path(result[name]))}
            for name in (
                "cancellation_manifest_path",
                "cancellation_units_path",
                "queue_manifest_path",
                "queue_units_path",
                "survivor_manifest_path",
            )
        },
        "status": "ELIGIBILITY_STATE_BUDGET_ASSEMBLY_COMPLETE",
        "supplemental_roots_used": False,
        "watermark": WATERMARK,
    }
    manifest_path = output / "manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
    }

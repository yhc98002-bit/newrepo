"""Read-only, fail-closed audit of Stage-1 state-lane enforcement.

This module validates the frozen Stage-1 terminal, its flat cancellation and
survivor publications, the exact registered source queue packages, and every
explicitly supplied materialized/executed/scored state artifact tree.  It never
writes runtime evidence; the command-line surface emits its report to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scoring.common import (
    canonical_json,
    load_json,
    load_jsonl,
    require_exact_keys,
    require_sha256,
    sha256_file,
)
from stage1.gates import (
    AXES,
    BACKBONE_SLUGS,
    BACKBONES,
    plan_survivors,
    validated_bindings,
)
from stage1.terminal import Stage1TerminalError, validate_stage1_terminal

PASS = "OUTCOME_SCREEN_PASS"
STOP = "STOP_AXIS_STAGE1"
WATERMARK = "AUTOMATIC-INSTRUMENT OUTCOMES"
ROLES = ("materialized", "executed", "scored")
INITIAL_ROOTS = frozenset(range(4))
CHECKPOINTS = frozenset((0.25, 0.5, 0.75))

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA256_BYTES = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_LANE_KEY = re.compile(r"(?:^|_)lane_request_sha256s?$")
_GROUP_KEY = re.compile(r"(?:^|_)group_request_sha256s?$")
_SUPPLEMENTAL_ROOT_PATH = re.compile(r"(?:^|/)root-(?:0[4-9]|[1-9][0-9]+)(?:/|$)")
_STATE_PAYLOAD_SUFFIXES = {
    ".bin",
    ".flac",
    ".npy",
    ".npz",
    ".ogg",
    ".pt",
    ".safetensors",
    ".wav",
}
_CANCEL_LANE_KEY = "cancelled_lane_request_sha256s"
_CANCEL_GROUP_KEY = "cancelled_group_request_sha256s"
_CANCELLATION_MANIFEST_KEYS = {
    "event_count",
    "event_last_sha256",
    "human_gold_claims",
    "prohibited_operations",
    "schema_version",
    "stage1_result_path",
    "stage1_result_sha256",
    "status",
    "summary_path",
    "summary_sha256",
    "units_path",
    "units_sha256",
    "watermark",
}
_SURVIVOR_INDEX_KEYS = {
    "backbones",
    "human_gold_claims",
    "schema_version",
    "stage1_result_sha256",
    "status",
    "watermark",
}
_SURVIVOR_INDEX_RECORD_KEYS = {"manifest_path", "manifest_sha256", "unit_count"}
_SURVIVOR_MANIFEST_KEYS = {
    "automatic_instrument_outcomes",
    "backbone",
    "decision_id",
    "human_gold_claims",
    "pass_axes",
    "schema_version",
    "source_queue_path",
    "source_queue_sha256",
    "stage1_result_path",
    "stage1_result_sha256",
    "status",
    "stop_axes",
    "unit_count",
    "units_path",
    "units_sha256",
    "watermark",
}


class Stage1FinalAuditError(RuntimeError):
    """Stage-1 state evidence is incomplete, mutable, or crosses a STOP boundary."""


@dataclass(frozen=True)
class _Registry:
    source_rows: Mapping[str, Mapping[str, Any]]
    survivor_ids: frozenset[str]
    cancelled_ids: frozenset[str]
    survivor_ids_by_backbone: Mapping[str, frozenset[str]]
    cancelled_ids_by_backbone: Mapping[str, frozenset[str]]
    group_members: Mapping[str, frozenset[str]]
    survivor_groups: frozenset[str]
    cancelled_groups: frozenset[str]
    cancelled_groups_by_backbone: Mapping[str, frozenset[str]]
    source_files: frozenset[Path]
    survivor_relpaths: frozenset[str]
    cancelled_relpaths: frozenset[str]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Stage1FinalAuditError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Stage1FinalAuditError(f"{label} must be a list")
    return value


def _bound_file(path_value: Any, sha_value: Any, label: str) -> Path:
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise Stage1FinalAuditError(f"{label} path must be absolute")
    path = Path(path_value).resolve(strict=True)
    if path_value != str(path) or not path.is_file():
        raise Stage1FinalAuditError(f"{label} path is absent or noncanonical")
    expected = require_sha256(sha_value, f"{label} sha256")
    if sha256_file(path) != expected:
        raise Stage1FinalAuditError(f"{label} SHA-256 binding drifted")
    return path


def _identity(row: Mapping[str, Any], label: str) -> tuple[str, int, float]:
    unit = _mapping(row.get("eligibility_unit"), f"{label}.eligibility_unit")
    prompt = unit.get("prompt")
    root = unit.get("root")
    checkpoint = unit.get("checkpoint")
    if (
        not isinstance(prompt, str)
        or not prompt
        or isinstance(root, bool)
        or not isinstance(root, int)
        or root not in INITIAL_ROOTS
        or isinstance(checkpoint, bool)
        or not isinstance(checkpoint, (int, float))
        or float(checkpoint) not in CHECKPOINTS
    ):
        raise Stage1FinalAuditError(f"{label} is not an initial eligibility unit")
    return prompt, root, float(checkpoint)


def _row_id(row: Mapping[str, Any], label: str) -> str:
    value = row.get("lane_request_sha256")
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Stage1FinalAuditError(f"{label}.lane_request_sha256 is invalid")
    return value


def _exact_rows(
    observed: Sequence[Mapping[str, Any]], expected: Sequence[Mapping[str, Any]]
) -> bool:
    return [canonical_json(row) for row in observed] == [canonical_json(row) for row in expected]


def _validate_flat_cancellations(
    result_path: Path,
    summary_path: Path,
    cancellations: Sequence[Mapping[str, Any]],
) -> None:
    root = result_path.parent / "cancellations"
    manifest_path = root / "manifest.json"
    units_path = root / "units.jsonl"
    manifest = require_exact_keys(
        load_json(manifest_path), _CANCELLATION_MANIFEST_KEYS, "cancellation manifest"
    )
    bound_result = _bound_file(
        manifest.get("stage1_result_path"),
        manifest.get("stage1_result_sha256"),
        "cancellation result",
    )
    bound_summary = _bound_file(
        manifest.get("summary_path"), manifest.get("summary_sha256"), "cancellation summary"
    )
    bound_units = _bound_file(
        manifest.get("units_path"), manifest.get("units_sha256"), "cancellation units"
    )
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "STAGE1_CANCELLATION_MANIFEST_COMPLETE"
        or manifest.get("event_count") != len(cancellations)
        or manifest.get("event_last_sha256") != load_json(summary_path).get("last_event_sha256")
        or manifest.get("prohibited_operations") != ["EXECUTE", "SCORE"]
        or manifest.get("human_gold_claims") is not False
        or manifest.get("watermark") != WATERMARK
        or bound_result != result_path
        or bound_summary != summary_path
        or bound_units != units_path.resolve(strict=True)
        or not _exact_rows(load_jsonl(bound_units), cancellations)
    ):
        raise Stage1FinalAuditError("flat cancellation publication differs from its terminal")


def _validate_survivor_publication(
    result_path: Path,
    rows: Sequence[Mapping[str, Any]],
    queue_bindings: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, frozenset[str]]]:
    expected = plan_survivors(list(rows), list(queue_bindings))
    index_path = result_path.parent / "survivors" / "manifest.json"
    index = require_exact_keys(load_json(index_path), _SURVIVOR_INDEX_KEYS, "survivor index")
    records = _mapping(index.get("backbones"), "survivor index.backbones")
    if (
        index.get("schema_version") != 1
        or index.get("status") != "STAGE1_SURVIVOR_INDEX_COMPLETE"
        or index.get("human_gold_claims") is not False
        or index.get("watermark") != WATERMARK
        or index.get("stage1_result_sha256") != sha256_file(result_path)
        or set(records) != set(BACKBONES)
    ):
        raise Stage1FinalAuditError("survivor index identity drifted")

    queue_by_backbone = {str(row["backbone"]): row for row in queue_bindings}
    ids_by_backbone: dict[str, frozenset[str]] = {}
    for backbone in BACKBONES:
        record = require_exact_keys(
            records[backbone],
            _SURVIVOR_INDEX_RECORD_KEYS,
            f"survivor index.{backbone}",
        )
        expected_manifest = (
            result_path.parent / "survivors" / BACKBONE_SLUGS[backbone] / "manifest.json"
        ).resolve(strict=True)
        manifest_path = _bound_file(
            record.get("manifest_path"), record.get("manifest_sha256"), f"{backbone} manifest"
        )
        manifest = require_exact_keys(
            load_json(manifest_path),
            _SURVIVOR_MANIFEST_KEYS,
            f"{backbone} survivor manifest",
        )
        units_path = _bound_file(
            manifest.get("units_path"), manifest.get("units_sha256"), f"{backbone} survivor units"
        )
        source = queue_by_backbone[backbone]
        source_path = _bound_file(
            manifest.get("source_queue_path"),
            manifest.get("source_queue_sha256"),
            f"{backbone} survivor source",
        )
        pass_axes = [
            axis
            for axis in AXES
            if next(row for row in rows if row["backbone"] == backbone and row["axis"] == axis)[
                "verdict"
            ]
            == PASS
        ]
        observed_units = load_jsonl(units_path)
        expected_units = expected[backbone]
        expected_units_path = expected_manifest.parent / "units.jsonl"
        if (
            manifest_path != expected_manifest
            or units_path != expected_units_path.resolve(strict=True)
            or manifest.get("schema_version") != 1
            or manifest.get("status") != "STAGE1_SURVIVOR_MANIFEST_COMPLETE"
            or manifest.get("backbone") != backbone
            or manifest.get("decision_id") != rows[0]["decision_id"]
            or manifest.get("automatic_instrument_outcomes") is not True
            or manifest.get("human_gold_claims") is not False
            or manifest.get("watermark") != WATERMARK
            or manifest.get("pass_axes") != pass_axes
            or manifest.get("stop_axes") != [axis for axis in AXES if axis not in pass_axes]
            or manifest.get("unit_count") != len(expected_units)
            or record.get("unit_count") != len(expected_units)
            or source_path != Path(str(source["path"])).resolve(strict=True)
            or manifest.get("source_queue_sha256") != source["sha256"]
            or manifest.get("stage1_result_path") != str(result_path)
            or manifest.get("stage1_result_sha256") != sha256_file(result_path)
            or not _exact_rows(observed_units, expected_units)
        ):
            raise Stage1FinalAuditError(f"{backbone} survivor publication is not exact")
        ids = frozenset(_row_id(row, f"{backbone} survivor") for row in observed_units)
        if len(ids) != len(observed_units):
            raise Stage1FinalAuditError(f"{backbone} survivor publication contains duplicates")
        for row in observed_units:
            _identity(row, f"{backbone} survivor")
            if str(row.get("tier", "INITIAL")).upper() != "INITIAL":
                raise Stage1FinalAuditError(f"{backbone} survivor publication is supplemental")
        ids_by_backbone[backbone] = ids
    return expected, ids_by_backbone


def _manifest_binding(manifest: Mapping[str, Any], name: str, label: str) -> Path:
    record = _mapping(manifest.get(name), f"{label}.{name}")
    path = _bound_file(record.get("path"), record.get("sha256"), f"{label}.{name}")
    rows = load_jsonl(path) if path.suffix == ".jsonl" else None
    if rows is not None and record.get("row_count") != len(rows):
        raise Stage1FinalAuditError(f"{label}.{name} row count drifted")
    return path


def _relpaths(row: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for key, value in row.items():
        if (
            key.endswith("_relpath")
            and isinstance(value, str)
            and value
            and not Path(value).is_absolute()
        ):
            values.add(Path(value).as_posix())
    return values


def _validate_source_packages(
    queue_bindings: Sequence[Mapping[str, Any]],
    survivor_ids_by_backbone: Mapping[str, frozenset[str]],
    cancelled_ids_by_backbone: Mapping[str, frozenset[str]],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, frozenset[str]],
    dict[str, frozenset[str]],
    frozenset[Path],
    frozenset[str],
    frozenset[str],
]:
    source_rows: dict[str, Mapping[str, Any]] = {}
    group_members: dict[str, frozenset[str]] = {}
    cancelled_groups_by_backbone: dict[str, frozenset[str]] = {}
    source_files: set[Path] = set()
    survivor_relpaths: set[str] = set()
    cancelled_relpaths: set[str] = set()

    for binding in queue_bindings:
        backbone = str(binding["backbone"])
        units_path = Path(str(binding["path"])).resolve(strict=True)
        manifest_path = units_path.parent / "state-capture-manifest.json"
        manifest = _mapping(load_json(manifest_path), f"{backbone} source manifest")
        bound_units = _manifest_binding(manifest, "units", f"{backbone} source manifest")
        groups_path = _manifest_binding(manifest, "prefix_groups", f"{backbone} source manifest")
        actions_path = _manifest_binding(manifest, "action_map", f"{backbone} source manifest")
        folds_path = _manifest_binding(manifest, "folds", f"{backbone} source manifest")
        if (
            bound_units != units_path
            or manifest.get("tier") != "INITIAL"
            or manifest.get("eligibility_unit") != ["prompt", "root", "checkpoint"]
            or manifest.get("units", {}).get("sha256") != binding["sha256"]
        ):
            raise Stage1FinalAuditError(f"{backbone} source package identity drifted")
        units = load_jsonl(units_path)
        expected_all = survivor_ids_by_backbone[backbone] | cancelled_ids_by_backbone[backbone]
        observed: set[str] = set()
        for index, row in enumerate(units):
            identity = _row_id(row, f"{backbone} source unit[{index}]")
            _identity(row, f"{backbone} source unit[{index}]")
            if identity in source_rows or str(row.get("tier", "INITIAL")).upper() != "INITIAL":
                raise Stage1FinalAuditError("source state queue is duplicated or supplemental")
            source_rows[identity] = row
            observed.add(identity)
            target = (
                survivor_relpaths
                if identity in survivor_ids_by_backbone[backbone]
                else cancelled_relpaths
            )
            target.update(_relpaths(row))
        if observed != expected_all or len(observed) != 432:
            raise Stage1FinalAuditError(f"{backbone} source queue is not the exact partition")

        observed_group_members: set[str] = set()
        cancelled_groups: set[str] = set()
        for index, group in enumerate(load_jsonl(groups_path)):
            group_id = group.get("group_request_sha256")
            members = group.get("lane_request_sha256s")
            if (
                not isinstance(group_id, str)
                or _SHA256.fullmatch(group_id) is None
                or not isinstance(members, list)
                or len(members) != 3
                or len(set(members)) != 3
                or group_id in group_members
                or any(member not in observed for member in members)
                or str(group.get("tier", "INITIAL")).upper() != "INITIAL"
                or group.get("root_index") not in INITIAL_ROOTS
            ):
                raise Stage1FinalAuditError(f"{backbone} source group[{index}] is invalid")
            member_set = frozenset(str(member) for member in members)
            if member_set <= survivor_ids_by_backbone[backbone]:
                survivor_relpaths.update(_relpaths(group))
            elif member_set <= cancelled_ids_by_backbone[backbone]:
                cancelled_groups.add(group_id)
                cancelled_relpaths.update(_relpaths(group))
            else:
                raise Stage1FinalAuditError("a source group crosses the Stage-1 boundary")
            group_members[group_id] = member_set
            observed_group_members.update(member_set)
        if observed_group_members != observed:
            raise Stage1FinalAuditError(f"{backbone} source groups do not cover the queue")

        action_counts = {identity: 0 for identity in observed}
        for index, action in enumerate(load_jsonl(actions_path)):
            identity = _row_id(action, f"{backbone} source action[{index}]")
            if identity not in observed or str(action.get("tier", "INITIAL")).upper() != "INITIAL":
                raise Stage1FinalAuditError(f"{backbone} source action[{index}] is invalid")
            action_counts[identity] += 1
        if set(action_counts.values()) != {3}:
            raise Stage1FinalAuditError(f"{backbone} source action replication drifted")

        supplemental = manifest.get("supplemental_lock")
        allowed_supplemental: set[Path] = set()
        if supplemental is not None:
            lock_path = _manifest_binding(
                manifest, "supplemental_lock", f"{backbone} source manifest"
            )
            lock = _mapping(load_json(lock_path), f"{backbone} supplemental lock")
            if lock.get("authorized") is not False or not str(lock.get("status", "")).startswith(
                "LOCKED"
            ):
                raise Stage1FinalAuditError(f"{backbone} supplemental queue is not locked")
            allowed_supplemental.add(lock_path)
            source_files.add(lock_path)
        materialized_supplemental = {
            path.resolve() for path in units_path.parent.rglob("*supplemental*") if path.is_file()
        }
        if materialized_supplemental != allowed_supplemental:
            raise Stage1FinalAuditError(f"{backbone} has an unauthorized supplemental artifact")
        source_files.update(
            {manifest_path.resolve(), units_path, groups_path, actions_path, folds_path}
        )
        cancelled_groups_by_backbone[backbone] = frozenset(cancelled_groups)
    return (
        source_rows,
        group_members,
        cancelled_groups_by_backbone,
        frozenset(source_files),
        frozenset(survivor_relpaths),
        frozenset(cancelled_relpaths),
    )


def _build_registry(
    result_path: Path,
    rows: Sequence[Mapping[str, Any]],
    cancellations: Sequence[Mapping[str, Any]],
    queue_bindings: Sequence[Mapping[str, Any]],
) -> _Registry:
    _, survivor_ids_by_backbone = _validate_survivor_publication(result_path, rows, queue_bindings)
    cancelled_mutable: dict[str, set[str]] = {backbone: set() for backbone in BACKBONES}
    for index, row in enumerate(cancellations):
        backbone = row.get("backbone")
        if backbone not in cancelled_mutable:
            raise Stage1FinalAuditError(f"cancellation[{index}] names an unknown backbone")
        identity = _row_id(row, f"cancellation[{index}]")
        _identity(row, f"cancellation[{index}]")
        cancelled_mutable[str(backbone)].add(identity)
    cancelled_ids_by_backbone = {
        backbone: frozenset(values) for backbone, values in cancelled_mutable.items()
    }
    for backbone in BACKBONES:
        if survivor_ids_by_backbone[backbone] & cancelled_ids_by_backbone[backbone]:
            raise Stage1FinalAuditError(f"{backbone} survivor/cancellation overlap")
        if len(survivor_ids_by_backbone[backbone] | cancelled_ids_by_backbone[backbone]) != 432:
            raise Stage1FinalAuditError(f"{backbone} partition does not cover 432 initial units")
    (
        source_rows,
        group_members,
        cancelled_groups_by_backbone,
        source_files,
        survivor_relpaths,
        cancelled_relpaths,
    ) = _validate_source_packages(
        queue_bindings, survivor_ids_by_backbone, cancelled_ids_by_backbone
    )
    survivor_ids = frozenset().union(*survivor_ids_by_backbone.values())
    cancelled_ids = frozenset().union(*cancelled_ids_by_backbone.values())
    cancelled_groups = frozenset().union(*cancelled_groups_by_backbone.values())
    survivor_groups = frozenset(set(group_members) - set(cancelled_groups))
    return _Registry(
        source_rows=source_rows,
        survivor_ids=survivor_ids,
        cancelled_ids=cancelled_ids,
        survivor_ids_by_backbone=survivor_ids_by_backbone,
        cancelled_ids_by_backbone=cancelled_ids_by_backbone,
        group_members=group_members,
        survivor_groups=survivor_groups,
        cancelled_groups=cancelled_groups,
        cancelled_groups_by_backbone=cancelled_groups_by_backbone,
        source_files=source_files,
        survivor_relpaths=survivor_relpaths,
        cancelled_relpaths=cancelled_relpaths,
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, int, int, int], ...]:
    rows: list[tuple[str, int, int, int, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise Stage1FinalAuditError(f"artifact tree contains a symlink: {path}")
        metadata = path.stat(follow_symlinks=False)
        rows.append(
            (
                path.relative_to(root).as_posix(),
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
        )
    return tuple(rows)


def _json_values(path: Path, payload: bytes) -> list[Any]:
    try:
        text = payload.decode("utf-8")
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return [json.loads(text)]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Stage1FinalAuditError(f"state JSON is invalid: {path}: {exc}") from exc


def _direct_hash_values(value: Mapping[str, Any], path: Path) -> list[tuple[str, str]]:
    observed: list[tuple[str, str]] = []
    for key, child in value.items():
        if not isinstance(key, str) or not (_LANE_KEY.search(key) or _GROUP_KEY.search(key)):
            continue
        values = child if isinstance(child, list) else [child]
        if not values or any(
            not isinstance(item, str) or _SHA256.fullmatch(item) is None for item in values
        ):
            raise Stage1FinalAuditError(f"state identity {key} is invalid: {path}")
        observed.extend((key, str(item)) for item in values)
    return observed


def _exact_cancel_set(values: set[str], expected_by_backbone: Mapping[str, frozenset[str]]) -> bool:
    candidates = [set(ids) for ids in expected_by_backbone.values()]
    candidates.append(set().union(*candidates))
    return values in candidates


def _validate_json_tree(value: Any, registry: _Registry, path: Path) -> tuple[int, int]:
    lane_references = 0
    group_references = 0
    if isinstance(value, dict):
        if str(value.get("tier", "INITIAL")).upper() == "SUPPLEMENTAL":
            raise Stage1FinalAuditError(f"supplemental state row materialized: {path}")
        if "supplemental_authorized" in value and value["supplemental_authorized"] is not False:
            raise Stage1FinalAuditError(f"supplemental state authorization opened: {path}")
        status = value.get("supplemental_queue_status")
        if status is not None and not str(status).startswith("LOCKED"):
            raise Stage1FinalAuditError(f"supplemental state queue is not locked: {path}")

        refs = _direct_hash_values(value, path)
        cancel_lane_refs = {item for key, item in refs if key == _CANCEL_LANE_KEY}
        cancel_group_refs = {item for key, item in refs if key == _CANCEL_GROUP_KEY}
        if cancel_lane_refs and not _exact_cancel_set(
            cancel_lane_refs, registry.cancelled_ids_by_backbone
        ):
            raise Stage1FinalAuditError(f"partial or fabricated cancellation denylist: {path}")
        if cancel_group_refs and not _exact_cancel_set(
            cancel_group_refs, registry.cancelled_groups_by_backbone
        ):
            raise Stage1FinalAuditError(f"partial or fabricated cancelled-group denylist: {path}")

        for key, identity in refs:
            if _LANE_KEY.search(key):
                lane_references += 1
                if identity not in registry.source_rows:
                    raise Stage1FinalAuditError(f"unregistered state unit referenced: {path}")
                if identity in registry.cancelled_ids and key != _CANCEL_LANE_KEY:
                    raise Stage1FinalAuditError(f"cancelled state unit entered an artifact: {path}")
            else:
                group_references += 1
                if identity not in registry.group_members:
                    raise Stage1FinalAuditError(f"unregistered state group referenced: {path}")
                if identity in registry.cancelled_groups and key != _CANCEL_GROUP_KEY:
                    raise Stage1FinalAuditError(
                        f"cancelled state group entered an artifact: {path}"
                    )

        lane_id = value.get("lane_request_sha256")
        if isinstance(lane_id, str) and lane_id in registry.source_rows:
            source = registry.source_rows[lane_id]
            if "eligibility_unit" in value and _identity(value, str(path)) != _identity(
                source, "registered source row"
            ):
                raise Stage1FinalAuditError(f"state eligibility identity changed: {path}")
            if (
                "root_index" in value
                and value["root_index"] != _identity(source, "registered source row")[1]
            ):
                raise Stage1FinalAuditError(f"state root is not root-local: {path}")
        elif "eligibility_unit" in value:
            _identity(value, str(path))

        for child in value.values():
            child_lanes, child_groups = _validate_json_tree(child, registry, path)
            lane_references += child_lanes
            group_references += child_groups
    elif isinstance(value, list):
        for child in value:
            child_lanes, child_groups = _validate_json_tree(child, registry, path)
            lane_references += child_lanes
            group_references += child_groups
    return lane_references, group_references


def _stream_cancelled_hash(path: Path, registry: _Registry) -> str | None:
    tail = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            block = tail + chunk
            for match in _SHA256_BYTES.finditer(block):
                value = match.group().decode()
                if value in registry.cancelled_ids or value in registry.cancelled_groups:
                    return value
            tail = block[-63:]
    return None


def _path_binding(path: Path, root: Path, registry: _Registry) -> str | None:
    relative = path.relative_to(root).as_posix()
    tokens = set(path.parts)
    if tokens & registry.cancelled_ids or tokens & registry.cancelled_groups:
        return "cancelled"
    if tokens & registry.survivor_ids or tokens & registry.survivor_groups:
        return "survivor"
    if any(
        relative == item or relative.endswith(f"/{item}") for item in registry.cancelled_relpaths
    ):
        return "cancelled"
    if any(
        relative == item or relative.endswith(f"/{item}") for item in registry.survivor_relpaths
    ):
        return "survivor"
    return None


def _scan_artifact_root(role: str, root: Path, registry: _Registry) -> dict[str, Any]:
    before = _tree_snapshot(root)
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    counts = {
        "file_count": 0,
        "group_identity_references": 0,
        "lane_identity_references": 0,
        "opaque_log_file_count": 0,
        "payload_file_count": 0,
        "source_queue_files_exempted": 0,
    }
    for path in files:
        resolved = path.resolve(strict=True)
        counts["file_count"] += 1
        if resolved in registry.source_files:
            counts["source_queue_files_exempted"] += 1
            continue
        relative = path.relative_to(root).as_posix()
        if "supplemental" in relative.lower():
            raise Stage1FinalAuditError(f"unauthorized supplemental artifact exists: {path}")
        if _SUPPLEMENTAL_ROOT_PATH.search(relative):
            raise Stage1FinalAuditError(f"supplemental eligibility root exists: {path}")
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise Stage1FinalAuditError(f"artifact is not a regular file: {path}")
        relative_path = Path(relative)
        if relative_path.parts and relative_path.parts[0] == "logs":
            cancelled = _stream_cancelled_hash(path, registry)
            if cancelled is not None:
                raise Stage1FinalAuditError(
                    f"cancelled identity appears in state log: {path}"
                )
            counts["opaque_log_file_count"] += 1
        elif path.suffix in {".json", ".jsonl"}:
            payload = path.read_bytes()
            for value in _json_values(path, payload):
                lanes, groups = _validate_json_tree(value, registry, path)
                counts["lane_identity_references"] += lanes
                counts["group_identity_references"] += groups
        else:
            cancelled = _stream_cancelled_hash(path, registry)
            if cancelled is not None:
                raise Stage1FinalAuditError(f"cancelled identity appears in state artifact: {path}")
            if path.suffix.lower() in _STATE_PAYLOAD_SUFFIXES:
                counts["payload_file_count"] += 1
                binding = _path_binding(path, root, registry)
                if binding == "cancelled":
                    raise Stage1FinalAuditError(f"cancelled state payload materialized: {path}")
                if role != "scored" and binding != "survivor":
                    raise Stage1FinalAuditError(f"state payload is not bound to a survivor: {path}")
        current = path.stat(follow_symlinks=False)
        if (
            current.st_ino != metadata.st_ino
            or current.st_size != metadata.st_size
            or current.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise Stage1FinalAuditError(f"artifact changed while it was audited: {path}")
    if _tree_snapshot(root) != before:
        raise Stage1FinalAuditError(f"artifact tree changed while it was audited: {root}")
    return {"path": str(root), "role": role, **counts}


def audit_stage1_state_artifacts(
    *,
    result_path: Path,
    summary_path: Path,
    config_path: Path,
    artifact_roots: Mapping[str, Sequence[Path]],
) -> dict[str, Any]:
    """Return a deterministic audit report without writing any runtime artifact."""

    unknown_roles = set(artifact_roots) - set(ROLES)
    if unknown_roles:
        raise Stage1FinalAuditError(f"unknown artifact roles: {sorted(unknown_roles)}")
    if not any(artifact_roots.values()):
        raise Stage1FinalAuditError("at least one state artifact root is required")
    try:
        terminal = validate_stage1_terminal(
            result_path,
            summary_path,
            expected_config_path=config_path,
        )
        bindings = validated_bindings(terminal.config_path)
        _validate_flat_cancellations(
            terminal.result_path, terminal.summary_path, terminal.cancellations
        )
        registry = _build_registry(
            terminal.result_path,
            terminal.rows,
            terminal.cancellations,
            bindings["state_queues"],
        )
        resolved_roots: list[tuple[str, Path]] = []
        seen: set[Path] = set()
        for role in ROLES:
            for raw_root in artifact_roots.get(role, ()):
                root = raw_root.resolve(strict=True)
                if not root.is_dir() or root in seen:
                    raise Stage1FinalAuditError("artifact roots must be distinct directories")
                seen.add(root)
                resolved_roots.append((role, root))
        scans = [_scan_artifact_root(role, root, registry) for role, root in resolved_roots]
    except Stage1FinalAuditError:
        raise
    except Stage1TerminalError as exc:
        raise Stage1FinalAuditError(f"Stage-1 terminal validation failed: {exc}") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise Stage1FinalAuditError(f"invalid final state audit evidence: {exc}") from exc
    return {
        "artifact_roots": scans,
        "cancelled_group_count": len(registry.cancelled_groups),
        "cancelled_unit_count": len(registry.cancelled_ids),
        "read_only": True,
        "schema_version": 1,
        "stage1_result_sha256": terminal.result_sha256,
        "stage1_summary_sha256": terminal.summary_sha256,
        "status": "PASS_STAGE1_STATE_ENFORCEMENT_AUDIT",
        "supplemental_roots_executed": 0,
        "survivor_group_count": len(registry.survivor_groups),
        "survivor_unit_count": len(registry.survivor_ids),
    }


def _artifact_root(value: str) -> tuple[str, Path]:
    role, separator, raw_path = value.partition("=")
    if not separator or role not in ROLES or not raw_path:
        raise argparse.ArgumentTypeError("artifact root must be ROLE=/absolute/path")
    path = Path(raw_path)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("artifact root path must be absolute")
    return role, path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--artifact-root", action="append", required=True, type=_artifact_root)
    arguments = parser.parse_args(argv)
    roots: dict[str, list[Path]] = {role: [] for role in ROLES}
    for role, path in arguments.artifact_root:
        roots[role].append(path)
    try:
        report = audit_stage1_state_artifacts(
            result_path=arguments.result,
            summary_path=arguments.summary,
            config_path=arguments.config,
            artifact_roots=roots,
        )
    except Stage1FinalAuditError as exc:
        parser.exit(2, f"Stage-1 final audit failed: {exc}\n")
    print(canonical_json(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "Stage1FinalAuditError",
    "audit_stage1_state_artifacts",
    "main",
]

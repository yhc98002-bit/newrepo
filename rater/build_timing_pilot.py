#!/usr/bin/env python3
"""Build one immutable, blinded 8--10 item PI timing-pilot bundle."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from rater.bundle_common import (
    freeze_private_tree,
    freeze_public_tree,
    load_json_strict,
    render_bundle_html,
    require_exact_keys,
    sha256_file,
    sha256_json,
    write_json_exclusive,
)

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "timing_pilot_v2.source.json"
DEFAULT_TEMPLATE = HERE / "timing_pilot.html"
DEFAULT_SCHEMA = HERE / "schema_v2.json"
DEFAULT_OUTPUT_ROOT = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/timing-pilot-bundles"
)
DEFAULT_ADMIN_ROOT = Path(
    "/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/timing-pilot-admin"
)
ALLOWED_TASKS = frozenset({"tempo_tap", "voice_stress", "integrity_audit"})


def _validate_source(source: Any) -> list[dict[str, Any]]:
    if not isinstance(source, dict):
        raise ValueError("timing-pilot source must be a JSON object")
    require_exact_keys(
        source,
        {
            "bundle_id",
            "expected_minutes",
            "presentation_order",
            "presentations",
            "schema_version",
            "source_scope",
            "supersedes",
        },
        "timing-pilot source",
    )
    if source["schema_version"] != 2:
        raise ValueError("timing-pilot source schema_version must be 2")
    if source["source_scope"] != "retained_foundation_audio_only_no_model_calls":
        raise ValueError("timing-pilot source_scope is not the frozen foundation-only scope")
    if not isinstance(source["expected_minutes"], int) or source["expected_minutes"] != 15:
        raise ValueError("timing-pilot expected_minutes must be exactly 15")
    presentations = source["presentations"]
    if not isinstance(presentations, list) or not 8 <= len(presentations) <= 10:
        raise ValueError("timing pilot must contain 8--10 presentations")

    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(presentations):
        if not isinstance(row, dict):
            raise ValueError(f"presentation {index} must be an object")
        required = {"presentation_id", "source_path", "source_sha256", "task"}
        allowed = required | {"repeat_of"}
        if not required <= set(row) or not set(row) <= allowed:
            raise ValueError(f"presentation {index} has invalid keys")
        presentation_id = row["presentation_id"]
        if not isinstance(presentation_id, str) or not presentation_id:
            raise ValueError(f"presentation {index} has invalid ID")
        if presentation_id in by_id:
            raise ValueError("presentation IDs must be unique")
        if row["task"] not in ALLOWED_TASKS:
            raise ValueError(f"presentation {presentation_id} has invalid task")
        digest = row["source_sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"presentation {presentation_id} has invalid source hash")
        by_id[presentation_id] = row

    order = source["presentation_order"]
    if not isinstance(order, list) or any(not isinstance(item, str) for item in order):
        raise ValueError("presentation_order must be a string list")
    if len(order) != len(set(order)) or set(order) != set(by_id):
        raise ValueError("presentation_order must contain every presentation ID exactly once")
    ordered = [by_id[item] for item in order]
    order_index = {row["presentation_id"]: index for index, row in enumerate(ordered)}

    repeat_count = 0
    for row in ordered:
        repeat_of = row.get("repeat_of")
        if repeat_of is None:
            continue
        repeat_count += 1
        if repeat_of not in by_id or repeat_of == row["presentation_id"]:
            raise ValueError(f"invalid repeat_of for {row['presentation_id']}")
        original = by_id[repeat_of]
        if order_index[repeat_of] >= order_index[row["presentation_id"]]:
            raise ValueError("each hidden repeat must follow its original")
        if order_index[row["presentation_id"]] - order_index[repeat_of] <= 1:
            raise ValueError("hidden repeats must be non-adjacent")
        for key in ("source_path", "source_sha256", "task"):
            if row[key] != original[key]:
                raise ValueError(f"repeat {row['presentation_id']} differs from its original")
    if repeat_count != 2:
        raise ValueError("timing pilot must contain exactly two hidden repeats")
    return ordered


def collect_build_inputs(
    source_path: Path,
    template_path: Path,
    schema_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    source_path = source_path.resolve()
    template_path = template_path.resolve()
    schema_path = schema_path.resolve()
    source = load_json_strict(source_path)
    ordered = _validate_source(source)
    file_hashes = {
        "builder": sha256_file(Path(__file__).resolve()),
        "bundle_common": sha256_file((HERE / "bundle_common.py").resolve()),
        "rater_schema": sha256_file(schema_path),
        "source_config": sha256_file(source_path),
        "ui_template": sha256_file(template_path),
    }
    source_audio_hashes = {row["presentation_id"]: row["source_sha256"] for row in ordered}
    inputs = {
        "files": file_hashes,
        "runtime": {
            "python": platform.python_version(),
            "soundfile": version("soundfile"),
        },
        "schema_version": 2,
        "source_audio_sha256": source_audio_hashes,
    }
    return source, inputs, ordered


def _validate_audio_sources(ordered: list[dict[str, Any]]) -> None:
    checked: set[Path] = set()
    for row in ordered:
        source_audio = Path(row["source_path"]).resolve()
        observed = sha256_file(source_audio)
        if observed != row["source_sha256"]:
            raise ValueError(f"source hash mismatch for {row['presentation_id']}")
        if source_audio in checked:
            continue
        info = sf.info(source_audio)
        if abs(float(info.duration) - 30.0) > 1e-6 or info.channels != 2:
            raise ValueError(f"pilot source must be 30-second stereo: {source_audio}")
        audio, _sample_rate = sf.read(source_audio, dtype="float32", always_2d=True)
        if audio.shape[1] != 2 or not np.isfinite(audio).all():
            raise ValueError(f"pilot source must be finite stereo: {source_audio}")
        if float(np.max(np.abs(audio))) <= 1e-8:
            raise ValueError(f"pilot source must be non-silent: {source_audio}")
        checked.add(source_audio)


def _write_text_exclusive(path: Path, text: str, mode: int) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, mode)


def build(
    source_path: Path,
    output_root: Path,
    *,
    admin_root: Path = DEFAULT_ADMIN_ROOT,
    template_path: Path = DEFAULT_TEMPLATE,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    source, build_inputs, ordered = collect_build_inputs(source_path, template_path, schema_path)
    _validate_audio_sources(ordered)
    build_identity = sha256_json(build_inputs)
    bundle_id = str(source["bundle_id"])
    directory_name = f"{bundle_id}-{build_identity[:12]}"
    bundle_dir = output_root.resolve() / directory_name
    admin_dir = admin_root.resolve() / directory_name
    if bundle_dir.exists() or admin_dir.exists():
        raise FileExistsError(f"pilot bundle/admin destination already exists: {directory_name}")
    bundle_dir.mkdir(parents=True, exist_ok=False)
    admin_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    audio_dir = bundle_dir / "audio"
    audio_dir.mkdir()

    public_rows: list[dict[str, Any]] = []
    admin_rows: list[dict[str, Any]] = []
    public_tree_entries: list[dict[str, Any]] = []
    for index, row in enumerate(ordered, start=1):
        source_audio = Path(row["source_path"]).resolve()
        blinded_name = f"item-{index:03d}.wav"
        relative_audio = f"audio/{blinded_name}"
        destination = audio_dir / blinded_name
        with source_audio.open("rb") as source_handle, destination.open("xb") as out_handle:
            shutil.copyfileobj(source_handle, out_handle, length=1024 * 1024)
        copied_hash = sha256_file(destination)
        if copied_hash != row["source_sha256"]:
            raise RuntimeError(f"copied hash mismatch for {destination}")
        os.chmod(destination, 0o444)
        item_id = f"item-{index:03d}"
        public_rows.append({"audio": relative_audio, "item_id": item_id, "task": row["task"]})
        admin_rows.append(
            {
                "audio_sha256": copied_hash,
                "item_id": item_id,
                "presentation_id": row["presentation_id"],
                "repeat_of_presentation_id": row.get("repeat_of"),
                "source_path": str(source_audio),
                "task": row["task"],
            }
        )
        public_tree_entries.append(
            {
                "path": relative_audio,
                "sha256": copied_hash,
                "size_bytes": destination.stat().st_size,
            }
        )

    public_bundle = {
        "build_identity_sha256": build_identity,
        "bundle_id": bundle_id,
        "expected_minutes": source["expected_minutes"],
        "items": public_rows,
        "purpose": "BLINDED_TIMING_PILOT",
        "response_schema_version": 2,
        "schema_version": 2,
    }
    bundle_path = bundle_dir / "bundle.json"
    write_json_exclusive(bundle_path, public_bundle)
    public_tree_entries.append(
        {
            "path": "bundle.json",
            "sha256": sha256_file(bundle_path),
            "size_bytes": bundle_path.stat().st_size,
        }
    )

    rendered_html = render_bundle_html(template_path.resolve(), public_bundle)
    index_path = bundle_dir / "index.html"
    _write_text_exclusive(index_path, rendered_html, 0o444)
    public_tree_entries.append(
        {
            "path": "index.html",
            "sha256": sha256_file(index_path),
            "size_bytes": index_path.stat().st_size,
        }
    )

    readme_path = bundle_dir / "README.txt"
    _write_text_exclusive(
        readme_path,
        "Open index.html directly in a browser (file:// is supported). Complete all nine "
        "presentations and use Export response JSON. Return only that response JSON.\n",
        0o444,
    )
    public_tree_entries.append(
        {
            "path": "README.txt",
            "sha256": sha256_file(readme_path),
            "size_bytes": readme_path.stat().st_size,
        }
    )

    public_tree_hash = sha256_json(sorted(public_tree_entries, key=lambda item: item["path"]))
    public_manifest = {
        "build_identity_sha256": build_identity,
        "bundle_id": bundle_id,
        "file_count_excluding_manifest": len(public_tree_entries),
        "item_count": len(public_rows),
        "public_tree_sha256": public_tree_hash,
        "schema_version": 2,
        "status": "TIMING_PILOT_OFFERED_AWAITING_PI_RESPONSE",
    }
    public_manifest_path = bundle_dir / "manifest.json"
    write_json_exclusive(public_manifest_path, public_manifest)

    admin_map = {
        "build_inputs": build_inputs,
        "build_identity_sha256": build_identity,
        "bundle_id": bundle_id,
        "bundle_json_sha256": sha256_file(bundle_path),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "items": admin_rows,
        "public_manifest_sha256": sha256_file(public_manifest_path),
        "public_tree_entries": sorted(public_tree_entries, key=lambda item: item["path"]),
        "public_tree_sha256": public_tree_hash,
        "schema_version": 2,
        "source_config_path": str(source_path.resolve()),
        "source_config_sha256": build_inputs["files"]["source_config"],
        "supersedes": source["supersedes"],
    }
    admin_map_path = admin_dir / "admin-map.json"
    write_json_exclusive(admin_map_path, admin_map, mode=0o400)

    freeze_public_tree(bundle_dir)
    freeze_private_tree(admin_dir)
    return {
        **public_manifest,
        "admin_dir": str(admin_dir),
        "admin_map_sha256": sha256_file(admin_map_path),
        "audio_generation_calls": 0,
        "bundle_dir": str(bundle_dir),
        "bundle_json_sha256": sha256_file(bundle_path),
        "index_html_sha256": sha256_file(index_path),
        "public_manifest_sha256": sha256_file(public_manifest_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--admin-root", type=Path, default=DEFAULT_ADMIN_ROOT)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build(
        args.source,
        args.output_root,
        admin_root=args.admin_root,
        template_path=args.template,
        schema_path=args.schema,
    )
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

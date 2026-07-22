"""CPU-only run preparation and post-commit launch authorization claims."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backbones.sao_operational_claims import (
    SaoOperationalAuthorizationError,
    consume_sao_core_run_claim,
    validate_sao_core_run_claim,
    verify_exact_sao_core_decision,
)
from benchmark_core.config import (
    SAO_MODEL_ID,
    CoreExecutionConfig,
    load_core_execution_config,
    sha256_file,
)
from benchmark_core.queue import EXPECTED_OUTPUTS_PER_READY_BACKBONE, build_queue, load_queue
from benchmark_core.state_queue import build_state_capture_queue, load_state_capture_queue

REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAO_OPERATIONAL_CLAIMS_SOURCE = (
    Path(__file__).resolve().parents[1] / "backbones" / "sao_operational_claims.py"
)


class LaunchAuthorizationError(RuntimeError):
    """The checkout or append-only decision does not authorize a launch."""


@dataclass(frozen=True)
class GitLaunchState:
    head: str
    origin_main: str


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def observe_clean_origin_main(repo_root: Path) -> GitLaunchState:
    """Require a clean checkout at the already-observed origin/main ref; no fetch occurs."""

    root = repo_root.resolve()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise LaunchAuthorizationError("launch checkout is not clean")
    head = _git(root, "rev-parse", "HEAD")
    origin = _git(root, "rev-parse", "refs/remotes/origin/main")
    if REVISION_RE.fullmatch(head) is None or REVISION_RE.fullmatch(origin) is None:
        raise LaunchAuthorizationError("Git revision identity is invalid")
    if head != origin:
        raise LaunchAuthorizationError("HEAD does not equal the observed origin/main ref")
    return GitLaunchState(head=head, origin_main=origin)


def _decision_block(text: str, decision_id: str) -> str:
    lines = text.splitlines()
    starts = [
        index for index, line in enumerate(lines) if line.startswith("## ") and decision_id in line
    ]
    if len(starts) != 1:
        raise LaunchAuthorizationError("launch decision ID must identify exactly one entry")
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def verify_decision_authorization(
    decisions_path: Path,
    *,
    decision_id: str,
    frozen_files: Sequence[Path],
) -> dict[str, str]:
    """Require an append-only decision binding every exact launch input hash."""

    block = _decision_block(decisions_path.read_text(encoding="utf-8"), decision_id)
    if "BENCHMARK_CORE_GENERATION_AUTHORIZED = YES" not in block:
        raise LaunchAuthorizationError("decision does not authorize benchmark generation")
    if re.search(r"\b(?:PLACEHOLDER|PENDING|TBD|ESTIMATE)\b", block, re.IGNORECASE):
        raise LaunchAuthorizationError("authorization decision contains unresolved placeholders")
    identities: dict[str, str] = {}
    identities[f"DECISION_BLOCK::{decision_id}"] = hashlib.sha256(block.encode()).hexdigest()
    for path in frozen_files:
        source = path.resolve(strict=True)
        digest = sha256_file(source)
        if source.name not in block or digest not in block:
            raise LaunchAuthorizationError(
                f"decision does not bind {source.name} at SHA-256 {digest}"
            )
        identities[str(source)] = digest
    return identities


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    for directory in (path.parent, path.parent.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _queue_binding(
    manifest: Mapping[str, Any], manifest_path: Path, *, run_dir: Path
) -> dict[str, Any]:
    """Bind both queue and manifest bytes under the exact external run root."""

    root = run_dir.resolve()
    resolved_manifest = manifest_path.resolve(strict=True)
    queue_value = manifest.get("queue_path")
    if not isinstance(queue_value, str):
        raise LaunchAuthorizationError("queue manifest lacks queue_path")
    resolved_queue = Path(queue_value).resolve(strict=True)
    for source in (resolved_manifest, resolved_queue):
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise LaunchAuthorizationError(
                "queue artifact escapes the launch run directory"
            ) from exc
    queue_sha = sha256_file(resolved_queue)
    if manifest.get("queue_sha256") != queue_sha:
        raise LaunchAuthorizationError("queue bytes drifted before launch claim creation")
    row_count = manifest.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
        raise LaunchAuthorizationError("queue manifest has an invalid row count")
    return {
        "manifest_path": str(resolved_manifest),
        "manifest_sha256": sha256_file(resolved_manifest),
        "queue_path": str(resolved_queue),
        "queue_sha256": queue_sha,
        "row_count": row_count,
    }


def create_external_launch_claim(
    path: Path,
    *,
    run_id: str,
    git_state: GitLaunchState,
    config: CoreExecutionConfig,
    decision_id: str,
    frozen_file_sha256: Mapping[str, str],
    run_dir: Path,
    queue_bindings: Mapping[str, Mapping[str, Any]],
    global_authority_claim: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind observed clean Git state after commit without self-reference."""

    if config.authorized_model_ids == (SAO_MODEL_ID,) and global_authority_claim is None:
        raise LaunchAuthorizationError("SAO launch lacks its global one-shot authority claim")
    claim = {
        "authorized_model_ids": list(config.authorized_model_ids),
        "claimed_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config.source_path),
        "config_sha256": config.source_sha256,
        "decision_id": decision_id,
        "frozen_file_sha256": dict(frozen_file_sha256),
        "git_head": git_state.head,
        "git_origin_main": git_state.origin_main,
        "queue_bindings": {key: dict(value) for key, value in sorted(queue_bindings.items())},
        "run_dir": str(run_dir.resolve()),
        "run_id": run_id,
        "schema_version": 2,
        "status": "AUTHORIZED_CLEAN_ORIGIN_MAIN",
    }
    if global_authority_claim is not None:
        claim["global_authority_claim_path"] = str(global_authority_claim["path"])
        claim["global_authority_claim_sha256"] = str(global_authority_claim["sha256"])
    _write_json_exclusive(path, claim)
    return claim


def validate_external_launch_claim(
    path: Path,
    *,
    run_id: str,
    config_sha256: str,
    git_commit: str,
    run_dir: Path,
    authorized_model_ids: Sequence[str],
) -> dict[str, Any]:
    """Validate the immutable claim required by every worker process."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LaunchAuthorizationError("launch claim is not an object")
    expected = {
        "status": "AUTHORIZED_CLEAN_ORIGIN_MAIN",
        "run_id": run_id,
        "config_sha256": config_sha256,
        "git_head": git_commit,
        "git_origin_main": git_commit,
        "run_dir": str(run_dir.resolve()),
        "schema_version": 2,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise LaunchAuthorizationError(f"launch claim mismatch: {key}")
    if value.get("authorized_model_ids") != list(authorized_model_ids):
        raise LaunchAuthorizationError("launch claim authorized-model allowlist mismatch")
    if tuple(authorized_model_ids) == (SAO_MODEL_ID,):
        global_path_value = value.get("global_authority_claim_path")
        global_sha256 = value.get("global_authority_claim_sha256")
        frozen_identities = value.get("frozen_file_sha256")
        decision_id = value.get("decision_id")
        if (
            not isinstance(global_path_value, str)
            or not isinstance(global_sha256, str)
            or not isinstance(frozen_identities, dict)
            or not isinstance(decision_id, str)
        ):
            raise LaunchAuthorizationError("SAO launch claim lacks global authority binding")
        decision_block_sha256 = frozen_identities.get(f"DECISION_BLOCK::{decision_id}")
        if not isinstance(decision_block_sha256, str):
            raise LaunchAuthorizationError("SAO launch claim lacks decision-block identity")
        global_path = Path(global_path_value)
        try:
            if sha256_file(global_path.resolve(strict=True)) != global_sha256:
                raise LaunchAuthorizationError("SAO global authority claim hash mismatch")
            validate_sao_core_run_claim(
                global_path,
                run_id=run_id,
                run_dir=run_dir,
                config_sha256=config_sha256,
                decision_id=decision_id,
                decision_block_sha256=decision_block_sha256,
                git_commit=git_commit,
            )
        except (OSError, SaoOperationalAuthorizationError) as exc:
            raise LaunchAuthorizationError(str(exc)) from exc
    bindings = value.get("queue_bindings")
    if not isinstance(bindings, dict) or set(bindings) != {
        "generation",
        "state_capture_initial",
        "state_capture_supplemental",
    }:
        raise LaunchAuthorizationError("launch claim queue bindings are incomplete")
    return value


def validate_run_bundle(
    run_dir: Path,
    manifest: Mapping[str, Any],
    launch_claim: Mapping[str, Any],
    *,
    config: CoreExecutionConfig,
) -> dict[str, dict[str, Any]]:
    """Recompute every claimed queue/manifest hash before a worker can load."""

    root = run_dir.resolve(strict=True)
    if manifest.get("status") != "PREPARED_NO_MODEL_CALLS":
        raise LaunchAuthorizationError("run manifest is not PREPARED_NO_MODEL_CALLS")
    if manifest.get("run_id") != launch_claim.get("run_id"):
        raise LaunchAuthorizationError("run manifest/claim run ID mismatch")
    if manifest.get("config_sha256") != config.source_sha256:
        raise LaunchAuthorizationError("run manifest/config identity mismatch")
    if manifest.get("git_commit") != launch_claim.get("git_head"):
        raise LaunchAuthorizationError("run manifest/claim Git identity mismatch")
    expected_authorized = list(config.authorized_model_ids)
    if manifest.get("authorized_model_ids") != expected_authorized:
        raise LaunchAuthorizationError("run manifest authorized-model allowlist mismatch")
    if launch_claim.get("authorized_model_ids") != expected_authorized:
        raise LaunchAuthorizationError("launch claim authorized-model allowlist mismatch")
    if tuple(config.authorized_model_ids) == (SAO_MODEL_ID,):
        for field in ("global_authority_claim_path", "global_authority_claim_sha256"):
            if manifest.get(field) != launch_claim.get(field):
                raise LaunchAuthorizationError(
                    f"SAO run manifest/global authority binding mismatch: {field}"
                )
    bindings = launch_claim.get("queue_bindings")
    assert isinstance(bindings, dict)  # validated by validate_external_launch_claim
    sources = {
        "generation": "generation_queue_manifest",
        "state_capture_initial": "state_capture_initial_manifest",
        "state_capture_supplemental": "state_capture_supplemental_manifest",
    }
    validated: dict[str, dict[str, Any]] = {}
    for name, manifest_key in sources.items():
        record = manifest.get(manifest_key)
        binding = bindings.get(name)
        if not isinstance(record, dict) or not isinstance(binding, dict):
            raise LaunchAuthorizationError(f"run bundle lacks {name}")
        manifest_path = Path(str(binding.get("manifest_path", ""))).resolve(strict=True)
        queue_path = Path(str(binding.get("queue_path", ""))).resolve(strict=True)
        for path in (manifest_path, queue_path):
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise LaunchAuthorizationError(f"{name} path escapes run directory") from exc
        if sha256_file(manifest_path) != binding.get("manifest_sha256"):
            raise LaunchAuthorizationError(f"{name} manifest hash mismatch")
        if sha256_file(queue_path) != binding.get("queue_sha256"):
            raise LaunchAuthorizationError(f"{name} queue hash mismatch")
        disk_record = json.loads(manifest_path.read_text(encoding="utf-8"))
        if disk_record != record:
            raise LaunchAuthorizationError(f"{name} manifest bytes disagree with run manifest")
        if record.get("queue_path") != str(queue_path):
            raise LaunchAuthorizationError(f"{name} queue path mismatch")
        if record.get("queue_sha256") != binding.get("queue_sha256"):
            raise LaunchAuthorizationError(f"{name} queue identity mismatch")
        if record.get("row_count") != binding.get("row_count"):
            raise LaunchAuthorizationError(f"{name} row count mismatch")
        validated[name] = dict(binding)
    expected_generation_counts = {
        model_id: EXPECTED_OUTPUTS_PER_READY_BACKBONE
        for model_id in config.authorized_model_ids
    }
    generation_manifest = manifest["generation_queue_manifest"]
    if generation_manifest.get("model_row_counts") != expected_generation_counts:
        raise LaunchAuthorizationError("generation queue model counts drift from allowlist")
    if generation_manifest.get("row_count") != sum(expected_generation_counts.values()):
        raise LaunchAuthorizationError("generation queue row count drift")
    expected_state_count = 432 * len(config.state_capture.eligible_model_ids)
    for key in ("state_capture_initial_manifest", "state_capture_supplemental_manifest"):
        state_manifest = manifest[key]
        expected_state_model_counts = {
            model_id: 432 for model_id in config.state_capture.eligible_model_ids
        }
        if state_manifest.get("model_row_counts") != expected_state_model_counts:
            raise LaunchAuthorizationError("state queue model counts drift from capable set")
        if state_manifest.get("row_count") != expected_state_count:
            raise LaunchAuthorizationError("state queue row count drift")
    if manifest["state_capture_initial_manifest"].get("authorization_status") != (
        "CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION"
    ):
        raise LaunchAuthorizationError("initial state queue is not closed")
    if manifest["state_capture_supplemental_manifest"].get("authorization_status") != (
        "SUPPLEMENTAL_LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
    ):
        raise LaunchAuthorizationError("supplemental state queue is not locked")
    generation_rows = load_queue(Path(validated["generation"]["queue_path"]))
    if {row["model_id"] for row in generation_rows} != set(config.authorized_model_ids):
        raise LaunchAuthorizationError("generation queue contains an unauthorized model")
    load_state_capture_queue(Path(validated["state_capture_initial"]["queue_path"]))
    load_state_capture_queue(Path(validated["state_capture_supplemental"]["queue_path"]))
    return validated


def prepare_run(
    config_path: Path,
    *,
    run_id: str,
    decisions_path: Path,
    decision_id: str,
    frozen_files: Sequence[Path],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Create immutable queues and launch claim; never import an adapter or probe CUDA."""

    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run_id contains unsafe characters")
    config = load_core_execution_config(config_path, repo_root=repo_root)
    git_state = observe_clean_origin_main(config.repo_root)
    dynamic_files = [config.source_path, config.phase_b_terminal.path]
    dynamic_files.extend(
        model.adapter_config_path
        for model in config.models
        if model.model_id in config.authorized_model_ids
        and model.adapter_config_path is not None
    )
    dynamic_files.extend(binding.path for binding in config.prior_model_completions.values())
    if config.authorized_model_ids == (SAO_MODEL_ID,):
        dynamic_files.append(SAO_OPERATIONAL_CLAIMS_SOURCE)
    exact_frozen_files = tuple(
        dict.fromkeys(path.resolve(strict=True) for path in (*dynamic_files, *frozen_files))
    )
    identities = verify_decision_authorization(
        decisions_path.resolve(strict=True),
        decision_id=decision_id,
        frozen_files=exact_frozen_files,
    )
    run_dir = config.run_root / run_id
    global_authority_claim: dict[str, Any] | None = None
    if config.authorized_model_ids == (SAO_MODEL_ID,):
        decision_identity = identities.get(f"DECISION_BLOCK::{decision_id}")
        assert decision_identity is not None
        try:
            verify_exact_sao_core_decision(
                decisions_path,
                decision_id=decision_id,
                requested_run_id=run_id,
                expected_decision_block_sha256=decision_identity,
            )
            global_authority_claim = consume_sao_core_run_claim(
                run_id=run_id,
                run_dir=run_dir,
                run_root=config.run_root,
                config_path=config.source_path,
                config_sha256=config.source_sha256,
                decisions_path=decisions_path,
                decision_id=decision_id,
                decision_block_sha256=decision_identity,
                git_commit=git_state.head,
            )
        except SaoOperationalAuthorizationError as exc:
            raise LaunchAuthorizationError(str(exc)) from exc
    run_dir.mkdir(parents=True, exist_ok=False)
    for directory in (run_dir, run_dir.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    generation_manifest = build_queue(
        config.source_path,
        run_dir / "queues" / "generation",
        authorized_model_ids=config.authorized_model_ids,
    )
    generation_rows = load_queue(Path(generation_manifest["queue_path"]))
    state_source_rows = list(generation_rows)
    generation_model_ids = {row["model_id"] for row in generation_rows}
    for model_id in config.state_capture.eligible_model_ids:
        if model_id in generation_model_ids:
            continue
        completion = config.prior_model_completions.get(model_id)
        if completion is None:
            raise LaunchAuthorizationError(
                "state-capable excluded model lacks a verified prior generation queue"
            )
        try:
            observed_queue_sha256 = sha256_file(completion.generation_queue_path)
        except OSError as exc:
            raise LaunchAuthorizationError(
                "prior completion generation queue is unavailable at state-row reread"
            ) from exc
        if observed_queue_sha256 != completion.generation_queue_sha256:
            raise LaunchAuthorizationError(
                "prior completion generation queue drifted after config validation"
            )
        state_source_rows.extend(load_queue(completion.generation_queue_path))
    initial_state_manifest = build_state_capture_queue(
        state_source_rows,
        config.state_capture,
        run_dir / "queues" / "state-capture-initial",
        root_indices=config.state_capture.initial_root_indices,
        tier="INITIAL",
        authorization_status="CLOSED_AWAITING_SEPARATE_STATE_AUTHORIZATION",
    )
    supplemental_state_manifest = build_state_capture_queue(
        state_source_rows,
        config.state_capture,
        run_dir / "queues" / "state-capture-supplemental",
        root_indices=config.state_capture.doubling_root_indices,
        tier="SUPPLEMENTAL",
        authorization_status=(
            "SUPPLEMENTAL_LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED"
        ),
    )
    queue_bindings = {
        "generation": _queue_binding(
            generation_manifest,
            Path(generation_manifest["queue_path"]).parent / "queue-manifest.json",
            run_dir=run_dir,
        ),
        "state_capture_initial": _queue_binding(
            initial_state_manifest,
            Path(initial_state_manifest["queue_path"]).parent / "state-capture-manifest.json",
            run_dir=run_dir,
        ),
        "state_capture_supplemental": _queue_binding(
            supplemental_state_manifest,
            Path(supplemental_state_manifest["queue_path"]).parent / "state-capture-manifest.json",
            run_dir=run_dir,
        ),
    }
    claim_path = run_dir / "control" / "launch-claim.json"
    launch_claim = create_external_launch_claim(
        claim_path,
        run_id=run_id,
        git_state=git_state,
        config=config,
        decision_id=decision_id,
        frozen_file_sha256=identities,
        run_dir=run_dir,
        queue_bindings=queue_bindings,
        global_authority_claim=global_authority_claim,
    )
    manifest = {
        "audio_generation_calls": 0,
        "authorized_model_ids": list(config.authorized_model_ids),
        "config_sha256": config.source_sha256,
        "generation_queue_manifest": generation_manifest,
        "git_commit": git_state.head,
        "launch_claim_sha256": hashlib.sha256(claim_path.read_bytes()).hexdigest(),
        "run_id": run_id,
        "schema_version": 1,
        "state_capture_initial_manifest": initial_state_manifest,
        "state_capture_supplemental_manifest": supplemental_state_manifest,
        "status": "PREPARED_NO_MODEL_CALLS",
    }
    if global_authority_claim is not None:
        manifest["global_authority_claim_path"] = global_authority_claim["path"]
        manifest["global_authority_claim_sha256"] = global_authority_claim["sha256"]
    _write_json_exclusive(run_dir / "run-manifest.json", manifest)
    validate_external_launch_claim(
        claim_path,
        run_id=run_id,
        config_sha256=config.source_sha256,
        git_commit=git_state.head,
        run_dir=run_dir,
        authorized_model_ids=config.authorized_model_ids,
    )
    validate_run_bundle(run_dir, manifest, launch_claim, config=config)
    assert launch_claim["status"] == "AUTHORIZED_CLEAN_ORIGIN_MAIN"
    return manifest

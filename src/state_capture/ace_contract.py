"""Frozen contract and authorization gates for the ACE state preflight.

This module is deliberately CPU-only and side-effect free.  Loading a contract
does not inspect CUDA, create a claim, write a run directory, or import the ACE
runtime.  The production runner performs those operations only after an
external post-freeze authorization has been validated.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCOPE = "ACE_STEP_V1_STATE_PREFLIGHT_NON_BENCHMARK"
AUTHORIZATION_ID = "ACE-STATE-PREFLIGHT-V2-ONE-ATTEMPT"
RUN_ID = "ace-state-preflight-v2-001"
ATTEMPT_ID = "ace-state-preflight-v2-attempt-001"
EXECUTE_PHRASE = "I_UNDERSTAND_THIS_CONSUMES_THE_ONLY_ACE_STATE_PREFLIGHT_ATTEMPT"
MODEL_ID = "ACE-Step/ACE-Step-v1-3.5B"
CHECKPOINT_FRACTIONS = (0.25, 0.5, 0.75)
CHECKPOINT_COMPLETED_TRANSITIONS = (9, 15, 20)
CHECKPOINT_CUMULATIVE_NFE = (11, 23, 33)
TOTAL_TRANSITIONS = 30
TOTAL_TRANSFORMER_NFE = 45
MAX_MODEL_CALLS = 4
MAX_GENERATIONS_ABSOLUTE = 8
MAX_GPU_SECONDS = 600.0
MAX_RETRIES = 0
OUTER_SOFT_TIMEOUT_SECONDS = 599
OUTER_KILL_GRACE_SECONDS = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

PACKAGE_RELATIVE_PATHS = (
    "configs/ace_state_preflight_v2.json",
    "scripts/prepare_ace_state_preflight_v2.py",
    "scripts/run_ace_state_preflight_v2.py",
    "scripts/run_ace_state_preflight_v2_with_timeout.py",
    "src/state_capture/ace_artifacts.py",
    "src/state_capture/ace_child.py",
    "src/state_capture/ace_contract.py",
    "src/state_capture/ace_engine.py",
    "src/state_capture/ace_runner.py",
)

REQUIRED_DECISION_ASSIGNMENTS = {
    "ACE_STATE_PREFLIGHT_V2_AUTHORIZED": "YES",
    "ACE_STATE_PREFLIGHT_V2_ATTEMPTS": "1",
    "ACE_STATE_PREFLIGHT_V2_MAX_GENERATIONS": "8",
    "ACE_STATE_PREFLIGHT_V2_MAX_GPU_SECONDS": "600",
    "ACE_STATE_PREFLIGHT_V2_RETRIES": "0",
    "ACE_STATE_PREFLIGHT_V2_RUN_ID": RUN_ID,
}


class AceContractError(ValueError):
    """A frozen input, authorization, or identity failed validation."""


@dataclass(frozen=True)
class LoadedContract:
    """A validated static configuration and the identities it binds."""

    path: Path
    raw: Mapping[str, Any]
    sha256: str
    frozen_source_hashes: Mapping[str, str]


@dataclass(frozen=True)
class Authorization:
    """A validated external authority for the sole production attempt."""

    path: Path
    raw: Mapping[str, Any]
    sha256: str
    attempt_token_sha256: str
    git_commit: str
    node: str
    physical_gpu_id: int


def canonical_json_bytes(value: Any, *, trailing_newline: bool = False) -> bytes:
    """Serialize finite JSON with one canonical encoding."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AceContractError(f"value is not finite JSON: {exc}") from exc
    return encoded + (b"\n" if trailing_newline else b"")


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AceContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_object(path: str | Path) -> dict[str, Any]:
    """Load strict JSON, rejecting duplicate keys and non-finite constants."""

    source = Path(path)
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AceContractError(f"non-finite JSON token: {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AceContractError(f"cannot load strict JSON object {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise AceContractError(f"JSON root must be an object: {source}")
    return value


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AceContractError(f"{name} must be an object")
    return value


def _require_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise AceContractError(f"{name} must be lowercase SHA-256")
    return value


def _require_commit(value: Any, name: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise AceContractError(f"{name} must be a lowercase 40-hex Git commit")
    return value


def _parse_utc(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise AceContractError(f"{name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AceContractError(f"{name} is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AceContractError(f"{name} must carry UTC timezone")
    return parsed


def _repo_file(repository_root: Path, relative: Any, name: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise AceContractError(f"{name}.path must be repository-relative")
    root = repository_root.resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AceContractError(f"{name}.path escapes the repository") from exc
    if not path.is_file():
        raise AceContractError(f"{name}.path is not a file")
    return path


def _validate_source_records(
    records: Any, repository_root: Path
) -> dict[str, str]:
    expected_paths = {
        "ace_adapter": "src/backbones/ace_step_v1.py",
        "ace_backbone_config": "configs/backbones/ace_step_v1.json",
        "benchmark_prereg_v2": "BENCHMARK_PREREG_v2.md",
        "incremental_core_config": "configs/benchmark_core_v2_ace_incremental.json",
        "phase_b_terminal_amendment": (
            "provenance/b2/build_status_terminal_v2_ace_amendment.json"
        ),
        "statistics_v2": "configs/statistics_v2.json",
    }
    source_records = _require_mapping(records, "frozen_sources")
    if set(source_records) != set(expected_paths):
        raise AceContractError("frozen_sources key set changed")
    observed: dict[str, str] = {}
    for name, expected_path in expected_paths.items():
        record = _require_mapping(source_records[name], f"frozen_sources.{name}")
        if record.get("path") != expected_path:
            raise AceContractError(f"frozen_sources.{name}.path changed")
        path = _repo_file(repository_root, record.get("path"), f"frozen_sources.{name}")
        expected_sha = _require_sha256(record.get("sha256"), f"frozen_sources.{name}.sha256")
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise AceContractError(
                f"frozen source {name} SHA-256 mismatch: {actual_sha} != {expected_sha}"
            )
        observed[name] = actual_sha
    return observed


def _nearest_checkpoint_mapping(total_steps: int, guidance_start: int, guidance_end: int) -> tuple[
    tuple[int, ...], tuple[int, ...]
]:
    cumulative: list[int] = []
    used = 0
    for index in range(total_steps):
        used += 2 if guidance_start <= index < guidance_end else 1
        cumulative.append(used)
    selected_steps: list[int] = []
    selected_nfe: list[int] = []
    total_nfe = cumulative[-1]
    for fraction in CHECKPOINT_FRACTIONS:
        target = fraction * total_nfe
        # min is stable, so an exact tie selects the earlier post-transition state.
        index = min(range(total_steps), key=lambda item: abs(cumulative[item] - target))
        selected_steps.append(index + 1)
        selected_nfe.append(cumulative[index])
    return tuple(selected_steps), tuple(selected_nfe)


def validate_static_config(
    config_path: str | Path,
    *,
    repository_root: str | Path,
) -> LoadedContract:
    """Validate the inert package without importing ACE or touching CUDA."""

    root = Path(repository_root).resolve(strict=True)
    path = Path(config_path).resolve(strict=True)
    config = load_json_object(path)
    if config.get("schema_version") != 1 or config.get("scope") != SCOPE:
        raise AceContractError("unexpected ACE state-preflight schema or scope")
    if config.get("protocol_status") != "PREPARED_NOT_AUTHORIZED":
        raise AceContractError("static config must remain PREPARED_NOT_AUTHORIZED")

    run = _require_mapping(config.get("run"), "run")
    if (
        run.get("run_id") != RUN_ID
        or run.get("attempt_id") != ATTEMPT_ID
        or run.get("authorization_scope") != SCOPE
    ):
        raise AceContractError("fixed run/attempt identity changed")

    authorization = _require_mapping(config.get("authorization"), "authorization")
    expected_authorization = {
        "authorization_id": AUTHORIZATION_ID,
        "execution_authorized_by_this_config_alone": False,
        "external_authorization_max_age_seconds": 86400,
        "required_execute_phrase": EXECUTE_PHRASE,
        "requires_clean_main_equal_origin_main": True,
        "requires_postfreeze_decision": True,
        "requires_seed_registry_row": True,
    }
    if authorization != expected_authorization:
        raise AceContractError("authorization gate changed")

    caps = _require_mapping(config.get("caps"), "caps")
    required_caps = {
        "exact_model_calls_if_completed": 4,
        "exact_retained_audio_outputs_if_completed": 4,
        "max_clip_seconds_requested": 30.0,
        "max_generations_absolute": MAX_GENERATIONS_ABSOLUTE,
        "max_gpu_seconds": MAX_GPU_SECONDS,
        "max_gpus": 1,
        "max_model_calls": MAX_MODEL_CALLS,
        "max_retries": MAX_RETRIES,
        "max_state_exports": 3,
        "tensor_parallel_width": 1,
        "replica_count": 1,
    }
    if caps != required_caps:
        raise AceContractError("four-call/600-GPU-second/no-retry caps changed")
    if caps["max_model_calls"] > caps["max_generations_absolute"]:
        raise AceContractError("model-call schedule exceeds absolute generation ceiling")

    checkpoint = _require_mapping(config.get("checkpoint_contract"), "checkpoint_contract")
    if tuple(checkpoint.get("capture_fractions", ())) != CHECKPOINT_FRACTIONS:
        raise AceContractError("checkpoint fractions are not exactly 25/50/75 percent")
    if checkpoint.get("total_scheduler_transitions") != TOTAL_TRANSITIONS:
        raise AceContractError("frozen scheduler transition budget changed")
    if checkpoint.get("total_transformer_nfe") != TOTAL_TRANSFORMER_NFE:
        raise AceContractError("frozen transformer budget changed")
    mapped_steps, mapped_nfe = _nearest_checkpoint_mapping(
        TOTAL_TRANSITIONS,
        int(checkpoint.get("guidance_start_index_inclusive", -1)),
        int(checkpoint.get("guidance_end_index_exclusive", -1)),
    )
    if mapped_steps != CHECKPOINT_COMPLETED_TRANSITIONS or mapped_nfe != CHECKPOINT_CUMULATIVE_NFE:
        raise AceContractError("internal frozen ACE NFE mapping constant is inconsistent")
    if tuple(checkpoint.get("completed_scheduler_transitions", ())) != mapped_steps:
        raise AceContractError("checkpoint transition mapping changed")
    if tuple(checkpoint.get("next_scheduler_indices", ())) != mapped_steps:
        raise AceContractError("checkpoint resume indices changed")
    if tuple(checkpoint.get("cumulative_transformer_nfe", ())) != mapped_nfe:
        raise AceContractError("checkpoint NFE mapping changed")
    if checkpoint.get("export_dtype") != "float32":
        raise AceContractError("checkpoint export dtype must remain float32")

    generation = _require_mapping(config.get("frozen_generation"), "frozen_generation")
    expected_generation = {
        "audio_duration_seconds": 30.0,
        "cfg_type": "cfg",
        "format": "wav",
        "guidance_interval": 0.5,
        "guidance_interval_decay": 0.0,
        "guidance_scale": 5.0,
        "inference_steps": 30,
        "lyrics": "",
        "min_guidance_scale": 3.0,
        "omega_scale": 10.0,
        "sample_rate": 48000,
        "scheduler_shift": 3.0,
        "scheduler_type": "euler",
        "use_erg_diffusion": False,
        "use_erg_lyric": False,
        "use_erg_tag": False,
    }
    if generation != expected_generation:
        raise AceContractError("frozen ACE generation settings changed")

    equivalence = _require_mapping(config.get("equivalence"), "equivalence")
    if equivalence.get("max_absolute_error") != 1e-5:
        raise AceContractError("max-absolute equivalence tolerance changed")
    if equivalence.get("minimum_snr_db") != 80.0:
        raise AceContractError("SNR equivalence tolerance changed")
    if equivalence.get("require_separate_process_per_checkpoint") is not True:
        raise AceContractError("separate-process resume requirement was disabled")

    boundary = _require_mapping(config.get("scientific_boundary"), "scientific_boundary")
    if boundary != {
        "benchmark_endpoint": False,
        "formal_section_11_capture": False,
        "human_packet_member": False,
        "instrument_evaluation_allowed": False,
        "pass_effect": "TECHNICAL_CAPABILITY_ONLY_REQUIRES_SEPARATE_PREREGISTERED_STATE_SCREEN",
        "state_queue_access": "FORBIDDEN",
    }:
        raise AceContractError("scientific boundary changed")

    engine = _require_mapping(config.get("engine"), "engine")
    if engine.get("model_id") != MODEL_ID:
        raise AceContractError("ACE model identity changed")
    for key in (
        "checkpoint_tree_sha256",
        "upstream_pipeline_sha256",
        "upstream_scheduler_sha256",
    ):
        _require_sha256(engine.get(key), f"engine.{key}")
    _require_commit(engine.get("source_commit"), "engine.source_commit")
    _require_commit(engine.get("source_tree"), "engine.source_tree")

    placement = _require_mapping(config.get("placement"), "placement")
    if placement.get("allowed_nodes") != ["an12", "an29"]:
        raise AceContractError("allowed node set changed")
    if placement.get("node_priority") != ["an12", "an29"]:
        raise AceContractError("node priority changed; an12 must remain first")
    if placement.get("candidate_physical_gpu_ids") != [4, 5, 6, 7]:
        raise AceContractError("candidate GPU set changed")
    if placement.get("logical_gpu_id") != 0:
        raise AceContractError("process-visible GPU must remain logical cuda:0")
    if "WAIT_OR_FAIL_WITHOUT_SIGNALING" not in str(placement.get("nonpreemption_policy")):
        raise AceContractError("nonpreemption policy changed")

    frozen_hashes = _validate_source_records(config.get("frozen_sources"), root)
    prereg = (root / "BENCHMARK_PREREG_v2.md").read_text(encoding="utf-8")
    normalized_prereg = " ".join(prereg.split())
    for needle in (
        "true state is tested at 25%, 50%, and 75%",
        "A failed true resume makes the axis/backbone screen `NOT_IDENTIFIABLE`",
        "Ordinary core workers cannot claim or consume either state queue",
    ):
        if needle not in normalized_prereg:
            raise AceContractError(f"frozen preregistration contract is absent: {needle}")
    statistics = load_json_object(root / "configs/statistics_v2.json")
    state_contract = statistics.get("eligibility", {}).get("state_capture_contract", {})
    if state_contract.get("capture_fractions") != list(CHECKPOINT_FRACTIONS):
        raise AceContractError("statistics state-capture fractions drifted")
    if state_contract.get("source_condition") != "BASE":
        raise AceContractError("statistics state source is no longer BASE-only")
    incremental = load_json_object(root / "configs/benchmark_core_v2_ace_incremental.json")
    state = incremental.get("execution", {}).get("state_capture", {})
    if state.get("ordinary_core_launch_status") != "CLOSED_AT_ORDINARY_CORE_LAUNCH":
        raise AceContractError("ordinary core config no longer keeps state queues closed")

    return LoadedContract(
        path=path,
        raw=config,
        sha256=sha256_file(path),
        frozen_source_hashes=frozen_hashes,
    )


def capture_git_evidence(repository_root: str | Path) -> dict[str, Any]:
    """Return clean-main/origin evidence without changing repository state."""

    root = Path(repository_root).resolve(strict=True)

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()

    head = git("rev-parse", "HEAD")
    origin = git("rev-parse", "origin/main")
    branch = git("branch", "--show-current")
    porcelain = git("status", "--porcelain", "--untracked-files=all")
    return {
        "branch": branch,
        "head": head,
        "origin_main": origin,
        "status_porcelain": porcelain,
        "clean_main_equal_origin_main": branch == "main" and head == origin and not porcelain,
    }


def _latest_assignment(text: str, key: str) -> str | None:
    pattern = re.compile(rf"^`{re.escape(key)}\s*=\s*([^`]+)`\s*$", re.MULTILINE)
    matches = pattern.findall(text)
    return matches[-1].strip() if matches else None


def seed_registry_has_proposed_row(repository_root: str | Path, request: Mapping[str, Any]) -> bool:
    registry = Path(repository_root) / "SEED_REGISTRY.md"
    expected = (
        f"| {request['seed_id']} | {request['seed']} | ACE-Step v1 state preflight "
        "reference/export/resume equivalence, non-benchmark | none |"
    )
    return expected in registry.read_text(encoding="utf-8")


def inspect_postfreeze_decision(
    repository_root: str | Path, *, config_sha256: str
) -> dict[str, Any]:
    """Read exact latest D-0031 assignments without granting execution authority."""

    path = Path(repository_root) / "DECISIONS.md"
    text = path.read_text(encoding="utf-8")
    expected = {
        **REQUIRED_DECISION_ASSIGNMENTS,
        "ACE_STATE_PREFLIGHT_V2_CONFIG_SHA256": config_sha256,
    }
    observed = {key: _latest_assignment(text, key) for key in expected}
    heading_present = "## D-0031 — Sole ACE-Step v1 state-capability preflight opened" in text
    exact = heading_present and observed == expected
    return {
        "status": "PASS" if exact else "ABSENT_OR_MISMATCHED",
        "decision_id": "D-0031",
        "path": str(path.resolve(strict=True)),
        "sha256": sha256_file(path),
        "heading_present": heading_present,
        "expected_latest_assignments": expected,
        "observed_latest_assignments": observed,
        "exact_latest_assignments_present": exact,
        "execution_authority_effect": "NONE_WITHOUT_COMPLETED_EXTERNAL_AUTHORIZATION",
    }


def authorization_token_identity(
    authorization: Mapping[str, Any], *, config_sha256: str
) -> dict[str, Any]:
    """Return the fixed identity whose digest is consumed by the one-shot seal."""

    decision = _require_mapping(authorization.get("decision"), "authorization.decision")
    seed_registry = _require_mapping(
        authorization.get("seed_registry"), "authorization.seed_registry"
    )
    placement = _require_mapping(authorization.get("placement"), "authorization.placement")
    return {
        "authorization_id": AUTHORIZATION_ID,
        "scope": SCOPE,
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "config_sha256": config_sha256,
        "git_commit": authorization.get("git_commit"),
        "decision_sha256": decision.get("sha256"),
        "seed_registry_sha256": seed_registry.get("sha256"),
        "node": placement.get("node"),
        "physical_gpu_id": placement.get("physical_gpu_id"),
    }


def validate_external_authorization(
    authorization_path: str | Path,
    *,
    contract: LoadedContract,
    repository_root: str | Path,
    now: datetime | None = None,
    git_evidence: Mapping[str, Any] | None = None,
) -> Authorization:
    """Validate a completed post-freeze authorization outside the repository."""

    root = Path(repository_root).resolve(strict=True)
    path = Path(authorization_path).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        raise AceContractError("completed authorization must be outside the repository")
    authorization = load_json_object(path)
    expected_scalars = {
        "schema_version": 1,
        "authorization_id": AUTHORIZATION_ID,
        "scope": SCOPE,
        "execution_authorized": True,
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "config_sha256": contract.sha256,
        "engine_factory": contract.raw["engine"]["production_factory"],
    }
    for key, expected in expected_scalars.items():
        if authorization.get(key) != expected:
            raise AceContractError(f"external authorization {key} changed")
    if authorization.get("caps") != contract.raw["caps"]:
        raise AceContractError("external authorization caps changed")
    if authorization.get("reference_request") != contract.raw["proposed_reference_request"]:
        raise AceContractError("external authorization request changed")

    authorized_at = _parse_utc(authorization.get("authorized_at_utc"), "authorized_at_utc")
    expires_at = _parse_utc(authorization.get("expires_at_utc"), "expires_at_utc")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise AceContractError("authorization validation time must be timezone-aware")
    maximum_age = int(contract.raw["authorization"]["external_authorization_max_age_seconds"])
    if not authorized_at <= observed_now <= expires_at:
        raise AceContractError("external authorization is not currently valid")
    if expires_at <= authorized_at or (expires_at - authorized_at).total_seconds() > maximum_age:
        raise AceContractError("authorization lifetime must be positive and at most 24 hours")

    observed_git = dict(git_evidence or capture_git_evidence(root))
    if observed_git.get("clean_main_equal_origin_main") is not True:
        raise AceContractError("production requires clean main equal to origin/main")
    commit = _require_commit(authorization.get("git_commit"), "authorization.git_commit")
    if observed_git.get("head") != commit:
        raise AceContractError("authorization Git commit differs from live clean origin/main")

    packages = _require_mapping(authorization.get("package_sha256"), "package_sha256")
    if set(packages) != set(PACKAGE_RELATIVE_PATHS):
        raise AceContractError("authorization package hash key set changed")
    for relative in PACKAGE_RELATIVE_PATHS:
        expected = _require_sha256(packages.get(relative), f"package_sha256.{relative}")
        actual = sha256_file(_repo_file(root, relative, f"package_sha256.{relative}"))
        if actual != expected:
            raise AceContractError(f"authorized package file drifted: {relative}")

    decision = _require_mapping(authorization.get("decision"), "decision")
    if decision.get("path") != "DECISIONS.md":
        raise AceContractError("authorization decision path changed")
    decision_path = _repo_file(root, decision.get("path"), "decision")
    decision_sha = _require_sha256(decision.get("sha256"), "decision.sha256")
    if sha256_file(decision_path) != decision_sha:
        raise AceContractError("authorization decision hash differs from live DECISIONS.md")
    decision_text = decision_path.read_text(encoding="utf-8")
    assignments = {
        **REQUIRED_DECISION_ASSIGNMENTS,
        "ACE_STATE_PREFLIGHT_V2_CONFIG_SHA256": contract.sha256,
    }
    for key, expected in assignments.items():
        if _latest_assignment(decision_text, key) != expected:
            raise AceContractError(f"post-freeze decision assignment is absent: {key}={expected}")

    request = _require_mapping(
        authorization.get("reference_request"), "authorization.reference_request"
    )
    if not seed_registry_has_proposed_row(root, request):
        raise AceContractError("exact append-only S-0010 seed-registry row is absent")
    seed_record = _require_mapping(authorization.get("seed_registry"), "seed_registry")
    if seed_record.get("path") != "SEED_REGISTRY.md":
        raise AceContractError("authorization seed-registry path changed")
    registry_path = _repo_file(root, seed_record.get("path"), "seed_registry")
    registry_sha = _require_sha256(seed_record.get("sha256"), "seed_registry.sha256")
    if sha256_file(registry_path) != registry_sha:
        raise AceContractError("authorization seed-registry hash differs from live registry")

    placement = _require_mapping(authorization.get("placement"), "placement")
    node = placement.get("node")
    physical_gpu_id = placement.get("physical_gpu_id")
    if node not in contract.raw["placement"]["allowed_nodes"]:
        raise AceContractError("authorization node is not allowed")
    if (
        isinstance(physical_gpu_id, bool)
        or physical_gpu_id not in contract.raw["placement"]["candidate_physical_gpu_ids"]
    ):
        raise AceContractError("authorization physical GPU must be one of prioritized 4..7")
    if placement.get("logical_gpu_id") != 0:
        raise AceContractError("authorization must expose the selected GPU as logical zero")
    if placement.get("tensor_parallel_width") != 1 or placement.get("replica_count") != 1:
        raise AceContractError("authorization placement must remain TP1 with one replica")
    justification = placement.get("placement_justification")
    if not isinstance(justification, str) or not justification.strip():
        raise AceContractError("authorization placement justification is absent")

    identity = authorization_token_identity(authorization, config_sha256=contract.sha256)
    token = json_sha256(identity)
    if authorization.get("attempt_token_sha256") != token:
        raise AceContractError("authorization one-attempt token does not match its bound identity")

    return Authorization(
        path=path,
        raw=authorization,
        sha256=sha256_file(path),
        attempt_token_sha256=token,
        git_commit=commit,
        node=str(node),
        physical_gpu_id=int(physical_gpu_id),
    )


def static_readiness_report(
    contract: LoadedContract, *, repository_root: str | Path
) -> dict[str, Any]:
    """Explain what is ready and what deliberately blocks model execution."""

    request = contract.raw["proposed_reference_request"]
    seed_present = seed_registry_has_proposed_row(repository_root, request)
    git = capture_git_evidence(repository_root)
    decision = inspect_postfreeze_decision(
        repository_root, config_sha256=contract.sha256
    )
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "status": "PREPARED_NOT_AUTHORIZED",
        "model_calls": 0,
        "generated_outputs": 0,
        "state_queue_accessed": False,
        "static_contract_sha256": contract.sha256,
        "checkpoint_fractions": list(CHECKPOINT_FRACTIONS),
        "checkpoint_completed_transitions": list(CHECKPOINT_COMPLETED_TRANSITIONS),
        "checkpoint_cumulative_nfe": list(CHECKPOINT_CUMULATIVE_NFE),
        "caps": dict(contract.raw["caps"]),
        "git": git,
        "postfreeze_decision": decision,
        "reference_request_registration": {
            "seed_id": request["seed_id"],
            "seed": request["seed"],
            "registration_status": request["registration_status"],
            "append_only_seed_registry_row_present": seed_present,
            "authorizing_decision": "D-0031",
        },
        "blocking_gates": [
            gate
            for gate, blocked in (
                (
                    "POSTFREEZE_DECISION_ABSENT",
                    not decision["exact_latest_assignments_present"],
                ),
                ("EXTERNAL_AUTHORIZATION_ABSENT", True),
                ("S0010_SEED_REGISTRY_ROW_ABSENT", not seed_present),
                ("CLEAN_MAIN_EQUAL_ORIGIN_MAIN_ABSENT", not git["clean_main_equal_origin_main"]),
            )
            if blocked
        ],
        "scientific_boundary": dict(contract.raw["scientific_boundary"]),
    }


def finite_nonnegative(value: Any, name: str) -> float:
    """Validate a finite non-negative measurement."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AceContractError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise AceContractError(f"{name} must be finite and non-negative")
    return result


def ensure_exact_string_list(value: Any, expected: Sequence[str], name: str) -> None:
    if not isinstance(value, list) or value != list(expected):
        raise AceContractError(f"{name} changed")

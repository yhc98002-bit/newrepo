"""Replay-proof claim for the repaired SAO three-call engineering smoke.

This claim is separate from the consumed D-0037/D-0042 claims.  It binds one
new run ID to the retained v2-002 failure, the CPU-validated dedicated runtime,
the unchanged scientific request schedule, and one append-only decision block.
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backbones.sao_environment import (
    EXPECTED_INFERENCE_IMPORT_PATCH_SHA256,
    EXPECTED_SAO_REVISION,
    EXPECTED_STABLE_AUDIO_TOOLS_LORA_ORIGINAL_SHA256,
    EXPECTED_STABLE_AUDIO_TOOLS_LORA_PATCHED_SHA256,
)
from backbones.sao_operational_claims import (
    GIT_REVISION_RE,
    RUN_ID_RE,
    SAO_MINI_SMOKE_SEED_SCHEDULE,
    SAO_MODEL_ID,
    SHA256_RE,
    SaoOperationalAuthorizationError,
    _canonical_json,
    _claim_identity,
    _decision_block,
    _path_entry_exists,
    _preparation_identity,
    _sha256_file,
    _single_decision_assignment,
    _strict_json_object,
    _utc_now,
    _verify_clean_main_revision,
    _write_json_o_excl,
)

RUNTIME_ROOT = Path("/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime")
SAO_ENGINEERING_RETRY_RUN_ID = "sao-mini-smoke-v2-003"
SAO_ENGINEERING_RETRY_RUN_DIR = (
    RUNTIME_ROOT / "runs/sao-live-v2/mini-smoke" / SAO_ENGINEERING_RETRY_RUN_ID
)
SAO_ENGINEERING_RETRY_CLAIM_PATH = (
    RUNTIME_ROOT / "claims/sao-live-v2/sao-mini-smoke-v2-003.engineering-repair.claim.json"
)
SAO_RUNTIME_AUTHORIZATION_PATH = (
    RUNTIME_ROOT / "claims/sao-live-v2/sao-mini-smoke-v2-001.runtime-authorization.json"
)
SAO_RUNTIME_AUTHORIZATION_SHA256 = (
    "b6a0be60366701465482c9a0991cd5008c4f9935806466d657885936068fb09e"
)
SAO_ENGINEERING_ENVIRONMENT_PATH = RUNTIME_ROOT / "environments/sao-v2/sao-env-v2-002"
SAO_ENGINEERING_ENVIRONMENT_MANIFEST = (
    RUNTIME_ROOT / "runs/sao-live-v2/engineering/sao-engineering-env-v2-002/"
    "provenance/environment-manifest.json"
)
SAO_ENGINEERING_ENVIRONMENT_MANIFEST_SHA256 = (
    "45a688fc8fb13cb81abc3da1267c0d90d6475244ca342ac30df9173ba2dc4e4f"
)
SAO_ENGINEERING_CPU_FACTORY_FAILURE = (
    RUNTIME_ROOT / "runs/sao-live-v2/engineering/sao-engineering-env-v2-001/"
    "provenance/cpu-factory-failure.json"
)
SAO_ENGINEERING_CPU_FACTORY_FAILURE_SHA256 = (
    "cb7df87510b2314361b2d5fa177fbc196870d64962d82ce27e994f9781c0a6ac"
)
SAO_PREVIOUS_MINI_SMOKE_TERMINAL = (
    RUNTIME_ROOT / "runs/sao-live-v2/mini-smoke/sao-mini-smoke-v2-002/sao-mini-smoke-terminal.json"
)
SAO_PREVIOUS_MINI_SMOKE_TERMINAL_SHA256 = (
    "3944b835ee5224b9b2156ff8049fc4d641fdf7da95b13acbb6814af65da17097"
)
SAO_DECISIONS_PATH = Path(__file__).resolve().parents[2] / "DECISIONS.md"
SAO_ENGINEERING_RETRY_DECISION_ID = "D-0050"
SAO_ENGINEERING_RETRY_DECISION_BLOCK_SHA256 = (
    "a14e4a2db3b2a968c480a453c549e9f5389ced392d1507c0cad004c8bd6d9845"
)
SAO_ENGINEERING_RETRY_CLAIM_SHA256 = (
    "173c6bd534730e8da01aa5b3c5afef73b709389ed1c39a6d64a328c1c7ce4f7c"
)
DECISION_ID_RE = re.compile(r"^D-[A-Za-z0-9._-]+$")

_CLAIM_KEYS = {
    "access_receipt_sha256",
    "authorized_calls",
    "authorized_max_clip_seconds",
    "authorized_max_gpus",
    "authorized_seed_schedule",
    "backbone_config_sha256",
    "claim_identity_sha256",
    "claimed_at_utc",
    "cpu_factory_failure_path",
    "cpu_factory_failure_sha256",
    "decision_block_sha256",
    "decision_id",
    "decisions_path",
    "engineering_failures_repairable",
    "environment_manifest_identity_sha256",
    "environment_manifest_path",
    "environment_manifest_sha256",
    "environment_path",
    "future_engineering_retry_requires_new_run_and_claim",
    "git_commit",
    "live_config_path",
    "live_config_sha256",
    "model_id",
    "previous_terminal_path",
    "previous_terminal_sha256",
    "prompts_seeds_budgets_changed",
    "run_dir",
    "run_id",
    "runtime_authorization_path",
    "runtime_authorization_sha256",
    "schema_version",
    "scientific_configuration_changed",
    "scope",
    "status",
}


def _require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SaoOperationalAuthorizationError(f"invalid SAO engineering hash: {field}")
    return value


def _strict_file(path: Path, expected_sha256: str, context: str) -> tuple[Path, dict[str, Any]]:
    if not path.is_absolute() or path.is_symlink():
        raise SaoOperationalAuthorizationError(f"{context} path is not canonical")
    source, value = _strict_json_object(path)
    if source != path:
        raise SaoOperationalAuthorizationError(f"{context} path is not canonical")
    if _sha256_file(source) != expected_sha256:
        raise SaoOperationalAuthorizationError(f"{context} hash mismatch")
    return source, value


def validate_sao_engineering_environment(
    path: Path = SAO_ENGINEERING_ENVIRONMENT_MANIFEST,
    *,
    require_live_prefix: bool = True,
) -> dict[str, Any]:
    """Validate the complete CPU gate and the exact inference-only repair."""

    source, value = _strict_file(
        path, SAO_ENGINEERING_ENVIRONMENT_MANIFEST_SHA256, "SAO environment manifest"
    )
    if source != SAO_ENGINEERING_ENVIRONMENT_MANIFEST.resolve(strict=True):
        raise SaoOperationalAuthorizationError("SAO environment manifest path drifted")
    identity = value.get("manifest_identity_sha256")
    unhashed = dict(value)
    unhashed.pop("manifest_identity_sha256", None)
    expected_identity = hashlib.sha256(_canonical_json(unhashed).encode()).hexdigest()
    if identity != expected_identity:
        raise SaoOperationalAuthorizationError("SAO environment manifest identity mismatch")
    expected_top = {
        "status": "CPU_VALIDATED_READY_FOR_GOVERNED_MINI_SMOKE",
        "network_used": False,
        "token_used": False,
        "gpu_used": False,
        "generation_calls": 0,
        "inference_import_patch_sha256": EXPECTED_INFERENCE_IMPORT_PATCH_SHA256,
    }
    for field, expected in expected_top.items():
        if value.get(field) != expected:
            raise SaoOperationalAuthorizationError(f"SAO environment manifest mismatch: {field}")
    imports = value.get("import_probe")
    factory = value.get("factory_probe")
    if not isinstance(imports, dict) or not isinstance(factory, dict):
        raise SaoOperationalAuthorizationError("SAO CPU probes are absent")
    if (
        imports.get("passed") is not True
        or imports.get("status") != "PASS"
        or imports.get("failures") != []
    ):
        raise SaoOperationalAuthorizationError("SAO CPU import probe did not pass")
    closure = imports.get("closure")
    if not isinstance(closure, dict) or closure.get("passed") is not True:
        raise SaoOperationalAuthorizationError("SAO dependency closure did not pass")
    if (
        closure.get("abi_pair", {}).get("numpy") != "1.26.4"
        or closure.get("abi_pair", {}).get("pywavelets") != "1.4.1"
    ):
        raise SaoOperationalAuthorizationError("SAO NumPy/PyWavelets ABI pair drifted")
    lora = imports.get("stable_audio_tools_lora_init")
    if (
        not isinstance(lora, dict)
        or lora.get("original_sha256") != EXPECTED_STABLE_AUDIO_TOOLS_LORA_ORIGINAL_SHA256
        or lora.get("patched_sha256") != EXPECTED_STABLE_AUDIO_TOOLS_LORA_PATCHED_SHA256
    ):
        raise SaoOperationalAuthorizationError("SAO inference import patch evidence drifted")
    expected_factory = {
        "status": "PASS",
        "resolved_provider_revision": EXPECTED_SAO_REVISION,
        "checkpoint_loaded": False,
        "generation_calls": 0,
        "cuda_available": False,
        "sample_rate": 44_100,
        "parameter_count": 1_213_337_474,
    }
    for field, expected in expected_factory.items():
        if factory.get(field) != expected:
            raise SaoOperationalAuthorizationError(f"SAO CPU factory mismatch: {field}")
    environment_path = Path(str(imports.get("sys_prefix", ""))).resolve()
    if environment_path != SAO_ENGINEERING_ENVIRONMENT_PATH.resolve():
        raise SaoOperationalAuthorizationError("SAO environment prefix drifted")
    if require_live_prefix and Path(sys.prefix).resolve() != environment_path:
        raise SaoOperationalAuthorizationError(
            "SAO runner is not executing in the CPU-validated dedicated environment"
        )
    freeze = Path(str(value.get("package_freeze_path", "")))
    freeze_sha256 = _require_hash(value.get("package_freeze_sha256"), "package freeze")
    if not freeze.is_absolute() or freeze.is_symlink() or _sha256_file(freeze) != freeze_sha256:
        raise SaoOperationalAuthorizationError("SAO package freeze changed after CPU validation")
    return {
        **value,
        "path": str(source),
        "sha256": _sha256_file(source),
        "environment_path": str(environment_path),
    }


def validate_sao_engineering_failure_lineage() -> dict[str, Any]:
    """Bind the retry to both retained pre-scientific failures."""

    terminal_path, terminal = _strict_file(
        SAO_PREVIOUS_MINI_SMOKE_TERMINAL,
        SAO_PREVIOUS_MINI_SMOKE_TERMINAL_SHA256,
        "SAO prior mini-smoke terminal",
    )
    expected_terminal = {
        "status": "FAILED_STOPPED_NO_RETRY",
        "run_id": "sao-mini-smoke-v2-002",
        "error_type": "ValueError",
        "model_calls": 1,
        "generated_outputs": 0,
        "benchmark_endpoints_scored": 0,
        "human_gold_claims": False,
    }
    for field, expected in expected_terminal.items():
        if terminal.get(field) != expected:
            raise SaoOperationalAuthorizationError(f"SAO prior terminal mismatch: {field}")
    rows = terminal.get("rows")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("status") != "MODEL_CALL_FAILED":
        raise SaoOperationalAuthorizationError("SAO prior failure row drifted")

    failure_path, failure = _strict_file(
        SAO_ENGINEERING_CPU_FACTORY_FAILURE,
        SAO_ENGINEERING_CPU_FACTORY_FAILURE_SHA256,
        "SAO CPU factory failure",
    )
    expected_failure = {
        "status": "FAILED_ENGINEERING_REPAIRABLE",
        "failure_phase": "CPU_MODEL_FACTORY_IMPORT_BEFORE_GRAPH_CONSTRUCTION",
        "error_type": "ModuleNotFoundError",
        "missing_module": "pytorch_lightning",
        "checkpoint_loaded": False,
        "model_graph_constructed": False,
        "gpu_used": False,
        "generation_calls": 0,
        "generated_audio": 0,
        "network_used": False,
        "token_used": False,
    }
    for field, expected in expected_failure.items():
        if failure.get(field) != expected:
            raise SaoOperationalAuthorizationError(f"SAO CPU failure mismatch: {field}")
    return {
        "previous_terminal_path": str(terminal_path),
        "previous_terminal_sha256": _sha256_file(terminal_path),
        "cpu_factory_failure_path": str(failure_path),
        "cpu_factory_failure_sha256": _sha256_file(failure_path),
    }


def sao_engineering_retry_decision_assignments() -> dict[str, str]:
    """Return the exact append-only opening vocabulary for run v2-003."""

    root = Path(__file__).resolve().parents[2]
    return {
        "SAO_ENGINEERING_REPAIR_AUTHORIZED": "YES",
        "SAO_ENGINEERING_REPAIR_RUN_ID": SAO_ENGINEERING_RETRY_RUN_ID,
        "SAO_ENGINEERING_REPAIR_CLAIM_PATH": str(SAO_ENGINEERING_RETRY_CLAIM_PATH),
        "SAO_ENGINEERING_REPAIR_EXACT_CALLS": "3",
        "SAO_ENGINEERING_REPAIR_MAX_CLIP_SECONDS": "30",
        "SAO_ENGINEERING_REPAIR_MAX_GPUS": "1",
        "SAO_ENGINEERING_REPAIR_MODEL_ID": SAO_MODEL_ID,
        "SAO_ENGINEERING_REPAIR_OFFICIAL_REVISION": EXPECTED_SAO_REVISION,
        "SAO_ENGINEERING_REPAIR_ENVIRONMENT_MANIFEST_SHA256": (
            SAO_ENGINEERING_ENVIRONMENT_MANIFEST_SHA256
        ),
        "SAO_ENGINEERING_REPAIR_PREVIOUS_TERMINAL_SHA256": (
            SAO_PREVIOUS_MINI_SMOKE_TERMINAL_SHA256
        ),
        "SAO_ENGINEERING_REPAIR_CPU_FAILURE_SHA256": (SAO_ENGINEERING_CPU_FACTORY_FAILURE_SHA256),
        "SAO_ENGINEERING_REPAIR_SCIENTIFIC_CONFIGURATION_CHANGED": "NO",
        "SAO_ENGINEERING_REPAIR_PROMPTS_SEEDS_BUDGETS_CHANGED": "NO",
        "SAO_ENGINEERING_FAILURES_REPAIRABLE": "YES",
        "SAO_ENGINEERING_FUTURE_RETRY_REQUIRES_NEW_RUN_AND_CLAIM": "YES",
        "SAO_ENGINEERING_REPAIR_RUNNER_SHA256": _sha256_file(
            root / "scripts/run_sao_engineering_retry_v2.py"
        ),
        "SAO_ENGINEERING_REPAIR_CLAIMS_SHA256": _sha256_file(
            root / "src/backbones/sao_engineering_retry.py"
        ),
        "SAO_ENGINEERING_REPAIR_SMOKE_SHA256": _sha256_file(
            root / "src/backbones/sao_mini_smoke.py"
        ),
        "SAO_ENGINEERING_REPAIR_ADAPTER_SHA256": _sha256_file(
            root / "src/backbones/stable_audio_open.py"
        ),
        "SAO_ENGINEERING_REPAIR_IMPORT_PATCH_SHA256": _sha256_file(
            root / "environment/sao/stable_audio_tools_inference_import.patch"
        ),
    }


def verify_sao_engineering_retry_decision(
    decisions_path: Path,
    *,
    decision_id: str,
    expected_decision_block_sha256: str,
) -> dict[str, str]:
    """Verify one exact opening without assuming the lead's next decision number."""

    if DECISION_ID_RE.fullmatch(decision_id) is None:
        raise SaoOperationalAuthorizationError("SAO engineering decision ID is invalid")
    if decisions_path.is_symlink():
        raise SaoOperationalAuthorizationError("SAO engineering decision may not be a symlink")
    try:
        source = decisions_path.resolve(strict=True)
        if source != SAO_DECISIONS_PATH.resolve(strict=True):
            raise SaoOperationalAuthorizationError(
                "SAO engineering decision is not repository DECISIONS.md"
            )
        block = _decision_block(source.read_text(encoding="utf-8"), decision_id)
    except SaoOperationalAuthorizationError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoOperationalAuthorizationError(
            "SAO engineering decision file is unavailable"
        ) from exc
    block_sha256 = hashlib.sha256(block.encode()).hexdigest()
    if (
        SHA256_RE.fullmatch(expected_decision_block_sha256) is None
        or block_sha256 != expected_decision_block_sha256
    ):
        raise SaoOperationalAuthorizationError("SAO engineering decision block changed")
    for key, expected in sao_engineering_retry_decision_assignments().items():
        if _single_decision_assignment(block, key) != expected:
            raise SaoOperationalAuthorizationError(f"SAO engineering decision mismatch: {key}")
    return {
        "decision_id": decision_id,
        "decision_block_sha256": block_sha256,
        "decisions_path": str(source),
    }


def _runtime_authorization(path: Path) -> tuple[Path, dict[str, Any]]:
    source, value = _strict_file(
        path, SAO_RUNTIME_AUTHORIZATION_SHA256, "SAO runtime authorization"
    )
    if source != SAO_RUNTIME_AUTHORIZATION_PATH.resolve(strict=True):
        raise SaoOperationalAuthorizationError("SAO runtime authorization path drifted")
    expected = {
        "status": "ACCESS_RECEIPT_VERIFIED_AND_GENERATION_AUTHORIZED",
        "decision_id": "D-0037",
        "schema_version": 1,
        "max_generations": 3,
        "max_clip_seconds": 30,
        "max_gpus": 1,
    }
    for field, wanted in expected.items():
        if value.get(field) != wanted:
            raise SaoOperationalAuthorizationError(
                f"SAO engineering runtime authorization mismatch: {field}"
            )
    _require_hash(value.get("backbone_config_sha256"), "backbone config")
    _require_hash(value.get("access_receipt_sha256"), "access receipt")
    return source, value


def prepare_sao_engineering_retry_attempt(
    runtime_authorization_path: Path,
    *,
    requested_run_dir: Path,
    live_config_path: Path,
    git_commit: str,
    decisions_path: Path,
    decision_id: str,
    decision_block_sha256: str,
    environment_manifest_path: Path = SAO_ENGINEERING_ENVIRONMENT_MANIFEST,
) -> dict[str, Any]:
    """Validate every frozen input before reserving a GPU."""

    if requested_run_dir.resolve() != SAO_ENGINEERING_RETRY_RUN_DIR.resolve():
        raise SaoOperationalAuthorizationError(
            "SAO engineering retry run directory is not the fixed v2-003 path"
        )
    if RUN_ID_RE.fullmatch(requested_run_dir.name) is None:
        raise SaoOperationalAuthorizationError("SAO engineering retry run ID is invalid")
    if GIT_REVISION_RE.fullmatch(git_commit) is None:
        raise SaoOperationalAuthorizationError("SAO engineering retry Git revision is invalid")
    if _path_entry_exists(requested_run_dir) or _path_entry_exists(
        SAO_ENGINEERING_RETRY_CLAIM_PATH
    ):
        raise SaoOperationalAuthorizationError("SAO engineering retry was already consumed")

    environment = validate_sao_engineering_environment(environment_manifest_path)
    lineage = validate_sao_engineering_failure_lineage()
    decision = verify_sao_engineering_retry_decision(
        decisions_path,
        decision_id=decision_id,
        expected_decision_block_sha256=decision_block_sha256,
    )
    authorization_path, authorization = _runtime_authorization(runtime_authorization_path)
    try:
        live_config = live_config_path.resolve(strict=True)
    except OSError as exc:
        raise SaoOperationalAuthorizationError("SAO live config is unavailable") from exc
    _verify_clean_main_revision(git_commit)

    record: dict[str, Any] = {
        "access_receipt_sha256": authorization["access_receipt_sha256"],
        "authorized_calls": 3,
        "authorized_max_clip_seconds": 30,
        "authorized_max_gpus": 1,
        "authorized_seed_schedule": [
            {"generation_index": index, "seed_id": seed_id, "seed": seed}
            for index, (seed_id, seed) in enumerate(SAO_MINI_SMOKE_SEED_SCHEDULE)
        ],
        "backbone_config_sha256": authorization["backbone_config_sha256"],
        "claimed_at_utc": None,
        "cpu_factory_failure_path": lineage["cpu_factory_failure_path"],
        "cpu_factory_failure_sha256": lineage["cpu_factory_failure_sha256"],
        "decision_block_sha256": decision["decision_block_sha256"],
        "decision_id": decision["decision_id"],
        "decisions_path": decision["decisions_path"],
        "engineering_failures_repairable": True,
        "environment_manifest_identity_sha256": environment["manifest_identity_sha256"],
        "environment_manifest_path": environment["path"],
        "environment_manifest_sha256": environment["sha256"],
        "environment_path": environment["environment_path"],
        "future_engineering_retry_requires_new_run_and_claim": True,
        "git_commit": git_commit,
        "live_config_path": str(live_config),
        "live_config_sha256": _sha256_file(live_config),
        "model_id": SAO_MODEL_ID,
        "previous_terminal_path": lineage["previous_terminal_path"],
        "previous_terminal_sha256": lineage["previous_terminal_sha256"],
        "prompts_seeds_budgets_changed": False,
        "run_dir": str(SAO_ENGINEERING_RETRY_RUN_DIR.resolve()),
        "run_id": SAO_ENGINEERING_RETRY_RUN_ID,
        "runtime_authorization_path": str(authorization_path),
        "runtime_authorization_sha256": _sha256_file(authorization_path),
        "schema_version": 1,
        "scientific_configuration_changed": False,
        "scope": "SAO_EXACT_THREE_CALL_ENGINEERING_REPAIR",
        "status": "PREPARED_ENGINEERING_REPAIR",
    }
    root = Path(__file__).resolve().parents[2]
    bound_paths = {
        authorization_path,
        live_config,
        Path(environment["path"]),
        Path(lineage["previous_terminal_path"]),
        Path(lineage["cpu_factory_failure_path"]),
        Path(decision["decisions_path"]),
        root / "scripts/run_sao_engineering_retry_v2.py",
        root / "src/backbones/sao_engineering_retry.py",
        root / "src/backbones/sao_mini_smoke.py",
        root / "src/backbones/stable_audio_open.py",
        root / "environment/sao/stable_audio_tools_inference_import.patch",
    }
    preparation: dict[str, Any] = {
        "bound_file_sha256": {
            str(path.resolve(strict=True)): _sha256_file(path.resolve(strict=True))
            for path in sorted(bound_paths, key=str)
        },
        "claim_path": str(SAO_ENGINEERING_RETRY_CLAIM_PATH),
        "record": record,
        "schema_version": 1,
        "status": "PREPARED_FOR_ATOMIC_ENGINEERING_REPAIR_CLAIM",
    }
    preparation["preparation_identity_sha256"] = _preparation_identity(preparation)
    return preparation


def consume_sao_engineering_retry_attempt(
    runtime_authorization_path: Path,
    *,
    requested_run_dir: Path,
    live_config_path: Path,
    git_commit: str,
    decisions_path: Path,
    decision_id: str,
    decision_block_sha256: str,
    environment_manifest_path: Path = SAO_ENGINEERING_ENVIRONMENT_MANIFEST,
    prepared_attempt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically consume the v2-003 claim after the safe-device check."""

    canonical = prepare_sao_engineering_retry_attempt(
        runtime_authorization_path,
        requested_run_dir=requested_run_dir,
        live_config_path=live_config_path,
        git_commit=git_commit,
        decisions_path=decisions_path,
        decision_id=decision_id,
        decision_block_sha256=decision_block_sha256,
        environment_manifest_path=environment_manifest_path,
    )
    if prepared_attempt is not None and _canonical_json(dict(prepared_attempt)) != _canonical_json(
        canonical
    ):
        raise SaoOperationalAuthorizationError("SAO engineering prepared attempt is not canonical")
    for path_text, expected_sha256 in canonical["bound_file_sha256"].items():
        path = Path(path_text)
        if _sha256_file(path.resolve(strict=True)) != expected_sha256:
            raise SaoOperationalAuthorizationError(
                "SAO engineering bound input changed before claim"
            )
    record = dict(canonical["record"])
    record["claimed_at_utc"] = _utc_now()
    record["status"] = "CLAIMED_ENGINEERING_REPAIR_EXACT_THREE_CALLS"
    record["claim_identity_sha256"] = _claim_identity(record)
    _write_json_o_excl(SAO_ENGINEERING_RETRY_CLAIM_PATH, record)
    return validate_sao_engineering_retry_claim(SAO_ENGINEERING_RETRY_CLAIM_PATH)


def validate_sao_engineering_retry_claim(path: Path) -> dict[str, Any]:
    """Validate the immutable v2-003 claim without re-running the environment gate."""

    if path.is_symlink():
        raise SaoOperationalAuthorizationError("SAO engineering claim may not be a symlink")
    source, value = _strict_json_object(path)
    if source != SAO_ENGINEERING_RETRY_CLAIM_PATH.resolve(strict=True):
        raise SaoOperationalAuthorizationError("SAO engineering claim path drifted")
    if set(value) != _CLAIM_KEYS:
        raise SaoOperationalAuthorizationError("SAO engineering claim keys drifted")
    expected = {
        "authorized_calls": 3,
        "authorized_max_clip_seconds": 30,
        "authorized_max_gpus": 1,
        "engineering_failures_repairable": True,
        "environment_manifest_sha256": SAO_ENGINEERING_ENVIRONMENT_MANIFEST_SHA256,
        "environment_manifest_path": str(SAO_ENGINEERING_ENVIRONMENT_MANIFEST.resolve()),
        "environment_path": str(SAO_ENGINEERING_ENVIRONMENT_PATH.resolve()),
        "future_engineering_retry_requires_new_run_and_claim": True,
        "model_id": SAO_MODEL_ID,
        "previous_terminal_sha256": SAO_PREVIOUS_MINI_SMOKE_TERMINAL_SHA256,
        "previous_terminal_path": str(SAO_PREVIOUS_MINI_SMOKE_TERMINAL.resolve()),
        "cpu_factory_failure_sha256": SAO_ENGINEERING_CPU_FACTORY_FAILURE_SHA256,
        "cpu_factory_failure_path": str(SAO_ENGINEERING_CPU_FACTORY_FAILURE.resolve()),
        "prompts_seeds_budgets_changed": False,
        "run_dir": str(SAO_ENGINEERING_RETRY_RUN_DIR.resolve()),
        "run_id": SAO_ENGINEERING_RETRY_RUN_ID,
        "runtime_authorization_path": str(SAO_RUNTIME_AUTHORIZATION_PATH.resolve()),
        "runtime_authorization_sha256": SAO_RUNTIME_AUTHORIZATION_SHA256,
        "schema_version": 1,
        "scientific_configuration_changed": False,
        "scope": "SAO_EXACT_THREE_CALL_ENGINEERING_REPAIR",
        "status": "CLAIMED_ENGINEERING_REPAIR_EXACT_THREE_CALLS",
    }
    for field, wanted in expected.items():
        if value.get(field) != wanted:
            raise SaoOperationalAuthorizationError(f"SAO engineering claim mismatch: {field}")
    if GIT_REVISION_RE.fullmatch(str(value.get("git_commit", ""))) is None:
        raise SaoOperationalAuthorizationError("SAO engineering claim Git revision is invalid")
    if DECISION_ID_RE.fullmatch(str(value.get("decision_id", ""))) is None:
        raise SaoOperationalAuthorizationError("SAO engineering claim decision ID is invalid")
    for field in (
        "access_receipt_sha256",
        "backbone_config_sha256",
        "claim_identity_sha256",
        "decision_block_sha256",
        "environment_manifest_identity_sha256",
        "live_config_sha256",
        "runtime_authorization_sha256",
    ):
        _require_hash(value.get(field), field)
    if value.get("claim_identity_sha256") != _claim_identity(value):
        raise SaoOperationalAuthorizationError("SAO engineering claim identity mismatch")
    if value.get("authorized_seed_schedule") != [
        {"generation_index": index, "seed_id": seed_id, "seed": seed}
        for index, (seed_id, seed) in enumerate(SAO_MINI_SMOKE_SEED_SCHEDULE)
    ]:
        raise SaoOperationalAuthorizationError("SAO engineering seed schedule drifted")
    return {**value, "path": str(source), "sha256": _sha256_file(source)}


def validate_sao_engineering_retry_terminal_decision(
    claim: Mapping[str, Any],
) -> dict[str, str]:
    """Validate the immutable D-0050 block used by the completed v2-003 run.

    The preparation-time verifier intentionally hashes then-current runner
    sources.  A later core-gate engineering repair must not reinterpret that
    historical opening against newer validator bytes, so terminal evidence is
    instead bound to the exact decision ID and block hash consumed by v2-003.
    """

    if claim.get("decision_id") != SAO_ENGINEERING_RETRY_DECISION_ID:
        raise SaoOperationalAuthorizationError("SAO engineering terminal decision ID drifted")
    if claim.get("decision_block_sha256") != SAO_ENGINEERING_RETRY_DECISION_BLOCK_SHA256:
        raise SaoOperationalAuthorizationError("SAO engineering terminal decision hash drifted")
    raw_path = claim.get("decisions_path")
    if not isinstance(raw_path, str):
        raise SaoOperationalAuthorizationError("SAO engineering terminal decision path is absent")
    path = Path(raw_path)
    if not path.is_absolute() or path.is_symlink():
        raise SaoOperationalAuthorizationError(
            "SAO engineering terminal decision path is not canonical"
        )
    try:
        source = path.resolve(strict=True)
        canonical = SAO_DECISIONS_PATH.resolve(strict=True)
        if source != canonical:
            raise SaoOperationalAuthorizationError(
                "SAO engineering terminal decision is not repository DECISIONS.md"
            )
        block = _decision_block(
            source.read_text(encoding="utf-8"),
            SAO_ENGINEERING_RETRY_DECISION_ID,
        )
    except SaoOperationalAuthorizationError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise SaoOperationalAuthorizationError(
            "SAO engineering terminal decision is unavailable"
        ) from exc
    block_sha256 = hashlib.sha256(block.encode()).hexdigest()
    if block_sha256 != SAO_ENGINEERING_RETRY_DECISION_BLOCK_SHA256:
        raise SaoOperationalAuthorizationError("SAO engineering terminal decision changed")
    return {
        "decision_block_sha256": block_sha256,
        "decision_id": SAO_ENGINEERING_RETRY_DECISION_ID,
        "decisions_path": str(source),
    }


def validate_sao_engineering_retry_terminal_lineage(path: Path) -> dict[str, Any]:
    """Revalidate every external v2-003 engineering binding for core admission."""

    claim = validate_sao_engineering_retry_claim(path)
    if claim["sha256"] != SAO_ENGINEERING_RETRY_CLAIM_SHA256:
        raise SaoOperationalAuthorizationError("SAO engineering terminal claim hash drifted")
    decision = validate_sao_engineering_retry_terminal_decision(claim)
    environment = validate_sao_engineering_environment(
        Path(str(claim["environment_manifest_path"])),
        require_live_prefix=False,
    )
    failures = validate_sao_engineering_failure_lineage()
    authorization_path, authorization = _runtime_authorization(
        Path(str(claim["runtime_authorization_path"]))
    )
    live_config = Path(str(claim["live_config_path"]))
    try:
        live_config = live_config.resolve(strict=True)
    except OSError as exc:
        raise SaoOperationalAuthorizationError(
            "SAO engineering terminal live config is unavailable"
        ) from exc

    expected = {
        "access_receipt_sha256": authorization["access_receipt_sha256"],
        "backbone_config_sha256": authorization["backbone_config_sha256"],
        "decision_block_sha256": decision["decision_block_sha256"],
        "decision_id": decision["decision_id"],
        "decisions_path": decision["decisions_path"],
        "environment_manifest_identity_sha256": environment["manifest_identity_sha256"],
        "environment_manifest_path": environment["path"],
        "environment_manifest_sha256": environment["sha256"],
        "environment_path": environment["environment_path"],
        "live_config_path": str(live_config),
        "live_config_sha256": _sha256_file(live_config),
        "runtime_authorization_path": str(authorization_path),
        "runtime_authorization_sha256": _sha256_file(authorization_path),
        **failures,
    }
    for field, wanted in expected.items():
        if claim.get(field) != wanted:
            raise SaoOperationalAuthorizationError(
                f"SAO engineering terminal lineage mismatch: {field}"
            )
    return claim

"""Exact three-call Stable Audio Open engineering smoke with immutable evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audio_duration_policy import duration_within_tolerance
from backbones import sao_operational_claims
from backbones.contracts import (
    DEFAULT_SAO_CONFIG,
    BackboneAdapter,
    GenerationRequest,
    sha256_file,
    strict_json_object,
)
from backbones.license_gate import validate_runtime_authorization
from backbones.mini_smoke import RunContext
from backbones.sao_t5 import conditioning_bundle_record
from sa3_smoke.artifacts import (
    PROVENANCE_REQUIRED_FIELDS,
    adjacent_provenance_path,
    exclusive_write_json,
    validate_adjacent_provenance,
    write_adjacent_provenance,
)
from sa3_smoke.audio import audio_sanity

EXACT_CALLS = 3
DURATION_TOLERANCE_SECONDS = 0.25
EXPECTED_SEEDS = (("S-0011", 73193011), ("S-0011", 73193011), ("S-0012", 73193012))
EXPECTED_PROMPTS = (
    (
        "sao-mini-repro",
        "A purely instrumental arrangement led throughout by piano, upright bass, and "
        "brushed drums, with a clean continuous texture.",
    ),
    (
        "sao-mini-repro",
        "A purely instrumental arrangement led throughout by piano, upright bass, and "
        "brushed drums, with a clean continuous texture.",
    ),
    (
        "sao-mini-resident-cost",
        "A purely instrumental arrangement led throughout by acoustic guitar, warm bass, "
        "and hand percussion, with a clean continuous texture.",
    ),
)
SAO_MODEL_ID = "stabilityai/stable-audio-open-1.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


class SaoMiniSmokeError(RuntimeError):
    """Terminal no-retry smoke failure."""


class SaoMiniSmokeEvidenceError(ValueError):
    """A purported PASS terminal is not linked to complete smoke evidence."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _evidence(condition: bool, message: str) -> None:
    if not condition:
        raise SaoMiniSmokeEvidenceError(message)


def _inside(path: Path, root: Path, context: str) -> Path:
    _evidence(path.is_absolute(), f"{context} must be absolute")
    _evidence(not path.is_symlink(), f"{context} may not be a symlink")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SaoMiniSmokeEvidenceError(f"{context} escapes the mini-smoke run") from exc
    _evidence(resolved.is_file(), f"{context} is not a regular file")
    return resolved


def _timestamp(value: Any, context: str) -> None:
    _evidence(isinstance(value, str) and bool(value), f"{context} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SaoMiniSmokeEvidenceError(f"{context} is not ISO-8601") from exc
    _evidence(
        parsed.tzinfo is not None
        and parsed.utcoffset() is not None
        and parsed.utcoffset().total_seconds() == 0,
        f"{context} must be UTC",
    )


def _positive_number(value: Any, context: str, *, allow_zero: bool = False) -> float:
    _evidence(
        not isinstance(value, bool) and isinstance(value, (int, float)),
        f"{context} must be numeric",
    )
    number = float(value)
    _evidence(math.isfinite(number), f"{context} must be finite")
    _evidence(number >= 0 if allow_zero else number > 0, f"{context} is out of range")
    return number


def _strict_ledger(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    _evidence(raw.endswith(b"\n"), "SAO generation ledger must end with a newline")
    lines = raw.splitlines()
    _evidence(len(lines) == EXACT_CALLS, "SAO generation ledger must contain exactly three rows")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SaoMiniSmokeEvidenceError(f"duplicate ledger JSON key: {key}")
            result[key] = value
        return result

    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(
                line,
                object_pairs_hook=reject_duplicates,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    SaoMiniSmokeEvidenceError(f"non-finite ledger number: {token}")
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SaoMiniSmokeEvidenceError("SAO generation ledger is not strict JSONL") from exc
        _evidence(isinstance(value, dict), "SAO generation ledger rows must be objects")
        _evidence(line.decode("utf-8") == _canonical(value), "SAO ledger row is not canonical JSON")
        rows.append(value)
    return rows


def validate_sao_mini_smoke_evidence(
    terminal_path: str | Path,
    *,
    expected_config_sha256: str,
    expected_receipt: Mapping[str, Any],
    expected_snapshot_dir: str | Path,
) -> dict[str, Any]:
    """Validate the exact terminal/manifest/ledger/audio/provenance receipt chain.

    This is the authorization boundary for ordinary SAO core generation.  A
    summary-shaped PASS object is deliberately insufficient: all three retained
    WAVs and their immutable evidence are decoded and re-hashed here.
    """

    try:
        return _validate_sao_mini_smoke_evidence(
            Path(terminal_path),
            expected_config_sha256=expected_config_sha256,
            expected_receipt=expected_receipt,
            expected_snapshot_dir=Path(expected_snapshot_dir),
        )
    except SaoMiniSmokeEvidenceError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SaoMiniSmokeEvidenceError(f"invalid SAO mini-smoke evidence: {exc}") from exc


def _validate_sao_mini_smoke_evidence(
    terminal_path: Path,
    *,
    expected_config_sha256: str,
    expected_receipt: Mapping[str, Any],
    expected_snapshot_dir: Path,
) -> dict[str, Any]:
    _evidence(bool(SHA256_RE.fullmatch(expected_config_sha256)), "invalid expected config hash")
    _evidence(
        sha256_file(DEFAULT_SAO_CONFIG) == expected_config_sha256,
        "mini-smoke config is not the frozen SAO adapter config",
    )
    adapter_config = strict_json_object(DEFAULT_SAO_CONFIG)
    generation = adapter_config["generation"]

    terminal_file = terminal_path.resolve(strict=True)
    _evidence(terminal_file.name == "sao-mini-smoke-terminal.json", "unexpected terminal filename")
    _evidence(not terminal_file.is_symlink(), "SAO mini-smoke terminal may not be a symlink")
    run_root = terminal_file.parent
    terminal = strict_json_object(terminal_file)
    terminal_keys = {
        "benchmark_endpoints_scored",
        "cost_calibration",
        "eligibility_scope_expanded",
        "finished_at_utc",
        "generated_outputs",
        "generation_ledger_path",
        "generation_ledger_sha256",
        "generation_ledger_tail_sha256",
        "human_gold_claims",
        "manifest_path",
        "manifest_sha256",
        "model_calls",
        "no_retry",
        "reproducibility_decoded_waveform_sha256",
        "reproducibility_hash_pass",
        "rows",
        "run_id",
        "schema_version",
        "started_at_utc",
        "state_capability",
        "status",
    }
    _evidence(set(terminal) == terminal_keys, "SAO PASS terminal keys drifted")
    _evidence(terminal["schema_version"] == 1, "SAO terminal schema drifted")
    _evidence(terminal["status"] == "PASS_MEASURED_READY", "SAO terminal is not PASS")
    _evidence(terminal["model_calls"] == EXACT_CALLS, "SAO terminal call count drifted")
    _evidence(terminal["generated_outputs"] == EXACT_CALLS, "SAO output count drifted")
    _evidence(terminal["no_retry"] is True, "SAO no-retry invariant drifted")
    _evidence(terminal["benchmark_endpoints_scored"] == 0, "mini-smoke scored benchmark endpoints")
    _evidence(terminal["human_gold_claims"] is False, "mini-smoke made human-gold claims")
    _evidence(terminal["reproducibility_hash_pass"] is True, "reproducibility did not pass")
    _evidence(terminal["state_capability"] == "NOT_ATTEMPTED", "SAO state scope expanded")
    _evidence(terminal["eligibility_scope_expanded"] is False, "SAO eligibility expanded")
    _evidence(isinstance(terminal["run_id"], str) and terminal["run_id"], "run_id is absent")
    _timestamp(terminal["started_at_utc"], "terminal.started_at_utc")
    _timestamp(terminal["finished_at_utc"], "terminal.finished_at_utc")

    manifest_path = _inside(Path(terminal["manifest_path"]), run_root, "manifest_path")
    ledger_path = _inside(
        Path(terminal["generation_ledger_path"]), run_root, "generation_ledger_path"
    )
    _evidence(manifest_path == run_root / "manifest.json", "manifest path identity drifted")
    _evidence(ledger_path == run_root / "generation-ledger.jsonl", "ledger path identity drifted")
    _evidence(sha256_file(manifest_path) == terminal["manifest_sha256"], "manifest hash mismatch")
    _evidence(
        sha256_file(ledger_path) == terminal["generation_ledger_sha256"],
        "generation ledger hash mismatch",
    )

    manifest = strict_json_object(manifest_path)
    _evidence(
        set(manifest)
        == {
            "caps",
            "command",
            "git_commit",
            "package_freeze_sha256",
            "placement",
            "preflight",
            "requests",
            "run_id",
            "schema_version",
            "scope",
            "started_at_utc",
            "status",
        },
        "SAO manifest keys drifted",
    )
    _evidence(manifest["schema_version"] == 1, "SAO manifest schema drifted")
    _evidence(
        manifest["scope"] == "SAO_THREE_CALL_ENGINEERING_MINI_SMOKE_NON_BENCHMARK"
        and manifest["status"] == "RESERVED_EXACTLY_THREE_CALLS",
        "SAO manifest scope/status drifted",
    )
    _evidence(manifest["run_id"] == terminal["run_id"], "manifest run_id mismatch")
    _evidence(manifest["run_id"] == run_root.name, "run_id is not bound to its run directory")
    _evidence(manifest["started_at_utc"] == terminal["started_at_utc"], "start time mismatch")
    _timestamp(manifest["started_at_utc"], "manifest.started_at_utc")
    _evidence(isinstance(manifest["command"], str) and manifest["command"], "command is absent")
    _evidence(
        isinstance(manifest["git_commit"], str)
        and bool(REVISION_RE.fullmatch(manifest["git_commit"])),
        "manifest git commit is invalid",
    )
    _evidence(
        isinstance(manifest["package_freeze_sha256"], str)
        and bool(SHA256_RE.fullmatch(manifest["package_freeze_sha256"])),
        "package-freeze hash is invalid",
    )
    _evidence(
        manifest["caps"]
        == {"exact_calls": 3, "max_clip_seconds": 30, "max_gpus": 1, "max_retries": 0},
        "SAO manifest caps drifted",
    )
    placement = manifest["placement"]
    _evidence(
        isinstance(placement, dict)
        and set(placement)
        == {
            "gpu_ids",
            "justification",
            "node",
            "preload_observation",
            "replica_count",
            "tensor_parallel_width",
        },
        "SAO placement record drifted",
    )
    _evidence(placement["node"] == "an12", "SAO smoke did not run on an12")
    _evidence(placement["gpu_ids"] in [["4"], ["5"], ["6"], ["7"]], "SAO GPU binding drifted")
    _evidence(
        placement["tensor_parallel_width"] == 1 and placement["replica_count"] == 1,
        "SAO placement width drifted",
    )
    _evidence(
        isinstance(placement["justification"], str) and placement["justification"],
        "SAO placement justification is absent",
    )
    observation = placement["preload_observation"]
    _evidence(
        isinstance(observation, dict)
        and set(observation)
        == {
            "free_vram_bytes",
            "gpu_name",
            "gpu_uuid",
            "neighbor_compute_pids",
            "node",
            "operational_attempt_claim_path",
            "operational_attempt_claim_sha256",
            "physical_gpu_id",
            "total_vram_bytes",
            "utilization_percent",
        },
        "SAO preload observation/attempt-claim linkage is incomplete",
    )
    _evidence(
        observation["node"] == "an12"
        and observation["physical_gpu_id"] == int(placement["gpu_ids"][0])
        and isinstance(observation["gpu_uuid"], str)
        and bool(observation["gpu_uuid"])
        and isinstance(observation["gpu_name"], str)
        and "A800" in observation["gpu_name"],
        "SAO observed GPU identity drifted",
    )
    free_vram = observation["free_vram_bytes"]
    total_vram = observation["total_vram_bytes"]
    utilization = observation["utilization_percent"]
    _evidence(
        not isinstance(free_vram, bool)
        and isinstance(free_vram, int)
        and free_vram >= 60_000_000_000
        and not isinstance(total_vram, bool)
        and isinstance(total_vram, int)
        and total_vram >= free_vram,
        "SAO observed VRAM headroom was unsafe",
    )
    _evidence(
        not isinstance(utilization, bool)
        and isinstance(utilization, (int, float))
        and math.isfinite(float(utilization))
        and 0 <= float(utilization) <= 5,
        "SAO observed utilization was unsafe",
    )
    _evidence(observation["neighbor_compute_pids"] == [], "SAO smoke had GPU neighbors")

    claim_path = Path(observation["operational_attempt_claim_path"])
    _evidence(claim_path.is_absolute(), "SAO attempt claim path must be absolute")
    _evidence(not claim_path.is_symlink(), "SAO attempt claim may not be a symlink")
    claim_path = claim_path.resolve(strict=True)
    _evidence(
        claim_path == sao_operational_claims.SAO_MINI_SMOKE_ATTEMPT_CLAIM.resolve(),
        "SAO attempt claim is not the fixed global claim",
    )
    claim = sao_operational_claims.validate_sao_mini_smoke_attempt_claim(claim_path)
    _evidence(
        claim["sha256"] == observation["operational_attempt_claim_sha256"],
        "SAO attempt claim hash mismatch",
    )
    _evidence(
        set(claim)
        == {
            "authorized_calls",
            "authorized_max_clip_seconds",
            "authorized_max_gpus",
            "backbone_config_sha256",
            "claim_identity_sha256",
            "claimed_at_utc",
            "decision_id",
            "git_commit",
            "live_config_path",
            "live_config_sha256",
            "model_id",
            "path",
            "retry_allowed",
            "run_dir",
            "run_id",
            "runtime_authorization_path",
            "runtime_authorization_sha256",
            "schema_version",
            "scope",
            "sha256",
            "status",
        },
        "SAO attempt claim keys drifted",
    )
    _timestamp(claim["claimed_at_utc"], "attempt_claim.claimed_at_utc")
    _evidence(
        Path(claim["run_dir"]).resolve() == run_root
        and claim["run_id"] == terminal["run_id"]
        and claim["git_commit"] == manifest["git_commit"]
        and claim["backbone_config_sha256"] == expected_config_sha256,
        "SAO attempt claim run/config/Git linkage drifted",
    )
    live_config_path = Path(claim["live_config_path"])
    _evidence(
        live_config_path.is_absolute()
        and not live_config_path.is_symlink()
        and sha256_file(live_config_path.resolve(strict=True)) == claim["live_config_sha256"],
        "SAO attempt claim live-config linkage drifted",
    )

    preflight = manifest["preflight"]
    _evidence(
        isinstance(preflight, dict)
        and set(preflight) == {"config_sha256", "details", "model_id", "status"},
        "SAO preflight record drifted",
    )
    _evidence(
        preflight["status"] == "READY_FOR_MINI_SMOKE"
        and preflight["model_id"] == SAO_MODEL_ID
        and preflight["config_sha256"] == expected_config_sha256,
        "SAO preflight identity drifted",
    )
    details = preflight["details"]
    _evidence(
        isinstance(details, dict)
        and set(details)
        == {
            "network_downloads_allowed",
            "receipt",
            "runtime_authorization",
            "runtime_authorization_path",
            "runtime_authorization_sha256",
            "snapshot_dir",
        },
        "SAO preflight detail linkage is incomplete",
    )
    expected_receipt_dict = dict(expected_receipt)
    _evidence(details["receipt"] == expected_receipt_dict, "mini-smoke receipt linkage mismatch")
    _evidence(details["network_downloads_allowed"] is False, "mini-smoke allowed network access")
    _evidence(
        Path(details["snapshot_dir"]).resolve(strict=True)
        == expected_snapshot_dir.resolve(strict=True),
        "mini-smoke snapshot linkage mismatch",
    )
    authorization_path = Path(details["runtime_authorization_path"])
    _evidence(authorization_path.is_absolute(), "mini-smoke authorization path must be absolute")
    _evidence(not authorization_path.is_symlink(), "mini-smoke authorization may not be a symlink")
    authorization_path = authorization_path.resolve(strict=True)
    _evidence(
        sha256_file(authorization_path) == details["runtime_authorization_sha256"],
        "mini-smoke authorization hash mismatch",
    )
    _evidence(
        Path(claim["runtime_authorization_path"]).resolve(strict=True) == authorization_path
        and claim["runtime_authorization_sha256"]
        == details["runtime_authorization_sha256"],
        "SAO attempt claim runtime-authorization linkage drifted",
    )
    authorization = validate_runtime_authorization(
        authorization_path,
        expected_config_sha256=expected_config_sha256,
        expected_receipt_sha256=str(expected_receipt_dict["receipt_sha256"]),
        expected_decision_id="D-0037",
        expected_generations=3,
    )
    _evidence(
        details["runtime_authorization"] == authorization,
        "authorization bytes/details drifted",
    )

    requests = manifest["requests"]
    _evidence(isinstance(requests, list) and len(requests) == EXACT_CALLS, "request count drifted")
    rows = _strict_ledger(ledger_path)
    _evidence(terminal["rows"] == rows, "terminal rows do not equal the ledger rows")
    previous = "0" * 64
    output_paths: set[Path] = set()
    prompt_hashes: list[str] = []
    safetensors_rows = [
        row
        for row in expected_receipt_dict.get("verified_files", [])
        if isinstance(row, dict) and row.get("path") == "model.safetensors"
    ]
    checkpoint_rows = [
        row
        for row in expected_receipt_dict.get("verified_files", [])
        if isinstance(row, dict) and row.get("path") == "model.ckpt"
    ]
    if safetensors_rows:
        _evidence(
            len(safetensors_rows) == 1,
            "receipt does not uniquely bind the preferred SAO safetensors weight",
        )
        selected_weight_row = safetensors_rows[0]
    else:
        _evidence(
            len(checkpoint_rows) == 1,
            "receipt does not uniquely bind a supported SAO weight file",
        )
        selected_weight_row = checkpoint_rows[0]
    expected_weight_sha = selected_weight_row.get("sha256")
    try:
        expected_conditioning_bundle_sha = conditioning_bundle_record(
            expected_receipt_dict.get("verified_files", [])
        )["conditioning_bundle_sha256"]
    except ValueError as exc:
        raise SaoMiniSmokeEvidenceError(
            "receipt does not bind the exact offline SAO T5 bundle"
        ) from exc
    expected_steps = int(generation["inference_steps"])
    expected_sampler = str(generation["sampler_type"])
    expected_revision = expected_receipt_dict.get("resolved_provider_revision")
    expected_license = expected_receipt_dict.get("license_identifier")

    row_keys = {
        "actual_nfe",
        "attempted_at_utc",
        "audio_sanity",
        "cost_status",
        "decoded_waveform_sha256",
        "duration_seconds",
        "file_sha256",
        "generation_index",
        "measurement_metadata",
        "output_path",
        "peak_allocated_bytes",
        "peak_reserved_bytes",
        "previous_row_sha256",
        "prompt_id",
        "prompt_sha256",
        "provenance_path",
        "provenance_sha256",
        "requested_steps",
        "row_sha256",
        "schema_version",
        "seed",
        "seed_id",
        "status",
        "wall_seconds",
    }
    request_keys = {
        "duration_seconds",
        "generation_index",
        "output_path",
        "prompt_id",
        "prompt_sha256",
        "seed",
        "seed_id",
    }
    for index, (request, row, seed, prompt) in enumerate(
        zip(requests, rows, EXPECTED_SEEDS, EXPECTED_PROMPTS, strict=True)
    ):
        _evidence(
            isinstance(request, dict) and set(request) == request_keys,
            "request keys drifted",
        )
        _evidence(set(row) == row_keys, f"ledger row {index} keys drifted")
        _evidence(row["schema_version"] == 1, f"ledger row {index} schema drifted")
        _evidence(request["generation_index"] == row["generation_index"] == index, "index drifted")
        for key in (
            "prompt_id",
            "prompt_sha256",
            "seed_id",
            "seed",
            "duration_seconds",
            "output_path",
        ):
            _evidence(request[key] == row[key], f"request/ledger {key} mismatch")
        _evidence((row["seed_id"], row["seed"]) == seed, f"row {index} seed drifted")
        _evidence(row["prompt_id"] == prompt[0], f"row {index} prompt identity drifted")
        _evidence(
            row["prompt_sha256"] == hashlib.sha256(prompt[1].encode("utf-8")).hexdigest(),
            f"row {index} prompt content drifted",
        )
        _evidence(row["duration_seconds"] == 30.0, f"row {index} duration drifted")
        _evidence(
            isinstance(row["prompt_sha256"], str)
            and bool(SHA256_RE.fullmatch(row["prompt_sha256"])),
            f"row {index} prompt hash is invalid",
        )
        prompt_hashes.append(row["prompt_sha256"])
        _timestamp(row["attempted_at_utc"], f"row {index}.attempted_at_utc")
        _evidence(row["status"] == "PASS" and row["cost_status"] == "MEASURED", "row not PASS")
        _evidence(row["requested_steps"] == expected_steps, "requested step count drifted")
        _evidence(
            not isinstance(row["actual_nfe"], bool)
            and isinstance(row["actual_nfe"], int)
            and row["actual_nfe"] > 0,
            "actual NFE is invalid",
        )
        _positive_number(row["wall_seconds"], f"row {index}.wall_seconds")
        for field in ("peak_allocated_bytes", "peak_reserved_bytes"):
            _evidence(
                not isinstance(row[field], bool)
                and isinstance(row[field], int)
                and row[field] >= 0,
                f"row {index}.{field} is invalid",
            )
        metadata = row["measurement_metadata"]
        _evidence(
            isinstance(metadata, dict)
            and set(metadata)
            == {
                "config_sha256",
                "conditioning_bundle_sha256",
                "execution_scope",
                "load_wall_seconds",
                "requested_sample_size",
                "resolved_provider_revision",
                "sampler_type",
                "weight_file_sha256",
            },
            f"row {index} measurement metadata drifted",
        )
        _positive_number(metadata["load_wall_seconds"], "load_wall_seconds", allow_zero=True)
        _evidence(
            metadata["config_sha256"] == expected_config_sha256
            and metadata["conditioning_bundle_sha256"] == expected_conditioning_bundle_sha
            and metadata["execution_scope"] == "MINI_SMOKE"
            and metadata["requested_sample_size"] == 1_323_000
            and metadata["resolved_provider_revision"] == expected_revision
            and metadata["sampler_type"] == expected_sampler
            and metadata["weight_file_sha256"] == expected_weight_sha,
            f"row {index} measurement linkage drifted",
        )

        output_path = _inside(Path(row["output_path"]), run_root, f"row {index} output")
        _evidence(output_path.suffix.lower() == ".wav", "SAO output is not WAV")
        _evidence(
            output_path == run_root / "audio" / f"call-{index:02d}.wav",
            f"row {index} output identity drifted",
        )
        _evidence(output_path not in output_paths, "SAO output paths are not unique")
        output_paths.add(output_path)
        _evidence(sha256_file(output_path) == row["file_sha256"], "retained WAV hash mismatch")
        provenance_path = _inside(
            Path(row["provenance_path"]), run_root, f"row {index} provenance"
        )
        _evidence(
            provenance_path == adjacent_provenance_path(output_path),
            "provenance path drifted",
        )
        _evidence(
            sha256_file(provenance_path) == row["provenance_sha256"],
            "provenance sidecar hash mismatch",
        )
        provenance = validate_adjacent_provenance(output_path)
        _evidence(set(provenance) == set(PROVENANCE_REQUIRED_FIELDS), "provenance keys drifted")
        _evidence(
            provenance["label"] == "synthetic_model_output"
            and provenance["creating_command"] == manifest["command"]
            and provenance["run_id"] == terminal["run_id"]
            and provenance["source_ids"]
            == [f"{SAO_MODEL_ID}@config-sha256:{expected_config_sha256}"]
            and provenance["model_revision"] == expected_revision
            and provenance["license_identifier"] == expected_license
            and provenance["transformation"]
            == "official offline Stable Audio Open text-to-audio decode",
            f"row {index} provenance linkage drifted",
        )
        sanity = _duration_adjudicated_sanity(Path(row["output_path"]), 30.0)
        _evidence(sanity == row["audio_sanity"], f"row {index} audio sanity was not recomputed")
        _evidence(
            sanity["pass"] is True
            and sanity["file_sha256"] == row["file_sha256"]
            and sanity["decoded_waveform_sha256"] == row["decoded_waveform_sha256"],
            f"row {index} retained audio is not eligible",
        )

        without_hash = dict(row)
        observed_hash = without_hash.pop("row_sha256")
        _evidence(without_hash["previous_row_sha256"] == previous, "ledger hash chain broke")
        expected_hash = hashlib.sha256(_canonical(without_hash).encode("utf-8")).hexdigest()
        _evidence(observed_hash == expected_hash, "ledger row hash mismatch")
        previous = observed_hash

    _evidence(previous == terminal["generation_ledger_tail_sha256"], "ledger tail mismatch")
    _evidence(prompt_hashes[0] == prompt_hashes[1], "repro pair prompt hashes differ")
    _evidence(prompt_hashes[2] != prompt_hashes[0], "resident-cost prompt is not distinct")
    _evidence(
        rows[0]["prompt_id"] == rows[1]["prompt_id"]
        and rows[2]["prompt_id"] != rows[0]["prompt_id"],
        "prompt identities do not form the frozen pair/distinct call",
    )
    _evidence(
        rows[0]["decoded_waveform_sha256"] == rows[1]["decoded_waveform_sha256"]
        and terminal["reproducibility_decoded_waveform_sha256"]
        == rows[0]["decoded_waveform_sha256"],
        "decoded-waveform reproducibility hash is not linked",
    )

    cost = terminal["cost_calibration"]
    _evidence(
        isinstance(cost, dict)
        and set(cost)
        == {
            "arithmetic_rule",
            "cold_plus_first_seconds",
            "cost_status",
            "gpu_hours_cap",
            "gpu_seconds_cap",
            "resident_unit_seconds",
            "scheduled_core_calls",
        },
        "SAO cost calibration keys drifted",
    )
    load_seconds = float(rows[0]["measurement_metadata"]["load_wall_seconds"])
    cold = load_seconds + float(rows[0]["wall_seconds"])
    resident = max(float(rows[1]["wall_seconds"]), float(rows[2]["wall_seconds"]))
    cap = cold + 1535 * (2 * resident)
    _evidence(
        cost["cost_status"] == "MEASURED"
        and cost["scheduled_core_calls"] == 1536
        and cost["arithmetic_rule"] == "c=L0+W0; u=max(W1,W2); cap=c+1535*(2*u)",
        "SAO cost calibration policy drifted",
    )
    for observed, expected, context in (
        (cost["cold_plus_first_seconds"], cold, "cold cost"),
        (cost["resident_unit_seconds"], resident, "resident cost"),
        (cost["gpu_seconds_cap"], cap, "GPU-seconds cap"),
        (cost["gpu_hours_cap"], cap / 3600, "GPU-hours cap"),
    ):
        _evidence(
            math.isclose(_positive_number(observed, context), expected, rel_tol=0.0, abs_tol=1e-9),
            f"{context} arithmetic mismatch",
        )
    return terminal


def _append(handle: Any, row: dict[str, Any], previous: str) -> str:
    value = {**row, "previous_row_sha256": previous}
    digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
    value["row_sha256"] = digest
    handle.write((_canonical(value) + "\n").encode("utf-8"))
    handle.flush()
    os.fsync(handle.fileno())
    row["previous_row_sha256"] = previous
    row["row_sha256"] = digest
    return digest


def _validate_requests(requests: Sequence[GenerationRequest], run_dir: Path) -> None:
    if len(requests) != EXACT_CALLS:
        raise ValueError("SAO mini-smoke requires exactly three requests")
    for index, (request, seed, prompt) in enumerate(
        zip(requests, EXPECTED_SEEDS, EXPECTED_PROMPTS, strict=True)
    ):
        if (request.seed_id, request.seed) != seed:
            raise ValueError(f"SAO mini-smoke request {index} has an unregistered seed")
        if (request.prompt_id, request.prompt) != prompt:
            raise ValueError(f"SAO mini-smoke request {index} differs from the frozen prompt")
        if request.duration_seconds != 30.0:
            raise ValueError("SAO mini-smoke requests must be exactly 30 seconds")
        try:
            request.output_path.resolve().relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("SAO mini-smoke output escapes its run directory") from exc
        if request.output_path.resolve() != run_dir.resolve() / "audio" / f"call-{index:02d}.wav":
            raise ValueError(f"SAO mini-smoke request {index} output path drifted")
    first, second, third = requests
    if (first.prompt, first.seed) != (second.prompt, second.seed):
        raise ValueError("SAO calls 0/1 must be an identical prompt/seed reproducibility pair")
    if third.prompt_id == first.prompt_id:
        raise ValueError("SAO call 2 must be a distinct resident-cost request")
    if len({request.output_path.resolve() for request in requests}) != EXACT_CALLS:
        raise ValueError("SAO mini-smoke output paths must be unique")


def _duration_adjudicated_sanity(path: Path, requested_seconds: float) -> dict[str, Any]:
    sanity = audio_sanity(
        path,
        requested_seconds,
        expected_sample_rate=44_100,
        expected_channels=2,
        require_provenance=True,
    )
    observed = sanity.get("duration_seconds")
    duration_pass = (
        isinstance(observed, (int, float))
        and not isinstance(observed, bool)
        and duration_within_tolerance(observed, requested_seconds, DURATION_TOLERANCE_SECONDS)
    )
    non_duration_failures = [
        failure for failure in sanity["failures"] if failure.get("check") != "sample_count"
    ]
    sanity["duration_policy"] = {
        "rule": "abs(decoded_duration_seconds - requested_duration_seconds) <= tolerance_seconds",
        "tolerance_seconds": DURATION_TOLERANCE_SECONDS,
        "pass": duration_pass,
    }
    sanity["exact_sample_count_pass"] = not any(
        failure.get("check") == "sample_count" for failure in sanity["failures"]
    )
    sanity["pass"] = duration_pass and not non_duration_failures
    sanity["adjudicated_failures"] = non_duration_failures + (
        []
        if duration_pass
        else [
            {
                "check": "duration_tolerance",
                "expected": DURATION_TOLERANCE_SECONDS,
                "observed": observed,
            }
        ]
    )
    return sanity


def run_sao_mini_smoke(
    adapter: BackboneAdapter,
    requests: Sequence[GenerationRequest],
    *,
    run_dir: Path,
    context: RunContext,
    require_visible_gpu: bool = True,
    placement_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the sole three calls; every failure is terminal and never retried."""

    destination = run_dir.resolve()
    if destination.exists():
        raise FileExistsError(destination)
    _validate_requests(requests, destination)
    if context.run_id != destination.name:
        raise ValueError("SAO mini-smoke run_id must equal its immutable run directory name")
    if require_visible_gpu and os.environ.get("CUDA_VISIBLE_DEVICES") != context.gpu_ids[0]:
        raise ValueError("CUDA_VISIBLE_DEVICES differs from the bound physical GPU")
    ready = adapter.preflight()
    if ready.status != "READY_FOR_MINI_SMOKE":
        raise ValueError("SAO adapter is not authorized for the mini-smoke scope")
    if adapter.logical_name != "stable-audio-open-1.0":
        raise ValueError("SAO mini-smoke received another backbone")

    destination.mkdir(parents=False, exist_ok=False)
    started = _utc_now()
    manifest = {
        "schema_version": 1,
        "scope": "SAO_THREE_CALL_ENGINEERING_MINI_SMOKE_NON_BENCHMARK",
        "run_id": context.run_id,
        "status": "RESERVED_EXACTLY_THREE_CALLS",
        "started_at_utc": started,
        "command": context.command,
        "git_commit": context.git_commit,
        "package_freeze_sha256": context.package_freeze_sha256,
        "placement": {
            "node": context.node,
            "gpu_ids": list(context.gpu_ids),
            "tensor_parallel_width": context.tensor_parallel_width,
            "replica_count": context.replica_count,
            "justification": context.placement_justification,
            "preload_observation": placement_observation,
        },
        "caps": {
            "exact_calls": EXACT_CALLS,
            "max_clip_seconds": 30,
            "max_gpus": 1,
            "max_retries": 0,
        },
        "preflight": {
            "status": ready.status,
            "model_id": ready.model_id,
            "config_sha256": ready.config_sha256,
            "details": dict(ready.details),
        },
        "requests": [
            {
                "generation_index": index,
                "prompt_id": request.prompt_id,
                "prompt_sha256": hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
                "seed_id": request.seed_id,
                "seed": request.seed,
                "duration_seconds": request.duration_seconds,
                "output_path": str(request.output_path),
            }
            for index, request in enumerate(requests)
        ],
    }
    manifest_path = exclusive_write_json(destination / "manifest.json", manifest)
    ledger_path = destination / "generation-ledger.jsonl"
    rows: list[dict[str, Any]] = []
    previous = "0" * 64

    def terminal(status: str, *, error_type: str | None = None) -> dict[str, Any]:
        value = {
            "schema_version": 1,
            "status": status,
            "run_id": context.run_id,
            "started_at_utc": started,
            "finished_at_utc": _utc_now(),
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "generation_ledger_path": str(ledger_path),
            "generation_ledger_sha256": sha256_file(ledger_path),
            "generation_ledger_tail_sha256": previous,
            "model_calls": len(rows),
            "generated_outputs": sum(Path(row["output_path"]).is_file() for row in rows),
            "rows": rows,
            "no_retry": True,
            "benchmark_endpoints_scored": 0,
            "human_gold_claims": False,
        }
        if error_type is not None:
            value["error_type"] = error_type
        return value

    with ledger_path.open("xb") as ledger:
        for index, request in enumerate(requests):
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            base = {
                "schema_version": 1,
                "generation_index": index,
                "prompt_id": request.prompt_id,
                "prompt_sha256": hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
                "seed_id": request.seed_id,
                "seed": request.seed,
                "duration_seconds": request.duration_seconds,
                "output_path": str(request.output_path),
                "attempted_at_utc": _utc_now(),
            }
            try:
                measured = adapter.generate(request)
                provenance_path = write_adjacent_provenance(
                    measured.output_path,
                    {
                        "label": "synthetic_model_output",
                        "created_at_utc": _utc_now(),
                        "creating_command": context.command,
                        "run_id": context.run_id,
                        "source_ids": [
                            f"{adapter.model_id}@config-sha256:{adapter.config_sha256}"
                        ],
                        "model_revision": ready.details["receipt"][
                            "resolved_provider_revision"
                        ],
                        "license_identifier": adapter.license_identifier,
                        "transformation": "official offline Stable Audio Open text-to-audio decode",
                    },
                )
                sanity = _duration_adjudicated_sanity(
                    measured.output_path, request.duration_seconds
                )
                row = {
                    **base,
                    "status": "PASS" if sanity["pass"] else "AUDIO_SANITY_FAILED",
                    "cost_status": "MEASURED",
                    "requested_steps": measured.requested_steps,
                    "actual_nfe": measured.actual_nfe,
                    "wall_seconds": measured.wall_seconds,
                    "peak_allocated_bytes": measured.peak_allocated_bytes,
                    "peak_reserved_bytes": measured.peak_reserved_bytes,
                    "measurement_metadata": dict(measured.metadata),
                    "file_sha256": sha256_file(measured.output_path),
                    "decoded_waveform_sha256": sanity["decoded_waveform_sha256"],
                    "provenance_path": str(provenance_path),
                    "provenance_sha256": sha256_file(provenance_path),
                    "audio_sanity": sanity,
                }
            except BaseException as exc:
                row = {**base, "status": "MODEL_CALL_FAILED", "error_type": type(exc).__name__}
                previous = _append(ledger, row, previous)
                rows.append(row)
                result = terminal("FAILED_STOPPED_NO_RETRY", error_type=type(exc).__name__)
                exclusive_write_json(destination / "sao-mini-smoke-terminal.json", result)
                raise SaoMiniSmokeError(f"SAO call {index} failed; see retained terminal") from exc
            previous = _append(ledger, row, previous)
            rows.append(row)
            if row["status"] != "PASS":
                result = terminal("FAILED_STOPPED_NO_RETRY", error_type="AudioSanityFailure")
                exclusive_write_json(destination / "sao-mini-smoke-terminal.json", result)
                raise SaoMiniSmokeError(f"SAO call {index} failed audio sanity")

    reproducible = rows[0]["decoded_waveform_sha256"] == rows[1][
        "decoded_waveform_sha256"
    ]
    load_seconds = rows[0]["measurement_metadata"].get("load_wall_seconds")
    if isinstance(load_seconds, bool) or not isinstance(load_seconds, (int, float)):
        load_seconds = None
    if not reproducible or load_seconds is None or load_seconds < 0:
        result = terminal(
            "FAILED_STOPPED_NO_RETRY",
            error_type="ReproducibilityOrLoadMeasurementFailure",
        )
        result["reproducibility_hash_pass"] = reproducible
        exclusive_write_json(destination / "sao-mini-smoke-terminal.json", result)
        raise SaoMiniSmokeError("SAO reproducibility or load measurement failed")
    resident = max(float(rows[1]["wall_seconds"]), float(rows[2]["wall_seconds"]))
    cold = float(load_seconds) + float(rows[0]["wall_seconds"])
    cap = cold + 1535 * (2 * resident)
    result = terminal("PASS_MEASURED_READY")
    result.update(
        {
            "reproducibility_hash_pass": True,
            "reproducibility_decoded_waveform_sha256": rows[0][
                "decoded_waveform_sha256"
            ],
            "cost_calibration": {
                "cost_status": "MEASURED",
                "cold_plus_first_seconds": cold,
                "resident_unit_seconds": resident,
                "scheduled_core_calls": 1536,
                "gpu_seconds_cap": cap,
                "gpu_hours_cap": cap / 3600,
                "arithmetic_rule": "c=L0+W0; u=max(W1,W2); cap=c+1535*(2*u)",
            },
            "state_capability": "NOT_ATTEMPTED",
            "eligibility_scope_expanded": False,
        }
    )
    terminal_path = exclusive_write_json(destination / "sao-mini-smoke-terminal.json", result)
    return {**result, "terminal_path": str(terminal_path)}

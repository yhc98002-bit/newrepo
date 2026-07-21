"""Durable one-shot claims, ledgers, heartbeats, and ACE audio evidence."""

from __future__ import annotations

import fcntl
import json
import math
import os
import stat
import threading
import uuid
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from state_capture.ace_contract import (
    ATTEMPT_ID,
    RUN_ID,
    Authorization,
    LoadedContract,
    canonical_json_bytes,
    finite_nonnegative,
    json_sha256,
    sha256_file,
)

GENESIS_SHA256 = "0" * 64
CALL_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"CLAIMED"}),
    "CLAIMED": frozenset({"CALL_STARTED"}),
    "CALL_STARTED": frozenset({"SUCCEEDED", "FAILED"}),
    "SUCCEEDED": frozenset(),
    "FAILED": frozenset(),
}


class AttemptConsumed(RuntimeError):
    """The sole authorization already has a durable consumption seal."""


class ArtifactValidationError(ValueError):
    """An immutable artifact, chain, waveform, or provenance record is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_bytes_exclusive(path: str | Path, payload: bytes, *, mode: int = 0o444) -> Path:
    """Publish bytes atomically without an overwrite path."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.partial-{os.getpid()}-{uuid.uuid4().hex}"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
        os.chmod(destination, mode)
        _fsync_directory(destination.parent)
    except FileExistsError:
        raise
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()
    return destination


def write_json_exclusive(path: str | Path, payload: Mapping[str, Any]) -> Path:
    return write_bytes_exclusive(path, canonical_json_bytes(dict(payload), trailing_newline=True))


def safe_external_path(
    root: str | Path,
    *,
    repository_root: str | Path,
    name: str,
    must_exist: bool = False,
) -> Path:
    """Validate an external persistent root without creating it."""

    repository = Path(repository_root).resolve(strict=True)
    candidate = Path(root).resolve(strict=must_exist)
    try:
        candidate.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ArtifactValidationError(f"{name} must be outside the repository")
    if candidate == Path("/") or len(candidate.parts) < 4:
        raise ArtifactValidationError(f"{name} is too broad to use safely")
    if must_exist and not candidate.is_dir():
        raise ArtifactValidationError(f"{name} is not a directory")
    return candidate


class OneShotAttemptStore:
    """Consume and terminalize exactly one SHA-bound authorization attempt."""

    def __init__(
        self,
        claim_root: str | Path,
        *,
        claim_filename: str,
        repository_root: str | Path,
    ) -> None:
        root = safe_external_path(
            claim_root,
            repository_root=repository_root,
            name="claim_root",
        )
        if Path(claim_filename).name != claim_filename or not claim_filename.endswith(".json"):
            raise ArtifactValidationError("attempt claim filename is unsafe")
        self.root = root
        self.claim_path = root / claim_filename
        self.terminal_path = root / claim_filename.replace(".claim.json", ".terminal.json")

    def consume(
        self,
        *,
        authorization: Authorization,
        contract: LoadedContract,
        package_sha256: Mapping[str, str],
    ) -> dict[str, Any]:
        """Durably consume authority before any runtime/GPU/engine preflight."""

        if self.claim_path.exists() or self.terminal_path.exists():
            raise AttemptConsumed(
                f"one-shot ACE state preflight is already consumed: {self.claim_path}"
            )
        record: dict[str, Any] = {
            "schema_version": 1,
            "claim_type": "SOLE_ACE_STATE_PREFLIGHT_AUTHORIZED_ATTEMPT",
            "run_id": RUN_ID,
            "attempt_id": ATTEMPT_ID,
            "claimed_at_utc": utc_now(),
            "authorization_path": str(authorization.path),
            "authorization_sha256": authorization.sha256,
            "attempt_token_sha256": authorization.attempt_token_sha256,
            "config_path": str(contract.path),
            "config_sha256": contract.sha256,
            "git_commit": authorization.git_commit,
            "node": authorization.node,
            "physical_gpu_id": authorization.physical_gpu_id,
            "caps": dict(contract.raw["caps"]),
            "package_sha256": dict(package_sha256),
            "retry_allowed": False,
        }
        record["claim_identity_sha256"] = json_sha256(record)
        try:
            write_json_exclusive(self.claim_path, record)
        except FileExistsError as exc:
            raise AttemptConsumed("one-shot claim raced with another process") from exc
        observed = validate_attempt_claim(
            self.claim_path,
            expected_token=authorization.attempt_token_sha256,
            expected_authorization_sha256=authorization.sha256,
        )
        return {**observed, "path": str(self.claim_path), "sha256": sha256_file(self.claim_path)}

    def write_terminal(
        self,
        *,
        status: str,
        claim_sha256: str,
        ledger_path: str | Path | None,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if status not in {"PASS", "FAIL"}:
            raise ArtifactValidationError("attempt terminal status must be PASS or FAIL")
        claim = validate_attempt_claim(self.claim_path)
        if sha256_file(self.claim_path) != claim_sha256:
            raise ArtifactValidationError("attempt claim changed before terminalization")
        terminal: dict[str, Any] = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "attempt_id": ATTEMPT_ID,
            "status": status,
            "finished_at_utc": utc_now(),
            "attempt_claim_path": str(self.claim_path),
            "attempt_claim_sha256": claim_sha256,
            "attempt_token_sha256": claim["attempt_token_sha256"],
            "retry_allowed": False,
            "payload": dict(payload),
        }
        if ledger_path is not None:
            ledger = Path(ledger_path)
            terminal["ledger_path"] = str(ledger)
            terminal["ledger_sha256"] = sha256_file(ledger)
            rows = validate_ledger(ledger)
            terminal["ledger_tail_sha256"] = (
                rows[-1]["ledger_row_sha256"] if rows else GENESIS_SHA256
            )
        terminal["terminal_identity_sha256"] = json_sha256(terminal)
        try:
            write_json_exclusive(self.terminal_path, terminal)
        except FileExistsError as exc:
            raise AttemptConsumed("one-shot attempt already has a terminal record") from exc
        return {
            **terminal,
            "path": str(self.terminal_path),
            "sha256": sha256_file(self.terminal_path),
        }


def validate_attempt_claim(
    path: str | Path,
    *,
    expected_token: str | None = None,
    expected_authorization_sha256: str | None = None,
) -> dict[str, Any]:
    source = Path(path)
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError("attempt claim is absent or invalid JSON") from exc
    if not isinstance(record, dict):
        raise ArtifactValidationError("attempt claim is not an object")
    claimed_identity = record.get("claim_identity_sha256")
    unhashed = dict(record)
    unhashed.pop("claim_identity_sha256", None)
    if claimed_identity != json_sha256(unhashed):
        raise ArtifactValidationError("attempt claim identity hash mismatch")
    if record.get("run_id") != RUN_ID or record.get("attempt_id") != ATTEMPT_ID:
        raise ArtifactValidationError("attempt claim fixed identity changed")
    if record.get("retry_allowed") is not False:
        raise ArtifactValidationError("attempt claim permits a retry")
    if expected_token is not None and record.get("attempt_token_sha256") != expected_token:
        raise ArtifactValidationError("attempt token differs from authorization")
    if (
        expected_authorization_sha256 is not None
        and record.get("authorization_sha256") != expected_authorization_sha256
    ):
        raise ArtifactValidationError("attempt authorization hash changed")
    return record


def validate_ledger(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    previous = GENESIS_SHA256
    call_states: dict[str, str] = {}
    raw = source.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ArtifactValidationError("ledger lacks a final newline")
    for expected_index, line in enumerate(raw.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArtifactValidationError("ledger row is invalid JSON") from exc
        if not isinstance(row, dict):
            raise ArtifactValidationError("ledger row is not an object")
        claimed = row.get("ledger_row_sha256")
        unhashed = dict(row)
        unhashed.pop("ledger_row_sha256", None)
        if row.get("ledger_index") != expected_index:
            raise ArtifactValidationError("ledger indices are not contiguous")
        if row.get("previous_row_sha256") != previous:
            raise ArtifactValidationError("ledger previous-row link mismatch")
        observed = json_sha256(unhashed)
        if claimed != observed:
            raise ArtifactValidationError("ledger row hash mismatch")
        previous = observed
        rows.append(row)
        if row.get("event_kind") == "MODEL_CALL_STATE":
            call_id = row.get("call_id")
            state = row.get("call_state")
            if not isinstance(call_id, str) or not call_id:
                raise ArtifactValidationError("call-state row lacks call_id")
            if not isinstance(state, str) or state not in CALL_TRANSITIONS:
                raise ArtifactValidationError("call-state row has invalid state")
            prior = call_states.get(call_id)
            if state not in CALL_TRANSITIONS[prior]:
                raise ArtifactValidationError(
                    f"invalid call transition {call_id}: {prior}->{state}"
                )
            call_states[call_id] = state
    return rows


class HashChainedLedger:
    """Fsync every append and enforce no-retry model-call transitions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
            _fsync_directory(self.path.parent)
        if not self.path.is_file():
            raise ArtifactValidationError("ledger path is not a regular file")

    def _append_locked(
        self, handle: Any, rows: list[dict[str, Any]], payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        if {"ledger_index", "previous_row_sha256", "ledger_row_sha256"}.intersection(payload):
            raise ArtifactValidationError("ledger payload uses a reserved field")
        row = dict(payload)
        row["ledger_index"] = len(rows) + 1
        row["previous_row_sha256"] = (
            rows[-1]["ledger_row_sha256"] if rows else GENESIS_SHA256
        )
        row["ledger_row_sha256"] = json_sha256(row)
        handle.seek(0, os.SEEK_END)
        handle.write(canonical_json_bytes(row, trailing_newline=True))
        handle.flush()
        os.fsync(handle.fileno())
        return row

    def append(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        # The file itself is read-only to discourage accidental shell edits; the
        # owning process temporarily opens it read/write and restores mode.
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        try:
            with self.path.open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    rows = validate_ledger(self.path)
                    return self._append_locked(handle, rows, payload)
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    def transition(
        self,
        call_id: str,
        state: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not call_id or state not in CALL_TRANSITIONS:
            raise ArtifactValidationError("invalid call transition identity")
        supplied = dict(payload or {})
        if {"event_kind", "call_id", "call_state"}.intersection(supplied):
            raise ArtifactValidationError("call transition payload uses a reserved field")
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        try:
            with self.path.open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    rows = validate_ledger(self.path)
                    states = {
                        row["call_id"]: row["call_state"]
                        for row in rows
                        if row.get("event_kind") == "MODEL_CALL_STATE"
                    }
                    prior = states.get(call_id)
                    if state not in CALL_TRANSITIONS[prior]:
                        raise ArtifactValidationError(
                            f"invalid call transition {call_id}: {prior}->{state}"
                        )
                    supplied.update(
                        {
                            "event_kind": "MODEL_CALL_STATE",
                            "call_id": call_id,
                            "call_state": state,
                            "recorded_at_utc": utc_now(),
                        }
                    )
                    return self._append_locked(handle, rows, supplied)
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    def tail_sha256(self) -> str:
        rows = validate_ledger(self.path)
        return rows[-1]["ledger_row_sha256"] if rows else GENESIS_SHA256


def _write_mutable_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    destination = path
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


class Heartbeat:
    """Refresh the complete placement/budget/ledger record at most every 60 s."""

    def __init__(
        self,
        path: str | Path,
        *,
        base: Mapping[str, Any],
        interval_seconds: float,
    ) -> None:
        if not math.isfinite(interval_seconds) or not 0 < interval_seconds <= 60:
            raise ArtifactValidationError("heartbeat interval must be in (0,60]")
        self.path = Path(path)
        self.interval_seconds = float(interval_seconds)
        self._payload = {
            **dict(base),
            "current_call_id": None,
            "completed_calls": 0,
            "failed_calls": 0,
            "cumulative_gpu_seconds": 0.0,
            "peak_allocated_bytes": 0,
            "peak_reserved_bytes": 0,
            "last_ledger_sha256": GENESIS_SHA256,
            "state": "CLAIMED",
            "updated_at_utc": utc_now(),
        }
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def _write(self) -> None:
        with self._write_lock:
            with self._lock:
                payload = {**self._payload, "updated_at_utc": utc_now()}
                self._payload = payload
            _write_mutable_json_atomic(self.path, payload)

    def _run(self) -> None:
        try:
            while not self._stop.wait(self.interval_seconds):
                self._write()
        except BaseException as exc:  # noqa: BLE001 - surfaced at next boundary
            self._failure = exc

    def start(self) -> Heartbeat:
        self._write()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ace-heartbeat")
        self._thread.start()
        return self

    def update(self, **changes: Any) -> None:
        if self._failure is not None:
            raise RuntimeError("heartbeat writer failed") from self._failure
        permitted = {
            "current_call_id",
            "completed_calls",
            "failed_calls",
            "cumulative_gpu_seconds",
            "peak_allocated_bytes",
            "peak_reserved_bytes",
            "last_ledger_sha256",
            "state",
        }
        if set(changes).difference(permitted):
            raise ArtifactValidationError("heartbeat update contains an unknown field")
        with self._lock:
            self._payload.update(changes)
        self._write()

    def close(self, *, final_state: str) -> None:
        self.update(state=final_state, current_call_id=None)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(5.0, self.interval_seconds + 1.0))
        if self._failure is not None:
            raise RuntimeError("heartbeat writer failed") from self._failure

    def __enter__(self) -> Heartbeat:
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close(final_state="FAILED" if exc is not None else "COMPLETE")


def basic_audio_sanity(
    path: str | Path,
    *,
    requested_duration_seconds: float,
    sample_rate: int = 48000,
    channels: int = 2,
    duration_tolerance_seconds: float = 0.25,
) -> dict[str, Any]:
    """Fully decode retained audio and reject corrupt, silent, or non-finite data."""

    source = Path(path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise ArtifactValidationError(f"audio is absent or empty: {source}")
    info = sf.info(source)
    if info.samplerate != sample_rate or info.channels != channels or info.frames <= 0:
        raise ArtifactValidationError("audio metadata differs from the frozen format")
    duration = info.frames / info.samplerate
    duration_error = abs(duration - requested_duration_seconds)
    if duration_error > duration_tolerance_seconds:
        raise ArtifactValidationError("audio duration exceeds the frozen tolerance")
    waveform, decoded_rate = sf.read(source, dtype="float32", always_2d=True)
    if decoded_rate != sample_rate or waveform.shape != (info.frames, channels):
        raise ArtifactValidationError("decoded audio shape differs from metadata")
    if not np.isfinite(waveform).all():
        raise ArtifactValidationError("decoded audio contains non-finite samples")
    peak = float(np.max(np.abs(waveform)))
    rms = float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64))))
    if not math.isfinite(peak) or not math.isfinite(rms) or rms <= 1e-8:
        raise ArtifactValidationError("decoded audio is silent or invalid")
    return {
        "status": "PASS",
        "path": str(source.resolve()),
        "sha256": sha256_file(source),
        "size_bytes": source.stat().st_size,
        "sample_rate": sample_rate,
        "channels": channels,
        "frames": info.frames,
        "duration_seconds": duration,
        "duration_error_seconds": duration_error,
        "duration_tolerance_seconds": duration_tolerance_seconds,
        "peak_absolute": peak,
        "rms": rms,
    }


def compare_audio_equivalence(
    reference_path: str | Path,
    resumed_path: str | Path,
    *,
    max_absolute_error: float,
    minimum_snr_db: float,
) -> dict[str, Any]:
    """Compare complete decoded waveforms under the documented tolerance."""

    reference, reference_rate = sf.read(reference_path, dtype="float64", always_2d=True)
    resumed, resumed_rate = sf.read(resumed_path, dtype="float64", always_2d=True)
    if reference_rate != resumed_rate or reference.shape != resumed.shape:
        raise ArtifactValidationError("resume waveform rate/shape differs from reference")
    if not np.isfinite(reference).all() or not np.isfinite(resumed).all():
        raise ArtifactValidationError("equivalence waveform contains non-finite values")
    delta = resumed - reference
    maximum = float(np.max(np.abs(delta))) if delta.size else 0.0
    signal_energy = float(np.sum(np.square(reference, dtype=np.float64)))
    error_energy = float(np.sum(np.square(delta, dtype=np.float64)))
    if error_energy == 0.0:
        snr_db: float | None = None
        snr_infinite = True
        snr_pass = True
    elif signal_energy <= 0.0:
        snr_db = -math.inf
        snr_infinite = False
        snr_pass = False
    else:
        snr_db = 10.0 * math.log10(signal_energy / error_energy)
        snr_infinite = False
        snr_pass = snr_db >= minimum_snr_db
    passed = maximum <= max_absolute_error and snr_pass
    result = {
        "status": "PASS" if passed else "FAIL",
        "reference_path": str(Path(reference_path).resolve()),
        "reference_sha256": sha256_file(reference_path),
        "resumed_path": str(Path(resumed_path).resolve()),
        "resumed_sha256": sha256_file(resumed_path),
        "sample_rate": reference_rate,
        "frames": int(reference.shape[0]),
        "channels": int(reference.shape[1]),
        "max_absolute_error": maximum,
        "max_absolute_error_tolerance": float(max_absolute_error),
        "snr_db": snr_db if snr_db is None or math.isfinite(snr_db) else None,
        "snr_db_infinite": snr_infinite,
        "minimum_snr_db": float(minimum_snr_db),
    }
    if not passed:
        raise ArtifactValidationError(
            f"resume audio failed equivalence: max_abs={maximum}, snr_db={snr_db}"
        )
    return result


def write_adjacent_provenance(
    artifact_path: str | Path,
    *,
    label: str,
    run_id: str,
    creating_call_id: str,
    model_revision: str,
    source_ids: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write immutable provenance adjacent to one already-retained artifact."""

    artifact = Path(artifact_path).resolve(strict=True)
    record: dict[str, Any] = {
        "schema_version": 1,
        "label": label,
        "path": str(artifact),
        "sha256": sha256_file(artifact),
        "size_bytes": artifact.stat().st_size,
        "created_at_utc": utc_now(),
        "creating_call_id": creating_call_id,
        "run_id": run_id,
        "source_ids": dict(source_ids),
        "model_revision": model_revision,
        "license_identifier": "Apache-2.0",
        "transformation": "ACE_STEP_V1_OFFICIAL_PIPELINE_WITH_HASH_GUARDED_STATE_INTERPOSITION",
    }
    if extra:
        record["extra"] = dict(extra)
    destination = artifact.with_name(f"{artifact.name}.provenance.json")
    write_json_exclusive(destination, record)
    validated = validate_adjacent_provenance(artifact)
    return {**validated, "path": str(destination), "sha256": sha256_file(destination)}


def validate_adjacent_provenance(artifact_path: str | Path) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve(strict=True)
    path = artifact.with_name(f"{artifact.name}.provenance.json")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError("adjacent provenance is absent or invalid") from exc
    required = {
        "schema_version",
        "label",
        "path",
        "sha256",
        "size_bytes",
        "created_at_utc",
        "creating_call_id",
        "run_id",
        "source_ids",
        "model_revision",
        "license_identifier",
        "transformation",
    }
    if not isinstance(record, dict) or not required.issubset(record):
        raise ArtifactValidationError("adjacent provenance schema is incomplete")
    if record.get("path") != str(artifact):
        raise ArtifactValidationError("provenance artifact path changed")
    if record.get("sha256") != sha256_file(artifact):
        raise ArtifactValidationError("provenance artifact hash mismatch")
    if record.get("size_bytes") != artifact.stat().st_size:
        raise ArtifactValidationError("provenance artifact size mismatch")
    return record


def aggregate_gpu_measurements(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    seconds = sum(finite_nonnegative(row.get("gpu_seconds"), "gpu_seconds") for row in results)
    peak_allocated = max((int(row.get("peak_allocated_bytes", 0)) for row in results), default=0)
    peak_reserved = max((int(row.get("peak_reserved_bytes", 0)) for row in results), default=0)
    return {
        "cumulative_gpu_seconds": seconds,
        "peak_allocated_bytes": peak_allocated,
        "peak_reserved_bytes": peak_reserved,
    }

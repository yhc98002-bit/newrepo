"""Fail-closed execution budget and per-generation evidence ledger.

The parent runner and the three Smoke E child interpreters share one state
file protected by ``flock``.  A reservation consumes its call/output quota
before the official model call, so a failed call cannot be retried implicitly.
Only CUDA-synchronized ``StableAudioModel.generate`` wall time contributes to
the GPU-seconds cap.  Crossing that cap does not discard the current output:
the caller may finish its exclusive WAV/provenance/sanity writes, but the next
reservation is rejected.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sa3_smoke.artifacts import sha256_file

MAX_GENERATIONS = 20
MAX_CLIP_SECONDS = 30.0
MAX_GPUS = 1
MAX_GPU_SECONDS = 1_800.0

FROZEN_SEEDS: Mapping[str, int] = {
    "S-0001": 73_193_001,
    "S-0002": 73_193_002,
    "S-0003": 73_193_003,
    "S-0004": 73_193_004,
    "S-0005": 73_193_005,
    "S-0006": 73_193_006,
    "S-0007": 73_193_007,
}
SEED_ID_BY_VALUE: Mapping[int, str] = {value: key for key, value in FROZEN_SEEDS.items()}

# D-0014 corrects D-0013's accidental omission of the required D batch-one
# cost call.  A reservation must fit this plan as well as the hard caps.
EXPECTED_CALLS_BY_SMOKE: Mapping[str, int] = {"A": 2, "B": 1, "C": 2, "D": 2, "E": 4}
EXPECTED_GENERATIONS_BY_SMOKE: Mapping[str, int] = {
    "A": 2,
    "B": 1,
    "C": 2,
    "D": 5,
    "E": 4,
}
EXPECTED_SEED_CALLS: Mapping[str, Mapping[str, int]] = {
    "A": {"S-0001": 2},
    "B": {"S-0002": 1},
    "C": {"S-0003": 1, "S-0004": 1},
    "D": {"S-0005": 1, "S-0006": 1},
    "E": {"S-0007": 4},
}
EXPECTED_CALL_SHAPES: Mapping[str, tuple[float, int]] = {
    "S-0001": (30.0, 1),
    "S-0002": (30.0, 1),
    "S-0003": (30.0, 1),
    "S-0004": (30.0, 1),
    "S-0005": (30.0, 1),
    "S-0006": (10.0, 4),
    "S-0007": (30.0, 1),
}
EXPECTED_CALLS = sum(EXPECTED_CALLS_BY_SMOKE.values())
EXPECTED_GENERATIONS = sum(EXPECTED_GENERATIONS_BY_SMOKE.values())
BASE_PROMPT = (
    "A steady instrumental electronic music loop with drums, bass, and warm "
    "synthesizer, clean studio recording, 120 BPM"
)
EXPECTED_PROMPTS_BY_SEED: Mapping[str, str | tuple[str, ...]] = {
    "S-0001": BASE_PROMPT,
    "S-0002": (
        "Continue the same instrumental electronic music with consistent rhythm and instrumentation"
    ),
    "S-0003": (
        "A seamless instrumental electronic music passage with steady drums and warm synthesizer"
    ),
    "S-0004": (
        "A seamless instrumental electronic music passage with steady drums and warm synthesizer"
    ),
    "S-0005": BASE_PROMPT,
    "S-0006": (
        "Steady electronic drums and warm synthesizer, 100 BPM",
        "Clean acoustic guitar rhythm with light percussion, 110 BPM",
        "Ambient synthesizer pulse with a steady beat, 90 BPM",
        "Bright piano groove with bass and drums, 120 BPM",
    ),
    "S-0007": BASE_PROMPT,
}
EXPECTED_NEGATIVE_PROMPT = "low quality, clipping, silence"

ENV_STATE_PATH = "SA3_FOUNDATION_BUDGET_STATE"
ENV_LEDGER_PATH = "SA3_FOUNDATION_GENERATION_LEDGER"
ENV_LOCK_PATH = "SA3_FOUNDATION_BUDGET_LOCK"
ENV_CLAIM_PATH = "SA3_FOUNDATION_EXECUTION_CLAIM"
ENV_SMOKE = "SA3_FOUNDATION_CURRENT_SMOKE"
CLAIM_NAME = ".sa3-foundation-d0014-execution-claim.json"


class BudgetExceeded(RuntimeError):
    """A model call was rejected before execution by a binding guard."""


class BudgetEvidenceError(RuntimeError):
    """Budget state, seed, or retained-artifact evidence is invalid."""


def _validate_official_kwargs(seed_id: str, kwargs: Mapping[str, Any]) -> None:
    """Reject any same-seed official call that drifts from the frozen request."""

    expected_prompt = EXPECTED_PROMPTS_BY_SEED[seed_id]
    observed_prompt = kwargs.get("prompt")
    if isinstance(expected_prompt, tuple):
        if not isinstance(observed_prompt, Sequence) or isinstance(observed_prompt, (str, bytes)):
            raise BudgetExceeded(f"{seed_id} requires the frozen batch-four prompt list")
        if tuple(observed_prompt) != expected_prompt:
            raise BudgetExceeded(f"{seed_id} prompt list differs from the frozen config")
    elif observed_prompt != expected_prompt:
        raise BudgetExceeded(f"{seed_id} prompt differs from the frozen config")
    expected_fields = {
        "negative_prompt": EXPECTED_NEGATIVE_PROMPT,
        "steps": 50,
        "cfg_scale": 7.0,
        "sampler_type": "euler",
        "duration_padding_sec": 6.0,
        "truncate_output_to_duration": True,
        "chunked_decode": True,
        "disable_tqdm": True,
    }
    for name, expected in expected_fields.items():
        if kwargs.get(name) != expected:
            raise BudgetExceeded(
                f"{seed_id} official argument {name} differs from frozen value {expected!r}"
            )
    expected_inpaint = {
        "S-0002": (10.0, 30.0),
        "S-0003": (8.0, 12.0),
        "S-0004": ([4.0, 20.0], [6.0, 23.0]),
    }
    if seed_id in expected_inpaint:
        if kwargs.get("inpaint_audio") is None:
            raise BudgetExceeded(f"{seed_id} requires the frozen inpaint_audio path")
        starts, ends = expected_inpaint[seed_id]
        if (
            kwargs.get("inpaint_mask_start_seconds") != starts
            or kwargs.get("inpaint_mask_end_seconds") != ends
        ):
            raise BudgetExceeded(f"{seed_id} inpaint mask differs from the frozen config")
    elif any(
        name in kwargs
        for name in (
            "inpaint_audio",
            "inpaint_mask_start_seconds",
            "inpaint_mask_end_seconds",
        )
    ):
        raise BudgetExceeded(f"{seed_id} is not authorized to use an inpaint path")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strict_json(value: Any) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise OSError("short write while retaining execution-budget evidence")
        view = view[count:]


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(fd, (_strict_json(dict(value)) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(fd, (_strict_json(dict(value)) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BudgetEvidenceError(f"invalid budget evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BudgetEvidenceError(f"budget evidence root is not an object: {path}")
    return value


def _visible_gpu_ids() -> tuple[str, ...]:
    value = os.environ.get("CUDA_VISIBLE_DEVICES")
    if value is None:
        raise BudgetExceeded("CUDA_VISIBLE_DEVICES must explicitly bind the one authorized GPU")
    identifiers = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(identifiers) != MAX_GPUS:
        raise BudgetExceeded(
            f"MAX_GPUS={MAX_GPUS} requires exactly one visible GPU, got {list(identifiers)}"
        )
    return identifiers


def seed_id_for(seed: int) -> str:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BudgetEvidenceError("generation seed must be an integer")
    try:
        return SEED_ID_BY_VALUE[seed]
    except KeyError as exc:
        raise BudgetEvidenceError(f"seed {seed} is not in frozen SEED_REGISTRY.md v1") from exc


@dataclass(frozen=True)
class BudgetPaths:
    state: Path
    ledger: Path
    lock: Path
    claim: Path


@dataclass(frozen=True)
class CallReservation:
    call_id: str
    smoke: str
    seed_id: str
    seed: int
    duration_seconds: float
    batch_size: int
    generation_ids: tuple[str, ...]
    process_id: int


class ExecutionBudget:
    """Cross-process hard-cap state for one authorized foundation run."""

    def __init__(self, paths: BudgetPaths) -> None:
        self.paths = paths

    @classmethod
    def initialize(
        cls,
        *,
        run_dir: str | os.PathLike[str],
        run_root: str | os.PathLike[str],
        claim_identity: Mapping[str, Any],
    ) -> ExecutionBudget:
        run = Path(run_dir).resolve()
        root = Path(run_root).resolve()
        paths = BudgetPaths(
            state=run / "execution-budget.state.json",
            ledger=run / "generation-ledger.jsonl",
            lock=run / ".execution-budget.lock",
            claim=root / CLAIM_NAME,
        )
        caps = {
            "max_generations": MAX_GENERATIONS,
            "max_clip_seconds": MAX_CLIP_SECONDS,
            "max_gpus": MAX_GPUS,
            "max_gpu_seconds": MAX_GPU_SECONDS,
        }
        plan = {
            "official_generate_calls": EXPECTED_CALLS,
            "generated_outputs": EXPECTED_GENERATIONS,
            "calls_by_smoke": dict(EXPECTED_CALLS_BY_SMOKE),
            "generations_by_smoke": dict(EXPECTED_GENERATIONS_BY_SMOKE),
            "seed_calls": {key: dict(value) for key, value in EXPECTED_SEED_CALLS.items()},
        }
        claim = {
            "schema_version": 1,
            "decision": "D-0013 as corrected before execution by D-0014",
            "created_at_utc": _utc_now(),
            "run_dir": str(run),
            "creator_pid": os.getpid(),
            "identity": dict(claim_identity),
            "caps": caps,
            "exact_plan": plan,
            "no_retry_without_later_append_only_decision": True,
        }
        # This fixed, run-root-local claim is intentionally created first.  A
        # second invocation cannot consume model compute merely by selecting a
        # fresh immutable run directory.
        try:
            _exclusive_json(paths.claim, claim)
        except FileExistsError as exc:
            raise BudgetExceeded(
                "the one D-0013/D-0014 foundation execution claim already exists; "
                "a retry requires a later append-only authorization decision"
            ) from exc

        state = {
            "schema_version": 1,
            "run_dir": str(run),
            "claim_path": str(paths.claim),
            "claim_sha256": sha256_file(paths.claim),
            "created_at_utc": claim["created_at_utc"],
            "model_load_started_monotonic_ns": time.monotonic_ns(),
            "caps": caps,
            "exact_plan": plan,
            "official_generate_calls_reserved": 0,
            "generation_slots_reserved": 0,
            "successful_model_calls": 0,
            "failed_model_calls": 0,
            "generated_outputs": 0,
            "ledgered_outputs": 0,
            "terminal_failure_ledger_rows": 0,
            "cumulative_synchronized_gpu_wall_seconds": 0.0,
            "time_cap_reached": False,
            "gpu_residency_upper_bound_seconds": 0.0,
            "residency_cap_reached": False,
            "calls_by_smoke": {},
            "generations_by_smoke": {},
            "seed_calls_by_smoke": {},
            "calls": [],
            "last_ledger_row_sha256": None,
            "finalized_at_utc": None,
            "exact_plan_completed": False,
            "measurement_evidence_complete": False,
        }
        try:
            _exclusive_json(paths.state, state)
            ledger_fd = os.open(paths.ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fsync(ledger_fd)
            os.close(ledger_fd)
            lock_fd = os.open(paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(lock_fd)
        except Exception:
            # The external claim deliberately remains: initialization failure
            # must not silently reopen the authorized one-run window.
            raise
        budget = cls(paths)
        budget.activate()
        return budget

    @classmethod
    def from_environment(cls) -> ExecutionBudget | None:
        values = {
            "state": os.environ.get(ENV_STATE_PATH),
            "ledger": os.environ.get(ENV_LEDGER_PATH),
            "lock": os.environ.get(ENV_LOCK_PATH),
            "claim": os.environ.get(ENV_CLAIM_PATH),
        }
        if not any(values.values()):
            return None
        if not all(values.values()):
            raise BudgetEvidenceError("partial execution-budget environment is fail-closed")
        paths = BudgetPaths(**{key: Path(str(value)).resolve() for key, value in values.items()})
        for path in (paths.state, paths.ledger, paths.lock, paths.claim):
            if not path.is_file():
                raise BudgetEvidenceError(f"execution-budget evidence is missing: {path}")
        state = _read_object(paths.state)
        if state.get("claim_sha256") != sha256_file(paths.claim):
            raise BudgetEvidenceError("execution claim changed after budget initialization")
        return cls(paths)

    def activate(self) -> None:
        os.environ.update(
            {
                ENV_STATE_PATH: str(self.paths.state),
                ENV_LEDGER_PATH: str(self.paths.ledger),
                ENV_LOCK_PATH: str(self.paths.lock),
                ENV_CLAIM_PATH: str(self.paths.claim),
            }
        )

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        with self.paths.lock.open("r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            state = _read_object(self.paths.state)
            if state.get("claim_sha256") != sha256_file(self.paths.claim):
                raise BudgetEvidenceError("execution claim changed after budget initialization")
            try:
                yield state
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def reserve_call(
        self,
        *,
        smoke: str,
        seed_id: str,
        seed: int,
        duration_seconds: float,
        batch_size: int,
        prompt: str | Sequence[str] | None = None,
        generation_parameters: Mapping[str, Any] | None = None,
    ) -> CallReservation:
        """Consume a call/output slot before any official model invocation."""

        _visible_gpu_ids()
        if smoke not in EXPECTED_CALLS_BY_SMOKE:
            raise BudgetExceeded(f"unknown or unauthorized smoke context: {smoke!r}")
        if seed_id not in FROZEN_SEEDS or FROZEN_SEEDS[seed_id] != seed:
            raise BudgetExceeded(
                f"unregistered seed pair rejected: seed_id={seed_id!r}, seed={seed!r}"
            )
        if seed_id not in EXPECTED_SEED_CALLS[smoke]:
            raise BudgetExceeded(f"{seed_id} is not authorized for smoke {smoke}")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise BudgetExceeded("batch_size must be a positive integer")
        duration = float(duration_seconds)
        if not math.isfinite(duration) or not (0.0 < duration <= MAX_CLIP_SECONDS):
            raise BudgetExceeded(
                f"clip duration {duration!r} violates MAX_CLIP_SECONDS={MAX_CLIP_SECONDS:g}"
            )
        expected_duration, expected_batch = EXPECTED_CALL_SHAPES[seed_id]
        if duration != expected_duration or batch_size != expected_batch:
            raise BudgetExceeded(
                f"{seed_id} call shape must be duration={expected_duration:g}, "
                f"batch_size={expected_batch}; got duration={duration:g}, batch_size={batch_size}"
            )

        with self._locked_state() as state:
            cumulative = float(state["cumulative_synchronized_gpu_wall_seconds"])
            residency = (time.monotonic_ns() - int(state["model_load_started_monotonic_ns"])) / 1e9
            state["gpu_residency_upper_bound_seconds"] = residency
            state["residency_cap_reached"] = residency >= MAX_GPU_SECONDS
            if state["time_cap_reached"] or cumulative >= MAX_GPU_SECONDS:
                raise BudgetExceeded(
                    f"measured GPU wall cap reached ({cumulative:.9f} >= {MAX_GPU_SECONDS:g}); "
                    "no next model call is permitted"
                )
            if state["residency_cap_reached"]:
                _replace_json(self.paths.state, state)
                raise BudgetExceeded(
                    f"one-GPU residency upper bound reached ({residency:.9f} >= "
                    f"{MAX_GPU_SECONDS:g}); no next model call is permitted"
                )
            smoke_calls = int(state["calls_by_smoke"].get(smoke, 0))
            smoke_generations = int(state["generations_by_smoke"].get(smoke, 0))
            seed_calls = state["seed_calls_by_smoke"].setdefault(smoke, {})
            prior_seed_calls = int(seed_calls.get(seed_id, 0))
            if smoke_calls + 1 > EXPECTED_CALLS_BY_SMOKE[smoke]:
                raise BudgetExceeded(f"smoke {smoke} exact call quota would be exceeded")
            if smoke_generations + batch_size > EXPECTED_GENERATIONS_BY_SMOKE[smoke]:
                raise BudgetExceeded(f"smoke {smoke} exact output quota would be exceeded")
            if prior_seed_calls + 1 > EXPECTED_SEED_CALLS[smoke][seed_id]:
                raise BudgetExceeded(f"{smoke}/{seed_id} call quota would be exceeded")
            reserved = int(state["generation_slots_reserved"])
            if reserved + batch_size > MAX_GENERATIONS:
                raise BudgetExceeded(
                    f"call would exceed MAX_GENERATIONS={MAX_GENERATIONS}: "
                    f"{reserved} + {batch_size}"
                )

            call_index = int(state["official_generate_calls_reserved"]) + 1
            call_id = f"call-{call_index:02d}"
            generation_ids = tuple(
                f"generation-{index:02d}"
                for index in range(reserved + 1, reserved + batch_size + 1)
            )
            call = {
                "call_id": call_id,
                "smoke": smoke,
                "seed_id": seed_id,
                "seed": seed,
                "duration_seconds": duration,
                "batch_size": batch_size,
                "prompt": prompt if isinstance(prompt, str) else list(prompt or ()),
                "generation_parameters": dict(generation_parameters or {}),
                "generation_ids": list(generation_ids),
                "process_id": os.getpid(),
                "reserved_at_utc": _utc_now(),
                "status": "RESERVED",
                "synchronized_gpu_wall_seconds": None,
                "measurements": None,
                "artifact_generation_ids": [],
                "terminal_ledger_generation_ids": [],
            }
            state["official_generate_calls_reserved"] = call_index
            state["generation_slots_reserved"] = reserved + batch_size
            state["calls_by_smoke"][smoke] = smoke_calls + 1
            state["generations_by_smoke"][smoke] = smoke_generations + batch_size
            seed_calls[seed_id] = prior_seed_calls + 1
            state["calls"].append(call)
            _replace_json(self.paths.state, state)
        return CallReservation(
            call_id=call_id,
            smoke=smoke,
            seed_id=seed_id,
            seed=seed,
            duration_seconds=duration,
            batch_size=batch_size,
            generation_ids=generation_ids,
            process_id=os.getpid(),
        )

    def complete_call(
        self,
        reservation: CallReservation,
        *,
        synchronized_gpu_wall_seconds: float,
        succeeded: bool,
        measurements: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        elapsed = float(synchronized_gpu_wall_seconds)
        if not math.isfinite(elapsed) or elapsed < 0.0:
            raise BudgetEvidenceError("synchronized GPU wall time must be finite and non-negative")
        with self._locked_state() as state:
            matches = [row for row in state["calls"] if row["call_id"] == reservation.call_id]
            if len(matches) != 1 or matches[0]["status"] != "RESERVED":
                raise BudgetEvidenceError(
                    f"reservation {reservation.call_id} is missing or already terminal"
                )
            row = matches[0]
            row.update(
                {
                    "status": "GENERATED" if succeeded else "MODEL_CALL_FAILED",
                    "completed_at_utc": _utc_now(),
                    "synchronized_gpu_wall_seconds": elapsed,
                    "measurements": dict(measurements or {}),
                    "error": error,
                }
            )
            cumulative = float(state["cumulative_synchronized_gpu_wall_seconds"]) + elapsed
            state["cumulative_synchronized_gpu_wall_seconds"] = cumulative
            state["time_cap_reached"] = cumulative >= MAX_GPU_SECONDS
            residency = (time.monotonic_ns() - int(state["model_load_started_monotonic_ns"])) / 1e9
            state["gpu_residency_upper_bound_seconds"] = residency
            state["residency_cap_reached"] = residency >= MAX_GPU_SECONDS
            counter = "successful_model_calls" if succeeded else "failed_model_calls"
            state[counter] = int(state[counter]) + 1
            if succeeded:
                state["generated_outputs"] = (
                    int(state["generated_outputs"]) + reservation.batch_size
                )
            _replace_json(self.paths.state, state)

    def finalize_latest_audio(
        self,
        artifacts: Sequence[Mapping[str, Any]],
        *,
        smoke: str,
    ) -> tuple[Mapping[str, Any], ...]:
        """Append one hash-chained row per retained output after all checks exist."""

        normalized = [dict(artifact) for artifact in artifacts]
        with self._locked_state() as state:
            pending = [
                row
                for row in state["calls"]
                if row["process_id"] == os.getpid()
                and row["smoke"] == smoke
                and row["status"] == "GENERATED"
                and not row["artifact_generation_ids"]
            ]
            if len(pending) != 1:
                raise BudgetEvidenceError(
                    f"expected exactly one generated, unledgered {smoke} call in pid "
                    f"{os.getpid()}, found {len(pending)}"
                )
            call = pending[0]
            if len(normalized) != int(call["batch_size"]):
                raise BudgetEvidenceError(
                    f"call {call['call_id']} produced {call['batch_size']} outputs but "
                    f"received {len(normalized)} retained artifacts"
                )

            rows: list[dict[str, Any]] = []
            previous_hash = state["last_ledger_row_sha256"]
            for batch_index, (generation_id, artifact) in enumerate(
                zip(call["generation_ids"], normalized, strict=True)
            ):
                path_value = artifact.get("path")
                provenance_value = artifact.get("provenance_path")
                sanity = artifact.get("sanity")
                if not isinstance(path_value, str) or not isinstance(provenance_value, str):
                    raise BudgetEvidenceError("generated audio lacks path/provenance_path")
                if not isinstance(sanity, Mapping) or "pass" not in sanity:
                    raise BudgetEvidenceError("generated audio lacks completed sanity evidence")
                audio_path = Path(path_value).resolve(strict=True)
                provenance_path = Path(provenance_value).resolve(strict=True)
                body = {
                    "schema_version": 1,
                    "status": "PASS",
                    "generation_id": generation_id,
                    "call_id": call["call_id"],
                    "smoke": smoke,
                    "batch_item_index": batch_index,
                    "seed_id": call["seed_id"],
                    "seed": call["seed"],
                    "duration_seconds": call["duration_seconds"],
                    "batch_size": call["batch_size"],
                    "prompt": (
                        call["prompt"][batch_index]
                        if isinstance(call["prompt"], list) and len(call["prompt"]) > 1
                        else call["prompt"]
                    ),
                    "generation_parameters": call["generation_parameters"],
                    "process_id": call["process_id"],
                    "synchronized_gpu_wall_seconds_for_call": call["synchronized_gpu_wall_seconds"],
                    "actual_measurements_for_call": call["measurements"],
                    "execution_claim_sha256": state["claim_sha256"],
                    "audio_path": str(audio_path),
                    "audio_sha256": sha256_file(audio_path),
                    "provenance_path": str(provenance_path),
                    "provenance_sha256": sha256_file(provenance_path),
                    "sanity": dict(sanity),
                    "ledgered_at_utc": _utc_now(),
                    "previous_row_sha256": previous_hash,
                }
                row_hash = hashlib.sha256(_strict_json(body).encode("utf-8")).hexdigest()
                row = {**body, "row_sha256": row_hash}
                rows.append(row)
                previous_hash = row_hash

            fd = os.open(self.paths.ledger, os.O_WRONLY | os.O_APPEND)
            try:
                _write_all(
                    fd,
                    "".join(_strict_json(row) + "\n" for row in rows).encode("utf-8"),
                )
                os.fsync(fd)
            finally:
                os.close(fd)
            call["artifact_generation_ids"] = list(call["generation_ids"])
            state["ledgered_outputs"] = int(state["ledgered_outputs"]) + len(rows)
            state["last_ledger_row_sha256"] = previous_hash
            _replace_json(self.paths.state, state)
            return tuple(rows)

    def summary(self) -> dict[str, Any]:
        state = _read_object(self.paths.state)
        calls = [dict(row) for row in state["calls"]]
        smoke_measurements: dict[str, dict[str, Any]] = {}
        for smoke in EXPECTED_CALLS_BY_SMOKE:
            rows = [row for row in calls if row["smoke"] == smoke]
            measurements = [
                row["measurements"] for row in rows if isinstance(row.get("measurements"), Mapping)
            ]
            smoke_measurements[smoke] = {
                "call_count": len(rows),
                "output_count": sum(int(row["batch_size"]) for row in rows),
                "actual_backbone_forward_calls": sum(
                    int(item.get("backbone_forward_calls", 0)) for item in measurements
                ),
                "synchronized_generation_wall_seconds": sum(
                    float(item.get("wall_seconds", 0.0)) for item in measurements
                ),
                "peak_allocated_bytes": max(
                    (int(item.get("peak_allocated_bytes", 0)) for item in measurements),
                    default=0,
                ),
                "peak_reserved_bytes": max(
                    (int(item.get("peak_reserved_bytes", 0)) for item in measurements),
                    default=0,
                ),
                "call_ids": [row["call_id"] for row in rows],
            }
        return {
            "status": "PASS" if state.get("exact_plan_completed") else "IN_PROGRESS",
            "caps": dict(state["caps"]),
            "exact_plan": dict(state["exact_plan"]),
            "official_generate_calls_reserved": state["official_generate_calls_reserved"],
            "generation_slots_reserved": state["generation_slots_reserved"],
            "successful_model_calls": state["successful_model_calls"],
            "failed_model_calls": state["failed_model_calls"],
            "generated_outputs": state["generated_outputs"],
            "ledgered_outputs": state["ledgered_outputs"],
            "terminal_failure_ledger_rows": state["terminal_failure_ledger_rows"],
            "cumulative_synchronized_gpu_wall_seconds": state[
                "cumulative_synchronized_gpu_wall_seconds"
            ],
            "time_cap_reached": state["time_cap_reached"],
            "gpu_residency_upper_bound_seconds": state["gpu_residency_upper_bound_seconds"],
            "residency_cap_reached": state["residency_cap_reached"],
            "calls_by_smoke": dict(state["calls_by_smoke"]),
            "generations_by_smoke": dict(state["generations_by_smoke"]),
            "seed_calls_by_smoke": dict(state["seed_calls_by_smoke"]),
            "exact_plan_completed": state.get("exact_plan_completed", False),
            "measurement_evidence_complete": state.get("measurement_evidence_complete", False),
            "claim_path": str(self.paths.claim),
            "claim_sha256": sha256_file(self.paths.claim),
            "state_path": str(self.paths.state),
            "state_sha256": sha256_file(self.paths.state),
            "ledger_path": str(self.paths.ledger),
            "ledger_sha256": sha256_file(self.paths.ledger),
            "last_ledger_row_sha256": state["last_ledger_row_sha256"],
            "calls": calls,
            "smoke_measurements": smoke_measurements,
        }

    def immutable_snapshot(self) -> dict[str, Any]:
        """Capture exact state bytes and ledger identity for one smoke manifest."""

        with self._locked_state() as state:
            return {
                "schema_version": 1,
                "captured_at_utc": _utc_now(),
                "state": state,
                "state_path": str(self.paths.state),
                "state_sha256_at_capture": sha256_file(self.paths.state),
                "ledger_path": str(self.paths.ledger),
                "ledger_sha256_at_capture": sha256_file(self.paths.ledger),
                "claim_path": str(self.paths.claim),
                "claim_sha256": sha256_file(self.paths.claim),
            }

    def finalize(self) -> dict[str, Any]:
        with self._locked_state() as state:
            # Failed model calls and artifact-write failures still receive one
            # append-only terminal ledger row per reserved generation ID.
            missing_rows: list[dict[str, Any]] = []
            previous_hash = state["last_ledger_row_sha256"]
            for call in state["calls"]:
                already = set(call["artifact_generation_ids"]) | set(
                    call["terminal_ledger_generation_ids"]
                )
                for batch_index, generation_id in enumerate(call["generation_ids"]):
                    if generation_id in already:
                        continue
                    body = {
                        "schema_version": 1,
                        "status": (
                            "MODEL_CALL_FAILED"
                            if call["status"] == "MODEL_CALL_FAILED"
                            else "ARTIFACT_NOT_FINALIZED"
                        ),
                        "generation_id": generation_id,
                        "call_id": call["call_id"],
                        "smoke": call["smoke"],
                        "batch_item_index": batch_index,
                        "seed_id": call["seed_id"],
                        "seed": call["seed"],
                        "duration_seconds": call["duration_seconds"],
                        "batch_size": call["batch_size"],
                        "process_id": call["process_id"],
                        "actual_measurements_for_call": call["measurements"],
                        "error": call.get("error"),
                        "audio_path": None,
                        "audio_sha256": None,
                        "provenance_path": None,
                        "provenance_sha256": None,
                        "sanity": None,
                        "execution_claim_sha256": state["claim_sha256"],
                        "ledgered_at_utc": _utc_now(),
                        "previous_row_sha256": previous_hash,
                    }
                    row_hash = hashlib.sha256(_strict_json(body).encode("utf-8")).hexdigest()
                    row = {**body, "row_sha256": row_hash}
                    missing_rows.append(row)
                    previous_hash = row_hash
                    call["terminal_ledger_generation_ids"].append(generation_id)
            if missing_rows:
                fd = os.open(self.paths.ledger, os.O_WRONLY | os.O_APPEND)
                try:
                    _write_all(
                        fd,
                        "".join(_strict_json(row) + "\n" for row in missing_rows).encode("utf-8"),
                    )
                    os.fsync(fd)
                finally:
                    os.close(fd)
                state["terminal_failure_ledger_rows"] = int(
                    state["terminal_failure_ledger_rows"]
                ) + len(missing_rows)
                state["last_ledger_row_sha256"] = previous_hash

            residency = (time.monotonic_ns() - int(state["model_load_started_monotonic_ns"])) / 1e9
            state["gpu_residency_upper_bound_seconds"] = residency
            state["residency_cap_reached"] = residency >= MAX_GPU_SECONDS
            measurement_evidence_complete = bool(
                len(state["calls"]) == EXPECTED_CALLS
                and all(
                    row.get("status") == "GENERATED"
                    and isinstance(row.get("measurements"), Mapping)
                    and int(row["measurements"].get("backbone_forward_calls", 0)) > 0
                    and float(row["measurements"].get("wall_seconds", 0.0)) > 0.0
                    and int(row["measurements"].get("peak_allocated_bytes", 0)) > 0
                    and int(row["measurements"].get("peak_reserved_bytes", 0)) > 0
                    for row in state["calls"]
                )
            )
            state["measurement_evidence_complete"] = measurement_evidence_complete
            exact = bool(
                state["official_generate_calls_reserved"] == EXPECTED_CALLS
                and state["generation_slots_reserved"] == EXPECTED_GENERATIONS
                and state["successful_model_calls"] == EXPECTED_CALLS
                and state["failed_model_calls"] == 0
                and state["generated_outputs"] == EXPECTED_GENERATIONS
                and state["ledgered_outputs"] == EXPECTED_GENERATIONS
                and state["calls_by_smoke"] == dict(EXPECTED_CALLS_BY_SMOKE)
                and state["generations_by_smoke"] == dict(EXPECTED_GENERATIONS_BY_SMOKE)
                and state["seed_calls_by_smoke"]
                == {key: dict(value) for key, value in EXPECTED_SEED_CALLS.items()}
                and float(state["cumulative_synchronized_gpu_wall_seconds"]) <= MAX_GPU_SECONDS
                and residency <= MAX_GPU_SECONDS
                and measurement_evidence_complete
            )
            state["finalized_at_utc"] = _utc_now()
            state["exact_plan_completed"] = exact
            _replace_json(self.paths.state, state)
        summary = self.summary()
        return {**summary, "status": "PASS" if exact else "FAIL"}


@contextmanager
def smoke_context(smoke: str) -> Iterator[None]:
    if smoke not in EXPECTED_CALLS_BY_SMOKE:
        raise ValueError(f"unknown smoke {smoke!r}")
    previous = os.environ.get(ENV_SMOKE)
    os.environ[ENV_SMOKE] = smoke
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(ENV_SMOKE, None)
        else:
            os.environ[ENV_SMOKE] = previous


def finalize_generated_audio(
    artifacts: Sequence[Mapping[str, Any]], *, smoke: str
) -> tuple[Mapping[str, Any], ...]:
    budget = ExecutionBudget.from_environment()
    if budget is None:
        return ()
    return budget.finalize_latest_audio(artifacts, smoke=smoke)


def remaining_budget_seconds() -> float | None:
    """Conservative remaining allowance across measured and residency clocks."""

    budget = ExecutionBudget.from_environment()
    if budget is None:
        return None
    state = _read_object(budget.paths.state)
    measured_remaining = MAX_GPU_SECONDS - float(state["cumulative_synchronized_gpu_wall_seconds"])
    residency = (time.monotonic_ns() - int(state["model_load_started_monotonic_ns"])) / 1e9
    return max(0.0, min(measured_remaining, MAX_GPU_SECONDS - residency))


class BudgetedStableAudioModel:
    """Transparent official-model proxy that meters every ``generate`` call."""

    def __init__(self, wrapped: Any) -> None:
        object.__setattr__(self, "_wrapped", wrapped)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_wrapped"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_wrapped":
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_wrapped"), name, value)

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        if args:
            raise BudgetExceeded("auditable official generate calls must use keyword arguments")
        budget = ExecutionBudget.from_environment()
        if budget is None:
            raise BudgetEvidenceError("budget proxy is active without complete shared state")
        smoke = os.environ.get(ENV_SMOKE)
        if smoke is None:
            raise BudgetExceeded("official generate call lacks a smoke budget context")
        seed = kwargs.get("seed")
        seed_id = seed_id_for(seed)
        _validate_official_kwargs(seed_id, kwargs)
        reservation = budget.reserve_call(
            smoke=smoke,
            seed_id=seed_id,
            seed=seed,
            duration_seconds=kwargs.get("duration"),
            batch_size=kwargs.get("batch_size"),
            prompt=kwargs.get("prompt"),
            generation_parameters={
                key: kwargs.get(key)
                for key in (
                    "negative_prompt",
                    "steps",
                    "cfg_scale",
                    "sampler_type",
                    "duration_padding_sec",
                    "truncate_output_to_duration",
                    "chunked_decode",
                    "sample_size",
                    "disable_tqdm",
                )
            },
        )

        import torch

        device = None
        hook = None
        forward_calls = 0
        baseline_allocated = 0
        baseline_reserved = 0
        started: float | None = None
        elapsed = 0.0

        def count_forward(_module: Any, _inputs: Any) -> None:
            nonlocal forward_calls
            forward_calls += 1

        def measurements() -> dict[str, Any]:
            peak_allocated = 0
            peak_reserved = 0
            device_name = None
            if device is not None:
                try:
                    peak_allocated = int(torch.cuda.max_memory_allocated(device))
                    peak_reserved = int(torch.cuda.max_memory_reserved(device))
                    device_name = str(torch.cuda.get_device_name(device))
                except Exception:  # noqa: BLE001 - preserve terminal budget evidence
                    pass
            return {
                "backbone_forward_calls": forward_calls,
                "wall_seconds": elapsed,
                "cuda_device": None if device is None else str(device),
                "cuda_device_name": device_name,
                "baseline_allocated_bytes": baseline_allocated,
                "baseline_reserved_bytes": baseline_reserved,
                "peak_allocated_bytes": peak_allocated,
                "peak_reserved_bytes": peak_reserved,
                "incremental_peak_allocated_bytes": max(0, peak_allocated - baseline_allocated),
                "incremental_peak_reserved_bytes": max(0, peak_reserved - baseline_reserved),
                "timing_scope": "CUDA-synchronized official StableAudioModel.generate",
                "nfe_scope": "actual DiT forward-pre-hook invocations",
            }

        try:
            if not torch.cuda.is_available() or torch.cuda.device_count() != MAX_GPUS:
                raise BudgetExceeded("official generation requires exactly one CUDA device")
            device = torch.device(getattr(self, "device", "cuda:0"))
            if device.type != "cuda":
                raise BudgetExceeded(f"official generation device must be CUDA, got {device}")
            backbone = getattr(self, "dit", None)
            if backbone is None:
                backbone = getattr(getattr(self, "model", None), "model", None)
            if not callable(getattr(backbone, "register_forward_pre_hook", None)):
                raise BudgetEvidenceError(
                    "could not locate the official DiT backbone for actual NFE measurement"
                )
            hook = backbone.register_forward_pre_hook(count_forward)
            torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)
            baseline_allocated = int(torch.cuda.memory_allocated(device))
            baseline_reserved = int(torch.cuda.memory_reserved(device))
            started = time.perf_counter()
            output = object.__getattribute__(self, "_wrapped").generate(**kwargs)
            torch.cuda.synchronize(device)
        except Exception as exc:
            if device is not None:
                with suppress(Exception):
                    torch.cuda.synchronize(device)
            if started is not None:
                elapsed = float(time.perf_counter() - started)
            budget.complete_call(
                reservation,
                synchronized_gpu_wall_seconds=elapsed,
                succeeded=False,
                measurements=measurements(),
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            elapsed = float(time.perf_counter() - started)
            budget.complete_call(
                reservation,
                synchronized_gpu_wall_seconds=elapsed,
                succeeded=True,
                measurements=measurements(),
            )
            return output
        finally:
            if hook is not None:
                hook.remove()


__all__ = [
    "BudgetEvidenceError",
    "BudgetExceeded",
    "BudgetedStableAudioModel",
    "CallReservation",
    "ExecutionBudget",
    "EXPECTED_CALLS",
    "EXPECTED_GENERATIONS",
    "FROZEN_SEEDS",
    "MAX_CLIP_SECONDS",
    "MAX_GENERATIONS",
    "MAX_GPU_SECONDS",
    "MAX_GPUS",
    "finalize_generated_audio",
    "remaining_budget_seconds",
    "seed_id_for",
    "smoke_context",
]

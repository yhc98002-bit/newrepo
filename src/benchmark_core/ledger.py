"""Append-only, hash-chained JSONL ledger for benchmark generation calls."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from benchmark_core.queue import canonical_json

GENESIS_HASH = "0" * 64
REQUEST_EVENT_KIND = "REQUEST_STATE"
REQUEST_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"CLAIMED"}),
    "CLAIMED": frozenset({"CALL_STARTED", "ABORTED_BEFORE_ADAPTER"}),
    "CALL_STARTED": frozenset({"SUCCEEDED", "FAILED"}),
    "ABORTED_BEFORE_ADAPTER": frozenset(),
    "SUCCEEDED": frozenset(),
    "FAILED": frozenset(),
}
TERMINAL_REQUEST_STATES = frozenset({"ABORTED_BEFORE_ADAPTER", "SUCCEEDED", "FAILED"})


def validate_request_state_machine(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Validate request transitions and return each request's latest state."""

    latest: dict[str, str] = {}
    for row in rows:
        if row.get("event_kind") != REQUEST_EVENT_KIND:
            continue
        request_sha = row.get("request_sha256")
        state = row.get("request_state")
        if not isinstance(request_sha, str) or len(request_sha) != 64:
            raise ValueError("request-state ledger row lacks request_sha256")
        if not isinstance(state, str) or state not in REQUEST_TRANSITIONS:
            raise ValueError("request-state ledger row has invalid state")
        previous = latest.get(request_sha)
        if state not in REQUEST_TRANSITIONS[previous]:
            raise ValueError(f"invalid request transition for {request_sha}: {previous} -> {state}")
        latest[request_sha] = state
    return latest


def validate_ledger(path: Path) -> list[dict[str, Any]]:
    """Validate every row and return the decoded ledger."""

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for expected_index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("ledger row must be an object")
        claimed = row.pop("ledger_row_sha256", None)
        if row.get("ledger_index") != expected_index:
            raise ValueError("ledger indices are not contiguous")
        if row.get("previous_row_sha256") != previous:
            raise ValueError("ledger previous-row link mismatch")
        observed = hashlib.sha256(canonical_json(row).encode()).hexdigest()
        row["ledger_row_sha256"] = claimed
        if claimed != observed:
            raise ValueError("ledger row hash mismatch")
        rows.append(row)
        previous = claimed
    validate_request_state_machine(rows)
    return rows


class HashChainedLedger:
    """Single-file append helper that locks, validates, writes, and fsyncs each row."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                # Two READY-model workers may race only while creating the
                # shared empty ledger. The winning O_EXCL creation is valid.
                pass
            else:
                os.close(descriptor)
        if not self.path.is_file():
            raise RuntimeError(f"shared ledger is not a regular file: {self.path}")
        parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)

    def append(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            rows = validate_ledger(self.path)
            try:
                return self._append_locked(handle, rows, payload)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _append_locked(
        handle: Any, rows: list[dict[str, Any]], payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        row = dict(payload)
        forbidden = {"ledger_index", "previous_row_sha256", "ledger_row_sha256"}
        if forbidden.intersection(row):
            raise ValueError("payload contains ledger-reserved fields")
        row["ledger_index"] = len(rows) + 1
        row["previous_row_sha256"] = rows[-1]["ledger_row_sha256"] if rows else GENESIS_HASH
        row["ledger_row_sha256"] = hashlib.sha256(canonical_json(row).encode()).hexdigest()
        handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        return row

    def transition(
        self,
        request_sha256: str,
        state: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically validate and append one no-retry request transition."""

        if len(request_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in request_sha256
        ):
            raise ValueError("request_sha256 must be lowercase SHA-256")
        if state not in REQUEST_TRANSITIONS:
            raise ValueError(f"unsupported request state: {state}")
        supplied = dict(payload or {})
        reserved = {"event_kind", "request_sha256", "request_state"}
        if reserved.intersection(supplied):
            raise ValueError("payload contains request-state reserved fields")
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                rows = validate_ledger(self.path)
                latest = validate_request_state_machine(rows)
                previous = latest.get(request_sha256)
                if state not in REQUEST_TRANSITIONS[previous]:
                    raise ValueError(
                        f"invalid request transition for {request_sha256}: {previous} -> {state}"
                    )
                supplied.update(
                    {
                        "event_kind": REQUEST_EVENT_KIND,
                        "request_sha256": request_sha256,
                        "request_state": state,
                    }
                )
                return self._append_locked(handle, rows, supplied)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def request_states(self) -> dict[str, str]:
        """Return validated latest request states."""

        return validate_request_state_machine(validate_ledger(self.path))

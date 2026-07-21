"""No-clobber scoring artifacts with immutable ledger and heartbeat events."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scoring.common import canonical_json, safe_child, sha256_json

GENESIS = "0" * 64


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_bytes_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    _fsync_dir(path.parent)


def write_json_exclusive(path: Path, value: Any) -> None:
    write_bytes_exclusive(path, (canonical_json(value) + "\n").encode("utf-8"))


def write_jsonl_exclusive(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    payload = "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")
    write_bytes_exclusive(path, payload)


class ImmutableEventLog:
    """An append-only chain represented by one read-only file per event."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".append.lock"
        self.lock_path.touch(exist_ok=True)

    def append(self, event_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not event_kind:
            raise ValueError("event_kind must be nonempty")
        with self.lock_path.open("r+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            events = sorted(self.root.glob("[0-9]*-*.json"))
            sequence = len(events) + 1
            previous = GENESIS
            if events:
                previous = events[-1].stem.rsplit("-", 1)[-1]
            row = {
                "event_kind": event_kind,
                "payload": payload,
                "previous_event_sha256": previous,
                "sequence": sequence,
            }
            digest = sha256_json(row)
            row["event_sha256"] = digest
            path = self.root / f"{sequence:06d}-{digest}.json"
            write_json_exclusive(path, row)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return row


class ImmutableRun:
    """Scoped no-clobber writer for one canonical scoring run."""

    def __init__(self, root: Path, *, create: bool) -> None:
        self.root = root.resolve()
        if create:
            self.root.mkdir(parents=True, exist_ok=False)
            _fsync_dir(self.root.parent)
        elif not self.root.is_dir():
            raise FileNotFoundError(self.root)
        self.ledger = ImmutableEventLog(self.root / "ledger" / "events")
        self.heartbeats = ImmutableEventLog(self.root / "heartbeats")

    def path(self, relative: str) -> Path:
        return safe_child(self.root, relative, "run artifact path")

    def write_json(self, relative: str, value: Any) -> Path:
        path = self.path(relative)
        write_json_exclusive(path, value)
        return path

    def write_jsonl(self, relative: str, rows: Iterable[dict[str, Any]]) -> Path:
        path = self.path(relative)
        write_jsonl_exclusive(path, rows)
        return path

    def heartbeat(self, state: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.heartbeats.append("SCORING_HEARTBEAT", {"state": state, **payload})

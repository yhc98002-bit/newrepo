"""Read-only heartbeat supervision; it never signals or kills a worker."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from benchmark_core.heartbeat import heartbeat_is_stale, validate_heartbeat


@dataclass(frozen=True)
class SupervisorDecision:
    assignment_allowed: bool
    status: str
    reason: str


def inspect_worker(heartbeat_path: Path, *, stale_after_seconds: float) -> SupervisorDecision:
    """Decide whether assignment may continue without changing external state."""

    if not heartbeat_path.is_file():
        return SupervisorDecision(False, "STOP_ASSIGNING", "heartbeat is absent")
    try:
        heartbeat = validate_heartbeat(json.loads(heartbeat_path.read_text(encoding="utf-8")))
        stale = heartbeat_is_stale(heartbeat_path, stale_after_seconds)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return SupervisorDecision(False, "STOP_ASSIGNING", f"heartbeat is invalid: {exc}")
    if stale:
        return SupervisorDecision(False, "STOP_ASSIGNING", "heartbeat is stale")
    if heartbeat["state"] in {
        "PLACEMENT_HEADROOM_BLOCKED",
        "HARD_CAP_REACHED",
        "FAILED_STOPPED",
        "COMPLETE",
    }:
        return SupervisorDecision(
            False,
            "STOP_ASSIGNING",
            f"worker is terminal: {heartbeat['state']}",
        )
    return SupervisorDecision(True, "ASSIGNMENT_ALLOWED", "heartbeat is current and active")

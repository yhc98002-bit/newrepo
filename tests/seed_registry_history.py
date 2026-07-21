from __future__ import annotations

import hashlib
from pathlib import Path

FROZEN_B2_SEED_REGISTRY_SHA256 = (
    "d9b175296a97e8acca72d124a950c4e2fcd08c2d4287587c5e70c149f24deb97"
)
AUTHORIZED_S0010_SUFFIX = (
    b"| S-0010 | 73193010 | ACE-Step v1 state preflight "
    b"reference/export/resume equivalence, non-benchmark | none |\n"
)


def exact_line_bounded_prefix(path: Path, expected_sha256: str) -> bytes:
    """Recover one exact historical prefix without accepting edited old bytes."""

    payload = path.read_bytes()
    digest = hashlib.sha256()
    offset = 0
    matches: list[int] = []
    for line in payload.splitlines(keepends=True):
        digest.update(line)
        offset += len(line)
        if digest.hexdigest() == expected_sha256:
            matches.append(offset)
    if len(matches) != 1:
        raise AssertionError(
            "expected exactly one complete-line historical prefix with SHA-256 "
            f"{expected_sha256}, observed {len(matches)}"
        )
    return payload[: matches[0]]


def frozen_b2_seed_registry_prefix(path: Path) -> bytes:
    return exact_line_bounded_prefix(path, FROZEN_B2_SEED_REGISTRY_SHA256)

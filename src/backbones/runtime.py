"""Runtime instrumentation shared by real backbone adapters."""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backbones.contracts import BackboneConfigurationError

_ACE_GENERATED_CACHE_RE = re.compile(
    r"(?:.*/)?__pycache__/[A-Za-z0-9_.-]+\.cpython-310(?:\.opt-[12])?\.pyc$"
)


def verify_clean_git_revision(
    source_dir: str | Path,
    expected_revision: str,
    *,
    expected_tree: str | None = None,
) -> dict[str, Any]:
    """Verify an exact source checkout, including ignored/untracked filesystem entries.

    The sole narrow exception is CPython 3.10 bytecode beneath ``__pycache__``.
    B2 launches with an absent alternate ``sys.pycache_prefix`` and ``-B``, so
    these retained generated caches are neither read nor written. Any other
    untracked or ignored file, any untracked symlink, or any tracked change is
    a hard failure.
    """

    root = Path(source_dir).resolve()
    if not root.is_dir():
        raise BackboneConfigurationError(f"upstream source directory is absent: {root}")
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        tree = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        tracked_output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackboneConfigurationError(f"cannot verify upstream source checkout: {exc}") from exc
    if revision != expected_revision:
        raise BackboneConfigurationError(
            f"upstream source revision mismatch: {revision} != {expected_revision}"
        )
    if expected_tree is not None and tree != expected_tree:
        raise BackboneConfigurationError(
            f"upstream source tree mismatch: {tree} != {expected_tree}"
        )
    if dirty:
        raise BackboneConfigurationError(
            "upstream source checkout has tracked or ordinary untracked modifications"
        )

    tracked = {item.decode("utf-8") for item in tracked_output.split(b"\0") if item}
    allowed_generated_caches: list[str] = []
    forbidden_extra_entries: list[str] = []
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        if candidate.is_dir() and not candidate.is_symlink():
            continue
        if relative in tracked:
            continue
        if (
            candidate.is_file()
            and not candidate.is_symlink()
            and _ACE_GENERATED_CACHE_RE.fullmatch(relative)
        ):
            allowed_generated_caches.append(relative)
        else:
            forbidden_extra_entries.append(relative)
    if forbidden_extra_entries:
        raise BackboneConfigurationError(
            "upstream source checkout contains ignored/untracked non-cache entries: "
            f"{forbidden_extra_entries}"
        )
    return {
        "source_dir": str(root),
        "revision": revision,
        "tree": tree,
        "tracked_worktree": "clean_including_untracked",
        "generated_cache_exception": (
            "only __pycache__/*.cpython-310[.opt-N].pyc; execution uses -B and an "
            "absent alternate sys.pycache_prefix"
        ),
        "allowed_generated_cache_files": allowed_generated_caches,
        "allowed_generated_cache_file_count": len(allowed_generated_caches),
        "forbidden_extra_entries": [],
        "filesystem_scan_complete": True,
        "python_cache_reads_from_source_tree": False,
        "process_python_version": os.sys.version.split()[0],
    }


class CudaTelemetry:
    """CUDA-synchronized call timing and peak-memory measurement."""

    def __init__(self, device: str = "cuda") -> None:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch is required for a GPU backbone call") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable; real backbone generation is GPU-only")
        self.torch = torch
        self.device = torch.device(device)
        if self.device.type != "cuda":
            raise RuntimeError(f"generation telemetry requires CUDA, got {self.device}")

    def reset(self) -> None:
        self.torch.cuda.synchronize(self.device)
        self.torch.cuda.reset_peak_memory_stats(self.device)

    def synchronize(self) -> None:
        self.torch.cuda.synchronize(self.device)

    def peak_bytes(self) -> tuple[int, int]:
        return (
            int(self.torch.cuda.max_memory_allocated(self.device)),
            int(self.torch.cuda.max_memory_reserved(self.device)),
        )

    @contextmanager
    def measured(self) -> Iterator[dict[str, Any]]:
        self.reset()
        started = time.perf_counter()
        result: dict[str, Any] = {}
        try:
            yield result
        finally:
            self.synchronize()
            result["wall_seconds"] = time.perf_counter() - started
            allocated, reserved = self.peak_bytes()
            result["peak_allocated_bytes"] = allocated
            result["peak_reserved_bytes"] = reserved


@contextmanager
def count_method_calls(owner: Any, method_name: str) -> Iterator[dict[str, int]]:
    """Count calls to one instance method and restore it on every exit path."""

    if not hasattr(owner, method_name):
        raise RuntimeError(f"cannot measure NFE: {type(owner).__name__}.{method_name} is absent")
    original = getattr(owner, method_name)
    counter = {"calls": 0}

    def counted(*args: Any, **kwargs: Any) -> Any:
        counter["calls"] += 1
        return original(*args, **kwargs)

    setattr(owner, method_name, counted)
    try:
        yield counter
    finally:
        setattr(owner, method_name, original)

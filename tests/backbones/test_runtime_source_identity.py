from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backbones.contracts import BackboneConfigurationError
from backbones.runtime import verify_clean_git_revision


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_checkout(root: Path) -> tuple[str, str]:
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "B2 test")
    (root / ".gitignore").write_text("__pycache__/\nignored.py\n", encoding="utf-8")
    (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "module.py")
    _git(root, "commit", "-m", "fixture")
    return _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")


def test_source_identity_scans_ignored_files_and_allows_only_inert_pycache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    revision, tree = _source_checkout(source)
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-310.pyc").write_bytes(b"retained generated cache")
    evidence = verify_clean_git_revision(source, revision, expected_tree=tree)
    assert evidence["tracked_worktree"] == "clean_including_untracked"
    assert evidence["allowed_generated_cache_files"] == ["__pycache__/module.cpython-310.pyc"]
    assert evidence["python_cache_reads_from_source_tree"] is False

    (source / "ignored.py").write_text("VALUE = 999\n", encoding="utf-8")
    with pytest.raises(BackboneConfigurationError, match="ignored/untracked non-cache"):
        verify_clean_git_revision(source, revision, expected_tree=tree)


def test_source_identity_rejects_ordinary_untracked_and_wrong_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    revision, tree = _source_checkout(source)
    with pytest.raises(BackboneConfigurationError, match="tree mismatch"):
        verify_clean_git_revision(source, revision, expected_tree="0" * 40)
    assert tree != "0" * 40

    (source / "ordinary.txt").write_text("untracked\n", encoding="utf-8")
    with pytest.raises(BackboneConfigurationError, match="ordinary untracked"):
        verify_clean_git_revision(source, revision, expected_tree=tree)

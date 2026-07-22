from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "finalize_sao_acquisition_recovery_v2_attempt2.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "sao_acquisition_recovery_attempt2_cli", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "variable", ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACEHUB_API_TOKEN"]
)
def test_attempt2_cli_rejects_provider_token_before_spawning_git(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    module = _load_cli_module()
    spawned = False

    def forbidden_subprocess(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("git subprocess must not start with a provider token")

    monkeypatch.setattr(module.subprocess, "check_output", forbidden_subprocess)
    with pytest.raises(RuntimeError, match="provider tokens"):
        module._git_state({"PATH": "/usr/bin", variable: "sentinel-never-print"})
    assert spawned is False

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import stage1.terminal as terminal_module
from scoring.common import load_json
from stage1.gates import AXES, BACKBONES
from stage1.terminal import Stage1TerminalError, validate_stage1_terminal
from tests.stage1.terminal_support import (
    build_terminal,
    queue_binding,
    rewrite_immutable_json,
    write_jsonl,
)


def _queues(tmp_path: Path) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for backbone in BACKBONES:
        rows: list[dict[str, Any]] = []
        for axis in AXES:
            for prompt_index in range(12):
                prompt = f"{axis}-prompt-{prompt_index:02d}"
                for root in range(4):
                    for checkpoint in (0.25, 0.5, 0.75):
                        identity = f"{backbone}|{axis}|{prompt}|{root}|{checkpoint}"
                        rows.append(
                            {
                                "axis": axis,
                                "eligibility_unit": {
                                    "checkpoint": checkpoint,
                                    "prompt": prompt,
                                    "root": root,
                                },
                                "lane_request_sha256": hashlib.sha256(
                                    identity.encode()
                                ).hexdigest(),
                            }
                        )
        path = tmp_path / "queues" / f"{backbone}.jsonl"
        write_jsonl(path, rows)
        bindings.append(queue_binding(path, backbone))
    return bindings


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    return build_terminal(
        tmp_path,
        queue_bindings=_queues(tmp_path),
        stopped_cells={
            ("ACE-Step v1", "tempo"),
            ("stable-audio-3-medium-base", "integrity"),
        },
    )


def test_deep_terminal_revalidates_policy_provenance_rows_and_cancellations(
    tmp_path: Path,
) -> None:
    result, summary, config = _fixture(tmp_path)
    terminal = validate_stage1_terminal(
        result,
        summary,
        expected_config_path=config,
    )
    assert terminal.config_sha256 == load_json(result)["provenance"]["config_sha256"]
    assert len(terminal.rows) == 6
    assert len(terminal.cancellations) == 288


def test_known_home_alias_is_exact_and_does_not_accept_arbitrary_copies() -> None:
    canonical = Path(
        "/XYFS01/HOME/paratera_xy/pxy1289/project/configs/stage1.json"
    )
    alias = Path("/HOME/paratera_xy/pxy1289/project/configs/stage1.json")
    assert terminal_module._known_home_alias(canonical, alias)
    assert terminal_module._known_home_alias(alias, canonical)
    assert not terminal_module._known_home_alias(canonical, canonical)
    assert not terminal_module._known_home_alias(canonical, Path("/tmp/stage1.json"))
    assert not terminal_module._known_home_alias(
        canonical,
        Path("/HOME/paratera_xy/pxy1289/other/configs/stage1.json"),
    )


def test_home_alias_requires_both_files_to_match_the_bound_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left = Path("/XYFS01/HOME/paratera_xy/pxy1289/project/config.json")
    right = Path("/HOME/paratera_xy/pxy1289/project/config.json")
    expected = "a" * 64
    monkeypatch.setattr(Path, "is_file", lambda self: self in {left, right})
    observed = {left: expected, right: expected}
    monkeypatch.setattr(terminal_module, "sha256_file", observed.__getitem__)
    assert terminal_module._same_bound_path_or_home_alias(left, right, expected)
    observed[right] = "b" * 64
    assert not terminal_module._same_bound_path_or_home_alias(left, right, expected)


def test_terminal_rejects_same_byte_config_at_an_unregistered_path(
    tmp_path: Path,
) -> None:
    result, summary, config = _fixture(tmp_path)
    copied_config = tmp_path / "unregistered-copy" / config.name
    copied_config.parent.mkdir()
    copied_config.write_bytes(config.read_bytes())
    with pytest.raises(Stage1TerminalError, match="different gate configuration"):
        validate_stage1_terminal(
            result,
            summary,
            expected_config_path=copied_config,
        )


def _config_sha(value: dict[str, Any]) -> None:
    value["provenance"]["config_sha256"] = "0" * 64


def _minimum(value: dict[str, Any]) -> None:
    value["rows"][0]["baseline_failure_rate"]["minimum"] = 0.125


def _maximum(value: dict[str, Any]) -> None:
    value["rows"][0]["baseline_failure_rate"]["maximum"] = 0.601


def _point(value: dict[str, Any]) -> None:
    row = next(row for row in value["rows"] if row["verdict"] == "OUTCOME_SCREEN_PASS")
    row["baseline_failure_rate"]["point"] = 0.0


def _verdict(value: dict[str, Any]) -> None:
    value["rows"][0]["verdict"] = (
        "OUTCOME_SCREEN_PASS"
        if value["rows"][0]["verdict"] == "STOP_AXIS_STAGE1"
        else "STOP_AXIS_STAGE1"
    )


def _point_and_verdict(value: dict[str, Any]) -> None:
    row = next(row for row in value["rows"] if row["verdict"] == "OUTCOME_SCREEN_PASS")
    row["baseline_failure_rate"]["point"] = 0.0
    row["verdict"] = "STOP_AXIS_STAGE1"


def _metric(value: dict[str, Any]) -> None:
    value["rows"][0]["primary_metric"] = "fabricated_metric"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (_config_sha, "config SHA-256 binding drifted"),
        (_minimum, "minimum differs from the frozen policy"),
        (_maximum, "maximum differs from the frozen policy"),
        (_point, "verdict was not recomputed"),
        (_verdict, "verdict was not recomputed"),
        (_point_and_verdict, "differ from recomputation over bound outcomes"),
        (_metric, "metric contract drifted"),
    ],
    ids=(
        "config-sha",
        "minimum",
        "maximum",
        "point",
        "verdict",
        "point-and-verdict",
        "metric",
    ),
)
def test_terminal_rejects_mutated_six_label_evidence(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    result, summary, config = _fixture(tmp_path)
    value = load_json(result)
    mutation(value)
    rewrite_immutable_json(result, value)
    with pytest.raises(Stage1TerminalError, match=match):
        validate_stage1_terminal(
            result,
            summary,
            expected_config_path=config,
        )

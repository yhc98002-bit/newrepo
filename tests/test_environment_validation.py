from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from sa3_smoke.environment_validation import (
    EXPECTED_DIRECT_DISTRIBUTIONS,
    EXPECTED_EDITABLE_NAME,
    EXPECTED_EDITABLE_VERSION,
    EXPECTED_ENVIRONMENT_PATH,
    EXPECTED_FILE_SHA256,
    EXPECTED_INSTALLED_LICENSE_SHA256,
    _canonical_name,
    validate_live_environment,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _copy_committed_environment_fixture(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    for relative in EXPECTED_FILE_SHA256:
        source = REPOSITORY_ROOT / relative
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (repository / "src" / "sa3_smoke").mkdir(parents=True)
    (repository / "src" / "sa3_smoke" / "__init__.py").write_text(
        '"""fixture"""\n', encoding="utf-8"
    )
    return repository


def _probe(repository: Path) -> dict[str, Any]:
    prefix = EXPECTED_ENVIRONMENT_PATH.resolve()
    site_packages = prefix / "lib" / "python3.10" / "site-packages"
    return {
        "python_version": "3.10.12",
        "sys_version": "3.10.12 (fixture)",
        "sys_version_info": [3, 10, 12],
        "sys_prefix": str(prefix),
        "sys_executable": str(prefix / "bin" / "python"),
        "torch_cuda_version": "12.6",
        "modules": {
            "sa3_smoke": {
                "file": str(repository / "src" / "sa3_smoke" / "__init__.py"),
                "version": "0.1.0",
            },
            "torch": {
                "file": str(site_packages / "torch" / "__init__.py"),
                "version": "2.7.1+cu126",
            },
            "torchaudio": {
                "file": str(site_packages / "torchaudio" / "__init__.py"),
                "version": "2.7.1+cu126",
            },
            "flash_attn": {
                "file": str(site_packages / "flash_attn" / "__init__.py"),
                "version": "2.6.3",
            },
            "stable_audio_3": {
                "file": str(site_packages / "stable_audio_3" / "__init__.py"),
                "version": None,
            },
            "stable_audio_tools": {
                "file": str(site_packages / "stable_audio_tools" / "__init__.py"),
                "version": None,
            },
        },
    }


def _distributions(repository: Path) -> list[dict[str, Any]]:
    del repository
    prefix = EXPECTED_ENVIRONMENT_PATH.resolve()
    records: list[dict[str, Any]] = []
    for line in (
        (REPOSITORY_ROOT / "environment" / "package-freeze.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        if line.startswith("-e "):
            records.append(
                {
                    "name": EXPECTED_EDITABLE_NAME,
                    "version": EXPECTED_EDITABLE_VERSION,
                    "location": str(prefix / "lib" / "python3.10" / "site-packages"),
                    "direct_url": {"url": line[3:], "dir_info": {"editable": True}},
                    "direct_url_error": None,
                    "license_files": [],
                }
            )
            continue
        if " @ " in line:
            name, url = line.split(" @ ", maxsplit=1)
            canonical = _canonical_name(name)
            version = EXPECTED_DIRECT_DISTRIBUTIONS[canonical]["version"]
            direct_url: dict[str, Any] | None = {"url": url, "archive_info": {}}
        else:
            name, version = line.split("==", maxsplit=1)
            canonical = _canonical_name(name)
            direct_url = None
        license_files = []
        if canonical in EXPECTED_INSTALLED_LICENSE_SHA256:
            license_files.append(
                {
                    "path": str(prefix / "licenses" / canonical / "LICENSE"),
                    "relative_path": f"{canonical}.dist-info/LICENSE",
                    "sha256": EXPECTED_INSTALLED_LICENSE_SHA256[canonical],
                }
            )
        records.append(
            {
                "name": name,
                "version": version,
                "location": str(prefix / "lib" / "python3.10" / "site-packages"),
                "direct_url": direct_url,
                "direct_url_error": None,
                "license_files": license_files,
            }
        )
    return records


@pytest.fixture
def valid_inputs(tmp_path: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    repository = _copy_committed_environment_fixture(tmp_path)
    return repository, _probe(repository), _distributions(repository)


def _validate(
    repository: Path, probe: dict[str, Any], distributions: list[dict[str, Any]], **kwargs: Any
) -> dict[str, Any]:
    return validate_live_environment(
        repository,
        repository / "environment" / "runtime.json",
        repository / "environment" / "package-freeze.txt",
        probe=probe,
        distributions=distributions,
        **kwargs,
    )


def test_valid_environment_returns_strict_json(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
) -> None:
    repository, probe, distributions = valid_inputs

    result = _validate(repository, probe, distributions)

    assert result["passed"] is True
    assert result["failures"] == []
    assert set(result) == {"passed", "failures", "evidence"}
    assert result["evidence"]["distributions"]["observed_distribution_count"] == 89
    assert result["evidence"]["package_freeze"]["expected_counts"] == {
        "version": 85,
        "direct": 3,
        "editable": 1,
        "total": 89,
    }
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("mutation", "failure_fragment"),
    [
        (lambda probe: probe.update(python_version="3.10.13"), "runtime python_version"),
        (lambda probe: probe.update(sys_version_info=[3, 10, 13]), "runtime sys.version_info"),
        (lambda probe: probe.update(sys_prefix="/tmp/wrong-env"), "runtime sys.prefix"),
        (
            lambda probe: probe["modules"]["torch"].update(version="2.7.2+cu126"),
            "imported torch.__version__",
        ),
        (lambda probe: probe.update(torch_cuda_version="12.8"), "torch_cuda_version"),
        (
            lambda probe: probe["modules"]["sa3_smoke"].update(file="/tmp/foreign.py"),
            "imported sa3_smoke location",
        ),
        (
            lambda probe: probe["modules"]["flash_attn"].update(file="/tmp/flash_attn.py"),
            "imported flash_attn location",
        ),
    ],
)
def test_runtime_probe_drift_fails_closed(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
    mutation: Any,
    failure_fragment: str,
) -> None:
    repository, probe, distributions = valid_inputs
    mutation(probe)

    result = _validate(repository, probe, distributions)

    assert result["passed"] is False
    assert any(failure_fragment in failure for failure in result["failures"])


@pytest.mark.parametrize(
    ("mutation", "failure_fragment"),
    [
        (
            lambda records: records.pop(
                next(i for i, row in enumerate(records) if row["name"] == "torch")
            ),
            "missing installed distributions",
        ),
        (
            lambda records: next(row for row in records if row["name"] == "torch").update(
                version="2.7.2"
            ),
            "distribution drift for torch: version",
        ),
        (
            lambda records: next(row for row in records if row["name"] == "stable-audio-3")[
                "direct_url"
            ].update(url="https://example.invalid/wrong.tar.gz"),
            "distribution drift for stable-audio-3: source URL",
        ),
        (
            lambda records: records.append(
                {
                    "name": "installer-surprise",
                    "version": "1.0",
                    "location": str(EXPECTED_ENVIRONMENT_PATH.resolve()),
                    "direct_url": None,
                    "license_files": [],
                }
            ),
            "unapproved installer extras",
        ),
        (
            lambda records: next(row for row in records if row["name"] == "flash-attn").update(
                location="/tmp/foreign-site-packages"
            ),
            "distribution metadata locations outside environment prefix",
        ),
        (
            lambda records: next(row for row in records if row["name"] == "stable-audio-tools")[
                "license_files"
            ][0].update(sha256="0" * 64),
            "installed license hash mismatch for stable-audio-tools",
        ),
    ],
)
def test_distribution_drift_fails_closed(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
    mutation: Any,
    failure_fragment: str,
) -> None:
    repository, probe, distributions = valid_inputs
    mutation(distributions)

    result = _validate(repository, probe, distributions)

    assert result["passed"] is False
    assert any(failure_fragment in failure for failure in result["failures"])


def test_extra_distribution_requires_a_nonempty_explicit_justification(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
) -> None:
    repository, probe, distributions = valid_inputs
    distributions.append(
        {
            "name": "installer-helper",
            "version": "1.2.3",
            "location": str(EXPECTED_ENVIRONMENT_PATH.resolve()),
            "direct_url": None,
            "license_files": [],
        }
    )

    empty = _validate(
        repository,
        probe,
        distributions,
        allowed_installer_extras={"installer-helper": ""},
    )
    justified = _validate(
        repository,
        probe,
        distributions,
        allowed_installer_extras={"installer_helper": "bootstrap tool installed by operator"},
    )

    assert empty["passed"] is False
    assert any("justification" in failure for failure in empty["failures"])
    assert justified["passed"] is True
    assert justified["evidence"]["distributions"]["approved_installer_extras"] == [
        {
            "name": "installer-helper",
            "justification": "bootstrap tool installed by operator",
        }
    ]


def test_committed_file_hash_drift_fails_before_accepting_live_metadata(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
) -> None:
    repository, probe, distributions = valid_inputs
    lock_path = repository / "uv.lock"
    lock_path.write_bytes(lock_path.read_bytes() + b"# drift\n")

    result = _validate(repository, probe, distributions)

    assert result["passed"] is False
    assert any("committed file hash drift for uv.lock" in item for item in result["failures"])


def test_probe_and_metadata_exceptions_are_terminal_json_failures(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
) -> None:
    repository, _, _ = valid_inputs

    def broken_probe() -> dict[str, Any]:
        raise ImportError("fixture import failure")

    def broken_metadata() -> list[dict[str, Any]]:
        raise RuntimeError("fixture metadata failure")

    result = validate_live_environment(
        repository,
        probe=broken_probe,
        distributions=broken_metadata,
    )

    assert result["passed"] is False
    assert any("runtime probe failed: ImportError" in item for item in result["failures"])
    assert any("distribution probe failed: RuntimeError" in item for item in result["failures"])
    json.dumps(result, allow_nan=False)


def test_input_objects_are_not_mutated(
    valid_inputs: tuple[Path, dict[str, Any], list[dict[str, Any]]],
) -> None:
    repository, probe, distributions = valid_inputs
    original_probe = copy.deepcopy(probe)
    original_distributions = copy.deepcopy(distributions)

    _validate(repository, probe, distributions)

    assert probe == original_probe
    assert distributions == original_distributions

"""Fail-closed validation of the frozen SA3 runtime environment.

The validator deliberately reads no installer state and performs no network or
filesystem writes.  Runtime imports and ``importlib.metadata`` are the sources
of live evidence; both boundaries are injectable so drift handling can be unit
tested without mutating the declared environment.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import platform
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

EXPECTED_PYTHON = "3.10.12"
EXPECTED_ENVIRONMENT_PATH = Path("/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env")
EXPECTED_TORCH = "2.7.1+cu126"
EXPECTED_TORCHAUDIO = "2.7.1+cu126"
EXPECTED_TORCH_CUDA = "12.6"
EXPECTED_FLASH_ATTN = "2.6.3+cu126torch2.7"

EXPECTED_FILE_SHA256 = {
    "environment/package-freeze.txt": (
        "da6aae61a6189ee8fc3842fa76652359ff802c6252ce191a199bad5953f98eab"
    ),
    "environment/runtime.json": (
        "b0e3c4d2dcb9023d862f80518a0bbb1a32f9541ab7c430e0ba7be8fd41fbec70"
    ),
    "environment/licenses.json": (
        "10f99624b8438c1dbc385ca2cec9bebac73ecb96cfe1098af32f4b9be8bd3294"
    ),
    "pyproject.toml": "70ba55cccb73e7cb763faa20bcd94d6c46b0f447cbb7863aa63fdf563513aeb8",
    "uv.lock": "c61a7fa1375d6766cceed983b56051b5b3ea7f3dba3769a5ffde1561f05f2b8c",
    "THIRD_PARTY_LICENSES.md": ("57f0eb61f069678516ff6af513a1b80cdae3c39b99e4a5250b1f4cdb521c39c4"),
}

EXPECTED_DIRECT_DISTRIBUTIONS = {
    "flash-attn": {
        "version": EXPECTED_FLASH_ATTN,
        "url": (
            "https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/"
            "download/v0.7.16/flash_attn-2.6.3%2Bcu126torch2.7-cp310-cp310-"
            "linux_x86_64.whl"
        ),
    },
    "stable-audio-3": {
        "version": "0.1.0",
        "url": (
            "https://github.com/Stability-AI/stable-audio-3/archive/"
            "0385302ea26522f00c80392c4b708df5ebf1adf5.tar.gz"
        ),
    },
    "stable-audio-tools": {
        "version": "0.0.20",
        "url": (
            "https://github.com/Stability-AI/stable-audio-tools/archive/"
            "3241adba4fc2a85cf5b29d9eb68d42f40a28e820.tar.gz"
        ),
    },
}
EXPECTED_EDITABLE_NAME = "sa3-foundation-smoke"
EXPECTED_EDITABLE_VERSION = "0.1.0"
EXPECTED_FREEZE_COUNTS = {"version": 85, "direct": 3, "editable": 1, "total": 89}
EXPECTED_INSTALLED_LICENSE_SHA256 = {
    "flash-attn": "8c9ccb96c065e706135b6cbad279b721da6156e51f3a5f27c6b3329af9416d73",
    "stable-audio-3": "16bd922f0deee6f11a76f5582258fdc3abdf67c6b8719dbcafbc34dee31979a6",
    "stable-audio-tools": ("a1fac33b7bcd791b74fb33aeb439f825e7277e239fc119fb7d2ab6f084a0c101"),
}

_DIRECT_RE = re.compile(r"^([^\s]+)\s+@\s+(\S+)$")
_VERSION_RE = re.compile(r"^([^=\s]+)==([^\s]+)$")
_CANONICALIZE_RE = re.compile(r"[-_.]+")
_REQUIRED_PREFIX_MODULES = (
    "torch",
    "torchaudio",
    "flash_attn",
    "stable_audio_3",
    "stable_audio_tools",
)


def _canonical_name(name: str) -> str:
    return _CANONICALIZE_RE.sub("-", name).lower()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_within(path: str | Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _module_location(module: Any) -> str | None:
    file_name = getattr(module, "__file__", None)
    if isinstance(file_name, str) and file_name:
        return str(Path(file_name).resolve())
    module_path = getattr(module, "__path__", None)
    if module_path:
        first = next(iter(module_path), None)
        if first:
            return str(Path(first).resolve())
    return None


def collect_runtime_probe() -> dict[str, Any]:
    """Import the required modules and return JSON-serializable live evidence."""

    modules = {
        name: importlib.import_module(name) for name in ("sa3_smoke", *_REQUIRED_PREFIX_MODULES)
    }
    torch = modules["torch"]
    return {
        "python_version": platform.python_version(),
        "sys_version": sys.version,
        "sys_version_info": list(sys.version_info[:3]),
        "sys_prefix": str(Path(sys.prefix).resolve()),
        "sys_executable": str(Path(sys.executable).resolve()),
        "torch_cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
        "modules": {
            name: {
                "file": _module_location(module),
                "version": getattr(module, "__version__", None),
            }
            for name, module in modules.items()
        },
    }


def _license_files(distribution: importlib.metadata.Distribution) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for relative in distribution.files or ():
        if Path(str(relative)).name.lower() not in {"license", "license.md", "license.txt"}:
            continue
        absolute = Path(distribution.locate_file(relative))
        if not absolute.is_file():
            continue
        result.append(
            {
                "path": str(absolute.resolve()),
                "relative_path": str(relative),
                "sha256": _sha256_file(absolute),
            }
        )
    return result


def collect_distributions() -> list[dict[str, Any]]:
    """Collect installed distribution identity, source, location, and licenses."""

    records: list[dict[str, Any]] = []
    for distribution in importlib.metadata.distributions():
        direct_text = distribution.read_text("direct_url.json")
        direct_url: Any = None
        direct_url_error: str | None = None
        if direct_text is not None:
            try:
                direct_url = json.loads(direct_text)
            except json.JSONDecodeError as exc:
                direct_url_error = str(exc)
        records.append(
            {
                "name": distribution.metadata.get("Name"),
                "version": distribution.version,
                "location": str(Path(distribution.locate_file("")).resolve()),
                "direct_url": direct_url,
                "direct_url_error": direct_url_error,
                "license_files": _license_files(distribution),
            }
        )
    return records


def _parse_freeze(text: str, failures: list[str]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    editable_rows: list[str] = []
    counts = {"version": 0, "direct": 0, "editable": 0, "total": 0}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            failures.append(f"package freeze line {line_number} is blank")
            continue
        counts["total"] += 1
        if line.startswith("-e "):
            counts["editable"] += 1
            editable_rows.append(line[3:])
            continue
        direct_match = _DIRECT_RE.fullmatch(line)
        version_match = _VERSION_RE.fullmatch(line)
        if direct_match:
            name, url = direct_match.groups()
            kind = "direct"
            value = url
        elif version_match:
            name, value = version_match.groups()
            kind = "version"
        else:
            failures.append(f"unparseable package freeze line {line_number}: {line!r}")
            continue
        canonical = _canonical_name(name)
        if name != canonical:
            failures.append(f"package freeze name is not canonical on line {line_number}: {name!r}")
        if canonical in expected:
            failures.append(f"duplicate package freeze name: {canonical}")
            continue
        counts[kind] += 1
        expected[canonical] = {"kind": kind, "value": value, "row": line}

    if len(editable_rows) == 1:
        if EXPECTED_EDITABLE_NAME in expected:
            failures.append(f"duplicate package freeze name: {EXPECTED_EDITABLE_NAME}")
        expected[EXPECTED_EDITABLE_NAME] = {
            "kind": "editable",
            "value": editable_rows[0],
            "row": f"-e {editable_rows[0]}",
        }
    else:
        failures.append(f"expected exactly one editable freeze row, got {len(editable_rows)}")
    for key, wanted in EXPECTED_FREEZE_COUNTS.items():
        if counts[key] != wanted:
            failures.append(f"package freeze {key} count: expected {wanted}, got {counts[key]}")
    return expected


def _normalise_distribution_records(
    records: Iterable[Mapping[str, Any]], failures: list[str]
) -> dict[str, dict[str, Any]]:
    actual: dict[str, dict[str, Any]] = {}
    for index, source_record in enumerate(records):
        record = dict(source_record)
        raw_name = record.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            failures.append(f"distribution record {index} has no valid metadata Name")
            continue
        canonical = _canonical_name(raw_name)
        if canonical in actual:
            failures.append(f"duplicate installed distribution canonical name: {canonical}")
            continue
        if not isinstance(record.get("version"), str) or not record["version"]:
            failures.append(f"installed distribution {canonical} has no valid version")
        if record.get("direct_url_error"):
            failures.append(
                f"installed distribution {canonical} has invalid direct_url.json: "
                f"{record['direct_url_error']}"
            )
        actual[canonical] = record
    return actual


def _source_kind(record: Mapping[str, Any]) -> tuple[str, str | None]:
    direct = record.get("direct_url")
    if direct is None:
        return "version", None
    if not isinstance(direct, Mapping):
        return "invalid", None
    url = direct.get("url")
    if not isinstance(url, str) or not url:
        return "invalid", None
    directory_info = direct.get("dir_info")
    if isinstance(directory_info, Mapping) and directory_info.get("editable") is True:
        return "editable", url
    return "direct", url


def _validate_distributions(
    expected: Mapping[str, Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
    environment_prefix: Path,
    failures: list[str],
    allowed_installer_extras: Mapping[str, str],
) -> dict[str, Any]:
    actual = _normalise_distribution_records(records, failures)
    justifications: dict[str, str] = {}
    for raw_name, reason in allowed_installer_extras.items():
        canonical = _canonical_name(raw_name)
        if not isinstance(reason, str) or not reason.strip():
            failures.append(f"installer-extra justification for {canonical} is empty")
            continue
        if canonical in justifications:
            failures.append(f"duplicate installer-extra justification: {canonical}")
            continue
        justifications[canonical] = reason.strip()

    expected_names = set(expected)
    actual_names = set(actual)
    missing = sorted(expected_names - actual_names)
    unapproved_extras = sorted((actual_names - expected_names) - set(justifications))
    approved_extras = sorted((actual_names - expected_names) & set(justifications))
    unused_justifications = sorted(set(justifications) - (actual_names - expected_names))
    if missing:
        failures.append(f"missing installed distributions: {missing}")
    if unapproved_extras:
        failures.append(f"unapproved installer extras: {unapproved_extras}")
    if unused_justifications:
        failures.append(
            f"installer-extra justifications do not match installed extras: {unused_justifications}"
        )

    drift: dict[str, dict[str, Any]] = {}
    for name in sorted(expected_names & actual_names):
        wanted = expected[name]
        observed = actual[name]
        observed_kind, observed_url = _source_kind(observed)
        issues: list[str] = []
        wanted_kind = str(wanted["kind"])
        if observed_kind != wanted_kind:
            issues.append(f"source kind expected {wanted_kind}, got {observed_kind}")
        if wanted_kind in {"direct", "editable"} and observed_url != wanted["value"]:
            issues.append(f"source URL expected {wanted['value']!r}, got {observed_url!r}")
        if wanted_kind == "version" and observed.get("version") != wanted["value"]:
            issues.append(f"version expected {wanted['value']!r}, got {observed.get('version')!r}")
        direct_expectation = EXPECTED_DIRECT_DISTRIBUTIONS.get(name)
        if direct_expectation is not None:
            if observed.get("version") != direct_expectation["version"]:
                issues.append(
                    "metadata version expected "
                    f"{direct_expectation['version']!r}, got {observed.get('version')!r}"
                )
            if observed_url != direct_expectation["url"]:
                issues.append(
                    f"pinned direct URL expected {direct_expectation['url']!r}, "
                    f"got {observed_url!r}"
                )
        if name == EXPECTED_EDITABLE_NAME and observed.get("version") != EXPECTED_EDITABLE_VERSION:
            issues.append(
                f"editable metadata version expected {EXPECTED_EDITABLE_VERSION!r}, "
                f"got {observed.get('version')!r}"
            )
        if issues:
            drift[name] = {
                "expected_row": wanted["row"],
                "observed_version": observed.get("version"),
                "observed_source_kind": observed_kind,
                "observed_url": observed_url,
                "issues": issues,
            }
            failures.extend(f"distribution drift for {name}: {issue}" for issue in issues)

    outside_prefix: list[dict[str, str]] = []
    for name, record in sorted(actual.items()):
        location = record.get("location")
        if not isinstance(location, str) or not _is_within(location, environment_prefix):
            outside_prefix.append({"name": name, "location": repr(location)})
    if outside_prefix:
        failures.append(
            f"distribution metadata locations outside environment prefix: {outside_prefix}"
        )

    license_evidence: dict[str, Any] = {}
    for name, expected_sha256 in EXPECTED_INSTALLED_LICENSE_SHA256.items():
        record = actual.get(name)
        files = record.get("license_files", []) if record is not None else []
        if not isinstance(files, list):
            files = []
        observed_files = [dict(item) for item in files if isinstance(item, Mapping)]
        observed_hashes = {
            item.get("sha256") for item in observed_files if isinstance(item.get("sha256"), str)
        }
        matched = expected_sha256 in observed_hashes
        license_evidence[name] = {
            "expected_sha256": expected_sha256,
            "matched": matched,
            "files": observed_files,
        }
        if not matched:
            failures.append(
                f"installed license hash mismatch for {name}: expected {expected_sha256}, "
                f"observed {sorted(observed_hashes)}"
            )

    return {
        "expected_distribution_count": len(expected),
        "observed_distribution_count": len(actual),
        "missing": missing,
        "unapproved_extras": unapproved_extras,
        "approved_installer_extras": [
            {"name": name, "justification": justifications[name]} for name in approved_extras
        ],
        "unused_installer_extra_justifications": unused_justifications,
        "drift": drift,
        "locations_outside_environment": outside_prefix,
        "installed_licenses": license_evidence,
    }


def _validate_probe(
    probe: Mapping[str, Any],
    repository_root: Path,
    environment_prefix: Path,
    failures: list[str],
) -> dict[str, Any]:
    expected_values = {
        "python_version": EXPECTED_PYTHON,
        "torch_cuda_version": EXPECTED_TORCH_CUDA,
    }
    for key, expected in expected_values.items():
        if probe.get(key) != expected:
            failures.append(f"runtime {key}: expected {expected!r}, got {probe.get(key)!r}")
    if probe.get("sys_version_info") != [3, 10, 12]:
        failures.append(
            f"runtime sys.version_info: expected [3, 10, 12], got {probe.get('sys_version_info')!r}"
        )
    observed_prefix = probe.get("sys_prefix")
    prefix_matches = (
        isinstance(observed_prefix, str) and Path(observed_prefix).resolve() == environment_prefix
    )
    if not prefix_matches:
        failures.append(
            f"runtime sys.prefix: expected {str(environment_prefix)!r}, got {observed_prefix!r}"
        )
    executable = probe.get("sys_executable")

    modules = probe.get("modules")
    if not isinstance(modules, Mapping):
        failures.append("runtime module probe is missing or not an object")
        modules = {}
    module_versions = {
        "torch": EXPECTED_TORCH,
        "torchaudio": EXPECTED_TORCHAUDIO,
    }
    for name, expected_version in module_versions.items():
        record = modules.get(name)
        observed = record.get("version") if isinstance(record, Mapping) else None
        if observed != expected_version:
            failures.append(
                f"imported {name}.__version__: expected {expected_version!r}, got {observed!r}"
            )

    module_locations: dict[str, Any] = {}
    for name in ("sa3_smoke", *_REQUIRED_PREFIX_MODULES):
        record = modules.get(name)
        location = record.get("file") if isinstance(record, Mapping) else None
        expected_root = repository_root if name == "sa3_smoke" else environment_prefix
        under_expected_root = isinstance(location, str) and _is_within(location, expected_root)
        module_locations[name] = {
            "file": location,
            "expected_root": str(expected_root),
            "under_expected_root": under_expected_root,
        }
        if not under_expected_root:
            failures.append(f"imported {name} location is outside {expected_root}: {location!r}")
    return {
        "python_version": probe.get("python_version"),
        "sys_version": probe.get("sys_version"),
        "sys_version_info": probe.get("sys_version_info"),
        "sys_prefix": observed_prefix,
        "sys_executable": executable,
        "torch_cuda_version": probe.get("torch_cuda_version"),
        "module_versions": {
            name: record.get("version") if isinstance(record, Mapping) else None
            for name, record in modules.items()
        },
        "module_locations": module_locations,
    }


def validate_live_environment(
    repository_root: str | Path,
    runtime_json: str | Path | None = None,
    package_freeze: str | Path | None = None,
    *,
    probe: Mapping[str, Any] | Callable[[], Mapping[str, Any]] | None = None,
    distributions: Iterable[Mapping[str, Any]]
    | Callable[[], Iterable[Mapping[str, Any]]]
    | None = None,
    allowed_installer_extras: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate live interpreter/import/metadata state against committed records.

    The returned object always has exactly ``passed``, ``failures``, and
    ``evidence`` keys and is safe for strict JSON serialization.  Any failed
    read, import, metadata probe, or comparison makes ``passed`` false.
    """

    failures: list[str] = []
    evidence: dict[str, Any] = {}
    root = Path(repository_root).resolve()
    expected_runtime_path = root / "environment" / "runtime.json"
    expected_freeze_path = root / "environment" / "package-freeze.txt"
    runtime_path = Path(runtime_json).resolve() if runtime_json else expected_runtime_path
    freeze_path = Path(package_freeze).resolve() if package_freeze else expected_freeze_path
    if runtime_path != expected_runtime_path:
        failures.append(f"runtime.json path: expected {expected_runtime_path}, got {runtime_path}")
    if freeze_path != expected_freeze_path:
        failures.append(f"package-freeze path: expected {expected_freeze_path}, got {freeze_path}")

    file_paths = {
        "environment/runtime.json": runtime_path,
        "environment/package-freeze.txt": freeze_path,
        **{
            relative: root / relative
            for relative in EXPECTED_FILE_SHA256
            if relative not in {"environment/runtime.json", "environment/package-freeze.txt"}
        },
    }
    file_evidence: dict[str, Any] = {}
    for relative, expected_sha256 in EXPECTED_FILE_SHA256.items():
        path = file_paths[relative]
        try:
            observed_sha256 = _sha256_file(path)
        except OSError as exc:
            observed_sha256 = None
            failures.append(f"cannot hash committed file {relative}: {exc}")
        matched = observed_sha256 == expected_sha256
        file_evidence[relative] = {
            "path": str(path),
            "expected_sha256": expected_sha256,
            "observed_sha256": observed_sha256,
            "matched": matched,
        }
        if observed_sha256 is not None and not matched:
            failures.append(
                f"committed file hash drift for {relative}: expected {expected_sha256}, "
                f"got {observed_sha256}"
            )
    evidence["committed_files"] = file_evidence

    runtime: dict[str, Any] = {}
    try:
        loaded_runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        if not isinstance(loaded_runtime, dict):
            raise ValueError("root is not an object")
        runtime = loaded_runtime
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        failures.append(f"cannot read runtime.json: {exc}")
    expected_runtime_values = {
        "environment_path": str(EXPECTED_ENVIRONMENT_PATH),
        "python": EXPECTED_PYTHON,
        "torch": EXPECTED_TORCH,
        "torchaudio": EXPECTED_TORCHAUDIO,
        "freeze_sha256": EXPECTED_FILE_SHA256["environment/package-freeze.txt"],
        "lock_sha256": EXPECTED_FILE_SHA256["uv.lock"],
        "pyproject_sha256": EXPECTED_FILE_SHA256["pyproject.toml"],
        "license_inventory_sha256": EXPECTED_FILE_SHA256["environment/licenses.json"],
    }
    for key, expected in expected_runtime_values.items():
        if runtime.get(key) != expected:
            failures.append(f"runtime.json {key}: expected {expected!r}, got {runtime.get(key)!r}")
    evidence["runtime_record"] = {
        "path": str(runtime_path),
        "validated_fields": {
            key: {"expected": expected, "observed": runtime.get(key)}
            for key, expected in expected_runtime_values.items()
        },
    }
    declared_environment = runtime.get("environment_path")
    environment_prefix = (
        Path(declared_environment).resolve()
        if isinstance(declared_environment, str) and declared_environment
        else EXPECTED_ENVIRONMENT_PATH.resolve()
    )

    freeze_text = ""
    try:
        freeze_text = freeze_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        failures.append(f"cannot read package freeze: {exc}")
    expected_distributions = _parse_freeze(freeze_text, failures)
    evidence["package_freeze"] = {
        "path": str(freeze_path),
        "row_count": len(freeze_text.splitlines()),
        "parsed_distribution_count": len(expected_distributions),
        "expected_counts": dict(EXPECTED_FREEZE_COUNTS),
    }

    try:
        live_probe = probe() if callable(probe) else probe
        if live_probe is None:
            live_probe = collect_runtime_probe()
        if not isinstance(live_probe, Mapping):
            raise TypeError("runtime probe did not return an object")
        evidence["runtime_probe"] = _validate_probe(live_probe, root, environment_prefix, failures)
    except Exception as exc:  # fail closed across arbitrary import/runtime failures
        failures.append(f"runtime probe failed: {type(exc).__name__}: {exc}")
        evidence["runtime_probe"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        live_distributions = distributions() if callable(distributions) else distributions
        if live_distributions is None:
            live_distributions = collect_distributions()
        evidence["distributions"] = _validate_distributions(
            expected_distributions,
            live_distributions,
            environment_prefix,
            failures,
            allowed_installer_extras or {},
        )
    except Exception as exc:  # fail closed across arbitrary metadata failures
        failures.append(f"distribution probe failed: {type(exc).__name__}: {exc}")
        evidence["distributions"] = {"error": f"{type(exc).__name__}: {exc}"}

    result = {"passed": not failures, "failures": failures, "evidence": evidence}
    json.dumps(result, allow_nan=False, sort_keys=True)
    return result


__all__ = [
    "collect_distributions",
    "collect_runtime_probe",
    "validate_live_environment",
]

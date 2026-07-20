"""Strict JSON, hashing, rendering, and immutable-tree helpers for rater bundles."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


class StrictJSONError(ValueError):
    """Raised when JSON is ambiguous or contains values outside the frozen schema."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_constant(token: str) -> None:
    raise StrictJSONError(f"non-finite JSON number is forbidden: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> Any:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StrictJSONError(f"invalid UTF-8 JSON: {path}: {exc}") from exc
    validate_finite_json(value)
    return value


def validate_finite_json(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StrictJSONError(f"non-finite number at {path.strip()}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_finite_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrictJSONError(f"non-string object key at {path.strip()}")
            validate_finite_json(item, f"{path}.{key}")
        return
    raise StrictJSONError(f"unsupported JSON value at {path.strip()}: {type(value).__name__}")


def require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise StrictJSONError(f"{context} keys differ; missing={missing}, extra={extra}")


def write_json_exclusive(path: Path, value: Any, *, mode: int = 0o444) -> None:
    validate_finite_json(value)
    text = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, mode)


def embedded_json(value: Any) -> str:
    """Return a script-safe JSON literal that works without fetch under file://."""

    text = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_bundle_html(template_path: Path, bundle: dict[str, Any]) -> str:
    placeholder = "__EMBEDDED_PUBLIC_BUNDLE_JSON__"
    template = template_path.read_text(encoding="utf-8")
    if template.count(placeholder) != 1:
        raise ValueError("timing-pilot template must contain exactly one bundle placeholder")
    rendered = template.replace(placeholder, embedded_json(bundle))
    if placeholder in rendered:
        raise RuntimeError("bundle placeholder survived HTML rendering")
    return rendered


def freeze_public_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.chmod(path, 0o444 if path.is_file() else 0o555)
    os.chmod(root, 0o555)


def freeze_private_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        os.chmod(path, 0o400 if path.is_file() else 0o500)
    os.chmod(root, 0o500)

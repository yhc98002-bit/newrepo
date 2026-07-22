#!/usr/bin/env python3
"""Validate the dedicated SAO environment before exposing a GPU."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backbones.sao_environment import (  # noqa: E402
    environment_manifest,
    run_cpu_factory_probe,
    run_cpu_import_probe,
)


def _write_exclusive(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    try:
        payload = (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:  # pragma: no cover - defensive kernel-I/O guard
                raise OSError("short write while sealing SAO CPU evidence")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--access-receipt", type=Path, required=True)
    parser.add_argument("--runtime-authorization", type=Path, required=True)
    parser.add_argument("--backbone-config", type=Path, required=True)
    parser.add_argument("--package-freeze", type=Path, required=True)
    parser.add_argument("--base-lock", type=Path, default=ROOT / "uv.lock")
    parser.add_argument("--numpy-wheel", type=Path, required=True)
    parser.add_argument("--inference-import-patch", type=Path, required=True)
    parser.add_argument("--import-output", type=Path, required=True)
    parser.add_argument("--factory-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    import_probe = run_cpu_import_probe(args.environment)
    _write_exclusive(args.import_output, import_probe)
    if not import_probe["passed"]:
        return 2
    factory_probe = run_cpu_factory_probe(
        snapshot_dir=args.snapshot,
        access_receipt_path=args.access_receipt,
        runtime_authorization_path=args.runtime_authorization,
        backbone_config_path=args.backbone_config,
    )
    _write_exclusive(args.factory_output, factory_probe)
    manifest = environment_manifest(
        import_probe=import_probe,
        factory_probe=factory_probe,
        package_freeze_path=args.package_freeze,
        base_lock_path=args.base_lock,
        numpy_wheel_path=args.numpy_wheel,
        inference_import_patch_path=args.inference_import_patch,
    )
    _write_exclusive(args.manifest_output, manifest)
    print(json.dumps(manifest, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

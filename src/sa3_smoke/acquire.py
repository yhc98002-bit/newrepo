"""Finalize and verify the pinned ModelScope-first model snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .provenance import build_weight_manifest, sha256_file

MODELSCOPE_REVISION = "a9c479f5f28ee89f6fbdaca57b683e6b6c160314"
HUGGINGFACE_REVISION = "b32993f73c3bdc3864043a72d8032606bba737c8"


def _entry(
    sha256: str,
    size: int,
    role: str,
    *,
    cross_provider_verified: bool = False,
) -> dict[str, object]:
    return {
        "cross_provider_verified": cross_provider_verified,
        "role": role,
        "sha256": sha256,
        "size": size,
    }


EXPECTED_FILES = {
    ".gitattributes": _entry(
        "fd6cc1d416c362fd60d19324aa2cb99067b4d02bc7719fe8e0a43ae0c21129c8",
        2323,
        "repository_metadata",
    ),
    "LICENSE.md": _entry(
        "d6f6b1a4dce5c852bd6d7d9482d002baf0ccdb71e662250b73be9eec8764ee8d",
        11852,
        "weight_license",
        cross_provider_verified=True,
    ),
    "LICENSE_GEMMA.md": _entry(
        "e77acc0d3163bb7534675045c584b4d04b387b529239fc4b3647da0a01ba4745",
        10541,
        "conditioner_license",
        cross_provider_verified=True,
    ),
    "NOTICE": _entry(
        "66f856d7da72797f528fca46b7c80634ab481f917bfe020960e123d84b19f75f",
        97,
        "conditioner_notice",
        cross_provider_verified=True,
    ),
    "README.md": _entry(
        "f46e841635ce2c1278dddb67e12d83d4094a5c4ec99d04d47feb026435f3e665",
        5240,
        "model_card",
    ),
    "Stable_Audio_3.0_Thumbnail_1x1.png": _entry(
        "a9834815023e381f367ed5e63a4cf6276a75b876b6fd6076f633e3135b786512",
        1462873,
        "model_card_asset",
    ),
    "configuration.json": _entry(
        "3eefed50f26939655a89fcb85efb21acbe4b0fe470f9f61146092fdd83c8d894",
        71,
        "modelscope_metadata",
    ),
    "model.safetensors": _entry(
        "c443fcc4d491475064cd0ff3eb92459b1e5f5060e86d96d016f048e528e24195",
        9222116660,
        "base_model_and_autoencoder_weights",
        cross_provider_verified=True,
    ),
    "model_config.json": _entry(
        "27e2a299f0bda6ff742d3387398f929299575642f2c6a4d4c4f94830928fd0d5",
        7842,
        "upstream_model_config",
    ),
    "svd_bases.pt": _entry(
        "d62c8d3855998fea824fb651885d220f216d2d6a86d14b19224f806ddb125692",
        3842356410,
        "optional_lora_svd_bases",
        cross_provider_verified=True,
    ),
    "t5gemma-b-b-ul2/README.md": _entry(
        "6a96748c87d323d6080d037191346e68c3eda39c34c0530cb4f7f3bd8cc20319",
        18296,
        "conditioner_model_card",
    ),
    "t5gemma-b-b-ul2/config.json": _entry(
        "575334409716886ac2952f5a275ed92868deef8a0ea560258d9970a431c6fb3a",
        2540,
        "conditioner_config",
    ),
    "t5gemma-b-b-ul2/generation_config.json": _entry(
        "1068b94599a94ceea097dd3936819f108c2e70806d7c6cc5ec425610af347625",
        156,
        "conditioner_generation_config",
    ),
    "t5gemma-b-b-ul2/model.safetensors": _entry(
        "9b05ea5a4f211d023832f706fb2c0e83e4fc721b6da35ab69ceb0b55eb7800d3",
        1183022944,
        "conditioner_weights",
        cross_provider_verified=True,
    ),
    "t5gemma-b-b-ul2/special_tokens_map.json": _entry(
        "baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351",
        636,
        "conditioner_tokenizer_metadata",
    ),
    "t5gemma-b-b-ul2/tokenizer.json": _entry(
        "7794135caa3ea73918949c902a781cc61dab674a4b59c17d85931c77c1114cbd",
        34362429,
        "conditioner_tokenizer",
    ),
    "t5gemma-b-b-ul2/tokenizer.model": _entry(
        "61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2",
        4241003,
        "conditioner_tokenizer",
    ),
    "t5gemma-b-b-ul2/tokenizer_config.json": _entry(
        "9546baec0dfefec0e29873edea9488ecde153f846e18c06ea48cb44587bf408f",
        46437,
        "conditioner_tokenizer_config",
    ),
}


def finalize_snapshot(snapshot: Path, manifest_path: Path) -> dict[str, object]:
    """Verify the exact snapshot and return a compact JSON-ready summary."""

    manifest = build_weight_manifest(
        snapshot,
        modelscope_revision=MODELSCOPE_REVISION,
        huggingface_revision=HUGGINGFACE_REVISION,
        expected=EXPECTED_FILES,
        output_path=manifest_path,
    )
    return {
        "file_count": len(manifest["files"]),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "model_sha256": EXPECTED_FILES["model.safetensors"]["sha256"],
        "status": "PASS",
        "total_bytes": sum(item["byte_size"] for item in manifest["files"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(finalize_snapshot(args.snapshot, args.manifest), sort_keys=True))


if __name__ == "__main__":
    main()

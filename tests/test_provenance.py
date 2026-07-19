import json

import pytest

from sa3_smoke.provenance import (
    ProvenanceError,
    build_weight_manifest,
    validate_artifact_provenance,
    write_artifact_provenance,
)


def test_artifact_sidecar_detects_tamper(tmp_path):
    artifact = tmp_path / "clip.wav"
    artifact.write_bytes(b"audio")
    sidecar = write_artifact_provenance(
        artifact,
        label="synthetic_model_output",
        run_id="run-1",
        model_revision="rev",
        license_id="license",
        command="test",
    )
    assert validate_artifact_provenance(artifact)["sha256"]
    with pytest.raises(FileExistsError):
        write_artifact_provenance(
            artifact,
            label="synthetic_model_output",
            run_id="run-2",
            model_revision="rev",
            license_id="license",
            command="test",
        )
    artifact.write_bytes(b"changed")
    with pytest.raises(ProvenanceError, match="byte size|SHA-256"):
        validate_artifact_provenance(artifact)
    assert sidecar.name == "clip.wav.provenance.json"


def test_weight_manifest_verifies_and_rejects_incomplete(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"weights")
    expected = {
        "model.safetensors": {
            "sha256": "9a129038d9a00aed0cf6a7ea059ca50a813449061ab87848cf1a13eafdf33b2c",
            "size": 7,
            "role": "base_model_weights",
            "cross_provider_verified": True,
        }
    }
    output = tmp_path / "weights.manifest.json"
    manifest = build_weight_manifest(
        snapshot,
        modelscope_revision="ms",
        huggingface_revision="hf",
        expected=expected,
        output_path=output,
    )
    assert manifest["files"][0]["cross_provider_verified"] is True
    assert json.loads(output.read_text())["modelscope"]["provider_role"] == "MIRROR"

    other = tmp_path / "incomplete"
    other.mkdir()
    (other / "model.safetensors.incomplete").write_bytes(b"")
    with pytest.raises(ProvenanceError, match="incomplete"):
        build_weight_manifest(
            other,
            modelscope_revision="ms",
            huggingface_revision="hf",
            expected={},
            output_path=tmp_path / "bad.json",
        )

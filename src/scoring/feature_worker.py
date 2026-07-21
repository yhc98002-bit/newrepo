"""Axis-sharded raw feature extraction for frozen automatic instruments."""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from instruments.integrity import analyze_integrity, integrity_raw_metrics
from instruments.voice import VOCAL_CLASSES
from scoring.common import require_sha256, sha256_file, sha256_json


class PostLoadHeadroomBlocked(RuntimeError):
    """Loaded evaluator left too little reserve; no clip may be scored."""

    def __init__(self, free_bytes: int, required_bytes: int, total_bytes: int) -> None:
        super().__init__(
            f"post-load free VRAM {free_bytes} is below required reserve {required_bytes}"
        )
        self.free_bytes = free_bytes
        self.required_bytes = required_bytes
        self.total_bytes = total_bytes


def require_post_load_headroom(
    required_bytes: int, *, torch_module: Any | None = None
) -> dict[str, int]:
    """Check allocator-visible device headroom after model load and before row zero."""

    if (
        isinstance(required_bytes, bool)
        or not isinstance(required_bytes, int)
        or required_bytes <= 0
    ):
        raise ValueError("post-load reserve must be a positive integer")
    if torch_module is None:
        import torch as torch_module

    free_bytes, total_bytes = torch_module.cuda.mem_get_info()
    free = int(free_bytes)
    total = int(total_bytes)
    if free < required_bytes:
        raise PostLoadHeadroomBlocked(free, required_bytes, total)
    return {
        "free_vram_bytes_after_load": free,
        "required_reserve_bytes": required_bytes,
        "total_vram_bytes": total,
    }


def panns_vocal_indices(labels: Sequence[str]) -> list[int]:
    """Select the frozen source set by intersection, as the old instrument did."""

    indices = [index for index, label in enumerate(labels) if label in VOCAL_CLASSES]
    if not indices:
        raise RuntimeError("PANNs vocal class set is empty")
    return indices


def runtime_identity(config: dict[str, Any], *, require_interpreter: bool) -> dict[str, Any]:
    """Hash every external evaluator asset and capture an exact pip freeze."""

    contract = config["feature_contract"]
    if contract["binding_status"] != "EXACT_RUNTIME_BOUND":
        raise RuntimeError("feature extraction runtime is not exactly bound")
    interpreter = Path(contract["interpreter"])
    if require_interpreter and Path(sys.executable) != interpreter:
        raise RuntimeError(
            f"feature worker must use the isolated interpreter {interpreter}, got {sys.executable}"
        )
    artifacts: list[dict[str, Any]] = []
    for row in contract["external_artifacts"]:
        path = Path(row["path"])
        expected = require_sha256(row["sha256"], f"external artifact {path}")
        observed = sha256_file(path)
        size = path.stat().st_size
        if observed != expected or size != row["size_bytes"]:
            raise RuntimeError(f"external evaluator artifact identity mismatch: {path}")
        artifacts.append({"path": str(path), "sha256": observed, "size_bytes": size})

    source = contract["beat_this_source"]
    source_path = Path(source["path"])
    head = subprocess.run(
        ["git", "-C", str(source_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "-C", str(source_path), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(source_path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout
    if head != source["commit"] or tree != source["tree"] or dirty:
        raise RuntimeError("Beat This! source checkout identity/cleanliness mismatch")

    version_probe = subprocess.run(
        [
            str(interpreter),
            "-c",
            (
                "import importlib.metadata,json,sys;"
                "versions={name:importlib.metadata.version(name) for name in sys.argv[1:]};"
                "print(json.dumps(versions))"
            ),
            *contract["package_versions"],
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed_versions = json.loads(version_probe.stdout)
    versions: dict[str, str] = {}
    for distribution, expected in contract["package_versions"].items():
        observed = observed_versions[distribution]
        if observed != expected:
            raise RuntimeError(
                f"package version mismatch for {distribution}: {observed} != {expected}"
            )
        versions[distribution] = observed
    freeze = subprocess.run(
        [str(interpreter), "-m", "pip", "freeze", "--all"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.splitlines()
    return {
        "beat_this_source": {"commit": head, "path": str(source_path), "tree": tree},
        "external_artifacts": artifacts,
        "interpreter": str(interpreter),
        "package_versions": versions,
        "pip_freeze": freeze,
        "pip_freeze_sha256": sha256_json(freeze),
    }


class VoiceExtractor:
    """Frozen old-repository Demucs preprocessing plus PANNs Cnn14."""

    def __init__(self, config: dict[str, Any]) -> None:
        import torch
        from demucs.pretrained import get_model
        from panns_inference import AudioTagging
        from panns_inference.config import labels

        contract = config["feature_contract"]
        weights = {row["id"]: row["path"] for row in contract["external_artifacts"]}
        self.torch = torch
        self.demucs = get_model("htdemucs").to("cuda").eval()
        self.panns = AudioTagging(
            checkpoint_path=weights["panns_cnn14"],
            device="cuda",
        )
        self.labels = labels
        self.vocal_indices = panns_vocal_indices(labels)

    def __call__(self, path: Path) -> dict[str, float]:
        import librosa
        import numpy as np
        import soundfile as sf
        import torchaudio
        from demucs.apply import apply_model

        torch = self.torch
        random.seed(20260711)
        np.random.seed(20260711)
        torch.manual_seed(20260711)
        torch.cuda.manual_seed_all(20260711)
        audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
        waveform = torch.from_numpy(audio.T.copy())
        target_rate = int(self.demucs.samplerate)
        if int(sample_rate) != target_rate:
            waveform = torchaudio.functional.resample(waveform, int(sample_rate), target_rate)
        if waveform.shape[0] == 1:
            waveform = waveform.repeat(2, 1)
        waveform = waveform.to(torch.float32)
        mixture_rms = float(torch.sqrt((waveform**2).mean()))
        with torch.no_grad():
            stems = apply_model(
                self.demucs,
                waveform.unsqueeze(0).to("cuda"),
                device="cuda",
                shifts=1,
                split=True,
                overlap=0.1,
            )[0]
        energies = (stems.to(torch.float32) ** 2).mean(dim=(1, 2))
        vocal_index = self.demucs.sources.index("vocals")
        ratio = float(energies[vocal_index] / energies.sum().clamp_min(1e-12))

        mono, _ = librosa.load(str(path), sr=32000, mono=True)
        clipwise, _embedding = self.panns.inference(mono[None, :])
        values = clipwise[0][self.vocal_indices]
        probability = float(values[int(np.argmax(values))])
        return {
            "demucs_vocal_energy_ratio": ratio,
            "mixture_rms": mixture_rms,
            "panns_max_vocal_probability": probability,
        }


class TempoExtractor:
    """Official frozen Beat This! minimal postprocessor plus librosa 0.11."""

    def __init__(self, config: dict[str, Any]) -> None:
        contract = config["feature_contract"]
        source = str(Path(contract["beat_this_source"]["path"]).resolve())
        if source not in sys.path:
            sys.path.insert(0, source)
        from beat_this.inference import Audio2Beats

        weights = {row["id"]: row["path"] for row in contract["external_artifacts"]}
        self.tracker = Audio2Beats(
            checkpoint_path=weights["beat_this_final0"],
            device="cuda",
            float16=False,
            dbn=False,
        )

    def _window(self, audio: Any, sample_rate: int) -> dict[str, Any]:
        import librosa
        import numpy as np

        mono = np.asarray(audio, dtype=np.float32).mean(axis=1)
        beats, _downbeats = self.tracker(mono, int(sample_rate))
        tempo, frames = librosa.beat.beat_track(
            y=mono,
            sr=int(sample_rate),
            hop_length=512,
            sparse=True,
        )
        tempo_scalar = float(np.asarray(tempo).reshape(-1)[0])
        return {
            "beat_this_events_seconds": [float(value) for value in np.asarray(beats)],
            "hop_length": 512,
            "librosa_beat_frames": [int(value) for value in np.asarray(frames)],
            "librosa_tempo_bpm": tempo_scalar,
            "sample_rate": int(sample_rate),
        }

    def __call__(self, path: Path) -> dict[str, Any]:
        import soundfile as sf

        audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
        first = audio[round(2 * sample_rate) : round(14 * sample_rate)]
        second = audio[round(16 * sample_rate) : round(28 * sample_rate)]
        if not len(first) or not len(second):
            raise ValueError("audio is too short for frozen tempo windows")
        return {
            "first_window": self._window(first, int(sample_rate)),
            "full_clip": self._window(audio, int(sample_rate)),
            "second_window": self._window(second, int(sample_rate)),
        }


def integrity_features(path: Path, *, requested_duration: float) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf

    failures: list[str] = []
    try:
        audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
    except (OSError, RuntimeError) as exc:
        return {
            "file_validity_failures": [f"DECODE_FAILURE:{type(exc).__name__}"],
            "raw_metrics": None,
        }
    duration = len(audio) / float(sample_rate)
    if abs(duration - requested_duration) > 0.25:
        failures.append("DURATION_OUTSIDE_PER_BACKBONE_0P25S_TOLERANCE")
    if audio.shape[1] != 2:
        failures.append("CHANNEL_COUNT_MISMATCH")
    if not np.isfinite(audio).all():
        failures.append("NONFINITE_AUDIO")
    if failures:
        return {"file_validity_failures": failures, "raw_metrics": None}
    result = analyze_integrity(
        audio,
        int(sample_rate),
        expected_duration_seconds=None,
        expected_channel_count=2,
    )
    if result.file_validity_failures:
        return {
            "file_validity_failures": list(result.file_validity_failures),
            "raw_metrics": None,
        }
    return {"file_validity_failures": [], "raw_metrics": integrity_raw_metrics(result)}


def extract_axis_shard(
    snapshot: dict[str, Any],
    config: dict[str, Any],
    *,
    axis: str,
    part_index: int,
    part_count: int,
) -> dict[str, Any]:
    """Extract one deterministic axis shard; it does not write any artifact."""

    if axis not in {"vocal_instrumental", "tempo", "integrity"}:
        raise ValueError("only frozen confirmatory axes have feature workers")
    if (
        isinstance(part_index, bool)
        or not isinstance(part_index, int)
        or isinstance(part_count, bool)
        or not isinstance(part_count, int)
        or part_count <= 0
        or not 0 <= part_index < part_count
    ):
        raise ValueError("feature shard index/count is invalid")
    rows = sorted(
        (row for row in snapshot["rows"] if row["axis"] == axis),
        key=lambda row: row["request_sha256"],
    )
    selected = [row for index, row in enumerate(rows) if index % part_count == part_index]
    extractor: Any
    if axis == "vocal_instrumental":
        extractor = VoiceExtractor(config)
    elif axis == "tempo":
        extractor = TempoExtractor(config)
    else:
        extractor = None
    post_load_headroom: dict[str, int] | None = None
    if axis != "integrity":
        try:
            post_load_headroom = require_post_load_headroom(
                int(config["gpu_guard"]["post_load_reserve_bytes"])
            )
        except PostLoadHeadroomBlocked:
            del extractor
            import torch

            torch.cuda.empty_cache()
            raise
    started = time.monotonic()
    output: list[dict[str, Any]] = []
    for row in selected:
        path = Path(row["audio_path"])
        observed_hash = sha256_file(path)
        if observed_hash != row["audio_sha256"]:
            raise RuntimeError(f"source audio changed after snapshot: {path}")
        if axis == "integrity":
            features = integrity_features(path, requested_duration=float(row["duration_seconds"]))
        else:
            features = extractor(path)
        output.append(
            {
                "audio_sha256": observed_hash,
                "axis": axis,
                "features": features,
                "request_sha256": row["request_sha256"],
            }
        )
    peak = None
    if axis != "integrity":
        import torch

        torch.cuda.synchronize()
        peak = int(torch.cuda.max_memory_reserved())
    return {
        "axis": axis,
        "evaluator_identities": config["feature_contract"]["expected_evaluator_identities"],
        "human_gold_labels_used": False,
        "part_count": part_count,
        "part_index": part_index,
        "peak_reserved_bytes": peak,
        "post_load_headroom": post_load_headroom,
        "row_count": len(output),
        "rows": output,
        "schema_version": 1,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "status": "FEATURE_SHARD_COMPLETE",
        "wall_seconds": time.monotonic() - started,
    }


def merge_feature_shards(
    snapshot: dict[str, Any],
    shards: list[dict[str, Any]],
    *,
    required_axes: set[str] | None = None,
) -> dict[str, Any]:
    """Merge complete disjoint shards into the strict ingestion bundle."""

    axes = required_axes or {"vocal_instrumental", "tempo", "integrity"}
    if not axes <= {"vocal_instrumental", "tempo", "integrity"} or not axes:
        raise ValueError("required_axes must be a nonempty confirmatory subset")
    expected = {
        row["request_sha256"]
        for row in snapshot["rows"]
        if row["axis"] in axes
    }
    rows: list[dict[str, Any]] = []
    identities: Any = None
    slots: set[tuple[str, int, int]] = set()
    for shard in shards:
        if shard.get("status") != "FEATURE_SHARD_COMPLETE":
            raise ValueError("cannot merge an incomplete feature shard")
        if shard.get("snapshot_sha256") != snapshot["snapshot_sha256"]:
            raise ValueError("feature shards span different source snapshots")
        slot = (shard["axis"], shard["part_index"], shard["part_count"])
        if slot in slots:
            raise ValueError("duplicate feature shard slot")
        slots.add(slot)
        if identities is None:
            identities = shard["evaluator_identities"]
        elif identities != shard["evaluator_identities"]:
            raise ValueError("feature shard evaluator identities differ")
        rows.extend(shard["rows"])
    if {shard["axis"] for shard in shards} != axes:
        raise ValueError("feature shard axes differ from required_axes")
    for axis in sorted(axes):
        axis_slots = sorted((part, count) for name, part, count in slots if name == axis)
        counts = {count for _, count in axis_slots}
        expected_slots = (
            [(part, next(iter(counts))) for part in range(next(iter(counts)))]
            if len(counts) == 1
            else []
        )
        if len(counts) != 1 or axis_slots != expected_slots:
            raise ValueError(f"feature shards do not completely cover axis {axis}")
    requests = [row["request_sha256"] for row in rows]
    if len(requests) != len(set(requests)) or set(requests) != expected:
        raise ValueError("merged feature shards do not exactly cover the confirmatory snapshot")
    return {
        "created_at_utc": "RECORDED_BY_FINALIZER_FROM_IMMUTABLE_SHARDS",
        "evaluator_identities": identities,
        "human_gold_labels_used": False,
        "rows": sorted(rows, key=lambda row: row["request_sha256"]),
        "schema_version": 1,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "status": "FEATURE_EXTRACTION_COMPLETE",
    }

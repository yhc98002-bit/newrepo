#!/usr/bin/env python3
"""Create the exact, no-clobber benchmark-v2 prompt and seed package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "v2"
MODELS = (
    "stabilityai/stable-audio-3-medium-base",
    "stabilityai/stable-audio-open-1.0",
    "ACE-Step/ACE-Step-v1-3.5B",
)
SEED_NAMESPACE = "benchmark-v2-root-seed-20260720"


def _write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_seed(model_id: str, prompt_id: str, root_index: int) -> int:
    if model_id not in MODELS:
        raise ValueError(f"unregistered model: {model_id}")
    if not 0 <= root_index <= 7:
        raise ValueError("root_index must be in 0..7")
    material = f"{SEED_NAMESPACE}|{model_id}|{prompt_id}|{root_index}".encode()
    return 1 + int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 2_147_483_646


def vocal_instrumental_rows() -> list[dict[str, Any]]:
    frames = (
        ("indie rock", "electric guitar, bass, and live drums", 120, "verse-chorus form"),
        ("acoustic folk", "fingerpicked guitar, mandolin, and cajon", 96, "verse-refrain form"),
        (
            "synth-pop",
            "analog synthesizers, synth bass, and drum machine",
            128,
            "verse-chorus form",
        ),
        ("classic soul", "Rhodes piano, electric bass, drums, and brass", 84, "verse-chorus form"),
        ("jazz waltz", "piano, upright bass, and brushed drums", 132, "head-solo-head form"),
        (
            "heavy metal",
            "distorted guitars, electric bass, and double-kick drums",
            156,
            "intro-verse-chorus form",
        ),
        ("bossa nova", "nylon-string guitar, acoustic bass, and shaker", 120, "AABA form"),
        (
            "ambient electronic",
            "synth pads, sequenced synthesizer, and soft percussion",
            72,
            "two-section evolving form",
        ),
        (
            "modern country",
            "steel guitar, acoustic guitar, bass, and drums",
            108,
            "verse-chorus form",
        ),
        (
            "funk",
            "clavinet, electric bass, rhythm guitar, and drums",
            112,
            "groove-break-groove form",
        ),
        (
            "cinematic orchestral",
            "strings, horns, and timpani",
            84,
            "theme-development-return form",
        ),
        ("roots reggae", "skank guitar, electric bass, organ, and drums", 76, "verse-chorus form"),
    )
    rows: list[dict[str, Any]] = []
    for index, (genre, instruments, bpm, form) in enumerate(frames, start=1):
        cluster = f"voice-frame-{index:02d}"
        common = f"A {genre} piece at {bpm} BPM featuring {instruments}, following {form}."
        rows.append(
            {
                "axis": "vocal_instrumental",
                "base_prompt": common,
                "cluster_id": cluster,
                "fixed_suffix": "Clearly audible lead human singing is central throughout.",
                "prompt_id": f"{cluster}-vocal",
                "request": "vocal",
            }
        )
        rows.append(
            {
                "axis": "vocal_instrumental",
                "base_prompt": common,
                "cluster_id": cluster,
                "diagnostic_negation_suffix": (
                    "Instrumental only; no singing, speech, rap, choir, or other "
                    "functioning human voice."
                ),
                "fixed_suffix": (
                    f"A purely instrumental arrangement led throughout by {instruments}."
                ),
                "prompt_id": f"{cluster}-instrumental",
                "request": "instrumental",
            }
        )
    return rows


def tempo_rows() -> list[dict[str, Any]]:
    templates = {
        "percussive_regular": (
            "A tightly played instrumental groove at {bpm} BPM with a clearly articulated "
            "kick-and-snare quarter-note pulse, steady throughout."
        ),
        "syncopated": (
            "A syncopated instrumental funk groove at {bpm} BPM with off-beat accents around "
            "a stable underlying quarter-note pulse."
        ),
        "legato_light_percussion": (
            "A legato cinematic instrumental piece at {bpm} BPM with sustained strings and "
            "soft light percussion marking a stable quarter-note pulse."
        ),
    }
    rows: list[dict[str, Any]] = []
    for bpm in (60, 72, 84, 96, 108, 120, 132, 144, 156, 168):
        for salience, template in templates.items():
            prompt_id = f"tempo-{bpm:03d}-{salience}"
            rows.append(
                {
                    "axis": "tempo",
                    "base_prompt": template.format(bpm=bpm),
                    "cluster_id": prompt_id,
                    "fixed_suffix": (f"Maintain a steady quarter-note pulse at exactly {bpm} BPM."),
                    "prompt_id": prompt_id,
                    "salience": salience,
                    "target_bpm": bpm,
                }
            )
    return rows


def integrity_rows() -> list[dict[str, Any]]:
    styles = (
        ("chamber", "a chamber ensemble of strings and piano"),
        ("electronic", "an electronic ensemble of synthesizers, bass, and drums"),
        ("rock", "a rock ensemble of electric guitars, bass, and drums"),
        ("jazz", "a jazz trio of piano, upright bass, and drums"),
        ("orchestral", "a full orchestral ensemble"),
        ("acoustic", "an acoustic ensemble of guitar, mandolin, and hand percussion"),
    )
    profiles = {
        "soft_sustained": "with gentle sustained phrases, soft attacks, and continuous sound",
        "sharp_percussive_control": (
            "with crisp legitimate percussive attacks and sharp musical transients"
        ),
        "dense_loud": "with a dense energetic arrangement and controlled wide dynamics",
    }
    rows: list[dict[str, Any]] = []
    for style_id, ensemble in styles:
        for profile_id, profile in profiles.items():
            prompt_id = f"integrity-{style_id}-{profile_id}"
            rows.append(
                {
                    "axis": "integrity",
                    "base_prompt": (
                        f"A continuous 30-second performance by {ensemble}, {profile}, "
                        "with no intentional silent break or glitch effect."
                    ),
                    "cluster_id": prompt_id,
                    "fixed_suffix": (
                        "Clean intact audio: no clipping, dropouts, unintended silence, "
                        "or digital crackle."
                    ),
                    "profile": profile_id,
                    "prompt_id": prompt_id,
                    "style_family": style_id,
                }
            )
    return rows


def structure_rows() -> list[dict[str, Any]]:
    forms = {
        "verse_chorus_return": "intro, verse, chorus, second verse, chorus, and outro",
        "aaba": "A, A, contrasting B, and returning A sections",
        "build_drop_return": "intro, gradual build, drop, short breakdown, and returning drop",
        "theme_development_return": "theme, development, contrasting episode, and theme return",
        "rondo_abaca": "A, B, A, C, and returning A sections",
        "through_composed_abcd": "four clearly distinct sections A, B, C, and D in order",
    }
    genres = {
        "indie_rock": "an indie-rock instrumental with guitars, bass, and drums",
        "electronic": "an electronic instrumental with synthesizers, bass, and drums",
        "orchestral": "an orchestral instrumental with strings, woodwinds, brass, and percussion",
    }
    rows: list[dict[str, Any]] = []
    for form_id, form_text in forms.items():
        for genre_id, genre_text in genres.items():
            prompt_id = f"structure-{form_id}-{genre_id}"
            rows.append(
                {
                    "axis": "structure_exploratory",
                    "base_prompt": f"Create {genre_text} following {form_text}.",
                    "cluster_id": prompt_id,
                    "fixed_suffix": (
                        "Follow the requested section order and make recurring sections "
                        "recognizably recurrent."
                    ),
                    "form": form_id,
                    "genre": genre_id,
                    "prompt_id": prompt_id,
                }
            )
    return rows


def main() -> int:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to replace frozen prompt package: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    payloads = {
        "vocal_instrumental.json": {
            "primary_instrumental_intervention": "positive_only",
            "rows": vocal_instrumental_rows(),
            "schema_version": 2,
        },
        "tempo.json": {
            "primary_octave_tolerance_ratio": 1.05,
            "rows": tempo_rows(),
            "schema_version": 2,
            "sensitivity_octave_tolerance_ratio": 1.10,
        },
        "integrity.json": {
            "rows": integrity_rows(),
            "schema_version": 2,
            "synthetic_fixture_validation_required": True,
        },
        "structure_exploratory.json": {
            "confirmatory": False,
            "rows": structure_rows(),
            "schema_version": 2,
        },
    }
    for name, payload in payloads.items():
        _write_json_exclusive(OUTPUT / name, payload)

    vector_requests = (
        (MODELS[0], "voice-frame-01-vocal", 0),
        (MODELS[1], "tempo-120-syncopated", 3),
        (MODELS[2], "integrity-rock-sharp_percussive_control", 7),
    )
    seed_payload = {
        "derivation": (
            "1 + uint64_be(sha256(namespace|model_id|prompt_id|root_index)[0:8]) mod 2147483646"
        ),
        "models": list(MODELS),
        "namespace": SEED_NAMESPACE,
        "root_indices": list(range(8)),
        "schema_version": 1,
        "test_vectors": [
            {
                "model_id": model,
                "prompt_id": prompt,
                "root_index": root,
                "seed": derive_seed(model, prompt, root),
            }
            for model, prompt, root in vector_requests
        ],
    }
    _write_json_exclusive(OUTPUT / "seed_registry.json", seed_payload)

    files = sorted(payloads) + ["seed_registry.json"]
    manifest = {
        "axis_row_counts": {
            "integrity": len(payloads["integrity.json"]["rows"]),
            "structure_exploratory": len(payloads["structure_exploratory.json"]["rows"]),
            "tempo": len(payloads["tempo.json"]["rows"]),
            "vocal_instrumental": len(payloads["vocal_instrumental.json"]["rows"]),
        },
        "files": {name: _sha256(OUTPUT / name) for name in files},
        "models": list(MODELS),
        "schema_version": 1,
        "total_prompt_rows": sum(len(payload["rows"]) for payload in payloads.values()),
    }
    _write_json_exclusive(OUTPUT / "manifest.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

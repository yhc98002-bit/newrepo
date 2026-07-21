"""Static acceptance tests for the adjudicated v2 freeze candidate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREREG_PATH = ROOT / "BENCHMARK_PREREG_v2.md"
PREREG = PREREG_PATH.read_text(encoding="utf-8")
NORMALIZED_PREREG = " ".join(PREREG.split())

PROMPT_IDENTITIES = {
    "prompts/v2/manifest.json": (
        "171d6c757ff3ecec1918d2f032206c2b570b3302dc5ed0100da0db5d22708089"
    ),
    "prompts/v2/vocal_instrumental.json": (
        "602c4e0fb419d7a300116eb5fb76c30a8e19364aaef566aec05425caffed9f90"
    ),
    "prompts/v2/tempo.json": (
        "16e31c155e1d535f2211fcd85c8d666c9ba7a6636e4487fd43ea2fd5fa0e36ab"
    ),
    "prompts/v2/integrity.json": (
        "be0e7c65fa8dfad8c7fdbf4456b2c1ad7e6f4fe0bbeb67eba2fcbf96b5f16d03"
    ),
    "prompts/v2/structure_exploratory.json": (
        "6e9ca89c20ebb43313d9b492140970d876a5cfc657cf123cfe44b7d89e974af8"
    ),
    "prompts/v2/seed_registry.json": (
        "2115d7e70a6c3f4dd19f38503861b8aeb3595a8f64dd1fc839d7a209e80724eb"
    ),
}

RATER_IDENTITIES = {
    "rater/timing_pilot_v2.source.json": (
        "1328c48f8a10b524cf5fc78e04e415e4c4a86713a9b74a3a9742570981be3d70"
    ),
    "rater/timing_pilot.html": (
        "78bba8a189b7f281888a7607bb8197ac457196501134e9dec8a3996e724e2708"
    ),
    "rater/timing_pilot_offer_v2.json": (
        "645cca46a001b42aace2f20a95d35921c6e26d7c56665cb7c457b30cf57227cb"
    ),
}

BUILD_COMPANION_IDENTITIES = {
    "provenance/b1/T6_PROMOTION_RESULT.json": (
        "2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2"
    ),
    "provenance/b1/voice_source_manifest.json": (
        "422f5509b12ae101c4bfa96db96254717c3a454f350e1907d05fc6e72eab8df0"
    ),
    "provenance/b1/tempo_evaluator_pins.json": (
        "375df3abe0daf13cc50741db16db8d0347ba3074b874c3434402d54593476447"
    ),
    "provenance/b1/integrity_synthetic_fixture.json": (
        "ec1fe4292dea823a4cfca29b83302b04c8a31151c9e5218157982c1fc342aaad"
    ),
    "provenance/b1/integrity_synthetic_validation.json": (
        "4e1b124ad2247eced85d21f049ad5b3849a4e1dd1a395689c235ec3d998a4dab"
    ),
    "provenance/b1/B1_VALIDATION_REPORT.json": (
        "656c8f960538ac0e35ea85786d1025d2350b581a0adb510a9879b2917506d448"
    ),
    "configs/statistics_v2.json": (
        "d2397bee6fa5b93bfde7287fda08c5b804fcf080448bc8ed1a8abb9feaffe36d"
    ),
    "rater/schema_v2.json": (
        "0edb492fbf00355aec3e9f059d3b17557814f58b203c963f1c420f0c92ccde76"
    ),
    "rater/freeze_manifest_v2.json": (
        "3fc506db647b4b1690866abe39f23f786c256376de3f304845a3fae294edc232"
    ),
    "provenance/citation_audit_v2.json": (
        "f6fadd8b36dfc05b55ba48211c1440de26af10da93f5b8306e4d5d44a5d43311"
    ),
    "BENCHMARK_CORE_PROTOCOL_v2.md": (
        "869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685"
    ),
    "configs/backbones/stable_audio_3_medium_base.json": (
        "e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75"
    ),
    "configs/backbones/stable_audio_open_1_0.json": (
        "fd3c77b1aa6b07f63d9ca207d795dbfc9c82c103358a2aabff3a6bb48e282e2b"
    ),
    "configs/backbones/ace_step_v1.json": (
        "b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879"
    ),
    "provenance/b2/build_status_pre_generation.json": (
        "16a13a6275be01b6ba45544b58e37798b93b30ac03ebfe5b99def07f87a0718e"
    ),
    "provenance/b2/stable_audio_3_adapter.json": (
        "b6add6d47b608930b02de340db52bb3eaf5a36ca10aa19805ae99ba6562b677c"
    ),
    "provenance/b2/stable_audio_open_license_block.json": (
        "1f5d314c2b01622bdaeb9575404753ea4b4b295ea364765942bde3f2812474ef"
    ),
    "provenance/b2/ace_step_v1_port.json": (
        "e57705caedab66d8c4b5ac138ed24fcff79527016e71e3a964f1321080d4d923"
    ),
    "SEED_REGISTRY.md": (
        "d9b175296a97e8acca72d124a950c4e2fcd08c2d4287587c5e70c149f24deb97"
    ),
    "configs/b2_mini_smoke_v2.json": (
        "01a1bd650dbe3f23eeb60c07c46c4a9d66750f4d8070f5e872604c7c4142f632"
    ),
    "B2_MINI_SMOKE_PROTOCOL_v2.md": (
        "2338cc92b1be99ce011902f9f7429976657ccb8ce2a791634d965096ce9c6118"
    ),
    "scripts/run_b2_mini_smoke_v2.py": (
        "040d0f75280c7adfbe614f74dab4a236b70068325ea4f85fe20b4b98ad56baff"
    ),
    "scripts/run_b2_mini_smoke_v2_with_timeout.py": (
        "1ba0dcd7f35e4f56a0f836da10491f440eed12689ca83cca47fbd56aeb47400f"
    ),
    "provenance/b2/b2_mini_smoke_authorization.template.json": (
        "3d0aaa08408ba394d827a578a8a231a39d3a965af325a4afbb019c2c34506ff1"
    ),
    "src/backbones/__init__.py": (
        "e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0"
    ),
    "src/backbones/ace_step_v1.py": (
        "a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7"
    ),
    "src/backbones/contracts.py": (
        "9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2"
    ),
    "src/backbones/factory.py": (
        "7774236d732d0262cbc412b4c516c0484ce20867ec48bc370821d037f09f60e3"
    ),
    "src/backbones/io.py": (
        "fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a"
    ),
    "src/backbones/mini_smoke.py": (
        "d7b810a1f1e35a7193ea2bf3ac34a5071c017c415407b90cf203737f9fed20e5"
    ),
    "src/backbones/runtime.py": (
        "d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed"
    ),
    "src/sa3_smoke/artifacts.py": (
        "c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3"
    ),
    "src/sa3_smoke/audio.py": (
        "c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24"
    ),
}

AMENDED_SEED_REGISTRY_SHA256 = (
    "c6267a855c804b65a69430b01c9739b887fb05cf4d97664a0d002a710b9626f1"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_markers(markers: tuple[str, ...]) -> None:
    missing = [marker for marker in markers if marker not in NORMALIZED_PREREG]
    assert not missing, f"v2 preregistration is missing markers: {missing!r}"


def test_supersession_and_freeze_fail_closed() -> None:
    assert_markers(
        (
            "Supersedes: `BENCHMARK_PREREG_v1.md`",
            "Generation authorization at this draft cutoff: `CLOSED`",
            "Benchmark endpoints scored at this draft cutoff: zero",
            "Benchmark audio generated under v2 at this draft cutoff: zero",
        )
    )
    assignments = re.findall(
        r"(?m)^(?:- )?`?BENCHMARK_PREREG_V2_FROZEN\s*=\s*(YES|NO)`?$",
        PREREG,
    )
    assert assignments
    assert len(set(assignments)) == 1
    if assignments[-1] == "YES":
        unresolved_hash_sentinel = r"PENDING_PHASE_B[123]_[A-Z0-9_]*SHA256"
        assert not re.search(unresolved_hash_sentinel, PREREG)


def test_prompt_files_have_frozen_identities_and_counts() -> None:
    for relative, expected in PROMPT_IDENTITIES.items():
        path = ROOT / relative
        assert path.is_file()
        assert sha256(path) == expected
        assert f"`{relative}`" in PREREG
        assert f"`{expected}`" in PREREG

    expected_counts = {
        "vocal_instrumental.json": 24,
        "tempo.json": 30,
        "integrity.json": 18,
        "structure_exploratory.json": 18,
    }
    for name, count in expected_counts.items():
        payload = json.loads((ROOT / "prompts" / "v2" / name).read_text(encoding="utf-8"))
        assert len(payload["rows"]) == count


def test_positive_only_primary_and_negation_diagnostic() -> None:
    assert_markers(
        (
            "positive-only",
            "A purely instrumental arrangement led throughout by {named_instruments}.",
            "`NEGATION_DIAGNOSTIC`",
            "excluded from the primary `FIXED − BASE` hypothesis",
            "targeted human stress audit",
            "automatic-instrument outcomes",
            "mutation test substitutes a canonical fixture",
            "forbids a hard-coded port",
        )
    )
    payload = json.loads(
        (ROOT / "prompts" / "v2" / "vocal_instrumental.json").read_text(encoding="utf-8")
    )
    instrumental = [row for row in payload["rows"] if row["request"] == "instrumental"]
    assert len(instrumental) == 12
    for row in instrumental:
        expected_prefix = "A purely instrumental arrangement led throughout by "
        assert row["fixed_suffix"].startswith(expected_prefix)
        assert row["diagnostic_negation_suffix"].startswith("Instrumental only; no singing")


def test_tempo_primary_sensitivity_and_window_drift() -> None:
    assert_markers(
        (
            "The **primary** target tolerance is 5%",
            "e_oct <= log2(1.05)",
            "The preregistered sensitivity is 10%",
            "e_oct <= log2(1.10)",
            "ad7974846029835307ba19a3d5cefbf40b243041",
            "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331",
            "af8c839fb15317fa2712ea66e7a22da6a9267b32",
            "`FIRST_WINDOW`",
            "`SECOND_WINDOW`",
            "first-window 5% success and 10% sensitivity",
            "second-window 5% success and 10% sensitivity",
            "signed drift `log2(b_second/b_first)`",
        )
    )


def test_integrity_validation_strata_and_defect_reporting() -> None:
    assert_markers(
        (
            "Mandatory synthetic-injection validation before generation",
            "INTEGRITY_SYNTHETIC_VALIDATION = FAIL",
            "blocks all benchmark generation",
            "Defect-specific prevalence and",
            "failure rates for clipping, dropout, silence, and crackle are **always",
            "integrity-axis outputs",
            "Selections are defect-separated strata",
            "closest clean-side row",
            "sharp/percussive controls",
        )
    )
    section = PREREG.split("## 7. Axis C — acoustic integrity", 1)[1]
    section = section.split("## 8. Structure and repetition", 1)[0]
    for defect in ("Clipping", "Dropout", "Silence", "Crackle"):
        assert f"| {defect} |" in section


def test_build_companion_identities_are_bound() -> None:
    for relative, expected in BUILD_COMPANION_IDENTITIES.items():
        path = ROOT / relative
        assert path.is_file()
        assert f"`{expected}`" in PREREG
        if relative == "SEED_REGISTRY.md":
            # D-0031 authorizes one append-only non-benchmark preflight seed.
            # The exact v2-frozen prefix must remain byte-identical; v2 itself
            # is never rewritten to pretend the later row was preregistered.
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            assert lines[-1] == (
                "| S-0010 | 73193010 | ACE-Step v1 state preflight "
                "reference/export/resume equivalence, non-benchmark | none |\n"
            )
            frozen_prefix = "".join(lines[:-1]).encode("utf-8")
            assert hashlib.sha256(frozen_prefix).hexdigest() == expected
            assert sha256(path) == AMENDED_SEED_REGISTRY_SHA256
            assert "## D-0031" in (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
        else:
            assert sha256(path) == expected


def test_backbone_tiering_and_v15_scope_deferral() -> None:
    assert_markers(
        (
            "exactly three primary human-audited backbones",
            "stable-audio-3-medium-base",
            "stable-audio-open-1.0",
            "ACE-Step v1",
            "`BLOCKED_ON_LICENSE`",
            "No fourth backbone enters the primary human-audited tier",
            "automatic-only tier",
            "ACE-Step v1.5 is deferred for scope and solo-PI budget",
            "generation-only amendment",
            "does **not** require a Gate-0",
        )
    )


def test_root_local_eligibility_unit_and_prompt_grouping() -> None:
    assert_markers(
        (
            "eligibility unit is exactly `(prompt, root, checkpoint)`",
            "only root r's",
            "decoded preview at checkpoint q",
            "RESTART_POOL_SHARED_AT_PROMPT_LEVEL",
            "Six deterministic prompt-grouped folds",
            "`PROMPT_PLUS_TIME_BUDGET`",
            "`PROMPT_PLUS_TIME_BUDGET_PLUS_STATE`",
            "no single-draw outcome-aware oracle",
        )
    )


def test_four_way_gate_and_single_doubling() -> None:
    assert "ELIGIBLE / REPLICATION_ONLY / INCONCLUSIVE_UNDERPOWERED / STOP_AXIS" in (
        NORMALIZED_PREREG
    )
    for label in (
        "ELIGIBLE",
        "REPLICATION_ONLY",
        "INCONCLUSIVE_UNDERPOWERED",
        "STOP_AXIS",
    ):
        assert re.search(rf"(?m)^{label}$", PREREG)
    assert_markers(
        (
            "CROSS_FITTED_DEVIATION_SHARE >= 0.10",
            "Only `INCONCLUSIVE_UNDERPOWERED` triggers one preregistered doubling",
            "There is no second doubling",
            "Apply the same four rules once",
        )
    )


def test_human_budget_and_pilot_gate() -> None:
    assert_markers(
        (
            "at most three hours **including** the timing pilot",
            "**178.0 minutes**",
            "nine presentations",
            "TIMING_PILOT_OFFERED_AWAITING_PI_RESPONSE",
            "HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION",
            "Core generation does **not** wait for pilot ingestion",
            "zero new model",
        )
    )

    for relative, expected in RATER_IDENTITIES.items():
        path = ROOT / relative
        assert path.is_file()
        assert sha256(path) == expected
        assert f"`{expected}`" in PREREG

    offer = json.loads(
        (ROOT / "rater" / "timing_pilot_offer_v2.json").read_text(encoding="utf-8")
    )
    assert offer["item_count"] == 9
    assert offer["audio_generation_calls"] == 0
    assert offer["bundle_json_sha256"] in PREREG
    assert offer["packet_assembly_status"] in PREREG


def test_smoke_e_pass_is_capability_not_axis_result() -> None:
    assert_markers(
        (
            "D-0020 records its PASS",
            "SA3_STATE_CAPABILITY = PASS",
            "30/60/80%",
            "produced waveforms exactly equal",
            "formal per-axis state rows",
            "SA3_SMOKE_E_RETRY_STATUS = PASS",
            "sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24",
        )
    )


def test_build_launch_caps_heartbeat_and_citation_policy() -> None:
    assert_markers(
        (
            "generated-output-slot count may not exceed 10",
            "`S-0008 = 73193008`",
            "`S-0009 = 73193009`",
            "two non-benchmark 30-second calls",
            "MEASUREMENT_STATUS = MEASURED",
            "absolute three-backbone core ceiling is 4,608",
            "queue waits rather than preempts",
            "heartbeat at least every 60 seconds",
            "Every call, failure, and retained audio artifact",
            "Project-authored code MIT",
            "`MTRF` is excluded as unverified",
        )
    )
    assert not re.search(r"\[MTRF[^]]*\]\(https?://", PREREG)

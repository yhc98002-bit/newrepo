"""Static acceptance tests; no model or evaluator code is executed."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREREG = (ROOT / "BENCHMARK_PREREG_v1.md").read_text(encoding="utf-8")
DECISIONS = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"}


class BenchmarkPreregistrationTests(unittest.TestCase):
    def assert_markers(self, text: str, markers: tuple[str, ...]) -> None:
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertTrue(marker in text, f"missing marker: {marker!r}")

    def test_draft_and_backbone_registry(self) -> None:
        self.assert_markers(
            PREREG,
            (
                "DRAFT_FOR_CO_PI_REVIEW_NOT_FROZEN",
                "Generation authorization: `CLOSED`",
                "Results in this document: none",
                "Audio generated under this preregistration: none",
                "stable-audio-3-medium-base",
                "stable-audio-open-1.0",
                "ACE-Step v1",
                "ACE-Step v1.5",
                "V15_GATE0_STATUS = FAIL_ESCALATED",
                "V1.5 is excluded from the v1",
            ),
        )

    def test_axes_generation_contract_and_statistics(self) -> None:
        self.assert_markers(
            PREREG,
            (
                "vocal versus instrumental",
                "explicit tempo",
                "acoustic integrity",
                "Structure and repetition are exploratory only",
                "standardized English prompt set",
                "exactly eight registered seed indices",
                "The registered cluster is independent",
                "`BoN-N`",
                "`N ∈ {1, 2, 4, 8}`",
                "matched-seed `FIXED − BASE` contrast",
                "10,000 deterministic two-stage bootstrap replicates",
            ),
        )

    def test_vocal_tempo_and_integrity_rules(self) -> None:
        self.assert_markers(
            PREREG,
            (
                "demucs_vocal_energy_ratio >= 0.03161777090281248",
                "0.04403413645923138",
                "voice_present = demucs_present OR panns_present",
                "For each eligible model, select 12 unique clips",
                "official Beat This! event tracker",
                "`librosa==0.11.0`",
                "min over k in {-2,-1,0,1,2}",
                "`d_oct <= log2(1.08)`",
                "Exactly 30 unique tempo clips per eligible model",
                "eight of its already scheduled 42 vocal/tempo clips",
            ),
        )
        integrity = PREREG.split("## 7. Axis C — acoustic integrity", 1)[1]
        integrity = integrity.split("## 8. Structure and repetition", 1)[0]
        for defect in ("Clipping", "Dropout", "Silence", "Crackle"):
            self.assertIn(f"| {defect} |", integrity)

    def test_evaluator_audit_and_eligibility_screen(self) -> None:
        self.assert_markers(
            PREREG,
            (
                "Evaluator audit against pooled solo-PI gold",
                "Prospectively audited failure slice against pooled gold",
                "No pooled-gold tuning",
                "replicated-action adaptation",
                "Prompt-only versus prompt+state models",
                "Seeds `0..3` are four roots",
                "`4..7` four paired restart replicates",
                "single-draw outcome-aware oracle",
                "LEGIBILITY(q)",
                "OUTCOME_COMMITMENT(q)",
                "STATE_INCREMENTAL_VALUE",
            ),
        )

    def test_human_budget_licensing_and_citations(self) -> None:
        planned = re.findall(
            r"\| [34] (?:mandatory|including conditional v1\.5).*?\| "
            r"([0-9]+\.[0-9]) \| Within 180 min",
            PREREG,
        )
        self.assertEqual(planned, ["142.9", "175.3"])
        self.assertTrue(all(float(minutes) <= 180 for minutes in planned))
        self.assertIn("hidden repeat", PREREG.lower())
        self.assert_markers(
            PREREG,
            (
                "| Instruments |",
                "| Gold labels |",
                "| Atlas |",
                "| Harness |",
                "MIT for project-authored code",
                "Only primary papers, official model cards",
                "`MTRF` is excluded",
            ),
        )
        self.assertNotRegex(PREREG, r"\[MTRF[^]]*\]\(https?://")

    def test_cost_appendix_is_honest_and_not_double_counted(self) -> None:
        self.assert_markers(
            PREREG,
            (
                "# Appendix A — execution cost and human effort",
                "**1,440**",
                "4,320 outputs and 36 audio-hours",
                "H_m = [R_m*c_m",
                "max(1440-R_m,0)*g_m",
                "142.9 minutes",
                "175.3 minutes",
                "no completed measured-cost smoke in this repository",
                "projects are not imported",
                "GPU_BUDGET_STATUS = UNMEASURED",
            ),
        )

    def test_generation_gates_are_closed(self) -> None:
        self.assert_markers(
            DECISIONS,
            (
                "D-0006 — Benchmark design drafting scope",
                "D-0007 — Benchmark preregistration and execution gates",
                "D-0009 — Decision-identifier collision resolution and benchmark gate",
                "D-0011 — Revoke foundation-smoke execution under no-generation goal",
                "SA3_FOUNDATION_SMOKE_AUTHORIZED = NO",
                "D-0013 — PI constraint amendment for bounded foundation cost smokes",
                "FOUNDATION_COST_SMOKE_AUTHORIZED = YES",
                "MAX_GENERATIONS = 20",
                "MAX_CLIP_SECONDS = 30",
                "MAX_GPUS = 1",
                "MAX_GPU_SECONDS = 1800",
                "BENCHMARK_PREREG_V1_FROZEN = NO",
                "BENCHMARK_EXECUTION_AUTHORIZED = NO",
                "No audio generation is authorized",
            ),
        )

    def test_repository_contains_no_audio(self) -> None:
        audio_files = sorted(
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if ".git" not in path.parts
            and path.is_file()
            and path.suffix.lower() in AUDIO_SUFFIXES
        )
        self.assertEqual(audio_files, [])


if __name__ == "__main__":
    unittest.main()

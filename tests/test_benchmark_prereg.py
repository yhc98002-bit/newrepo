"""Static acceptance tests; no model or evaluator code is executed."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREREG = (ROOT / "BENCHMARK_PREREG_v1.md").read_text(encoding="utf-8")
DECISIONS = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
REPORT_PATH = ROOT / "SA3_FOUNDATION_REPORT.md"
REPORT = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.is_file() else ""
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
                "Benchmark results in this document: none",
                "Benchmark audio generated under this preregistration: none",
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
                "SA3_FOUNDATION_RUN_STATUS = FAIL_ESCALATED",
                "SA3_COST_OBSERVATION_STATUS = MEASURED_SINGLETON",
                ("SA3_BENCHMARK_COST_CALIBRATION_STATUS = INSUFFICIENT_REPETITIONS"),
                ("SAO_COST_STATUS = NOT_MEASURED_BY_THIS_SA3_ONLY_AUTHORIZATION"),
                ("ACE_STEP_V1_COST_STATUS = NOT_MEASURED_BY_THIS_SA3_ONLY_AUTHORIZATION"),
                "MULTI_BACKBONE_BENCHMARK_GPU_BUDGET_STATUS = INCOMPLETE",
                "SA3_STATE_CAPABILITY = PASS",
                "C_SA3 = 1",
                "sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24",
            ),
        )
        self.assertNotIn("GPU_BUDGET_STATUS = UNMEASURED", PREREG)
        self.assertNotIn("no completed measured-cost smoke in this repository", PREREG)
        self.assertNotIn("Future measured `g_m`", PREREG)
        appendix = PREREG.split("# Appendix A — execution cost and human effort", 1)[1]
        self.assertNotRegex(appendix, r"\b(?:ESTIMATE|PENDING)\b")

    def test_terminal_foundation_report_records_partial_failure(self) -> None:
        self.assertTrue(REPORT_PATH.is_file(), "missing SA3_FOUNDATION_REPORT.md")
        self.assert_markers(
            REPORT,
            (
                "SA3_FOUNDATION_RUN_STATUS = FAIL_ESCALATED",
                "sa3-foundation-20260719T134821.040493Z-9ea9d06209d6",
                "65adbde1e8abe9e744749a52745243d7c4bb572e778284d76827f98a05b6d912",
                "7caafac155c3e04519633749bb89a31d4a86f8d118926aabd0bcdd0130626a2c",
                "| A | PASS |",
                "| B | PASS |",
                "| C | PASS |",
                "| D | PASS |",
                "| E | FAIL |",
                "MODEL_CALL_FAILED",
                "Actual DiT NFE",
                "Synchronized official-call wall time",
                "Peak VRAM",
                "FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO",
                "SA3_SMOKE_E_RETRY_STATUS = PASS",
                "SA3_STATE_CAPABILITY = PASS",
                "sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24",
                "10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117",
                "33.31213849410415 s",
                "All three resumes were stricter than required",
            ),
        )

    def test_foundation_terminal_state_and_generation_gates(self) -> None:
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
                "D-0014 — Correct bounded foundation call enumeration before execution",
                "MAX_GENERATIONS = 20",
                "MAX_CLIP_SECONDS = 30",
                "MAX_GPUS = 1",
                "MAX_GPU_SECONDS = 1800",
                "D-0017 — Terminal foundation-smoke result and retry gate",
                "FOUNDATION_COST_SMOKE_STATUS = FAIL_ESCALATED",
                "FOUNDATION_COST_SMOKE_AUTHORIZATION_STATUS = CONSUMED",
                "FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO",
                "D-0018 — Safe flexible GPU placement pool; no execution expansion",
                "physical GPUs on `an12` or `an29`",
                "must not be terminated, evicted, migrated, reconfigured, or",
                "placed at OOM risk",
                "D-0019 — One-shot Smoke E dtype-boundary retry",
                "D-0020 — Terminal Smoke E retry PASS and authority closure",
                "SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZATION_STATUS = CONSUMED",
                "SA3_STATE_CAPABILITY = PASS",
                "BENCHMARK_PREREG_V1_FROZEN = NO",
                "BENCHMARK_EXECUTION_AUTHORIZED = NO",
            ),
        )
        normalized_decisions = " ".join(DECISIONS.split())
        self.assertIn(
            "11 official generation calls producing 14 model outputs",
            normalized_decisions,
        )
        self.assertIn(
            "Eight calls succeeded, three resume calls failed",
            normalized_decisions,
        )
        for gate in (
            "FOUNDATION_COST_SMOKE_AUTHORIZED",
            "FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED",
            "BENCHMARK_PREREG_V1_FROZEN",
            "BENCHMARK_EXECUTION_AUTHORIZED",
        ):
            values = re.findall(rf"\b{re.escape(gate)}\s*=\s*(YES|NO)\b", DECISIONS)
            self.assertTrue(values, f"no decision value found for {gate}")
            self.assertEqual(values[-1], "NO", f"latest {gate} must be NO")

    def test_repository_contains_no_audio(self) -> None:
        audio_files = sorted(
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if ".git" not in path.parts and path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        )
        self.assertEqual(audio_files, [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRE_D0029_DECISIONS_SHA256 = (
    "1da23e78d4049f3ffd8b4373d1122e37d0a1711b95e5e63bc15f4f5180199a34"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision_block(decision_id: str) -> str:
    text = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^## {re.escape(decision_id)}\b.*?(?=^## D-\d+\b|\Z)", text
    )
    assert match is not None
    return match.group(0)


def test_lane_decisions_are_a_true_append_only_suffix() -> None:
    data = (ROOT / "DECISIONS.md").read_bytes()
    marker = b"## D-0029 \xe2\x80\x94"
    suffix_start = data.index(marker)
    historical_prefix = data[:suffix_start]
    assert historical_prefix.endswith(b"\n\n")
    assert hashlib.sha256(historical_prefix[:-1]).hexdigest() == (
        PRE_D0029_DECISIONS_SHA256
    )

    suffix = data[suffix_start:].decode("utf-8")
    headings = re.findall(r"(?m)^## (D-\d+)\b", suffix)
    assert headings == [
        "D-0029",
        "D-0030",
        "D-0031",
        "D-0032",
        "D-0033",
        "D-0034",
        "D-0035",
        "D-0036",
        "D-0037",
        "D-0038",
        "D-0039",
        "D-0040",
        "D-0041",
    ]


def test_four_openings_are_separate_and_hash_bound() -> None:
    expected = {
        "D-0029": (
            "configs/automatic_scoring_v2.json",
            "1e03782323d469fe8bcae09aabd9d86aecf740050d54cbe95b26e14d39d1cbdd",
        ),
        "D-0030": (
            "configs/sa3_state_capture_v2.json",
            "4bb6d6480dd5167da97e4907193204ac319df090668f976734de7d37da87d02e",
        ),
        "D-0031": (
            "configs/ace_state_preflight_v2.json",
            "7996daa1803a71aeae2f9ac8441b73d8cc487eecd1343eb1ab4075e6cc563ed6",
        ),
        "D-0032": (
            "configs/human_packet_autoassembly_v2.json",
            "519f71753ee8340320a9a32e0c8dd72a577e8e48aa57154f20379382520dd4db",
        ),
    }
    for decision_id, (relative, expected_sha) in expected.items():
        assert _sha256(ROOT / relative) == expected_sha
        block = _decision_block(decision_id)
        assert relative in block
        assert expected_sha in block


def test_openings_preserve_scientific_and_execution_boundaries() -> None:
    scoring = _decision_block("D-0029")
    assert "AUTOMATIC_ENDPOINT_SCORING_AUTHORIZED = YES" in scoring
    assert "AUDIO_GENERATION_AUTHORIZED_BY_SCORING = NO" in scoring
    assert "AUTOMATIC_SCORING_HUMAN_GOLD_CLAIMS = NO" in scoring
    assert "QUEUE_DO_NOT_PREEMPT = YES" in scoring

    sa3 = _decision_block("D-0030")
    assert "SA3_STATE_CAPTURE_INITIAL_AUTHORIZED = YES" in sa3
    assert "SA3_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED = NO" in sa3
    assert "NO_AUTOMATIC_RETRY = YES" in sa3

    ace = _decision_block("D-0031")
    assert "ACE_STATE_PREFLIGHT_V2_ATTEMPTS = 1" in ace
    assert "ACE_STATE_PREFLIGHT_V2_MAX_GENERATIONS = 8" in ace
    assert "ACE_STATE_PREFLIGHT_V2_MAX_GPU_SECONDS = 600" in ace
    assert "ACE_STATE_PREFLIGHT_V2_RETRIES = 0" in ace

    packet = _decision_block("D-0032")
    assert "HUMAN_AUDIT_PACKET_AUTOASSEMBLY = ARMED" in packet
    assert "ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA" in packet
    assert "HUMAN_AUDIT_PACKET_HUMAN_GOLD_CLAIMS = NO" in packet


def test_ace_pass_branch_opens_only_the_initial_formal_queue() -> None:
    ace_pass = _decision_block("D-0033")
    assert "ACE_STATE_CAPABILITY = PASS" in ace_pass
    assert "ACE_STATE_CAPTURE_INITIAL_AUTHORIZED = YES" in ace_pass
    assert "ACE_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED = NO" in ace_pass
    assert "NO_AUTOMATIC_RETRY = YES" in ace_pass
    assert (
        "ACE_STATE_CAPTURE_CONFIG_SHA256 = "
        "7797efee802aa9380c3953cfd89d05b852692f284d129c07745e46e584dcf8a3"
    ) in ace_pass
    assert (
        "ACE_STATE_PREFLIGHT_TERMINAL_SHA256 = "
        "69afb2851dbe5b90e6c4c71cc5c4581740bce4b88a4aaab42a410c69c7f8bb7d"
    ) in ace_pass


def test_stage1_and_scoped_state_openings_are_fail_closed_and_hash_bound() -> None:
    stage1 = _decision_block("D-0034")
    assert "STAGE1_OUTCOME_GATE_STATUS = BLOCKED_MISSING_FROZEN_THRESHOLDS" in stage1
    assert "STAGE1_VERDICTS_COMPUTED = NO" in stage1
    assert "STAGE1_CANCELLATION_LEDGER_CREATED = NO" in stage1
    assert _sha256(ROOT / "configs/stage1_outcome_gates_v2.json") in stage1

    sa3 = _decision_block("D-0035")
    assert "SA3_STATE_RESTRICTED_RERUN_AUTHORIZED = YES" in sa3
    assert "SURVIVORS_ONLY = YES" in sa3
    assert "ONE_ROOT_VALIDATION_REQUIRED = YES" in sa3
    assert "NO_THIRD_REPAIR = YES" in sa3
    assert _sha256(ROOT / "configs/sa3_state_restricted_rerun_v2.json") in sa3

    ace = _decision_block("D-0036")
    assert "ACE_STATE_FORMAL_SURVIVORS_ONLY = YES" in ace
    assert "ACE_STATE_FORMAL_STOP_UNITS_PROHIBITED = EXECUTE,SCORE" in ace
    assert "ACE_STATE_SUPPLEMENTAL_AUTHORIZED = NO" in ace
    assert _sha256(ROOT / "configs/ace_state_formal_v2.json") in ace


def test_sao_live_and_packet_watcher_are_separate_hash_bound_openings() -> None:
    sao = _decision_block("D-0037")
    assert "SAO_ACQUISITION_AUTHORIZED = YES" in sao
    assert "SAO_MINI_SMOKE_EXACT_CALLS = 3" in sao
    assert "SAO_CORE_EXACT_ROWS = 1536" in sao
    assert "SAO_STATE_CAPABILITY = NOT_ATTEMPTED" in sao
    assert "SAO_ELIGIBILITY_SCOPE_EXPANDED = NO" in sao
    assert _sha256(ROOT / "configs/sao_live_v2.json") in sao

    packet = _decision_block("D-0038")
    assert "HUMAN_AUDIT_PACKET_AUTOASSEMBLY = ARMED" in packet
    assert "ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA" in packet
    assert "HUMAN_AUDIT_PACKET_HUMAN_GOLD_CLAIMS = NO" in packet
    assert _sha256(ROOT / "configs/human_packet_autoassembly_v2_sao.json") in packet


def test_sao_recovery_and_decision_grade_openings_preserve_scope() -> None:
    recovery = _decision_block("D-0039")
    for assignment in (
        "SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES",
        "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO",
        "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO",
        "SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0",
    ):
        assert assignment in recovery
    assert (
        "SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256 = "
        "d1b7f3c35ab211372910db3ba9a0a73abcf2b24d49745f3d0717cdb77096db82"
    ) in recovery

    tables = _decision_block("D-0040")
    assert "DECISION_GRADE_AUTOMATIC_TABLES_AUTHORIZED = YES" in tables
    assert "DECISION_GRADE_HUMAN_GOLD_CLAIMS = NO" in tables
    assert "DECISION_GRADE_AUDIO_GENERATION_AUTHORIZED = NO" in tables
    assert "SA3_PLUS_ACE_COMPLETE" in tables
    assert "COMPLETED_SCORED_SHARDS_ONLY" in tables

    recovery_attempt2 = _decision_block("D-0041")
    for assignment in (
        "SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES",
        "SAO_ACQUISITION_RECOVERY_RUN_ID = sao-acquisition-recovery-v2-002",
        "SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO",
        "SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO",
        "SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0",
        "SAO_ACQUISITION_RECOVERY_MATERIALIZATION = HARDLINK_CLONE_RETAINED_STAGE",
        "SAO_RECOVERY_ATTEMPT2_ATOMIC_PUBLICATION = NO",
        "SAO_RECOVERY_ATTEMPT2_RECEIPT_GATED_PUBLICATION = YES",
        "SAO_RECOVERY_ATTEMPT2_FURTHER_ATTEMPTS = NO",
    ):
        assert assignment in recovery_attempt2


def test_ace_core_completion_receipt_is_terminal_and_complete() -> None:
    receipt = json.loads(
        (ROOT / "provenance/core/ace_core_completion_v2.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["status"] == "COMPLETE"
    assert receipt["completed_calls"] == 1536
    assert receipt["failed_calls"] == 0
    assert receipt["completed_shards"] == 384
    assert receipt["heartbeat"]["state"] == "COMPLETE"
    assert receipt["generation_queue"]["row_count"] == 1536
    assert receipt["retained_counts"]["wav_files"] == 1536


def test_lane_report_states_automatic_only_and_sao_blocker() -> None:
    report = (ROOT / "SCORING_STATE_LANES_REPORT.md").read_text(encoding="utf-8")
    for marker in (
        "automatic-instrument outcomes",
        "NOT_HUMAN_GOLD",
        "BLOCKED_ON_LICENSE",
        "an12 physical GPUs 0–3 occupied",
        "GPUs 4–7",
        "timing-pilot-bundles",
        "provenance/b2/sao_access_receipt.schema.json",
    ):
        assert marker in report

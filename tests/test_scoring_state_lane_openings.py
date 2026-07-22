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
        "D-0042",
        "D-0043",
        "D-0044",
        "D-0045",
        "D-0046",
        "D-0047",
        "D-0048",
        "D-0049",
        "D-0050",
        "D-0051",
        "D-0052",
        "D-0053",
        "D-0054",
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
    assert "bc54978d8257e14dd373c34c2401f99beb20be78fc4a7a97f762dad67a1b82bd" in stage1

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

    replacement = _decision_block("D-0042")
    for assignment in (
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_AUTHORIZED = YES",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_RUN_ID = sao-mini-smoke-v2-002",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_MODEL_CALLS = 0",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_MODEL_LOADS = 0",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_AUDIO_OUTPUTS = 0",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_EXACT_CALLS = 3",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_MAX_CLIP_SECONDS = 30",
        "SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_MAX_GPUS = 1",
        "SAO_MINI_SMOKE_FURTHER_REPLACEMENT_AUTHORIZED = NO",
    ):
        assert assignment in replacement

    sao_terminal = _decision_block("D-0043")
    for assignment in (
        "SAO_MINI_SMOKE_STATUS = FAILED_STOPPED_NO_RETRY",
        "SAO_MINI_SMOKE_MODEL_CALL_ATTEMPTS = 1",
        "SAO_MINI_SMOKE_COMPLETED_MODEL_LOADS = 0",
        "SAO_MINI_SMOKE_GENERATED_AUDIO_OUTPUTS = 0",
        "SAO_CORE_GENERATION_AUTHORIZED = NO",
        "SAO_AUTOMATIC_SCORING_AUTHORIZED = NO",
        "SAO_STATE_CAPABILITY = NOT_ATTEMPTED",
        "SAO_ELIGIBILITY_SCOPE_EXPANDED = NO",
        "SAO_FURTHER_MINI_SMOKE_ATTEMPTS = 0",
    ):
        assert assignment in sao_terminal
    receipt_path = ROOT / "provenance/b2/sao_live_terminal_v2.json"
    assert _sha256(receipt_path) in sao_terminal
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "BLOCKED_ON_ENGINEERING_FAILURE"
    assert receipt["model_call_attempts"] == 1
    assert receipt["audio_outputs"] == 0
    assert receipt["no_retry"] is True
    assert receipt["benchmark_core_generation_authorized"] is False
    assert receipt["sao_automatic_scoring_authorized"] is False

    sealed_tables = _decision_block("D-0044")
    for assignment in (
        "DECISION_GRADE_INITIAL_STATUS = "
        "DECISION_GRADE_AUTOMATIC_TABLES_PARTIAL_VERIFIED_SOURCES",
        "DECISION_GRADE_INITIAL_PREVALENCE_ROWS = 64",
        "DECISION_GRADE_INITIAL_TEMPO_DRIFT_ROWS = 8",
        "DECISION_GRADE_INITIAL_DISAGREEMENT_ROWS = 28",
        "DECISION_GRADE_INITIAL_MISSING_BACKBONES = stable-audio-open-1.0",
        "DECISION_GRADE_HUMAN_GOLD_CLAIMS = NO",
    ):
        assert assignment in sealed_tables


def test_engineering_repair_and_stage1_policy_are_separate_append_only_decisions() -> None:
    repair = _decision_block("D-0045")
    for assignment in (
        "ENGINEERING_FAILURES_REPAIRABLE = YES",
        "WITHIN_ATTEMPT_RETRY = NO",
        "ENGINEERING_REPAIR_REQUIRES_NEW_RUN_ID = YES",
        "ENGINEERING_REPAIR_REQUIRES_NEW_CLAIM = YES",
        "SCIENTIFIC_RERUNS_FOR_WEAK_RESULTS = NO",
        "FROZEN_SCIENTIFIC_DESIGN_CHANGES_AUTHORIZED = NO",
        "FAILED_ATTEMPTS_IMMUTABLE = YES",
        "STOP_AXIS_UNITS_EXECUTABLE = NO",
        "SAO_OFFLINE_TOKEN_ACCESS_AUTHORIZED = NO",
    ):
        assert assignment in repair

    policy = _decision_block("D-0046")
    config = ROOT / "configs" / "stage1_outcome_gates_v2.json"
    schema = ROOT / "configs" / "stage1_outcome_gates_v2.schema.json"
    for assignment in (
        "STAGE1_POLICY_STATUS = FROZEN_BEFORE_OUTCOME_READ",
        f"STAGE1_POLICY_CONFIG_SHA256 = {_sha256(config)}",
        f"STAGE1_POLICY_SCHEMA_SHA256 = {_sha256(schema)}",
        "STAGE1_BASELINE_FAILURE_RATE_MINIMUM = 0.10",
        "STAGE1_BASELINE_FAILURE_RATE_MAXIMUM = 0.60",
        "STAGE1_MIXED_OUTCOME_PROMPT_SHARE_MINIMUM = 0.20",
        "STAGE1_OUTCOME_ROWS_READ_AT_FREEZE = NO",
        "STAGE1_STOP_UNIT_OPERATIONS = CANCELLED_EXECUTE_AND_SCORE",
    ):
        assert assignment in policy

    terminal = _decision_block("D-0047")
    receipt = ROOT / "provenance" / "stage1" / "stage1_outcome_gates_terminal_v2.json"
    for assignment in (
        "STAGE1_OUTCOME_GATE_STATUS = STAGE1_OUTCOME_GATES_COMPLETE",
        "STAGE1_STOP_CELL_COUNT = 4",
        "STAGE1_CANCELLED_UNIT_COUNT = 576",
        "ACE_STATE_SURVIVOR_AXES = integrity",
        "ACE_STATE_SURVIVOR_UNIT_COUNT = 144",
        "SA3_STATE_SURVIVOR_AXES = vocal_instrumental",
        "SA3_STATE_SURVIVOR_UNIT_COUNT = 144",
        "STATE_INITIAL_SURVIVOR_EXECUTION_AUTHORIZED = YES",
        "STATE_SUPPLEMENTAL_ROOTS_AUTHORIZED = NO",
        f"SHA-256 `{_sha256(receipt)}`",
        "STAGE1_HUMAN_GOLD_CLAIMS = NO",
    ):
        assert assignment in terminal


def test_zero_call_state_repair_openings_bind_exact_attempts_and_placements() -> None:
    sa3 = _decision_block("D-0048")
    for assignment in (
        "SA3_STATE_ENGINEERING_REPAIR_AUTHORIZED = YES",
        "SA3_STATE_ENGINEERING_REPAIR_RUN_ID = sa3-state-v2-restricted-rerun-002",
        "SA3_STATE_ENGINEERING_REPAIR_PREDECESSOR_SHA256 = "
        "edd63740e402f3d91224ffb16872ba62f6482c5bfe5a8220174ae2b0e35689ec",
        "SA3_STATE_ENGINEERING_REPAIR_PLACEMENT = an12:[4];TP1;R1",
        "SA3_STATE_ENGINEERING_REPAIR_SURVIVOR_AXES = vocal_instrumental",
        "SA3_STATE_ENGINEERING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO",
        "SA3_STATE_ENGINEERING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO",
    ):
        assert assignment in sa3

    ace = _decision_block("D-0049")
    for assignment in (
        "ACE_STATE_ENGINEERING_REPAIR_AUTHORIZED = YES",
        "ACE_STATE_ENGINEERING_REPAIR_RUN_ID = ace-state-formal-v2-002",
        "ACE_STATE_ENGINEERING_REPAIR_PREDECESSOR_SHA256 = "
        "4e647f1c3154ea59ad2e2478ba846f5e0c4b41303e8318d52f01368cf2da34dd",
        "ACE_STATE_ENGINEERING_REPAIR_PLACEMENT = an12:[5,6];TP1;R2",
        "ACE_STATE_ENGINEERING_REPAIR_SURVIVOR_AXES = integrity",
        "ACE_STATE_ENGINEERING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO",
        "ACE_STATE_ENGINEERING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO",
    ):
        assert assignment in ace


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
        "BLOCKED_MISSING_FROZEN_THRESHOLDS",
        "FAILED_STOPPED_NO_RETRY",
        "NOT_AUTHORIZED_ENGINEERING_FAILURE",
        "33b15bf8811d1a2f85575605eef95e58e253f77767e79575dc5a6ec263473d94",
        "provenance/b2/sao_live_terminal_v2.json",
        "an12 physical GPUs 0–3 occupied",
        "GPUs 4–7",
        "timing-pilot-bundles",
        "provenance/b2/sao_access_receipt.schema.json",
    ):
        assert marker in report

    launch = (ROOT / "BENCHMARK_LAUNCH_REPORT.md").read_text(encoding="utf-8")
    for marker in (
        "Runtime terminal addendum",
        "NO_VERDICT_SPECIFICATION_BLOCKED",
        "PYWAVELETS_NUMPY_BINARY_ABI_INCOMPATIBILITY",
        "SAO 1,536-row core",
        "zero WAVs",
    ):
        assert marker in launch

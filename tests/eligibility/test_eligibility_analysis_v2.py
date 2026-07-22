from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from eligibility.analysis import analyze_initial_cell, apply_four_way_gate
from eligibility.builder import assemble_initial_rows, build_initial_input_package
from eligibility.contract import (
    ACTIONS,
    ROOT_LOCAL_SOURCE,
    AnalysisConfig,
    BoundInitialInput,
    EligibilityContractError,
    _validate_scored_rows,
    expected_folds,
    load_analysis_config,
    load_bound_initial_input,
    supplemental_trigger,
    validate_prospective_opening,
)
from scoring.common import canonical_json, sha256_file, sha256_json

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "eligibility_analysis_v2.json"
SCHEMA_PATH = ROOT / "configs" / "eligibility_scored_state_actions_v2.schema.json"
BACKBONE = "stable-audio-3-medium-base"
MODEL_ID = "stabilityai/stable-audio-3-medium-base"
AXIS = "vocal_instrumental"
WORDING = "AUTOMATIC_INSTRUMENT_OUTCOME_NOT_HUMAN_VOICE_JUDGMENT"


@pytest.fixture(scope="module")
def config() -> AnalysisConfig:
    return load_analysis_config(CONFIG_PATH, repo_root=ROOT)


def _hashed(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = hashlib.sha256(canonical_json(result).encode()).hexdigest()
    return result


def _state_features(config: AnalysisConfig, signal: float) -> dict[str, dict[str, Any]]:
    contract = config.raw["input_contract"]["state_feature_fields"]
    groups: dict[str, dict[str, Any]] = {}
    for group in ("integrity_values", "within_preview_summaries"):
        groups[group] = {name: 0.0 for name in contract[group]}
    groups["within_preview_summaries"]["dc_offset_per_channel"] = [0.0, 0.0]
    groups["axis_evaluator_values"] = {
        name: (signal if name == "voice_margin" else 0.0)
        for name in contract["axis_evaluator_values"][AXIS]
    }
    groups["frozen_decoder_metadata"] = {
        name: (
            "float32"
            if name == "latent_dtype"
            else ([1, 64, 128] if name == "latent_shape" else 0.0)
        )
        for name in contract["frozen_decoder_metadata"]
    }
    groups["frozen_decoder_metadata"].update(
        {
            "checkpoint_fraction": 0.25,
            "checkpoint_sha256": "a" * 64,
            "decoder_channels": 2.0,
            "decoder_sample_rate": 44100.0,
            "preview_sha256": "b" * 64,
            "schedule_sha256": "c" * 64,
            "transformer_budget_nfe": 50.0,
        }
    )
    return groups


def _synthetic_contract(
    config: AnalysisConfig,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, int],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    prompt_rows = json.loads((ROOT / "prompts/v2/vocal_instrumental.json").read_text())["rows"]
    registry = {row["prompt_id"]: row for row in prompt_rows}
    prompt_ids = config.statistics["eligibility"]["prompt_selection"]["axis_prompt_ids"][AXIS]
    folds = expected_folds(prompt_ids, namespace=config.raw["folds"]["namespace"])
    units: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    scored: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    outcomes_by_binding: dict[str, dict[str, Any]] = {}
    costs: list[dict[str, Any]] = []
    action_sequence = 0
    for prompt_index, prompt_id in enumerate(sorted(prompt_ids)):
        prompt = registry[prompt_id]
        for root in range(4):
            for checkpoint in (0.25, 0.5, 0.75):
                parent = hashlib.sha256(f"parent|{prompt_id}|{root}".encode()).hexdigest()
                signal = 1.0 if (prompt_index + root) % 2 == 0 else -1.0
                unit = _hashed(
                    {
                        "axis": AXIS,
                        "checkpoint_completed_steps": 50.0 * checkpoint,
                        "checkpoint_fraction": checkpoint,
                        "condition": "BASE",
                        "eligibility_unit": {
                            "checkpoint": checkpoint,
                            "prompt": prompt_id,
                            "root": root,
                        },
                        "feature_contract": {
                            "forbidden_sources": [
                                "OTHER_ROOT_PREVIEWS",
                                "ACTION_OUTCOMES",
                                "TERMINAL_AUDIO_FEATURES",
                                "HUMAN_GOLD",
                                "HELD_OUT_FITTED_VALUES",
                            ],
                            "root_local_only": True,
                        },
                        "fold_id": folds[prompt_id],
                        "parent_request_sha256": parent,
                        "preview_source": ROOT_LOCAL_SOURCE,
                        "preview_source_request_sha256": parent,
                        "prompt_id": prompt_id,
                        "root_index": root,
                        "source_condition": "BASE",
                        "tier": "INITIAL",
                        "transformer_budget_nfe": 50.0,
                    },
                    "lane_request_sha256",
                )
                units.append(unit)
                state_features = _state_features(config, signal)
                state_features["frozen_decoder_metadata"]["checkpoint_fraction"] = checkpoint
                state_features["frozen_decoder_metadata"]["checkpoint_completed_steps"] = (
                    50.0 * checkpoint
                )
                preview_sha = hashlib.sha256(
                    f"preview|{unit['lane_request_sha256']}".encode()
                ).hexdigest()
                state_features["frozen_decoder_metadata"]["preview_sha256"] = preview_sha
                evaluator_sha = sha256_json(
                    json.loads((ROOT / "configs/automatic_scoring_v2.json").read_text())[
                        "feature_contract"
                    ]["expected_evaluator_identities"]
                )
                previews.append(
                    {
                        "axis": AXIS,
                        "checkpoint_fraction": checkpoint,
                        "evaluator_identities_sha256": evaluator_sha,
                        "held_out_fitted_value_used": False,
                        "human_gold_used": False,
                        "lane_request_sha256": unit["lane_request_sha256"],
                        "model_id": MODEL_ID,
                        "other_root_preview_used": False,
                        "preview_audio_sha256": preview_sha,
                        "preview_source": ROOT_LOCAL_SOURCE,
                        "preview_source_request_sha256": parent,
                        "root_index": root,
                        "schema_version": 1,
                        "state_features": state_features,
                        "terminal_features_used": False,
                    }
                )
                elapsed_nfe = 50.0 * checkpoint
                elapsed_seconds = 20.0 * checkpoint
                costs.append(
                    {
                        "elapsed_nfe": elapsed_nfe,
                        "elapsed_seconds": elapsed_seconds,
                        "lane_request_sha256": unit["lane_request_sha256"],
                        "remaining_nfe": 50.0 - elapsed_nfe,
                        "remaining_seconds": 20.0 - elapsed_seconds,
                        "schema_version": 1,
                        "total_nfe": 50.0,
                        "total_seconds": 20.0,
                    }
                )
                desired = "KEEP" if signal > 0 else "RESTART_FIXED"
                for action_name in ACTIONS:
                    action_sequence += 1
                    if action_name == "KEEP":
                        action = {
                            "action": action_name,
                            "action_sequence": action_sequence,
                            "axis": AXIS,
                            "checkpoint_fraction": checkpoint,
                            "fold_id": folds[prompt_id],
                            "incremental_cost": "MEASURED_REMAINING_NFE_AND_TIME",
                            "lane_request_sha256": unit["lane_request_sha256"],
                            "outcome_label": "KEEP_TRUE_ROOT_STATE",
                            "outcome_relpath": f"resumed/{unit['lane_request_sha256']}.wav",
                            "outcome_source": "ROOT_LOCAL_TRUE_STATE_RESUME",
                            "outcome_source_root_index": root,
                            "prompt_id": prompt_id,
                            "root_index": root,
                            "tier": "INITIAL",
                        }
                        binding = unit["lane_request_sha256"]
                    else:
                        checkpoint_token = json.dumps(checkpoint, separators=(",", ":"))
                        material = (
                            "benchmark-v2-restart-map-20260720|"
                            f"{prompt_id}|{checkpoint_token}|{action_name}"
                        )
                        offset = (
                            int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big")
                            % 4
                        )
                        roots = (4, 5, 6, 7)
                        pool_root = (roots[offset:] + roots[:offset])[root]
                        binding = hashlib.sha256(
                            f"restart|{prompt_id}|{checkpoint}|{action_name}|{pool_root}".encode()
                        ).hexdigest()
                        action = {
                            "action": action_name,
                            "action_sequence": action_sequence,
                            "axis": AXIS,
                            "checkpoint_fraction": checkpoint,
                            "fold_id": folds[prompt_id],
                            "incremental_cost": "ONE_FULL_NATIVE_GENERATION",
                            "lane_request_sha256": unit["lane_request_sha256"],
                            "outcome_label": "RESTART_POOL_SHARED_AT_PROMPT_LEVEL",
                            "outcome_source": "FROZEN_PROMPT_LEVEL_CORE_TERMINAL_POOL",
                            "outcome_source_condition": (
                                "BASE" if action_name == "RESTART_BASE" else "FIXED"
                            ),
                            "outcome_source_core_artifact": {
                                "audio_sha256": hashlib.sha256(
                                    f"core|{binding}".encode()
                                ).hexdigest()
                            },
                            "outcome_source_request_sha256": binding,
                            "outcome_source_root_index": pool_root,
                            "prompt_id": prompt_id,
                            "restart_pool_root_indices": [4, 5, 6, 7],
                            "root_index": root,
                            "rotation_direction": "LEFT",
                            "rotation_offset": offset,
                            "tier": "INITIAL",
                        }
                    action = _hashed(action, "action_mapping_sha256")
                    actions.append(action)
                    success = action_name == desired
                    audio_sha = hashlib.sha256(f"audio|{binding}".encode()).hexdigest()
                    outcomes_by_binding[binding] = {
                        "automatic_result_wording": WORDING,
                        "axis": AXIS,
                        "evaluator_identities_sha256": evaluator_sha,
                        "human_gold_used": False,
                        "metrics": {"automatic_instrument_success": success},
                        "outcome_audio_sha256": audio_sha,
                        "outcome_binding_sha256": binding,
                        "outcome_valid": True,
                        "schema_version": 1,
                        "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
                    }
                    budget = {
                        "elapsed_nfe": elapsed_nfe,
                        "elapsed_seconds": elapsed_seconds,
                        "incremental_cost_nfe": (
                            50.0 - elapsed_nfe if action_name == "KEEP" else 50.0
                        ),
                        "incremental_cost_seconds": (
                            20.0 - elapsed_seconds if action_name == "KEEP" else 20.0
                        ),
                        "remaining_nfe": 50.0 - elapsed_nfe,
                        "remaining_seconds": 20.0 - elapsed_seconds,
                        "total_nfe": 50.0,
                        "total_seconds": 20.0,
                    }
                    scored.append(
                        {
                            "action": action_name,
                            "action_mapping_sha256": action["action_mapping_sha256"],
                            "automatic_result_wording": WORDING,
                            "axis": AXIS,
                            "backbone": BACKBONE,
                            "budget_features": budget,
                            "checkpoint_fraction": checkpoint,
                            "fold_id": folds[prompt_id],
                            "held_out_fitted_value_used": False,
                            "human_gold_used": False,
                            "lane_request_sha256": unit["lane_request_sha256"],
                            "model_id": MODEL_ID,
                            "other_root_preview_used": False,
                            "outcome_audio_sha256": audio_sha,
                            "outcome_binding_sha256": binding,
                            "outcome_label": action["outcome_label"],
                            "outcome_source": action["outcome_source"],
                            "outcome_source_root_index": action["outcome_source_root_index"],
                            "outcome_success": success,
                            "outcome_valid": True,
                            "preview_audio_sha256": preview_sha,
                            "preview_source_request_sha256": parent,
                            "prompt_factors": {
                                "profile": None,
                                "request": prompt["request"],
                                "salience": None,
                                "style_family": None,
                                "target_bpm": None,
                            },
                            "prompt_id": prompt_id,
                            "prompt_stratum": prompt["request"],
                            "root_index": root,
                            "schema_version": 1,
                            "state_features": deepcopy(state_features),
                            "terminal_features_used": False,
                            "tier": "INITIAL",
                            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
                        }
                    )
    return units, actions, scored, folds, previews, list(outcomes_by_binding.values()), costs


def _validate(
    config: AnalysisConfig,
    units: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    folds: dict[str, int],
    *,
    cancelled: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], ...]:
    unit_index = {row["lane_request_sha256"]: row for row in units}
    action_index = {(row["lane_request_sha256"], row["action"]): row for row in actions}
    return _validate_scored_rows(
        rows,
        config=config,
        backbone=BACKBONE,
        model_id=MODEL_ID,
        axis=AXIS,
        units=unit_index,
        actions=action_index,
        folds=folds,
        survivor_ids=frozenset(unit_index),
        cancelled_ids=cancelled,
    )


def test_config_freezes_verbatim_model_gate_bootstrap_and_schema(config: AnalysisConfig) -> None:
    assert config.raw["model"]["optimizer"] == {
        "ftol": 2.220446049250313e-09,
        "gtol": 1e-08,
        "max_iterations": 2000,
        "max_line_search_steps": 20,
        "method": "L-BFGS-B",
        "require_success": True,
    }
    assert config.raw["model"]["prompt_effect_parameterization"].startswith("NONCENTERED")
    assert config.raw["bootstrap"]["replicates"] == 10000
    assert config.raw["bootstrap"]["seed"] == 2026072002
    assert config.raw["gate"]["order"] == [
        "ELIGIBLE",
        "REPLICATION_ONLY",
        "INCONCLUSIVE_UNDERPOWERED",
        "STOP_AXIS",
    ]
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    fields = config.raw["input_contract"]["state_feature_fields"]
    assert set(schema["$defs"]["decoder"]["required"]) == set(fields["frozen_decoder_metadata"])
    assert set(schema["$defs"]["withinPreview"]["required"]) == set(
        fields["within_preview_summaries"]
    )
    assert set(schema["$defs"]["integrityValues"]["required"]) == set(fields["integrity_values"])
    assert set(schema["$defs"]["voiceAxis"]["required"]) == set(
        fields["axis_evaluator_values"]["vocal_instrumental"]
    )
    assert set(schema["$defs"]["tempoAxis"]["required"]) == set(
        fields["axis_evaluator_values"]["tempo"]
    )
    assert set(schema["$defs"]["integrityAxis"]["required"]) == set(
        fields["axis_evaluator_values"]["integrity"]
    )


def test_four_way_gate_order_boundaries_and_only_supplemental_trigger() -> None:
    assert (
        apply_four_way_gate(
            one_sided_lower=0.001,
            point_estimate=0.01,
            two_sided_upper=0.1,
            deviation_share=0.10,
        )
        == "ELIGIBLE"
    )
    assert (
        apply_four_way_gate(
            one_sided_lower=0.001,
            point_estimate=0.2,
            two_sided_upper=0.4,
            deviation_share=0.099999,
        )
        == "REPLICATION_ONLY"
    )
    assert (
        apply_four_way_gate(
            one_sided_lower=0.0,
            point_estimate=0.05,
            two_sided_upper=0.00001,
            deviation_share=1.0,
        )
        == "INCONCLUSIVE_UNDERPOWERED"
    )
    assert (
        apply_four_way_gate(
            one_sided_lower=0.0,
            point_estimate=0.049999,
            two_sided_upper=1.0,
            deviation_share=1.0,
        )
        == "STOP_AXIS"
    )
    for label in ("ELIGIBLE", "REPLICATION_ONLY", "STOP_AXIS"):
        assert supplemental_trigger(label)["triggered"] is False
    trigger = supplemental_trigger("INCONCLUSIVE_UNDERPOWERED")
    assert trigger["triggered"] is True
    assert trigger["root_indices"] == [4, 5, 6, 7]
    assert trigger["maximum_additional_root_blocks"] == 1


def test_strict_rows_bind_survivor_actions_folds_and_root_local_preview(
    config: AnalysisConfig,
) -> None:
    units, actions, rows, folds, *_ = _synthetic_contract(config)
    validated = _validate(config, units, actions, rows, folds)
    assert len(validated) == 432
    assert {row["root_index"] for row in validated} == {0, 1, 2, 3}
    assert {row["fold_id"] for row in validated} == set(range(6))


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda row: row.update(other_root_preview_used=True), "identity/leakage"),
        (lambda row: row.update(terminal_features_used=True), "identity/leakage"),
        (lambda row: row.update(held_out_fitted_value_used=True), "identity/leakage"),
        (lambda row: row.update(root_index=4), "identity/leakage"),
        (lambda row: row.update(fold_id=(row["fold_id"] + 1) % 6), "queue unit/fold"),
        (lambda row: row.update(outcome_binding_sha256="0" * 64), "mapped outcome"),
        (lambda row: row.update(terminal_probability=0.99), "keys differ"),
        (
            lambda row: row.update(outcome_valid=False, outcome_success=True),
            "invalid files must be failures",
        ),
    ],
)
def test_adversarial_rows_fail_closed(config: AnalysisConfig, mutation: Any, match: str) -> None:
    units, actions, rows, folds, *_ = _synthetic_contract(config)
    changed = deepcopy(rows)
    mutation(changed[0])
    with pytest.raises(EligibilityContractError, match=match):
        _validate(config, units, actions, changed, folds)


def test_cancelled_unit_can_never_enter_analysis(config: AnalysisConfig) -> None:
    units, actions, rows, folds, *_ = _synthetic_contract(config)
    cancelled = frozenset({rows[0]["lane_request_sha256"]})
    with pytest.raises(EligibilityContractError, match="STOP/cancelled"):
        _validate(config, units, actions, rows, folds, cancelled=cancelled)


def test_action_dependent_preview_features_are_rejected(config: AnalysisConfig) -> None:
    units, actions, rows, folds, *_ = _synthetic_contract(config)
    changed = deepcopy(rows)
    changed[1]["state_features"]["axis_evaluator_values"]["voice_margin"] += 0.5
    with pytest.raises(EligibilityContractError, match="changes root-local preview"):
        _validate(config, units, actions, changed, folds)


def test_fail_closed_builder_uses_only_frozen_instrument_receipts(config: AnalysisConfig) -> None:
    units, actions, expected, _folds, previews, outcomes, costs = _synthetic_contract(config)
    built = assemble_initial_rows(
        config=config,
        backbone=BACKBONE,
        model_id=MODEL_ID,
        axis=AXIS,
        queue_units=units,
        action_rows=actions,
        survivor_units=units,
        preview_rows=previews,
        outcome_rows=outcomes,
        cost_rows=costs,
    )
    assert len(built) == len(expected) == 432
    bad = deepcopy(outcomes)
    bad[0]["human_gold_used"] = True
    with pytest.raises(EligibilityContractError, match="automatic outcome receipt"):
        assemble_initial_rows(
            config=config,
            backbone=BACKBONE,
            model_id=MODEL_ID,
            axis=AXIS,
            queue_units=units,
            action_rows=actions,
            survivor_units=units,
            preview_rows=previews,
            outcome_rows=bad,
            cost_rows=costs,
        )


def test_built_package_passes_the_full_manifest_queue_and_stage1_contract(
    tmp_path: Path, config: AnalysisConfig
) -> None:
    units, actions, _expected, folds, previews, outcomes, costs = _synthetic_contract(config)

    def write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, allow_nan=False, sort_keys=True) + "\n")

    def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(canonical_json(value) + "\n" for value in values))

    queue = tmp_path / "queue"
    unit_path = queue / "initial-units.jsonl"
    action_path = queue / "replicated-action-map.jsonl"
    fold_path = queue / "prompt-grouped-folds.json"
    write_jsonl(unit_path, units)
    write_jsonl(action_path, actions)
    write_json(
        fold_path,
        {
            "assignment": "WHOLE_PROMPT_GROUPED",
            "fold_count": 6,
            "fold_namespace": config.raw["folds"]["namespace"],
            "rows": [
                {"axis": AXIS, "fold_id": fold, "prompt_id": prompt}
                for prompt, fold in folds.items()
            ],
            "schema_version": 1,
        },
    )
    queue_manifest = queue / "state-capture-manifest.json"
    write_json(
        queue_manifest,
        {
            "action_map": {"path": str(action_path), "sha256": sha256_file(action_path)},
            "folds": {"path": str(fold_path), "sha256": sha256_file(fold_path)},
            "tier": "INITIAL",
            "units": {"path": str(unit_path), "sha256": sha256_file(unit_path)},
        },
    )
    stage1 = tmp_path / "stage1"
    survivor_units = stage1 / "survivors/sa3/units.jsonl"
    write_jsonl(survivor_units, units)
    survivor_manifest = survivor_units.parent / "manifest.json"
    write_json(
        survivor_manifest,
        {
            "automatic_instrument_outcomes": True,
            "backbone": BACKBONE,
            "human_gold_claims": False,
            "pass_axes": [AXIS],
            "status": "STAGE1_SURVIVOR_MANIFEST_COMPLETE",
            "stop_axes": ["tempo", "integrity"],
            "unit_count": len(units),
            "units_path": str(survivor_units),
            "units_sha256": sha256_file(survivor_units),
            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
        },
    )
    cancelled_units = stage1 / "cancellations/units.jsonl"
    write_jsonl(cancelled_units, [])
    cancellation_manifest = cancelled_units.parent / "manifest.json"
    write_json(
        cancellation_manifest,
        {
            "event_count": 0,
            "human_gold_claims": False,
            "prohibited_operations": ["EXECUTE", "SCORE"],
            "status": "STAGE1_CANCELLATION_MANIFEST_COMPLETE",
            "units_path": str(cancelled_units),
            "units_sha256": sha256_file(cancelled_units),
            "watermark": "AUTOMATIC-INSTRUMENT OUTCOMES",
        },
    )
    preview_path = tmp_path / "preview-features.jsonl"
    outcome_path = tmp_path / "automatic-outcomes.jsonl"
    cost_path = tmp_path / "costs.jsonl"
    write_jsonl(preview_path, previews)
    write_jsonl(outcome_path, outcomes)
    write_jsonl(cost_path, costs)
    package = build_initial_input_package(
        config=config,
        backbone=BACKBONE,
        model_id=MODEL_ID,
        axis=AXIS,
        queue_manifest_path=queue_manifest,
        survivor_manifest_path=survivor_manifest,
        cancellation_manifest_path=cancellation_manifest,
        preview_features_path=preview_path,
        automatic_outcomes_path=outcome_path,
        measured_costs_path=cost_path,
        output_dir=tmp_path / "assembled",
    )
    bound = load_bound_initial_input(Path(package["manifest_path"]), config=config)
    assert len(bound.rows) == 432
    assert len(bound.units) == 144
    assert set(bound.folds.values()) == set(range(6))


def test_exact_cross_fitted_analysis_is_deterministic_and_reports_every_curve(
    config: AnalysisConfig,
) -> None:
    units, actions, rows, folds, *_ = _synthetic_contract(config)
    validated = _validate(config, units, actions, rows, folds)
    bound = BoundInitialInput(
        manifest_path=Path("/synthetic/input-manifest.json"),
        manifest_sha256="f" * 64,
        manifest={"axis": AXIS, "backbone": BACKBONE, "model_id": MODEL_ID},
        rows_path=Path("/synthetic/scored.jsonl"),
        rows_sha256="e" * 64,
        rows=validated,
        units=tuple(units),
        actions=tuple(actions),
        folds=folds,
    )
    first, first_oof = analyze_initial_cell(bound, config=config)
    second, second_oof = analyze_initial_cell(bound, config=config)
    assert first["four_way_gate"] in config.raw["gate"]["order"]
    assert first["four_way_gate"] == second["four_way_gate"]
    assert first["overall_policy"] == second["overall_policy"]
    assert first_oof == second_oof
    assert len(first_oof) == 432
    assert [row["checkpoint_fraction"] for row in first["curves"]] == [0.25, 0.5, 0.75]
    assert len(first["oof_fit_diagnostics"]) == 12
    assert all(row["unseen_prompt_intercept"] == 0.0 for row in first["oof_fit_diagnostics"])
    assert first["bootstrap"] == {
        "cluster_unit": "prompt_id",
        "paired": True,
        "refit_each_replicate": False,
        "replicates": 10000,
        "seed": 2026072002,
        "stratified": True,
    }


def test_prospective_opening_requires_config_schema_and_decision_on_remote_ref(
    tmp_path: Path, config: AnalysisConfig
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "configs").mkdir()
    copied_config = repo / "configs/eligibility_analysis_v2.json"
    copied_schema = repo / "configs/eligibility_scored_state_actions_v2.schema.json"
    copied_config.write_bytes(CONFIG_PATH.read_bytes())
    copied_schema.write_bytes(SCHEMA_PATH.read_bytes())
    decision_id = "D-9001"
    values = {
        **config.raw["opening_contract"]["required_assignment_values"],
        "ELIGIBILITY_ANALYSIS_CONFIG_SHA256": sha256_file(copied_config),
        "ELIGIBILITY_ACTION_ROW_SCHEMA_SHA256": sha256_file(copied_schema),
    }
    decisions = repo / "DECISIONS.md"
    decisions.write_text(
        f"## {decision_id} — prospective eligibility freeze\n\n"
        + "\n".join(
            f"{name} = {values[name]}"
            for name in config.raw["opening_contract"]["required_assignment_names"]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "freeze"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", head], cwd=repo, check=True)
    fake = AnalysisConfig(
        path=copied_config.resolve(),
        sha256=sha256_file(copied_config),
        schema_path=copied_schema.resolve(),
        schema_sha256=sha256_file(copied_schema),
        repo_root=repo.resolve(),
        raw=config.raw,
        statistics=config.statistics,
    )
    receipt = validate_prospective_opening(fake, decisions_path=decisions, decision_id=decision_id)
    assert receipt["status"] == "PROSPECTIVE_OPENING_VERIFIED_BEFORE_OUTCOME_READ"
    decisions.write_text(decisions.read_text() + "uncommitted\n", encoding="utf-8")
    with pytest.raises(EligibilityContractError, match="not on origin/main"):
        validate_prospective_opening(fake, decisions_path=decisions, decision_id=decision_id)


def test_runner_surface_cannot_pass_an_outcome_path_to_opening() -> None:
    parameters = inspect.signature(validate_prospective_opening).parameters
    assert set(parameters) == {"config", "decisions_path", "decision_id"}
    source = (ROOT / "scripts/run_eligibility_analysis_v2.py").read_text()
    assert source.index("validate_prospective_opening(") < source.index("run_initial_analysis(")

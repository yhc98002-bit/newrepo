"""Exact prompt-grouped hierarchical Bernoulli-logit MAP implementation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

BASELINE_TIER = "PROMPT_PLUS_TIME_BUDGET"
STATE_TIER = "PROMPT_PLUS_TIME_BUDGET_PLUS_STATE"
TIERS = (BASELINE_TIER, STATE_TIER)


class EligibilityModelError(RuntimeError):
    """A design matrix, optimizer, or cross-fitting invariant failed."""


@dataclass(frozen=True)
class Encoder:
    feature_names: tuple[str, ...]
    means: np.ndarray
    scales: np.ndarray


@dataclass(frozen=True)
class FittedMap:
    intercept: float
    coefficients: np.ndarray
    prompt_effects: Mapping[str, float]
    sigma_prompt: float
    feature_names: tuple[str, ...]
    objective: float
    iterations: int
    gradient_max_abs: float


@dataclass(frozen=True)
class OOFResult:
    probabilities: Mapping[str, np.ndarray]
    diagnostics: tuple[dict[str, Any], ...]


def require_frozen_numeric_runtime() -> dict[str, str]:
    """Require the versions already bound by automatic_scoring_v2."""

    try:
        import scipy
    except ImportError as exc:  # pragma: no cover - exercised by fail-closed deployments
        raise EligibilityModelError("SciPy is required for frozen L-BFGS-B") from exc
    if np.__version__ != "2.2.6" or scipy.__version__ != "1.15.3":
        raise EligibilityModelError(
            "eligibility numeric runtime must be NumPy 2.2.6 / SciPy 1.15.3"
        )
    return {"numpy": np.__version__, "scipy": scipy.__version__}


def _feature_values(row: Mapping[str, Any], tier: str) -> tuple[dict[str, float], set[str]]:
    if tier not in TIERS:
        raise EligibilityModelError(f"unknown model tier: {tier}")
    budget = row["budget_features"]
    numeric = {
        "budget.checkpoint_fraction": float(row["checkpoint_fraction"]),
        **{f"budget.{name}": float(budget[name]) for name in sorted(budget)},
    }
    categorical = {f"action={row['action']}"}
    factors = row["prompt_factors"]
    for name in ("request", "salience", "profile", "style_family"):
        value = factors[name]
        if value is not None:
            categorical.add(f"prompt.{name}={value}")
    request = factors["request"]
    if request is not None:
        categorical.add(f"interaction.action_x_request={row['action']}|{request}")
    target = factors["target_bpm"]
    if target is not None:
        numeric["prompt.target_bpm"] = float(target)
        for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED"):
            numeric[f"interaction.action_x_target_bpm={action}"] = (
                float(target) if row["action"] == action else 0.0
            )
    if tier == STATE_TIER:
        for group in sorted(row["state_features"]):
            for name, value in sorted(row["state_features"][group].items()):
                feature = f"state.{group}.{name}"
                if isinstance(value, str):
                    categorical.add(f"{feature}={value}")
                    categorical.add(f"interaction.action_x_{feature}={row['action']}|{value}")
                elif isinstance(value, list):
                    for position, item in enumerate(value):
                        component = f"{feature}[{position}]"
                        numeric[component] = float(item)
                        for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED"):
                            numeric[f"interaction.action_x_{component}={action}"] = (
                                float(item) if row["action"] == action else 0.0
                            )
                else:
                    numeric[feature] = float(value)
                    for action in ("KEEP", "RESTART_BASE", "RESTART_FIXED"):
                        numeric[f"interaction.action_x_{feature}={action}"] = (
                            float(value) if row["action"] == action else 0.0
                        )
    return numeric, categorical


def fit_encoder(rows: Sequence[Mapping[str, Any]], tier: str) -> Encoder:
    """Freeze vocabulary, means, and population SD on training prompts only."""

    if not rows:
        raise EligibilityModelError("cannot fit an encoder on no rows")
    extracted = [_feature_values(row, tier) for row in rows]
    numeric_names = sorted(set().union(*(set(values) for values, _ in extracted)))
    category_names = sorted(set().union(*(tokens for _, tokens in extracted)))
    names = tuple(numeric_names + [f"onehot.{token}" for token in category_names])
    matrix = np.zeros((len(rows), len(names)), dtype=np.float64)
    numeric_index = {name: index for index, name in enumerate(numeric_names)}
    category_index = {
        token: len(numeric_names) + index for index, token in enumerate(category_names)
    }
    for row_index, (numbers, tokens) in enumerate(extracted):
        for name, value in numbers.items():
            matrix[row_index, numeric_index[name]] = value
        for token in tokens:
            matrix[row_index, category_index[token]] = 1.0
    means = np.mean(matrix, axis=0)
    scales = np.std(matrix, axis=0, ddof=0)
    scales = np.where(scales > 0.0, scales, 1.0)
    return Encoder(names, means, scales)


def transform(rows: Sequence[Mapping[str, Any]], tier: str, encoder: Encoder) -> np.ndarray:
    index = {name: position for position, name in enumerate(encoder.feature_names)}
    matrix = np.zeros((len(rows), len(index)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        numbers, tokens = _feature_values(row, tier)
        for name, value in numbers.items():
            position = index.get(name)
            if position is not None:
                matrix[row_index, position] = value
        for token in tokens:
            position = index.get(f"onehot.{token}")
            if position is not None:
                matrix[row_index, position] = 1.0
    return (matrix - encoder.means) / encoder.scales


def _sigmoid(value: np.ndarray) -> np.ndarray:
    result = np.empty_like(value, dtype=np.float64)
    positive = value >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-value[positive]))
    exponential = np.exp(value[~positive])
    result[~positive] = exponential / (1.0 + exponential)
    return result


def fit_hierarchical_map(
    matrix: np.ndarray,
    outcomes: np.ndarray,
    prompts: Sequence[str],
    *,
    optimizer: Mapping[str, Any],
    sigma_lower_bound: float,
) -> FittedMap:
    """Fit the frozen noncentered hierarchical MAP with analytic gradient."""

    require_frozen_numeric_runtime()
    from scipy.optimize import minimize

    if matrix.ndim != 2 or outcomes.shape != (matrix.shape[0],):
        raise EligibilityModelError("hierarchical MAP matrix/outcome shape drifted")
    if len(prompts) != matrix.shape[0] or not set(np.unique(outcomes)) <= {0.0, 1.0}:
        raise EligibilityModelError("hierarchical MAP prompts/outcomes are invalid")
    prompt_levels = tuple(sorted(set(prompts)))
    prompt_index = {prompt: index for index, prompt in enumerate(prompt_levels)}
    group = np.asarray([prompt_index[prompt] for prompt in prompts], dtype=np.int64)
    feature_count = matrix.shape[1]
    prompt_count = len(prompt_levels)
    sigma_position = 1 + feature_count + prompt_count

    def objective(parameters: np.ndarray) -> tuple[float, np.ndarray]:
        intercept = parameters[0]
        coefficients = parameters[1 : 1 + feature_count]
        z_prompt = parameters[1 + feature_count : sigma_position]
        sigma = parameters[sigma_position]
        prompt_effect = sigma * z_prompt
        eta = intercept + matrix @ coefficients + prompt_effect[group]
        residual = _sigmoid(eta) - outcomes
        value = float(
            np.sum(np.logaddexp(0.0, eta) - outcomes * eta)
            + 0.5 * (intercept / 2.5) ** 2
            + 0.5 * np.dot(coefficients, coefficients)
            + 0.5 * np.dot(z_prompt, z_prompt)
            + 0.5 * sigma**2
        )
        grouped_residual = np.bincount(group, weights=residual, minlength=prompt_count)
        gradient = np.empty_like(parameters)
        gradient[0] = np.sum(residual) + intercept / (2.5**2)
        gradient[1 : 1 + feature_count] = matrix.T @ residual + coefficients
        gradient[1 + feature_count : sigma_position] = sigma * grouped_residual + z_prompt
        gradient[sigma_position] = float(np.dot(z_prompt, grouped_residual) + sigma)
        return value, gradient

    initial = np.zeros(sigma_position + 1, dtype=np.float64)
    initial[sigma_position] = 0.5
    bounds = [(None, None)] * sigma_position + [(sigma_lower_bound, None)]
    result = minimize(
        objective,
        initial,
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
        options={
            "ftol": float(optimizer["ftol"]),
            "gtol": float(optimizer["gtol"]),
            "maxiter": int(optimizer["max_iterations"]),
            "maxls": int(optimizer["max_line_search_steps"]),
        },
    )
    if optimizer["require_success"] is True and not result.success:
        raise EligibilityModelError(
            f"frozen L-BFGS-B did not converge: status={result.status}; {result.message}"
        )
    if not np.isfinite(result.x).all() or not math.isfinite(float(result.fun)):
        raise EligibilityModelError("hierarchical MAP returned nonfinite parameters")
    parameters = np.asarray(result.x, dtype=np.float64)
    sigma = float(parameters[sigma_position])
    z_prompt = parameters[1 + feature_count : sigma_position]
    gradient = np.asarray(result.jac, dtype=np.float64)
    return FittedMap(
        intercept=float(parameters[0]),
        coefficients=parameters[1 : 1 + feature_count],
        prompt_effects={
            prompt: float(sigma * z_prompt[index]) for index, prompt in enumerate(prompt_levels)
        },
        sigma_prompt=sigma,
        feature_names=tuple(),
        objective=float(result.fun),
        iterations=int(result.nit),
        gradient_max_abs=float(np.max(np.abs(gradient), initial=0.0)),
    )


def predict_map(
    fitted: FittedMap,
    matrix: np.ndarray,
    prompts: Sequence[str],
    *,
    unseen_prompt_intercept: float,
) -> np.ndarray:
    if matrix.shape[1] != fitted.coefficients.shape[0] or matrix.shape[0] != len(prompts):
        raise EligibilityModelError("prediction matrix shape drifted")
    effects = np.asarray(
        [fitted.prompt_effects.get(prompt, unseen_prompt_intercept) for prompt in prompts],
        dtype=np.float64,
    )
    probabilities = _sigmoid(fitted.intercept + matrix @ fitted.coefficients + effects)
    if not np.isfinite(probabilities).all() or np.any((probabilities < 0) | (probabilities > 1)):
        raise EligibilityModelError("MAP predictions are not finite probabilities")
    return probabilities


def cross_fitted_probabilities(
    rows: Sequence[Mapping[str, Any]],
    *,
    model_config: Mapping[str, Any],
) -> OOFResult:
    """Fit both tiers in six deterministic whole-prompt folds."""

    if len(rows) == 0:
        raise EligibilityModelError("cross-fitting requires rows")
    probabilities = {tier: np.full(len(rows), np.nan, dtype=np.float64) for tier in TIERS}
    diagnostics: list[dict[str, Any]] = []
    folds = sorted({int(row["fold_id"]) for row in rows})
    if folds != list(range(6)):
        raise EligibilityModelError("cross-fitting requires folds 0..5")
    for fold in folds:
        test_indices = [index for index, row in enumerate(rows) if row["fold_id"] == fold]
        train_indices = [index for index, row in enumerate(rows) if row["fold_id"] != fold]
        train_prompts = {str(rows[index]["prompt_id"]) for index in train_indices}
        test_prompts = {str(rows[index]["prompt_id"]) for index in test_indices}
        if len(test_prompts) != 2 or train_prompts & test_prompts:
            raise EligibilityModelError("fold does not hold out exactly two whole prompts")
        training = [rows[index] for index in train_indices]
        testing = [rows[index] for index in test_indices]
        outcomes = np.asarray([float(row["outcome_success"]) for row in training])
        for tier in TIERS:
            encoder = fit_encoder(training, tier)
            train_matrix = transform(training, tier, encoder)
            test_matrix = transform(testing, tier, encoder)
            fitted = fit_hierarchical_map(
                train_matrix,
                outcomes,
                [str(row["prompt_id"]) for row in training],
                optimizer=model_config["optimizer"],
                sigma_lower_bound=float(model_config["sigma_prompt_lower_bound"]),
            )
            predicted = predict_map(
                fitted,
                test_matrix,
                [str(row["prompt_id"]) for row in testing],
                unseen_prompt_intercept=float(model_config["unseen_prompt_intercept"]),
            )
            probabilities[tier][test_indices] = predicted
            diagnostics.append(
                {
                    "feature_count": len(encoder.feature_names),
                    "fold_id": fold,
                    "gradient_max_abs": fitted.gradient_max_abs,
                    "held_out_prompts": sorted(test_prompts),
                    "iterations": fitted.iterations,
                    "objective": fitted.objective,
                    "optimizer": "L-BFGS-B",
                    "sigma_prompt": fitted.sigma_prompt,
                    "tier": tier,
                    "training_prompt_count": len(train_prompts),
                    "unseen_prompt_intercept": 0.0,
                }
            )
    if any(not np.isfinite(value).all() for value in probabilities.values()):
        raise EligibilityModelError("cross-fitting left missing OOF predictions")
    return OOFResult(probabilities, tuple(diagnostics))

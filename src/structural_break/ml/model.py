"""Chronological Model A training, persisted inference and raw-margin Tree SHAP.

The held-out 2024–2025 outcomes are deliberately outside this module's training
and evaluation path. Every fitted transformation is learned inside its fit period.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import ParameterSampler
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from structural_break.config.models import MLConfig
from structural_break.storage.files import sha256_file, write_bytes


class ModelTrainingError(ValueError):
    """A scientific/data contract cannot support the requested model fit."""


@dataclass(frozen=True)
class SigmoidCalibrator:
    """Monotone Platt mapping, including explicit constant small-sample fits."""

    slope: float
    intercept: float
    sample_count: int
    positives: int
    status: str

    def predict(self, margins: Any) -> np.ndarray[Any, Any]:
        values = np.asarray(margins, dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Calibration margins must be finite")
        return np.asarray(expit(self.slope * values + self.intercept), dtype=float)


def fit_sigmoid(margins: Any, labels: Any) -> SigmoidCalibrator:
    """Fit validation-only sigmoid with Platt target smoothing and a >= 0.

    The nonnegative slope preserves the base model ranking. One-class or constant
    margins cannot identify discrimination, so a smoothed constant prior is saved.
    """
    x = np.asarray(margins, dtype=float).reshape(-1)
    observed_labels = np.asarray(labels, dtype=float).reshape(-1)
    if not np.isin(observed_labels, [0, 1]).all():
        raise ModelTrainingError("Calibration labels must be binary")
    y = observed_labels.astype(int)
    if not len(x) or len(x) != len(y) or not np.isfinite(x).all():
        raise ModelTrainingError("Calibration requires finite nonempty aligned observations")
    if not np.isin(y, [0, 1]).all():
        raise ModelTrainingError("Calibration labels must be binary")
    positives, negatives = int(y.sum()), int(len(y) - y.sum())
    prior = (positives + 1.0) / (len(y) + 2.0)
    intercept = float(np.log(prior / (1.0 - prior)))
    if not positives or not negatives or np.ptp(x) < 1e-12:
        return SigmoidCalibrator(0.0, intercept, len(y), positives, "CONSTANT_UNIDENTIFIABLE")
    target = np.where(y == 1, (positives + 1) / (positives + 2), 1 / (negatives + 2))

    def objective(parameters: np.ndarray[Any, Any]) -> tuple[float, np.ndarray[Any, Any]]:
        a, b = parameters
        logits = a * x + b
        loss = float(np.sum(np.logaddexp(0.0, logits) - target * logits))
        residual = expit(logits) - target
        gradient = np.array([np.dot(residual, x), residual.sum()], dtype=float)
        return loss, gradient

    fitted = minimize(
        objective,
        np.array([0.0, intercept]),
        jac=True,
        method="L-BFGS-B",
        bounds=[(0.0, None), (None, None)],
        options={"ftol": 1e-12, "gtol": 1e-9, "maxiter": 1000},
    )
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise ModelTrainingError(f"Sigmoid calibration failed: {fitted.message}")
    slope, fitted_intercept = (float(value) for value in fitted.x)
    status = "FITTED" if slope > 1e-10 else "CONSTANT_NONNEGATIVE_BOUNDARY"
    return SigmoidCalibrator(slope, fitted_intercept, len(y), positives, status)


def _schema_columns(schema: dict[str, Any]) -> list[str]:
    columns = list(schema["feature_columns"])
    definitions = [column["name"] for column in schema["columns"]]
    if columns != definitions or len(columns) != len(set(columns)) or not columns:
        raise ValueError("Feature schema must have one ordered definition per feature")
    forbidden = {
        "event_id",
        "pair_id",
        "ticker",
        "leg_a",
        "leg_b",
        "company_name",
        "partition",
        "y_revert_success",
        "outcome_type",
        "resolution_date",
        "time_to_resolution",
        "horizon_end_date",
        "max_adverse_z",
        "max_favourable_z",
        "gross_pair_return",
        "net_pair_return",
        "event_timestamp",
    }
    if forbidden.intersection(columns):
        raise ValueError("Identifiers, targets and outcome metadata cannot be predictors")
    return columns


def validate_features(frame: pd.DataFrame, schema: dict[str, Any]) -> pd.DataFrame:
    """Require the frozen ordered numeric schema without arbitrary reordering."""
    columns = _schema_columns(schema)
    if list(frame.columns) != columns:
        raise ValueError("Feature names/order differ from the frozen feature schema")
    result = frame.copy()
    for definition in schema["columns"]:
        name = definition["name"]
        if not pd.api.types.is_numeric_dtype(result[name]):
            raise ValueError(f"Feature must be numeric: {name}")
        values = result[name].to_numpy(dtype=float, na_value=np.nan)
        if np.isinf(values).any():
            raise ValueError(f"Infinite feature: {name}")
        if not definition.get("allow_missing", False) and np.isnan(values).any():
            raise ValueError(f"Required feature is missing: {name}")
        if (
            definition.get("binary", False)
            and not np.isin(values[np.isfinite(values)], [0, 1]).all()
        ):
            raise ValueError(f"Declared binary feature is outside 0/1: {name}")
        result[name] = values
    return result


def _logistic(schema: dict[str, Any], c_value: float, seed: int) -> Any:
    binary = [item["name"] for item in schema["columns"] if item.get("binary", False)]
    continuous = [name for name in _schema_columns(schema) if name not in binary]
    numeric = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
        ]
    )
    transformers: list[tuple[str, Any, list[str]]] = [("continuous", numeric, continuous)]
    if binary:
        transformers.append(("binary", SimpleImputer(strategy="most_frequent"), binary))
    return Pipeline(
        [
            ("preprocessor", ColumnTransformer(transformers, remainder="drop")),
            ("classifier", LogisticRegression(C=c_value, max_iter=3000, random_state=seed)),
        ]
    )


def _xgboost(parameters: dict[str, Any], seed: int) -> Any:
    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=1,
        random_state=seed,
        **parameters,
    )


def _wilson(positive: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    proportion = positive / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * np.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
    return [
        float(max(0.0, center - radius / denominator)),
        float(min(1.0, center + radius / denominator)),
    ]


def predictive_metrics(labels: Any, probabilities: Any, threshold: float = 0.65) -> dict[str, Any]:
    """Coverage, discrimination and calibration; undefined values are explicit nulls."""
    observed_labels = np.asarray(labels, dtype=float)
    if not np.isin(observed_labels, [0, 1]).all():
        raise ValueError("Metrics require aligned binary labels")
    y = observed_labels.astype(int)
    p = np.asarray(probabilities, dtype=float)
    if len(y) != len(p) or not np.isin(y, [0, 1]).all():
        raise ValueError("Metrics require aligned binary labels")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Metrics probabilities must be finite in [0,1]")
    if not len(y):
        return {
            "n": 0,
            "positives": 0,
            "roc_auc": None,
            "pr_auc": None,
            "brier": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "selected": 0,
            "coverage": 0.0,
            "calibration_curve": [],
            "confusion_matrix": None,
        }
    selected = p >= threshold
    classes = len(np.unique(y)) == 2
    calibration = []
    for lower, upper in zip(np.linspace(0, 1, 6)[:-1], np.linspace(0, 1, 6)[1:], strict=True):
        members = (p >= lower) & ((p < upper) if upper < 1 else (p <= upper))
        if members.any():
            calibration.append(
                {
                    "lower": float(lower),
                    "upper": float(upper),
                    "n": int(members.sum()),
                    "mean_probability": float(p[members].mean()),
                    "observed_success_rate": float(y[members].mean()),
                }
            )
    quintiles = []
    edges = np.unique(np.quantile(p, np.linspace(0, 1, 6)))
    if len(edges) == 1:
        quintiles.append(
            {
                "n": len(y),
                "mean_probability": float(p.mean()),
                "observed_success_rate": float(y.mean()),
            }
        )
    else:
        for number, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
            members = (p >= lower) & ((p <= upper) if number == len(edges) - 2 else (p < upper))
            if members.any():
                quintiles.append(
                    {
                        "n": int(members.sum()),
                        "mean_probability": float(p[members].mean()),
                        "observed_success_rate": float(y[members].mean()),
                    }
                )
    return {
        "n": len(y),
        "positives": int(y.sum()),
        "success_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, p)) if classes else None,
        "pr_auc": float(average_precision_score(y, p)) if classes else None,
        "brier": float(brier_score_loss(y, p)),
        "precision": float(precision_score(y, selected, zero_division=0))
        if selected.any()
        else None,
        "recall": float(recall_score(y, selected, zero_division=0)) if y.any() else None,
        "f1": float(f1_score(y, selected, zero_division=0)),
        "selected": int(selected.sum()),
        "coverage": float(selected.mean()),
        "confusion_matrix": confusion_matrix(y, selected, labels=[0, 1]).tolist(),
        "calibration_curve": calibration,
        "observed_probability_quintiles": quintiles,
        "pr_auc_method": "average_precision",
        "success_rate_wilson95_iid_reference": _wilson(int(y.sum()), len(y)),
        "precision_wilson95_iid_reference": _wilson(int(y[selected].sum()), int(selected.sum())),
        "uncertainty_note": (
            "Wilson intervals are iid references; pair/date dependence and small N limit inference."
        ),
    }


def select_threshold(
    labels: Any, probabilities: Any, *, candidate_threshold: float = 0.65
) -> dict[str, Any]:
    """Freeze the predeclared threshold; report validation sensitivity descriptively.

    The available validation event sample is too small to justify precision-based
    policy optimization on the same outcomes used to fit the calibrator.
    """
    grid = [0.55, 0.60, 0.65, 0.70, 0.75]
    evaluated = [
        dict(threshold=value, **predictive_metrics(labels, probabilities, value)) for value in grid
    ]
    return {
        "candidate_threshold": candidate_threshold,
        "status": "FROZEN_PREDECLARED_SMALL_SAMPLE",
        "grid": grid,
        "validation_sensitivity": evaluated,
        "selection_rule": (
            "Retain the predeclared .65 threshold; no optimization on sparse "
            "calibration-fit validation."
        ),
        "bucket_low_upper": 0.55,
        "bucket_high_lower": candidate_threshold,
        "economic_threshold_validation": "DEFERRED_TO_PHASE6",
    }


def forward_folds(rows: pd.DataFrame, settings: MLConfig) -> list[dict[str, Any]]:
    """Three expanding past-to-future folds; labels never cross evaluation boundaries."""
    dates = pd.to_datetime(rows["event_timestamp"], utc=True).dt.date
    horizon = pd.to_datetime(rows["horizon_end_date"]).dt.date
    folds = []
    for year in [2019, 2020, 2021]:
        boundary = date(year, 1, 1)
        fit = rows.index[
            (dates >= settings.train.start) & (dates < boundary) & (horizon < boundary)
        ]
        evaluation = rows.index[
            (dates >= boundary) & (dates <= date(year, 12, 31)) & (horizon <= date(year, 12, 31))
        ]
        folds.append(
            {
                "year": year,
                "fit_index": fit,
                "evaluation_index": evaluation,
                "n_fit": len(fit),
                "n_evaluation": len(evaluation),
            }
        )
    return folds


@dataclass
class ModelBundle:
    model: Any
    logistic: Any
    calibrator: SigmoidCalibrator
    schema: dict[str, Any]
    policy: dict[str, Any]
    background: pd.DataFrame
    metadata: dict[str, Any]
    _explainer: Any = field(default=None, init=False, repr=False)

    def predict(self, features: pd.DataFrame, *, explain: bool = True) -> pd.DataFrame:
        matrix = validate_features(features, self.schema)
        if matrix.empty:
            return pd.DataFrame(
                columns=[
                    "raw_margin",
                    "raw_probability",
                    "calibrated_probability",
                    "logistic_probability",
                    "probability_bucket",
                    "ml_qualified",
                ]
            )
        margin = np.asarray(self.model.predict(matrix, output_margin=True), dtype=float)
        raw = np.asarray(self.model.predict_proba(matrix)[:, 1], dtype=float)
        calibrated = self.calibrator.predict(margin)
        output = pd.DataFrame(
            {
                "raw_margin": margin,
                "raw_probability": raw,
                "calibrated_probability": calibrated,
                "logistic_probability": self.logistic.predict_proba(matrix)[:, 1],
            },
            index=features.index,
        )
        threshold = self.policy["candidate_threshold"]
        output["ml_qualified"] = calibrated >= threshold
        output["probability_bucket"] = np.where(
            calibrated >= threshold, "HIGH", np.where(calibrated < 0.55, "LOW", "MEDIUM")
        )
        output["model_version"] = self.metadata["model_version"]
        output["calibrator_version"] = self.metadata["calibrator_version"]
        output["ml_policy_version"] = self.metadata["ml_policy_version"]
        output["feature_schema_version"] = self.schema["version"]
        output["dataset_version"] = self.metadata["dataset_version"]
        output["label_policy_version"] = self.metadata["label_policy_version"]
        output["split_version"] = self.metadata["split_version"]
        output["explanation_status"] = "NOT_REQUESTED"
        if explain:
            import shap

            if self._explainer is None:
                self._explainer = shap.TreeExplainer(
                    self.model,
                    data=self.background,
                    model_output="raw",
                    feature_perturbation="interventional",
                    feature_names=_schema_columns(self.schema),
                )
            values = np.asarray(
                self._explainer.shap_values(matrix, check_additivity=True), dtype=float
            )
            base = float(self._explainer.expected_value)
            if values.shape != matrix.shape or not np.allclose(
                values.sum(axis=1) + base, margin, atol=2e-5
            ):
                raise ValueError("Tree SHAP did not reconstruct the base model margin")
            positive: list[list[dict[str, Any]]] = []
            negative: list[list[dict[str, Any]]] = []
            for row, inputs in zip(values, matrix.to_numpy(), strict=True):
                drivers: list[dict[str, Any]] = [
                    {
                        "feature": name,
                        "contribution": float(value),
                        "feature_value": None if pd.isna(actual) else float(actual),
                    }
                    for name, value, actual in zip(matrix.columns, row, inputs, strict=True)
                ]
                positive.append(
                    sorted(
                        [item for item in drivers if item["contribution"] > 0],
                        key=lambda item: -item["contribution"],
                    )[:5]
                )
                negative.append(
                    sorted(
                        [item for item in drivers if item["contribution"] < 0],
                        key=lambda item: item["contribution"],
                    )[:5]
                )
            output["shap_base_value"] = base
            output["shap_values"] = values.tolist()
            output["top_shap_positive"] = pd.Series(positive, index=output.index, dtype=object)
            output["top_shap_negative"] = pd.Series(negative, index=output.index, dtype=object)
            output["explanation_status"] = "AVAILABLE_RAW_MARGIN"
        return output


@dataclass(frozen=True)
class TrainingResult:
    bundle: ModelBundle
    metrics: dict[str, Any]
    predictions: pd.DataFrame
    manifest: dict[str, Any]


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str).encode("utf-8")


def _joblib_bytes(value: Any) -> bytes:
    buffer = io.BytesIO()
    joblib.dump(value, buffer)
    return buffer.getvalue()


def _mean_selection(scores: list[dict[str, Any]]) -> tuple[float, float, float]:
    available_auc = [score["roc_auc"] for score in scores if score.get("roc_auc") is not None]
    available_pr = [score["pr_auc"] for score in scores if score.get("pr_auc") is not None]
    briers = [score["brier"] for score in scores if score.get("brier") is not None]
    return (
        float(np.mean(available_auc)) if available_auc else -1.0,
        float(np.mean(available_pr)) if available_pr else -1.0,
        -float(np.mean(briers)) if briers else -1.0,
    )


def _score_folds(
    rows: pd.DataFrame, matrix: pd.DataFrame, folds: list[dict[str, Any]], estimator_factory: Any
) -> list[dict[str, Any]]:
    outcomes = []
    for fold in folds:
        fit, evaluation = fold["fit_index"], fold["evaluation_index"]
        y_fit = rows.loc[fit, "y_revert_success"].astype(int)
        if len(np.unique(y_fit)) < 2 or not len(evaluation):
            outcomes.append(
                {
                    "year": fold["year"],
                    "n_fit": len(fit),
                    "n_evaluation": len(evaluation),
                    "status": "UNUSABLE_ONE_CLASS_FIT_OR_EMPTY_EVALUATION",
                }
            )
            continue
        estimator = estimator_factory()
        estimator.fit(matrix.loc[fit], y_fit)
        probabilities = estimator.predict_proba(matrix.loc[evaluation])[:, 1]
        metrics = predictive_metrics(
            rows.loc[evaluation, "y_revert_success"].astype(int), probabilities
        )
        outcomes.append(
            {
                "year": fold["year"],
                "n_fit": len(fit),
                "n_evaluation": len(evaluation),
                "status": "EVALUATED",
                **metrics,
            }
        )
    return outcomes


def _fold_summary(scores: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "evaluated_folds": sum(score.get("status") == "EVALUATED" for score in scores),
        "total_folds": len(scores),
    }
    for metric in ["roc_auc", "pr_auc", "brier"]:
        values = [score[metric] for score in scores if score.get(metric) is not None]
        summary[metric] = {
            "defined_folds": len(values),
            "mean": float(np.mean(values)) if values else None,
            "std": float(np.std(values)) if values else None,
        }
    return summary


def train_model_a(
    rows: pd.DataFrame,
    feature_schema: dict[str, Any],
    settings: MLConfig,
    output_directory: Path,
    *,
    model_version: str,
    dataset_version: str,
    tracking_directory: Path | None = None,
    label_policy: dict[str, Any] | None = None,
) -> TrainingResult:
    """Tune inside training; calibrate validation and freeze the predeclared policy."""
    columns = _schema_columns(feature_schema)
    if feature_schema["version"] != settings.feature_schema_version:
        raise ValueError("Configured and dataset feature schema versions differ")
    required = {
        "event_id",
        "event_timestamp",
        "partition",
        "supervised_eligible",
        "horizon_end_date",
        "y_revert_success",
    }
    if not required.issubset(rows.columns) or rows["event_id"].duplicated().any():
        raise ValueError("One unique event row with explicit partitions and targets is required")
    if "feature_cutoff_timestamp" in rows:
        cutoff = pd.to_datetime(rows["feature_cutoff_timestamp"], utc=True)
        event_time = pd.to_datetime(rows["event_timestamp"], utc=True)
        if (cutoff > event_time).any() or cutoff.isna().any():
            raise ValueError("Feature cutoff cannot exceed event time or be unknown")
    final = rows["partition"].isin(["final_test", "test"])
    if rows.loc[final, "y_revert_success"].notna().any():
        raise ModelTrainingError("Locked final-test outcomes must not be supplied to training")
    development = rows.loc[
        rows["supervised_eligible"].astype(bool) & rows["partition"].isin(["train", "validation"])
    ].copy()
    development = development.sort_values(["event_timestamp", "event_id"]).reset_index(drop=True)
    if development.empty or development["y_revert_success"].isna().any():
        raise ModelTrainingError("Development rows require known uncensored binary targets")
    if not development["y_revert_success"].isin([0, 1]).all():
        raise ModelTrainingError("Development targets must be binary")
    dates = pd.to_datetime(development["event_timestamp"], utc=True).dt.date
    horizons = pd.to_datetime(development["horizon_end_date"]).dt.date
    training_mask = development["partition"] == "train"
    validation_mask = development["partition"] == "validation"
    if (
        (dates[training_mask] < settings.train.start) | (dates[training_mask] > settings.train.end)
    ).any():
        raise ValueError("Training row lies outside the configured training partition")
    if (horizons[training_mask] > settings.train.end).any():
        raise ValueError("Training label crosses its partition boundary")
    if (
        (dates[validation_mask] < settings.validation.start)
        | (dates[validation_mask] > settings.validation.end)
    ).any():
        raise ValueError("Validation row lies outside the configured validation partition")
    if (horizons[validation_mask] > settings.validation.end).any():
        raise ValueError("Validation label crosses into locked final test")
    matrix = validate_features(development[columns], feature_schema)
    training = development.loc[training_mask]
    if training["y_revert_success"].nunique() != 2:
        raise ModelTrainingError("Final training fit requires both observed target classes")
    folds = forward_folds(training, settings)
    if not any(fold["n_fit"] and fold["n_evaluation"] for fold in folds):
        raise ModelTrainingError("No chronological training fold has fit/evaluation observations")
    search: list[dict[str, Any]] = []
    for c_value in [0.01, 0.1, 1.0, 10.0]:
        scores = _score_folds(
            training,
            matrix,
            folds,
            lambda c_value=c_value: _logistic(feature_schema, c_value, settings.seed),
        )
        search.append(
            {
                "family": "logistic",
                "parameters": {"C": c_value},
                "fold_metrics": scores,
                "summary": _fold_summary(scores),
            }
        )
    best_logistic = max(search, key=lambda item: _mean_selection(item["fold_metrics"]))
    space = {
        "n_estimators": [200, 300, 450, 600],
        "max_depth": [2, 3, 4, 5],
        "learning_rate": [0.03, 0.05, 0.08, 0.10],
        "min_child_weight": [1, 3, 5, 8],
        "subsample": [0.70, 0.85, 1.0],
        "colsample_bytree": [0.70, 0.85, 1.0],
        "reg_alpha": [0.0, 0.1, 0.5, 1.0],
        "reg_lambda": [1.0, 3.0, 5.0, 10.0],
        "gamma": [0.0, 0.1, 0.3],
    }
    search_trials = int(getattr(settings, "search_trials", 30))
    for parameters in ParameterSampler(space, n_iter=search_trials, random_state=settings.seed):
        candidate = {
            key: value.item() if isinstance(value, np.generic) else value
            for key, value in parameters.items()
        }
        scores = _score_folds(
            training, matrix, folds, lambda candidate=candidate: _xgboost(candidate, settings.seed)
        )
        search.append(
            {
                "family": "xgboost",
                "parameters": candidate,
                "fold_metrics": scores,
                "summary": _fold_summary(scores),
            }
        )
    best_xgb = max(
        [item for item in search if item["family"] == "xgboost"],
        key=lambda item: _mean_selection(item["fold_metrics"]),
    )
    if not any(item.get("status") == "EVALUATED" for item in best_xgb["fold_metrics"]):
        raise ModelTrainingError(
            "No fold has both training classes for actual hyperparameter tuning"
        )
    logistic = _logistic(feature_schema, best_logistic["parameters"]["C"], settings.seed)
    model = _xgboost(best_xgb["parameters"], settings.seed)
    x_train, y_train = matrix.loc[training.index], training["y_revert_success"].astype(int)
    logistic.fit(x_train, y_train)
    model.fit(x_train, y_train)
    calibration_mask = validation_mask
    policy_mask = validation_mask
    if not calibration_mask.any():
        raise ModelTrainingError(
            "No eligible validation observations remain for sigmoid calibration"
        )
    margin = np.asarray(model.predict(matrix, output_margin=True), dtype=float)
    calibrator = fit_sigmoid(
        margin[calibration_mask], development.loc[calibration_mask, "y_revert_success"]
    )
    policy = select_threshold(
        development.loc[policy_mask, "y_revert_success"].astype(int),
        calibrator.predict(margin[policy_mask]),
        candidate_threshold=float(settings.candidate_threshold),
    )
    policy.update(
        {
            "calibration_period": "2022-2023",
            "threshold_selection_period": "2022-2023",
            "validation_metric_role": "CALIBRATION_FIT_DESCRIPTIVE",
            "final_test_locked": True,
        }
    )
    schema_hash = hashlib.sha256(_json_bytes(feature_schema)).hexdigest()
    calibrator_version = (
        f"sigmoid_{hashlib.sha256(_json_bytes(calibrator.__dict__)).hexdigest()[:16]}"
    )
    policy_version = f"ml_policy_{hashlib.sha256(_json_bytes(policy)).hexdigest()[:16]}"
    metadata = {
        "model_version": model_version,
        "dataset_version": dataset_version,
        "calibrator_version": calibrator_version,
        "ml_policy_version": policy_version,
        "feature_schema_sha256": schema_hash,
        "selected_hyperparameters": best_xgb["parameters"],
        "logistic_C": best_logistic["parameters"]["C"],
        "seed": settings.seed,
        "final_test_locked": True,
        "search_trials": search_trials,
        "search_space": space,
        "n_training": int(training_mask.sum()),
        "n_calibration": int(calibration_mask.sum()),
        "n_policy_validation": int(policy_mask.sum()),
        "label_policy_version": (label_policy or {}).get("version", settings.label_policy_version),
        "declared_label_policy_version": settings.label_policy_version,
        "split_version": settings.split_version,
        "calibration_event_ids": development.loc[calibration_mask, "event_id"].tolist(),
        "policy_event_ids": development.loc[policy_mask, "event_id"].tolist(),
        "training_event_ids": training["event_id"].tolist(),
        "training_only_transformations": True,
    }
    background = x_train.sample(n=min(100, len(x_train)), random_state=settings.seed).reset_index(
        drop=True
    )
    bundle = ModelBundle(model, logistic, calibrator, feature_schema, policy, background, metadata)
    predictions = pd.concat(
        [development[["event_id", "event_timestamp", "partition"]], bundle.predict(matrix)], axis=1
    )
    predictions["evaluation_role"] = np.select(
        [training_mask, validation_mask],
        ["TRAINING_RESUBSTITUTION", "CALIBRATION_FIT_DESCRIPTIVE"],
        default="EXCLUDED",
    )
    metrics: dict[str, Any] = {
        "final_test": {"status": "LOCKED", "outcomes_inspected": False},
        "sample_limitations": (
            "Small dependent event sample; development metrics do not demonstrate alpha."
        ),
        "folds": best_xgb["fold_metrics"],
        "logistic_folds": best_logistic["fold_metrics"],
        "fold_summary": best_xgb["summary"],
        "logistic_fold_summary": best_logistic["summary"],
        "model_selection_rule": (
            "Mean defined training-fold ROC-AUC, then mean PR-AUC, then lower Brier; "
            "undefined AUC folds remain reported, all-undefined ranking falls back to Brier."
        ),
        "selected_hyperparameters": best_xgb["parameters"],
        "threshold": policy["candidate_threshold"],
        "partitions": {},
    }
    for name, mask in [("train", training_mask), ("validation", validation_mask)]:
        y = development.loc[mask, "y_revert_success"].astype(int)
        metrics["partitions"][name] = {
            "logistic": predictive_metrics(
                y, predictions.loc[mask, "logistic_probability"], policy["candidate_threshold"]
            ),
            "xgboost_raw": predictive_metrics(
                y, predictions.loc[mask, "raw_probability"], policy["candidate_threshold"]
            ),
            "xgboost_calibrated": predictive_metrics(
                y, predictions.loc[mask, "calibrated_probability"], policy["candidate_threshold"]
            ),
            "role": "TRAINING_RESUBSTITUTION"
            if name == "train"
            else "RAW_VALIDATION_HOLDOUT; CALIBRATED_VALIDATION_FIT_DESCRIPTIVE",
        }
    slices: dict[str, Any] = {}
    for group in ["pair_id", "sector", "divergence_sign"]:
        if group not in development:
            continue
        slices[group] = {
            str(value): predictive_metrics(
                development.loc[index, "y_revert_success"].astype(int),
                predictions.loc[index, "calibrated_probability"],
                policy["candidate_threshold"],
            )
            for value, index in development.loc[policy_mask].groupby(group).groups.items()
        }
    slices["year"] = {
        str(year): predictive_metrics(
            development.loc[index, "y_revert_success"].astype(int),
            predictions.loc[index, "calibrated_probability"],
            policy["candidate_threshold"],
        )
        for year, index in development.loc[validation_mask]
        .groupby(pd.to_datetime(development.loc[validation_mask, "event_timestamp"]).dt.year)
        .groups.items()
    }
    metrics["validation_slices"] = slices
    if "vix_level" in matrix:
        lower, upper = (float(value) for value in x_train["vix_level"].quantile([0.25, 0.75]))
        metadata["market_stress_slice_training_vix_quantiles"] = [lower, upper]
        stress = pd.Series(
            np.where(
                matrix["vix_level"] < lower,
                "LOW",
                np.where(matrix["vix_level"] > upper, "HIGH", "MIDDLE"),
            ),
            index=development.index,
        )
        slices["market_stress"] = {
            str(group): predictive_metrics(
                development.loc[index, "y_revert_success"].astype(int),
                predictions.loc[index, "calibrated_probability"],
                policy["candidate_threshold"],
            )
            for group, index in development.loc[validation_mask]
            .groupby(stress[validation_mask])
            .groups.items()
        }
    coefficients = logistic.named_steps["classifier"].coef_[0]
    names = logistic.named_steps["preprocessor"].get_feature_names_out()
    metrics["logistic_coefficients"] = {
        str(name): float(value) for name, value in zip(names, coefficients, strict=True)
    }
    ablations: dict[str, Any] = {}
    for name, families in [
        ("A0", {"spread", "relationship"}),
        ("A1", {"spread", "relationship", "market"}),
    ]:
        selected = [
            item["name"] for item in feature_schema["columns"] if item.get("family") in families
        ]
        if not selected:
            continue
        fitted = _xgboost(best_xgb["parameters"], settings.seed)
        fitted.fit(x_train[selected], y_train)
        p = fitted.predict_proba(matrix.loc[validation_mask, selected])[:, 1]
        ablations[name] = predictive_metrics(
            development.loc[validation_mask, "y_revert_success"].astype(int),
            p,
            policy["candidate_threshold"],
        )
    ablations["A2"] = metrics["partitions"]["validation"]["xgboost_raw"]
    metrics["raw_validation_feature_ablations"] = ablations
    metrics["global_mean_abs_shap_validation"] = {
        name: float(value)
        for name, value in zip(
            columns,
            np.abs(np.asarray(predictions.loc[validation_mask, "shap_values"].tolist())).mean(
                axis=0
            ),
            strict=True,
        )
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {
        "xgb_model.json": bytes(model.get_booster().save_raw(raw_format="json")),
        "logistic_pipeline.joblib": _joblib_bytes(logistic),
        "platt_calibrator.joblib": _joblib_bytes(calibrator),
        "platt_calibrator.json": _json_bytes(calibrator.__dict__),
        "feature_schema.json": _json_bytes(feature_schema),
        "label_policy.json": _json_bytes(
            label_policy
            or {
                "version": settings.label_policy_version,
                "entry_z": 2.0,
                "success_z": 0.5,
                "stop_z": 3.0,
                "max_horizon_sessions": 10,
                "outcome_parameters": "Frozen event-entry relationship for complete forward path",
            }
        ),
        "ml_policy.json": _json_bytes(policy),
        "metadata.json": _json_bytes(metadata),
        "metrics.json": _json_bytes(metrics),
        "search_scores.json": _json_bytes(search),
        "split_policy.json": _json_bytes(
            {
                "train": settings.train.model_dump(mode="json"),
                "validation": settings.validation.model_dump(mode="json"),
                "final_test": settings.final_test.model_dump(mode="json"),
                "embargo_days": settings.embargo_days,
                "calibration": "2022-2023",
                "policy_selection": "PREDECLARED_SMALL_SAMPLE",
            }
        ),
        "shap_background.parquet": background.to_parquet(index=False),
        "development_predictions.parquet": predictions.to_parquet(index=False),
        "model_card.json": _json_bytes(
            {
                "family": "Model A quantitative XGBoost",
                "benchmark": "L2 logistic same information",
                "calibration": calibrator.__dict__,
                "limits": metrics["sample_limitations"],
                "explanations": "Tree SHAP raw margins; association, not causation.",
                "final_test_locked": True,
                **metadata,
            }
        ),
    }
    for filename, contents in files.items():
        write_bytes(output_directory / filename, contents)
    # Local reproducibility does not require MLflow usage telemetry or tracing.
    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
    import mlflow

    tracking = (tracking_directory or output_directory.parent / "mlflow").resolve()
    tracking.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{(tracking / 'tracking.sqlite').as_posix()}")
    experiment = mlflow.get_experiment_by_name("structural-break-model-a")
    experiment_id = (
        experiment.experiment_id
        if experiment is not None
        else mlflow.create_experiment(
            "structural-break-model-a", artifact_location=(tracking / "artifacts").as_uri()
        )
    )
    mlflow.set_experiment(experiment_id=experiment_id)
    with mlflow.start_run(run_name=model_version) as tracked_run:
        mlflow.log_params(
            {
                "dataset_version": dataset_version,
                "feature_schema_version": feature_schema["version"],
                "seed": settings.seed,
                "search_trials": search_trials,
                "calibration": "2022-2023_sigmoid",
                "policy_selection": "PREDECLARED_SMALL_SAMPLE",
                **{f"selected_{key}": value for key, value in best_xgb["parameters"].items()},
            }
        )
        mlflow.log_metrics(
            {
                "n_training": float(training_mask.sum()),
                "n_calibration": float(calibration_mask.sum()),
                "n_policy": float(policy_mask.sum()),
                "candidate_threshold": float(policy["candidate_threshold"]),
            }
        )
        for filename in ["search_scores.json", "metrics.json", "model_card.json", "ml_policy.json"]:
            mlflow.log_artifact(str(output_directory / filename))
        tracking_id = tracked_run.info.run_id
    manifest = {
        "model_version": model_version,
        "dataset_version": dataset_version,
        "feature_schema_version": feature_schema["version"],
        "calibrator_version": calibrator_version,
        "ml_policy_version": policy_version,
        "mlflow_run_id": tracking_id,
        "final_test_locked": True,
        "files": {
            filename: hashlib.sha256(contents).hexdigest() for filename, contents in files.items()
        },
    }
    write_bytes(output_directory / "bundle_manifest.json", _json_bytes(manifest))
    return TrainingResult(bundle, metrics, predictions, manifest)


def load_bundle(directory: Path) -> ModelBundle:
    """Verify immutable bundle components before loading executable model objects."""
    manifest = json.loads((directory / "bundle_manifest.json").read_text(encoding="utf-8"))
    for filename, expected in manifest["files"].items():
        path = (directory / filename).resolve()
        if path.parent != directory.resolve() or sha256_file(path) != expected:
            raise ValueError(f"Model bundle file checksum mismatch: {filename}")
    schema = json.loads((directory / "feature_schema.json").read_text(encoding="utf-8"))
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if hashlib.sha256(_json_bytes(schema)).hexdigest() != metadata["feature_schema_sha256"]:
        raise ValueError("Feature schema differs from the fitted bundle")
    model = XGBClassifier()
    model.load_model(directory / "xgb_model.json")
    logistic = joblib.load(directory / "logistic_pipeline.joblib")
    calibrator = joblib.load(directory / "platt_calibrator.joblib")
    if not isinstance(calibrator, SigmoidCalibrator):
        raise ValueError("Saved calibrator has an unexpected type")
    policy = json.loads((directory / "ml_policy.json").read_text(encoding="utf-8"))
    background = validate_features(pd.read_parquet(directory / "shap_background.parquet"), schema)
    if metadata["model_version"] != manifest["model_version"]:
        raise ValueError("Bundle model version mismatch")
    return ModelBundle(model, logistic, calibrator, schema, policy, background, metadata)

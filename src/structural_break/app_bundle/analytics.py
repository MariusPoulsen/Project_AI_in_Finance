"""Descriptive presentation tables computed from stored predictions and saved models.

Nothing here fits, tunes or recalibrates a model. Curves summarise already
published assessment predictions. Explanations decompose the saved native models'
own margins exactly (they are checked to add back up to the stored margin).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.metrics import precision_recall_curve, roc_curve

from structural_break.app_bundle.contracts import EXPLAINED_VARIANTS, FAMILIES, VARIANTS
from structural_break.app_bundle.features import feature_block, feature_label, one_hot_value
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.research.evaluation import ResearchModel

EVENT_COLUMNS = (
    "event_id",
    "event_date",
    "pair_id",
    "leg_a",
    "leg_b",
    "sector",
    "business_group",
    "baseline1_eligible",
    "research_partition",
    "y_revert_success",
)
CONTEXT_COLUMNS = (
    "z_signed",
    "abs_z",
    "coint_pvalue",
    "half_life",
    "beta_abs",
    "vix_level",
    "sec_a_days_since_latest_8k",
    "sec_b_days_since_latest_8k",
    "sec_a_metadata_coverage_unknown",
    "sec_b_metadata_coverage_unknown",
    "sentiment_a_net",
    "sentiment_b_net",
    "sentiment_both_known",
    "evidence_available",
    "extraction_confidence",
)
CATALYST_GROUPS = ("event_type", "direction", "materiality", "affected_leg")
CURVE_POINTS = 120
RELIABILITY_BINS = 10
MARGIN_TOLERANCE = {"logistic": 1e-8, "xgboost": 1e-4}


def model_key(family: str, variant: str) -> str:
    return f"{family}_{variant}"


def events_table(predictions: pd.DataFrame, model_inputs: pd.DataFrame | None) -> pd.DataFrame:
    """Slim event rows: identity, partition, development target and stored probabilities."""
    columns = [name for name in EVENT_COLUMNS if name in predictions]
    for family in FAMILIES:
        for variant in VARIANTS:
            for kind in ("raw", "calibrated"):
                name = f"{model_key(family, variant)}_{kind}"
                if name in predictions and (kind == "calibrated" or variant in EXPLAINED_VARIANTS):
                    columns.append(name)
    rows = predictions.loc[:, columns].copy()
    rows["event_date"] = pd.to_datetime(rows["event_date"]).dt.date
    if model_inputs is not None and len(model_inputs):
        context = [name for name in CONTEXT_COLUMNS if name in model_inputs]
        one_hot = tuple(
            name
            for name in EVENT_FEATURE_NAMES
            if name in model_inputs and name not in context and name.startswith(CATALYST_GROUPS)
        )
        extra = model_inputs.loc[:, ["event_id", *context, *one_hot]].copy()
        records: list[dict[str, object]] = (
            [
                {str(k): v for k, v in r.items()}
                for r in extra.loc[:, list(one_hot)].to_dict("records")
            ]
            if one_hot
            else []
        )
        for group in CATALYST_GROUPS:
            column = f"catalyst_{group}"
            extra[column] = (
                [one_hot_value(record, group, one_hot) for record in records]
                if one_hot
                else "UNKNOWN"
            )
        extra = extra.drop(columns=list(one_hot))
        rows = rows.merge(extra, on="event_id", how="left", validate="one_to_one")
    for name in rows.columns:
        if rows[name].dtype == "float64":
            rows[name] = rows[name].astype("float32")
    return rows.reset_index(drop=True)


def _thin(x: np.ndarray[Any, Any], y: np.ndarray[Any, Any]) -> tuple[Any, Any]:
    if len(x) <= CURVE_POINTS:
        return x, y
    keep = np.unique(np.linspace(0, len(x) - 1, CURVE_POINTS).round().astype(int))
    return x[keep], y[keep]


def model_curves(predictions: pd.DataFrame) -> pd.DataFrame:
    """ROC, precision–recall and equal-count reliability curves on assessment rows."""
    rows = predictions.loc[predictions["research_partition"].eq("assessment")]
    if rows.empty:
        return pd.DataFrame(columns=["family", "variant", "kind", "x", "y", "n"])
    y = rows["y_revert_success"].to_numpy(dtype=int)
    output: list[dict[str, Any]] = []
    for family in FAMILIES:
        for variant in VARIANTS:
            name = model_key(family, variant) + "_calibrated"
            if name not in rows:
                continue
            p = rows[name].to_numpy(dtype=float)
            if len(np.unique(y)) == 2:
                fpr, tpr, _ = roc_curve(y, p)
                for x_value, y_value in zip(*_thin(fpr, tpr), strict=True):
                    output.append(
                        {"kind": "roc", "x": float(x_value), "y": float(y_value), "n": len(y)}
                    )
                    output[-1].update(family=family, variant=variant)
                precision, recall, _ = precision_recall_curve(y, p)
                order = np.argsort(recall)
                for x_value, y_value in zip(*_thin(recall[order], precision[order]), strict=True):
                    output.append(
                        {"kind": "pr", "x": float(x_value), "y": float(y_value), "n": len(y)}
                    )
                    output[-1].update(family=family, variant=variant)
            bins = pd.qcut(pd.Series(p).rank(method="first"), RELIABILITY_BINS, labels=False)
            frame = pd.DataFrame({"p": p, "y": y, "bin": bins.to_numpy()})
            for _, group in frame.groupby("bin"):
                output.append(
                    {
                        "family": family,
                        "variant": variant,
                        "kind": "reliability",
                        "x": float(group["p"].mean()),
                        "y": float(group["y"].mean()),
                        "n": len(group),
                    }
                )
    return pd.DataFrame(output, columns=["family", "variant", "kind", "x", "y", "n"])


def _logistic_contributions(
    model: ResearchModel, values: pd.DataFrame
) -> tuple[np.ndarray[Any, Any], float]:
    """Coefficient × transformed value; transforms are the pipeline's own fitted steps."""
    estimator = model.estimator
    transformed: Any = values
    if hasattr(estimator, "steps"):
        for _, step in estimator.steps[:-1]:
            transformed = step.transform(transformed)
        classifier = estimator.steps[-1][1]
    else:
        classifier = estimator
    coefficients = np.asarray(classifier.coef_, dtype=float).reshape(-1)
    intercept = float(np.asarray(classifier.intercept_).reshape(-1)[0])
    return np.asarray(transformed, dtype=float) * coefficients, intercept


def _coefficients(model: ResearchModel) -> np.ndarray[Any, Any]:
    estimator = model.estimator
    classifier = estimator.steps[-1][1] if hasattr(estimator, "steps") else estimator
    return np.asarray(classifier.coef_, dtype=float).reshape(-1)


def _tree_contributions(
    model: ResearchModel, values: pd.DataFrame
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    import xgboost

    matrix = xgboost.DMatrix(values, feature_names=list(model.columns))
    raw = np.asarray(model.estimator.get_booster().predict(matrix, pred_contribs=True), float)
    return raw[:, :-1], raw[:, -1]


def explain_models(
    model_inputs: pd.DataFrame,
    models: dict[str, ResearchModel],
    event_ids: Iterable[str],
    *,
    importance_ids: Iterable[str],
    top_k: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Exact additive margin decompositions of the saved native models.

    Logistic: coefficient × standardised (imputed) value, i.e. linear SHAP with
    the fitting-period mean as baseline. XGBoost: native TreeSHAP contributions.
    Each decomposition must reproduce the stored model margin.
    """
    importance_set = set(importance_ids)
    wanted = set(event_ids) | importance_set
    inputs = model_inputs.set_index("event_id", drop=False)
    explained = inputs.loc[inputs.index.isin(wanted)]
    long_rows: list[pd.DataFrame] = []
    totals: list[pd.DataFrame] = []
    importance: list[dict[str, Any]] = []
    for key, model in models.items():
        family, variant = key.split("_", 1)
        values = explained.loc[:, list(model.columns)].astype(float)
        if values.empty:
            continue
        if family == "logistic":
            contributions, intercept = _logistic_contributions(model, values)
            base = np.full(len(values), intercept)
            signed = dict(zip(model.columns, _coefficients(model), strict=True))
        else:
            contributions, base = _tree_contributions(model, values)
            signed = {}
        margins = np.asarray(model.margins(explained), dtype=float)
        reconstructed = base + contributions.sum(axis=1)
        if float(np.max(np.abs(reconstructed - margins))) > MARGIN_TOLERANCE[family]:
            raise ValueError(f"Explanation of {key} does not reproduce the saved model margin")
        calibrated = np.asarray(model.calibrator.predict(margins), dtype=float)
        order = np.argsort(-np.abs(contributions), axis=1)[:, :top_k]
        rows = np.repeat(np.arange(len(values)), order.shape[1])
        columns = order.reshape(-1)
        chosen = contributions[rows, columns]
        long_rows.append(
            pd.DataFrame(
                {
                    "event_id": explained["event_id"].to_numpy()[rows],
                    "model": key,
                    "feature": np.asarray(model.columns)[columns],
                    "value": values.to_numpy(dtype=float)[rows, columns].astype("float32"),
                    "contribution": chosen.astype("float32"),
                }
            )
        )
        top_sum = np.take_along_axis(contributions, order, axis=1).sum(axis=1)
        totals.append(
            pd.DataFrame(
                {
                    "event_id": explained["event_id"].to_numpy(),
                    "model": key,
                    "base": base,
                    "other": margins - base - top_sum,
                    "margin": margins,
                    "raw_probability": expit(margins),
                    "calibrated_probability": calibrated,
                }
            )
        )
        # Global importance summarises the out-of-sample assessment rows only.
        mask = explained["event_id"].isin(importance_set).to_numpy()
        if not mask.any():
            mask = np.ones(len(explained), dtype=bool)
        absolute = np.abs(contributions[mask]).mean(axis=0)
        mean_signed = contributions[mask].mean(axis=0)
        for index, feature in enumerate(model.columns):
            importance.append(
                {
                    "family": family,
                    "variant": variant,
                    "feature": feature,
                    "label": feature_label(feature),
                    "block": feature_block(feature),
                    "mean_abs_contribution": float(absolute[index]),
                    "mean_contribution": float(mean_signed[index]),
                    "coefficient": float(signed[feature]) if feature in signed else None,
                }
            )
    long_frame = (
        pd.concat(long_rows, ignore_index=True)
        if long_rows
        else pd.DataFrame(columns=["event_id", "model", "feature", "value", "contribution"])
    )
    total_frame = (
        pd.concat(totals, ignore_index=True)
        if totals
        else pd.DataFrame(
            columns=[
                "event_id",
                "model",
                "base",
                "other",
                "margin",
                "raw_probability",
                "calibrated_probability",
            ]
        )
    )
    return long_frame, total_frame, pd.DataFrame(importance)


def feature_profile(model_inputs: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Yearly distribution summaries for drift monitoring; never row-level values."""
    years = pd.to_datetime(model_inputs["event_date"]).dt.year
    output: list[dict[str, Any]] = []
    for name in dict.fromkeys(columns):
        if name not in model_inputs:
            continue
        values = pd.to_numeric(model_inputs[name], errors="coerce")
        for year, group in values.groupby(years):
            known = group.dropna()
            quantiles = (
                known.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).to_numpy()
                if len(known)
                else np.full(5, np.nan)
            )
            output.append(
                {
                    "feature": name,
                    "label": feature_label(name),
                    "block": feature_block(name),
                    "year": int(year),
                    "n": len(group),
                    "missing_share": float(group.isna().mean()) if len(group) else np.nan,
                    "mean": float(known.mean()) if len(known) else np.nan,
                    "p05": quantiles[0],
                    "p25": quantiles[1],
                    "p50": quantiles[2],
                    "p75": quantiles[3],
                    "p95": quantiles[4],
                }
            )
    return pd.DataFrame(output)

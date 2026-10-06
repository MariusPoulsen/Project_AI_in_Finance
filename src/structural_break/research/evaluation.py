"""Matched forward tuning, independent calibration and paired development assessment."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from structural_break.ml.model import fit_sigmoid, predictive_metrics
from structural_break.research.protocol import ResearchProtocol, partition_rows


@dataclass
class ResearchModel:
    columns: tuple[str, ...]
    estimator: Any
    calibrator: Any
    family: str

    def margins(self, rows: pd.DataFrame) -> Any:
        values = rows.loc[:, self.columns].astype(float)
        if self.family == "logistic":
            return self.estimator.decision_function(values)
        return self.estimator.predict(values, output_margin=True)

    def predict(self, rows: pd.DataFrame) -> Any:
        return self.calibrator.predict(self.margins(rows))


@dataclass
class ResearchEvaluation:
    predictions: pd.DataFrame
    report: dict[str, Any]
    models: dict[str, bytes]


def _estimator(family: str, parameters: dict[str, int | float], seed: int) -> Any:
    if family == "logistic":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scale", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(C=parameters["C"], max_iter=3000, random_state=seed),
                ),
            ]
        )
    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=1,
        random_state=seed,
        **parameters,
    )


def _raw(estimator: Any, rows: pd.DataFrame, columns: tuple[str, ...]) -> Any:
    return estimator.predict_proba(rows.loc[:, columns].astype(float))[:, 1]


def _metrics(rows: pd.DataFrame, values: Any, threshold: float) -> dict[str, Any]:
    return predictive_metrics(rows["y_revert_success"].to_numpy(dtype=int), values, threshold)


def _weighted_losses(rows: pd.DataFrame, a: Any, b: Any) -> dict[str, Any]:
    y = rows["y_revert_success"].to_numpy(dtype=float)
    result: dict[str, Any] = {}
    counts = rows["pair_id"].value_counts()
    weights = 1.0 / rows["pair_id"].map(counts).to_numpy(dtype=float)
    result["pair_balanced_brier"] = {
        "A": float(np.average((a - y) ** 2, weights=weights)),
        "B": float(np.average((b - y) ** 2, weights=weights)),
    }
    issuers = pd.concat([rows["leg_a"], rows["leg_b"]]).value_counts()
    weights = (
        1.0 / rows["leg_a"].map(issuers).to_numpy(dtype=float)
        + 1.0 / rows["leg_b"].map(issuers).to_numpy(dtype=float)
    ) / 2
    result["issuer_balanced_brier"] = {
        "A": float(np.average((a - y) ** 2, weights=weights)),
        "B": float(np.average((b - y) ** 2, weights=weights)),
    }
    return result


def paired_assessment(
    rows: pd.DataFrame, a: Any, b: Any, protocol: ResearchProtocol
) -> dict[str, Any]:
    """Sample complete calendar quarters, retaining all shared-issuer events.

    This is a temporal block sensitivity, not an assertion of eight independent
    blocks or an issuer-bootstrap confidence interval. Empty quarters are not
    invented. Both model losses always use identical row multiplicities.
    """
    if not len(rows) or len(a) != len(rows) or len(b) != len(rows):
        raise ValueError("Paired assessment requires nonempty aligned probabilities")
    y = rows["y_revert_success"].to_numpy(dtype=float)
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Invalid paired probabilities")
    if not np.isin(y, [0, 1]).all() or ((a < 0) | (a > 1) | (b < 0) | (b > 1)).any():
        raise ValueError("Paired targets/probabilities are outside their contract")
    losses = (b - y) ** 2 - (a - y) ** 2
    dates = pd.to_datetime(rows["event_date"])
    quarters = dates.dt.to_period("Q").astype(str).to_numpy()
    groups = [np.flatnonzero(quarters == q) for q in sorted(set(quarters))]
    rng = np.random.default_rng(protocol.seed)
    samples = np.empty(protocol.bootstrap_replicates)
    for number in range(protocol.bootstrap_replicates):
        indices = np.concatenate(
            [groups[int(i)] for i in rng.integers(0, len(groups), len(groups))]
        )
        samples[number] = float(losses[indices].mean())
    interval = [float(value) for value in np.quantile(samples, [0.025, 0.975])]
    difference = float(losses.mean())
    slices: dict[str, Any] = {}
    for name, values in (
        ("year", dates.dt.year.astype(str)),
        ("sector", rows["sector"].astype(str)),
        ("ACTIVE", rows["baseline1_eligible"].astype(str)),
    ):
        slices[name] = {}
        for value in sorted(set(values)):
            mask = values.eq(value).to_numpy()
            slices[name][value] = {
                "n": int(mask.sum()),
                "positives": int(y[mask].sum()),
                "brier_delta_B_minus_A": float(losses[mask].mean()),
            }
    return {
        "brier_delta_B_minus_A": difference,
        "quarter_block_percentile_interval_95": interval,
        "observed_quarter_blocks": len(groups),
        "resamples": protocol.bootstrap_replicates,
        "seed": protocol.seed,
        "point_estimate_improves": difference < 0,
        "interval_below_zero": interval[1] < 0,
        "uncertainty_limit": (
            "Few temporal blocks; shared issuers and cross-quarter dependence remain"
        ),
        **_weighted_losses(rows, a, b),
        "slices": slices,
    }


def evaluate_matched_models(
    rows: pd.DataFrame,
    quantitative_columns: tuple[str, ...],
    extra_blocks: dict[str, tuple[str, ...]],
    protocol: ResearchProtocol,
) -> ResearchEvaluation:
    """B imputes missing text on A's cohort; it cannot drop unfavorable UNKNOWNs."""
    if rows["event_id"].duplicated().any():
        raise ValueError("Duplicate observations in matched research registry")
    required = {
        "event_id",
        "event_date",
        "horizon_end_date",
        "supervised_eligible",
        "y_revert_success",
        "pair_id",
        "leg_a",
        "leg_b",
        "sector",
        "baseline1_eligible",
    }
    if not required <= set(rows):
        raise ValueError("Research observation registry is incomplete")
    if "both" not in extra_blocks or not quantitative_columns:
        raise ValueError("Predeclared primary quantitative/B-both features are absent")
    forbidden = required | {
        "outcome_type",
        "resolution_date",
        "partition",
        "research_partition",
        "time_to_resolution",
        "max_adverse_z",
        "max_favourable_z",
        "censor_reason",
        "label_eligible",
        "exclusion_reason",
        "gross_pair_return",
        "net_pair_return",
        "event_timestamp",
        "feature_cutoff_timestamp",
        "data_available_at",
        "evidence_available_at",
        "entry_z",
        "ticker",
        "company_name",
    }
    columns_by_variant = {
        "A": quantitative_columns,
        **{f"B_{name}": (*quantitative_columns, *cols) for name, cols in extra_blocks.items()},
    }
    for columns in columns_by_variant.values():
        if len(set(columns)) != len(columns) or forbidden.intersection(columns):
            raise ValueError("Outcome/identity metadata or duplicate field entered predictors")
        if (
            not set(columns) <= set(rows)
            or np.isinf(rows.loc[:, columns].to_numpy(dtype=float)).any()
        ):
            raise ValueError("Research features are absent, nonnumeric or infinite")
    data = partition_rows(rows, protocol)
    eligible = data["supervised_eligible"].eq(True)
    supervised = data.loc[eligible & data["research_partition"].ne("excluded")].copy()
    if not supervised["y_revert_success"].isin([0, 1]).all():
        raise ValueError("Eligible observations must have binary targets")
    subsets = {
        p: supervised.loc[supervised["research_partition"].eq(p)].copy()
        for p in ("fit", "calibration", "assessment")
    }
    if (
        any(frame.empty for frame in subsets.values())
        or subsets["fit"]["y_revert_success"].nunique() < 2
    ):
        raise ValueError("Matched fitting needs two classes and nonempty calibration/assessment")
    report: dict[str, Any] = {
        "protocol": protocol.model_dump(mode="json"),
        "final_test_read": False,
        "all_quantitative_events_retained": True,
        "cohorts": {},
        "models": {},
    }
    for name, frame in subsets.items():
        report["cohorts"][name] = {
            "n": len(frame),
            "positives": int(frame["y_revert_success"].sum()),
            "pairs": frame["pair_id"].nunique(),
            "issuers": len(set(frame["leg_a"]) | set(frame["leg_b"])),
            "ACTIVE": int(frame["baseline1_eligible"].sum()),
        }
    report["excluded_registry_rows"] = len(rows) - len(supervised)
    coverage_columns = [
        name
        for name in supervised
        if name.endswith("metadata_coverage_unknown")
        or name in {"sentiment_both_known", "event_type_UNKNOWN", "event_type_NONE"}
    ]
    report["text_coverage"] = {}
    for period, frame in subsets.items():
        report["text_coverage"][period] = {
            "n": len(frame),
            "flags": {
                name: {
                    "ones": int(frame[name].eq(1).sum()),
                    "missing": int(frame[name].isna().sum()),
                }
                for name in coverage_columns
            },
            "yearly": {
                str(year): {
                    "n": len(group),
                    "flags": {name: int(group[name].eq(1).sum()) for name in coverage_columns},
                }
                for year, group in frame.groupby(pd.to_datetime(frame["event_date"]).dt.year)
            },
        }
    fit, calibration, assessment = (subsets[p] for p in ("fit", "calibration", "assessment"))
    prediction_columns = [
        "event_id",
        "event_date",
        "pair_id",
        "leg_a",
        "leg_b",
        "sector",
        "baseline1_eligible",
        "research_partition",
        "y_revert_success",
    ]
    predictions = supervised.loc[:, prediction_columns].copy()
    prior = float(fit["y_revert_success"].mean())
    report["fitting_prevalence_baseline"] = {
        "probability": prior,
        "assessment": _metrics(
            assessment, np.full(len(assessment), prior), protocol.candidate_threshold
        ),
    }
    artifacts: dict[str, bytes] = {}
    for family in ("logistic", "xgboost"):
        report["models"][family] = {}
        for name, columns in columns_by_variant.items():
            grid = (
                [{"C": c} for c in protocol.logistic_c]
                if family == "logistic"
                else list(protocol.xgb_candidates)
            )
            scores: list[dict[str, Any]] = []
            for params in grid:
                fold_scores: list[dict[str, Any]] = []
                for year in protocol.tuning_years:
                    boundary = date(year, 1, 1)
                    previous = fit.loc[pd.to_datetime(fit["horizon_end_date"]).dt.date.lt(boundary)]
                    in_year = pd.to_datetime(fit["event_date"]).dt.year.eq(year)
                    validation = fit.loc[
                        in_year
                        & pd.to_datetime(fit["horizon_end_date"]).dt.date.le(date(year, 12, 31))
                    ]
                    if previous["y_revert_success"].nunique() < 2 or validation.empty:
                        fold_scores.append(
                            {"year": year, "brier": None, "reason": "EMPTY_OR_ONE_CLASS_FIT"}
                        )
                        continue
                    estimator = _estimator(family, params, protocol.seed)
                    estimator.fit(
                        previous.loc[:, columns].astype(float),
                        previous["y_revert_success"].astype(int),
                    )
                    metrics = _metrics(
                        validation,
                        _raw(estimator, validation, columns),
                        protocol.candidate_threshold,
                    )
                    fold_scores.append(
                        {
                            "year": year,
                            "brier": metrics["brier"],
                            "fit_n": len(previous),
                            "assessment_n": len(validation),
                            "purged_year_tail": int(in_year.sum()) - len(validation),
                        }
                    )
                defined = [s["brier"] for s in fold_scores if s["brier"] is not None]
                scores.append(
                    {
                        "parameters": params,
                        "folds": fold_scores,
                        "mean_brier": float(np.mean(defined)) if defined else None,
                    }
                )
            candidates = [s for s in scores if s["mean_brier"] is not None]
            if not candidates:
                raise ValueError("No usable predeclared forward tuning fold")
            chosen = min(candidates, key=lambda score: score["mean_brier"])
            estimator = _estimator(family, chosen["parameters"], protocol.seed)
            estimator.fit(fit.loc[:, columns].astype(float), fit["y_revert_success"].astype(int))
            temporary = ResearchModel(columns, estimator, None, family)
            calibrator = fit_sigmoid(
                temporary.margins(calibration), calibration["y_revert_success"].astype(int)
            )
            model = ResearchModel(columns, estimator, calibrator, family)
            raw = _raw(estimator, assessment, columns)
            calibrated = model.predict(assessment)
            buffer = io.BytesIO()
            joblib.dump(model, buffer)
            content = buffer.getvalue()
            reloaded: ResearchModel = joblib.load(io.BytesIO(content))
            error = float(np.max(np.abs(reloaded.predict(assessment) - calibrated)))
            if error > 1e-12:
                raise ValueError("Stored research model does not reproduce its predictions")
            key = f"{family}_{name}"
            artifacts[key] = content
            predictions[f"{key}_raw"] = _raw(estimator, supervised, columns)
            predictions[f"{key}_calibrated"] = model.predict(supervised)
            report["models"][family][name] = {
                "feature_columns": list(columns),
                "tuning": scores,
                "chosen_parameters": chosen["parameters"],
                "calibrator": vars(calibrator),
                "reload_max_error": error,
                "raw_assessment": _metrics(assessment, raw, protocol.candidate_threshold),
                "calibrated_assessment": _metrics(
                    assessment, calibrated, protocol.candidate_threshold
                ),
            }
        assessment_mask = predictions["research_partition"].eq("assessment")
        aligned = predictions.loc[assessment_mask]
        for name in columns_by_variant:
            if name == "A":
                continue
            report["models"][family][name]["paired_assessment"] = paired_assessment(
                aligned,
                aligned[f"{family}_A_calibrated"].to_numpy(),
                aligned[f"{family}_{name}_calibrated"].to_numpy(),
                protocol,
            )
    return ResearchEvaluation(predictions.reset_index(drop=True), report, artifacts)

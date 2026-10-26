"""Model B (R0): data loading, the Decision 45 walk-forward split and selection helpers.

R0 is the fixed Decision 45 XGBoost (``FIXED_XGB``). ``load_data`` joins the frozen
research model inputs with the walk-forward frame; ``rolling_split`` trains on label
windows that ended before Y-1 and returns the Y-1 threshold rows and the Y test rows;
``selections`` takes the top 20 % by the previous year's cut. The tuned variants of
Decision 65 were erased in the Decision 115 cleanup; their results stay in DECISIONS.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DECISION_YEARS = tuple(range(2010, 2022))
REFERENCE_YEARS = (2022, 2023)
TARGET = "y_revert_success"
MODEL_SEED = 42  # the Decision 45 estimator seed
K_FOLDS = 5
EMBARGO = pd.Timedelta(days=30)
TOP_SHARE = 0.20

FIXED_XGB = {
    "learning_rate": 0.03,
    "max_depth": 3,
    "min_child_weight": 20,
    "n_estimators": 400,
    "reg_lambda": 10,
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


# --------------------------------------------------------------------------- #
# Walk-forward split and inner folds
# --------------------------------------------------------------------------- #


def rolling_split(
    frame: pd.DataFrame, year: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The Decision 45 split: train before Y-1, threshold rows Y-1, test rows Y."""
    signal_year = pd.to_datetime(frame["event_date"]).dt.year
    window_end = pd.to_datetime(frame["horizon_end_date"])
    supervised = frame["supervised_eligible"].eq(True) & frame[TARGET].notna()
    train = frame.loc[supervised & window_end.lt(pd.Timestamp(year - 1, 1, 1))]
    return train, frame.loc[signal_year.eq(year - 1)], frame.loc[signal_year.eq(year)]


Fold = tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]


def _usable(train: pd.DataFrame, fit: np.ndarray[Any, Any], valid: np.ndarray[Any, Any]) -> bool:
    labels = train[TARGET].to_numpy()
    return bool(
        len(fit) and len(valid) and len(set(labels[fit])) == 2 and len(set(labels[valid])) == 2
    )


def purged_kfold(
    train: pd.DataFrame, folds: int = K_FOLDS, embargo: pd.Timedelta = EMBARGO
) -> list[Fold]:
    """Contiguous K-fold; drop fit rows whose label window overlaps the block, plus an embargo."""
    signal = pd.to_datetime(train["event_date"]).to_numpy()
    window_end = pd.to_datetime(train["horizon_end_date"]).to_numpy()
    order = np.lexsort((train["event_id"].astype(str).to_numpy(), signal))
    result = []
    for block in np.array_split(order, folds):
        start, stop = signal[block].min(), window_end[block].max()
        overlap = (signal <= stop) & (window_end >= start)
        embargoed = (signal > stop) & (signal <= stop + embargo.to_timedelta64())
        keep = ~(overlap | embargoed)
        keep[block] = False
        fit = np.flatnonzero(keep)
        valid = np.sort(block)
        if _usable(train, fit, valid):
            result.append((fit, valid))
    return result


# --------------------------------------------------------------------------- #
# Estimators and search spaces
# --------------------------------------------------------------------------- #


def log_loss(labels: np.ndarray[Any, Any], probabilities: np.ndarray[Any, Any]) -> float:
    p = np.clip(probabilities, 1e-12, 1 - 1e-12)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


# --------------------------------------------------------------------------- #
# Tasks: one (variant, model, year) per task, resumable
# --------------------------------------------------------------------------- #


def load_data(workspace: Path, simulation: Path) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    from structural_break.pipeline.sources import _sources, load_frame

    frame, report = load_frame(workspace, _sources(workspace).binding.evaluation.version)
    simulated = pd.read_parquet(simulation, columns=["event_id", "frozen|status", "frozen|net"])
    frame = frame.merge(simulated, on="event_id", how="inner", validate="one_to_one")
    columns = {
        "A": tuple(report["models"]["logistic"]["A"]["feature_columns"]),
        "B": tuple(report["models"]["logistic"]["B_both"]["feature_columns"]),
    }
    return frame.reset_index(drop=True), columns


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


def _logit(p: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return np.asarray(np.log(q / (1 - q)), dtype=float)


def selections(scored: pd.DataFrame) -> pd.Series:
    """Top-20 % rule: test score at least the 80th percentile of the Y-1 scores."""
    chosen = pd.Series(False, index=scored.index)
    for _, group in scored.groupby("year"):
        cut = float(np.quantile(group.loc[group["role"].eq("threshold"), "score"], 1 - TOP_SHARE))
        test = group["role"].eq("test")
        chosen.loc[group.index[test]] = group.loc[test, "score"].to_numpy() >= cut
    return chosen


def allocation(selected: pd.Series, status: pd.Series, net: pd.Series) -> pd.Series:
    result = pd.Series(0.0, index=selected.index)
    complete = selected & status.eq("COMPLETE")
    result[complete] = net[complete].astype(float)
    result[selected & ~status.eq("COMPLETE")] = np.nan
    return result


"""Pre-registered boosting tuning, model families and cross-validation (DECISIONS 65).

For every Decision 45 walk-forward year Y the training window (label windows
ending before Y-1) is tuned with Optuna, separately for each variant, using
only inner folds inside that window: forward-chaining folds purged by the label
horizon, or a purged K-fold with an embargo. The tuned model is refit on the
whole window and scores the Y-1 (threshold and calibration) and Y (test)
events. ``evaluate`` compares each variant with the fixed Decision 45 XGBoost
on calibrated Brier score and on top-20 % per-candidate net return under the
frozen exit. 2010-2021 decide; 2022-2023 are reference rows. The 2024-2025
final test is not read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PLAN_VERSION = "p6-boosting-tuning-v1"
DECISION_YEARS = tuple(range(2010, 2022))
REFERENCE_YEARS = (2022, 2023)
TARGET = "y_revert_success"
MODEL_SEED = 42  # the Decision 45 estimator seed
SEARCH_SEED = 5557
TRIALS = 30
STARTUP_TRIALS = 10
MAX_TREES = 1500
PATIENCE = 100
FORWARD_FOLDS = 4
K_FOLDS = 5
EMBARGO = pd.Timedelta(days=30)
TOP_SHARE = 0.20
ALPHA = 0.05
MIN_POSITIVE_YEARS = 8
DRAWS = 2000

REFERENCE = "R0_xgb_fixed"
FIXED_XGB = {
    "learning_rate": 0.03,
    "max_depth": 3,
    "min_child_weight": 20,
    "n_estimators": 400,
    "reg_lambda": 10,
}
# name -> (family, inner cross-validation, tuning objective)
TUNED = {
    "V1_xgb_forward": ("xgboost", "forward", "logloss"),
    "V2_xgb_purged_kfold": ("xgboost", "kfold", "logloss"),
    "V3_lgbm_forward": ("lightgbm", "forward", "logloss"),
    "V4_catboost_forward": ("catboost", "forward", "logloss"),
    "V6_xgb_forward_precision": ("xgboost", "forward", "precision"),
}
ENSEMBLE = "V5_ensemble"
ENSEMBLE_MEMBERS = ("V1_xgb_forward", "V3_lgbm_forward", "V4_catboost_forward")
VARIANTS = (*TUNED, ENSEMBLE)
MODELS = ("B", "A")


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


def forward_folds(train: pd.DataFrame, folds: int = FORWARD_FOLDS) -> list[Fold]:
    """Validate each of the last ``folds`` signal years on earlier, fully ended labels."""
    signal = pd.to_datetime(train["event_date"])
    window_end = pd.to_datetime(train["horizon_end_date"])
    years = sorted(signal.dt.year.unique())
    result = []
    for year in years[1:][-folds:]:
        fit = np.flatnonzero(window_end.lt(pd.Timestamp(year, 1, 1)).to_numpy())
        valid = np.flatnonzero(signal.dt.year.eq(year).to_numpy())
        if _usable(train, fit, valid):
            result.append((fit, valid))
    return result


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


def suggest(trial: Any, family: str) -> dict[str, Any]:
    if family == "xgboost":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "max_depth": trial.suggest_int("max_depth", 2, 6),
            "min_child_weight": trial.suggest_float("min_child_weight", 1, 100, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 100, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10, log=True),
            "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        }
    if family == "lightgbm":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 4, 64, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 400, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 100, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10, log=True),
        }
    if family == "catboost":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "depth": trial.suggest_int("depth", 3, 8),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1, 100, log=True),
            "random_strength": trial.suggest_float("random_strength", 1e-3, 10, log=True),
            "bagging_temperature": trial.suggest_float("bagging_temperature", 0.0, 2.0),
            "rsm": trial.suggest_float("rsm", 0.3, 1.0),
        }
    raise ValueError(f"Unknown family {family}")


def estimator(family: str, parameters: dict[str, Any], trees: int | None = None) -> Any:
    """Single-threaded, seeded estimator; ``trees`` None means early-stopping mode."""
    params = dict(parameters)
    if family == "xgboost":
        from xgboost import XGBClassifier

        if trees is not None:
            params["n_estimators"] = trees
        else:
            params |= {"n_estimators": MAX_TREES, "early_stopping_rounds": PATIENCE}
        return XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            n_jobs=1,
            random_state=MODEL_SEED,
            **params,
        )
    if family == "lightgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            n_estimators=trees or MAX_TREES,
            subsample_freq=1,
            n_jobs=1,
            random_state=MODEL_SEED,
            deterministic=True,
            force_row_wise=True,
            verbose=-1,
            **params,
        )
    if family == "catboost":
        from catboost import CatBoostClassifier

        extra = {} if trees is not None else {"od_type": "Iter", "od_wait": PATIENCE}
        return CatBoostClassifier(
            iterations=trees or MAX_TREES,
            loss_function="Logloss",
            bootstrap_type="Bayesian",
            thread_count=1,
            random_seed=MODEL_SEED,
            verbose=0,
            allow_writing_files=False,
            **extra,
            **params,
        )
    raise ValueError(f"Unknown family {family}")


def fit_early(
    family: str,
    parameters: dict[str, Any],
    x_fit: pd.DataFrame,
    y_fit: pd.Series,
    x_valid: pd.DataFrame,
    y_valid: pd.Series,
) -> tuple[np.ndarray[Any, Any], int]:
    """Fit with early stopping on the validation fold; return its probabilities and trees."""
    model = estimator(family, parameters)
    if family == "xgboost":
        model.fit(x_fit, y_fit, eval_set=[(x_valid, y_valid)], verbose=False)
        trees = int(model.best_iteration) + 1
    elif family == "lightgbm":
        import lightgbm

        model.fit(
            x_fit,
            y_fit,
            eval_set=[(x_valid, y_valid)],
            eval_metric="binary_logloss",
            callbacks=[lightgbm.early_stopping(PATIENCE, verbose=False)],
        )
        trees = int(model.best_iteration_ or MAX_TREES)
    else:
        model.fit(x_fit, y_fit, eval_set=(x_valid, y_valid), use_best_model=True)
        trees = int(model.get_best_iteration()) + 1
    return np.asarray(model.predict_proba(x_valid)[:, 1], dtype=float), trees


def top_share_precision(labels: np.ndarray[Any, Any], scores: np.ndarray[Any, Any]) -> float:
    cut = float(np.quantile(scores, 1.0 - TOP_SHARE))
    chosen = scores >= cut
    return float(labels[chosen].mean()) if chosen.any() else 0.0


def log_loss(labels: np.ndarray[Any, Any], probabilities: np.ndarray[Any, Any]) -> float:
    p = np.clip(probabilities, 1e-12, 1 - 1e-12)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


def tune(
    family: str,
    objective: str,
    x: pd.DataFrame,
    y: pd.Series,
    folds: list[Fold],
    trials: int = TRIALS,
) -> dict[str, Any]:
    """Optuna TPE over the inner folds; returns the best parameters and refit tree count."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    if not folds:
        raise ValueError("No usable inner fold")

    def score(trial: Any) -> float:
        parameters = suggest(trial, family)
        values, trees = [], []
        for fit, valid in folds:
            probabilities, best = fit_early(
                family, parameters, x.iloc[fit], y.iloc[fit], x.iloc[valid], y.iloc[valid]
            )
            labels = y.iloc[valid].to_numpy()
            if objective == "logloss":
                values.append(log_loss(labels, probabilities))
            else:
                values.append(-top_share_precision(labels, probabilities))
            trees.append(best)
        trial.set_user_attr("trees", trees)
        trial.set_user_attr("fold_scores", values)
        return float(np.mean(values))

    sampler = optuna.samplers.TPESampler(
        seed=SEARCH_SEED, n_startup_trials=min(STARTUP_TRIALS, trials)
    )
    study = optuna.create_study(direction="minimize", sampler=sampler)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        study.optimize(score, n_trials=trials)
    best = study.best_trial
    return {
        "parameters": best.params,
        "trees": max(1, int(round(float(np.mean(best.user_attrs["trees"]))))),
        "inner_score": float(best.value or 0.0),
        "inner_fold_scores": best.user_attrs["fold_scores"],
        "inner_folds": len(folds),
        "trials": [
            {"number": t.number, "value": t.value, "params": t.params} for t in study.trials
        ],
    }


# --------------------------------------------------------------------------- #
# Tasks: one (variant, model, year) per task, resumable
# --------------------------------------------------------------------------- #

_STATE: dict[str, Any] = {}


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


def _init(workspace: str, simulation: str) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    _STATE["frame"], _STATE["columns"] = load_data(Path(workspace), Path(simulation))


def task_name(variant: str, model: str, year: int) -> str:
    return f"{variant}__{model}__{year}"


def all_tasks() -> list[tuple[str, str, int]]:
    cost = {"catboost": 3.0, "xgboost": 1.0, "lightgbm": 1.0}
    tasks = [
        (variant, model, year)
        for variant in (REFERENCE, *TUNED)
        for model in MODELS
        for year in (*DECISION_YEARS, *REFERENCE_YEARS)
    ]

    def weight(task: tuple[str, str, int]) -> float:
        variant, _, year = task
        if variant == REFERENCE:
            return 0.0
        family, scheme, _ = TUNED[variant]
        return cost[family] * (K_FOLDS if scheme == "kfold" else FORWARD_FOLDS) * (year - 2005)

    return sorted(tasks, key=weight, reverse=True)


def run_task(
    frame: pd.DataFrame,
    columns: dict[str, tuple[str, ...]],
    variant: str,
    model: str,
    year: int,
    trials: int = TRIALS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.monotonic()
    train, threshold_rows, test = rolling_split(frame, year)
    train = train.reset_index(drop=True)
    features = list(columns[model])
    x, y = train.loc[:, features].astype(float), train[TARGET].astype(int)
    if variant == REFERENCE:
        family, trees = "xgboost", int(FIXED_XGB["n_estimators"])
        parameters = {k: v for k, v in FIXED_XGB.items() if k != "n_estimators"}
        meta: dict[str, Any] = {"parameters": FIXED_XGB, "trees": trees}
    else:
        family, scheme, objective = TUNED[variant]
        folds = forward_folds(train) if scheme == "forward" else purged_kfold(train)
        meta = tune(family, objective, x, y, folds, trials)
        parameters, trees = meta["parameters"], int(meta["trees"])
    fitted = estimator(family, parameters, trees)
    fitted.fit(x, y)
    rows = pd.concat([threshold_rows.assign(role="threshold"), test.assign(role="test")])
    scores = np.asarray(fitted.predict_proba(rows.loc[:, features].astype(float))[:, 1])
    output = pd.DataFrame(
        {
            "event_id": rows["event_id"].to_numpy(),
            "role": rows["role"].to_numpy(),
            "score": scores,
            "variant": variant,
            "model": model,
            "year": year,
        }
    )
    meta |= {
        "variant": variant,
        "model": model,
        "year": year,
        "family": family,
        "train_n": len(train),
        "seconds": round(time.monotonic() - started, 1),
        "plan_version": PLAN_VERSION,
    }
    return output, meta


def _worker(task: tuple[str, str, int], folder: str, trials: int) -> str:
    variant, model, year = task
    scores, meta = run_task(_STATE["frame"], _STATE["columns"], variant, model, year, trials)
    name = task_name(variant, model, year)
    target = Path(folder)
    scores.to_parquet(target / f".{name}.parquet.tmp", index=False)
    os.replace(target / f".{name}.parquet.tmp", target / f"{name}.parquet")
    (target / f".{name}.json.tmp").write_text(json.dumps(meta, indent=1, default=str))
    os.replace(target / f".{name}.json.tmp", target / f"{name}.json")
    return name


def pending(output: Path) -> list[tuple[str, str, int]]:
    folder = output / "tasks"
    return [
        task
        for task in all_tasks()
        if not (folder / f"{task_name(*task)}.json").exists()
        or not (folder / f"{task_name(*task)}.parquet").exists()
    ]


def run(workspace: Path, simulation: Path, output: Path, workers: int, trials: int = TRIALS) -> int:
    folder = output / "tasks"
    folder.mkdir(parents=True, exist_ok=True)
    todo = pending(output)
    total = len(all_tasks())
    print(f"{_now()} {len(todo)} of {total} tasks to run on {workers} workers", flush=True)
    done = total - len(todo)
    with ProcessPoolExecutor(
        workers, initializer=_init, initargs=(str(workspace), str(simulation))
    ) as pool:
        jobs = {pool.submit(_worker, task, str(folder), trials): task for task in todo}
        for job in as_completed(jobs):
            name = job.result()
            done += 1
            print(f"{_now()} finished {name} ({done}/{total})", flush=True)
    (output / "run_done").write_text(_now())
    return len(todo)


def status(output: Path) -> str:
    folder = output / "tasks"
    total = len(all_tasks())
    metas = [json.loads(p.read_text()) for p in folder.glob("*.json")] if folder.exists() else []
    seconds = sum(m.get("seconds", 0.0) for m in metas)
    by_variant: dict[str, int] = {}
    for meta in metas:
        by_variant[meta["variant"]] = by_variant.get(meta["variant"], 0) + 1
    lines = [
        f"Boosting tuning: {len(metas)} / {total} tasks done"
        f" ({'finished' if (output / 'run_done').exists() else 'running or stopped'}),"
        f" {seconds / 3600:.1f} CPU-hours used",
    ]
    per = len(MODELS) * (len(DECISION_YEARS) + len(REFERENCE_YEARS))
    for variant in (REFERENCE, *TUNED):
        lines.append(f"  {variant:28s} {by_variant.get(variant, 0):3d} / {per}")
    if (output / "evaluation.json").exists():
        lines.append("  evaluation.json written")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


def bootstrap(difference: np.ndarray[Any, Any], months: np.ndarray[Any, Any]) -> dict[str, Any]:
    """Mean with calendar-month block resampling: interval and one-sided p (> 0)."""
    labels = sorted(set(months.tolist()))
    index = {label: i for i, label in enumerate(labels)}
    blocks = np.array([index[m] for m in months.tolist()])
    sums = np.bincount(blocks, weights=difference, minlength=len(labels))
    counts = np.bincount(blocks, minlength=len(labels)).astype(float)
    rng = np.random.default_rng(SEARCH_SEED)
    sample = rng.integers(0, len(labels), (DRAWS, len(labels)))
    means = sums[sample].sum(axis=1) / np.maximum(counts[sample].sum(axis=1), 1)
    return {
        "estimate": float(difference.mean()),
        "interval_95": [float(v) for v in np.quantile(means, [0.025, 0.975])],
        "p_one_sided": float((means <= 0).mean()),
        "months": len(labels),
        "n": int(len(difference)),
    }


def holm(p_values: dict[str, float]) -> dict[str, float]:
    order = sorted(p_values, key=p_values.__getitem__)
    adjusted, running = {}, 0.0
    for rank, name in enumerate(order):
        running = min(1.0, max(running, (len(order) - rank) * p_values[name]))
        adjusted[name] = running
    return adjusted


def _logit(p: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return np.asarray(np.log(q / (1 - q)), dtype=float)


def assemble(frame: pd.DataFrame, output: Path) -> pd.DataFrame:
    """Raw scores plus Y-1-calibrated probabilities for every variant, model and year."""
    from structural_break.ml.model import fit_sigmoid

    parts = [pd.read_parquet(p) for p in sorted((output / "tasks").glob("*.parquet"))]
    scores = pd.concat(parts, ignore_index=True)
    info = frame.loc[:, ["event_id", "horizon_end_date", "supervised_eligible", TARGET]]
    scores = scores.merge(info, on="event_id", how="left", validate="many_to_one")
    calibrated = []
    for (_, _, year), group in scores.groupby(["variant", "model", "year"], sort=False):
        known = (
            group["role"].eq("threshold")
            & group["supervised_eligible"].eq(True)
            & group[TARGET].notna()
            & pd.to_datetime(group["horizon_end_date"]).lt(pd.Timestamp(int(str(year)), 1, 1))
        )
        calibrator = fit_sigmoid(
            _logit(group.loc[known, "score"].to_numpy()), group.loc[known, TARGET]
        )
        calibrated.append(
            pd.Series(calibrator.predict(_logit(group["score"].to_numpy())), index=group.index)
        )
    scores["probability"] = pd.concat(calibrated)
    members = scores.loc[scores["variant"].isin(ENSEMBLE_MEMBERS)]
    keys = ["model", "year", "event_id", "role"]
    counts = members.groupby(keys)["variant"].nunique()
    ensemble = members.groupby(keys)[["probability"]].mean()
    ensemble = ensemble.loc[counts.eq(len(ENSEMBLE_MEMBERS))].reset_index()
    ensemble = ensemble.assign(variant=ENSEMBLE, score=ensemble["probability"]).merge(
        info, on="event_id", how="left"
    )
    return pd.concat([scores, ensemble], ignore_index=True)


def _metrics(labels: np.ndarray[Any, Any], probabilities: np.ndarray[Any, Any]) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    return {
        "brier": float(np.mean((probabilities - labels) ** 2)),
        "log_loss": log_loss(labels, probabilities),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "n": int(len(labels)),
    }


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


def _test_table(
    scores: pd.DataFrame, frame: pd.DataFrame, variant: str, model: str, exits: pd.DataFrame | None
) -> pd.DataFrame:
    scored = scores.loc[scores["variant"].eq(variant) & scores["model"].eq(model)].copy()
    scored["selected"] = selections(scored)
    test = scored.loc[scored["role"].eq("test")]
    priced = frame.loc[:, ["event_id", "event_date", "frozen|status", "frozen|net"]]
    test = test.merge(priced, on="event_id", how="left", validate="one_to_one")
    test["alloc_frozen"] = allocation(test["selected"], test["frozen|status"], test["frozen|net"])
    if exits is not None:
        test = test.merge(exits, on="event_id", how="left", validate="one_to_one")
        both = test["frozen_status"].eq("COMPLETE") & test["exit|status"].eq("COMPLETE")
        test["alloc_e3"] = np.where(
            both, allocation(test["selected"], test["exit|status"], test["exit|net"]), np.nan
        )
    return test.set_index("event_id")


def _contrast(
    left: pd.DataFrame, right: pd.DataFrame, value: str, years: Sequence[int]
) -> dict[str, Any]:
    """right - left per event over common known rows in ``years``."""
    common = left.index.intersection(right.index)
    difference = (right.loc[common, value] - left.loc[common, value]).dropna()
    year = right.loc[difference.index, "year"]
    keep = year.isin(years)
    difference, year = difference[keep], year[keep]
    months = pd.to_datetime(right.loc[difference.index, "event_date"]).dt.strftime("%Y-%m")
    result = bootstrap(difference.to_numpy(dtype=float), months.to_numpy())
    result["per_year"] = {int(y): float(v) for y, v in difference.groupby(year).mean().items()}
    result["years_positive"] = sum(v > 0 for v in result["per_year"].values())
    return result


def evaluate(
    workspace: Path, simulation: Path, output: Path, exits_dir: Path | None = None
) -> dict[str, Any]:
    frame, _ = load_data(workspace, simulation)
    scores = assemble(frame, output)
    exits = None
    if exits_dir is not None and exits_dir.exists():
        from structural_break.pipeline.news_exit_results import EXIT, load_exits

        exits = load_exits(exits_dir).rename(
            columns={f"{EXIT}|status": "exit|status", f"{EXIT}|net": "exit|net"}
        )
        exits = exits.drop(columns=["frozen_net"])
    tables = {
        (variant, model): _test_table(scores, frame, variant, model, exits)
        for variant in (REFERENCE, *VARIANTS)
        for model in MODELS
    }
    result: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "decision": "DECISIONS 65",
        "decision_years": list(DECISION_YEARS),
        "reference_years": list(REFERENCE_YEARS),
        "models": {},
    }
    for model in MODELS:
        reference = tables[(REFERENCE, model)]
        labelled_ref = reference.loc[
            reference["supervised_eligible"].eq(True) & reference[TARGET].notna()
        ]
        labelled_ref = labelled_ref.assign(
            sq=(labelled_ref["probability"] - labelled_ref[TARGET]) ** 2
        )
        rows: dict[str, Any] = {}
        for variant in (REFERENCE, *VARIANTS):
            table = tables[(variant, model)]
            labelled = table.loc[table["supervised_eligible"].eq(True) & table[TARGET].notna()]
            labelled = labelled.assign(sq=(labelled["probability"] - labelled[TARGET]) ** 2)
            row: dict[str, Any] = {}
            for span, years in (("decision", DECISION_YEARS), ("reference", REFERENCE_YEARS)):
                part = labelled.loc[labelled["year"].isin(years)]
                row[f"forecast_{span}"] = _metrics(
                    part[TARGET].to_numpy(dtype=float), part["probability"].to_numpy(dtype=float)
                )
                chosen = table.loc[table["year"].isin(years) & table["selected"]]
                complete = chosen.loc[chosen["frozen|status"].eq("COMPLETE"), "frozen|net"]
                row[f"selected_{span}"] = {
                    "selected_n": int(len(chosen)),
                    "mean_net_per_trade_bps": float(complete.astype(float).mean() * 1e4),
                    "mean_net_per_candidate_bps": float(
                        table.loc[table["year"].isin(years), "alloc_frozen"].mean() * 1e4
                    ),
                }
                if exits is not None:
                    e3 = chosen.loc[chosen["exit|status"].eq("COMPLETE"), "exit|net"]
                    row[f"selected_{span}"]["e3_mean_net_per_trade_bps"] = float(
                        e3.astype(float).mean() * 1e4
                    )
            if variant != REFERENCE:
                # right - left = squared error of R0 minus the variant's: positive is better
                row["brier_gain"] = _contrast(labelled, labelled_ref, "sq", DECISION_YEARS)
                row["return_gain"] = _contrast(reference, table, "alloc_frozen", DECISION_YEARS)
                row["return_gain_reference_years"] = _contrast(
                    reference, table, "alloc_frozen", REFERENCE_YEARS
                )
                if exits is not None:
                    row["return_gain_e3"] = _contrast(reference, table, "alloc_e3", DECISION_YEARS)
            rows[variant] = row
        for measure in ("brier_gain", "return_gain"):
            adjusted = holm({v: rows[v][measure]["p_one_sided"] for v in VARIANTS})
            for variant in VARIANTS:
                stats = rows[variant][measure]
                stats["p_holm"] = adjusted[variant]
                stats["passes"] = bool(
                    stats["estimate"] > 0
                    and adjusted[variant] < ALPHA
                    and stats["years_positive"] >= MIN_POSITIVE_YEARS
                )
        result["models"][model] = rows
    result["tuning"] = _tuning_summary(output)
    body = json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    (output / "evaluation.json").write_text(body)
    return result


def _tuning_summary(output: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for path in sorted((output / "tasks").glob("*.json")):
        meta = json.loads(path.read_text())
        key = f"{meta['variant']}|{meta['model']}"
        summary.setdefault(key, {})[str(meta["year"])] = {
            "parameters": meta["parameters"],
            "trees": meta["trees"],
            "inner_score": meta.get("inner_score"),
            "inner_folds": meta.get("inner_folds"),
            "seconds": meta.get("seconds"),
        }
    return summary


def headline(result: dict[str, Any]) -> str:
    lines = []
    for model, rows in result["models"].items():
        lines.append(f"Model {model}")
        for variant, row in rows.items():
            f = row["forecast_decision"]
            s = row["selected_decision"]
            text = (
                f"  {variant:26s} Brier {f['brier']:.5f} AUC {f['roc_auc']:.3f}"
                f" PR {f['pr_auc']:.3f} | per trade {s['mean_net_per_trade_bps']:+.1f} bps"
            )
            if "return_gain" in row:
                b, r = row["brier_gain"], row["return_gain"]
                text += (
                    f" | Brier gain {b['estimate']:+.6f} p_holm {b['p_holm']:.3f}"
                    f" ({b['years_positive']}/12) | return gain {r['estimate'] * 1e4:+.2f} bps"
                    f" p_holm {r['p_holm']:.3f} ({r['years_positive']}/12)"
                )
            lines.append(text)
    return "\n".join(lines)


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status", "evaluate"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"),
    )
    parser.add_argument("--exits-dir", type=Path, default=Path("outputs/p6_sec_explore2"))
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_boosting"))
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--trials", type=int, default=TRIALS)
    args = parser.parse_args(arguments)
    if args.command == "run":
        count = run(args.workspace_root, args.simulation, args.output, args.workers, args.trials)
        print(f"{_now()} run finished: {count} tasks", flush=True)
    elif args.command == "status":
        print(status(args.output))
    else:
        print(headline(evaluate(args.workspace_root, args.simulation, args.output, args.exits_dir)))
    sys.stdout.flush()


if __name__ == "__main__":
    main()

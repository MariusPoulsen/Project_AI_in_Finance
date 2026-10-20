"""Quant research harness: forecast and trading evaluation of model specs (DECISIONS 75).

A spec is a feature set, a model and a training scheme. For every test year
2010-2023 the harness fits the model and scores the test year, and records:

- forecast metrics on labelled test events (ROC-AUC, PR-AUC, log loss and Brier
  after Platt calibration on out-of-fold training scores);
- top-share selections (cutoff = the 80th or 90th percentile of the previous
  year's out-of-sample scores), priced under the frozen exit and the E3 exit.

Schemes:
- ``d45``: the Decision 45 split, training on labels that ended before Y-1;
- ``recent``: training on every label that ended before Y. The previous year's
  scores for the cutoff are out-of-fold (purged K-fold) for training events
  and out-of-sample for the rest, so nothing is scored by a model that saw it.

Years are split into a development-selection block (2010-2017), used to
choose, and a holdout block (2018-2023), used once to confirm. The 2024-2025
final test is not read.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.experiments import p6_boosting as pb
from structural_break.experiments import p6_quant_features as qf

PLAN_VERSION = "p6-quant-v1"
TARGET = pb.TARGET
YEARS = tuple(range(2010, 2024))
SELECT, HOLDOUT = (2010, 2017), (2018, 2023)
SHARES = (0.20, 0.10)
OOF_FOLDS = 5
CALIBRATION_YEARS = 3
XGB = dict(pb.FIXED_XGB)


def feature_sets(
    base: dict[str, tuple[str, ...]], available: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    from structural_break.experiments.p6_coint import FEATURES as COINT

    b = base["B"]
    blocks = {name: cols for name, cols in qf.BLOCKS.items() if set(cols) <= set(available)}
    sets = {"B": b, "A": base["A"]}
    for name, cols in blocks.items():
        sets[f"B+{name}"] = (*b, *cols)
    stage_a = ("peer", "state", "track", "earnings", "momentum")
    every = tuple(c for name in stage_a if name in blocks for c in blocks[name])
    # Decision 75a: the blocks that each lowered Model B's 2010-2017 log loss.
    rule = ("peer", "state", "earnings", "momentum")
    if all(name in blocks for name in rule):
        sets["B+rule"] = (*b, *(c for name in rule for c in blocks[name]))
        from structural_break.experiments.p6_quant_ou import OU

        if set(OU) <= set(available):  # Decision 85 (Stage D)
            sets["B+rule+ou"] = (*sets["B+rule"], *OU)
            sets["B+all+ou"] = (*b, *every, *OU)
        if "extra" in blocks:  # Decision 81 (Stage A2)
            sets["B+rule+extra"] = (*sets["B+rule"], *blocks["extra"])
            sets["B+all+extra"] = (*b, *every, *blocks["extra"])
    sets["B+all"] = (*b, *every)
    if set(COINT) <= set(available):
        sets["B+all+coint"] = (*b, *every, *COINT)
    return sets


# Decision 86 (Stage E): model-capacity variants for the larger feature set.
PARAMS: dict[str, dict[str, Any]] = {
    "base": XGB,
    "col05": {**XGB, "colsample_bytree": 0.5},
    "slow": {**XGB, "n_estimators": 800, "learning_rate": 0.015},
    "bag5": {**XGB, "colsample_bytree": 0.5, "subsample": 0.8, "seeds": 5},
}


class _Bag:
    """Average of XGBoost fits that differ only in their random seed."""

    def __init__(self, params: dict[str, Any], seeds: int) -> None:
        self.models = [_model(params, pb.MODEL_SEED + i) for i in range(seeds)]

    def fit(self, x: Any, y: Any) -> _Bag:
        for model in self.models:
            model.fit(x, y)
        return self

    def predict_proba(self, x: Any) -> np.ndarray[Any, Any]:
        return np.asarray(np.mean([m.predict_proba(x) for m in self.models], axis=0))


def _estimator(params: dict[str, Any]) -> Any:
    params = dict(params)
    seeds = int(params.pop("seeds", 1))
    return _Bag(params, seeds) if seeds > 1 else _model(params)


def _model(params: dict[str, Any], seed: int = pb.MODEL_SEED) -> Any:
    from xgboost import XGBClassifier

    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=2,
        random_state=seed,
        **params,
    )


def split(
    frame: pd.DataFrame, year: int, scheme: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    signal_year = pd.to_datetime(frame["event_date"]).dt.year
    window_end = pd.to_datetime(frame["horizon_end_date"])
    supervised = frame["supervised_eligible"].eq(True) & frame[TARGET].notna()
    cut = pd.Timestamp(year - 1 if scheme == "d45" else year, 1, 1)
    train = frame.loc[supervised & window_end.lt(cut)]
    return train, frame.loc[signal_year.eq(year - 1)], frame.loc[signal_year.eq(year)]


def oof_scores(train: pd.DataFrame, columns: tuple[str, ...], params: dict[str, Any]) -> pd.Series:
    """Purged K-fold out-of-fold scores for every training event."""
    data = train.reset_index()
    scores = pd.Series(np.nan, index=data.index)
    for fit, valid in pb.purged_kfold(data, OOF_FOLDS):
        model = _estimator(params)
        model.fit(data.loc[fit, list(columns)].astype(float), data.loc[fit, TARGET].astype(int))
        scores.iloc[valid] = model.predict_proba(data.loc[valid, list(columns)].astype(float))[:, 1]
    scores.index = data["index"]
    return scores


def run_spec(
    frame: pd.DataFrame, columns: tuple[str, ...], scheme: str, params: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Raw test scores, calibrated probabilities and selections for every year."""
    from structural_break.ml.model import fit_sigmoid

    params = params or XGB
    parts = []
    for year in YEARS:
        train, previous, test = split(frame, year, scheme)
        oof = oof_scores(train, columns, params)
        model = _estimator(params)
        model.fit(train.loc[:, list(columns)].astype(float), train[TARGET].astype(int))
        test_raw = model.predict_proba(test.loc[:, list(columns)].astype(float))[:, 1]
        # Previous-year scores that no model fitted on them produced.
        in_train = previous.index.intersection(oof.index)
        outside = previous.index.difference(train.index)
        prior = pd.concat(
            [
                oof.loc[in_train],
                pd.Series(
                    model.predict_proba(previous.loc[outside, list(columns)].astype(float))[:, 1],
                    index=outside,
                ),
            ]
        )
        recent = pd.to_datetime(train["event_date"]).dt.year >= year - CALIBRATION_YEARS - (
            1 if scheme == "d45" else 0
        )
        cal_index = train.index[recent.to_numpy()]
        calibrator = fit_sigmoid(
            pb._logit(oof.loc[cal_index].to_numpy()), train.loc[cal_index, TARGET]
        )
        part = pd.DataFrame(
            {
                "event_id": test["event_id"].to_numpy(),
                "year": year,
                "raw": test_raw,
                "probability": calibrator.predict(pb._logit(test_raw)),
            }
        )
        for share in SHARES:
            cut = float(np.quantile(prior.to_numpy(), 1 - share))
            part[f"top{int(share * 100)}"] = test_raw >= cut
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def forecast_metrics(scored: pd.DataFrame, years: tuple[int, int]) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    part = scored.loc[scored["year"].between(*years) & scored["labelled"]]
    y = part[TARGET].to_numpy(float)
    p = part["probability"].to_numpy(float)
    return {
        "roc_auc": float(roc_auc_score(y, part["raw"])),
        "pr_auc": float(average_precision_score(y, part["raw"])),
        "log_loss": pb.log_loss(y, p),
        "brier": float(np.mean((p - y) ** 2)),
        "base_rate": float(y.mean()),
        "n": int(len(y)),
    }


def trading_metrics(scored: pd.DataFrame, years: tuple[int, int], share: int) -> dict[str, Any]:
    part = scored.loc[scored["year"].between(*years) & scored["priced_both"]]
    chosen = part.loc[part[f"top{share}"]]
    months = pd.to_datetime(part["event_date"]).dt.strftime("%Y-%m")
    out: dict[str, Any] = {"selected": int(len(chosen)), "candidates": int(len(part))}
    for exit_name, column in (("frozen", "frozen_net"), ("e3", "exit|net")):
        alloc = np.where(part[f"top{share}"], part[column].astype(float), 0.0)
        monthly = pd.Series(alloc, index=part.index).groupby(months).mean()
        out[exit_name] = {
            "per_trade_bps": float(chosen[column].astype(float).mean() * 1e4),
            "per_candidate_bps": float(alloc.mean() * 1e4),
            "monthly_sharpe": float(monthly.mean() / monthly.std(ddof=1) * math.sqrt(12))
            if monthly.std(ddof=1) > 0
            else math.nan,
            "hit_rate": float((chosen[column].astype(float) > 0).mean()),
        }
    return out


def attach(scored: pd.DataFrame, frame: pd.DataFrame, exits: pd.DataFrame) -> pd.DataFrame:
    info = frame.loc[:, ["event_id", "event_date", "supervised_eligible", TARGET]]
    out = scored.merge(info, on="event_id", how="left").merge(exits, on="event_id", how="left")
    out["labelled"] = out["supervised_eligible"].eq(True) & out[TARGET].notna()
    out["priced_both"] = out["frozen_status"].eq("COMPLETE") & out["exit|status"].eq("COMPLETE")
    return out


def summarise(scored: pd.DataFrame, holdout: bool = False) -> dict[str, Any]:
    """Selection-block metrics; the holdout block only when explicitly requested."""
    result: dict[str, Any] = {}
    blocks: list[tuple[str, tuple[int, int]]] = [("select", SELECT)]
    if holdout:
        blocks += [("holdout", HOLDOUT), ("all", (YEARS[0], YEARS[-1]))]
    for label, years in blocks:
        result[label] = {
            "forecast": forecast_metrics(scored, years),
            **{f"top{s}": trading_metrics(scored, years, s) for s in (20, 10)},
        }
    return result


def load(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]], pd.DataFrame]:
    from structural_break.experiments.p6_sec_explore3 import EXIT, load_exits

    frame, base = pb.load_data(args.workspace_root, args.simulation)
    frame = frame.merge(
        pd.read_parquet(args.features), on="event_id", how="left", validate="one_to_one"
    )
    ou_path = args.features.parent / "ou_features.parquet"
    if ou_path.exists():
        frame = frame.merge(
            pd.read_parquet(ou_path), on="event_id", how="left", validate="one_to_one"
        )
    if args.coint.exists():
        frame = frame.merge(
            pd.read_parquet(args.coint), on="event_id", how="left", validate="one_to_one"
        )
    exits = load_exits(args.exits_dir).rename(
        columns={f"{EXIT}|status": "exit|status", f"{EXIT}|net": "exit|net"}
    )
    return frame, base, exits


_STATE: dict[str, Any] = {}


def _init(arguments: list[str]) -> None:
    args = parser().parse_args(arguments)
    _STATE["frame"], _STATE["base"], _STATE["exits"] = load(args)


def _job(job: tuple[str, str, tuple[str, ...], str]) -> str:
    name, scheme, columns, folder = job
    variant = scheme.split(":")[1] if ":" in scheme else "base"
    scored = run_spec(_STATE["frame"], columns, scheme.split(":")[0], PARAMS[variant])
    path = Path(folder) / f"scores__{name}__{scheme.replace(':', '-')}.parquet"
    scored.to_parquet(path, index=False)
    return str(path)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("run", "summary"))
    p.add_argument("--specs", nargs="*", default=[])
    p.add_argument("--schemes", nargs="*", default=["recent"])
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    p.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"),
    )
    p.add_argument("--features", type=Path, default=Path("outputs/p6_quant/features.parquet"))
    p.add_argument("--coint", type=Path, default=Path("outputs/p6_coint/coint_features.parquet"))
    p.add_argument("--exits-dir", type=Path, default=Path("outputs/p6_sec_explore2"))
    p.add_argument("--output", type=Path, default=Path("outputs/p6_quant"))
    p.add_argument("--holdout", action="store_true", help="also report 2018-2023 (confirmation)")
    return p


def main(arguments: Sequence[str] | None = None) -> None:
    raw = list(arguments) if arguments is not None else sys.argv[1:]
    args = parser().parse_args(raw)
    frame, base, exits = load(args)
    sets = feature_sets(base, list(frame.columns))
    args.output.mkdir(parents=True, exist_ok=True)
    if args.command == "run":
        jobs = [
            (name, scheme, sets[name], str(args.output))
            for name in (args.specs or list(sets))
            for scheme in args.schemes
            if not (args.output / f"scores__{name}__{scheme.replace(':', '-')}.parquet").exists()
        ]
        print(f"{pb._now()} {len(jobs)} specs to run", flush=True)
        with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(raw,)) as pool:
            for path in pool.map(_job, jobs):
                print(f"{pb._now()} wrote {path}", flush=True)
        return
    rows = {}
    for path in sorted(args.output.glob("scores__*.parquet")):
        _, name, scheme = path.stem.split("__")
        rows[f"{name}|{scheme}"] = summarise(
            attach(pd.read_parquet(path), frame, exits), holdout=args.holdout
        )
    body = {"plan_version": PLAN_VERSION, "run_date": date.today().isoformat(), "specs": rows}
    name = "summary_holdout.json" if args.holdout else "summary_select.json"
    (args.output / name).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    for key, row in rows.items():
        for label in [k for k in ("select", "holdout") if k in row]:
            f, t = row[label]["forecast"], row[label]["top20"]
            print(
                f"{key:26s} {label:7s} AUC {f['roc_auc']:.4f} PR {f['pr_auc']:.4f}"
                f" LL {f['log_loss']:.5f} BR {f['brier']:.5f}"
                f" | top20 E3/trade {t['e3']['per_trade_bps']:+5.1f}"
                f" frozen/trade {t['frozen']['per_trade_bps']:+5.1f}"
                f" E3 SR {t['e3']['monthly_sharpe']:+.2f}"
            )


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------- #
# Decision 79: ranking by predicted trade return under the adopted exit
# --------------------------------------------------------------------------- #

ADOPTED_EXIT = "b1_snone_t20_news"


def _regressor(params: dict[str, Any]) -> Any:
    from xgboost import XGBRegressor

    return XGBRegressor(
        objective="reg:squarederror",
        tree_method="hist",
        n_jobs=2,
        random_state=pb.MODEL_SEED,
        **params,
    )


def run_return_spec(
    frame: pd.DataFrame, columns: tuple[str, ...], target: str, params: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Walk-forward regression on realised net return; selections as in ``run_spec``."""
    params = params or XGB
    parts = []
    signal_year = pd.to_datetime(frame["event_date"]).dt.year
    window_end = pd.to_datetime(frame["horizon_end_date"])
    known = frame[target].notna()
    for year in YEARS:
        train = frame.loc[known & window_end.lt(pd.Timestamp(year, 1, 1))].reset_index(drop=True)
        low, high = train[target].quantile([0.01, 0.99])
        y = train[target].clip(low, high)
        oof = pd.Series(np.nan, index=train.index)
        for fit, valid in pb.purged_kfold(train, OOF_FOLDS):
            model = _regressor(params)
            model.fit(train.loc[fit, list(columns)].astype(float), y.iloc[fit])
            oof.iloc[valid] = model.predict(train.loc[valid, list(columns)].astype(float))
        model = _regressor(params)
        model.fit(train.loc[:, list(columns)].astype(float), y)
        previous = frame.loc[signal_year.eq(year - 1)]
        test = frame.loc[signal_year.eq(year)]
        in_train = train.loc[train["event_id"].isin(previous["event_id"])]
        outside = previous.loc[~previous["event_id"].isin(train["event_id"])]
        prior = np.concatenate(
            [
                oof.loc[in_train.index].to_numpy(),
                model.predict(outside.loc[:, list(columns)].astype(float)) if len(outside) else [],
            ]
        )
        raw = model.predict(test.loc[:, list(columns)].astype(float))
        part = pd.DataFrame({"event_id": test["event_id"].to_numpy(), "year": year, "raw": raw})
        for share in SHARES:
            part[f"top{int(share * 100)}"] = raw >= float(np.quantile(prior, 1 - share))
        parts.append(part)
    return pd.concat(parts, ignore_index=True)

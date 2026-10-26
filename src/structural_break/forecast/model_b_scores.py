"""Pre-registered boosting round 2: return-aware improvements on the best model (DECISIONS 68).

The base is the fixed Decision 45 XGBoost Model B (R0), traded with the E3
news exit, the best combination so far. Round 1 (DECISIONS 66) showed that
re-tuning hyperparameters mostly fits noise, so these variants change how the
same model learns instead:

- W1 seed bagging: R0 with 80 % row and column subsampling, averaged over 10 seeds;
- W2 linear start: boosting starts from the logistic Model B logit (C = 0.01);
- W3 return weighting: each training event is weighted by the size of its
  frozen-policy net return (López de Prado's return attribution);
- W4 cointegration block: the 21 Decision 67 features added;
- W5 all four together.

Every variant uses the Decision 45 walk-forward and the top-20 % rule. The
primary measure is net return per Baseline 0 candidate under the E3 exit
against R0, 2010-2021. The 2024-2025 final test is not read.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.forecast import model_b as pb
from structural_break.forecast.coint_features import FEATURES as COINT_FEATURES

PLAN_VERSION = "p6-boosting-round2-v1"
TARGET = pb.TARGET
SEEDS = tuple(range(10))
BAG = {"subsample": 0.8, "colsample_bytree": 0.8}
LOGISTIC_C = 0.01
WEIGHT_CLIP = (0.01, 0.99)
BASE = "R0_xgb_fixed"
VARIANTS: dict[str, dict[str, bool]] = {
    "W1_seed_bag": {"bag": True},
    "W2_linear_start": {"start": True},
    "W3_return_weights": {"weights": True},
    "W4_coint_features": {"coint": True},
    "W5_all": {"bag": True, "start": True, "weights": True, "coint": True},
}


def return_weights(train: pd.DataFrame) -> np.ndarray[Any, Any]:
    """|frozen net| clipped at its 1st/99th percentiles, mean 1; unpriced rows get the median."""
    net = train["frozen|net"].astype(float).abs().where(train["frozen|status"].eq("COMPLETE"))
    low, high = net.quantile(WEIGHT_CLIP[0]), net.quantile(WEIGHT_CLIP[1])
    weights = net.clip(low, high).fillna(net.median())
    return np.asarray(weights / weights.mean(), dtype=float)


def _logistic_margin(
    train: pd.DataFrame, columns: tuple[str, ...], rows: pd.DataFrame
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    from structural_break.research.evaluation import _estimator

    model = _estimator("logistic", {"C": LOGISTIC_C}, pb.MODEL_SEED)
    model.fit(train.loc[:, columns].astype(float), train[TARGET].astype(int))
    return (
        np.asarray(model.decision_function(train.loc[:, columns].astype(float))),
        np.asarray(model.decision_function(rows.loc[:, columns].astype(float))),
    )


def score(
    options: dict[str, bool], train: pd.DataFrame, rows: pd.DataFrame, base: tuple[str, ...]
) -> np.ndarray[Any, Any]:
    """Fit one variant on the training window and return probabilities for ``rows``."""
    from xgboost import XGBClassifier

    columns = (*base, *COINT_FEATURES) if options.get("coint") else base
    x, y = train.loc[:, columns].astype(float), train[TARGET].astype(int)
    x_rows = rows.loc[:, columns].astype(float)
    fit_args: dict[str, Any] = {}
    predict_args: dict[str, Any] = {}
    if options.get("start"):
        train_margin, row_margin = _logistic_margin(train, columns, rows)
        fit_args["base_margin"] = train_margin
        predict_args["base_margin"] = row_margin
    if options.get("weights"):
        fit_args["sample_weight"] = return_weights(train)
    parameters = {k: v for k, v in pb.FIXED_XGB.items()}
    seeds: Sequence[int] = (pb.MODEL_SEED,)
    if options.get("bag"):
        parameters |= BAG
        seeds = SEEDS
    probabilities = np.zeros(len(rows))
    for seed in seeds:
        model = XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            n_jobs=1,
            random_state=seed,
            **parameters,
        )
        model.fit(x, y, **fit_args)
        probabilities += model.predict_proba(x_rows, **predict_args)[:, 1]
    return probabilities / len(seeds)


def walk_forward(frame: pd.DataFrame, base: tuple[str, ...]) -> pd.DataFrame:
    """Scores of R0 and every variant for the Y-1 threshold rows and Y test rows."""
    parts = []
    for year in (*pb.DECISION_YEARS, *pb.REFERENCE_YEARS):
        train, threshold_rows, test = pb.rolling_split(frame, year)
        rows = pd.concat([threshold_rows.assign(role="threshold"), test.assign(role="test")])
        for name, options in {BASE: {}, **VARIANTS}.items():
            parts.append(
                pd.DataFrame(
                    {
                        "event_id": rows["event_id"].to_numpy(),
                        "role": rows["role"].to_numpy(),
                        "score": score(options, train, rows, base),
                        "variant": name,
                        "model": "B",
                        "year": year,
                    }
                )
            )
        print(f"{pb._now()} year {year} scored", flush=True)
    return pd.concat(parts, ignore_index=True)


def sharpe(allocations: pd.Series, months: pd.Series) -> float:
    """Annualised Sharpe of the monthly mean per-candidate return."""
    monthly = allocations.groupby(months).mean()
    sd = float(monthly.std(ddof=1))
    return float(monthly.mean() / sd * math.sqrt(12)) if sd > 0 else math.nan


def evaluate(frame: pd.DataFrame, scores: pd.DataFrame, exits: pd.DataFrame) -> dict[str, Any]:
    info = frame.loc[
        :, ["event_id", "event_date", "supervised_eligible", TARGET, "frozen|status", "frozen|net"]
    ]
    tables: dict[str, pd.DataFrame] = {}
    for name in (BASE, *VARIANTS):
        scored = scores.loc[scores["variant"].eq(name)].copy()
        scored["selected"] = pb.selections(scored)
        test = scored.loc[scored["role"].eq("test")].merge(info, on="event_id", how="left")
        test = test.merge(exits, on="event_id", how="left", validate="one_to_one")
        test["alloc_frozen"] = pb.allocation(
            test["selected"], test["frozen|status"], test["frozen|net"]
        )
        both = test["frozen_status"].eq("COMPLETE") & test["exit|status"].eq("COMPLETE")
        test["alloc_e3"] = np.where(
            both, pb.allocation(test["selected"], test["exit|status"], test["exit|net"]), np.nan
        )
        labelled = test["supervised_eligible"].eq(True) & test[TARGET].notna()
        test["sq"] = np.where(labelled, (test["score"] - test[TARGET].astype(float)) ** 2, np.nan)
        tables[name] = test.set_index("event_id")
    result: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "decision": "DECISIONS 68",
        "variants": {},
    }
    reference = tables[BASE]
    for name, table in tables.items():
        row: dict[str, Any] = {}
        for span, years in (("decision", pb.DECISION_YEARS), ("reference", pb.REFERENCE_YEARS)):
            part = table.loc[table["year"].isin(years)]
            chosen = part.loc[part["selected"]]
            months = pd.to_datetime(part["event_date"]).dt.strftime("%Y-%m")
            known = part["alloc_e3"].notna()
            row[span] = {
                "selected_n": int(len(chosen)),
                "e3_mean_net_per_trade_bps": float(
                    chosen.loc[chosen["exit|status"].eq("COMPLETE"), "exit|net"]
                    .astype(float)
                    .mean()
                    * 1e4
                ),
                "frozen_mean_net_per_trade_bps": float(
                    chosen.loc[chosen["frozen|status"].eq("COMPLETE"), "frozen|net"]
                    .astype(float)
                    .mean()
                    * 1e4
                ),
                "e3_per_candidate_bps": float(part["alloc_e3"].mean() * 1e4),
                "e3_sharpe_monthly_annualised": sharpe(part.loc[known, "alloc_e3"], months[known]),
                "brier_raw": float(part["sq"].mean()),
            }
        if name != BASE:
            row["e3_return_gain"] = pb._contrast(reference, table, "alloc_e3", pb.DECISION_YEARS)
            row["frozen_return_gain"] = pb._contrast(
                reference, table, "alloc_frozen", pb.DECISION_YEARS
            )
            row["e3_return_gain_reference_years"] = pb._contrast(
                reference, table, "alloc_e3", pb.REFERENCE_YEARS
            )
            row["brier_gain_raw"] = pb._contrast(table, reference, "sq", pb.DECISION_YEARS)
        result["variants"][name] = row
    adjusted = pb.holm(
        {n: result["variants"][n]["e3_return_gain"]["p_one_sided"] for n in VARIANTS}
    )
    for name in VARIANTS:
        stats = result["variants"][name]["e3_return_gain"]
        stats["p_holm"] = adjusted[name]
        stats["passes"] = bool(
            stats["estimate"] > 0
            and adjusted[name] < pb.ALPHA
            and stats["years_positive"] >= pb.MIN_POSITIVE_YEARS
        )
    return result


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"),
    )
    parser.add_argument(
        "--coint", type=Path, default=Path("outputs/p6_coint/coint_features.parquet")
    )
    parser.add_argument("--exits-dir", type=Path, default=Path("outputs/p6_sec_explore2"))
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_boosting2"))
    args = parser.parse_args(arguments)
    from structural_break.pipeline.news_exit_results import EXIT, load_exits

    frame, columns = pb.load_data(args.workspace_root, args.simulation)
    frame = frame.merge(
        pd.read_parquet(args.coint), on="event_id", how="left", validate="one_to_one"
    )
    exits = load_exits(args.exits_dir).rename(
        columns={f"{EXIT}|status": "exit|status", f"{EXIT}|net": "exit|net"}
    )
    exits = exits.drop(columns=["frozen_net"])
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "scores.parquet"
    scores = pd.read_parquet(cache) if cache.exists() else walk_forward(frame, columns["B"])
    scores.to_parquet(cache, index=False)
    result = evaluate(frame, scores, exits) | {"run_date": date.today().isoformat()}
    (args.output / "evaluation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    )
    for name, row in result["variants"].items():
        d = row["decision"]
        text = (
            f"{name:20s} E3 per trade {d['e3_mean_net_per_trade_bps']:+6.1f} bps"
            f" per candidate {d['e3_per_candidate_bps']:+5.2f}"
            f" Sharpe {d['e3_sharpe_monthly_annualised']:+.2f}"
        )
        if "e3_return_gain" in row:
            g = row["e3_return_gain"]
            text += (
                f" | gain {g['estimate'] * 1e4:+.2f} bps p_holm {g['p_holm']:.3f}"
                f" ({g['years_positive']}/12) passes {g['passes']}"
            )
        print(text)


if __name__ == "__main__":
    main()

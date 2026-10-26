"""Pre-registered walk-forward replication of the reversion-rank lead (DECISIONS 45).

For every test year Y the models train only on label windows that ended before
year Y-1, the top-20 % threshold comes from out-of-sample scores in year Y-1 and
the rule then trades year Y. A and B share one fixed XGBoost family in the primary
pair. The frozen Decision 36 headline execution policy prices every trade.
2010-2021 decide pass/fail; 2022-2023 are reference rows only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.backtest.historical import HistoricalSources
from structural_break.backtest.production_policy import load_headline
from structural_break.pipeline.sources import (
    SEED,
    _sources,
    load_frame,
    paired_block_bootstrap,
    simulate_events,
)
from structural_break.research.evaluation import _estimator
from structural_break.storage.files import write_bytes

DECISION_YEARS = tuple(range(2010, 2022))
REFERENCE_YEARS = (2022, 2023)
TOP_SHARE = 0.20
MINIMUM_POSITIVE_YEARS = 8
XGB_PARAMETERS = {
    "learning_rate": 0.03,
    "max_depth": 3,
    "min_child_weight": 20,
    "n_estimators": 400,
    "reg_lambda": 10,
}
PAIRS = {
    "primary_xgb_vs_xgb": (("xgboost", XGB_PARAMETERS), ("xgboost", XGB_PARAMETERS)),
    "secondary_logistic_vs_xgb": (("logistic", {"C": 0.01}), ("xgboost", XGB_PARAMETERS)),
}


def rolling_split(
    frame: pd.DataFrame, year: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train on windows ending before Y-1; threshold on Y-1 signals; test on Y signals."""
    signal_year = pd.to_datetime(frame["event_date"]).dt.year
    window_end = pd.to_datetime(frame["horizon_end_date"]).dt.date
    supervised = frame["supervised_eligible"].eq(True) & frame["y_revert_success"].notna()
    train = frame.loc[supervised & window_end.lt(date(year - 1, 1, 1))]
    return train, frame.loc[signal_year.eq(year - 1)], frame.loc[signal_year.eq(year)]


def allocation(selected: pd.Series, status: pd.Series, net: pd.Series) -> pd.Series:
    """Selected COMPLETE -> net; withheld -> 0; selected unknown execution -> NaN."""
    result = pd.Series(0.0, index=selected.index)
    complete = selected & status.eq("COMPLETE")
    result[complete] = net[complete].astype(float)
    result[selected & ~status.eq("COMPLETE")] = np.nan
    return result


def _scores(
    family: str,
    parameters: dict[str, Any],
    train: pd.DataFrame,
    columns: tuple[str, ...],
    rows: pd.DataFrame,
) -> np.ndarray[Any, Any]:
    estimator = _estimator(family, parameters, SEED)
    estimator.fit(train.loc[:, columns].astype(float), train["y_revert_success"].astype(int))
    return np.asarray(estimator.predict_proba(rows.loc[:, columns].astype(float))[:, 1])


def run_walk_forward(
    sources: HistoricalSources,
    workspace: Path,
    configs: Path,
    output: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> Path:
    say = progress or (lambda message: None)
    cache = output / "simulation_frozen_exit.parquet"
    if cache.exists():
        simulated = pd.read_parquet(cache)
    else:
        headline = load_headline(configs)
        simulated = simulate_events(
            sources, {"frozen": headline}, date(2006, 1, 1), periods.data_end(), progress=say
        )
        output.mkdir(parents=True, exist_ok=True)
        simulated.to_parquet(cache, index=False)
    frame, report = load_frame(workspace, sources.binding.evaluation.version)
    frame = frame.merge(
        simulated.loc[:, ["event_id", "frozen|status", "frozen|net"]], on="event_id", how="inner"
    )
    columns = {
        "A": tuple(report["models"]["logistic"]["A"]["feature_columns"]),
        "B": tuple(report["models"]["logistic"]["B_both"]["feature_columns"]),
    }
    month = pd.to_datetime(frame["event_date"]).dt.strftime("%Y-%m")
    result: dict[str, Any] = {
        "decision": "DECISIONS 45",
        "post_hoc_replication_of": "DECISIONS 44 Baseline 0 reversion-rank lead",
        "execution_policy": load_headline(configs).version,
        "top_share": TOP_SHARE,
        "decision_years": list(DECISION_YEARS),
        "reference_years": list(REFERENCE_YEARS),
        "pairs": {},
    }
    for pair_name, ((family_a, params_a), (family_b, params_b)) in PAIRS.items():
        allocations: dict[str, pd.Series] = {
            "A": pd.Series(np.nan, index=frame.index),
            "B": pd.Series(np.nan, index=frame.index),
        }
        years: dict[str, Any] = {}
        for year in (*DECISION_YEARS, *REFERENCE_YEARS):
            say(f"{pair_name}: year {year}")
            train, calibrate, test = rolling_split(frame, year)
            row: dict[str, Any] = {
                "train_n": len(train),
                "threshold_n": len(calibrate),
                "candidates_n": len(test),
            }
            for side, family, params in (("A", family_a, params_a), ("B", family_b, params_b)):
                if train["y_revert_success"].nunique() < 2 or calibrate.empty or test.empty:
                    raise ValueError(f"Walk-forward year {year} lacks data")
                both = pd.concat([calibrate, test])
                scored = _scores(family, params, train, columns[side], both)
                cut = float(np.quantile(scored[: len(calibrate)], 1.0 - TOP_SHARE))
                selected = pd.Series(scored[len(calibrate) :] >= cut, index=test.index)
                status, net = test["frozen|status"], test["frozen|net"]
                values = allocation(selected, status, net)
                allocations[side].loc[test.index] = values
                complete = selected & status.eq("COMPLETE")
                row[side] = {
                    "threshold": cut,
                    "selected_n": int(selected.sum()),
                    "priced_n": int(complete.sum()),
                    "unknown_n": int((selected & ~status.eq("COMPLETE")).sum()),
                    "mean_net_bps": float(net[complete].astype(float).mean() * 1e4)
                    if complete.any()
                    else None,
                }
            known = (
                allocations["A"].loc[test.index].notna() & allocations["B"].loc[test.index].notna()
            )
            index = test.index[known.to_numpy()]
            difference = allocations["B"].loc[index] - allocations["A"].loc[index]
            row["b_minus_a_per_candidate_bps"] = float(difference.mean() * 1e4)
            row["common_candidates_n"] = int(len(index))
            years[str(year)] = row
        decision_rows = pd.to_datetime(frame["event_date"]).dt.year.isin(DECISION_YEARS)
        known = decision_rows & allocations["A"].notna() & allocations["B"].notna()
        pooled = paired_block_bootstrap(
            allocations["A"][known].to_numpy(dtype=float),
            allocations["B"][known].to_numpy(dtype=float),
            month[known].to_numpy(),
        )
        positive = sum(
            years[str(year)]["b_minus_a_per_candidate_bps"] > 0 for year in DECISION_YEARS
        )
        interval = pooled["interval_95"]
        passed = bool(
            interval is not None and interval[0] > 0 and positive >= MINIMUM_POSITIVE_YEARS
        )
        result["pairs"][pair_name] = {
            "years": years,
            "pooled_decision_years": {
                "common_candidates_n": int(known.sum()),
                "estimate_bps": pooled["estimate"] * 1e4
                if pooled["estimate"] is not None
                else None,
                "interval_95_bps": [value * 1e4 for value in interval] if interval else None,
                "months_n": pooled["blocks_n"],
                "positive_years": positive,
                "years_n": len(DECISION_YEARS),
            },
            "passes_pre_registered_criterion": passed,
        }
    result["lead_passes"] = result["pairs"]["primary_xgb_vs_xgb"]["passes_pre_registered_criterion"]
    body = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return write_bytes(output / "walk_forward.json", body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--configs-dir", type=Path, default=Path("configs"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    path = run_walk_forward(
        _sources(args.workspace_root),
        args.workspace_root,
        args.configs_dir,
        args.output_dir,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    print(json.dumps({"output": str(path)}))


if __name__ == "__main__":
    main()

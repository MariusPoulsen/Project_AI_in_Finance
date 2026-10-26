"""Walk-forward scores of the original Model B (R0), the selection model of the book.

The fixed Decision 45 XGBoost is refitted for every test year on labels that ended before
Y-1 (Decision 45 split); it scores the year Y-1 threshold rows and the year Y test rows.
The top-20 % cut is the 80th percentile of the threshold rows (``model_b.selections``).
``evaluate`` reports R0 under the frozen and E3 exits. The round-2 variants (W1-W5,
Decision 68) were erased in the Decision 115 cleanup. The 2024-2025 final test is not read.
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

from structural_break import periods
from structural_break.forecast import model_b as pb

PLAN_VERSION = "p6-boosting-round2-v1"
TARGET = pb.TARGET
BASE = "R0_xgb_fixed"


def score(train: pd.DataFrame, rows: pd.DataFrame, base: tuple[str, ...]) -> np.ndarray[Any, Any]:
    """Fit R0 on the training window and return probabilities for ``rows``."""
    from xgboost import XGBClassifier

    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=1,
        random_state=pb.MODEL_SEED,
        **pb.FIXED_XGB,
    )
    model.fit(train.loc[:, base].astype(float), train[TARGET].astype(int))
    return np.asarray(model.predict_proba(rows.loc[:, base].astype(float))[:, 1])


def walk_forward(frame: pd.DataFrame, base: tuple[str, ...]) -> pd.DataFrame:
    """R0 scores for the Y-1 threshold rows and the Y test rows of every year."""
    parts = []
    for year in (*pb.DECISION_YEARS, *pb.REFERENCE_YEARS, *periods.final_years_open()):
        train, threshold_rows, test = pb.rolling_split(frame, year)
        rows = pd.concat([threshold_rows.assign(role="threshold"), test.assign(role="test")])
        parts.append(
            pd.DataFrame(
                {
                    "event_id": rows["event_id"].to_numpy(),
                    "role": rows["role"].to_numpy(),
                    "score": score(train, rows, base),
                    "variant": BASE,
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
    for name in (BASE,):
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
        result["variants"][name] = row
    return result


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/walkforward/simulation_frozen_exit.parquet"),
    )
    parser.add_argument("--exits-dir", type=Path, default=Path("outputs/news_exit"))
    parser.add_argument("--output", type=Path, default=Path("outputs/model_b"))
    args = parser.parse_args(arguments)
    from structural_break.pipeline.news_exit import EXIT, load_exits

    frame, columns = pb.load_data(args.workspace_root, args.simulation)
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
        print(text)


if __name__ == "__main__":
    main()

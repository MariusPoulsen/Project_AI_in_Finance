"""Final-test report (Decisions 113, 117): Goal 1 and Goal 2 on the final-test years, once.

    python scripts/final_test_report.py --rehearsal   # same computation on 2022-2023 (allowed now)
    python scripts/final_test_report.py               # 2024-2025, only after the owner's unlock

Goal 1: ROC-AUC, PR-AUC, log loss and Brier of the original Model B (R0), the pre-registered
bagged B+rule+ou and the best observed B+rule+ou+track, on the labelled events of the years;
and (Decision 119) the full model, the bagged B+rule+ou plus the agent desk's entry scores,
against its own base on the desk's region events.
Goal 2: the adopted book (Decision 110d), the same book without the monitor exit, and
(Decision 119) the same book construction with the best forecaster's and the full model's
selections: Sharpe in excess of cash, CAGR with and without cash, maximum drawdown, turnover
and costs.
Writes outputs/final_test/<label>.json and prints the tables.
"""

import argparse
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.agents import desk_runner as desk
from structural_break.book import residual_sleeve as book
from structural_break.forecast import harness
from structural_break.pipeline.sources import _sources

WORKSPACE = Path("data/team")
SPECS = {
    "Original Model B (R0)": "scores__B__d45",
    "B+rule+ou, bagged (pre-registered Goal 1 model)": "scores__B+rule+ou__recent-bag5",
    "B+rule+ou+track, bagged (best observed)": "scores__B+rule+ou+track__recent-bag5",
}


def goal1(years: tuple[int, int]) -> dict[str, dict[str, Any]]:
    args = harness.parser().parse_args(["summary"])
    frame, _, exits = harness.load(args)
    out = {}
    for label, name in SPECS.items():
        scored = harness.attach(
            pd.read_parquet(Path("outputs/book") / f"{name}.parquet"), frame, exits
        )
        out[label] = harness.forecast_metrics(scored, years)
    # Decision 119: the full model against its own base, on the region events with a forecast.
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

    table, _ = desk.full_model(WORKSPACE)
    part = table[table.year.between(*years)].dropna(subset=["p_base", "p_agent"])
    for label, column in (
        ("Desk region: bagged B+rule+ou alone (walk-forward calibrated)", "p_base"),
        ("Desk region: full model (bagged B+rule+ou + agent desk)", "p_agent"),
    ):
        out[label] = {
            "roc_auc": float(roc_auc_score(part.y, part[column])),
            "pr_auc": float(average_precision_score(part.y, part[column])),
            "log_loss": float(log_loss(part.y, part[column])),
            "brier": float(brier_score_loss(part.y, part[column])),
            "n": int(len(part)),
        }
    return out


def goal2(years: tuple[int, int]) -> dict[str, dict[str, Any]]:
    sectors = _sources(WORKSPACE).security_sectors()
    prices = pd.read_parquet(
        WORKSPACE / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"],
    )
    panels = book.load_panels(prices, sectors)
    rf = book.tbill(Path("data/external/irx_13w_tbill.csv"))
    w = np.load("outputs/book/residual_targets_pca.npy") * 0.25
    checks: list[dict[str, Any]] = []
    for record in pd.read_parquet(desk.OUTPUT / "monitor_inventory.parquet").to_dict("records"):
        result = desk.load_result(desk.OUTPUT, "monitor", record["file"])
        if result and result["scores"]:
            checks.append(
                {
                    **cast(dict[str, Any], record),
                    **{k: result["scores"][k] for k in ("adverse", "persistence")},
                }
            )
    hit = pd.DataFrame(checks).query("adverse >= 5 and persistence >= 5")
    exits = hit.sort_values("session").groupby("event_id").session.first().dt.date.to_dict()
    out = {}
    _, chosen_full = desk.full_model(WORKSPACE)
    books = (
        ("adopted book (with monitor exit)", desk.desk_book(WORKSPACE, {}, set(), exits)),
        ("same book without the monitor exit", desk.desk_book(WORKSPACE, {}, set(), {})),
        # Decision 119: the same construction, only the selection differs.
        (
            "best forecaster's selection",
            desk.desk_book(WORKSPACE, {}, set(), exits, "B+rule+ou__recent-bag5"),
        ),
        (
            "full model's selection",
            desk.desk_book(WORKSPACE, {}, set(), exits, "FULL", chosen_full),
        ),
    )
    for label, legs in books:
        b = book.run_book(
            panels,
            w,
            legs,
            pd.Timestamp("2010-01-01"),
            pd.Timestamp(periods.data_end()),
            capital=1e7,
            rf=rf,
            speed=0.10,
            vol_target=0.04,
            vol_window=60,
            timing="close",
            max_gross=2.0,
        )
        excess, cash = book.stats(b, *years), book.stats(b, *years, cash=True)
        out[label] = {**excess, "cagr_with_cash": cash["cagr"]}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--rehearsal", action="store_true", help="run on 2022-2023 instead of the final test"
    )
    args = parser.parse_args()
    if args.rehearsal:
        years, label = (2022, 2023), "rehearsal_2022_2023"
    else:
        if not periods.final_years_open():
            raise SystemExit(
                "The final test is locked: no owner unlock record cites the freeze manifest"
            )
        years, label = (
            (periods.FINAL_TEST_YEARS[0], periods.FINAL_TEST_YEARS[-1]),
            "final_test_2024_2025",
        )
    report: dict[str, Any] = {
        "years": list(years),
        "unlock_record": periods.unlock_record(),
        "manifest_sha256": periods.manifest_sha256(),
        "goal1": goal1(years),
        "goal2": goal2(years),
    }
    out = Path("outputs/final_test") / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    print(f"Goal 1, {years[0]}-{years[1]}")
    for name, m in report["goal1"].items():
        print(
            f"  {name:50s} AUC {m['roc_auc']:.3f}  PR {m['pr_auc']:.3f}  LL {m['log_loss']:.4f}  Brier {m['brier']:.4f}  n {m.get('n', '')}"  # noqa: E501
        )
    print(f"Goal 2, {years[0]}-{years[1]}")
    for name, s in report["goal2"].items():
        print(
            f"  {name:36s} Sharpe {s['sharpe']:+.3f}  CAGR {s['cagr']:+.2%}  with cash {s['cagr_with_cash']:+.2%}  "  # noqa: E501
            f"max DD {s['maxdd']:.1%}  turnover {s['turnover']:.0f}x  cost {s['cost']:.2%}/yr"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

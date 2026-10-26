"""Final-test report (Decisions 113, 117): Goal 1 and Goal 2 on the final-test years, once.

    python scripts/final_test_report.py --rehearsal   # same computation on 2022-2023 (allowed now)
    python scripts/final_test_report.py               # 2024-2025, only after the owner's unlock

Goal 1: ROC-AUC, PR-AUC, log loss and Brier of the original Model B (R0), the pre-registered
bagged B+rule+ou and the best observed B+rule+ou+track, on the labelled events of the years.
Goal 2: the adopted book (Decision 110d) and the same book without the monitor exit: Sharpe
in excess of cash, CAGR with and without cash, maximum drawdown, turnover and costs.
Writes outputs/final_test/<label>.json and prints the tables.
"""

import argparse
import json
from pathlib import Path

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


def goal1(years: tuple[int, int]) -> dict[str, dict]:
    args = harness.parser().parse_args(["summary"])
    frame, _, exits = harness.load(args)
    out = {}
    for label, name in SPECS.items():
        scored = harness.attach(
            pd.read_parquet(Path("outputs/book") / f"{name}.parquet"), frame, exits
        )
        out[label] = harness.forecast_metrics(scored, years)
    return out


def goal2(years: tuple[int, int]) -> dict[str, dict]:
    sectors = _sources(WORKSPACE).security_sectors()
    prices = pd.read_parquet(
        WORKSPACE / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"],
    )
    panels = book.load_panels(prices, sectors)
    rf = book.tbill(Path("data/external/irx_13w_tbill.csv"))
    w = np.load("outputs/book/residual_targets_pca.npy") * 0.25
    checks = []
    for record in pd.read_parquet(desk.OUTPUT / "monitor_inventory.parquet").to_dict("records"):
        result = desk.load_result(desk.OUTPUT, "monitor", record["file"])
        if result and result["scores"]:
            checks.append(
                {**record, **{k: result["scores"][k] for k in ("adverse", "persistence")}}
            )
    hit = pd.DataFrame(checks).query("adverse >= 5 and persistence >= 5")
    exits = hit.sort_values("session").groupby("event_id").session.first().dt.date.to_dict()
    out = {}
    for label, legs in (
        ("adopted book (with monitor exit)", desk.desk_book(WORKSPACE, {}, set(), exits)),
        ("same book without the monitor exit", desk.desk_book(WORKSPACE, {}, set(), {})),
    ):
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
    report = {
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
            f"  {name:50s} AUC {m['roc_auc']:.3f}  PR {m['pr_auc']:.3f}  LL {m['log_loss']:.4f}  Brier {m['brier']:.4f}  n {m.get('n', '')}"
        )
    print(f"Goal 2, {years[0]}-{years[1]}")
    for name, s in report["goal2"].items():
        print(
            f"  {name:36s} Sharpe {s['sharpe']:+.3f}  CAGR {s['cagr']:+.2%}  with cash {s['cagr_with_cash']:+.2%}  "
            f"max DD {s['maxdd']:.1%}  turnover {s['turnover']:.0f}x  cost {s['cost']:.2%}/yr"
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

"""Small, read-only summary of the adopted book for the research app (demo/book/).

Reads the development outputs (2010-2023 only) and writes:
- book_daily.parquet: daily value of the adopted book and of the same book without the
  monitor exit (from scripts/verify_book.py);
- summary.json: the design, period statistics, the Goal 1 table, the overfitting audit and
  the agent-desk and news results, each with its decision reference.
Nothing from 2024-2025 is read.
"""

import json
from pathlib import Path

import pandas as pd

from structural_break.book import residual_sleeve as book

OUT = Path("demo/book")
PERIODS = {
    "2010–2017 (selection)": (2010, 2017),
    "2018–2023 (holdout)": (2018, 2023),
    "2010–2023": (2010, 2023),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    books = {
        "Adopted book (with monitor exit)": pd.read_parquet(
            "outputs/book/book_final_daily.parquet"
        ),
        "Same book without the monitor exit": pd.read_parquet(
            "outputs/book/book_no_monitor_daily.parquet"
        ),
    }
    daily = pd.DataFrame({"session_date": pd.to_datetime(next(iter(books.values())).session_date)})
    stats: dict[str, dict[str, dict[str, float]]] = {}
    for name, b in books.items():
        daily[name] = (1 + b.daily_return.to_numpy()).cumprod()
        stats[name] = {}
        for label, (y0, y1) in PERIODS.items():
            s, c = book.stats(b, y0, y1), book.stats(b, y0, y1, cash=True)
            stats[name][label] = {
                "sharpe": s["sharpe"],
                "cagr": s["cagr"],
                "cagr_with_cash": c["cagr"],
                "max_drawdown": s["maxdd"],
                "volatility": s["vol"],
                "turnover": s["turnover"],
                "cost": s["cost"],
            }
    daily.to_parquet(OUT / "book_daily.parquet", index=False)
    audit = json.loads(Path("outputs/book/audit/overfitting_audit.json").read_text())
    summary = {
        "design": [
            [
                "Selection",
                "Original Model B (R0), top 20 % of each test year, after the R1 fresh-news, "
                "mean-crossing and cost filters",
            ],
            [
                "Execution and size",
                "Signal and trade at the close; 7.5 % of NAV per entry; pairs gross cap 100 %",
            ],
            [
                "Exits",
                "Take profit at |z| ≤ 1.0, no z-score stop; time stop of 1.5 half-lives (10–40 "
                "sessions); "
                "8-K adverse-tone news exit; agent monitor exit (adverse ≥ 5 and persistence ≥ 5)",
            ],
            ["Residual sleeve", "PCA residual reversal, λ 0.25, trading speed 0.10"],
            ["Risk", "4 % volatility target (60 sessions); hard 200 % gross cap"],
            ["Cash", "Interest at the 13-week T-bill minus 0.25 %; Sharpe in excess of it"],
        ],
        "stats": stats,
        "goal1": pd.read_csv("outputs/book/goal1_table.csv").to_dict(orient="records"),
        "audit": {
            "trials": audit["trials"],
            "pbo": audit["pbo_cscv_2010_2023"],
            "dsr_2010_2023": {k: v["dsr"] for k, v in audit["dsr_2010_2023"].items()},
            "dsr_2018_2023": {k: v["dsr"] for k, v in audit["dsr_2018_2023_holdout"].items()},
            "rank": audit["final_rank_in_matrix"],
        },
        "desk": {
            "entry_scored": 6485,
            "entry_abstained": 31,
            "monitor_checks": 21333,
            "monitor_after_triage": 7937,
            "monitor_scored": 7933,
            "monitor_abstained": 4,
            "decision": "110d",
        },
        "news": {
            "source_2024_2025": "TickerTick",
            "toned_session_ratio": 4.83,
            "coverage_ratio": 1.90,
            "decision": "116d",
        },
        # Decision 119a: the same book construction with the other selections (development).
        "comparison": json.loads(Path("outputs/checks/books_dev.json").read_text()),
        "decisions": "Decisions 105-119 in docs/DECISIONS.md",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(f"wrote {OUT} ({sum(p.stat().st_size for p in OUT.iterdir()) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()

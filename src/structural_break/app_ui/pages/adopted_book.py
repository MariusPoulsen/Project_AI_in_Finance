"""The adopted trading book (Decisions 105-120): design, results by period and the final test."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import components, result_charts
from structural_break.app_ui.context import current
from structural_break.app_ui.results import BOOKS, Results, period_label

DESIGN = [
    (
        "Selection",
        "Original Model B (R0), top 20 % of each test year by the previous year's cutoff, after "
        "the R1 fresh-news filter, a 120-session mean-crossing filter and the most-expensive-"
        "fifth cost filter",
    ),
    (
        "Execution and size",
        "Signal and trade at the close; 7.5 % of NAV per entry; pairs gross cap 100 %",
    ),
    (
        "Exits",
        "Take profit at |z| ≤ 1.0, no z-score stop; time stop of 1.5 half-lives (10–40 sessions, "
        "20 when unknown); 8-K adverse-tone news exit; agent monitor exit (adverse ≥ 5 and "
        "persistence ≥ 5)",
    ),
    ("Residual sleeve", "PCA residual reversal, λ 0.25, trading a tenth of the gap each day"),
    ("Risk", "4 % volatility target on 60 sessions; hard 200 % book gross cap"),
    (
        "Costs",
        "Per stock: half spread by liquidity tier, square-root impact and commission, at $10m",
    ),
    ("Cash", "Interest at the 13-week T-bill minus 0.25 %; Sharpe is in excess of it"),
]
DESK = {
    "entry_scored": 6485,
    "entry_abstained": 31,
    "monitor_checks": 21333,
    "monitor_after_triage": 7937,
    "monitor_scored": 7933,
}
STATS_COLUMNS: dict[str, Any] = {
    "label": "Book",
    "period": "Years",
    "sharpe": st.column_config.NumberColumn("Sharpe", format="%.3f"),
    "cagr": st.column_config.NumberColumn("CAGR", format="percent"),
    "cagr_with_cash": st.column_config.NumberColumn("CAGR with cash", format="percent"),
    "max_drawdown": st.column_config.NumberColumn("Max drawdown", format="percent"),
    "turnover": st.column_config.NumberColumn("Turnover (×/yr)", format="%.1f"),
    "cost": st.column_config.NumberColumn("Costs (/yr)", format="percent"),
}
FINAL_BOOK_COLUMNS: dict[str, Any] = {
    "book": "Book",
    "sharpe": st.column_config.NumberColumn("Sharpe", format="%.3f"),
    "cagr": st.column_config.NumberColumn("CAGR", format="percent"),
    "cagr_with_cash": st.column_config.NumberColumn("CAGR with cash", format="percent"),
    "maxdd": st.column_config.NumberColumn("Max drawdown", format="percent"),
    "turnover": st.column_config.NumberColumn("Turnover (×/yr)", format="%.1f"),
    "cost": st.column_config.NumberColumn("Costs (/yr)", format="percent"),
}
FINAL_MODEL_COLUMNS: dict[str, Any] = {
    "model": "Model",
    "roc_auc": st.column_config.NumberColumn("ROC AUC", format="%.3f"),
    "pr_auc": st.column_config.NumberColumn("PR AUC", format="%.3f"),
    "log_loss": st.column_config.NumberColumn("Log loss", format="%.4f"),
    "brier": st.column_config.NumberColumn("Brier", format="%.4f"),
    "n": st.column_config.NumberColumn("Events", format="%d"),
}


def _final_test(report: dict[str, Any] | None, results: Results) -> None:
    st.subheader("Final test, 2024–2025")
    if report is None:
        sha = str(results.manifest.get("freeze_manifest_sha256") or "")[:12]
        components.verdict_box(
            "Unlocked, results pending",
            " The owner unlocked the final test on 27 October 2026 for the "
            f"freeze manifest {sha}…. The frozen code and design run once on 2024–2025; this "
            "section fills in when that run is published. Nothing is retuned after it.",
            "unavailable",
        )
        return
    components.verdict_box(
        "Opened once on the frozen design",
        " Owner-authorized final test; freeze manifest "
        f"{str(report.get('manifest_sha256', ''))[:12]}…. Every parameter is the frozen one.",
        "inconclusive",
    )
    goal2 = pd.DataFrame([{"book": k, **v} for k, v in report.get("goal2", {}).items()])
    if len(goal2):
        st.markdown("**Goal 2: the books on 2024–2025**")
        st.dataframe(
            goal2[list(FINAL_BOOK_COLUMNS)],
            hide_index=True,
            width="stretch",
            column_config=FINAL_BOOK_COLUMNS,
        )
    goal1 = pd.DataFrame([{"model": k, **v} for k, v in report.get("goal1", {}).items()])
    if len(goal1):
        st.markdown("**Goal 1: the forecasters on 2024–2025**")
        st.dataframe(
            goal1[list(FINAL_MODEL_COLUMNS)],
            hide_index=True,
            width="stretch",
            column_config=FINAL_MODEL_COLUMNS,
        )
    for note in report.get("notes", []):
        st.markdown(f"- {note}")


def news_density(news: pd.DataFrame) -> pd.DataFrame:
    """Company-specific headlines per ticker and month, by source and year."""
    if news.empty:
        return news
    frame = news.assign(year=news["month"].str[:4].astype(int))
    grouped = frame.groupby(["source", "year"]).agg(
        headlines=("headlines", "sum"), months=("month", "nunique")
    )
    grouped["per_ticker_month"] = grouped["headlines"] / (250 * grouped["months"])
    return grouped.reset_index()


def render() -> None:
    ctx = current()
    results = ctx.results
    components.page_header(
        "Adopted book",
        "The trading book chosen on 2010–2017, confirmed once on 2018–2023 and tested once on "
        "2024–2025: the original Model B selects the trades, and the agent desk's position "
        "monitor can close them early.",
    )
    if results is None:
        components.empty_state(
            "The book results are not in this deployment. Export them with "
            "`python scripts/export_results.py`."
        )
        return
    stats = results.book_stats()
    adopted = stats[stats["book"].eq("adopted")].set_index("period")
    span = "2010–2025" if "2010–2025" in adopted.index else "2010–2023"
    cards: list[tuple[str, str, str | None]] = [
        ("Sharpe, 2010–2017", f"{adopted.at['2010–2017', 'sharpe']:.2f}", "Selection years"),
        (
            "Sharpe, 2018–2023",
            f"{adopted.at['2018–2023', 'sharpe']:.2f}",
            "Holdout, opened once per stage",
        ),
    ]
    if "2024–2025" in adopted.index:
        cards.append(
            ("Sharpe, 2024–2025", f"{adopted.at['2024–2025', 'sharpe']:.2f}", "Final test")
        )
    cards += [
        (f"CAGR with cash, {span}", components.pct(adopted.at[span, "cagr_with_cash"]), None),
        (f"Max drawdown, {span}", components.pct(adopted.at[span, "max_drawdown"]), None),
    ]
    for column, (label, value, note) in zip(st.columns(len(cards)), cards, strict=True):
        column.metric(label, value, help=note)
    daily = results.tables["books_daily"]
    components.chart(result_charts.book_values(daily, ["adopted", "no_monitor"]), key="book_curves")
    st.caption(
        "Values include cash interest; Sharpe ratios are in excess of it. The dotted line marks "
        "the start of the 2018–2023 holdout"
        + (", the shaded band the 2024–2025 final test." if results.final_included else ".")
    )

    _final_test(results.final_test, results)

    st.subheader("Design")
    st.table(pd.DataFrame(DESIGN, columns=["Part", "Choice"]).set_index("Part"))

    st.subheader("Results by period")
    table = stats[stats["book"].isin(["adopted", "no_monitor"])].copy()
    table["period"] = table["period"].map(period_label)
    table["label"] = table["book"].map(
        {"adopted": "With monitor exit", "no_monitor": "Without monitor exit"}
    )
    st.dataframe(
        table[list(STATS_COLUMNS)], hide_index=True, width="stretch", column_config=STATS_COLUMNS
    )
    st.caption(
        f"The {BOOKS['bag5'].lower()} and the {BOOKS['full'].lower()} are compared in the "
        "Strategy Lab, with the design ladder and every trade."
    )
    st.page_link(
        ctx.pages["strategy"], label="Open the Strategy Lab", icon=":material/candlestick_chart:"
    )

    st.subheader("Monthly returns of the adopted book")
    components.chart(result_charts.monthly_heatmap(daily, "adopted"), key="book_months")

    components.verdict_box(
        "Overfitting audit",
        " Across 132 tracked designs the probability of backtest overfitting is 0.54, and the "
        "book's deflated Sharpe ratio is 0.86 for 2010–2023 (0.65 for 2018–2023), below the "
        "usual 0.95 bar. After correcting for the number of designs tried, the development "
        "Sharpe is not significantly different from luck; the 2024–2025 final test is the "
        "clean test.",
        "inconclusive",
    )

    st.subheader("Agent desk")
    review = results.summary.get("review", {})
    lines = [
        f"- **Entry agents** (pair news analyst, bull/bear debate, risk judge): "
        f"{DESK['entry_scored']:,} development events scored, {DESK['entry_abstained']} "
        "abstained. Their scores did not improve the forecast or the book, so they are "
        "evaluated in the Full model, while the adopted book retains R0 entry selection.",
        f"- **Position monitor:** a FinBERT triage sent {DESK['monitor_after_triage']:,} of "
        f"{DESK['monitor_checks']:,} development checks to the model; "
        f"{DESK['monitor_scored']:,} were scored. A trade closes when the monitor rates new "
        "news adverse 5 and persistent 5.",
    ]
    if review.get("answered"):
        lines.append(
            f"- **Human review:** the group checked {review['cases']} blind "
            f"cases with {review['claims']} cited claims; {review['confirmed']} of "
            f"{review['answered']} answers confirm the agents, {review['partly']} partly, "
            f"{review['rejected']} reject."
        )
    st.markdown("\n".join(lines))
    density = news_density(results.tables["news"])
    if len(density):
        st.markdown("**Company-specific headlines per ticker and month, by source**")
        st.dataframe(
            density.pivot(index="year", columns="source", values="per_ticker_month").reset_index(),
            hide_index=True,
            width="stretch",
            column_config={
                "year": st.column_config.NumberColumn("Year", format="%d"),
                "FNSPID": st.column_config.NumberColumn("FNSPID (development)", format="%.1f"),
                "TickerTick": st.column_config.NumberColumn(
                    "TickerTick (final test)", format="%.1f"
                ),
            },
        )
        st.caption(
            "FNSPID ends in 2023. For 2024–2025 the monitor reads TickerTick: "
            "its bulk file covers January 2024 to 25 May 2025 and is far denser than FNSPID; the "
            "live API used from 26 May 2025 keeps a much thinner archive, close to FNSPID's "
            "density. No threshold was changed for either."
        )

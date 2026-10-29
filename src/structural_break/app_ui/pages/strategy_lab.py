"""Strategy Lab: how the trading book was built (Goal 2), the selections, exits and trades."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import components, result_charts
from structural_break.app_ui.context import current
from structural_break.app_ui.results import Results, period_label

# How the book was built (development results, Sharpe in excess of cash). Each step was chosen
# on 2010-2017 and confirmed once on 2018-2023; the decisions hold the full records.
DESIGN_LADDER = [
    (
        "Trade every divergence, frozen exit",
        "Plan rules, flat costs, 25 % per entry",
        None,
        None,
        -0.86,
        -0.036,
        -0.200,
        "36–40",
    ),
    (
        "Model B selection, 8-K news exit",
        "Flat costs, 25 % per entry",
        None,
        None,
        -0.06,
        -0.005,
        -0.187,
        "73",
    ),
    (
        "Programme design: filters, take profit at |z| ≤ 1.0, disaster stop 5",
        "Flat costs, 25 % per entry",
        None,
        None,
        0.42,
        0.0231,
        -0.132,
        "77–89",
    ),
    (
        "Realistic costs, 7.5 % per entry, skip the most expensive fifth",
        "Realistic costs",
        0.482,
        0.53,
        0.50,
        0.018,
        -0.092,
        "95–99",
    ),
    ("+ PCA residual sleeve (λ 0.25)", "Realistic costs", 0.489, 0.54, 0.51, 0.018, -0.097, "105"),
    ("+ 4 % volatility target", "Realistic costs", 0.491, 0.50, 0.49, 0.018, -0.084, "106–107"),
    (
        "+ trading at the signal close",
        "Realistic costs",
        0.613,
        0.52,
        0.57,
        0.021,
        -0.080,
        "106–107",
    ),
    ("+ hard 200 % gross cap", "Realistic costs", 0.612, 0.52, 0.565, 0.021, -0.082, "108"),
    (
        "+ time stop of 1.5 half-lives, no z-score stop",
        "Realistic costs",
        0.799,
        0.439,
        0.622,
        0.024,
        -0.063,
        "112b",
    ),
    (
        "+ agent monitor exit: the adopted book",
        "Realistic costs",
        0.813,
        0.595,
        0.713,
        0.027,
        -0.069,
        "110d",
    ),
]
BOOK_KEYS = ["adopted", "no_monitor", "bag5", "full"]
REASONS = {
    "TAKE_PROFIT": "Take profit (|z| ≤ 1.0)",
    "CONVERGED": "Take profit (|z| ≤ 1.0)",
    "CONVERGENCE": "Take profit (|z| ≤ 1.0)",
    "TIMEOUT": "Time stop",
    "TIME_STOP": "Time stop",
    "MONITOR": "Agent monitor exit",
    "NEWS_EXIT": "8-K news exit",
}


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _book_table(results: Results) -> pd.DataFrame:
    stats = results.book_stats()
    order = ["2010–2017", "2018–2023", "2024–2025", "2010–2023", "2010–2025"]
    stats = stats[stats["period"].isin(order)].copy()
    stats["order"] = stats["period"].map(order.index)
    stats["book_order"] = stats["book"].map(BOOK_KEYS.index)
    stats = stats.sort_values(["book_order", "order"])
    stats["period"] = stats["period"].map(period_label)
    return stats[
        [
            "label",
            "period",
            "sharpe",
            "cagr",
            "cagr_with_cash",
            "max_drawdown",
            "volatility",
            "turnover",
            "cost",
        ]
    ]


BOOK_COLUMNS: dict[str, Any] = {
    "label": "Book",
    "period": "Years",
    "sharpe": st.column_config.NumberColumn("Sharpe", format="%.3f"),
    "cagr": st.column_config.NumberColumn("CAGR", format="percent"),
    "cagr_with_cash": st.column_config.NumberColumn("CAGR with cash", format="percent"),
    "max_drawdown": st.column_config.NumberColumn("Max drawdown", format="percent"),
    "volatility": st.column_config.NumberColumn("Volatility", format="percent"),
    "turnover": st.column_config.NumberColumn("Turnover (×/yr)", format="%.1f"),
    "cost": st.column_config.NumberColumn("Costs (/yr)", format="percent"),
}


def trade_summary(trades: pd.DataFrame) -> pd.DataFrame:
    frame = trades.assign(reason=trades["exit_reason"].map(REASONS).fillna(trades["exit_reason"]))
    grouped = frame.groupby("reason").agg(
        trades=("event_id", "size"),
        mean_bps=("gross_return", lambda r: 1e4 * r.mean()),
        hit_rate=("gross_return", lambda r: (r > 0).mean()),
        sessions=("sessions", "mean"),
    )
    grouped.loc["All trades"] = [
        len(frame),
        1e4 * frame["gross_return"].mean(),
        (frame["gross_return"] > 0).mean(),
        frame["sessions"].mean(),
    ]
    return grouped.reset_index()


TRADE_COLUMNS: dict[str, Any] = {
    "reason": "Exit",
    "trades": st.column_config.NumberColumn("Trades", format="%d"),
    "mean_bps": st.column_config.NumberColumn("Mean gross (bps)", format="%+.1f"),
    "hit_rate": st.column_config.NumberColumn("Winning share", format="percent"),
    "sessions": st.column_config.NumberColumn("Mean holding (sessions)", format="%.1f"),
}


def goal2(results: Results | None) -> None:
    st.subheader("The trading book (Goal 2)")
    if results is None:
        components.empty_state(
            "The book results are not in this deployment. Export them with "
            "`python scripts/export_results.py`."
        )
        return
    stats = results.book_stats().set_index(["book", "period"])
    cols = st.columns(4)
    cards = [
        ("Sharpe, 2010–2017 (selection)", "2010–2017"),
        ("Sharpe, 2018–2023 (holdout)", "2018–2023"),
    ]
    if ("adopted", "2024–2025") in stats.index:
        cards.append(("Sharpe, 2024–2025 (final test)", "2024–2025"))
    for col, (label, period) in zip(cols, cards, strict=False):
        col.metric(label, f"{stats.loc[('adopted', period), 'sharpe']:.2f}")
    span = "2010–2025" if ("adopted", "2010–2025") in stats.index else "2010–2023"
    cols[len(cards)].metric(
        f"CAGR with cash, {span}", components.pct(stats.loc[("adopted", span), "cagr_with_cash"])
    )
    tabs = st.tabs(["Design ladder", "Selections compared", "Exits and the monitor", "Trades"])
    with tabs[0]:
        ladder = pd.DataFrame(
            [
                {
                    "Step": step,
                    "Costs": "flat" if costs.startswith(("Plan", "Flat")) else "realistic",
                    "2010–17": _num(s1),
                    "2018–23": _num(s2),
                    "2010–23": _num(s3),
                    "CAGR 2010–23": components.pct(cagr),
                    "Max DD": components.pct(dd),
                }
                for step, costs, s1, s2, s3, cagr, dd, _decision in DESIGN_LADDER
            ]
        )
        st.markdown("**Sharpe ratio by period, each step added to the one above**")
        st.table(ladder.set_index("Step"))
        st.caption(
            "Each step was chosen on the 2010–2017 selection years and confirmed once on "
            "2018–2023. The first three rows use the plan's flat costs and 25 % of NAV per "
            "entry; from the fourth row on, realistic per-stock costs (spread, square-root "
            "impact, commission) at $10m. The largest gains came from how trades are run, not "
            "from better forecasts: the better forecasters did not select better trades. "
            "Probability of backtest overfitting over all 132 tracked designs: "
            "0.54; deflated Sharpe 0.86."
        )
    with tabs[1]:
        daily = results.tables["books_daily"]
        components.chart(result_charts.book_values(daily, BOOK_KEYS), key="g2_values")
        components.chart(result_charts.drawdowns(daily, BOOK_KEYS), key="g2_drawdowns")
        st.dataframe(
            _book_table(results), hide_index=True, width="stretch", column_config=BOOK_COLUMNS
        )
        st.caption(
            "All four books share the exits, sizing, residual sleeve, risk targeting and costs; "
            "only the trade selection or the monitor exit differs. Values "
            "include cash interest; Sharpe ratios are in excess of it. The dotted line marks the "
            "2018 holdout"
            + (", the shaded band the 2024–2025 final test." if results.final_included else ".")
        )
    with tabs[2]:
        trades = results.tables["trades"]
        left, right = st.columns([3, 2])
        with left:
            st.markdown("**Mean gross return by exit**")
            components.chart(
                result_charts.reason_bars(
                    trades.assign(
                        exit_reason=trades["exit_reason"].map(REASONS).fillna(trades["exit_reason"])
                    )
                ),
                key="g2_reasons",
            )
        with right:
            st.dataframe(
                trade_summary(trades), hide_index=True, width="stretch", column_config=TRADE_COLUMNS
            )
        with_monitor = stats.loc["adopted"]
        without = stats.loc["no_monitor"]
        rows = [
            {
                "Years": period_label(p),
                "With monitor": with_monitor.loc[p, "sharpe"],
                "Without monitor": without.loc[p, "sharpe"],
            }
            for p in with_monitor.index
            if p in without.index
        ]
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={
                "With monitor": st.column_config.NumberColumn(
                    "Sharpe with the monitor exit", format="%.3f"
                ),
                "Without monitor": st.column_config.NumberColumn(
                    "Sharpe without it", format="%.3f"
                ),
            },
        )
        st.caption(
            "Returns per trade are gross, from the entry close to the exit close, as a share of "
            "the trade's gross notional; costs are charged in the book. The monitor exit closes "
            "a trade when the agent desk rates new company news adverse 5 and persistent 5."
        )
    with tabs[3]:
        trades = results.tables["trades"].copy()
        years = sorted(trades["entry_date"].dt.year.unique())
        from structural_break.app_ui import navigation

        chosen = navigation.trade_years([int(y) for y in years])
        navigation.share("strategy")
        part = trades[trades["entry_date"].dt.year.between(*chosen)]
        part = part.assign(
            exit=part["exit_reason"].map(REASONS).fillna(part["exit_reason"]),
            gross_bps=1e4 * part["gross_return"],
        )
        st.dataframe(
            part[
                [
                    "entry_date",
                    "exit_date",
                    "pair_id",
                    "long_leg",
                    "exit",
                    "sessions",
                    "size_nav",
                    "gross_bps",
                ]
            ],
            hide_index=True,
            width="stretch",
            height=420,
            column_config={
                "entry_date": st.column_config.DateColumn("Entry", format="D MMM YYYY"),
                "exit_date": st.column_config.DateColumn("Exit", format="D MMM YYYY"),
                "pair_id": "Pair",
                "long_leg": "Long",
                "exit": "Exit",
                "sessions": st.column_config.NumberColumn("Sessions", format="%d"),
                "size_nav": st.column_config.NumberColumn("Size (share of NAV)", format="percent"),
                "gross_bps": st.column_config.NumberColumn("Gross (bps)", format="%+.1f"),
            },
        )
        st.download_button(
            "Download trades (CSV)",
            part.to_csv(index=False).encode(),
            file_name="adopted_book_trades.csv",
            mime="text/csv",
            icon=":material/download:",
            key="g2_download",
        )


def render() -> None:
    ctx = current()
    components.page_header(
        "Strategy Lab",
        "Would the forecasts have paid after costs? The trading book of Goal 2: how it was "
        "built step by step, how the same book does with other selections, its exits and "
        "every trade.",
    )
    components.synthetic_banner(ctx.service.identity)
    goal2(ctx.results)

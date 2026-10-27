"""Strategy Lab: how the trading book was built (Goal 2), then the frozen plan ladder."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, result_charts
from structural_break.app_ui.context import current
from structural_break.app_ui.results import Results, period_label
from structural_break.services.research_application import RUNG_LABELS

LADDER_COLUMNS: dict[str, Any] = {
    "label": "Strategy rung",
    "selected_n": "Selected",
    "priced_n": "Priced",
    "not_entered_n": "Not entered",
    "unpriced_n": "Unpriced",
    "mean_net_bps": "Mean net (bps)",
    "median_net_bps": "Median net (bps)",
    "net_positive_rate": "Winning share",
    "label_success": "Label success",
    "mean_holding_sessions": "Mean holding (sessions)",
}


def _ladder_table(rows: pd.DataFrame) -> pd.DataFrame:
    table = rows.copy()
    for name in ("mean_net_return", "median_net_return", "label_success_rate", "labelled_n"):
        if name not in table:
            table[name] = None
    table["mean_net_bps"] = pd.to_numeric(table["mean_net_return"], errors="coerce") * 1e4
    table["median_net_bps"] = pd.to_numeric(table["median_net_return"], errors="coerce") * 1e4
    table["label_success"] = [
        "not run"
        if status == "NOT_RUN"
        else (
            f"{components.pct(rate)} (n={int(n)})"
            if rate is not None and not pd.isna(rate) and n
            else "n/a"
        )
        for status, rate, n in zip(
            table["status"], table["label_success_rate"], table["labelled_n"], strict=False
        )
    ]
    table = table.reindex(columns=list(LADDER_COLUMNS))
    for name in LADDER_COLUMNS:
        if name not in {"label", "label_success"}:
            table[name] = pd.to_numeric(table[name], errors="coerce")
    return table.rename(columns=LADDER_COLUMNS)


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
                    "Decision": decision,
                }
                for step, costs, s1, s2, s3, cagr, dd, decision in DESIGN_LADDER
            ]
        )
        st.markdown("**Sharpe ratio by period, each step added to the one above**")
        st.table(ladder.set_index("Step"))
        st.caption(
            "Each step was chosen on the 2010–2017 selection years and confirmed once on "
            "2018–2023. The first three rows use the plan's flat costs and 25 % of NAV per "
            "entry; from the fourth row on, realistic per-stock costs (spread, square-root "
            "impact, commission) at $10m. The largest gains came from how trades are run, not "
            "from better forecasts: the better forecasters did not select better trades "
            "(Decision 87). Probability of backtest overfitting over all 132 tracked designs: "
            "0.54; deflated Sharpe 0.86 (Decision 113)."
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
            "only the trade selection or the monitor exit differs (Decision 119). Values "
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
            "a trade when the agent desk rates new company news adverse 5 and persistent 5 "
            "(Decision 110d)."
        )
    with tabs[3]:
        trades = results.tables["trades"].copy()
        years = sorted(trades["entry_date"].dt.year.unique())
        chosen = st.select_slider(
            "Entry years", options=years, value=(years[0], years[-1]), key="g2_years"
        )
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
    service, horizon = ctx.service, ctx.horizon
    components.page_header(
        "Strategy Lab",
        "Would the forecasts have paid after costs? First the trading book of Goal 2: how it "
        "was built step by step, how the same book does with other selections, and every "
        "trade. Below it, the frozen plan ladder that applied the original execution rules to "
        "2022–2023.",
    )
    components.synthetic_banner(service.identity)
    goal2(ctx.results)
    st.divider()
    st.subheader("Research layer: the frozen plan ladder, 2022–2023 (Decisions 36–40)")
    st.caption(
        "The pre-registered ladder: the same frozen execution engine and flat cost policy for "
        "every rung (trade every divergence, only ACTIVE relationships, or only events a "
        "research-layer model rates likely to revert), on 2022–2023. Its tiny model selections "
        "are why the programme above changed how trades are selected and run."
    )
    summary = service.strategy(horizon)
    if not summary:
        components.empty_state(
            "No verified Phase 6 experiment is attached for this horizon. Run "
            "`structural-break-backtest p6-acceptance` and re-export the bundle with "
            "`--experiments-root .acceptance`, or open the app on the workspace that holds them."
        )
        return
    headline = summary["headline"]
    rungs = service.strategy_rungs(horizon, "HEADLINE")
    st.markdown(
        f'<span class="sb-chip">Model threshold {float(headline["threshold"]):.2f}</span>'
        f'<span class="sb-chip">Execution policy {headline["execution_config_version"]}</span>'
        f'<span class="sb-chip">{summary["event_count"]} events</span>'
        '<span class="sb-chip">Full System rung: not part of this frozen ladder</span>',
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    by_rung = rungs.set_index("rung")
    for col, rung in zip(cols, ["BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B"], strict=True):
        if rung not in by_rung.index:
            continue
        row = by_rung.loc[rung]
        col.metric(
            RUNG_LABELS[rung].split(" ·")[0],
            components.bps(row.get("mean_net_return")),
            help=f"Mean net return per priced selected trade. Selected "
            f"{components.count(row.get('selected_n'))}, "
            f"priced {components.count(row.get('priced_n'))}.",
        )
        col.caption(
            f"{components.count(row.get('selected_n'))} selected, "
            f"{components.count(row.get('priced_n'))} priced"
        )
    st.dataframe(
        _ladder_table(rungs),
        hide_index=True,
        width="stretch",
        column_config={
            "Mean net (bps)": st.column_config.NumberColumn(format="%+.1f"),
            "Median net (bps)": st.column_config.NumberColumn(format="%+.1f"),
            "Winning share": st.column_config.NumberColumn(format="percent"),
            "Mean holding (sessions)": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    st.caption(
        "Signal at the close, entry at the next open, beta-weighted legs, exits at convergence, "
        "adverse stop or timeout. Returns are in basis points of entry gross notional for "
        "COMPLETE trades only; not-entered and unpriced trades keep their counts and are never "
        "counted as zero."
    )
    tabs = st.tabs(
        [
            "Equity and drawdown",
            "Threshold sensitivity",
            "Costs and borrow",
            "Paired bootstrap",
            "Rejected trades",
            "Limitations",
        ]
    )
    with tabs[0]:
        nav = service.strategy_nav(horizon)
        if nav.empty:
            components.empty_state("No portfolio marks are published for this experiment.")
        else:
            components.chart(charts.nav_chart(nav, "nav", "Portfolio NAV (start = 1)"), key="nav")
            components.chart(
                charts.nav_chart(nav, "drawdown", "Drawdown", percent=True), key="drawdown"
            )
            portfolios = service.strategy_portfolios(horizon)
            table = portfolios.reindex(
                columns=[
                    "label",
                    "final_nav",
                    "maximum_drawdown",
                    "known_turnover",
                    "known_trading_cost",
                    "known_borrow_cost",
                ]
            )
            for name in table.columns[1:]:
                table[name] = pd.to_numeric(table[name], errors="coerce")
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                column_config={
                    "label": "Strategy rung",
                    "final_nav": st.column_config.NumberColumn("Final NAV", format="%.4f"),
                    "maximum_drawdown": st.column_config.NumberColumn(
                        "Max drawdown", format="percent"
                    ),
                    "known_turnover": st.column_config.NumberColumn(
                        "Turnover (known)", format="%.2f"
                    ),
                    "known_trading_cost": st.column_config.NumberColumn(
                        "Trading cost (known)", format="%.5f"
                    ),
                    "known_borrow_cost": st.column_config.NumberColumn(
                        "Borrow cost (known)", format="%.5f"
                    ),
                },
            )
            st.caption(
                "A NAV line stops where a held position could not be priced; it is not filled in."
            )
    with tabs[1]:
        thresholds = service.strategy_thresholds(horizon)
        if thresholds.empty:
            components.empty_state("No threshold sensitivities are published.")
        else:
            table = thresholds.assign(
                mean_net_bps=pd.to_numeric(thresholds["mean_net_return"], errors="coerce") * 1e4,
                rung=thresholds["rung"].map(RUNG_LABELS),
            )[["threshold", "role", "rung", "selected_n", "priced_n", "mean_net_bps"]]
            st.dataframe(
                table,
                hide_index=True,
                width="stretch",
                column_config={
                    "mean_net_bps": st.column_config.NumberColumn("Mean net (bps)", format="%+.1f")
                },
            )
            st.caption(
                "Selection counts are the binding fact: at higher thresholds the models select "
                "almost nothing."
            )
    with tabs[2]:
        rung = (
            st.segmented_control(
                "Rung",
                ["BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B"],
                default="MODEL_B",
                format_func=lambda r: RUNG_LABELS[r].split(" ·")[0],
                key="cost_rung",
            )
            or "MODEL_B"
        )
        costs = service.strategy_costs(horizon, rung)
        if costs.empty:
            components.empty_state("No cost grid is published.")
        else:
            components.chart(charts.cost_heatmap(costs), key="costs")
            st.caption(
                "Mean net bps per priced selected trade. The selected trades are identical in "
                "every cell; no scenario is chosen."
            )
    with tabs[3]:
        comparisons = service.strategy_comparisons(horizon)
        if comparisons.empty:
            components.empty_state("No paired bootstrap is published.")
        else:
            components.chart(charts.forest(comparisons), key="boot")
            st.dataframe(
                comparisons.assign(
                    estimate=comparisons["estimate"] * 1e4,
                    low=comparisons["low"] * 1e4,
                    high=comparisons["high"] * 1e4,
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    name: st.column_config.NumberColumn(name, format="%+.2f")
                    for name in ("estimate", "low", "high")
                },
            )
            st.caption(
                "Calendar-month block bootstrap of the common known allocation per raw candidate. "
                "An interval that includes zero means the step up the ladder made no "
                "distinguishable economic difference."
            )
    with tabs[4]:
        rung = (
            st.segmented_control(
                "Rung",
                ["BASELINE_1", "MODEL_A", "MODEL_B"],
                default="MODEL_B",
                format_func=lambda r: RUNG_LABELS[r].split(" ·")[0],
                key="reject_rung",
            )
            or "MODEL_B"
        )
        outcomes = service.trade_outcomes(horizon, rung)
        if outcomes.empty:
            components.empty_state("No trade-level executions are available.")
        else:
            components.chart(charts.outcome_box(outcomes), key="outcomes")
            rung_info = by_rung.loc[rung] if rung in by_rung.index else None
            if rung_info is not None:
                st.caption(
                    f"Withheld events that could be priced: "
                    f"{components.count(rung_info.get('not_selected_priced_n'))}, "
                    f"mean counterfactual net "
                    f"{components.bps(rung_info.get('not_selected_mean_net_return'))}. "
                    "A good filter rejects trades that would have lost money."
                )
            withheld = service.strategy_trades(horizon, rung, "WITHHELD")
            with st.expander(f"Withheld events ({len(withheld)})"):
                st.dataframe(
                    withheld.drop(
                        columns=[c for c in withheld if c in RUNG_LABELS], errors="ignore"
                    ),
                    hide_index=True,
                    width="stretch",
                )
    with tabs[5]:
        for item in summary.get("limitations", []):
            st.markdown(f"- {item}")
        st.markdown(
            "- Model selections are tiny at the headline threshold, so no A-versus-B economic "
            "comparison supports a conclusion.\n"
            "- 2022–2023 was already observed during development; these are development "
            "results, not the final test.\n"
            "- The multi-agent Full System rung is not part of this frozen ladder; the agent "
            "desk was evaluated later, in the trading book above (Decisions 109–110, 119)."
        )
    components.provenance(
        {
            "Experiment": summary["experiment_id"],
            "Headline combination": headline["key"],
            f"Evaluation (h{horizon})": service.identity.evaluations.get(horizon),
            "Calendar months": f"{len(summary.get('calendar_months', []))}",
            "Bundle": service.identity.bundle_id,
        }
    )

"""Frozen policy benchmark presented within the portfolio workspace."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components
from structural_break.services.research_application import RUNG_LABELS, ResearchApplicationService

LADDER_COLUMNS = {
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


def render_benchmark(service: ResearchApplicationService) -> None:
    horizon = 20
    st.caption(
        "Frozen policy benchmark · 2022–2023 · next-open entry · fixed 20-session cap. "
        "The model A/B scores here belong to the frozen benchmark, not the current "
        "annual walk-forward comparison above."
    )
    summary = service.strategy(horizon)
    if not summary:
        components.empty_state(
            "No verified policy benchmark is attached to this snapshot. "
            "Ask the project owner for an export containing the saved benchmark."
        )
        return
    headline = summary["headline"]
    rungs = service.strategy_rungs(horizon, "HEADLINE")
    rungs = rungs.loc[rungs["rung"].isin(["BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B"])].copy()
    st.markdown(
        f'<span class="sb-chip">Model threshold {float(headline["threshold"]):.2f}</span>'
        f'<span class="sb-chip">Execution policy {headline["execution_config_version"]}</span>'
        f'<span class="sb-chip">{summary["event_count"]} events</span>',
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
        if not nav.empty:
            nav = nav.loc[nav.rung.isin(by_rung.index)]
        if nav.empty:
            components.empty_state("No portfolio marks are published for this experiment.")
        else:
            components.chart(charts.nav_chart(nav, "nav", "Portfolio NAV (start = 1)"), key="nav")
            components.chart(
                charts.nav_chart(nav, "drawdown", "Drawdown", percent=True), key="drawdown"
            )
            portfolios = service.strategy_portfolios(horizon)
            portfolios = portfolios.loc[portfolios.rung.isin(by_rung.index)]
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
        if not thresholds.empty:
            thresholds = thresholds.loc[thresholds.rung.isin(by_rung.index)]
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
            st.caption("Threshold sensitivities use the same saved benchmark and cohort.")
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
                    "Counterfactual outcomes are development diagnostics."
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
        st.caption(
            "Post-hoc development benchmark. Distinct execution and score generations "
            "must not be compared as a matched current-book experiment. "
            "Missing or unpriced trades are never treated as zero returns."
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

"""Period-aligned presentation of the adopted and no-monitor saved books."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import components, data, theme
from structural_break.app_ui.pages import workspace
from structural_break.services.research_summary import ADOPTED, COMPARATOR

LABELS = {ADOPTED: "With monitor", COMPARATOR: "Without monitor"}


def curves(daily: pd.DataFrame, drawdown: bool) -> go.Figure:
    figure = go.Figure()
    for name, color, dash in (
        (ADOPTED, theme.MODEL_B, "solid"),
        (COMPARATOR, theme.MODEL_A, "dash"),
    ):
        figure.add_trace(
            go.Scatter(
                x=daily["session_date"],
                y=daily[name],
                name=LABELS[name],
                line={"color": color, "width": 2, "dash": dash},
                hovertemplate="%{x|%d %b %Y}<br>"
                + ("%{y:.2%}" if drawdown else "%{y:.4f}")
                + "<extra>%{fullData.name}</extra>",
            )
        )
    figure.update_layout(
        theme.layout(
            height=340,
            hovermode="x unified",
            margin={"l": 65, "r": 15, "t": 40, "b": 45},
            yaxis={
                "title": "Drawdown · with cash" if drawdown else "NAV · with cash interest",
                "tickformat": ".0%" if drawdown else ".2f",
            },
        )
    )
    return figure


def render() -> None:
    components.page_header(
        "Compare portfolio returns",
        "Exit-policy statistics, NAV and drawdown after saved trading costs.",
    )
    svc = workspace.service()
    if svc is None:
        return
    controls = st.columns([1.2, 1], gap="large")
    with controls[0]:
        period = workspace.period_control("sb_book_period")
    with controls[1]:
        view = st.segmented_control(
            "Curve", ["NAV", "Drawdown"], default="NAV", key="sb_book_curve"
        )
    stats = svc.book_comparison(period)
    st.caption(f"{period} · costs included · Sharpe in excess of cash")
    drawdown = view == "Drawdown"
    daily = svc.curves(period, drawdown=drawdown)
    st.subheader("Selection and exit-policy comparison")
    displayed = pd.DataFrame(
        [
            {
                "Selection": row["Selection"],
                "Monitor": row["Monitor"],
                "Sharpe (excess cash)": f"{row['sharpe']:.3f}",
                "CAGR with cash": components.pct(row["cagr_with_cash"], 2)
                if pd.notna(row["cagr_with_cash"])
                else "Not exported",
                "CAGR excluding cash": components.pct(row["cagr"], 2),
                "Max DD (excess cash)": components.pct(row["max_drawdown"], 2),
                "Costs / year": components.pct(row["cost"], 2),
            }
            for _, row in stats.iterrows()
        ]
    )
    st.dataframe(displayed, hide_index=True, width="stretch")
    st.caption(
        "Best-forecaster selection: B+rule+ou bag5. Full: forecaster plus entry desk. "
        "Missing monitor checks remain fail-open, including Full-only positions."
    )
    components.chart(curves(daily, drawdown), key="adopted_curves")
    st.caption(
        "Curves include cash interest; statistics labelled excess cash exclude it. "
        "NAV rebases on the preceding close (initial capital 1 for 2010)."
    )
    st.caption(
        "Daily curves are exported for R0 with and without monitor only. "
        "Best-forecaster and Full rows use saved book statistics; their curves "
        "and CAGR including cash have not been exported."
    )
    with st.expander("Book rules"):
        st.table(workspace.book_rules(svc))
    with st.expander("Download the displayed comparison"):
        st.download_button(
            "Download book statistics",
            stats.assign(Period=period, Snapshot=svc.snapshot_id).to_csv(index=False),
            file_name="book-comparison.csv",
            mime="text/csv",
        )
        st.download_button(
            "Download displayed curves",
            daily.to_csv(index=False),
            file_name="book-drawdown.csv" if drawdown else "book-nav.csv",
            mime="text/csv",
        )
    workspace.link("evidence", "Open selection and coverage diagnostics")
    workspace.link("forecast", "Compare the forecasting evidence")
    with st.expander("Baseline and model policy benchmark · 2022–2023"):
        from structural_break.app_ui.pages.policy_benchmark import render_benchmark

        outcome = data.registry()
        if outcome.service is None:
            st.info("The frozen policy benchmark is unavailable.")
        else:
            render_benchmark(outcome.service)
    workspace.provenance(svc)

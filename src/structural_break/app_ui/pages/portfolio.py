"""Period-aligned presentation of the adopted and no-monitor saved books."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import components, theme
from structural_break.app_ui.pages import workspace
from structural_break.services.research_summary import ADOPTED, COMPARATOR

LABELS = {ADOPTED: "R0 + monitor", COMPARATOR: "R0 without monitor"}


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
        "R0 selects the trades. "
        "Compare the adopted position-monitor exits with the same book "
        "without them, after saved trading costs.",
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
    stats = svc.book_stats(period)
    adopted = stats.iloc[0]
    st.caption(f"{period} · costs included · Sharpe in excess of cash")
    metrics = st.columns(4)
    metrics[0].metric("Sharpe · excess cash", f"{adopted['sharpe']:.3f}")
    metrics[1].metric("CAGR · with cash", components.pct(adopted["cagr_with_cash"], 2))
    metrics[2].metric("Max drawdown · excess cash", components.pct(adopted["max_drawdown"], 2))
    metrics[3].metric("Trading costs · annualized", components.pct(adopted["cost"], 2))
    drawdown = view == "Drawdown"
    daily = svc.curves(period, drawdown=drawdown)
    components.chart(curves(daily, drawdown), key="adopted_curves")
    st.caption(
        "Curves include cash interest and rebase on the close preceding this period "
        "(initial capital 1 for 2010). Curve drawdown therefore differs from the reported "
        "excess-cash maximum drawdown. No final-test sessions are loaded."
    )
    st.subheader("Same period. Two exit policies.")
    displayed = pd.DataFrame(
        [
            {
                "Book": LABELS[row["Book"]],
                "Sharpe (excess cash)": f"{row['sharpe']:.3f}",
                "CAGR with cash": components.pct(row["cagr_with_cash"], 2),
                "CAGR excluding cash": components.pct(row["cagr"], 2),
                "Max DD (excess cash)": components.pct(row["max_drawdown"], 2),
                "Costs / year": components.pct(row["cost"], 2),
            }
            for _, row in stats.iterrows()
        ]
    )
    st.dataframe(displayed, hide_index=True, width="stretch")
    st.caption(
        "Saved backtest point estimates, not a guarantee that the monitor improves "
        "future returns. Reused development periods and model selection limit inference."
    )
    with st.expander("Execution, sizing, exits and cash assumptions"):
        st.dataframe(
            pd.DataFrame(svc.summary.design, columns=["Part", "Saved choice"]),
            hide_index=True,
            width="stretch",
        )
        st.write(
            "R0 eligibility uses the previous year's cutoff, not a threshold fitted "
            "to the current test year's outcomes (Decision 110d)."
        )
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
    audit = svc.summary.audit
    st.markdown("**How much confidence is warranted?**")
    st.write(
        f"{audit.trials} tracked designs; PBO {audit.pbo:.2f}. Confirmation deflated "
        f"Sharpe {audit.dsr_2018_2023['132']:.2f}, below 0.95 (2018–2023). "
        "The final test remains locked in this snapshot. These results do not establish alpha."
    )
    st.divider()
    st.markdown("**Why use R0 rather than the best forecaster?**")
    st.write(
        "Improved forecasting did not produce the best trade selection. Entry-agent "
        "scores were not adopted; the position monitor is used for exits."
    )
    workspace.link("forecast", "Compare the forecasting evidence")
    workspace.link("strategy", "Open the earlier plan-ladder benchmark")
    workspace.provenance(svc)

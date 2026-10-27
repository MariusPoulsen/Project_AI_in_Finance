"""Matched current forecasters: measured points, explicit roles, no synthetic curves."""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import components, theme
from structural_break.app_ui.pages import workspace
from structural_break.services.research_summary import METRICS

HELP = {
    "ROC AUC": "Ranking: how often a reversion scores above a non-reversion. Higher is better; "
    "0.5 is chance ranking. This does not measure returns.",
    "PR AUC": "Precision–recall ranking for positive events. Higher is better; compare only "
    "within the same cohort because prevalence affects this metric.",
    "Brier score": "Mean squared error of predicted probabilities. Lower is better. "
    "It reflects calibration and discrimination.",
    "Log loss": "Probability loss that penalizes confidently wrong forecasts. Lower is better.",
}


def points(rows: pd.DataFrame, metric: str, selected: str) -> go.Figure:
    _, higher, digits = METRICS[metric]
    figure = go.Figure()
    short = {
        "A": "Model A",
        "R0": "Model B / R0",
        "B_rule_ou": "B+rule+ou",
        "B_rule_ou_track": "B+rule+ou+track",
    }
    for _, row in rows.iterrows():
        active = row["id"] == selected
        figure.add_trace(
            go.Scatter(
                x=[row[metric]],
                y=[short[row["id"]]],
                mode="markers+text",
                text=[f"{row[metric]:.{digits}f}"],
                textposition="middle right",
                marker={
                    "color": theme.MODEL_B if active else theme.MODEL_A,
                    "size": 12 if active else 9,
                    "symbol": "diamond" if active else "circle",
                },
                name=row["Model"],
                customdata=[[row["Model"], row["Role"]]],
                hovertemplate=f"%{{customdata[0]}}<br>%{{customdata[1]}}<br>{metric}: "
                f"%{{x:.{digits}f}}<extra></extra>",
                cliponaxis=False,
            )
        )
    lo, hi = float(rows[metric].min()), float(rows[metric].max())
    span = max(hi - lo, 0.001)
    figure.update_layout(
        theme.layout(
            height=330,
            showlegend=False,
            margin={"l": 130, "r": 55, "t": 15, "b": 55},
            xaxis={
                "title": f"{metric} · {'higher' if higher else 'lower'} is better",
                "range": [lo - span * 0.25, hi + span * 0.5],
                "tickformat": f".{digits}f",
            },
            yaxis={
                "autorange": "reversed",
                "categoryorder": "array",
                "categoryarray": list(short.values()),
                "fixedrange": True,
            },
        )
    )
    return figure


def records(rows: pd.DataFrame, selected: str, metric: str) -> None:
    secondary = "Log loss" if metric != "Log loss" else "Brier score"
    digits = METRICS[metric][2]
    body = "".join(
        "<tr" + (' class="selected"' if row["id"] == selected else "") + ">"
        f'<td>{html.escape(row["Model"])}<span class="role">{html.escape(row["Role"])}</span></td>'
        f'<td class="number">{row[metric]:.{digits}f}</td>'
        f'<td class="number">{row[secondary]:.4f}</td></tr>'
        for _, row in rows.iterrows()
    )
    st.markdown(
        '<div class="sb-table-scroll"><table class="sb-records">'
        '<thead><tr><th scope="col">Model / role</th><th scope="col">'
        f'{html.escape(metric)}</th><th scope="col">{secondary}</th></tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def render() -> None:
    components.page_header(
        "Compare reversion forecasts",
        "The preregistered OU model improves "
        "ranking; the original R0 model still selects the book.",
    )
    svc = workspace.service()
    if svc is None:
        return
    controls = st.columns([1.15, 1.4], gap="large")
    with controls[0]:
        period = workspace.period_control("sb_forecast_period")
    with controls[1]:
        metric = str(
            st.segmented_control(
                "Evaluation metric",
                list(METRICS),
                default="ROC AUC",
                selection_mode="single",
                key="sb_forecast_metric",
            )
            or "ROC AUC"
        )
    workspace.cohort_line(svc, period)
    st.caption(HELP[metric])
    rows = svc.forecasts(period)
    chart_column, table_column = st.columns([1.1, 1], gap="large")
    with table_column:
        selected = st.selectbox(
            "Inspect a model",
            list(rows["id"]),
            index=2,
            format_func=lambda key: str(rows.set_index("id").loc[key, "Model"]),
            key="sb_forecast_model",
        )
        records(rows, selected, metric)
    with chart_column:
        st.subheader("Matched point estimates")
        components.chart(points(rows, metric, selected), key="current_forecast_points")
        st.caption("Shared metric scale · point estimates only · no uncertainty export")
    st.divider()
    model = next(m for m in svc.manifest.models if m.id == selected)
    st.subheader(model.name)
    st.caption(model.role)
    st.write(model.explanation)
    with st.expander("Forecast diagnostics and limitations"):
        st.write(
            "Current-model per-event predictions, calibration curves, ROC/PR arrays, "
            "SHAP values and matched uncertainty intervals are not in this export. "
            "The point plot above compares published metrics; it is not a ROC curve."
        )
        st.write(
            "The event explorer contains the earlier accepted study. Its probabilities "
            "and SHAP values must not be interpreted as explanations of this model."
        )
        workspace.link("model", "Inspect the earlier accepted model study")
    st.caption(
        "Full model: the entry desk was evaluated on a separately selected subset. "
        "It is not a fifth matched-population forecaster in this table."
    )
    with st.expander("All forecast metrics and CSV export"):
        shown = rows.drop(columns="id").assign(
            Period=period,
            Events=svc.manifest.cohorts[period].n,
            Cohort=svc.manifest.cohorts[period].id,
        )
        st.dataframe(shown, hide_index=True, width="stretch")
        st.download_button(
            "Download this comparison",
            shown.to_csv(index=False),
            file_name=f"forecast-{svc.manifest.cohorts[period].id}.csv",
            mime="text/csv",
        )
    workspace.portfolio_bridge(svc, period)
    workspace.provenance(svc)

"""Matched current forecasters: measured points, explicit roles, no synthetic curves."""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import components, data, theme
from structural_break.app_ui.pages import workspace
from structural_break.services.research_summary import METRICS
from structural_break.services.workspace_diagnostics import baseline_outcomes

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
            height=440,
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

    def measurement(row: pd.Series, name: str, places: int) -> str:
        if pd.notna(row[name]):
            return f"{row[name]:.{places}f}"
        return "Policy" if str(row["id"]).startswith("BASELINE") else "Regional"

    body = "".join(
        "<tr" + (' class="selected"' if row["id"] == selected else "") + ">"
        f'<td>{html.escape(row["Model"])}<span class="role">{html.escape(row["Role"])}</span></td>'
        f'<td class="number">{measurement(row, metric, digits)}</td>'
        f'<td class="number">{measurement(row, secondary, 4)}</td></tr>'
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
        "Matched cohorts, shared metric scales and model diagnostics.",
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
    comparison = svc.forecast_comparison(period)
    catalogue = svc.catalogue()
    chart_column, table_column = st.columns([1.1, 1], gap="large")
    with table_column:
        selected = st.selectbox(
            "Inspect a model",
            list(catalogue["id"]),
            index=4,
            format_func=lambda key: str(catalogue.set_index("id").loc[key, "Model"]),
            key="sb_forecast_model",
        )
        records(comparison, selected, metric)
    with chart_column:
        st.subheader("Matched point estimates")
        components.chart(points(rows, metric, selected), key="current_forecast_points")
        st.caption("Shared metric scale · point estimates only · no uncertainty export")
    st.caption(
        "Baseline policies do not issue probabilities. Full uses a selected desk region; "
        "its metrics belong in the matched comparison below."
    )
    with st.expander("Baseline selection and observed outcomes"):
        outcome = data.registry()
        if outcome.service is None:
            st.info("The policy-outcome export is unavailable.")
        else:
            st.caption(
                "Frozen policy benchmark · 2022–2023 · separate from annual walk-forward scores"
            )
            st.dataframe(baseline_outcomes(outcome.service), hide_index=True, width="stretch")
    with st.expander("Full model · matched entry-desk region", expanded=selected == "FULL"):
        st.caption(
            "R0 top-40% region · compare the logistic desk base with the same base plus "
            "agent features. Selection-period rows begin in 2011."
        )
        regional = pd.DataFrame(svc.study.regional)
        requested = "2018–2023" if period.startswith("2018") else "2011–2017"
        regional = regional.loc[regional["Period"].eq(requested)]
        if regional.empty:
            st.info("Exact regional metrics for this period have not been exported.")
        else:
            st.dataframe(regional, hide_index=True, width="stretch")
    with st.expander("ROC and calibration · saved confirmation diagnostics"):
        st.caption("2018–2023 · four population forecasters · saved research figures")
        columns = st.columns(2)
        for column, name in zip(columns, ("roc.png", "calibration.png"), strict=True):
            if name in svc.manifest.files:
                column.image(str(svc.root / name), width="stretch")
    with st.expander("Forecasting rules"):
        st.table(workspace.forecast_rules())
    with st.expander("Forecast diagnostics and limitations"):
        st.write(
            "Current-model per-event predictions, ROC/PR arrays, "
            "SHAP values and matched uncertainty intervals are not in this export. "
            "The point plot above compares published metrics; it is not a ROC curve."
        )
        st.write(
            "The event explorer exposes registry inputs and observed outcomes. "
            "It does not substitute superseded model scores for current predictions."
        )
        st.dataframe(catalogue.drop(columns="id"), hide_index=True, width="stretch")
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
    workspace.link("book", "Compare portfolio returns")
    workspace.provenance(svc)

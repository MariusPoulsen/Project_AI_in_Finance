"""Current-model SHAP: saved native attributions only, never legacy explanations."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_bundle.features import feature_label
from structural_break.app_ui import charts, components, theme
from structural_break.app_ui.results import MODELS, Results


def render(results: Results, years: tuple[int, int]) -> None:
    st.markdown("**SHAP explanations**")
    if "shap_events" not in results.tables:
        st.info("Current-model SHAP values have not been exported yet.")
        st.caption(
            "This view requires explanations of the annual walk-forward fits. "
            "Frozen-study SHAP is a different model and is not substituted here."
        )
        with st.expander("Prepare the explanation export"):
            st.write(
                "Run this batch command in the development checkout holding the saved "
                "features and predictions, then publish its demo/results files:"
            )
            st.code("uv run --frozen python scripts/export_forecast_shap.py", language="shell")
            st.caption(
                "The job checks every reconstructed annual raw score before exporting "
                "a deterministic event sample. It does not alter research outputs."
            )
        return
    totals = results.tables["shap_events"]
    totals = totals.loc[totals.year.between(*years)]
    if totals.empty:
        components.empty_state("No SHAP sample was exported for these test years.")
        return
    choices = [m for m in ("r0", "bag5", "track") if m in set(totals.model)]
    model = st.selectbox(
        "Explain current model",
        choices,
        index=choices.index("bag5") if "bag5" in choices else 0,
        format_func=lambda key: MODELS[key],
        key="shap_model",
    )
    totals = totals.loc[totals.model.eq(model)]
    values = results.tables["shap_values"]
    values = values.loc[values.model.eq(model) & values.event_id.isin(totals.event_id)]
    st.caption(
        f"{totals.event_id.nunique():,} sampled events · {int(totals.year.min())}–"
        f"{int(totals.year.max())} · target-blind sample · native TreeSHAP log-odds"
    )
    st.markdown("**Feature influence in the exported sample**")
    importance = values.groupby("feature").contribution.agg(lambda v: v.abs().mean())
    importance = importance.nlargest(15).sort_values()
    figure = go.Figure(
        go.Bar(
            x=importance,
            y=[feature_label(f) for f in importance.index],
            orientation="h",
            marker_color=theme.MODEL_B,
            hovertemplate="%{y}<br>Mean |SHAP| %{x:.4f}<extra></extra>",
        )
    )
    figure.update_layout(
        theme.layout(
            height=430,
            showlegend=False,
            margin={"l": 230},
            xaxis={"title": "Mean |TreeSHAP| · seed-model log-odds"},
        )
    )
    components.chart(figure, key="headline_shap_importance")
    st.caption(
        "For a bagged model, this summarizes its seed fits. The bag averages "
        "probabilities, so averaged SHAP margins are not its probability decomposition."
    )
    st.markdown("**Explain one event**")
    forecasts = results.tables["forecasts"].set_index("event_id")
    controls = st.columns([3, 1])
    with controls[0]:
        event = st.selectbox(
            "Event",
            list(totals.event_id.drop_duplicates()),
            format_func=lambda key: (
                f"{forecasts.loc[key, 'pair_id']} · {str(forecasts.loc[key, 'event_date'])[:10]}"
            ),
            key="shap_event",
        )
    with controls[1]:
        seed = st.selectbox("Seed component", sorted(totals.seed.unique()), key="shap_seed")
    total = totals.loc[totals.event_id.eq(event) & totals.seed.eq(seed)].iloc[0]
    parts = values.loc[values.event_id.eq(event) & values.seed.eq(seed)].copy()
    parts["label"] = parts.feature.map(feature_label)
    parts = parts.sort_values("contribution", key=np.abs, ascending=False)
    explanation = {"base": float(total.base), "margin": float(total.margin), "contributions": parts}
    components.chart(charts.waterfall(explanation), key="headline_shap_event")
    st.caption(
        f"Base {total.base:+.3f} + feature contributions = margin {total.margin:+.3f}. "
        f"Raw seed probability {total.raw_probability:.2%}; published calibrated "
        f"model probability {float(forecasts.loc[event, f'p_{model}']):.2%}. "
        "SHAP explains model behaviour, not causality."
    )
    with st.expander("Feature values and exact contributions"):
        st.dataframe(parts[["feature", "value", "contribution"]], hide_index=True, width="stretch")
        st.download_button(
            "Download event SHAP",
            parts.to_csv(index=False),
            file_name=f"shap-{model}-{seed}-{event}.csv",
            mime="text/csv",
        )

"""Saved annual-model explanations. No fitting or provider calls during browsing."""

from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_bundle.features import feature_label
from structural_break.app_ui import charts, components, navigation, theme
from structural_break.app_ui.results import MODELS, Results

LABELS = {
    "logit_bag5": "Bagged forecast (log-odds)",
    "no_news": "No news available",
    "abstain": "Agent abstention",
    "explains_move": "News explains the move",
    "persistence": "News persistence",
    "relationship_change": "Relationship change",
    "persistence_x_explains": "Persistence × explains the move",
}


def label(feature: str) -> str:
    return LABELS.get(feature, feature_label(feature))


def tables(results: Results, model: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    prefix = "full_shap" if model.startswith("full") else "shap"
    events = results.tables.get(f"{prefix}_events", pd.DataFrame())
    values = results.tables.get(f"{prefix}_values", pd.DataFrame())
    if events.empty or values.empty:
        return pd.DataFrame(columns=["event_id"]), pd.DataFrame()
    return events.loc[events.model.eq(model)], values.loc[values.model.eq(model)]


def _totals(results: Results, model: str) -> pd.DataFrame:
    prefix = "full_shap" if model.startswith("full") else "shap"
    events = results.tables.get(
        f"{prefix}_events", pd.DataFrame(columns=["event_id", "model", "year"])
    )
    return events.loc[events.model.eq(model)]


def render_event(results: Results, event_id: str, *, key: str = "investigation") -> None:
    choices = [
        m
        for m in ("r0", "bag5", "track", "full", "full_base")
        if _totals(results, m).event_id.eq(event_id).any()
    ]
    if not choices:
        components.empty_state(
            "No current-model attribution is exported for this event. Tree SHAP uses a "
            "target-blind sample; Full explanations exist only for desk-scored events. "
            "No other event's explanation is substituted."
        )
        return
    model = navigation.selectbox(
        "Explain model",
        choices,
        f"{key}_shap_model",
        default="full" if "full" in choices else choices[0],
        format_func=lambda m: MODELS[m],
    )
    events, values = tables(results, model)
    _event(
        results,
        model,
        events.loc[events.event_id.eq(event_id)],
        values.loc[values.event_id.eq(event_id)],
        key=key,
    )


def _event(
    results: Results, model: str, totals: pd.DataFrame, values: pd.DataFrame, *, key: str
) -> None:
    linear = model.startswith("full")
    if not linear:
        options = [str(seed) for seed in sorted(totals.seed.unique())]
        seed = int(
            navigation.selectbox("Seed component", options, f"{key}_seed", default=options[0])
        )
        total = totals.loc[totals.seed.eq(seed)].iloc[0]
        parts = values.loc[values.seed.eq(seed)].copy()
    else:
        total = totals.iloc[0]
        parts = values.copy()
    parts["label"] = parts.feature.map(label)
    parts = parts.sort_values("contribution", key=np.abs, ascending=False)
    figure = charts.waterfall(
        {
            "base": float(total.base),
            "margin": float(total.margin),
            "contributions": parts.assign(
                label=parts.label.map(lambda text: "<br>".join(textwrap.wrap(text, 24)))
            )
            if linear
            else parts,
        }
    )
    if linear:
        figure.update_layout(margin={"l": 155, "r": 45}, font={"size": 11})
    components.chart(figure, key=f"{key}_waterfall")
    published = results.tables["forecasts"].set_index("event_id").loc[total.event_id, f"p_{model}"]
    st.caption(
        f"Base {total.base:+.3f} + contributions = {total.margin:+.3f} log-odds. "
        f"Published probability {float(published):.2%}. "
        "SHAP describes model behaviour, not causality."
    )
    if linear:
        st.caption(
            f"Exact linear SHAP against the annual training mean; {int(total.train_n):,} "
            f"training events through {int(total.train_last_year)}. "
            "The interaction is a separate input. These are interventional, "
            "not conditional, attributions for correlated features."
        )
        st.caption(
            "The Full and probability-only stacks have separately fitted coefficients. "
            "Their contributions are not a decomposition of the difference between "
            "the two probabilities."
        )
    else:
        st.caption(
            f"Native TreeSHAP explains this seed's raw probability "
            f"({total.raw_probability:.2%}), before calibration. "
            "Bagged models average seed probabilities: averaged margins are not "
            "an explanation of the bagged probability."
        )
    with st.expander("Feature values and exact contributions"):
        columns = [
            c
            for c in (
                "feature",
                "value",
                "training_mean",
                "training_std",
                "coefficient",
                "contribution",
            )
            if c in parts
        ]
        st.dataframe(parts[columns], hide_index=True, width="stretch")
        st.download_button(
            "Download event explanation",
            parts[columns].to_csv(index=False),
            file_name=f"shap-{model}-{total.event_id}.csv",
            mime="text/csv",
            key=f"{key}_download",
        )


def render(results: Results, years: tuple[int, int]) -> None:
    st.markdown("**SHAP explanations**")
    choices = []
    for model in ("r0", "bag5", "track", "full", "full_base"):
        totals = _totals(results, model)
        if not totals.empty and totals.year.between(*years).any():
            choices.append(model)
    if not choices:
        components.empty_state(
            "Current annual-model explanations have not been exported for these years."
        )
        return
    model = navigation.selectbox(
        "Explain current model",
        choices,
        "shap_model",
        default="bag5" if "bag5" in choices else choices[0],
        format_func=lambda m: MODELS[m],
    )
    totals, values = tables(results, model)
    totals = totals.loc[totals.year.between(*years)]
    values = values.loc[values.event_id.isin(totals.event_id)]
    linear = model.startswith("full")
    count = totals.event_id.nunique()
    universe = results.tables["forecasts"]
    denominator = int((universe.year.between(*years) & universe[f"p_{model}"].notna()).sum())
    st.caption(
        f"{count:,} / {denominator:,} scored events explained · {years[0]}–{years[1]} · "
        + (
            "all desk-scored events · exact linear SHAP"
            if linear
            else "target-blind annual sample · native seed-model TreeSHAP"
        )
    )
    importance = (
        values.groupby("feature")
        .contribution.agg(lambda v: v.abs().mean())
        .nlargest(15)
        .sort_values()
    )
    figure = go.Figure(
        go.Bar(
            x=importance,
            y=[label(f) for f in importance.index],
            orientation="h",
            marker_color=theme.MODEL_B,
            hovertemplate="%{y}<br>Mean |SHAP| %{x:.4f}<extra></extra>",
        )
    )
    figure.update_layout(
        theme.layout(
            height=430 if not linear else 290,
            showlegend=False,
            margin={"l": 230},
            xaxis={"title": "Mean |SHAP| · model log-odds"},
        )
    )
    components.chart(figure, key="headline_shap_importance")
    if not linear:
        st.caption(
            "Global influence summarizes seed fits, not changes in the averaged bagged probability."
        )
    forecasts = universe.set_index("event_id")
    options = list(totals.event_id.drop_duplicates())
    event_id = navigation.selectbox(
        "Event",
        options,
        "shap_event",
        default=options[0],
        format_func=lambda event: (
            f"{forecasts.loc[event, 'pair_id']} · {str(forecasts.loc[event, 'event_date'])[:10]}"
        ),
    )
    _event(
        results,
        model,
        totals.loc[totals.event_id.eq(event_id)],
        values.loc[values.event_id.eq(event_id)],
        key="lab",
    )

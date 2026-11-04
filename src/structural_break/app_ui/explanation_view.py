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
from structural_break.services.forecast_explanations import OTHER

LABELS = {
    "logit_bag5": "Bagged forecast (log-odds)",
    "no_news": "No news available",
    "abstain": "Agent abstention",
    "explains_move": "News explains the move",
    "persistence": "News persistence",
    "relationship_change": "Relationship change",
    "persistence_x_explains": "Persistence × explains the move",
}


OTHER_LABEL = "All other inputs (summed)"


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


#: The models whose explanations the pages offer. The probability-only stack beside the full
#: model has a single input (the bagged forecast), so its explanation would always be one bar.
EXPLAINED = ("bag5", "track", "r0", "full")
TREE_NOTE = {
    "r0": "TreeSHAP of the R0 model in log-odds, before calibration.",
    "bag5": "TreeSHAP averaged over the bag's five models, in log-odds.",
    "track": "TreeSHAP averaged over the bag's five models, in log-odds.",
}


def _explained_neighbour(results: Results, event_id: str) -> tuple[str, str] | None:
    """An explained event of the same pair, else of the same year, as (event id, pair)."""
    explained = set(_totals(results, "bag5").event_id) | set(_totals(results, "full").event_id)
    forecasts = results.tables["forecasts"]
    this = forecasts.loc[forecasts.event_id.eq(event_id)]
    if this.empty or not explained:
        return None
    candidates = forecasts.loc[forecasts.event_id.isin(explained)]
    for same in (candidates.pair_id.eq(this.pair_id.iat[0]), candidates.year.eq(this.year.iat[0])):
        if same.any():
            row = candidates.loc[same].sort_values("event_date").iloc[-1]
            return str(row.event_id), str(row.pair_id)
    return None


def render_event(results: Results, event_id: str, *, key: str = "investigation") -> None:
    choices = [m for m in EXPLAINED if _totals(results, m).event_id.eq(event_id).any()]
    if not choices:
        components.empty_state(
            "This event has no saved explanation. No other event's explanation is shown in "
            "its place."
        )
        example = _explained_neighbour(results, event_id)
        if example is not None and st.button(
            "Open a similar event that has an explanation",
            icon=":material/arrow_forward:",
            key=f"{key}_explained_example",
        ):
            navigation.switch("event", event=example[0], pair=example[1])
        return
    model = navigation.selectbox(
        "Explain model",
        choices,
        f"{key}_shap_model",
        default=choices[0],
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
    parts = values.copy()
    if linear:
        total = totals.iloc[0]
        base, margin = float(total.base), float(total.margin)
    else:
        # Contributions are averaged over the bag's seed models; so are base and margin.
        base, margin = float(totals.base.mean()), float(totals.margin.mean())
        parts = parts.loc[parts.feature.ne(OTHER)]
    parts["label"] = parts.feature.map(label)
    parts = parts.sort_values("contribution", key=np.abs, ascending=False)
    figure = charts.waterfall(
        {
            "base": base,
            "margin": margin,
            "contributions": parts.assign(
                label=parts.label.map(lambda text: "<br>".join(textwrap.wrap(text, 24)))
            )
            if linear
            else parts,
        },
        limit=8 if linear else 12,
    )
    if linear:
        figure.update_layout(margin={"l": 155, "r": 45}, font={"size": 11})
    components.chart(figure, key=f"{key}_waterfall")
    event_id = str(totals.event_id.iloc[0])
    forecasts = results.tables["forecasts"]
    published = float(forecasts.loc[forecasts.event_id.eq(event_id), f"p_{model}"].iloc[0])
    st.caption(
        f"Base {base:+.3f} + contributions = {margin:+.3f} log-odds. "
        f"Published probability {published:.2%}. "
        "SHAP describes model behaviour, not causality."
    )
    if linear:
        total = totals.iloc[0]
        st.caption(
            "The full model is a logistic stack on top of the bagged model. Its "
            "“Bagged forecast” bar is the whole bagged model: choose “B+rule+ou, bagged” "
            "above to see which inputs drove that forecast. Exact linear SHAP against the "
            f"annual training mean; {int(total.train_n):,} training events through "
            f"{int(total.train_last_year)}."
        )
    else:
        st.caption(
            TREE_NOTE[model]
            + " The bars add up to the models' average log-odds before calibration "
            f"({1 / (1 + np.exp(-margin)):.2%}); the published probability averages the "
            "models' probabilities and is then calibrated, so it is close to, not equal to, "
            "this value. The chart shows the 12 largest effects and sums the rest in “All other "
            "features”; the table below lists the 15 largest."
        )
    with st.expander("Input values and contributions"):
        table = values.assign(
            label=values.feature.map(lambda f: OTHER_LABEL if f == OTHER else label(f))
        )
        columns = [
            c
            for c in (
                "label",
                "value",
                "training_mean",
                "training_std",
                "coefficient",
                "contribution",
            )
            if c in table
        ]
        table = table.sort_values("contribution", key=np.abs, ascending=False)[columns]
        st.dataframe(table, hide_index=True, width="stretch")
        st.download_button(
            "Download event explanation",
            table.to_csv(index=False),
            file_name=f"shap-{model}-{event_id}.csv",
            mime="text/csv",
            key=f"{key}_download",
        )


def _importance(results: Results, model: str, years: tuple[int, int]) -> pd.Series:
    """Mean absolute contribution per input over every explained event in the years."""
    if model.startswith("full"):
        totals, values = tables(results, model)
        chosen = totals.loc[totals.year.between(*years), "event_id"]
        values = values.loc[values.event_id.isin(chosen)]
        return values.groupby("feature").contribution.agg(lambda v: v.abs().mean())
    summary = results.tables["shap_summary"]
    part = summary.loc[summary.model.eq(model) & summary.year.between(*years)]
    grouped = part.groupby("feature")[["sum_abs", "n"]].sum()
    return grouped.sum_abs / grouped.n


def render(results: Results, years: tuple[int, int]) -> None:
    st.markdown("**SHAP explanations**")
    choices = []
    for model in EXPLAINED:
        totals = _totals(results, model)
        if not totals.empty and totals.year.between(*years).any():
            choices.append(model)
    if not choices:
        components.empty_state("Annual-model explanations have not been exported for these years.")
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
    linear = model.startswith("full")
    count = totals.event_id.nunique()
    universe = results.tables["forecasts"]
    denominator = int((universe.year.between(*years) & universe[f"p_{model}"].notna()).sum())
    st.caption(
        f"{count:,} / {denominator:,} scored events explained · {years[0]}–{years[1]} · "
        + ("exact linear SHAP" if linear else "native TreeSHAP, averaged over the seed models")
    )
    importance = _importance(results, model, years).nlargest(15).sort_values()
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
    forecasts = universe.set_index("event_id")
    explained = totals.event_id.astype(str).drop_duplicates()
    traded = explained[explained.map(forecasts.traded).fillna(False).astype(bool)]
    options = list(traded if len(traded) else explained)
    st.caption(
        "Pick one of the adopted book's trades below; every event's own explanation is on its "
        "event page."
    )
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

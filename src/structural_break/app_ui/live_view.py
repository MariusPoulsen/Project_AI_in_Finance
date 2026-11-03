"""Live scoring and what-if on the event page, with the saved final-test models."""

from __future__ import annotations

import hashlib
import time

import numpy as np
import pandas as pd
import streamlit as st

from structural_break.app_bundle.features import feature_label
from structural_break.app_ui import charts, components
from structural_break.app_ui import results as published
from structural_break.app_ui.results import Results
from structural_break.services import live_scoring

#: Inputs offered for editing: the event's largest effects with a known value.
EDITABLE = 4


@st.cache_resource(show_spinner="Loading and checking the saved models…", max_entries=1)
def _model(digest: str) -> live_scoring.LiveModel | None:
    del digest  # cache key: the results manifest
    found = published.load()
    if found is None or "live.json" not in found.manifest["files"]:
        return None
    return live_scoring.load(published.FOLDER, found.manifest, found.tables["forecasts"])


def model(results: Results) -> live_scoring.LiveModel | None:
    if "live.json" not in results.manifest.get("files", {}):
        return None
    digest = hashlib.sha256(str(sorted(results.manifest["files"].items())).encode()).hexdigest()
    return _model(digest)


def _bounds(column: pd.Series, value: float) -> tuple[float, float]:
    """The 1st to 99th percentile of the input, widened to include this event's value."""
    finite = column[np.isfinite(column)]
    low, high = (float(q) for q in np.quantile(finite, [0.01, 0.99]))
    return min(low, value), max(high, value)


def _waterfall(score: live_scoring.Score, columns: list[str], key: str) -> None:
    parts = pd.DataFrame({"feature": columns, "contribution": score.contributions[0]})
    parts["label"] = parts.feature.map(feature_label)
    parts = parts.sort_values("contribution", key=np.abs, ascending=False)
    figure = charts.waterfall(
        {"base": float(score.base[0]), "margin": float(score.margin[0]), "contributions": parts},
        limit=10,
    )
    components.chart(figure, key=key)


def render(results: Results, event_id: str, year: int) -> None:
    live = model(results)
    if live is None:
        components.empty_state("The saved models are not in this deployment.")
        return
    if year not in live.years:
        components.empty_state(
            "Live scoring covers the final-test events (2024–2025), whose bagged models "
            "ship with the app. Open a 2024 or 2025 event to score it live."
        )
        return
    row = live.event(event_id)
    if row is None:
        components.empty_state("This event's inputs are not among the saved ones.")
        return
    columns = live.columns
    original = row.to_frame().T[columns].astype(float)
    started = time.perf_counter()
    score = live.score(year, original)
    elapsed = 1000 * (time.perf_counter() - started)
    forecasts = results.tables["forecasts"]
    stored = float(forecasts.loc[forecasts.event_id.eq(event_id), "p_bag5"].iloc[0])
    st.markdown("**Scored live by the saved bagged model**")
    cols = st.columns(3)
    cols[0].metric("Live probability", f"{score.probability[0]:.2%}")
    cols[1].metric("Published probability", f"{stored:.2%}")
    cols[2].metric("Scoring time", f"{elapsed:.0f} ms")
    if abs(float(score.probability[0]) - stored) < 1e-6:
        st.success(
            "The five saved models, averaged and calibrated, reproduce the published forecast.",
            icon=":material/check_circle:",
        )
    else:
        st.error("The live score differs from the published forecast.", icon=":material/error:")
    st.markdown("**What if an input had been different?**")
    contributions = pd.Series(score.contributions[0], index=columns)
    finite = [
        c
        for c in contributions.abs().sort_values(ascending=False).index
        if np.isfinite(original[c].iat[0])
    ]
    choices = finite[:EDITABLE]
    edited = original.copy()
    with st.form(f"whatif_{event_id}", border=True):
        st.caption(
            "The four inputs that moved this forecast the most. Change them and score again; "
            "values are limited to the range seen in the final-test events."
        )
        grid = st.columns(2)
        for number, column in enumerate(choices):
            value = float(original[column].iat[0])
            observed = live.inputs[column]
            distinct = np.unique(observed[np.isfinite(observed)])
            with grid[number % 2]:
                if len(distinct) <= 6:
                    options = sorted({*distinct.tolist(), value})
                    edited[column] = st.selectbox(
                        feature_label(column),
                        options,
                        index=options.index(value),
                        key=f"wi_{column}",
                    )
                else:
                    low, high = _bounds(observed, value)
                    edited[column] = st.slider(
                        feature_label(column),
                        min_value=low,
                        max_value=high,
                        value=value,
                        step=(high - low) / 200 or 1.0,
                        format="%.3f",
                        key=f"wi_{column}",
                    )
        submitted = st.form_submit_button("Score the changed event", icon=":material/play_arrow:")
    if not submitted:
        return
    changed = live.score(year, edited)
    before, after = float(score.probability[0]), float(changed.probability[0])
    cols = st.columns(2)
    cols[0].metric(
        "New probability",
        f"{after:.2%}",
        delta=f"{100 * (after - before):+.2f} pts",
        delta_color="normal",
    )
    moved = [c for c in choices if not np.isclose(edited[c].iat[0], original[c].iat[0])]
    cols[1].metric("Inputs changed", str(len(moved)))
    _waterfall(changed, columns, key=f"whatif_waterfall_{event_id}")
    st.caption(
        "Only the chosen inputs change; everything else stays at this event's values. In the "
        "market these inputs move together, so this shows how the model responds, not what "
        "would have happened."
    )

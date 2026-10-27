"""Pair Detail: prices, frozen spread, relationship history, events and explanations."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, theme
from structural_break.app_ui.context import current
from structural_break.services.workspace_diagnostics import registry_events


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Pair detail",
        "The frozen spread of one business-peer pair, its monthly relationship tests, and "
        "each divergence event with point-in-time inputs and observed outcomes.",
    )
    components.synthetic_banner(service.identity)
    pairs = service.pairs()
    if pairs.empty:
        components.empty_state("No pairs are published in this bundle.")
        return
    available = pairs.sort_values(["series_available", "assessment_events_n"], ascending=False)
    options = available["pair_id"].tolist()
    requested = st.session_state.get("sb_pair")
    index = options.index(requested) if requested in options else 0
    pair_id = st.selectbox(
        "Pair",
        options,
        index=index,
        format_func=lambda p: (
            p.replace("__", " vs ")
            + (
                ""
                if bool(available.set_index("pair_id").at[p, "series_available"])
                else " (events only)"
            )
        ),
    )
    if pair_id != requested:
        st.session_state["sb_pair"] = pair_id
        st.session_state["sb_event"] = None
    info = pairs.set_index("pair_id").loc[pair_id]
    st.markdown(
        f'<span class="sb-chip">{info["leg_a"]} / {info["leg_b"]}</span>'
        f'<span class="sb-chip">{info["business_group"]}</span>'
        f'<span class="sb-chip">{info["sector"]}</span>'
        f'<span class="sb-chip">{int(info["events_n"])} events, '
        f"{int(info['assessment_events_n'])} in assessment</span>",
        unsafe_allow_html=True,
    )
    events = registry_events(service)
    events = events.loc[events.pair_id.eq(pair_id)]
    with st.spinner("Loading the frozen pair history…"):
        series = service.pair_series(pair_id)

    if series is None or series.state.empty:
        components.empty_state(
            "Daily prices and spread history for this pair are not in this demo bundle (it carries "
            "a showcase subset to stay small). Its registry events are still listed below; "
            "the full workspace shows every pair."
        )
    else:
        state = series.state.copy()
        state["trading_date"] = pd.to_datetime(state["trading_date"])
        first, last = state["trading_date"].min().date(), state["trading_date"].max().date()
        focus = st.session_state.get("sb_event")
        focus_row = events.loc[events["event_id"].eq(focus)] if focus else events.iloc[0:0]
        if len(focus_row):
            center = focus_row["date"].iloc[0].date()
            default = (
                max(first, center - timedelta(days=270)),
                min(last, center + timedelta(days=120)),
            )
        else:
            default = (max(first, last - timedelta(days=3 * 365)), last)
        window = st.slider(
            "Window", min_value=first, max_value=last, value=default, format="MMM YYYY"
        )
        start, end = window
        in_window = state.loc[state["trading_date"].dt.date.between(start, end)]
        components.chart(
            charts.spread_bands(
                in_window,
                entry=float(protocol["entry_z"]),
                success=float(protocol["success_z"]),
                adverse=float(protocol["adverse_z"]),
            ),
            key="pair_bands",
        )
        components.legend(
            [
                (f"±{protocol['entry_z']:g} entry", theme.ENTRY),
                (f"±{protocol['success_z']:g} reversion", theme.MODEL_B),
                (f"±{protocol['adverse_z']:g} adverse stop", theme.ADVERSE),
                ("Shaded: not ACTIVE", theme.INACTIVE),
            ]
        )
        left, right = st.columns(2)
        with left:
            st.markdown("**Prices, rebased to 100**")
            prices = service.normalised_prices(series, start, end)
            if prices.empty:
                components.empty_state("No prices in this window.")
            else:
                components.chart(
                    charts.normalised_prices(prices, info["leg_a"], info["leg_b"]), key="prices"
                )
        with right:
            st.markdown("**Monthly hedge ratio (teal = ACTIVE)**")
            snapshots = series.snapshots
            if snapshots.empty or "beta" not in snapshots:
                components.empty_state("No monthly relationship snapshots for this pair.")
            else:
                snaps = snapshots.loc[
                    pd.to_datetime(snapshots["estimation_date"]).dt.date.between(
                        start - timedelta(days=31), end
                    )
                ]
                components.chart(
                    charts.beta_history(snaps if len(snaps) else snapshots), key="beta"
                )
        with st.expander("Monthly relationship diagnostics"):
            st.dataframe(
                series.snapshots.drop(columns=["pair_id"], errors="ignore"),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Each month the hedge ratio and spread statistics are re-estimated on the trailing "
                "formation window and frozen for the following month, so every z-score uses only "
                "information available at the time."
            )

    st.subheader("Divergence events")
    if events.empty:
        components.empty_state("This pair has no published development events at this horizon.")
        return
    table = events.drop(columns=["y_revert_success"])
    st.caption(
        "Current walk-forward event probabilities and SHAP values have not been exported. "
        "Registry inputs below do not substitute an older model's predictions."
    )
    st.dataframe(table.drop(columns="event_id"), hide_index=True, width="stretch")
    options = list(table.event_id)
    focus = st.session_state.get("sb_event")
    event_id = st.selectbox(
        "Inspect event",
        options,
        index=options.index(focus) if focus in options else 0,
        format_func=lambda key: str(table.set_index("event_id").loc[key, "date"])[:10],
    )
    st.subheader("SEC evidence available at event close")
    evidence = service.evidence(horizon, event_id)
    if evidence:
        st.dataframe(
            pd.DataFrame({"Field": list(evidence), "Value": [str(v) for v in evidence.values()]}),
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No evidence fields are exported for this event.")
    st.caption(
        "Unavailable, unscheduled and invalid evidence remains UNKNOWN, "
        "never neutral tone or confirmed absence."
    )

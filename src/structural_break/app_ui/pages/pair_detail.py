"""Pair Detail: prices, frozen spread, relationship history, events and explanations."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, theme
from structural_break.app_ui.context import current
from structural_break.app_ui.results import EXIT_LABELS, Results, event_table


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Pair detail",
        "The frozen spread of one business-peer pair, its monthly relationship tests, each "
        "divergence with the headline forecasters' probabilities, and the adopted book's "
        "trades on the pair.",
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
    events = service.pair_events(horizon, pair_id)
    with st.spinner("Loading the frozen pair history…"):
        series = service.pair_series(pair_id)

    if series is None or series.state.empty:
        components.empty_state(
            "Daily prices and spread history for this pair are not in this demo bundle (it carries "
            "a showcase subset to stay small). Its events and explanations are still listed below; "
            "the full workspace shows every pair."
        )
    else:
        state = series.state.copy()
        state["trading_date"] = pd.to_datetime(state["trading_date"])
        first, last = state["trading_date"].min().date(), state["trading_date"].max().date()
        focus = st.session_state.get("sb_event")
        focus_row = events.loc[events["event_id"].eq(focus)] if focus else events.iloc[0:0]
        if not len(focus_row) and focus and ctx.results is not None:
            forecasts = ctx.results.tables["forecasts"]
            hit = forecasts.loc[forecasts["event_id"].eq(focus), "event_date"]
            focus_row = pd.DataFrame({"date": hit.to_numpy()})
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
        window_events = events.loc[events["date"].dt.date.between(start, end)]
        components.chart(
            charts.spread_bands(
                in_window,
                window_events,
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
    if ctx.results is not None:
        _headline_events(ctx.results, pair_id, events)
        return
    if events.empty:
        components.empty_state("This pair has no published development events at this horizon.")
        return
    table = events[
        ["event_id", "date", "research_partition", "baseline1_eligible", "p_A", "p_B", "outcome"]
    ].copy()
    table["date"] = table["date"].dt.date
    focus = st.session_state.get("sb_event")
    selection = st.dataframe(
        table.drop(columns=["event_id"]),
        hide_index=True,
        width="stretch",
        height=260,
        on_select="rerun",
        selection_mode="single-row",
        key=f"pair_events_{pair_id}",
        column_config={
            "date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
            "research_partition": "Period",
            "baseline1_eligible": st.column_config.CheckboxColumn("ACTIVE"),
            "p_A": st.column_config.ProgressColumn(
                "P(revert) A", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "p_B": st.column_config.ProgressColumn(
                "P(revert) B", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "outcome": "Outcome",
        },
    )
    rows = selection.selection.rows if selection else []
    if rows:
        event_id = str(table.iloc[rows[0]]["event_id"])
    elif focus in set(table["event_id"]):
        event_id = str(focus)
    else:
        explained = set(
            service.data(horizon).contribution_totals.get("event_id", pd.Series(dtype=str))
        )
        candidates = table.loc[table["event_id"].isin(explained), "event_id"]
        event_id = str(candidates.iloc[0] if len(candidates) else table.iloc[0]["event_id"])
    _event_panel(event_id, events)


def _event_panel(event_id: str, events: pd.DataFrame) -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    row = events.loc[events["event_id"].eq(event_id)].iloc[0]
    event_date: date = row["date"].date()
    st.markdown(f"#### Event on {event_date:%d %B %Y}")
    cols = st.columns(4)
    cols[0].metric("Model A P(revert)", components.pct(row["p_A"]))
    cols[1].metric(
        "Model B P(revert)",
        components.pct(row["p_B"]),
        delta=f"{100 * (row['p_B'] - row['p_A']):+.1f} pts vs A",
        delta_color="off",
    )
    cols[2].metric("Outcome", row["outcome"])
    cols[3].metric("Period", str(row["research_partition"]).capitalize())
    if row["research_partition"] == "fit":
        st.caption("Fit-period probabilities are in-sample: the models were trained on this event.")
    family = protocol["primary_family"]
    choice = st.radio(
        "Explain",
        [
            f"{family}_B_{protocol['primary_b_variant']}",
            f"{family}_A",
            "xgboost_B_both",
            "xgboost_A",
        ],
        horizontal=True,
        format_func=lambda key: {
            "logistic_B_both": "Logistic B (all SEC)",
            "logistic_A": "Logistic A",
            "xgboost_B_both": "XGBoost B (all SEC)",
            "xgboost_A": "XGBoost A",
        }.get(key, key),
    )
    explanation = service.explanation(horizon, event_id, choice)
    left, right = st.columns([3, 2])
    with left:
        if explanation is None:
            components.empty_state(
                "Explanations are stored for assessment-period events and showcase pairs only. "
                + (
                    ""
                    if service.identity.explanation_status == "AVAILABLE"
                    else service.identity.explanation_status
                )
            )
        else:
            st.markdown(
                f"Starting from the average event (log-odds {explanation['base']:+.2f}), these "
                f"features move the score to {explanation['margin']:+.2f}."
            )
            components.chart(charts.waterfall(explanation), key=f"waterfall_{event_id}_{choice}")
            st.caption(
                "Exact additive decomposition of the saved model's margin "
                + (
                    "(coefficient × standardised feature, i.e. linear SHAP against the "
                    "fitting-period mean). "
                    if choice.startswith("logistic")
                    else "(native XGBoost TreeSHAP). "
                )
                + f"Raw probability {components.pct(explanation['raw_probability'])}; after "
                "sigmoid "
                f"calibration {components.pct(explanation['calibrated_probability'])}."
            )
    with right:
        st.markdown("**SEC evidence available at the event close**")
        evidence = service.evidence(horizon, event_id)
        if not evidence:
            components.empty_state("No evidence fields for this event.")
        else:
            st.dataframe(
                pd.DataFrame({"Field": list(evidence), "Value": list(evidence.values())}),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "UNKNOWN means the evidence was unavailable, unscheduled or invalid. It is kept as "
                "UNKNOWN, never read as neutral tone or 'no catalyst'. Filing text itself is not "
                "part of the group snapshot."
            )


EVENT_COLUMNS: dict[str, Any] = {
    "date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
    "period": "Period",
    "p_r0": st.column_config.ProgressColumn(
        "P(revert) R0", min_value=0.0, max_value=1.0, format="%.3f"
    ),
    "p_bag5": st.column_config.ProgressColumn(
        "P(revert) bagged", min_value=0.0, max_value=1.0, format="%.3f"
    ),
    "p_track": st.column_config.ProgressColumn(
        "P(revert) +track", min_value=0.0, max_value=1.0, format="%.3f"
    ),
    "p_full": st.column_config.ProgressColumn(
        "P(revert) full model", min_value=0.0, max_value=1.0, format="%.3f"
    ),
    "traded": st.column_config.CheckboxColumn("Traded"),
    "outcome": "Outcome",
    "exit": "Book exit",
    "trade_bps": st.column_config.NumberColumn("Trade gross (bps)", format="%+.1f"),
}


def _headline_events(results: Results, pair_id: str, research_events: pd.DataFrame) -> None:
    table = event_table(results, pair_id)
    if table.empty:
        components.empty_state("This pair has no divergence scored walk-forward since 2010.")
    else:
        selection = st.dataframe(
            table[["date", *list(EVENT_COLUMNS)[1:]]].assign(date=table["date"].dt.date),
            hide_index=True,
            width="stretch",
            height=280,
            on_select="rerun",
            selection_mode="single-row",
            key=f"pair_headline_{pair_id}",
            column_config=EVENT_COLUMNS,
        )
        chosen = selection.selection.rows if selection else []
        focus = st.session_state.get("sb_event")
        if chosen:
            row = table.iloc[chosen[0]]
        elif focus in set(table["event_id"]):
            row = table.loc[table["event_id"].eq(str(focus))].iloc[0]
        else:
            traded = table.loc[table["traded"]]
            row = traded.iloc[0] if len(traded) else table.iloc[0]
        st.markdown(f"#### Event on {row['date']:%d %B %Y}")
        cols = st.columns(5)
        cols[0].metric("R0 P(revert)", components.pct(row["p_r0"]))
        cols[1].metric(
            "Bagged P(revert)",
            components.pct(row["p_bag5"]),
            delta=f"{100 * (row['p_bag5'] - row['p_r0']):+.1f} pts vs R0",
            delta_color="off",
        )
        cols[2].metric("+track P(revert)", components.pct(row["p_track"]))
        cols[3].metric("Full model", components.pct(row["p_full"]))
        cols[4].metric(
            "Reverted (label)",
            {"Reverted": "Yes", "Did not revert": "No"}.get(row["outcome"], "n/a"),
        )
        if row["traded"]:
            st.markdown(
                f'<span class="sb-chip">Traded by the adopted book</span>'
                f'<span class="sb-chip">Exit: {row["exit"]}</span>'
                f'<span class="sb-chip">Gross {row["trade_bps"]:+.1f} bps</span>',
                unsafe_allow_html=True,
            )
        elif row["candidate"]:
            st.caption(
                "In R0's top 20 % but not entered: skipped by the book's news, mean-crossing or "
                "cost filter, or by its capacity rules."
            )
        same_day = research_events.loc[
            research_events["date"].dt.date.eq(pd.Timestamp(row["date"]).date())
        ]
        if len(same_day):
            with st.expander("Why the research-layer models leaned this way (frozen A/B study)"):
                _event_panel(str(same_day["event_id"].iloc[0]), research_events)
    trades = results.tables["trades"]
    part = trades.loc[trades["pair_id"].eq(pair_id)].sort_values("entry_date", ascending=False)
    st.subheader("Trades of the adopted book on this pair")
    if part.empty:
        components.empty_state("The adopted book never traded this pair.")
        return
    st.dataframe(
        part.assign(
            gross_bps=1e4 * part["gross_return"],
            exit_reason=part["exit_reason"].map(EXIT_LABELS).fillna(part["exit_reason"]),
        )[
            [
                "entry_date",
                "exit_date",
                "long_leg",
                "exit_reason",
                "sessions",
                "size_nav",
                "gross_bps",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "entry_date": st.column_config.DateColumn("Entry", format="D MMM YYYY"),
            "exit_date": st.column_config.DateColumn("Exit", format="D MMM YYYY"),
            "long_leg": "Long",
            "exit_reason": "Exit",
            "sessions": st.column_config.NumberColumn("Sessions", format="%d"),
            "size_nav": st.column_config.NumberColumn("Size (share of NAV)", format="percent"),
            "gross_bps": st.column_config.NumberColumn("Gross (bps)", format="%+.1f"),
        },
    )
    st.caption(
        "Entry and exit at the close. Gross returns run from the entry close to the exit close "
        "as a share of the trade's gross notional; the book charges costs separately."
    )

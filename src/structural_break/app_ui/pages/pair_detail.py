"""Pair Detail: prices, frozen spread, relationship history, scored events and trades."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, navigation, theme
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
    requested = st.query_params.get("pair", st.session_state.get("sb_pair"))
    index = options.index(requested) if requested in options else 0
    pair_id = navigation.selectbox(
        "Pair",
        options,
        "pair",
        default=options[index],
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
    if st.query_params.get("event"):
        st.session_state["sb_event"] = st.query_params["event"]
    info = pairs.set_index("pair_id").loc[pair_id]
    if ctx.results is not None:
        scored = event_table(ctx.results, pair_id)
        count_label = (
            f"{len(scored):,} scored events, "
            f"{int(scored['period'].eq('holdout').sum()):,} in holdout"
        )
    else:
        count_label = (
            f"{int(info['events_n'])} events, {int(info['assessment_events_n'])} in assessment"
        )
    st.markdown(
        f'<span class="sb-chip">{info["leg_a"]} / {info["leg_b"]}</span>'
        f'<span class="sb-chip">{info["business_group"]}</span>'
        f'<span class="sb-chip">{info["sector"]}</span>'
        f'<span class="sb-chip">{count_label}</span>',
        unsafe_allow_html=True,
    )
    events = service.pair_events(horizon, pair_id)
    with st.spinner("Loading the frozen pair history…"):
        series = service.pair_series(pair_id)

    if series is None or series.state.empty:
        components.empty_state(
            "Daily prices and spread history for this pair are not in the verified history "
            "export. Its available events are listed below."
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
        window = navigation.date_window(first, last, default)
        start, end = window
        in_window = state.loc[state["trading_date"].dt.date.between(start, end)]
        # Markers come from the scored events (all years) when the headline results are in.
        marked = scored.rename(columns={"z_at_event": "z_signed"}) if ctx.results else events
        labels = (
            (("p_r0", "R0"), ("p_bag5", "bagged")) if ctx.results else (("p_A", "A"), ("p_B", "B"))
        )
        window_events = marked.loc[pd.to_datetime(marked["date"]).dt.date.between(start, end)]
        components.chart(
            charts.spread_bands(
                in_window,
                window_events,
                entry=float(protocol["entry_z"]),
                success=float(protocol["success_z"]),
                adverse=float(protocol["adverse_z"]),
                probabilities=labels,
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
                    charts.normalised_prices(prices, str(info["leg_a"]), str(info["leg_b"])),
                    key="prices",
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
        _headline_events(ctx.results, pair_id)
        return
    components.empty_state(
        "The headline results are not in this deployment, so this pair's scored events and "
        "trades cannot be listed."
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


def _headline_events(results: Results, pair_id: str) -> None:
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
        st.query_params["event"] = str(row["event_id"])
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

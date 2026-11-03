"""Look up the saved forecast for a pair on a date, with the input checked first."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from structural_break.app_ui import components, navigation

FIRST, LAST = date(2010, 1, 1), date(2025, 12, 31)
KEY = "lookup_result"


@dataclass(frozen=True)
class Lookup:
    """The outcome of one lookup: the event found, or the reason there is none."""

    event: pd.Series | None
    message: str


def find(events: pd.DataFrame, pair: str | None, day: date | None) -> Lookup:
    """The most recent scored divergence of ``pair`` on or before ``day``."""
    if not pair or pair not in set(events["pair"]):
        return Lookup(None, "Choose one of the listed pairs.")
    if not isinstance(day, date):
        return Lookup(None, "Enter a date.")
    if not FIRST <= day <= LAST:
        return Lookup(None, f"Choose a date between {FIRST:%d %b %Y} and {LAST:%d %b %Y}.")
    part = events[events["pair"].eq(pair)].sort_values("date")
    before = part[part["date"].dt.date.le(day)]
    name = pair.replace("__", " vs ")
    if before.empty:
        first = part["date"].iloc[0].date()
        return Lookup(
            None,
            f"{name} had no scored divergence on or before {day:%d %b %Y}. "
            f"Its first one was on {first:%d %b %Y}.",
        )
    event = before.iloc[-1]
    gap = (day - event["date"].date()).days
    when = "on that day" if gap == 0 else f"{gap} days earlier, on {event['date']:%d %b %Y}"
    return Lookup(event, f"The most recent divergence of {name} was {when}.")


def render(events: pd.DataFrame) -> None:
    pairs = sorted(events["pair"].unique())
    with st.container(border=True):
        st.markdown("**Look up a forecast**")
        with st.form("lookup", border=False):
            left, middle, right = st.columns([3, 2, 2], vertical_alignment="bottom")
            pair = left.selectbox(
                "Pair",
                pairs,
                index=None,
                placeholder="Type a ticker, e.g. KO",
                format_func=lambda p: p.replace("__", " vs "),
            )
            day = middle.date_input(
                "Date", value=LAST, min_value=FIRST, max_value=LAST, format="DD/MM/YYYY"
            )
            submitted = right.form_submit_button(
                "Find the forecast", icon=":material/search:", width="stretch"
            )
        if submitted:
            st.session_state[KEY] = find(events, pair, day)
        found: Lookup | None = st.session_state.get(KEY)
        if found is None:
            st.caption(
                "Pick a pair and a date to see the forecasts the models made for its most "
                "recent divergence on or before that date."
            )
            return
        if found.event is None:
            st.warning(found.message, icon=":material/info:")
            return
        event = found.event
        st.success(found.message, icon=":material/check_circle:")
        cols = st.columns(4)
        cols[0].metric("z at the event", f"{event['z_at_event']:+.2f}")
        cols[1].metric("R0", components.pct(event["p_r0"]))
        cols[2].metric("Bagged B+rule+ou", components.pct(event["p_bag5"]))
        cols[3].metric(
            "Full model",
            components.pct(event["p_full"]),
            help="Only for events the agent desk scored; n/a means no agent forecast.",
        )
        traded = "traded by the adopted book" if bool(event["traded"]) else "not traded"
        st.markdown(f"Outcome: **{event['outcome']}**, {traded}.")
        if st.button("Open this event", icon=":material/search_insights:", key="lookup_open"):
            navigation.switch("event", event=str(event["event_id"]), pair=str(event["pair"]))

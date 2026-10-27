"""Explore development registry inputs and outcomes without superseded scores."""

from __future__ import annotations

import streamlit as st

from structural_break.app_ui import components
from structural_break.app_ui.context import current, open_pair
from structural_break.services.workspace_diagnostics import registry_events


def render() -> None:
    service = current().service
    components.page_header(
        "Event explorer", "Registry inputs, relationship status and observed 20-session outcomes."
    )
    components.synthetic_banner(service.identity)
    rows = registry_events(service)
    st.caption(
        "Underlying event registry · separate from the matched scoring cohort. "
        "Current per-event predictions have not been exported."
    )
    controls = st.columns(3)
    periods = controls[0].multiselect(
        "Research period", list(rows["Period"].unique()), default=["2018–2023 · confirmation"]
    )
    query = controls[1].text_input("Pair contains", placeholder="e.g. KO or KO__PEP")
    active = controls[2].toggle("ACTIVE relationships only")
    if periods:
        rows = rows.loc[rows.Period.isin(periods)]
    if query:
        rows = rows.loc[rows.pair_id.str.contains(query, case=False, regex=False)]
    if active:
        rows = rows.loc[rows.baseline1_eligible.eq(True)]
    if rows.empty:
        components.empty_state("No events match. Change the period, pair query or ACTIVE filter.")
        return
    cols = st.columns(3)
    cols[0].metric("Events", f"{len(rows):,}")
    cols[1].metric("Pairs", f"{rows.pair_id.nunique():,}")
    cols[2].metric("Observed reversion share", components.pct(rows.y_revert_success.mean()))
    selection = st.dataframe(
        rows.drop(columns=["event_id", "y_revert_success"]),
        hide_index=True,
        width="stretch",
        height=460,
        on_select="rerun",
        selection_mode="single-row",
        key="scanner_table",
    )
    chosen = selection.selection.rows if selection else []
    if chosen and st.button("Open pair detail", type="primary"):
        row = rows.iloc[chosen[0]]
        open_pair(str(row["pair_id"]), str(row["event_id"]))
    st.download_button(
        "Download filtered registry", rows.to_csv(index=False), "event-registry.csv", "text/csv"
    )
    st.caption(
        "Outcomes use future observations for development evaluation, never as predictors. "
        "Missing evidence remains UNKNOWN."
    )

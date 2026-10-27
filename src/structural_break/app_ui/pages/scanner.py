"""Scanner: every scored divergence event, filterable, linked to Pair Detail."""

from __future__ import annotations

from datetime import date

import streamlit as st

from structural_break.app_ui import components
from structural_break.app_ui.context import current, open_pair
from structural_break.services.research_application import PARTITION_ORDER, ScannerFilters


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Scanner",
        "Every fresh divergence in the frozen development data, with the stored calibrated "
        "probability that the gap closes. Select a row to open the pair.",
    )
    components.synthetic_banner(service.identity)
    fit_start = date.fromisoformat(str(protocol["fit_start"]))
    end = date.fromisoformat(str(protocol["development_end"]))
    assessment_start = date.fromisoformat(str(protocol["assessment_start"]))

    with st.container(border=True):
        top = st.columns([2, 2, 3])
        window = top[0].date_input(
            "Event dates",
            value=(assessment_start, end),
            min_value=fit_start,
            max_value=end,
            help="The final test (2024–2025) is locked and cannot be selected.",
        )
        partitions = top[1].multiselect(
            "Research period",
            PARTITION_ORDER,
            default=["assessment"],
            format_func=lambda p: {
                "fit": "Fit (in-sample)",
                "calibration": "Calibration",
                "assessment": "Assessment (out-of-sample)",
            }[p],
        )
        groups = top[2].multiselect("Business groups", service.business_groups(horizon))
        bottom = st.columns([2, 2, 2, 1])
        minimum = bottom[0].slider("Minimum Model B probability", 0.0, 1.0, 0.0, 0.01)
        query = bottom[1].text_input("Pair contains", placeholder="e.g. KO or KO__PEP")
        active = bottom[2].toggle(
            "ACTIVE relationships only",
            help="Pairs whose monthly cointegration test passed at the event (Baseline 1). "
            "An exploratory subset, not a separate trading cohort.",
        )
    if not isinstance(window, tuple) or len(window) != 2:
        st.warning("Choose a start and an end date.")
        return
    rows = service.scanner(
        horizon,
        ScannerFilters(
            start=window[0],
            end=window[1],
            partitions=tuple(partitions),
            business_groups=tuple(groups),
            active_only=active,
            min_probability=minimum,
            pair_query=query,
        ),
    )
    if rows.empty:
        components.empty_state(
            "No events match these filters. Widen the date range, add a research period or lower "
            "the minimum probability."
        )
        return
    summary = service.scanner_summary(rows)
    cols = st.columns(4)
    cols[0].metric("Events", components.count(summary["events"]))
    cols[1].metric("Pairs", components.count(summary["pairs"]))
    cols[2].metric("Observed reversion rate", components.pct(summary["reverted"]))
    cols[3].metric(
        "Mean P(revert), B vs A",
        components.pct(summary["mean_p_b"]),
        delta=f"{100 * (summary['mean_p_b'] - summary['mean_p_a']):+.1f} pts vs A",
        delta_color="off",
    )
    threshold = float(protocol["candidate_threshold"])
    selection = st.dataframe(
        rows.drop(columns=["event_id"]),
        hide_index=True,
        width="stretch",
        height=460,
        on_select="rerun",
        selection_mode="single-row",
        key="scanner_table",
        column_config={
            "date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
            "pair": "Pair",
            "group": "Business group",
            "period": "Period",
            "ACTIVE": st.column_config.CheckboxColumn("ACTIVE"),
            "z_at_event": st.column_config.NumberColumn("z at event", format="%.2f"),
            "p_A": st.column_config.ProgressColumn(
                "P(revert) A", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "p_B": st.column_config.ProgressColumn(
                "P(revert) B", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "B_minus_A": st.column_config.NumberColumn("B − A", format="%+.3f"),
            "catalyst": "Catalyst",
            "outcome": "Outcome",
        },
    )
    chosen = selection.selection.rows if selection else []
    if chosen:
        row = rows.iloc[chosen[0]]
        st.success(f"Selected {row['pair']} on {row['date']:%d %b %Y}.")
        if st.button("Open pair detail", type="primary", icon=":material/open_in_new:"):
            open_pair(str(row["pair"]), str(row["event_id"]))
    st.download_button(
        "Download these rows (CSV)",
        rows.to_csv(index=False).encode(),
        file_name=f"scanner_h{horizon}.csv",
        mime="text/csv",
        icon=":material/download:",
    )
    st.caption(
        "Scores are stored retrospective research outputs, not forecasts issued on the date. "
        "Fit-period scores are in-sample. Outcomes are development labels "
        f"(reverted inside ±{protocol['success_z']:g} before ±{protocol['adverse_z']:g} within "
        f"{horizon} sessions). The research threshold of {threshold:.2f} is not a trade signal. "
        "Catalyst UNKNOWN means not scheduled or not extracted, never 'no news'."
    )
    components.provenance(
        {
            f"Evaluation (h{horizon})": service.identity.evaluations.get(horizon),
            "Probabilities": f"calibrated {protocol['primary_family']} A and "
            "B_{protocol['primary_b_variant']}",
            "Bundle": service.identity.bundle_id,
        }
    )

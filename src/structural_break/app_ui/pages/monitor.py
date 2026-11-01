"""Data and Model Monitor: versions, cohorts, source coverage, drift and inventory."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import charts, components, theme
from structural_break.app_ui.context import current
from structural_break.app_ui.results import Results
from structural_break.services import current_monitor as diagnostics

INVENTORY_COLUMNS: dict[str, Any] = {
    "bundle": "Saved bundle",
    "features": "Features",
    "chosen_parameters": "Chosen parameters",
    "calibrator_slope": st.column_config.NumberColumn("Calibrator slope", format="%.3f"),
    "calibrator_intercept": st.column_config.NumberColumn("Calibrator intercept", format="%.3f"),
    "calibrator_status": "Calibrator status",
    "reload_max_error": st.column_config.NumberColumn("Reload error", format="%.1e"),
    "assessment_brier": st.column_config.NumberColumn("Assessment Brier", format="%.4f"),
}


def render() -> None:
    ctx = current()
    service = ctx.service
    identity = service.identity
    components.page_header(
        "Data and model monitor",
        "What the results rest on: exact data and model identities, sample sizes per period, "
        "how much SEC evidence was actually available, how features shift over time, and the "
        "health of every saved model and of the agent desk.",
    )
    components.synthetic_banner(identity)
    st.subheader("Versions")
    versions = _result_versions(ctx.results)
    st.dataframe(
        pd.DataFrame({"Item": list(versions), "Value": [str(v) for v in versions.values()]}),
        hide_index=True,
        width="stretch",
    )
    with st.expander("Technical provenance"):
        st.caption(
            "These identifiers bind the source inputs, app packaging and the methodology "
            "authorized for the final test."
        )
        inputs = {
            "Accepted input snapshot": identity.primary_version,
            "Event registry": identity.registry_version,
            "SEC evidence generation": identity.intelligence_version,
            "Input registry protocol": service.protocol.get("version"),
            "Bundle identity": identity.bundle_id,
            "Data source": {
                "workspace": "Accepted workspace (read in memory)",
                "bundle": "Exported app bundle",
                "synthetic": "Synthetic preview",
            }[identity.source],
        }
        if ctx.results is not None:
            inputs["Freeze manifest SHA-256"] = ctx.results.manifest.get("freeze_manifest_sha256")
        st.dataframe(
            pd.DataFrame({"Input": list(inputs), "Identity": [str(v) for v in inputs.values()]}),
            hide_index=True,
            width="stretch",
        )
    _current_data()
    _headline_health(ctx.results)


def _current_data() -> None:
    ctx = current()
    if ctx.results is None:
        components.empty_state(
            "Current scored-event diagnostics are not in this deployment. "
            "The frozen study's partitions are not a substitute."
        )
        return
    events = diagnostics.event_inputs(
        ctx.results.tables["forecasts"],
        ctx.results.tables.get("diagnostic_inputs", ctx.service.data(ctx.horizon).events),
        final_included=ctx.results.final_included,
    )
    st.subheader("Samples per study period")
    st.dataframe(
        diagnostics.cohorts(events, final_included=ctx.results.final_included),
        hide_index=True,
        width="stretch",
        column_config={"Reversion rate": st.column_config.NumberColumn(format="percent")},
    )
    st.caption(
        "Each annual model trains on earlier years. Selection and holdout describe "
        "evaluation periods; they are not one fixed train/test split. Reversion rates "
        "use labelled events only. Unlabelled events remain in the event counts."
    )
    yearly = diagnostics.events_by_year(events)
    figure = go.Figure()
    for period, part in yearly.groupby("period", sort=False):
        figure.add_trace(
            go.Bar(
                x=part.year,
                y=part.events,
                name=str(period),
                marker_color=theme.PARTITION_COLORS[str(period)],
            )
        )
    figure.add_vline(x=2017.5, line_dash="dot", line_color=theme.MUTED)
    if ctx.results.final_included:
        figure.add_vline(x=2023.5, line_dash="dot", line_color=theme.MUTED)
    figure.update_layout(
        theme.layout(height=300, xaxis={"dtick": 2}, yaxis={"title": "Scored divergence events"})
    )
    components.chart(figure, key="current_events_year")
    st.subheader("SEC evidence coverage")
    st.caption(
        "Fit covers model selection (2010–2017); Calibration covers holdout validation "
        "(2018–2023). Each annual model fits and calibrates its probabilities on earlier data."
    )
    rows = diagnostics.coverage(events)
    components.chart(charts.coverage_lines(rows), key="coverage")
    table = diagnostics.coverage_table(rows)
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            name: st.column_config.NumberColumn(format="percent") for name in table.columns[1:]
        },
    )
    missing = int((~events.registry_available).sum())
    st.caption(
        f"Coverage uses all {len(events):,} current scored events. "
        f"{missing:,} have no matching row in the SEC input export and remain UNKNOWN; "
        "they are retained in the denominators. This view shows metadata and FinBERT tone."
    )
    st.subheader("Feature drift")
    features = diagnostics.drift_features(events)
    if not features:
        components.empty_state("No current-event feature values are exported.")
        return
    from structural_break.app_bundle.features import feature_label

    blocks = ["All feature groups", *dict.fromkeys(diagnostics.feature_block(f) for f in features)]
    from structural_break.app_ui import navigation

    block = navigation.selectbox(
        "Feature group", blocks, "drift_group", default="All feature groups"
    )
    if block != "All feature groups":
        features = [f for f in features if diagnostics.feature_block(f) == block]
    default = features.index("abs_z") if "abs_z" in features else 0
    feature = navigation.selectbox(
        "Feature",
        features,
        "drift_feature",
        default=features[default],
        format_func=lambda f: f"{feature_label(f)} ({f})",
    )
    profile = diagnostics.drift(events, feature)
    components.chart(charts.drift(profile, feature_label(feature)), key="drift")
    st.caption(
        "Distributions use the current scored events and their exported input values. "
        "Selection: 2010–2017; holdout: 2018–2023; final test only when exported. "
        "Peer, relationship state, earnings, momentum, OU and track inputs are included when "
        "the current diagnostics sidecar is deployed. Missing values remain missing."
    )
    with st.expander("Feature coverage by year"):
        st.dataframe(
            profile[["year", "period", "n", "missing_share"]],
            hide_index=True,
            width="stretch",
            column_config={
                "missing_share": st.column_config.NumberColumn("Missing values", format="percent")
            },
        )


FORECASTER_INVENTORY = [
    ("Original Model B (R0)", "Fixed XGBoost", "Selects the adopted book's trades"),
    (
        "B+rule+ou, bagged",
        "Five XGBoost seeds, feature subsampling",
        "Pre-registered Goal 1 model",
    ),
    (
        "B+rule+ou+track, bagged",
        "As above plus track record",
        "Best observed, post-hoc",
    ),
    (
        "Full model",
        "Bagged base plus entry-agent scores",
        "Reported, not adopted",
    ),
]
DESK_HEALTH = [
    ("Entry agents (pair news analyst, bull/bear debate, risk judge)", 6485, 31),
    ("Position monitor (after the FinBERT triage)", 7937, 4),
]


def _result_versions(results: Results | None) -> dict[str, object]:
    if results is None:
        return {"Headline results": "Not in this deployment"}
    manifest = results.manifest
    return {
        "Headline results export": f"{manifest.get('commit')} ({manifest.get('generated_at')})",
        "Scored event years": "–".join(str(y) for y in manifest.get("event_years", [])),
        "Final-test unlock": "Owner authorization recorded"
        if manifest.get("unlock_record")
        else "No unlock record",
        "Final test": "Included" if results.final_included else "Unlocked, results pending",
        "Agent desk": "Monitor exit adopted; entry scores evaluated in the Full model",
    }


def _headline_health(results: Results | None) -> None:
    st.subheader("Headline forecasters")
    if results is None:
        components.empty_state("The headline results are not in this deployment.")
        return
    forecasts = results.tables["forecasts"]
    counts = forecasts.groupby("year").agg(
        events=("event_id", "size"), labelled=("labelled", "sum"), traded=("traded", "sum")
    )
    rows = []
    for (name, method, role), column in zip(
        FORECASTER_INVENTORY, ["p_r0", "p_bag5", "p_track", "p_full"], strict=True
    ):
        scored = forecasts[column].notna()
        years = forecasts.loc[scored, "year"]
        rows.append(
            {
                "Model": name,
                "Method": method,
                "Role": role,
                "Years scored": f"{int(years.min())}–{int(years.max())}" if len(years) else "none",
                "Events scored": int(scored.sum()),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Every forecaster is refitted walk-forward each year on earlier years only; the full "
        "model has a score only where the entry agents read the event."
    )
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=counts.index, y=counts["events"], name="Scored divergences", marker_color="#9AA5B1"
        )
    )
    figure.add_trace(
        go.Bar(
            x=counts.index,
            y=counts["traded"],
            name="Traded by the book",
            marker_color=theme.MODEL_B,
        )
    )
    figure.update_layout(theme.layout(height=280, barmode="overlay", xaxis={"dtick": 1}))
    components.chart(figure, key="headline_years")

    st.subheader("Agent desk health")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Agent": agent,
                    "Cases sent": sent,
                    "Abstained or failed": failed,
                    "Abstention rate": failed / sent,
                }
                for agent, sent, failed in DESK_HEALTH
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Abstention rate": st.column_config.NumberColumn(format="percent"),
        },
    )
    review = results.summary.get("review", {})
    if review.get("answered"):
        st.caption(
            f"Development cases. Human review: {review['cases']} blind cases and "
            f"{review['claims']} cited claims; {review['confirmed']} of {review['answered']} "
            "answers confirm the agents. Language models never set a trade by themselves: the "
            "monitor's scores pass a fixed rule (adverse ≥ 5 and persistence ≥ 5)."
        )
    news = results.tables["news"]
    if len(news):
        st.subheader("Company news coverage")
        figure = go.Figure()
        for source, color in (("FNSPID", theme.MODEL_A), ("TickerTick", theme.MODEL_B)):
            part = news[news["source"].eq(source)]
            if part.empty:
                continue
            figure.add_trace(
                go.Scatter(
                    x=pd.PeriodIndex(part["month"], freq="M").to_timestamp(),
                    y=part["headlines"] / 250,
                    name=source,
                    mode="lines",
                    line={"color": color, "width": 1.6},
                )
            )
        figure.update_layout(
            theme.layout(
                height=300,
                yaxis={"title": "Company-specific headlines per ticker", "type": "log"},
            )
        )
        components.chart(figure, key="news_coverage")
        st.caption(
            "Monthly company-specific headlines per ticker (log scale). FNSPID is the development "
            "source and ends in 2023; TickerTick covers the final test: its bulk file to 25 May "
            "2025, then a much thinner live-API archive."
        )

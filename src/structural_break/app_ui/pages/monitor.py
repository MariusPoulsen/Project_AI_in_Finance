"""Data and Model Monitor: versions, cohorts, source coverage, drift and inventory."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import charts, components, theme
from structural_break.app_ui.context import current
from structural_break.app_ui.results import Results

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
    service, horizon = ctx.service, ctx.horizon
    identity = service.identity
    components.page_header(
        "Data and model monitor",
        "What the results rest on: exact data and model identities, sample sizes per period, "
        "how much SEC evidence was actually available, how features shift over time, and the "
        "health of every saved model and of the agent desk.",
    )
    components.synthetic_banner(identity)
    st.subheader("Versions")
    versions = {
        **_result_versions(ctx.results),
        "Data source": {
            "workspace": "Accepted workspace (read in memory)",
            "bundle": "Exported app bundle",
            "synthetic": "Synthetic preview",
        }[identity.source],
        "Primary research generation": identity.primary_version,
        "Event registry": identity.registry_version,
        "SEC evidence generation": identity.intelligence_version,
        **{f"Evaluation h{h}": v for h, v in sorted(identity.evaluations.items())},
        **{f"Backtest h{h}": v for h, v in sorted(identity.experiments.items())},
        "Explanations": identity.explanation_status,
        "Protocol": service.protocol.get("version"),
        "Bundle identity": identity.bundle_id,
    }
    st.dataframe(
        pd.DataFrame({"Item": list(versions), "Value": [str(v) for v in versions.values()]}),
        hide_index=True,
        width="stretch",
    )
    st.subheader(f"Samples per period, research layer, {horizon} sessions")
    cohorts = service.cohorts(horizon)
    if cohorts.empty:
        components.empty_state("No cohort record is published.")
    else:
        st.dataframe(
            cohorts,
            hide_index=True,
            width="stretch",
            column_config={
                "period": "Period",
                "n": st.column_config.NumberColumn("Events", format="localized"),
                "positives": st.column_config.NumberColumn("Reverted", format="localized"),
                "success_rate": st.column_config.NumberColumn("Reversion rate", format="percent"),
                "pairs": "Pairs",
                "issuers": "Issuers",
                "ACTIVE": st.column_config.NumberColumn("ACTIVE at event", format="localized"),
            },
        )
    components.chart(charts.events_by_year(service.events_by_year(horizon)), key="events_year")
    st.subheader("SEC evidence coverage")
    coverage = service.coverage(horizon)
    if coverage.empty:
        components.empty_state("No coverage record is published.")
    else:
        components.chart(charts.coverage_lines(coverage), key="coverage")
        table = service.coverage_table(horizon)
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={"indicator": "Indicator"}
            | {
                name: st.column_config.NumberColumn(name, format="percent")
                for name in table.columns[1:]
            },
        )
        st.caption(
            "Coverage is reported with full denominators. Missing evidence stays in the matched "
            "comparison as UNKNOWN. Catalysts were extracted for a frozen, target-blind schedule "
            "of 500 events; all others are UNKNOWN by design."
        )
    st.subheader("Feature drift")
    features = service.drift_features(horizon)
    if not features:
        components.empty_state("No feature profiles are published.")
    else:
        default = features.index("abs_z") if "abs_z" in features else 0
        from structural_break.app_bundle.features import feature_label

        feature = st.selectbox(
            "Feature", features, index=default, format_func=lambda f: f"{feature_label(f)} ({f})"
        )
        rows = service.drift(horizon, feature)
        components.chart(charts.drift(rows, feature_label(feature)), key="drift")
        st.caption(
            "Yearly distribution of the feature across all events; marker colour shows the "
            "research period (grey fit, gold calibration, teal assessment). The research "
            "layer's events end in 2023."
        )
    _headline_health(ctx.results)
    st.subheader("Research-layer model inventory (frozen A/B study)")
    st.dataframe(
        service.inventory(horizon),
        hide_index=True,
        width="stretch",
        column_config=INVENTORY_COLUMNS,
    )
    st.caption(
        "Three horizons × two families × five variants = thirty bundles of the frozen research "
        "study (Decisions 36–45). The headline forecasters and the agent desk are listed above."
    )


FORECASTER_INVENTORY = [
    ("Original Model B (R0)", "Fixed XGBoost, Decision 45", "Selects the adopted book's trades"),
    (
        "B+rule+ou, bagged",
        "Five XGBoost seeds, feature subsampling, Decision 86b",
        "Pre-registered Goal 1 model",
    ),
    (
        "B+rule+ou+track, bagged",
        "As above plus track record, Decision 88b",
        "Best observed, post-hoc",
    ),
    (
        "Full model",
        "Bagged base plus entry-agent scores, Decisions 110b–c, 119",
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
        "Freeze manifest SHA-256": manifest.get("freeze_manifest_sha256"),
        "Final-test unlock": manifest.get("unlock_record") or "No unlock record",
        "Final test": "Included" if results.final_included else "Unlocked, results pending",
        "Agent desk": "Run (Decisions 109–110); monitor exit adopted, entry scores reported",
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
            f"Development cases. Human review (Decision 113): {review['cases']} blind cases and "
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

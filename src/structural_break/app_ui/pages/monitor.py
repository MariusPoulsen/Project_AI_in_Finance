"""Data and Model Monitor: versions, cohorts, source coverage, drift and inventory."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components
from structural_break.app_ui.context import current

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
        "health of every saved model.",
    )
    components.synthetic_banner(identity)
    st.subheader("Versions")
    versions = {
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
        "Final test": "Locked (2024–2025 not loaded)",
        "Multi-agent Full System": "Not run (Decision 40)",
    }
    st.dataframe(
        pd.DataFrame({"Item": list(versions), "Value": [str(v) for v in versions.values()]}),
        hide_index=True,
        width="stretch",
    )
    st.subheader(f"Samples per period, {horizon} sessions")
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
            "research period (grey fit, gold calibration, teal assessment)."
        )
    st.subheader("Saved model inventory")
    st.dataframe(
        service.inventory(horizon),
        hide_index=True,
        width="stretch",
        column_config=INVENTORY_COLUMNS,
    )
    st.caption(
        "Three horizons × two families × five variants = thirty bundles. The agent layer's "
        "failure and abstention rates are not shown because the Full System was not run."
    )

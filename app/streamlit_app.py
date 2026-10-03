"""A read-only presentation shell for explicitly published research generations."""

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths
from structural_break.services.app_queries import (
    PairDetailView,
    ResearchQueryService,
    ResearchVersions,
)

DEVELOPMENT_END = date(2023, 12, 31)


def create_service() -> ResearchQueryService:
    from structural_break.services.model_a import ModelARepository

    root = Path(__file__).resolve().parents[1]
    runtime = RuntimeSettings(_env_file=root / ".env")
    paths = ProjectPaths.resolve(root, runtime.workspace_root)
    return ResearchQueryService(paths, ModelARepository(paths))


def render_versions(versions: ResearchVersions) -> None:
    if versions.synthetic:
        st.info("Synthetic research fixture")
    st.caption(
        f"Data: {versions.data_snapshot_id} · Relationships: {versions.relationship_version}"
    )
    st.caption("Final-test outcomes (2024–2025) remain locked. This app reads frozen outputs.")


def _number(value: Any, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    return f"{float(value):.{digits}f}"


def render_model(detail: PairDetailView) -> None:
    st.subheader("Model A research replay")
    if detail.versions.model is None:
        st.info("No Model A generation is published for this relationship history.")
        return
    model = {**detail.versions.model, **detail.versions.model.get("model_manifest", {})}
    st.caption(
        f"Model: {model.get('model_version', 'Unavailable')} · "
        f"Feature schema: {model.get('feature_schema_version', 'Unavailable')} · "
        f"Calibrator: {model.get('calibrator_version', 'Unavailable')} · "
        f"Policy: {model.get('ml_policy_version', model.get('policy_version', 'Unavailable'))}"
    )
    if detail.predictions.empty:
        st.info("No stored Model A prediction is available for this pair by the selected date.")
        return
    st.caption(
        "Stored development-event scores use the frozen research model. "
        "Training scores describe model fit. Validation outcomes fitted the calibrator, "
        "so calibrated validation scores and metrics are descriptive of that fitted sample."
    )
    latest = detail.predictions.iloc[0]
    columns = st.columns(3)
    columns[0].metric("Calibrated P(revert)", _number(latest.get("calibrated_probability")))
    columns[1].metric("Raw P(revert)", _number(latest.get("raw_probability")))
    qualified = latest.get("ml_qualified")
    columns[2].metric(
        "Model A threshold",
        "Unavailable" if pd.isna(qualified) else ("Pass" if qualified else "Below"),
    )
    st.caption(
        f"Event: {latest.get('event_id')} · Date: {latest.get('event_timestamp')} · "
        f"Evaluation role: {latest.get('evaluation_role', latest.get('partition', 'Unavailable'))}"
    )
    drivers = [
        *latest.get("top_shap_positive", []),
        *latest.get("top_shap_negative", []),
    ]
    if drivers:
        st.dataframe(pd.DataFrame(drivers), hide_index=True, width="stretch")
        st.caption(
            "Tree SHAP contributions explain the raw model margin; they are not causal effects."
        )
    else:
        st.info("No stored SHAP explanation is available for this event.")
    with st.expander("Stored event predictions"):
        st.dataframe(detail.predictions, hide_index=True, width="stretch")


def render_pair_detail(detail: PairDetailView) -> None:
    st.header(detail.pair_id.replace("__", " / "))
    if detail.state is None:
        st.info("No usable pair state exists on the selected research session.")
    else:
        columns = st.columns(4)
        columns[0].metric("Relationship", detail.state["pair_status"])
        columns[1].metric("Frozen z-score", _number(detail.state.get("z_score")))
        columns[2].metric("Hedge ratio β", _number(detail.state.get("beta")))
        columns[3].metric("Signal available", str(detail.state.get("data_available_at")))
    if detail.history.empty:
        st.info("No spread history is available in this date range.")
    else:
        st.subheader("Frozen daily spread state")
        st.line_chart(detail.history.set_index("trading_date")[["z_score"]])
        st.line_chart(detail.history.set_index("trading_date")[["spread"]])
    st.subheader("Effective monthly relationship")
    if detail.snapshot is None:
        st.info("No relationship estimate is effective at this date.")
    else:
        snapshot = detail.snapshot
        st.caption(
            f"Estimated: {snapshot.get('estimation_date')} · "
            f"Effective: {snapshot.get('effective_start')} · "
            f"Snapshot: {snapshot.get('relationship_snapshot_id')}"
        )
        st.json(snapshot, expanded=False)
    st.subheader("Fresh threshold crossings")
    if detail.crossings.empty:
        st.info("No fresh crossings are stored for this date range.")
    else:
        st.dataframe(detail.crossings, hide_index=True, width="stretch")
        st.caption("Baseline 1 eligibility requires ACTIVE status at the crossing.")
    render_model(detail)


def main(service: ResearchQueryService | None = None) -> None:
    st.set_page_config(page_title="Structural-Break Research", layout="wide")
    st.title("Structural-Break Research")
    st.caption("Quantitative pair research · frozen daily data · no live execution")
    try:
        service = service or create_service()
        versions = service.versions()
    except FileNotFoundError as error:
        if error.filename is None:
            st.info("No frozen research history is published. Run the documented batch jobs first.")
        else:
            st.error("A registered research artifact is missing. Verify the published manifests.")
        return
    except Exception:
        st.error("Frozen research outputs cannot be loaded. Verify the published manifests.")
        return
    render_versions(versions)
    upper = min(versions.last_session, DEVELOPMENT_END)
    if versions.first_session > upper:
        st.info("This history contains no unlocked development sessions.")
        return
    as_of = st.sidebar.date_input(
        "Research as of", value=upper, min_value=versions.first_session, max_value=upper
    )
    if not isinstance(as_of, date):
        st.error("Select one research date.")
        return
    page = st.sidebar.radio("Page", ("Scanner", "Pair Detail"))
    try:
        overview = service.scanner(as_of)
        if overview.session is None:
            st.info("No usable research session is available by this date.")
            return
        st.caption(f"Selected date: {as_of} · Last research session: {overview.session}")
        if page == "Scanner":
            st.header("Scanner")
            if overview.rows.empty:
                st.info("No usable pair states exist on this research session.")
            else:
                st.dataframe(overview.rows, hide_index=True, width="stretch")
                st.caption(
                    "Rows use the selected session's frozen relationship parameters. "
                    "Unavailable pair observations are omitted."
                )
        else:
            if not overview.pair_ids:
                st.info("No fixed-orientation pairs are available.")
                return
            pair_id = st.sidebar.selectbox("Pair", overview.pair_ids)
            history_days = st.sidebar.selectbox("History (calendar days)", (365, 730, 1095))
            render_pair_detail(service.pair_detail(pair_id, as_of, lookback_days=history_days))
    except Exception:
        st.error("The selected frozen output cannot be loaded. Verify the research manifests.")


if __name__ == "__main__":
    main()

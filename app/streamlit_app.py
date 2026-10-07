"""Primary v2 presentation of explicitly promoted, immutable research outputs."""

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import PrimaryNotReadyError
from structural_break.services.research_app import PrimaryResearchService, PrimaryResearchView


def create_service() -> PrimaryResearchService:
    root = Path(__file__).resolve().parents[1]
    runtime = RuntimeSettings(_env_file=root / ".env")
    paths = ProjectPaths.resolve(root, runtime.workspace_root or root / "data/research_v2")
    return PrimaryResearchService(paths)


def _number(value: Any) -> str:
    return "Unavailable" if value is None or pd.isna(value) else f"{float(value):.4f}"


def render_comparison(
    service: PrimaryResearchService,
    view: PrimaryResearchView,
    horizon: int,
    *,
    active_only: bool,
) -> None:
    st.header("Independent assessment: Model A and Model B")
    rows = service.comparison(view, horizon, active_only=active_only)
    primary = rows.loc[
        rows["family"].eq(view.protocol["primary_family"])
        & rows["variant"].isin(["A", "B_" + view.protocol["primary_b_variant"]])
    ].set_index("variant")
    columns = st.columns(2)
    columns[0].metric("Model A Brier loss", _number(primary.loc["A", "brier"]))
    columns[1].metric(
        "Model B Brier loss",
        _number(primary.loc["B_" + view.protocol["primary_b_variant"], "brier"]),
    )
    st.caption(
        "The fixed comparison is logistic A versus B-both (SEC metadata, tone and catalysts). "
        "Lower Brier and log loss are better; a negative B-minus-A loss difference favors B. "
        "All variants and families remain visible, including unfavorable results."
    )
    st.dataframe(rows, hide_index=True, width="stretch")
    model_b = view.reports[horizon]["models"][view.protocol["primary_family"]][
        "B_" + view.protocol["primary_b_variant"]
    ]
    if active_only:
        st.caption("ACTIVE is an exploratory subset; no separate uncertainty interval is fitted.")
    else:
        st.subheader("Paired assessment uncertainty")
        st.json(model_b["paired_assessment"], expanded=False)
        st.caption(
            "Calendar-quarter resampling is a temporal sensitivity with few blocks. "
            "Shared issuers and dependence remain; forecast performance does not establish profit."
        )
    with st.expander("Sample sizes, source coverage and descriptive groups"):
        st.json(
            {
                "cohorts": view.reports[horizon]["cohorts"],
                "text_coverage": view.reports[horizon]["text_coverage"],
            },
            expanded=False,
        )
        st.caption(
            "Coverage flags retain UNKNOWN observations in the matched A/B comparison. "
            "The catalyst pilot uses its frozen schedule; unscheduled events stay UNKNOWN. "
            "Year, sector, business-group and ACTIVE slices are descriptive."
        )
        st.json(model_b["calibrated_assessment_slices"], expanded=False)


def render_predictions(
    service: PrimaryResearchService,
    view: PrimaryResearchView,
    horizon: int,
    *,
    active_only: bool,
) -> None:
    st.header("Stored development-event scores")
    end = date.fromisoformat(view.protocol["development_end"])
    as_of = st.sidebar.date_input(
        "Research as of",
        value=end,
        min_value=date.fromisoformat(view.protocol["fit_start"]),
        max_value=end,
    )
    if not isinstance(as_of, date):
        st.error("Select one research date.")
        return
    rows = service.predictions(view, horizon, as_of=as_of, active_only=active_only)
    if rows.empty:
        st.info("No stored event scores are available for this selection.")
        return
    pair = st.sidebar.selectbox("Pair", ("All pairs", *sorted(rows["pair_id"].unique())))
    if pair != "All pairs":
        rows = rows.loc[rows["pair_id"].eq(pair)]
    st.caption(
        "Fit and calibration-period scores describe fitted samples. Only assessment-period "
        "scores support the independent comparison. These are retrospective stored scores, "
        "not forecasts issued on the historical date. The research threshold is not a trade signal."
    )
    st.dataframe(rows, hide_index=True, width="stretch")


def main(service: PrimaryResearchService | None = None) -> None:
    st.set_page_config(page_title="Structural-Break Research v2", layout="wide")
    st.title("Structural-Break Research v2")
    st.caption("Frozen research outputs · broader estimable-event population · no live execution")
    st.caption("Final-test outcomes (2024–2025) remain locked.")
    try:
        service = service or create_service()
        versions = service.versions()
        view = service.view()
        selected = st.sidebar.selectbox(
            "Verified research generation", versions, index=versions.index(view.primary_version)
        )
        if selected != view.primary_version:
            view = service.view(selected)
    except PrimaryNotReadyError:
        st.info(
            "V2 is the primary research version. Its complete evidence batch and all three "
            "model evaluations must finish and pass independent verification before results "
            "are published here."
        )
        return
    except Exception:
        st.error(
            "The selected v2 publication failed verification. Verify its registered artifacts."
        )
        return
    st.caption(
        f"Primary: {view.primary_version} · Registry: {view.registry_version} · "
        f"Evidence: {view.intelligence_version}"
    )
    st.caption(
        f"Fit: {view.protocol['fit_start']}–{view.protocol['fit_end']} · "
        f"Calibration: {view.protocol['calibration_start']}–{view.protocol['calibration_end']} · "
        f"Independent assessment: {view.protocol['assessment_start']}–"
        f"{view.protocol['assessment_end']}"
    )
    horizon = st.sidebar.selectbox(
        "Horizon (sessions)",
        (view.protocol["primary_horizon"], *view.protocol["sensitivity_horizons"]),
        format_func=lambda value: (
            f"{value} — predeclared primary"
            if value == view.protocol["primary_horizon"]
            else f"{value} — sensitivity"
        ),
    )
    active_only = st.sidebar.checkbox("ACTIVE at event only", value=False)
    st.caption(
        "The primary cohort includes estimable fresh divergences. ACTIVE marks eligibility "
        "at the event and is an exploratory subset, not a reconstructed trading strategy."
    )
    page = st.sidebar.radio("Page", ("Model comparison", "Event scores"))
    try:
        if page == "Model comparison":
            render_comparison(service, view, horizon, active_only=active_only)
        else:
            render_predictions(service, view, horizon, active_only=active_only)
    except Exception:
        st.error("The selected v2 output cannot be read. Verify the registered research artifacts.")


if __name__ == "__main__":
    main()

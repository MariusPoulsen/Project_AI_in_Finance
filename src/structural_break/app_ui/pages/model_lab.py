"""Model Lab: the matched A/B ladder, curves, slices, drivers and tuning."""

from __future__ import annotations

import streamlit as st

from structural_break.app_ui import charts, components
from structural_break.app_ui.context import current
from structural_break.services.research_application import VARIANT_LABELS

FAMILY_LABELS = {
    "logistic": "Logistic regression (primary)",
    "xgboost": "XGBoost (secondary family)",
}
DIMENSIONS = {
    "year": "Year",
    "sector": "Sector",
    "business_group": "Business group",
    "ACTIVE": "ACTIVE at event",
}


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Model Lab",
        "All ten saved model bundles for this horizon, scored on the same 2022–2023 "
        "assessment events with identical features, folds, tuning budget and calibration. "
        "Unfavourable results are shown as prominently as favourable ones.",
    )
    components.synthetic_banner(service.identity)
    controls = st.columns([3, 2])
    family = (
        controls[0].segmented_control(
            "Model family",
            list(FAMILY_LABELS),
            default=protocol["primary_family"],
            format_func=lambda f: FAMILY_LABELS[f],
        )
        or protocol["primary_family"]
    )
    active = controls[1].toggle(
        "ACTIVE events only",
        help="Exploratory subset: no separate uncertainty interval is fitted for it.",
    )
    comparison = service.comparison(horizon, active_only=active)
    tabs = st.tabs(
        [
            "Ablation ladder",
            "Discrimination and calibration",
            "Where B differs",
            "What drives the models",
            "Tuning and calibration",
            "All metrics",
        ]
    )
    with tabs[0]:
        left, right = st.columns(2)
        with left:
            st.markdown("**Brier loss by evidence block**")
            components.chart(charts.ladder(comparison, family), key="ladder")
        with right:
            st.markdown(
                "**B − A difference"
                + (" (point estimate only)**" if active else " with 95% quarter-block interval**")
            )
            components.chart(charts.delta_forest(comparison, family), key="forest")
        st.caption(
            "Each B variant adds one block of SEC evidence to A's identical quantitative columns. "
            "Rows with UNKNOWN evidence stay in both models' samples. Intervals resample whole "
            "calendar quarters (eight blocks), so they are a temporal sensitivity, not a precise "
            "confidence interval."
        )
    with tabs[1]:
        if active:
            st.info(
                "Curves use all assessment events; switch off the ACTIVE filter to compare "
                "like with like."
            )
        cohort = service.cohorts(horizon)
        prevalence = None
        if len(cohort):
            assessed = cohort.loc[cohort["period"].eq("assessment")]
            prevalence = float(assessed["success_rate"].iloc[0]) if len(assessed) else None
        from structural_break.app_ui import theme

        components.legend(
            [(VARIANT_LABELS[v], theme.VARIANT_COLORS[v]) for v in VARIANT_LABELS]
            + [("Reference (diagonal or base rate)", theme.GRID)]
        )
        cols = st.columns(3)
        for col, kind, title in (
            (cols[0], "reliability", "Reliability (equal-count bins)"),
            (cols[1], "roc", "ROC curve"),
            (cols[2], "pr", "Precision–recall"),
        ):
            with col:
                st.markdown(f"**{title}**")
                rows = service.curves(horizon, kind, family)
                if rows.empty:
                    components.empty_state("No assessment curve is available.")
                else:
                    components.chart(charts.curve(rows, kind, prevalence), key=f"curve_{kind}")
        st.caption(
            "Reliability points sit on the diagonal when predicted probabilities match observed "
            "reversion rates. The dashed precision–recall line is the assessment base rate."
        )
    with tabs[2]:
        cols = st.columns([2, 3])
        dimension = cols[0].selectbox(
            "Slice by", list(DIMENSIONS), format_func=lambda d: DIMENSIONS[d]
        )
        variant = cols[1].selectbox(
            "B variant",
            [v for v in VARIANT_LABELS if v != "A"],
            index=3,
            format_func=lambda v: VARIANT_LABELS[v],
        )
        rows = service.slices(horizon, dimension or "year", family, variant or "B_both")
        if rows.empty:
            components.empty_state("No slices are available for this selection.")
        else:
            components.chart(charts.slice_bars(rows), key="slices")
            st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "brier": st.column_config.NumberColumn("B Brier", format="%.4f"),
                    "roc_auc": st.column_config.NumberColumn("B AUC", format="%.3f"),
                    "delta_brier_B_minus_A": st.column_config.NumberColumn(
                        "Δ Brier B − A", format="%+.5f"
                    ),
                },
            )
            st.caption(
                "Slices are predeclared and descriptive. With small groups and many slices, some "
                "will favour B by chance; none is selected after the fact."
            )
    with tabs[3]:
        explained = service.identity.explanation_status
        cols = st.columns(2)
        for col, variant in ((cols[0], "A"), (cols[1], "B_both")):
            with col:
                st.markdown(f"**{VARIANT_LABELS[variant]}**")
                rows = service.importance(horizon, family, variant)
                if rows.empty:
                    components.empty_state(f"Feature contributions are unavailable. {explained}")
                    continue
                components.chart(charts.importance_bars(rows, family), key=f"imp_{variant}")
        blocks = service.block_importance(horizon, family, "B_both")
        if len(blocks):
            sec_share = float(blocks.loc[blocks["block"].str.startswith("SEC"), "share"].sum())
            st.metric(
                "Share of Model B's attribution from SEC evidence blocks", components.pct(sec_share)
            )
        st.caption(
            "Mean absolute contribution of each feature to the saved model's margin on assessment "
            "events (linear SHAP for logistic, TreeSHAP for XGBoost). Slate bars are quantitative "
            "features, teal bars are SEC evidence. Attribution describes the model, not causation."
        )
    with tabs[4]:
        variant = st.selectbox(
            "Model",
            list(VARIANT_LABELS),
            index=4,
            format_func=lambda v: VARIANT_LABELS[v],
            key="tuning_variant",
        )
        tuning = service.tuning(horizon, family, variant or "B_both")
        if tuning.empty:
            components.empty_state("No tuning record is published for this bundle.")
        else:
            st.dataframe(tuning, hide_index=True, width="stretch")
        inventory = service.inventory(horizon)
        from structural_break.app_ui.pages.monitor import INVENTORY_COLUMNS

        st.dataframe(
            inventory.loc[inventory["bundle"].str.startswith(family)],
            hide_index=True,
            width="stretch",
            column_config=INVENTORY_COLUMNS,
        )
        st.caption(
            f"Candidates are chosen by mean Brier on forward folds "
            f"{', '.join(map(str, protocol['tuning_years']))}, "
            "with each fold's full target window purged at its boundary. Calibration is fitted on "
            f"{str(protocol['calibration_start'])[:4]}–{str(protocol['calibration_end'])[:4]} "
            "only. "
            "Reload error confirms the saved model reproduces its published probabilities."
        )
    with tabs[5]:
        st.dataframe(
            comparison,
            hide_index=True,
            width="stretch",
            column_config={
                name: st.column_config.NumberColumn(name, format="%.4f")
                for name in (
                    "brier",
                    "log_loss",
                    "roc_auc",
                    "pr_auc",
                    "pair_balanced_brier",
                    "issuer_balanced_brier",
                )
            }
            | {
                name: st.column_config.NumberColumn(name, format="%+.5f")
                for name in ("delta_brier_B_minus_A", "ci_low", "ci_high")
            },
        )
        st.download_button(
            "Download metrics (CSV)",
            comparison.to_csv(index=False).encode(),
            file_name=f"model_comparison_h{horizon}.csv",
            mime="text/csv",
            icon=":material/download:",
        )
    components.provenance(
        {
            f"Evaluation (h{horizon})": service.identity.evaluations.get(horizon),
            "Primary comparison": f"calibrated {protocol['primary_family']} "
            "B_{protocol['primary_b_variant']} vs A at {protocol['primary_horizon']} sessions",
            "Bootstrap": f"{protocol['bootstrap_replicates']} calendar-quarter resamples, seed "
            "{protocol['seed']}",
            "Bundle": service.identity.bundle_id,
        }
    )

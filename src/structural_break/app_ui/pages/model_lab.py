"""Model Lab: the headline forecasters (Goal 1), then the frozen A/B research study."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, result_charts, theme
from structural_break.app_ui.context import current
from structural_break.app_ui.results import MODEL_NOTES, MODELS, Results, period_label
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


HEADLINE = ["model_a", "r0", "bag5", "track"]
CURVES = ["r0", "bag5", "track"]
METRIC_COLUMNS: dict[str, Any] = {
    "label": "Model",
    "roc_auc": st.column_config.NumberColumn("ROC AUC", format="%.3f"),
    "pr_auc": st.column_config.NumberColumn("PR AUC", format="%.3f"),
    "log_loss": st.column_config.NumberColumn("Log loss", format="%.4f"),
    "brier": st.column_config.NumberColumn("Brier", format="%.4f"),
    "base_rate": st.column_config.NumberColumn("Base rate", format="percent"),
    "n": st.column_config.NumberColumn("Events", format="%d"),
}


@st.cache_data(show_spinner=False)
def _by_year(forecasts: pd.DataFrame) -> pd.DataFrame:
    from sklearn.metrics import roc_auc_score

    rows = []
    labelled = forecasts[forecasts["labelled"] & forecasts["y"].notna()]
    for year, part in labelled.groupby("year"):
        if part["y"].nunique() < 2:
            continue
        row: dict[str, float] = {"year": float(str(year))}
        for key in CURVES:
            row[key] = float(roc_auc_score(part["y"], part[f"raw_{key}"]))
        rows.append(row)
    return pd.DataFrame(rows)


def headline_forecasters(results: Results | None) -> None:
    st.subheader("Headline forecasters (Goal 1)")
    if results is None:
        components.empty_state(
            "The headline results are not in this deployment. Export them with "
            "`python scripts/export_results.py`."
        )
        return
    metrics = results.metrics()
    periods = [p for p in ("2010–2017", "2018–2023", "2024–2025") if p in results.periods]
    default = periods[-1]
    period = (
        st.segmented_control(
            "Test years", periods, default=default, format_func=period_label, key="g1_period"
        )
        or default
    )
    rows = metrics[metrics["period"].eq(period)].set_index("model")
    cols = st.columns(4)
    if {"bag5", "r0"} <= set(rows.index):
        best, base = rows.loc["bag5"], rows.loc["r0"]
        cols[0].metric(
            "ROC AUC, pre-registered model",
            f"{best['roc_auc']:.3f}",
            delta=f"{best['roc_auc'] - base['roc_auc']:+.3f} vs R0",
        )
        cols[1].metric(
            "Log loss",
            f"{best['log_loss']:.4f}",
            delta=f"{best['log_loss'] - base['log_loss']:+.4f} vs R0",
            delta_color="inverse",
        )
        cols[2].metric(
            "Brier",
            f"{best['brier']:.4f}",
            delta=f"{best['brier'] - base['brier']:+.4f} vs R0",
            delta_color="inverse",
        )
        cols[3].metric(
            "Labelled events",
            components.count(best["n"]),
            help=f"Base rate {components.pct(best['base_rate'])}: the share of divergences that "
            "reverted to |z| ≤ 0.5 within 20 sessions before |z| ≥ 3.",
        )
    tabs = st.tabs(
        [
            "Comparison",
            "Discrimination and calibration",
            "By year",
            "Full model and agent desk",
            "All metrics",
        ]
    )
    with tabs[0]:
        left, right = st.columns(2)
        with left:
            st.markdown("**ROC AUC by test period (higher is better)**")
            components.chart(
                result_charts.metric_bars(metrics, "roc_auc", "ROC AUC", HEADLINE), key="g1_auc"
            )
        with right:
            st.markdown("**Log loss by test period (lower is better)**")
            components.chart(
                result_charts.metric_bars(metrics, "log_loss", "Log loss", HEADLINE),
                key="g1_ll",
            )
        st.dataframe(
            rows.reindex([m for m in HEADLINE if m in rows.index]).reset_index()[
                list(METRIC_COLUMNS)
            ],
            hide_index=True,
            width="stretch",
            column_config=METRIC_COLUMNS,
        )
        st.markdown("\n".join(f"- **{MODELS[m]}**: {MODEL_NOTES[m]}" for m in HEADLINE))
        st.caption(
            "Every model is refitted walk-forward: each test year is scored by a model trained "
            "only on earlier years, with the same labelled events in every row. On 2018–2023 the "
            "pre-registered model beats R0 by 0.0053 in log loss (month-block bootstrap "
            "p = 0.002) and by 0.017 in AUC. Model A's walk-forward scores were erased in "
            "Decision 114: its metrics are kept, its curves are not."
        )
    with tabs[1]:
        components.legend(
            [(MODELS[m], theme.FORECASTER_COLORS[m]) for m in CURVES]
            + [("Reference (diagonal)", theme.GRID)]
        )
        left, right = st.columns(2)
        with left:
            st.markdown(f"**ROC curve, {period}**")
            components.chart(
                result_charts.roc(results.tables["curves"], period, CURVES), key="g1_roc"
            )
        with right:
            st.markdown(f"**Calibration, {period}**")
            components.chart(
                result_charts.calibration(results.tables["curves"], period, CURVES),
                key="g1_cal",
            )
        st.caption(
            "Calibration points are deciles of the predicted probability; they sit on the "
            "diagonal when predictions match observed reversion rates. Probabilities are "
            "calibrated walk-forward on earlier years only."
        )
    with tabs[2]:
        table = _by_year(results.tables["forecasts"])
        if table.empty:
            components.empty_state("No yearly results are available.")
        else:
            components.chart(result_charts.yearly(table, "ROC AUC"), key="g1_years")
            st.caption(
                "One point per test year. The dotted line separates the selection years "
                "(2010–2017) from the holdout (2018–2023)"
                + ("; the second marks the final test." if table["year"].max() >= 2024 else ".")
            )
    with tabs[3]:
        desk = metrics[metrics["model"].isin(["full_base", "full"])]
        if desk.empty:
            components.empty_state("No agent-desk forecasts are available.")
        else:
            st.dataframe(
                desk[["period", *METRIC_COLUMNS]],
                hide_index=True,
                width="stretch",
                column_config={"period": "Test years", **METRIC_COLUMNS},
            )
            st.markdown(
                f"- **{MODELS['full']}**: {MODEL_NOTES['full']}\n"
                f"- **{MODELS['full_base']}**: {MODEL_NOTES['full_base']}"
            )
            st.caption(
                "Both rows use only the events the entry agents scored (the desk region), so the "
                "comparison is like with like. On the selection years the agent features made "
                "the forecast slightly worse (Brier +0.00104, 95 % [+0.00034, +0.00189], "
                "Decision 110b); the full model is reported, not adopted."
            )
    with tabs[4]:
        st.dataframe(
            metrics[["period", *METRIC_COLUMNS]],
            hide_index=True,
            width="stretch",
            column_config={"period": "Test years", **METRIC_COLUMNS},
        )
        st.download_button(
            "Download metrics (CSV)",
            metrics.to_csv(index=False).encode(),
            file_name="forecaster_metrics.csv",
            mime="text/csv",
            icon=":material/download:",
            key="g1_download",
        )


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Model Lab",
        "Every forecaster scored on the same events. First the headline walk-forward "
        "forecasters of Goal 1, refitted each year from 2010; below them the frozen research "
        "study that compared Model A with SEC-evidence variants of Model B on 2022–2023. "
        "Unfavourable results are shown as prominently as favourable ones.",
    )
    components.synthetic_banner(service.identity)
    headline_forecasters(ctx.results)
    st.divider()
    st.subheader("Research layer: the frozen A/B study, 2022–2023")
    st.caption(
        "The pre-registered research comparison (Decisions 36–45): calibrated logistic and "
        "XGBoost models at 20 sessions, Model A against Model B with each block of SEC evidence, "
        "on the 2022–2023 assessment events. Its Model B is the research-layer model, not the "
        "walk-forward R0 above; the later walk-forward variants erased in Decision 114 are not "
        "shown anywhere."
    )
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
    headline = service.headline(horizon, family)
    tone, sentence = service.verdict(headline)
    if not active:
        components.verdict_box(
            f"{FAMILY_LABELS[family].split(' (')[0]}: B (all SEC evidence) vs A",
            sentence,
            tone,
        )
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

"""Model Lab: the headline reversion forecasters of Goal 1, scored walk-forward."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import components, result_charts, theme
from structural_break.app_ui.context import current
from structural_break.app_ui.results import MODEL_NOTES, MODELS, period_label

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
YEARS = {"2010–2017": (2010, 2017), "2018–2023": (2018, 2023), "2024–2025": (2024, 2025)}
SETTINGS = [
    (
        "Original Model B (R0)",
        "Model A's 36 quantitative features plus SEC 8-K timing, FinBERT tone and catalyst "
        "fields (the research layer's B, all SEC evidence)",
        "XGBoost: depth 3, 400 trees, learning rate 0.03, min child weight 20, λ 10; one seed",
        "Decision 45 split: trains on labels that ended before year Y−1",
    ),
    (
        "B+rule+ou, bagged",
        "R0's features plus the peer, state, earnings and momentum blocks and the structural "
        "OU prior (about 170 features)",
        "The same XGBoost with column subsample 0.5 and row subsample 0.8, averaged over five "
        "seeds",
        "Recent: trains on every label that ended before year Y",
    ),
    (
        "B+rule+ou+track, bagged",
        "As above plus the pair's and stock's earlier reversion record",
        "As above",
        "Recent",
    ),
    (
        "Full model",
        "The bagged B+rule+ou probability plus the entry agents' scores",
        "Walk-forward logistic stack on the desk region (Decisions 110b–c)",
        "Recent",
    ),
]


def _labelled(forecasts: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    part = forecasts[forecasts["labelled"] & forecasts["y"].notna()]
    return part[part["year"].between(*years)]


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


@st.cache_data(show_spinner=False)
def _pr_curves(forecasts: pd.DataFrame, period: str) -> pd.DataFrame:
    from sklearn.metrics import precision_recall_curve

    part = _labelled(forecasts, YEARS[period])
    rows = []
    for key in CURVES:
        precision, recall, _ = precision_recall_curve(part["y"], part[f"raw_{key}"])
        pick = np.unique(np.linspace(0, len(recall) - 1, min(len(recall), 250)).astype(int))
        rows += [
            {"model": key, "recall": float(r), "precision": float(p)}
            for r, p in zip(recall[pick], precision[pick], strict=True)
        ]
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _calibration_fit(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Logistic recalibration of each model's probability: slope 1 and intercept 0 are ideal."""
    from sklearn.linear_model import LogisticRegression

    rows = []
    for period, years in YEARS.items():
        part = _labelled(forecasts, years)
        if part.empty or part["y"].nunique() < 2:
            continue
        for key in CURVES:
            p = np.clip(part[f"p_{key}"].to_numpy(float), 1e-6, 1 - 1e-6)
            logit = np.log(p / (1 - p)).reshape(-1, 1)
            fit = LogisticRegression(C=1e6).fit(logit, part["y"].astype(int))
            rows.append(
                {
                    "label": MODELS[key],
                    "period": period_label(period),
                    "slope": float(fit.coef_[0][0]),
                    "intercept": float(fit.intercept_[0]),
                    "mean_predicted": float(p.mean()),
                    "observed": float(part["y"].mean()),
                }
            )
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _by_group(forecasts: pd.DataFrame, period: str) -> pd.DataFrame:
    from sklearn.metrics import roc_auc_score

    rows = []
    for group, part in _labelled(forecasts, YEARS[period]).groupby("business_group"):
        if part["y"].nunique() < 2 or part["y"].sum() < 5:
            continue
        rows.append(
            {
                "group": group,
                "events": len(part),
                "reverted": int(part["y"].sum()),
                "auc_r0": float(roc_auc_score(part["y"], part["raw_r0"])),
                "auc_bag5": float(roc_auc_score(part["y"], part["raw_bag5"])),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["difference"] = frame["auc_bag5"] - frame["auc_r0"]
    return frame.sort_values("difference").reset_index(drop=True)


def _pr_figure(rows: pd.DataFrame, base_rate: float) -> go.Figure:
    figure = go.Figure()
    for key in CURVES:
        part = rows[rows["model"].eq(key)]
        figure.add_trace(
            go.Scatter(
                x=part["recall"],
                y=part["precision"],
                mode="lines",
                name=MODELS[key],
                line={"color": theme.FORECASTER_COLORS[key], "width": 2},
                hovertemplate="Recall %{x:.2f}<br>Precision %{y:.2f}<extra></extra>",
            )
        )
    figure.add_hline(y=base_rate, line={"color": theme.MUTED, "dash": "dash", "width": 1})
    figure.update_layout(
        theme.layout(
            height=360,
            xaxis={"title": "Recall", "range": [0, 1]},
            yaxis={"title": "Precision", "range": [0, 1]},
        )
    )
    return figure


def _group_figure(rows: pd.DataFrame) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            y=rows["group"],
            x=rows["difference"],
            orientation="h",
            customdata=rows[["events", "auc_r0", "auc_bag5"]],
            marker_color=[theme.MODEL_B if v >= 0 else theme.ADVERSE for v in rows["difference"]],
            hovertemplate="%{y}<br>AUC bagged − R0 %{x:+.3f}<br>%{customdata[0]} events, "
            "R0 %{customdata[1]:.3f}, bagged %{customdata[2]:.3f}<extra></extra>",
        )
    )
    figure.add_vline(x=0, line={"color": theme.INK, "width": 1})
    figure.update_layout(
        theme.layout(
            height=max(320, 22 * len(rows) + 80),
            xaxis={"title": "ROC AUC, bagged B+rule+ou − R0"},
            margin={"l": 260},
        )
    )
    return figure


def render() -> None:
    ctx = current()
    results = ctx.results
    components.page_header(
        "Model Lab",
        "The reversion forecasters of Goal 1, each refitted every year from 2010 on earlier "
        "years only and scored on the same labelled events. Unfavourable results are shown as "
        "prominently as favourable ones.",
    )
    components.synthetic_banner(ctx.service.identity)
    if results is None:
        components.empty_state(
            "The headline results are not in this deployment. Export them with "
            "`python scripts/export_results.py`."
        )
        return
    metrics = results.metrics()
    forecasts = results.tables["forecasts"]
    periods = [p for p in YEARS if p in results.periods]
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
            "Discrimination",
            "Calibration",
            "By year",
            "By business group",
            "Full model and agent desk",
            "Settings",
            "All metrics",
        ]
    )
    legend = [(MODELS[m], theme.FORECASTER_COLORS[m]) for m in CURVES]
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
            "On 2018–2023 the pre-registered model beats R0 by 0.0053 in log loss (month-block "
            "bootstrap p = 0.002) and by 0.017 in AUC. Model A's walk-forward scores were "
            "erased in Decision 114: its metrics are kept, its curves are not. Where it "
            "started: the frozen research study (Decisions 36–45) found no established "
            "difference between Model A and the SEC-evidence variants of Model B on 2022–2023; "
            "R0 is that study's Model B refitted walk-forward."
        )
    with tabs[1]:
        components.legend([*legend, ("Reference (chance or base rate)", theme.GRID)])
        left, right = st.columns(2)
        with left:
            st.markdown(f"**ROC curve, {period}**")
            components.chart(
                result_charts.roc(results.tables["curves"], period, CURVES), key="g1_roc"
            )
        with right:
            st.markdown(f"**Precision–recall, {period}**")
            labelled = _labelled(forecasts, YEARS[period])
            base_rate = float(labelled["y"].mean()) if len(labelled) else 0.0
            components.chart(_pr_figure(_pr_curves(forecasts, period), base_rate), key="g1_pr")
        st.caption(
            "Divergences that revert are rare (the dashed line is the base rate), so precision–"
            "recall shows how cleanly each model ranks the few that do; ROC weighs both classes "
            "equally."
        )
    with tabs[2]:
        components.legend([*legend, ("Perfect calibration", theme.GRID)])
        st.markdown(f"**Reliability, {period}**")
        components.chart(
            result_charts.calibration(results.tables["curves"], period, CURVES), key="g1_cal"
        )
        st.markdown("**Calibration slope and intercept**")
        st.dataframe(
            _calibration_fit(forecasts),
            hide_index=True,
            width="stretch",
            column_config={
                "label": "Model",
                "period": "Years",
                "slope": st.column_config.NumberColumn("Slope", format="%.2f"),
                "intercept": st.column_config.NumberColumn("Intercept", format="%+.2f"),
                "mean_predicted": st.column_config.NumberColumn("Mean predicted", format="percent"),
                "observed": st.column_config.NumberColumn("Observed", format="percent"),
            },
        )
        st.caption(
            "Probabilities are Platt-calibrated each year on the previous three years' "
            "out-of-fold scores only. The slope and intercept come from regressing the outcome "
            "on each model's log-odds: slope 1 and intercept 0 are perfect. A slope below 1 "
            "means the predictions are too spread out, above 1 too cautious."
        )
    with tabs[3]:
        table = _by_year(forecasts)
        if table.empty:
            components.empty_state("No yearly results are available.")
        else:
            components.chart(result_charts.yearly(table, "ROC AUC"), key="g1_years")
            st.caption(
                "One point per test year. The dotted line separates the selection years "
                "(2010–2017) from the holdout (2018–2023)"
                + ("; the second marks the final test." if table["year"].max() >= 2024 else ".")
            )
    with tabs[4]:
        groups = _by_group(forecasts, period)
        if groups.empty:
            components.empty_state("Too few reverting events per business group in these years.")
        else:
            components.chart(_group_figure(groups), key="g1_groups")
            st.dataframe(
                groups.sort_values("events", ascending=False),
                hide_index=True,
                width="stretch",
                column_config={
                    "group": "Business group",
                    "events": st.column_config.NumberColumn("Events", format="%d"),
                    "reverted": st.column_config.NumberColumn("Reverted", format="%d"),
                    "auc_r0": st.column_config.NumberColumn("AUC R0", format="%.3f"),
                    "auc_bag5": st.column_config.NumberColumn("AUC bagged", format="%.3f"),
                    "difference": st.column_config.NumberColumn("Difference", format="%+.3f"),
                },
            )
            st.caption(
                "Descriptive: with about 40 groups and few reversions in each, some groups "
                "favour either model by chance; none was selected after the fact. Groups with "
                "fewer than five reversions are left out."
            )
    with tabs[5]:
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
    with tabs[6]:
        st.table(
            pd.DataFrame(
                SETTINGS, columns=["Model", "Features", "Learner", "Training window"]
            ).set_index("Model")
        )
        st.caption(
            "No hyperparameter is tuned per year: tuning and other boosting libraries did not "
            "improve the forecast on the selection years (Decisions 66, 70, 86), so every model "
            "keeps the fixed XGBoost settings. Each test year's model is fitted on earlier years "
            "only; selections use the previous year's out-of-sample score cutoff."
        )
    with tabs[7]:
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
    components.provenance(
        {
            "Results export": f"{results.manifest.get('commit')} "
            f"({results.manifest.get('generated_at')})",
            "Scored event years": "–".join(str(y) for y in results.manifest["event_years"]),
        }
    )

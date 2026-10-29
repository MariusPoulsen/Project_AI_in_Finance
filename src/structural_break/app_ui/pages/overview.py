"""Overview: the question, the spread picture, the two goals' answers and how they fit."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, pipeline_view, result_charts, theme
from structural_break.app_ui.context import current
from structural_break.app_ui.results import Results


def _goals(ctx_results: Results | None) -> None:
    if ctx_results is None:
        components.empty_state(
            "The headline results are not in this deployment. Export them with "
            "`python scripts/export_results.py`."
        )
        return
    metrics = {(m["model"], m["period"]): m for m in ctx_results.summary["goal1"]}
    stats = {
        (key, period): values
        for key, book in ctx_results.summary["books"].items()
        for period, values in book["periods"].items()
    }
    final = "2024–2025" in ctx_results.periods
    test = "2024–2025" if final else "2018–2023"
    role = "final test" if final else "holdout"
    left, right = st.columns(2)
    with left:
        st.markdown("#### Goal 1: forecast which divergences revert")
        if ("bag5", test) in metrics and ("r0", test) in metrics:
            best, base = metrics[("bag5", test)], metrics[("r0", test)]
            cols = st.columns(2)
            cols[0].metric(
                f"ROC AUC, {test} ({role})",
                f"{best['roc_auc']:.3f}",
                delta=f"{best['roc_auc'] - base['roc_auc']:+.3f} vs original Model B",
            )
            cols[1].metric(
                f"Log loss, {test}",
                f"{best['log_loss']:.4f}",
                delta=f"{best['log_loss'] - base['log_loss']:+.4f}",
                delta_color="inverse",
            )
        st.markdown(
            "The pre-registered model (bagged B+rule+ou) adds peer displacement, the earnings "
            "calendar, momentum and a structural Ornstein–Uhlenbeck prior to the original Model "
            "B, and forecast reversion better on both development periods (2010–2017 and "
            "2018–2023). The agent desk's entry scores did not add to it."
        )
    with right:
        st.markdown("#### Goal 2: the best long-run book after costs")
        if ("adopted", test) in stats:
            book = stats[("adopted", test)]
            span = "2010–2025" if ("adopted", "2010–2025") in stats else "2010–2023"
            cols = st.columns(2)
            cols[0].metric(f"Sharpe, {test} ({role})", f"{book['sharpe']:.2f}")
            cols[1].metric(
                f"CAGR with cash, {span}",
                components.pct(stats[("adopted", span)]["cagr_with_cash"]),
            )
        st.markdown(
            "Better forecasts did not select better trades. The adopted book keeps the original "
            "Model B's selection and earns its edge from how trades are run: wider take profit, "
            "a half-life time stop, trading at the close, risk targeting and the agent monitor "
            "exit."
        )
    daily = ctx_results.tables["books_daily"]
    components.chart(
        result_charts.book_values(daily, ["adopted", "bag5"], height=280), key="overview_book"
    )
    st.caption(
        "The adopted book against the same book built on the best forecaster's selection. "
        "Values include cash interest. Dotted line: start of the 2018–2023 holdout"
        + ("; shaded: the 2024–2025 final test." if ctx_results.final_included else ".")
    )


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Structural-break detector",
        "When two business-peer stocks drift apart, does the gap close or has the "
        "relationship broken? The project forecasts which divergences revert (Goal 1) and "
        "builds the best long-run trading book from them after costs (Goal 2). Every choice "
        "was made on 2010–2017, confirmed once on 2018–2023 and tested once on 2024–2025.",
    )
    components.synthetic_banner(service.identity)

    pair_id = service.hero_pair(horizon)
    series = service.pair_series(pair_id) if pair_id else None
    if series is not None and len(series.state):
        state = series.state.copy()
        state["trading_date"] = pd.to_datetime(state["trading_date"])
        start = pd.Timestamp(protocol["calibration_start"])
        state = state.loc[state["trading_date"].ge(start)]
        events = service.pair_events(horizon, series.pair_id)
        events = events.loc[events["date"].ge(start)]
        st.subheader(f"{series.pair_id.replace('__', ' vs ')}: the spread the models watch")
        components.chart(
            charts.spread_bands(
                state,
                events,
                entry=float(protocol["entry_z"]),
                success=float(protocol["success_z"]),
                adverse=float(protocol["adverse_z"]),
                height=330,
            ),
            key="hero",
        )
        components.legend(
            [
                (f"±{protocol['entry_z']:g} divergence (event)", theme.ENTRY),
                (f"±{protocol['success_z']:g} reversion (success)", theme.MODEL_B),
                (f"±{protocol['adverse_z']:g} adverse (failure)", theme.ADVERSE),
                ("Shaded: relationship not ACTIVE", theme.INACTIVE),
            ]
        )
        st.caption(
            f"An event is a fresh crossing of ±{protocol['entry_z']:g}. The forecasting target "
            f"is a success if the spread returns inside ±{protocol['success_z']:g} before "
            f"reaching ±{protocol['adverse_z']:g}, within {horizon} trading sessions. The book "
            "trades with its own exits (take profit at ±1.0, a time stop of 1.5 half-lives)."
        )

    st.subheader("The answers")
    _goals(ctx.results)

    counts = service.universe_counts(horizon)
    st.subheader("What the study covers")
    cols = st.columns(4)
    cols[0].metric("Business-peer pairs", components.count(counts["pairs"]))
    cols[1].metric("Issuers", components.count(counts["issuers"]))
    cols[2].metric("Business groups", components.count(counts["groups"]))
    scored = len(ctx.results.tables["forecasts"]) if ctx.results is not None else counts["events"]
    cols[3].metric(
        "Scored divergences",
        components.count(scored),
        help="Fresh divergences scored walk-forward from 2010 (the research layer counts "
        f"{components.count(counts['events'])} development events from 2006).",
    )
    st.subheader("How the pipeline fits together")
    pipeline_view.render(protocol, counts["issuers"])
    st.markdown(
        "**Where to go next.** Compare the forecasters in the Model Lab, see how the book was "
        "built and every trade in the Strategy Lab, read the adopted book and the final test, "
        "or browse every scored divergence in the Scanner."
    )
    links = st.columns(4)
    links[0].page_link(ctx.pages["model"], label="Model Lab", icon=":material/science:")
    links[1].page_link(
        ctx.pages["strategy"], label="Strategy Lab", icon=":material/candlestick_chart:"
    )
    links[2].page_link(ctx.pages["book"], label="Adopted book", icon=":material/trending_up:")
    links[3].page_link(ctx.pages["scanner"], label="Scanner", icon=":material/radar:")
    components.provenance(
        {
            "Results export": (
                f"{ctx.results.manifest.get('commit')} ({ctx.results.manifest.get('generated_at')})"
                if ctx.results is not None
                else "not available"
            ),
            "Freeze manifest": (
                ctx.results.manifest.get("freeze_manifest_sha256") if ctx.results else None
            ),
            "Primary research generation": service.identity.primary_version,
            f"Evaluation (h{horizon})": service.identity.evaluations.get(horizon),
            "Bundle": service.identity.bundle_id,
        }
    )

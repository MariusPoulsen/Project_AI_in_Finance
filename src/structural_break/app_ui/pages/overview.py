"""Overview: the question, the spread picture, and the predeclared answer."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from structural_break.app_ui import charts, components, theme
from structural_break.app_ui.context import current

ARCHITECTURE = """
digraph {
  rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.35;
  node [shape=box, style="rounded,filled", fontname="IBM Plex Sans", fontsize=15,
        margin="0.18,0.08",
        color="#D5DAE1", fillcolor="#FFFFFF", fontcolor="#172033"];
  edge [color="#9AA5B1", arrowsize=0.6];
  prices [label="Daily prices\\n250 issuers · VIX"];
  sec [label="SEC EDGAR filings\\n(public)"];
  econ [label="Econometric engine\\nmonthly Engle–Granger,\\nfrozen z-score"];
  events [label="Fresh divergences\\n|z| ≥ 2"];
  quant [label="Quantitative features\\nspread · relationship ·\\nmarket · liquidity"];
  text [label="SEC evidence\\n8-K metadata · FinBERT tone ·\\nGemma catalysts (UNKNOWN kept)"];
  a [label="Model A\\nlogistic / XGBoost", fillcolor="#EEF1F5"];
  b [label="Model B\\nA + SEC blocks", fillcolor="#E3F2EF"];
  cal [label="Sigmoid calibration\\n2020–2021"];
  eval [label="Paired assessment\\n2022–2023"];
  bt [label="Strategy ladder\\nfrozen costs"];
  prices -> econ -> events -> quant;
  sec -> text;
  quant -> a; quant -> b; text -> b;
  a -> cal; b -> cal; cal -> eval; cal -> bt;
}
"""


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    protocol = service.protocol
    components.page_header(
        "Structural-break detector",
        "When two business-peer stocks drift apart, does the gap close or has the "
        "relationship broken? Model A answers from prices alone; Model B also reads the "
        "companies' SEC filings. This page shows the frozen answer on 2022–2023 events "
        "that neither model was fitted or calibrated on.",
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
                (f"±{protocol['adverse_z']:g} adverse stop (failure)", theme.ADVERSE),
                ("Shaded: relationship not ACTIVE", theme.INACTIVE),
            ]
        )
        st.caption(
            f"An event is a fresh crossing of ±{protocol['entry_z']:g}. It succeeds if the "
            f"spread returns inside ±{protocol['success_z']:g} before reaching "
            f"±{protocol['adverse_z']:g}, within {horizon} trading sessions."
        )

    headline = service.headline(horizon)
    tone, sentence = service.verdict(headline)
    title = {
        "favours_b": "Model B forecasts better",
        "favours_a": "Model A forecasts better",
        "inconclusive": "No established difference between A and B",
        "unavailable": "Comparison unavailable",
    }[tone]
    st.subheader(f"Predeclared primary result, {horizon} sessions")
    components.verdict_box(title, sentence, tone)
    cols = st.columns(4)
    cols[0].metric("Model A Brier loss", components.fmt(headline.a_brier))
    cols[1].metric("Model B Brier loss", components.fmt(headline.b_brier))
    cols[2].metric(
        "Difference, B − A",
        f"{headline.delta:+.5f}" if headline.delta is not None else "n/a",
        help="Negative favours Model B. The interval below comes from a calendar-quarter block "
        f"bootstrap over {headline.quarter_blocks} quarters: few blocks, so treat it as a "
        "sensitivity rather than a precise confidence interval.",
    )
    if headline.interval:
        cols[2].caption(f"95% interval {headline.interval[0]:+.4f} to {headline.interval[1]:+.4f}")
    cols[3].metric(
        "Assessment events",
        components.count(headline.n),
        help=f"{components.count(headline.positives)} reverted "
        f"({components.pct(headline.positives / headline.n if headline.n else None)}).",
    )
    st.caption(
        f"Calibrated {headline.family} models. ROC AUC: A {components.fmt(headline.a_auc, 3)}, "
        f"B {components.fmt(headline.b_auc, 3)}. A constant fitting-period base rate scores "
        f"Brier {components.fmt(headline.prevalence_brier)}. Better forecasts do not by "
        "themselves mean trading profit; see the Strategy Lab."
    )

    counts = service.universe_counts(horizon)
    st.subheader("What the study covers")
    cols = st.columns(4)
    cols[0].metric("Business-peer pairs", components.count(counts["pairs"]))
    cols[1].metric("Issuers", components.count(counts["issuers"]))
    cols[2].metric("Business groups", components.count(counts["groups"]))
    cols[3].metric("Development events", components.count(counts["events"]))
    st.markdown("**How the pipeline fits together**")
    st.graphviz_chart(ARCHITECTURE, width="stretch")
    st.markdown(
        "**Where to go next.** Browse every scored divergence in the Scanner, open any pair "
        "to see why a model leaned one way, compare all ten model bundles in the Model Lab, "
        "or check whether the forecasts would have paid after costs in the Strategy Lab."
    )
    links = st.columns(4)
    links[0].page_link(ctx.pages["scanner"], label="Open the Scanner", icon=":material/radar:")
    links[1].page_link(ctx.pages["model"], label="Compare models", icon=":material/science:")
    links[2].page_link(
        ctx.pages["strategy"], label="Strategy Lab", icon=":material/candlestick_chart:"
    )
    links[3].page_link(ctx.pages["method"], label="How it works", icon=":material/menu_book:")
    components.provenance(
        {
            "Primary research generation": service.identity.primary_version,
            f"Evaluation (h{horizon})": service.identity.evaluations.get(horizon),
            "Bundle": service.identity.bundle_id,
        }
    )

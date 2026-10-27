"""Methodology and model card."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from structural_break.app_bundle.features import BLOCK_ORDER, feature_block
from structural_break.app_ui import charts, components
from structural_break.app_ui.context import current


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    p = service.protocol
    components.page_header(
        "Methodology and model card",
        "How events, labels, features and models are defined, what the evidence can and cannot "
        "support, and how the system is meant to be used.",
    )
    components.synthetic_banner(service.identity)
    st.subheader("The question")
    st.markdown(
        "Statistical arbitrage bets that two related stocks which drift apart will drift back. "
        "Sometimes the gap closes; sometimes the relationship has broken, often because "
        "something happened to one of the companies. The study asks whether information in "
        "public SEC filings helps tell those cases apart, compared with prices alone."
    )
    st.subheader("Chronology")
    components.chart(charts.timeline(service.periods()), key="timeline")
    st.dataframe(pd.DataFrame(service.periods()), hide_index=True, width="stretch")
    st.subheader("Events and labels")
    st.markdown(
        f"- **Population:** a frozen roster of business-peer pairs. Each month an Engle–Granger "
        f"relationship is re-estimated on the trailing {p['formation_sessions']}-session window "
        "and frozen for the next month.\n"
        f"- **Event:** a fresh crossing of |z| ≥ {p['entry_z']:g} on the frozen spread.\n"
        f"- **Label:** success if |z| returns to ≤ {p['success_z']:g} before reaching "
        f"{p['adverse_z']:g} in the adverse direction, within {p['primary_horizon']} sessions "
        f"(primary) or {', '.join(map(str, p['sensitivity_horizons']))} (sensitivities).\n"
        "- **Point-in-time:** every predictor is available by the event close: previous-session "
        "VIX, SEC filings accepted before the cutoff. Future prices are used only to build labels."
    )
    st.subheader("Features and models")
    report = service.data(horizon).report
    columns = report["models"].get("logistic", {}).get("B_both", {}).get("feature_columns", [])
    blocks = pd.Series([feature_block(c) for c in columns]).value_counts()
    table = pd.DataFrame(
        {
            "Block": [b for b in BLOCK_ORDER if b in blocks.index],
            "Features": [int(blocks[b]) for b in BLOCK_ORDER if b in blocks.index],
            "Used by": [
                "A and B" if not b.startswith("SEC") else "B variants"
                for b in BLOCK_ORDER
                if b in blocks.index
            ],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    st.markdown(
        "- **Model A:** quantitative features only. **Model B:** A's identical columns plus SEC "
        "evidence: 8-K/item recency (metadata), FinBERT tone, Gemma-extracted catalysts, or "
        "all three.\n"
        "- **Families:** logistic regression (median imputation, standardisation; C from "
        f"{p['logistic_c']}) and a small fixed XGBoost grid. Choices use forward folds "
        f"{', '.join(map(str, p['tuning_years']))} with full-horizon purging; a sigmoid "
        f"calibrator is fitted on "
        f"{str(p['calibration_start'])[:4]}–{str(p['calibration_end'])[:4]}.\n"
        f"- **Primary comparison (declared in advance):** calibrated {p['primary_family']} "
        f"B_{p['primary_b_variant']} versus A at {p['primary_horizon']} sessions, Brier loss, "
        f"paired calendar-quarter block bootstrap ({p['bootstrap_replicates']} resamples).\n"
        "- **Explanations:** exact margin decompositions of the saved models (linear SHAP for "
        "logistic, TreeSHAP for XGBoost), computed from the stored models without refitting."
    )
    st.subheader("Limitations")
    st.markdown(
        "- The issuer roster survives to today and uses current business classifications, so it "
        "is not a historically complete investable universe.\n"
        "- Prices use retrospective Yahoo adjustments rather than a vintage feed.\n"
        "- Modern pretrained text models (FinBERT, Gemma) are applied to older filings, which a "
        "trader at the time could not have done.\n"
        "- The assessment has only eight calendar-quarter blocks, and 2022–2023 was already "
        "observed during development, so its results are development evidence.\n"
        "- Catalysts cover a frozen schedule of 500 events; others are UNKNOWN by design.\n"
        "- Forecast improvement does not establish trading profitability, and model selections "
        "in the backtest are very small."
    )
    st.subheader("Intended use")
    st.markdown(
        "- **For:** research and teaching on whether disclosure text helps judge pair "
        "divergences; transparent comparison of model variants.\n"
        "- **Not for:** live trading, investment advice or decisions about any individual. "
        "The application has no order execution and shows no live data.\n"
        "- **Human oversight:** language models never set a trade or research status; a "
        "deterministic, auditable controller is reserved for that, and it is not yet run."
    )
    st.subheader("Data, privacy and security")
    st.markdown(
        "- Inputs are public market prices and public SEC EDGAR filings about listed companies. "
        "No personal or customer data is collected, stored or displayed.\n"
        "- The app is read-only: browsing never downloads data, calls a language model, fits a "
        "model or writes results. Every file it shows is checked against a SHA-256 manifest.\n"
        "- API keys live only in an ignored `.env` file or platform secrets, never in the "
        "repository, logs or this interface.\n"
        "- The 2024–2025 final test remains locked and is not present in this application."
    )

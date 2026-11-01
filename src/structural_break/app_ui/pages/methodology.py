"""Methodology and model card."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from structural_break.app_bundle.features import BLOCK_ORDER, feature_block
from structural_break.app_ui import components
from structural_break.app_ui.context import current

PROGRAMME = [
    (
        "Selection years",
        "2010–2017",
        "Every forecaster, filter, exit and book choice was made here",
    ),
    (
        "Holdout",
        "2018–2023",
        "Opened once per stage, after the choice was committed (about ten stages)",
    ),
    ("Final test", "2024–2025", "Opened once, after the owner's unlock record"),
]
HEADLINE_BLOCKS = [
    ("Quantitative (Model A)", "Spread, relationship, market and liquidity features"),
    ("SEC timing and tone (R0)", "8-K recency and FinBERT tone of each leg's filings"),
    ("peer", "Each stock's displacement against its other peers; market-wide divergence breadth"),
    ("state", "Zero crossings, AR(1) persistence, error-correction speed, relationship age"),
    ("earnings", "Days since and to each leg's earnings 8-K; earnings inside the holding window"),
    ("momentum", "Each leg's 20- and 120-session return aligned with the divergence"),
    (
        "ou",
        "Structural Ornstein–Uhlenbeck Monte Carlo: probability of the label and of the take "
        "profit, expected z captured",
    ),
    ("track", "The pair's and stock's reversion record on earlier resolved events (+track)"),
]


def render() -> None:
    ctx = current()
    service, horizon = ctx.service, ctx.horizon
    p = service.protocol
    components.page_header(
        "Methodology and model card",
        "How events, labels, features, models and the trading book are defined, what the "
        "evidence can and cannot support, and how the system is meant to be used.",
    )
    components.synthetic_banner(service.identity)
    st.subheader("The question")
    st.markdown(
        "Statistical arbitrage bets that two related stocks which drift apart will drift back. "
        "Sometimes the gap closes; sometimes the relationship has broken, often because "
        "something happened to one of the companies. The project has two goals:\n"
        "1. **Forecast mean reversion:** compare methods that predict which divergences close, "
        "by ROC AUC, PR AUC, log loss and Brier loss.\n"
        "2. **Build the best long-run book:** use the forecasts to trade, and judge the book by "
        "Sharpe ratio, CAGR and drawdown after realistic costs."
    )
    st.subheader("Chronology")
    st.dataframe(
        pd.DataFrame(PROGRAMME, columns=["Period", "Years", "Use"]),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Events and labels")
    st.markdown(
        f"- **Population:** a frozen roster of business-peer pairs. Each month an Engle–Granger "
        f"relationship is re-estimated on the trailing {p['formation_sessions']}-session window "
        "and frozen for the next month.\n"
        f"- **Event:** a fresh crossing of |z| ≥ {p['entry_z']:g} on the frozen spread.\n"
        f"- **Label (the forecasting target):** success if |z| returns to ≤ {p['success_z']:g} "
        f"before reaching {p['adverse_z']:g} in the adverse direction, within "
        f"{p['primary_horizon']} sessions. The research layer also reported "
        f"{', '.join(map(str, p['sensitivity_horizons']))} sessions as sensitivities; every "
        "headline model and the final test use 20.\n"
        "- **Trading is not the label:** the book exits with its own rules (take profit at "
        "|z| ≤ 1.0, a time stop of 1.5 half-lives, news and monitor exits), so a better forecast "
        "of the label need not make a better book.\n"
        "- **Point-in-time:** every predictor is available by the event close: previous-session "
        "VIX, SEC filings accepted before the cutoff, headlines available before the session. "
        "Future prices are used only to build labels and returns."
    )
    st.subheader("Headline forecasters (Goal 1)")
    st.dataframe(
        pd.DataFrame(HEADLINE_BLOCKS, columns=["Block", "Contents"]),
        hide_index=True,
        width="stretch",
    )
    st.markdown(
        "- **Original Model B (R0):** fixed XGBoost on the quantitative and SEC blocks.\n"
        "- **B+rule+ou, bagged (pre-registered):** R0's inputs plus the peer, state, earnings, "
        "momentum and OU blocks; five seeds with feature subsampling.\n"
        "- **B+rule+ou+track, bagged:** the same plus the track-record block; best observed, "
        "chosen after the fact.\n"
        "- **Full model:** the pre-registered model plus the entry agents' scores, where the "
        "agents read the event.\n"
        "- **Calibration:** walk-forward on earlier years only. Model comparisons use the same "
        "labelled events in every row and a month-block bootstrap."
    )
    st.subheader("Agent desk")
    st.markdown(
        "- **Entry agents:** a pair news analyst, a bull/bear debate and a risk judge read the "
        "company headlines and filings around an event and score it. Their assessments enter "
        "the Full model's probability forecast and its alternative trade selection. They do "
        "not select the adopted R0 book's entries.\n"
        "- **Position monitor:** for every open trade and session with new company headlines, a "
        "FinBERT triage passes adverse-toned news to a language model (Gemma), which scores "
        "how adverse and how persistent it is. A trade closes when both scores are 5.\n"
        "- **News:** FNSPID headlines for development; TickerTick for 2024–2025."
    )
    st.subheader("Trading book (Goal 2)")
    st.markdown(
        "- **Selection:** R0's top 20 % of each test year by the previous year's cutoff, after "
        "a fresh-news filter, a 120-session mean-crossing filter and a cost filter.\n"
        "- **Execution:** signal and trade at the close, 7.5 % of NAV per entry, realistic "
        "per-stock costs (spread tier, square-root impact, commission) at $10m.\n"
        "- **Exits:** take profit at |z| ≤ 1.0, no z-score stop, a time stop of 1.5 half-lives "
        "(10–40 sessions), an 8-K adverse-tone exit and the monitor exit.\n"
        "- **Book:** a PCA residual-reversal sleeve, a 4 % volatility target, a hard 200 % "
        "gross cap and T-bill interest on cash; Sharpe ratios are in excess of cash."
    )
    st.subheader("Where it started: the frozen A/B study")
    report = service.data(horizon).report
    columns = report["models"].get("logistic", {}).get("B_both", {}).get("feature_columns", [])
    blocks = pd.Series([feature_block(c) for c in columns]).value_counts()
    shown = [b for b in BLOCK_ORDER if b in blocks.index and "catalyst" not in b.lower()]
    table = pd.DataFrame(
        {
            "Block": shown,
            "Features": [int(blocks[b]) for b in shown],
            "Used by": ["A and B" if not b.startswith("SEC") else "B variants" for b in shown],
        }
    )
    st.dataframe(table, hide_index=True, width="stretch")
    st.markdown(
        "- **Model A:** quantitative features only. **Model B:** A's identical columns plus SEC "
        "evidence shown here: 8-K/item recency (metadata) and FinBERT tone.\n"
        "- **Families:** logistic regression (median imputation, standardisation; C from "
        f"{p['logistic_c']}) and a small fixed XGBoost grid. Choices use forward folds "
        f"{', '.join(map(str, p['tuning_years']))} with full-horizon purging; a sigmoid "
        f"calibrator is fitted on "
        f"{str(p['calibration_start'])[:4]}–{str(p['calibration_end'])[:4]}.\n"
        f"- **Primary comparison (declared in advance):** calibrated {p['primary_family']} "
        f"B_{p['primary_b_variant']} versus A at {p['primary_horizon']} sessions, Brier loss, "
        f"paired calendar-quarter block bootstrap ({p['bootstrap_replicates']} resamples). "
        "Result: no established difference.\n"
        "- **Explanations:** exact margin decompositions of the saved models (linear SHAP for "
        "logistic, TreeSHAP for XGBoost), computed from the stored models without refitting."
    )
    st.subheader("Limitations")
    st.markdown(
        "- **Universe:** the issuer roster survives to today and uses current business "
        "classifications, so it is not a historically complete investable universe. QRVO has "
        "no 2024–2025 prices (its history was withdrawn after its 2026 delisting), so its seven "
        "pairs have no final-test events.\n"
        "- **Prices** use retrospective Yahoo adjustments rather than a vintage feed.\n"
        "- **Text models:** modern pretrained models (FinBERT, Gemma) are applied to older "
        "filings and headlines, which a trader at the time could not have done.\n"
        "- **Reuse of years:** 2018–2023 was opened in about ten stages, so it is less clean "
        "than a single holdout. Across 132 tracked designs the probability of backtest "
        "overfitting is 0.54 and the book's deflated Sharpe ratio is 0.86.\n"
        "- **Thin edge:** at double the realistic costs the book is only marginally positive.\n"
        "- **News source change:** the final test's headlines come from a different, much "
        "denser source until May 2025 and a thinner one after it; the monitor's thresholds were "
        "not changed.\n"
        "- **Final-test code:** one development-only year check in the catalyst scheduler was "
        "widened to the unlocked end date; no development result changes."
    )
    st.subheader("Intended use")
    st.markdown(
        "- **For:** research and teaching on forecasting pair divergences and turning forecasts "
        "into a book after costs; transparent comparison of model variants.\n"
        "- **Not for:** live trading, investment advice or decisions about any individual. "
        "The application has no order execution and shows no live data.\n"
        "- **Human oversight:** language models never trade by themselves. The monitor's "
        "scores pass a fixed, audited rule; entry assessments feed a statistical forecast; "
        "the group reviewed 50 blind agent cases."
    )
    st.subheader("Data, privacy and security")
    st.markdown(
        "- Inputs are public market prices, public SEC EDGAR filings and public news headlines "
        "about listed companies. No personal or customer data is collected, stored or "
        "displayed.\n"
        "- The app is read-only: browsing never downloads data, calls a language model, fits a "
        "model or writes results. Every file it shows is checked against a SHA-256 manifest.\n"
        "- API keys live only in an ignored `.env` file or platform secrets, never in the "
        "repository, logs or this interface.\n"
        "- The owner unlocked the 2024–2025 final test on 27 October 2026; its "
        "results appear in the app once the single run is published."
    )

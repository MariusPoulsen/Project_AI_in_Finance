"""Current research findings, evidence and methods; no analytical work on browsing."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from structural_break.app_ui import components, data
from structural_break.services.research_summary import ADOPTED, PERIODS, ResearchSummaryService

DEFAULT_PERIOD = next(iter(PERIODS))


def service() -> ResearchSummaryService | None:
    outcome = data.load_summary()
    if outcome.service is None:
        if outcome.status == "failed":
            st.error(outcome.message)
        else:
            st.info(outcome.message)
        st.caption("Final-test results are not included in this development snapshot.")
    return outcome.service


def link(key: str, label: str) -> None:
    pages = st.session_state.get("_sb_pages", {})
    if key in pages:
        st.page_link(pages[key], label=label)


def period_control(key: str) -> str:
    if key not in st.session_state and "_sb_research_period" in st.session_state:
        st.session_state[key] = st.session_state["_sb_research_period"]
    value = str(st.selectbox("Research period", list(PERIODS), key=key))
    st.session_state["_sb_research_period"] = value
    return value


def cohort_line(svc: ResearchSummaryService, period: str) -> None:
    cohort = svc.manifest.cohorts[period]
    st.caption(f"{period} · {cohort.n:,} matched labelled events · 20-session forecast target")


def provenance(svc: ResearchSummaryService) -> None:
    with st.expander("Data provenance and available diagnostics"):
        st.write(svc.manifest.source)
        st.write(svc.manifest.precision)
        st.caption(f"Presentation snapshot SHA-256: {svc.snapshot_id}")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Artifact": name, "SHA-256": digest}
                    for name, digest in svc.manifest.files.items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption("Snapshot final-test state: locked. No 2024–2025 outcomes are loaded.")


def portfolio_bridge(svc: ResearchSummaryService, period: str) -> None:
    stats = svc.summary.stats[ADOPTED][PERIODS[period][2]]
    st.divider()
    columns = st.columns([2.2, 1, 1, 1.3], vertical_alignment="center")
    with columns[0]:
        st.markdown("**Portfolio choice: R0 + position monitor**")
        st.caption(f"{period} · Sharpe in excess of cash")
    columns[1].metric("Sharpe", f"{stats.sharpe:.3f}")
    columns[2].metric("CAGR with cash", components.pct(stats.cagr_with_cash, 2))
    with columns[3]:
        link("book", "Compare portfolio returns")


def render() -> None:
    components.page_header(
        "Better forecasts. A different book choice.",
        "Two research goals, assessed separately: predict mean reversion, "
        "then test whether the signal earns returns after realistic costs.",
    )
    svc = service()
    if svc is None:
        return
    period = DEFAULT_PERIOD
    cohort_line(svc, period)
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Forecasting")
        st.markdown(
            '<p class="sb-finding">The preregistered OU model ranks reversion events '
            "better than the original Model B.</p>",
            unsafe_allow_html=True,
        )
        rows = svc.forecasts(period)
        comparison = st.columns(2)
        comparison[0].metric("R0 · ROC AUC", f"{rows.iloc[1]['ROC AUC']:.3f}")
        comparison[1].metric("B+rule+ou · ROC AUC", f"{rows.iloc[2]['ROC AUC']:.3f}")
        st.caption(
            "Higher is better. Point estimates; the +track variant is post-hoc. "
            "A forecast gain does not establish a profitable trading strategy."
        )
        link("forecast", "Compare reversion forecasts")
    with right:
        st.subheader("Portfolio")
        st.markdown(
            '<p class="sb-finding">The original R0 model remains the trade selector. '
            "The adopted book adds position-monitor exits.</p>",
            unsafe_allow_html=True,
        )
        stats = svc.book_stats(period)
        comparison = st.columns(2)
        comparison[0].metric("Without monitor · Sharpe", f"{stats.iloc[1]['sharpe']:.3f}")
        comparison[1].metric("With monitor · Sharpe", f"{stats.iloc[0]['sharpe']:.3f}")
        st.caption(
            "Sharpe is in excess of cash. Entry-agent scores did not improve the book; "
            "monitor exits are the adopted use of the agent desk."
        )
        link("book", "Compare portfolio returns")
    st.divider()
    st.subheader("Read the evidence in context")
    st.write(
        "These are development findings. Periods were reused during research. The final "
        "2024–2025 test remains locked in this snapshot; the results do not establish alpha."
    )
    audit = svc.summary.audit
    st.caption(
        f"Overfitting audit: {audit.trials} tracked designs · PBO {audit.pbo:.2f} · "
        f"confirmation deflated Sharpe {audit.dsr_2018_2023['132']:.2f} (below 0.95)."
    )
    with st.expander("What exactly is a successful reversion?"):
        st.write(svc.manifest.cohorts[period].definition)
        st.write(
            "That forecast target differs from the book's take-profit and adaptive time "
            "stop. Baseline 0 and Baseline 1 are trading benchmarks, not probability models."
        )
    provenance(svc)


def evidence() -> None:
    components.page_header(
        "Evidence and diagnostics",
        "Coverage, model roles and research limitations behind the two comparisons.",
    )
    svc = service()
    if svc is None:
        return
    st.subheader("What is available in this snapshot")
    st.dataframe(
        pd.DataFrame(
            [
                (
                    "Four retained forecasters",
                    "Rounded matched-cohort metrics",
                    "2010–17 / 2018–23",
                ),
                (
                    "Adopted and no-monitor books",
                    "Saved period statistics and daily NAV",
                    "2010–2023",
                ),
                (
                    "Current event predictions / calibration",
                    "Not exported",
                    "Do not infer from old study",
                ),
                (
                    "Full model + entry desk",
                    "Separately selected desk subset",
                    "No full-population row",
                ),
                ("Final test", "Locked in this snapshot", "2024–2025 outcomes not loaded"),
            ],
            columns=["Evidence", "Availability", "Scope"],
        ),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Agent desk: coverage is part of the result")
    desk = svc.summary.desk
    st.write(
        f"Entry desk: {desk.entry_scored:,} scored and {desk.entry_abstained:,} abstained. "
        "Its entry scores did not improve forecasting or portfolio selection."
    )
    st.write(
        f"Position monitor: {desk.monitor_checks:,} checks; FinBERT triage sent "
        f"{desk.monitor_after_triage:,} to the model. {desk.monitor_scored:,} scored and "
        f"{desk.monitor_abstained:,} abstained. An abstention is unknown, not neutral news."
    )
    audit = svc.summary.audit
    st.subheader("Selection and overfitting")
    st.write(
        f"Across {audit.trials} tracked designs, PBO is {audit.pbo:.2f}. Deflated Sharpe "
        f"is {audit.dsr_2010_2023['132']:.2f} over 2010–2023 and "
        f"{audit.dsr_2018_2023['132']:.2f} over 2018–2023. Neither reaches 0.95."
    )
    st.write(
        "The +track forecaster is a post-hoc best observed variant. Repeated inspection "
        "of development periods limits the strength of selection claims."
    )
    news = svc.summary.news
    st.subheader("News-source shift")
    st.write(
        f"The final-test news source is {news.source_2024_2025}. Its toned-session density "
        f"is about {news.toned_session_ratio:.2f}× the development source. This is an input "
        "coverage limitation, not a final-test performance result."
    )
    provenance(svc)
    link("monitor", "Inspect the earlier study's data health")


def methods() -> None:
    components.page_header(
        "How to read this research",
        "Forecasting and portfolio construction "
        "answer different questions. Keep their targets and cohorts separate.",
    )
    svc = service()
    if svc is None:
        return
    st.subheader("Goal 1 · predict mean reversion")
    st.write(svc.manifest.cohorts[DEFAULT_PERIOD].definition)
    st.write(
        "ROC AUC measures event ranking; PR AUC focuses on positive-event precision and "
        "recall. Brier score and log loss assess probability quality. Higher AUC is better; "
        "lower loss is better. Neither measures investment return."
    )
    for model in svc.manifest.models:
        with st.expander(f"{model.name} — {model.role}"):
            st.write(model.explanation)
    st.subheader("Goal 2 · construct the book")
    st.dataframe(
        pd.DataFrame(svc.summary.design, columns=["Part", "Saved design choice"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Selection cutoffs use the previous year's scores (Decision 110d). The source "
        "export's phrase 'top 20% of each test year' names the eligibility target, "
        "not a cutoff fitted on future test-year outcomes."
    )
    st.write(
        "CAGR with cash includes interest; CAGR excluding cash removes that interest. "
        "Sharpe and reported risk statistics use excess-cash returns. Costs include the "
        "saved trading assumptions, not a promise of executable future returns."
    )
    st.subheader("Full model and baselines")
    st.write(
        "The Full model adds the source-grounded analyst, bull/bear and risk desk to "
        "a forecaster on an eligible subset. Entry scores did not improve results; "
        "position-monitor exits were adopted. Its subset is not a fifth matched-population "
        "forecast row. Baseline 0/1 and the earlier A/B strategy ladder remain reference views."
    )
    link("strategy", "Open the reference strategy ladder")
    st.subheader("Chronology and provenance")
    st.write(
        "Selection: 2010–2017. Development confirmation: 2018–2023. The earlier accepted "
        "study instead uses a 2022–2023 assessment with its own models and calibration. "
        "Those probabilities cannot be relabelled as current walk-forward predictions."
    )
    st.write(
        "Previous-session VIX and conservative SEC timestamps protect the information "
        "cutoff. Missing evidence remains UNKNOWN. The surviving-issuer roster, current "
        "business classifications and modern language models used on historical text "
        "are retrospective limitations."
    )
    provenance(svc)


def reference_notice() -> None:
    st.info(
        "Reference study · earlier accepted A/B generation, 2022–2023 assessment. "
        "These event scores and diagnostics are not the current walk-forward model outputs."
    )


def footer() -> None:
    st.markdown(
        '<div class="sb-footer">Saved research exports · read-only · '
        + html.escape("Development evidence, not established alpha")
        + "</div>",
        unsafe_allow_html=True,
    )

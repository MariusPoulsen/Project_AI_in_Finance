"""Comparison workspace, fixed rules and saved diagnostics; no report conclusions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from structural_break.app_ui import components, data
from structural_break.services.research_summary import PERIODS, ResearchSummaryService
from structural_break.services.workspace_diagnostics import registry_coverage, registry_events

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
        st.caption(svc.manifest.source)
        st.caption(svc.manifest.precision)
        st.caption(f"Presentation snapshot SHA-256: {svc.snapshot_id}")
        st.dataframe(
            pd.DataFrame(svc.study.sources.items(), columns=["Source", "Identity"]),
            hide_index=True,
            width="stretch",
        )
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


def forecast_rules() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("Event", "Fresh divergence crossing |z| ≥ 2"),
            ("Success", "Reach |z| ≤ 0.5 before |z| ≥ 3"),
            ("Horizon", "20 trading sessions"),
            ("Failure barrier", "|z| ≥ 3 before convergence"),
            ("Population comparison", "Same labelled events and period for the four forecasters"),
            ("Baselines", "Deterministic selection policies; no probability forecast"),
            ("Full comparison", "Matched top-40% desk region; separate from population metrics"),
        ],
        columns=["Rule", "Definition"],
    )


def book_rules(svc: ResearchSummaryService) -> pd.DataFrame:
    rows = []
    for part, choice in svc.summary.design:
        if part == "Selection":
            rows.extend(
                [
                    ("Selection", "Original Model B / R0; top 20% by previous-year score cutoff"),
                    (
                        "Entry filters",
                        "R1 fresh-news; mean crossing within 120 sessions; "
                        "exclude the most expensive cost fifth",
                    ),
                ]
            )
            continue
        elif part == "Exits":
            rows.extend(
                [
                    ("Take profit", "|z| ≤ 1"),
                    ("Z-score stop", "None"),
                    ("Time stop", "clip(ceil(1.5 × half-life), 10, 40) sessions; 20 if unknown"),
                    ("News exit", "8-K adverse-tone exit"),
                    ("Monitor exit", "Adverse ≥ 5 and persistence ≥ 5"),
                ]
            )
            continue
        rows.append((part, choice))
    return pd.DataFrame(rows, columns=["Rule", "Definition"])


def render() -> None:
    components.page_header(
        "Research comparisons", "Forecast metrics, portfolio statistics and fixed rules."
    )
    svc = service()
    if svc is None:
        return
    period = period_control("sb_overview_period")
    cohort_line(svc, period)
    left, right = st.container(), st.container()
    with left:
        st.subheader("Forecasting")
        rows = svc.forecast_comparison(period).drop(columns="id")
        for metric, digits in (("ROC AUC", 3), ("Brier score", 4)):
            rows[metric] = [
                f"{value:.{digits}f}"
                if pd.notna(value)
                else "Regional"
                if model == "Full model"
                else "Policy"
                for value, model in zip(rows[metric], rows["Model"], strict=True)
            ]
        st.dataframe(
            rows[["Model", "Role", "ROC AUC", "Brier score"]],
            hide_index=True,
            width="stretch",
            column_config={
                "ROC AUC": st.column_config.TextColumn(),
                "Brier score": st.column_config.TextColumn(),
            },
        )
        st.caption(
            "Policy = deterministic selection. Regional = matched desk subset; "
            "open Forecasting for the separate comparison."
        )
        link("forecast", "Open forecast comparison")
        with st.expander("Forecasting rules"):
            st.table(forecast_rules())
    with right:
        st.subheader("Portfolio")
        stats = svc.book_comparison(period)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Selection": row["Selection"],
                        "Monitor": row["Monitor"],
                        "Sharpe · excess cash": round(row["sharpe"], 3),
                        "CAGR · excluding cash": components.pct(row["cagr"], 2),
                        "Max DD · excess cash": components.pct(row["max_drawdown"], 2),
                    }
                    for _, row in stats.iterrows()
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Sharpe · excess cash": st.column_config.NumberColumn("Sharpe", format="%.3f"),
                "CAGR · excluding cash": st.column_config.TextColumn("CAGR excl. cash"),
                "Max DD · excess cash": st.column_config.TextColumn("Max DD"),
            },
        )
        st.caption("Sharpe and max drawdown exclude cash interest.")
        link("book", "Open portfolio comparison")
        with st.expander("Book rules"):
            st.table(book_rules(svc))
    link("evidence", "Open diagnostics")
    provenance(svc)


def evidence() -> None:
    components.page_header(
        "Evidence and diagnostics", "Available exports, coverage and saved diagnostic statistics."
    )
    svc = service()
    if svc is None:
        return
    st.subheader("Export availability")
    st.dataframe(
        pd.DataFrame(svc.study.availability),
        hide_index=True,
        width="stretch",
    )
    st.subheader("Agent coverage")
    desk = svc.summary.desk
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Stage": "Entry desk",
                    "Checks": "—",
                    "After triage": "—",
                    "Scored": desk.entry_scored,
                    "Abstained": desk.entry_abstained,
                },
                {
                    "Stage": "Position monitor",
                    "Checks": f"{desk.monitor_checks:,}",
                    "After triage": f"{desk.monitor_after_triage:,}",
                    "Scored": desk.monitor_scored,
                    "Abstained": desk.monitor_abstained,
                },
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption("Abstentions remain UNKNOWN; they are not neutral observations.")
    audit = svc.summary.audit
    st.subheader("Selection diagnostics")
    st.caption(f"{audit.trials} tracked designs · PBO {audit.pbo:.3f}")
    st.dataframe(
        pd.DataFrame(
            [
                {"Period": "2010–2023", "Deflated Sharpe": audit.dsr_2010_2023["132"]},
                {"Period": "2018–2023", "Deflated Sharpe": audit.dsr_2018_2023["132"]},
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption("Development periods were reused. Model roles identify post-hoc variants.")
    news = svc.summary.news
    st.subheader("News coverage")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Source": news.source_2024_2025,
                    "Scope": "2024–2025 inputs",
                    "Toned-session ratio to development": news.toned_session_ratio,
                    "Coverage ratio to development": news.coverage_ratio,
                }
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    with st.expander("Registry, source coverage and feature distributions"):
        outcome = data.registry()
        if outcome.service is None:
            st.info("The underlying registry diagnostics export is unavailable.")
        else:
            registry = outcome.service
            events = registry_events(registry)
            st.caption(
                "Underlying fixed-20-session registry; counts differ from the matched "
                "annual walk-forward scoring cohort. No superseded scores are exposed."
            )
            st.dataframe(
                events.groupby(events.date.dt.year)
                .agg(Events=("event_id", "size"), Pairs=("pair_id", "nunique"))
                .reset_index(names="Year"),
                hide_index=True,
                width="stretch",
            )
            st.dataframe(registry_coverage(registry), hide_index=True, width="stretch")
            features = registry.drift_features(20)
            if features:
                feature = st.selectbox("Feature distribution", features)
                distribution = registry.drift(20, feature)
                if not distribution.empty:
                    st.dataframe(
                        distribution.drop(columns="period", errors="ignore"),
                        hide_index=True,
                        width="stretch",
                    )
            components.provenance(
                {
                    "Registry": registry.identity.registry_version,
                    "Bundle": registry.identity.bundle_id,
                }
            )
    with st.expander("Current model inventory"):
        st.dataframe(svc.catalogue().drop(columns="id"), hide_index=True, width="stretch")
    provenance(svc)


def methods() -> None:
    components.page_header(
        "Rules and definitions",
        "Fixed forecast targets, book configuration and metric definitions.",
    )
    svc = service()
    if svc is None:
        return
    st.subheader("Forecasting rules")
    st.table(forecast_rules())
    st.subheader("Book rules")
    st.table(book_rules(svc))
    with st.expander("Model registry"):
        st.dataframe(
            svc.catalogue().drop(columns="id"),
            hide_index=True,
            width="stretch",
        )
    with st.expander("Metric definitions"):
        st.table(
            pd.DataFrame(
                [
                    ("ROC AUC", "Event ranking", "Higher"),
                    ("PR AUC", "Precision–recall ranking; cohort-dependent prevalence", "Higher"),
                    ("Brier score", "Mean squared probability error", "Lower"),
                    ("Log loss", "Probability loss; penalizes confident errors", "Lower"),
                    ("Sharpe", "Risk-adjusted return in excess of cash", "Higher"),
                    ("CAGR with cash", "Compounded growth including cash interest", "Higher"),
                    (
                        "Max drawdown · excess cash",
                        "Peak-to-trough loss excluding cash interest",
                        "Closer to zero",
                    ),
                ],
                columns=["Metric", "Definition", "Direction"],
            )
        )
    with st.expander("Chronology and information cutoff"):
        st.table(
            pd.DataFrame(
                [
                    ("Selection", "2010–2017"),
                    ("Development confirmation", "2018–2023"),
                    ("Policy benchmark", "2022–2023; next-open execution, fixed 20-session cap"),
                    (
                        "Model fitting",
                        "Expanding earlier years; transformations fitted within training",
                    ),
                    ("Full region", "R0 top 40%; same regional rows for base and agent stack"),
                    ("Final test", "2024–2025; locked in this snapshot"),
                    ("VIX", "Previous NYSE session"),
                    ("SEC evidence", "Admissible by event close; missing evidence remains UNKNOWN"),
                ],
                columns=["Scope", "Definition"],
            )
        )
    with st.expander("Data limits and research safeguards"):
        st.table(
            pd.DataFrame(
                [
                    (
                        "Universe",
                        "Frozen surviving-issuer roster and current business classifications",
                    ),
                    ("Prices", "Retrospective Yahoo adjustments; not a vintage investable feed"),
                    ("Historical text", "Modern pretrained text models applied retrospectively"),
                    ("Missing evidence", "UNKNOWN retained; unscheduled extraction is not no-news"),
                    (
                        "Development reuse",
                        "Selection and confirmation periods were already observed",
                    ),
                    (
                        "App operation",
                        "Saved outputs only; no fitting, downloads or provider calls",
                    ),
                ],
                columns=["Item", "Definition"],
            )
        )
    provenance(svc)


def footer() -> None:
    st.markdown(
        '<div class="sb-footer">Saved research exports · read-only</div>', unsafe_allow_html=True
    )

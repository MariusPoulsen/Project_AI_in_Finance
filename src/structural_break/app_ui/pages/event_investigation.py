"""One event: contemporaneous forecasts/evidence, then the separate realised outcome."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_bundle.features import feature_label
from structural_break.app_ui import components, explanation_view, navigation, theme
from structural_break.app_ui.context import current, open_pair
from structural_break.app_ui.results import event_table
from structural_break.services.current_monitor import feature_block
from structural_break.services.event_investigation import evidence_record

ROLES = {
    "analyst": "Pair news analyst",
    "mean_reversion_opening": "Bull · reversion case",
    "structural_break_opening": "Bear · structural break case",
    "mean_reversion_rebuttal": "Bull · rebuttal",
    "structural_break_rebuttal": "Bear · rebuttal",
    "facilitator": "Debate facilitator",
    "judge": "Risk judge",
}


def render() -> None:
    ctx = current()
    if ctx.results is None:
        components.page_header("Event investigation", "Inspect one published divergence.")
        components.empty_state("Current forecasting results are not deployed.")
        return
    results = ctx.results
    rows = event_table(results)
    event_id = st.query_params.get("event", "")
    if event_id not in set(rows.event_id):
        components.page_header(
            "Event investigation",
            "Open an event from Scanner to inspect its forecasts, evidence and outcome.",
        )
        if event_id:
            st.warning(
                "This event ID is not in the published results. "
                "Check the link or choose an event from Scanner."
            )
        if st.button("Open Scanner", type="primary"):
            navigation.switch("scanner")
        return
    row = rows.loc[rows.event_id.eq(event_id)].iloc[0]
    components.page_header(
        f"{row['pair'].replace('__', ' / ')} · {row['date']:%d %b %Y}",
        f"{row['group']} · {str(row['period']).capitalize()} · "
        f"divergence z = {row['z_at_event']:+.2f}",
    )
    with st.container(key="investigation_actions"):
        actions = st.columns([1, 1, 2])
        if actions[0].button(
            "Back", icon=":material/arrow_back:", help="Return to Scanner with the same filters"
        ):
            navigation.switch("scanner")
        if actions[1].button(
            "Pair",
            icon=":material/stacked_line_chart:",
            help="Open this pair's price and spread history",
        ):
            open_pair(str(row["pair"]), str(event_id))
        with actions[2]:
            navigation.share("event", label="Share")
    with st.container(key="investigation_metrics"):
        cols = st.columns(4)
        for col, model in zip(cols, ("r0", "bag5", "track", "full"), strict=True):
            col.metric(
                {
                    "r0": "R0",
                    "bag5": "Bagged +OU",
                    "track": "Bagged +OU +track",
                    "full": "Full model",
                }[model],
                components.pct(row[f"p_{model}"]),
            )
    st.caption(
        "Saved annual walk-forward probabilities. Each annual model uses earlier years only. "
        "Full is available only where the entry desk supplied a usable forecast; "
        "a missing score is not zero."
    )
    tabs = st.tabs(
        ["Forecast and SHAP", "Evidence and agents", "Outcome and trade", "Input values"]
    )
    with tabs[0]:
        st.subheader("What moved the forecast?")
        full = results.tables["forecasts"].set_index("event_id").loc[event_id]
        if pd.notna(full.p_full):
            base, value = float(full.p_full_base), float(full.p_full)
            st.write(
                f"Probability-only stack **{base:.2%}** → Full model **{value:.2%}** · "
                f"change **{100 * (value - base):+.2f} percentage points**."
            )
            st.caption(
                "Both stacks use this desk-covered event. The probability-only comparator "
                "is fitted separately; it differs from the raw bagged probability above."
            )
        explanation_view.render_event(results, str(event_id))
    with tabs[1]:
        _evidence(results.tables.get("event_cases", pd.DataFrame()), str(event_id))
    with tabs[2]:
        _outcome(row)
    with tabs[3]:
        inputs = results.tables.get("diagnostic_inputs", pd.DataFrame())
        hit = inputs.loc[inputs.event_id.eq(event_id)] if not inputs.empty else inputs
        if hit.empty:
            components.empty_state("Current input values are not exported for this event.")
        else:
            fields = hit.drop(columns="event_id").iloc[0]
            table = pd.DataFrame({"Feature": fields.index, "Value": fields.values})
            table["Group"] = table.Feature.map(feature_block)
            table["Description"] = table.Feature.map(feature_label)
            st.dataframe(
                table[["Group", "Description", "Feature", "Value"]],
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Download event inputs",
                table.to_csv(index=False),
                file_name=f"inputs-{event_id}.csv",
                mime="text/csv",
            )
            st.caption(
                "Exported input values at the event close; missing values remain missing. "
                "Track features use only earlier events whose target windows had resolved."
            )
    components.provenance(
        {
            "Event": event_id,
            "Forecast export": results.manifest.get("commit"),
            "Forecast SHA-256": results.manifest["files"]["forecasts.parquet"],
            "Evidence / inputs schema": results.manifest.get("investigation_reference", {}).get(
                "schema_version"
            ),
        }
    )


def _evidence(cases: pd.DataFrame, event_id: str) -> None:
    st.subheader("Evidence available at the close")
    try:
        case, result, status = evidence_record(cases, event_id)
    except (ValueError, KeyError, TypeError):
        st.error(
            "The cached evidence does not match its event or citations. "
            "It is hidden until the export is repaired."
        )
        return
    if case is None:
        components.empty_state(
            "NO_NEWS: the cached desk inventory has no available news for this event."
            if status == "NO_NEWS"
            else status
            + ". No cached evidence pack is available; this does not establish an absence of news."
        )
        return
    evidence = case["event"]["evidence"]
    st.caption(
        f"{len(evidence)} source chunks · cutoff {case['event']['event_timestamp']} · "
        "cached analyst material, with company names masked as in the experiment. "
        "Context summaries are distinguished from primary excerpts."
    )
    if result is not None:
        st.markdown("**Entry desk assessment**")
        scores = result.get("scores")
        st.write(
            f"Status: **{result['status']}** · "
            f"Debate: **{'run' if result.get('debated') else 'not triggered'}**"
        )
        if scores:
            st.dataframe(
                pd.DataFrame(
                    {
                        "Assessment": ["Explains the move", "Persistence", "Relationship change"],
                        "Score (1–5)": [
                            scores[k]
                            for k in ("explains_move", "persistence", "relationship_change")
                        ],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
        stages = result.get("stages", {})
        order = [
            "analyst",
            "mean_reversion_opening",
            "structural_break_opening",
            "mean_reversion_rebuttal",
            "structural_break_rebuttal",
            "facilitator",
            "judge",
        ]
        for role in [r for r in order if r in stages] + [r for r in stages if r not in order]:
            stage = stages[role]
            with st.expander(
                ROLES.get(role, role.replace("_", " ").capitalize())
                + f" · {stage.get('status', 'UNKNOWN')}"
            ):
                report: dict[str, Any] = stage.get("report") or {}
                if not report:
                    st.caption(
                        "No validated report is cached for this stage. "
                        "A failed/abstained stage is not treated as a neutral assessment."
                    )
                    continue
                for claim in report.get("claims", []):
                    st.write(f"**{claim.get('kind', 'Assessment')}** · {claim['text']}")
                    for citation in claim.get("citations", []):
                        st.caption(f"Leg {citation['leg']} · {citation['chunk_id']}")
                        st.text(citation["quote"])
                if report.get("uncertainties"):
                    st.markdown("**Uncertainties**")
                    for note in report["uncertainties"]:
                        st.write(note)
                other = {k: v for k, v in report.items() if k not in ("claims", "uncertainties")}
                if other:
                    st.json(other, expanded=False)
        st.caption(
            "Roles run conditionally. The statistical stack uses the final structured "
            "assessments; agents do not issue orders. The position monitor is a separate "
            "post-entry exit component."
        )
    else:
        st.info("A case was prepared, but no current validated agent result is cached.")
    st.markdown("**Sources and cited excerpts**")
    for chunk in sorted(evidence, key=lambda c: c["source_timestamp"]):
        kind = (
            "Context summary"
            if chunk["filing_id"] == "analyst-context"
            else "Company headlines"
            if "headline" in chunk["filing_id"]
            else "SEC filing excerpt"
        )
        with st.expander(f"{kind} · leg {chunk['leg']} · {chunk['source_timestamp']}"):
            st.text(chunk["text"])
            st.caption(
                f"Source {chunk['filing_id']} · "
                f"offsets {chunk['start_offset']}–{chunk['end_offset']} · "
                f"chunk {chunk['chunk_id']} · SHA-256 {chunk['document_sha256']}"
            )


def _outcome(row: pd.Series) -> None:
    ctx = current()
    assert ctx.results is not None
    st.subheader("What happened afterwards?")
    cols = st.columns(3)
    cols[0].metric("Forecasting label", row["outcome"])
    cols[1].metric("Adopted book entry", "Entered" if row["traded"] else "Not entered")
    cols[2].metric(
        "Trade gross return", "—" if pd.isna(row["trade_bps"]) else f"{row['trade_bps']:+.1f} bps"
    )
    st.caption(
        "The label is reversion inside ±0.5 before ±3 within 20 sessions. "
        "The book uses its own exits; the label and a trade's return answer different "
        "questions. Outcomes below were not available to the forecast."
    )
    with st.spinner("Loading this event's spread history…"):
        series = ctx.service.pair_series(str(row["pair"]))
    if series is not None and not series.state.empty:
        state = series.state.copy()
        dates = pd.to_datetime(state.trading_date)
        center = pd.Timestamp(row["date"])
        state = state.loc[dates.between(center - timedelta(days=90), center + timedelta(days=65))]
        points = pd.DataFrame({"date": [center], "z_at_event": [row["z_at_event"]]})
        # Use only the line and fixed target bands here; no future values enter a predictor.
        figure = go.Figure(
            go.Scatter(
                x=state.trading_date,
                y=state.z_score,
                mode="lines",
                line={"color": theme.NEUTRAL},
                name="Spread z",
            )
        )
        for bound in (-3, -2, -0.5, 0.5, 2, 3):
            figure.add_hline(
                y=bound,
                line_dash="dot",
                line_color=theme.MODEL_B if abs(bound) == 0.5 else theme.GRID,
            )
        figure.add_vline(x=center.timestamp() * 1000, line_color=theme.INK, line_dash="dash")
        figure.add_trace(
            go.Scatter(
                x=points.date,
                y=points.z_at_event,
                mode="markers",
                marker={"color": theme.ENTRY, "size": 9},
                name="Event close",
            )
        )
        figure.update_layout(theme.layout(height=300, yaxis={"title": "Frozen spread z-score"}))
        components.chart(figure, key="investigation_spread")
    trades = ctx.results.tables["trades"]
    trade = trades.loc[trades.event_id.eq(row["event_id"])]
    if not trade.empty:
        st.markdown("**Adopted book trade**")
        st.dataframe(
            trade.drop(columns=["event_id"], errors="ignore"), hide_index=True, width="stretch"
        )
        st.caption(
            "Gross return is before portfolio costs and the residual sleeve; "
            "it is not portfolio NAV return."
        )
    else:
        st.caption(
            "No adopted-book trade is recorded for this event. The available export "
            "does not establish which execution filter prevented an entry."
        )

"""Explain and compare the agent-augmented probability on its matched event population."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from structural_break.app_ui import components

AGENT_INPUTS = [
    ("Explains the move", "Does the available news account for the observed divergence?", "1–5"),
    ("Persistence", "How persistent is the news-driven change likely to be?", "1–5"),
    (
        "Relationship change",
        "Does the evidence suggest the pair's relationship has changed?",
        "1–5",
    ),
    ("Explains × persistence", "Interaction between the first two assessments", "Product"),
    ("No news", "The case has no available news evidence", "Indicator"),
    ("Abstain", "No usable, validated agent assessment is available", "Indicator"),
]


def render(metrics: pd.DataFrame, period: str) -> None:
    st.markdown("### What the agents add to the forecast")
    st.write(
        "The Full model combines the bagged B+rule+ou forecast with structured assessments "
        "of the pair's news. A logistic model learns how much weight to give that evidence "
        "and outputs an updated probability of mean reversion."
    )
    st.markdown(
        "**Bagged reversion probability + agent evidence scores → annual logistic stack "
        "→ Full model reversion probability**"
    )
    st.caption(
        "Each year's stack is fitted on earlier years only. The agents supply evidence scores; "
        "the fitted statistical model converts them into a probability."
    )

    st.markdown(f"**Agent contribution · {period}**")
    st.write(
        "Forecast only uses the bagged probability in the same annual logistic stack. "
        "Full model adds the six agent inputs below. Both are evaluated on the same "
        "desk-covered events, so the difference isolates the added agent information."
    )
    part = metrics.loc[
        metrics.period.eq(period) & metrics.model.isin(["full_base", "full"])
    ].set_index("model")
    if set(part.index) != {"full_base", "full"} or part.index.duplicated().any():
        components.empty_state("The matched Full model comparison is not exported for these years.")
    else:
        base, full = part.loc["full_base"], part.loc["full"]
        if base["n"] != full["n"] or not np.isclose(base["base_rate"], full["base_rate"]):
            st.error(
                "The exported comparison populations differ; agent effects cannot be compared."
            )
            return
        st.caption(
            f"{int(base['n']):,} labelled events in each version · "
            f"reversion rate {components.pct(base['base_rate'])} · "
            "this desk subset differs from the all-event headline comparison."
        )
        rows = []
        for key, label in (
            ("roc_auc", "ROC AUC ↑"),
            ("pr_auc", "PR AUC ↑"),
            ("log_loss", "Log loss ↓"),
            ("brier", "Brier ↓"),
        ):
            rows.append(
                {
                    "Metric": label,
                    "Forecast only": base[key],
                    "Full model": full[key],
                    "Change": full[key] - base[key],
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={
                "Forecast only": st.column_config.NumberColumn(format="%.4f"),
                "Full model": st.column_config.NumberColumn(format="%.4f"),
                "Change": st.column_config.NumberColumn(
                    "Change (Full − forecast only)", format="%+.4f"
                ),
            },
        )
        st.caption(
            "↑ Higher is better; ↓ lower is better. Change is Full model minus forecast only. "
            "These are forecasting metrics; portfolio returns are evaluated in Strategy Lab."
        )

    with st.expander("Agent inputs and how they are produced"):
        st.table(pd.DataFrame(AGENT_INPUTS, columns=["Added input", "Meaning", "Value"]))
        st.markdown(
            "- **Pair news analyst:** assesses both companies' available news.\n"
            "- **Bull/bear debate and facilitator:** test the reversion and structural-break "
            "explanations on contested cases and revise the assessments.\n"
            "- **Risk judge:** checks citation support for design candidates; unsupported "
            "assessments become ABSTAIN."
        )
        st.caption(
            "Debate and risk review run on their designated subsets. NO_NEWS and ABSTAIN "
            "remain distinct indicators, rather than neutral news judgments. The effect of "
            "each score is learned from earlier events; there is no fixed probability bonus. "
            "The position monitor is a separate exit component of the trading strategy."
        )

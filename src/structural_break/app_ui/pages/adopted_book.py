"""The adopted trading book and the full model (Decisions 105-117), from demo/book/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from structural_break.app_ui import components, theme

SUMMARY = Path("demo/book")
COLORS = {
    "Adopted book (with monitor exit)": theme.MODEL_B,
    "Same book without the monitor exit": theme.MODEL_A,
}


@st.cache_data(show_spinner=False)
def _load(root: str) -> tuple[dict[str, Any], pd.DataFrame] | None:
    folder = Path(root)
    if not (folder / "summary.json").is_file() or not (folder / "book_daily.parquet").is_file():
        return None
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    return summary, pd.read_parquet(folder / "book_daily.parquet")


def _curves(daily: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    for name, color in COLORS.items():
        figure.add_trace(
            go.Scatter(
                x=daily["session_date"],
                y=daily[name],
                name=name,
                line={"color": color, "width": 1.8},
                hovertemplate="%{x|%d %b %Y}<br>%{y:.3f}<extra></extra>",
            )
        )
    figure.add_vline(
        x=pd.Timestamp("2018-01-01"), line={"color": theme.MUTED, "dash": "dot", "width": 1}
    )
    figure.update_layout(
        theme.layout(height=340, yaxis={"title": "Value (start 1.0, with cash interest)"})
    )
    return figure


def render() -> None:
    components.page_header(
        "Adopted book",
        "The trading book chosen on 2010–2017 and confirmed once on 2018–2023: the original "
        "Model B "
        "selects the trades, and the agent desk's position monitor can close them early.",
    )
    root = Path.cwd() / SUMMARY
    loaded = _load(str(root))
    if loaded is None:
        components.empty_state(
            "No book summary was found in demo/book. Create it with "
            "`python scripts/export_book_summary.py`."
        )
        return
    summary, daily = loaded
    stats = summary["stats"]["Adopted book (with monitor exit)"]
    columns = st.columns(4)
    for column, (label, period) in zip(
        columns,
        (
            ("Sharpe, 2010–2017", "2010–2017 (selection)"),
            ("Sharpe, 2018–2023", "2018–2023 (holdout)"),
            ("CAGR with cash, 2010–2023", "2010–2023"),
            ("Max drawdown, 2010–2023", "2010–2023"),
        ),
        strict=True,
    ):
        s = stats[period]
        value = {
            "Sharpe, 2010–2017": f"{s['sharpe']:.2f}",
            "Sharpe, 2018–2023": f"{s['sharpe']:.2f}",
            "CAGR with cash, 2010–2023": components.pct(s["cagr_with_cash"]),
            "Max drawdown, 2010–2023": components.pct(s["max_drawdown"]),
        }[label]
        column.metric(label, value)
    components.chart(_curves(daily), key="book_curves")
    st.caption(
        "The dotted line marks the start of the 2018–2023 holdout. Final test 2024–2025 locked."
    )

    st.subheader("Design")
    st.dataframe(
        pd.DataFrame(summary["design"], columns=["Part", "Choice"]),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Both books by period")
    rows = []
    for name, periods in summary["stats"].items():
        for period, s in periods.items():
            rows.append(
                {
                    "Book": name,
                    "Period": period,
                    "Sharpe": round(s["sharpe"], 3),
                    "CAGR": components.pct(s["cagr"]),
                    "CAGR with cash": components.pct(s["cagr_with_cash"]),
                    "Max drawdown": components.pct(s["max_drawdown"]),
                    "Turnover (x/yr)": round(s["turnover"], 1),
                    "Costs (/yr)": components.pct(s["cost"], 2),
                }
            )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("Goal 1: reversion forecasters")
    st.dataframe(pd.DataFrame(summary["goal1"]), hide_index=True, width="stretch")

    audit = summary["audit"]
    components.verdict_box(
        "Overfitting audit (Decision 113)",
        f" Across {audit['trials']} tracked designs the probability of backtest overfitting is "
        f"{audit['pbo']:.2f}, and the book's deflated Sharpe ratio is "
        f"{audit['dsr_2010_2023']['132']:.2f} for 2010–2023 ({audit['dsr_2018_2023']['132']:.2f} for "  # noqa: E501
        "2018–2023), below the usual 0.95 bar. The 2024–2025 final test is the clean test.",
        "inconclusive",
    )

    desk, news = summary["desk"], summary["news"]
    st.subheader("Agent desk")
    st.markdown(
        f"- **Entry agents** (pair news analyst, bull/bear debate, risk judge): {desk['entry_scored']:,} "  # noqa: E501
        f"events scored, {desk['entry_abstained']} abstained. Their scores did not improve the forecast "  # noqa: E501
        "or the book, so they are reported but not used.\n"
        f"- **Position monitor:** a FinBERT triage sent {desk['monitor_after_triage']:,} of "
        f"{desk['monitor_checks']:,} checks to the model; {desk['monitor_scored']:,} were scored. A trade "  # noqa: E501
        "closes when the monitor rates new news adverse 5 and persistent 5 (Decision 110d).\n"
        f"- **News for 2024–2025:** {news['source_2024_2025']}, which is about "
        f"{news['toned_session_ratio']:.1f}× denser than the development source (Decision {news['decision']})."  # noqa: E501
    )
    st.caption(summary["decisions"])

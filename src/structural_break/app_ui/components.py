"""Small shared UI pieces: headers, banners, states and number formatting."""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_bundle.contracts import BundleIdentity
from structural_break.app_ui import theme


def fmt(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    return f"{float(value):.{digits}f}"


def pct(value: Any, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    return f"{100 * float(value):.{digits}f}%"


def bps(value: Any, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    return f"{1e4 * float(value):+.{digits}f} bps"


def count(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    return f"{int(value):,}"


def page_header(title: str, lede: str) -> None:
    st.title(title)
    st.markdown(f'<p class="sb-lede">{html.escape(lede)}</p>', unsafe_allow_html=True)


def synthetic_banner(identity: BundleIdentity) -> None:
    if identity.synthetic:
        st.markdown(
            '<div class="sb-synthetic">Synthetic preview: every ticker, price, label and '
            "result on this page is invented to demonstrate the interface. "
            "It is not a research finding.</div>",
            unsafe_allow_html=True,
        )


def verdict_box(title: str, body: str, tone: str) -> None:
    accent = {
        "favours_b": theme.MODEL_B,
        "favours_a": theme.MODEL_A,
        "inconclusive": theme.ENTRY,
        "unavailable": theme.MUTED,
    }.get(tone, theme.MUTED)
    st.markdown(
        f'<div class="sb-verdict" style="--sb-accent:{accent}"><strong>{html.escape(title)}'
        f"</strong>{html.escape(body)}</div>",
        unsafe_allow_html=True,
    )


def legend(items: list[tuple[str, str]]) -> None:
    spans = "".join(
        f'<span><i style="background:{color}"></i>{html.escape(label)}</span>'
        for label, color in items
    )
    st.markdown(f'<div class="sb-legend">{spans}</div>', unsafe_allow_html=True)


def empty_state(message: str) -> None:
    st.info(message, icon=":material/inbox:")


def provenance(lines: dict[str, Any]) -> None:
    """Version context for the values above it (PLAN P7 acceptance)."""
    with st.expander("Data and model versions behind this page"):
        st.dataframe(
            pd.DataFrame({"Item": list(lines), "Identity": [str(v) for v in lines.values()]}),
            hide_index=True,
            width="stretch",
        )


def chart(figure: Any, key: str | None = None) -> None:
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
        key=key,
    )

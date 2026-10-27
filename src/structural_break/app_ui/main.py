"""Seven current research views; fixed forecast target and no legacy navigation."""

from __future__ import annotations

import logging
from collections.abc import Callable

import streamlit as st

from structural_break.app_ui import data, theme
from structural_break.app_ui.context import KEY, AppContext
from structural_break.app_ui.pages import forecasting, pair_detail, portfolio, scanner, workspace

LOGGER = logging.getLogger(__name__)


def _investigate(render: Callable[[], None]) -> Callable[[], None]:
    def view() -> None:
        outcome = data.registry()
        if outcome.service is None:
            st.info(
                "The underlying event registry is unavailable. Forecast and book summaries "
                "remain accessible."
            )
            return
        st.session_state[KEY] = AppContext(
            service=outcome.service, horizon=20, pages=st.session_state["_sb_pages"]
        )
        render()

    return view


def _pages() -> dict[str, st.Page]:
    return {
        "overview": st.Page(workspace.render, title="Overview", default=True),
        "forecast": st.Page(forecasting.render, title="Forecasting", url_path="forecasting"),
        "book": st.Page(portfolio.render, title="Portfolio", url_path="book"),
        "scanner": st.Page(
            _investigate(scanner.render), title="Event explorer", url_path="scanner"
        ),
        "pair": st.Page(_investigate(pair_detail.render), title="Pair detail", url_path="pair"),
        "evidence": st.Page(
            workspace.evidence, title="Evidence and diagnostics", url_path="evidence"
        ),
        "method": st.Page(workspace.methods, title="Rules and definitions", url_path="methodology"),
    }


def run(load: Callable[[], data.LoadOutcome] | None = None) -> None:
    st.set_page_config(
        page_title="Structural Break", page_icon=":material/analytics:", layout="wide"
    )
    st.markdown(theme.CSS, unsafe_allow_html=True)
    if load is not None:
        st.session_state["_sb_registry_outcome"] = load()
    pages = _pages()
    st.session_state["_sb_pages"] = pages
    navigation = st.navigation(list(pages.values()), position="hidden")
    with st.sidebar:
        st.markdown('<div class="sb-brand">Structural Break</div>', unsafe_allow_html=True)
        st.caption("Mean-reversion research")
        for heading, keys in (
            ("Research", ("overview", "forecast", "book")),
            ("Investigate", ("scanner", "pair")),
            ("Evidence", ("evidence", "method")),
        ):
            st.markdown(f"**{heading}**")
            for key in keys:
                st.page_link(pages[key], label=pages[key].title)
        st.caption("Forecast target · 20 sessions")
        st.caption("Book time stop · 10–40 sessions")
        st.markdown(
            '<p class="sb-lock">Final test 2024–2025 locked in this snapshot</p>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="sb-status"><span>Structural Break · research workspace</span>'
        "<span>Development through 2023</span><span>Final test · locked snapshot</span></div>",
        unsafe_allow_html=True,
    )
    try:
        navigation.run()
    except Exception:  # noqa: BLE001
        LOGGER.exception("Research presentation failed")
        st.error(
            "This view could not be drawn from the saved outputs. "
            "Ask the owner to verify the presentation export."
        )
    workspace.footer()

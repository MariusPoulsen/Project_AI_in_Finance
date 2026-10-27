"""Read-only research workspace, with independently available current and reference data."""

from __future__ import annotations

import logging
from collections.abc import Callable

import streamlit as st

from structural_break.app_ui import data, theme
from structural_break.app_ui.context import KEY, AppContext
from structural_break.app_ui.pages import (
    forecasting,
    methodology,
    model_lab,
    monitor,
    pair_detail,
    portfolio,
    scanner,
    strategy_lab,
    workspace,
)

TITLE = "Structural Break"
LOGGER = logging.getLogger(__name__)
REFERENCE_PATHS = {"scanner", "pair", "models", "strategy", "data-health", "reference-methods"}


def _reference(render: Callable[[], None]) -> Callable[[], None]:
    def view() -> None:
        workspace.reference_notice()
        outcome = st.session_state.get("_sb_reference_outcome")
        if outcome is None or outcome.service is None:
            st.subheader("Reference study unavailable")
            if outcome is not None and outcome.status == "failed":
                st.error(outcome.message)
            else:
                st.info(
                    "The earlier accepted-study bundle is unavailable. Current forecasting "
                    "and portfolio summaries remain independently accessible."
                )
            return
        render()

    return view


def _pages() -> dict[str, st.Page]:
    return {
        "overview": st.Page(workspace.render, title="Overview", url_path="overview", default=True),
        "forecast": st.Page(forecasting.render, title="Forecasting", url_path="forecasting"),
        "book": st.Page(portfolio.render, title="Portfolio", url_path="book"),
        "scanner": st.Page(_reference(scanner.render), title="Event explorer", url_path="scanner"),
        "pair": st.Page(_reference(pair_detail.render), title="Pair detail", url_path="pair"),
        "model": st.Page(
            _reference(model_lab.render), title="Accepted model study", url_path="models"
        ),
        "strategy": st.Page(
            _reference(strategy_lab.render), title="Plan-ladder benchmark", url_path="strategy"
        ),
        "monitor": st.Page(
            _reference(monitor.render), title="Reference data health", url_path="data-health"
        ),
        "evidence": st.Page(
            workspace.evidence, title="Evidence and diagnostics", url_path="evidence"
        ),
        "method": st.Page(workspace.methods, title="Methods", url_path="methodology"),
        "reference_method": st.Page(
            _reference(methodology.render), title="Reference protocol", url_path="reference-methods"
        ),
    }


def run(load: Callable[[], data.LoadOutcome] | None = None) -> None:
    st.set_page_config(page_title=TITLE, page_icon=":material/analytics:", layout="wide")
    st.markdown(theme.CSS, unsafe_allow_html=True)
    pages = _pages()
    st.session_state["_sb_pages"] = pages
    with st.sidebar:
        st.markdown('<div class="sb-brand">Structural Break</div>', unsafe_allow_html=True)
        st.caption("Mean-reversion research")
    navigation = st.navigation(
        {
            "Research": [pages["overview"], pages["forecast"], pages["book"]],
            "Investigate · reference study": [pages["scanner"], pages["pair"]],
            "Evidence": [pages["evidence"], pages["method"]],
            "Reference study": [
                pages["model"],
                pages["strategy"],
                pages["monitor"],
                pages["reference_method"],
            ],
        },
        position="hidden",
    )
    with st.sidebar:
        for heading, keys in (
            ("Research", ("overview", "forecast", "book")),
            ("Investigate · reference study", ("scanner", "pair")),
            ("Evidence", ("evidence", "method")),
        ):
            st.markdown(f"**{heading}**")
            for key in keys:
                st.page_link(pages[key], label=pages[key].title)
        with st.expander("Earlier accepted study"):
            for key in ("model", "strategy", "monitor", "reference_method"):
                st.page_link(pages[key], label=pages[key].title)
    if navigation.url_path in REFERENCE_PATHS or load is not None:
        with st.spinner("Checking the reference-study bundle…"):
            outcome = load() if load is not None else data.load(data.resolve_source())
        st.session_state["_sb_reference_outcome"] = outcome
        if outcome.service is not None:
            service = outcome.service
            with st.sidebar:
                horizons = service.horizons()
                primary = service.identity.primary_horizon
                horizon = st.selectbox(
                    "Reference-study horizon",
                    horizons,
                    index=horizons.index(primary) if primary in horizons else 0,
                    format_func=lambda h: f"{h} sessions" + (" · primary" if h == primary else ""),
                    help="Applies only to the earlier accepted study, not the current book.",
                )
                if service.identity.synthetic:
                    st.error("Synthetic reference preview")
            st.session_state[KEY] = AppContext(service=service, horizon=int(horizon), pages=pages)
        else:
            st.session_state.pop(KEY, None)
    with st.sidebar:
        st.markdown(
            '<p class="sb-lock">Final test 2024–2025 locked in this snapshot</p>',
            unsafe_allow_html=True,
        )
        st.caption("Browsing reads saved outputs. No downloads, fitting, model calls or trades.")
    st.markdown(
        '<div class="sb-status"><span>Structural Break · research workspace</span>'
        "<span>Development through 2023</span>"
        "<span>Final test 2024–2025 · locked snapshot</span></div>",
        unsafe_allow_html=True,
    )
    try:
        navigation.run()
    except Exception:  # noqa: BLE001 - fail closed, log diagnostics without exposing them
        LOGGER.exception("Research presentation failed")
        st.error(
            "This view could not be drawn from the saved outputs. Try another research "
            "view; ask the project owner to verify the presentation export."
        )
    workspace.footer()

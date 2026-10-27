"""Application shell: load verified data, global controls and page navigation."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from structural_break.app_ui import data, theme
from structural_break.app_ui.context import KEY, AppContext
from structural_break.app_ui.pages import (
    adopted_book,
    methodology,
    model_lab,
    monitor,
    overview,
    pair_detail,
    scanner,
    strategy_lab,
)
from structural_break.services.research_application import ResearchApplicationService

TITLE = "Structural-break detector"


def _pages() -> dict[str, st.Page]:
    return {
        "overview": st.Page(
            overview.render,
            title="Overview",
            icon=":material/insights:",
            url_path="overview",
            default=True,
        ),
        "scanner": st.Page(
            scanner.render, title="Scanner", icon=":material/radar:", url_path="scanner"
        ),
        "pair": st.Page(
            pair_detail.render,
            title="Pair detail",
            icon=":material/stacked_line_chart:",
            url_path="pair",
        ),
        "model": st.Page(
            model_lab.render, title="Model Lab", icon=":material/science:", url_path="models"
        ),
        "strategy": st.Page(
            strategy_lab.render,
            title="Strategy Lab",
            icon=":material/candlestick_chart:",
            url_path="strategy",
        ),
        "book": st.Page(
            adopted_book.render,
            title="Adopted book",
            icon=":material/trending_up:",
            url_path="book",
        ),
        "monitor": st.Page(
            monitor.render,
            title="Data and model monitor",
            icon=":material/monitor_heart:",
            url_path="monitor",
        ),
        "method": st.Page(
            methodology.render,
            title="Methodology",
            icon=":material/menu_book:",
            url_path="methodology",
        ),
    }


def run(load: Callable[[], data.LoadOutcome] | None = None) -> None:
    st.set_page_config(page_title=TITLE, page_icon=":material/insights:", layout="wide")
    st.markdown(theme.CSS, unsafe_allow_html=True)
    with st.spinner("Verifying the published research outputs…"):
        outcome = load() if load is not None else data.load(data.resolve_source())
    if outcome.status != "ready" or outcome.service is None:
        st.title(TITLE)
        if outcome.status == "pending":
            st.info(outcome.message, icon=":material/hourglass_empty:")
        else:
            st.error(outcome.message, icon=":material/gpp_bad:")
        st.caption("Final-test outcomes (2024–2025) remain locked.")
        return
    service: ResearchApplicationService = outcome.service
    pages = _pages()
    with st.sidebar:
        st.markdown(f"### {TITLE}")
        if service.identity.synthetic:
            st.error("Synthetic preview data", icon=":material/warning:")
        horizons = service.horizons()
        primary = service.identity.primary_horizon
        horizon = st.selectbox(
            "Forecast horizon",
            horizons,
            index=horizons.index(primary) if primary in horizons else 0,
            format_func=lambda h: (
                f"{h} sessions" + (" (primary)" if h == primary else " (sensitivity)")
            ),
            help="The 20-session horizon was declared primary in advance; 10 and 30 are "
            "sensitivities.",
        )
        st.markdown('<p class="sb-lock">Final test 2024–2025 locked</p>', unsafe_allow_html=True)
        st.caption(
            f"Development data {str(service.protocol['fit_start'])[:4]}–"
            f"{str(service.protocol['development_end'])[:4]}. Read-only: nothing on these pages "
            "downloads, trains or trades."
        )
    st.session_state[KEY] = AppContext(service=service, horizon=int(horizon), pages=pages)
    navigation = st.navigation(
        {
            "Explore": [pages["overview"], pages["scanner"], pages["pair"]],
            "Evaluate": [pages["model"], pages["strategy"], pages["book"]],
            "Trust": [pages["monitor"], pages["method"]],
        }
    )
    try:
        navigation.run()
    except Exception:  # noqa: BLE001 - a page fails closed, without showing internals
        st.error(
            "This view could not be drawn from the published outputs. Other pages are "
            "unaffected; re-verify the bundle with `structural-break-app verify`.",
            icon=":material/error:",
        )

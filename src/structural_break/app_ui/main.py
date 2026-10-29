"""Application shell: load verified data, global controls and page navigation."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from structural_break.app_ui import data, results, theme
from structural_break.app_ui import navigation as links
from structural_break.app_ui.context import KEY, AppContext
from structural_break.app_ui.pages import (
    adopted_book,
    event_investigation,
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
        "event": st.Page(
            event_investigation.render,
            title="Event investigation",
            icon=":material/search_insights:",
            url_path="event",
            visibility="hidden",
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
        return
    service: ResearchApplicationService = outcome.service
    pages = _pages()
    found = results.load()
    # Every headline model, the book and the final test use the 20-session target; the
    # research layer's 10 and 30 sessions were sensitivities of the frozen A/B study only.
    primary = service.identity.primary_horizon
    horizon = primary if primary in service.horizons() else service.horizons()[0]
    with st.sidebar:
        st.markdown(f"### {TITLE}")
        if service.identity.synthetic:
            st.error("Synthetic preview data", icon=":material/warning:")
        st.caption(
            f"Target: a divergence reverts to |z| ≤ {service.protocol['success_z']:g} within "
            f"{horizon} sessions, before |z| ≥ {service.protocol['adverse_z']:g}."
        )
        if found is not None and found.final_included:
            status = '<p class="sb-final">Final test 2024–2025 included</p>'
        else:
            status = '<p class="sb-lock">Final test 2024–2025: unlocked, results pending</p>'
        st.markdown(status, unsafe_allow_html=True)
        first, last = found.manifest["event_years"] if found is not None else (2010, 2023)
        st.caption(
            f"Scored events {first}–{last}. Read-only: nothing on these pages downloads, "
            "trains or trades."
        )
    st.session_state[KEY] = AppContext(
        service=service, horizon=int(horizon), pages=pages, results=found
    )
    links.restore()
    navigation = st.navigation(
        {
            "Explore": [pages["overview"], pages["scanner"], pages["event"], pages["pair"]],
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

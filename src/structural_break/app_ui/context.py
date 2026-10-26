"""Per-session page context set by the app shell before a page runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from structural_break.services.research_application import ResearchApplicationService

KEY = "_sb_context"


@dataclass
class AppContext:
    service: ResearchApplicationService
    horizon: int
    pages: dict[str, Any]


def current() -> AppContext:
    context: AppContext = st.session_state[KEY]
    return context


def open_pair(pair_id: str, event_id: str | None = None) -> None:
    st.session_state["sb_pair"] = pair_id
    st.session_state["sb_event"] = event_id
    st.switch_page(current().pages["pair"])

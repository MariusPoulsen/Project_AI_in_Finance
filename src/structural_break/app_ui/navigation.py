"""Validated URL-backed controls; links contain filters, never credentials/data."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import cast

import streamlit as st


def _set(name: str, values: list[str]) -> None:
    if values:
        st.query_params[name] = values
    elif name in st.query_params:
        del st.query_params[name]


def selectbox(
    label: str,
    options: Sequence[str],
    name: str,
    *,
    default: str,
    format_func: Callable[[str], str] = str,
) -> str:
    choices = list(options)
    wanted = st.query_params.get(name, default)
    wanted = wanted if wanted in choices else default
    key = f"url_{name}"
    if st.session_state.get(f"seen_{name}") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value: str = st.selectbox(label, choices, key=key, format_func=format_func)
    _set(name, [value])
    st.session_state[f"seen_{name}"] = value
    return value


def multiselect(
    label: str, options: Sequence[str], name: str, *, format_func: Callable[[str], str] = str
) -> list[str]:
    wanted = [v for v in st.query_params.get_all(name) if v in options]
    key = f"url_{name}"
    if st.session_state.get(f"seen_{name}") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value: list[str] = st.multiselect(label, list(options), key=key, format_func=format_func)
    _set(name, value)
    st.session_state[f"seen_{name}"] = value
    return value


def text_input(label: str, name: str, *, placeholder: str = "") -> str:
    wanted = str(st.query_params.get(name, ""))[:100]
    key = f"url_{name}"
    if st.session_state.get(f"seen_{name}") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value: str = st.text_input(label, placeholder=placeholder, key=key)
    _set(name, [value] if value else [])
    st.session_state[f"seen_{name}"] = value
    return value


def toggle(label: str, name: str, *, help: str) -> bool:
    wanted = st.query_params.get(name, "0") == "1"
    key = f"url_{name}"
    if st.session_state.get(f"seen_{name}") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value: bool = st.toggle(label, key=key, help=help)
    _set(name, ["1"] if value else [])
    st.session_state[f"seen_{name}"] = value
    return value


def year_range(first: int, last: int) -> tuple[int, int]:
    wanted = (max(first, last - 1), last)
    try:
        a, b = str(st.query_params.get("scan_years", "")).split(":")
        if first <= int(a) <= int(b) <= last:
            wanted = (int(a), int(b))
    except ValueError:
        pass
    key = "url_scan_years"
    if st.session_state.get("seen_scan_years") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value = cast(tuple[int, int], st.slider("Event years", first, last, key=key))
    result = (int(value[0]), int(value[1]))
    _set("scan_years", [f"{result[0]}:{result[1]}"])
    st.session_state["seen_scan_years"] = result
    return result


def probability() -> float:
    try:
        wanted = max(0.0, min(1.0, float(st.query_params.get("scan_min", "0"))))
        if not (0 <= wanted <= 1):
            wanted = 0.0
    except ValueError:
        wanted = 0.0
    key = "url_scan_min"
    if st.session_state.get("seen_scan_min") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value: float = st.slider("Minimum probability", 0.0, 1.0, step=0.01, key=key)
    _set("scan_min", [f"{value:.2f}"])
    st.session_state["seen_scan_min"] = value
    return value


def switch(page: str, **params: str) -> None:
    from structural_break.app_ui.context import current

    query = {name: st.query_params.get_all(name) for name in st.query_params}
    query.update({name: [value] for name, value in params.items()})
    st.session_state["_pending_query"] = query
    st.switch_page(current().pages[page])


def restore() -> None:
    pending = st.session_state.pop("_pending_query", None)
    if pending is not None:
        st.query_params.from_dict(pending)


def share(path: str, *, label: str = "Share this view") -> None:
    del path
    with st.popover(label, icon=None if label == "Share" else ":material/link:"):
        st.write(
            "Copy the browser address to share this page and its filters. "
            "A teammate with the same published data will see the same selection."
        )
        st.caption(
            "Links preserve the investigation and filters, not a particular export. "
            "Data versions are shown on each page."
        )


def trade_years(options: list[int]) -> tuple[int, int]:
    wanted = (options[0], options[-1])
    try:
        a, b = str(st.query_params.get("trade_years", "")).split(":")
        if int(a) in options and int(b) in options and int(a) <= int(b):
            wanted = (int(a), int(b))
    except ValueError:
        pass
    key = "url_trade_years"
    if key in st.session_state and st.session_state.get("seen_trade_years") != wanted:
        st.session_state[key] = wanted
    value = cast(
        tuple[int, int], st.select_slider("Entry years", options=options, value=wanted, key=key)
    )
    _set("trade_years", [f"{value[0]}:{value[1]}"])
    st.session_state["seen_trade_years"] = value
    return value


def period(options: list[str], default: str, format_func: Callable[[str], str]) -> str:
    wanted = st.query_params.get("model_period", default)
    wanted = wanted if wanted in options else default
    key = "url_model_period"
    if st.session_state.get("seen_model_period") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    value: str = (
        st.segmented_control("Test years", options, key=key, format_func=format_func) or default
    )
    _set("model_period", [value])
    st.session_state["seen_model_period"] = value
    return value


def date_window(first: date, last: date, default: tuple[date, date]) -> tuple[date, date]:
    wanted = default
    try:
        start, end = str(st.query_params.get("pair_window", "")).split(":")
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if first <= a <= b <= last:
            wanted = (a, b)
    except ValueError:
        pass
    key = "url_pair_window"
    if st.session_state.get("seen_pair_window") != wanted or key not in st.session_state:
        st.session_state[key] = wanted
    selected = cast(
        tuple[date, date],
        st.slider("Window", min_value=first, max_value=last, format="MMM YYYY", key=key),
    )
    value = (selected[0], selected[1])
    _set("pair_window", [f"{value[0].isoformat()}:{value[1].isoformat()}"])
    st.session_state["seen_pair_window"] = value
    return value

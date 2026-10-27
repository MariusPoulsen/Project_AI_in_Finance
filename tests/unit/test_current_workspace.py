"""The two research goals work without the earlier accepted bundle or live computation."""

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = [
    pytest.mark.allow_hosts(["127.0.0.1", "::1"]),
    pytest.mark.usefixtures("preserve_main_module"),
]


def page(name):
    import importlib

    import streamlit as st

    from structural_break.app_ui import theme

    st.markdown(theme.CSS, unsafe_allow_html=True)
    module, function = name.split(":")
    getattr(importlib.import_module(f"structural_break.app_ui.pages.{module}"), function)()


@pytest.mark.parametrize(
    "name",
    [
        "workspace:render",
        "forecasting:render",
        "portfolio:render",
        "workspace:evidence",
        "workspace:methods",
    ],
)
def test_current_pages_use_saved_outputs_without_reference_bundle(name, monkeypatch):
    from structural_break.app_ui import data

    monkeypatch.setattr(data, "registry", lambda: data.LoadOutcome("pending"))
    app = AppTest.from_function(page, args=(name,), default_timeout=45).run()
    assert not app.exception and not app.error
    assert app.title


def test_forecast_model_selection_and_period_keep_roles_and_denominator():
    app = AppTest.from_function(page, args=("forecasting:render",), default_timeout=45).run()
    assert app.selectbox[1].value == "B_rule_ou"
    app.selectbox[1].set_value("B_rule_ou_track").run()
    assert "B_rule_ou_track" == app.selectbox[1].value
    app.selectbox[0].select_index(1).run()
    assert any("11,048 matched" in caption.value for caption in app.caption)
    assert app.selectbox[1].value == "B_rule_ou_track"
    assert any(
        "Events" in item.value and item.value["Events"].tolist() == [11048] * 4
        for item in app.dataframe
    )
    assert not app.error and not app.exception


def test_book_period_updates_both_statistics_and_export_scope():
    app = AppTest.from_function(page, args=("portfolio:render",), default_timeout=45).run()
    assert app.dataframe[0].value["Sharpe (excess cash)"].tolist() == [
        "0.595",
        "0.439",
        "0.406",
        "0.250",
    ]
    assert app.dataframe[0].value["CAGR with cash"].tolist() == [
        "4.10%",
        "3.63%",
        "Not exported",
        "Not exported",
    ]
    app.selectbox[0].select_index(1).run()
    assert app.dataframe[0].value["Sharpe (excess cash)"].tolist() == [
        "0.813",
        "0.799",
        "0.344",
        "0.381",
    ]
    assert app.dataframe[0].value["CAGR with cash"].tolist() == [
        "3.01%",
        "2.95%",
        "Not exported",
        "Not exported",
    ]
    assert not app.error and not app.exception


def test_missing_current_snapshot_is_explicit_without_old_score_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SB_RESEARCH_SUMMARY", str(tmp_path))
    app = AppTest.from_function(page, args=("forecasting:render",), default_timeout=45).run()
    assert not app.exception and not app.metric and not app.dataframe
    assert any("not available" in message.value for message in app.info)

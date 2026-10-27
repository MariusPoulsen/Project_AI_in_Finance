"""Every page of the full research app renders from a bundle without computation.

Uses the clearly labelled synthetic preview (invented data) so the smoke tests
need no snapshot, network or language model.
"""

import pytest
from streamlit.testing.v1 import AppTest

from structural_break.app_bundle.synthetic import synthetic_bundle
from structural_break.app_ui.data import LoadOutcome
from structural_break.services.research_application import ResearchApplicationService

pytestmark = [
    pytest.mark.allow_hosts(["127.0.0.1", "::1"]),
    pytest.mark.usefixtures("preserve_main_module"),
]
PAGES = ("scanner", "pair_detail")


@pytest.fixture(scope="module")
def service():
    return ResearchApplicationService(synthetic_bundle(pairs=6, small=True, seed=3))


def shell(service):
    from structural_break.app_ui.data import LoadOutcome
    from structural_break.app_ui.main import run

    run(lambda: LoadOutcome("ready", service))


def page(service, name, horizon):
    import importlib

    import streamlit as st

    from structural_break.app_ui.context import KEY, AppContext
    from structural_break.app_ui.main import _pages

    pages = _pages()
    st.navigation(list(pages.values()), position="hidden")
    st.session_state[KEY] = AppContext(service=service, horizon=horizon, pages=pages)
    importlib.import_module(f"structural_break.app_ui.pages.{name}").render()


def outcome_shell(outcome):
    from structural_break.app_ui.main import run

    run(lambda: outcome)


def test_shell_opens_on_current_goals_and_scopes_reference_controls(service):
    app = AppTest.from_function(shell, args=(service,), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "Research comparisons"
    assert not app.sidebar.selectbox
    assert app.dataframe[0].value["ROC AUC"].tolist() == [
        "Policy",
        "Policy",
        "0.711",
        "0.718",
        "0.735",
        "0.739",
        "Regional",
    ]
    assert len(app.dataframe[1].value) == 4
    assert any("Final test 2024–2025 locked" in item.value for item in app.sidebar.markdown)


@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("horizon", [20])
def test_every_page_renders_without_errors(service, name, horizon):
    app = AppTest.from_function(page, args=(service, name, horizon), default_timeout=60).run()
    assert not app.exception, app.exception
    assert not app.error
    assert app.title
    assert any("Synthetic preview" in item.value for item in app.markdown)


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("pending", "No accepted research generation"),
        ("failed", "failed verification"),
    ],
)
def test_pending_and_failed_reference_does_not_hide_independent_current_summary(status, text):
    outcome = LoadOutcome(status, message=f"{text} — fixture message")
    app = AppTest.from_function(outcome_shell, args=(outcome,), default_timeout=30).run()
    assert not app.exception
    assert not app.error
    assert app.dataframe[0].value["ROC AUC"].tolist() == [
        "Policy",
        "Policy",
        "0.711",
        "0.718",
        "0.735",
        "0.739",
        "Regional",
    ]
    assert app.title[0].value == "Research comparisons"


def test_scanner_filters_to_an_empty_state_without_inventing_rows(service):
    app = AppTest.from_function(page, args=(service, "scanner", 20), default_timeout=60).run()
    app.text_input[0].set_value("DOES_NOT_EXIST").run()
    assert not app.exception
    assert any("No events match" in item.value for item in app.info)


def test_adopted_book_page_renders_the_committed_summary(service):
    app = AppTest.from_function(page, args=(service, "adopted_book", 20), default_timeout=60).run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Compare portfolio returns"
    assert app.dataframe[0].value["Sharpe (excess cash)"].tolist() == [
        "0.595",
        "0.439",
        "0.406",
        "0.250",
    ]


def test_registry_projection_cannot_leak_superseded_probabilities(service):
    from structural_break.services.workspace_diagnostics import registry_events

    rows = registry_events(service)
    assert not any(
        "logistic" in column or "xgboost" in column or column in {"p_A", "p_B"} for column in rows
    )
    assert rows.date.dt.year.max() <= 2023
    assert set(rows.outcome) <= {"Reverted", "Did not revert", "Unknown"}


def registry_page(service, view):
    import importlib

    import streamlit as st

    from structural_break.app_ui.data import LoadOutcome

    st.session_state["_sb_registry_outcome"] = LoadOutcome("ready", service)
    module, function = view.split(":")
    getattr(importlib.import_module(f"structural_break.app_ui.pages.{module}"), function)()


@pytest.mark.parametrize("view", ["forecasting:render", "portfolio:render", "workspace:evidence"])
def test_integrated_registry_diagnostics_render_without_old_model_pages(service, view):
    app = AppTest.from_function(registry_page, args=(service, view), default_timeout=60).run()
    assert not app.exception and not app.error
    assert app.title

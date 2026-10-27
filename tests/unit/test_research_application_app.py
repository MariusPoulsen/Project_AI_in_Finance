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
PAGES = (
    "overview",
    "scanner",
    "pair_detail",
    "model_lab",
    "strategy_lab",
    "monitor",
    "methodology",
)


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
    assert app.title[0].value == "Better forecasts. A different book choice."
    assert app.sidebar.selectbox[0].value == 20
    labels = [metric.label for metric in app.metric]
    assert "R0 · ROC AUC" in labels and "With monitor · Sharpe" in labels
    assert any("Synthetic reference preview" in item.value for item in app.sidebar.error)
    assert any("Final test 2024–2025 locked" in item.value for item in app.sidebar.markdown)


@pytest.mark.parametrize("name", PAGES)
@pytest.mark.parametrize("horizon", [20, 10])
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
    assert app.metric[0].value == "0.718"
    assert app.title[0].value == "Better forecasts. A different book choice."


def test_scanner_filters_to_an_empty_state_without_inventing_rows(service):
    app = AppTest.from_function(page, args=(service, "scanner", 20), default_timeout=60).run()
    app.slider[0].set_value(1.0).run()
    assert not app.exception
    assert any("No events match" in item.value for item in app.info)


def test_adopted_book_page_renders_the_committed_summary(service):
    app = AppTest.from_function(page, args=(service, "adopted_book", 20), default_timeout=60).run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Compare portfolio returns"
    labels = [metric.label for metric in app.metric]
    assert "Sharpe · excess cash" in labels and "Max drawdown · excess cash" in labels
    assert app.metric[0].value == "0.595"

"""Every page of the full research app renders from a bundle without computation.

Uses the clearly labelled synthetic preview (invented data) so the smoke tests
need no snapshot, network or language model.
"""

import re

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


def page(service, name, horizon, with_results=False):
    import importlib

    import streamlit as st

    from structural_break.app_ui import results
    from structural_break.app_ui.context import KEY, AppContext
    from structural_break.app_ui.main import _pages

    pages = _pages()
    st.navigation(list(pages.values()), position="hidden")
    st.session_state[KEY] = AppContext(
        service=service,
        horizon=horizon,
        pages=pages,
        results=results.load() if with_results else None,
    )
    importlib.import_module(f"structural_break.app_ui.pages.{name}").render()


def outcome_shell(outcome):
    from structural_break.app_ui.main import run

    run(lambda: outcome)


def test_shell_opens_on_the_overview_with_the_synthetic_warning(service):
    app = AppTest.from_function(shell, args=(service,), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "Structural-break detector"
    assert not app.sidebar.selectbox  # every headline model uses the 20-session target
    assert any("within 20 sessions" in item.value for item in app.sidebar.caption)
    labels = [metric.label for metric in app.metric]
    assert "Business-peer pairs" in labels
    assert any("Synthetic preview" in item.value for item in app.markdown)
    assert any("Final test 2024–2025" in item.value for item in app.sidebar.markdown)


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
def test_pending_and_failed_data_never_show_results(status, text):
    outcome = LoadOutcome(status, message=f"{text} — fixture message")
    app = AppTest.from_function(outcome_shell, args=(outcome,), default_timeout=30).run()
    assert not app.exception
    shown = [item.value for item in (app.info if status == "pending" else app.error)]
    assert len(shown) == 1 and text in shown[0]
    assert not app.metric and not app.dataframe


def test_scanner_filters_to_an_empty_state_without_inventing_rows(service):
    app = AppTest.from_function(page, args=(service, "scanner", 20), default_timeout=60).run()
    app.slider[0].set_value(1.0).run()
    assert not app.exception
    assert any("No events match" in item.value for item in app.info)


RESULT_PAGES = (*PAGES, "adopted_book")


@pytest.mark.parametrize("name", RESULT_PAGES)
def test_every_page_renders_with_the_committed_results(service, name):
    app = AppTest.from_function(page, args=(service, name, 20, True), default_timeout=90).run()
    assert not app.exception, app.exception
    assert not app.error
    assert app.title
    for item in [*app.markdown, *app.caption, *app.table, *app.dataframe]:
        value = item.value
        text = value.to_csv(index=False) if hasattr(value, "to_csv") else str(value)
        assert not re.search(r"\bDecisions?\s+\d|DECISIONS\.md|decision log", text)
        if hasattr(value, "columns"):
            assert "Decision" not in value.columns


def test_adopted_book_page_renders_the_committed_results(service):
    app = AppTest.from_function(
        page, args=(service, "adopted_book", 20, True), default_timeout=90
    ).run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Adopted book"
    labels = [metric.label for metric in app.metric]
    assert "Sharpe, 2010–2017" in labels and "Sharpe, 2018–2023" in labels
    assert any(label.startswith("Max drawdown, 2010–") for label in labels)
    assert len(app.dataframe) >= 1 and len(app.table) >= 1


def test_results_pages_explain_when_no_results_are_deployed(service):
    app = AppTest.from_function(page, args=(service, "adopted_book", 20), default_timeout=60).run()
    assert not app.exception
    assert any("export_results.py" in item.value for item in app.info)


def test_results_fail_closed_when_a_file_does_not_match_the_manifest(tmp_path):
    import shutil

    from structural_break.app_ui import results

    copy = tmp_path / "results"
    shutil.copytree(results.FOLDER, copy)
    assert results.load(copy) is not None
    (copy / "summary.json").write_text("{}", encoding="utf-8")
    assert results.load(copy) is None


def test_monitor_uses_current_periods_and_omits_catalyst_fields(service, monkeypatch):
    monkeypatch.setattr(
        service, "cohorts", lambda *_: pytest.fail("Used frozen fitting partitions")
    )
    app = AppTest.from_function(page, args=(service, "monitor", 20, True), default_timeout=90).run()
    assert not app.exception and not app.error
    samples = next(item.value for item in app.dataframe if "Labelled" in item.value)
    versions = next(item.value for item in app.dataframe if "Item" in item.value)
    assert not versions.Item.str.startswith("Frozen").any()
    assert "Input registry protocol" not in set(versions.Item)
    assert samples["Labelled"].iloc[:2].tolist() == [11048, 10940]
    assert samples["Period"].tolist() == [
        "Selection · 2010–2017",
        "Holdout · 2018–2023",
        "Final test · 2024–2025",
    ]
    coverage = next(item.value for item in app.dataframe if "Indicator" in item.value)
    assert coverage.columns.tolist() == [
        "Indicator",
        "Fit · 2010–2017 (n=11236)",
        "Calibration · 2018–2023 (n=11214)",
    ]
    assert not coverage.Indicator.str.contains("catalyst", case=False).any()
    assert not any(
        "catalyst" in str(option).lower() or "affected_leg" in str(option)
        for option in app.selectbox[0].options
    )


def test_model_lab_exposes_current_shap_pending_instead_of_legacy_attributions(
    service, monkeypatch
):
    from dataclasses import replace

    from structural_break.app_ui import results

    saved = results.load()
    assert saved is not None
    pending = replace(
        saved,
        tables={k: v for k, v in saved.tables.items() if not k.startswith(("shap_", "full_shap_"))},
    )
    monkeypatch.setattr(results, "load", lambda: pending)
    app = AppTest.from_function(
        page, args=(service, "model_lab", 20, True), default_timeout=90
    ).run()
    assert not app.exception and not app.error
    assert "SHAP" in [tab.label for tab in app.tabs]
    assert any("explanations have not been exported" in item.value for item in app.info)


def test_event_investigation_opens_a_saved_full_forecast_and_rejects_unknown_id(service):
    from structural_break.app_ui import results

    saved = results.load()
    assert saved is not None
    event_id = str(saved.tables["full_shap_events"].event_id.iloc[0])
    app = AppTest.from_function(
        page, args=(service, "event_investigation", 20, True), default_timeout=90
    )
    app.query_params["event"] = event_id
    app.run()
    assert not app.exception and not app.error
    assert "Forecast and SHAP" in [tab.label for tab in app.tabs]
    assert any("Probability-only stack" in item.value for item in app.markdown)
    assert any("Exact linear SHAP" in item.value for item in app.caption)
    app.query_params["event"] = "not-published"
    app.run()
    assert not app.exception and not app.error
    assert any("not in the published results" in item.value for item in app.warning)


def test_model_lab_comparison_includes_matched_entry_baselines(service):
    app = AppTest.from_function(
        page, args=(service, "model_lab", 20, True), default_timeout=90
    ).run()
    assert not app.exception and not app.error
    table = next(item.value for item in app.dataframe if "roc_auc" in item.value)
    baseline = table.loc[table.label.str.startswith("Baseline")]
    assert len(table) == 6 and len(baseline) == 2
    assert baseline.n.tolist() == [10940, 10940]
    assert baseline.iloc[0].roc_auc == 0.5
    assert baseline[["log_loss", "brier"]].isna().all().all()

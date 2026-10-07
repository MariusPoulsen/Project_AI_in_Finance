"""Primary app browsing exposes verified v2 DTOs without starting computation."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from structural_break.research.primary import PrimaryNotReadyError
from structural_break.services.research_app import PrimaryResearchView

# Streamlit AppTest needs a Windows asyncio loopback wake-up socket only.
pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])


class FrozenV2Service:
    """Small deterministic presentation fixture, never an accepted research publication."""

    def __init__(self, *, unready=False, broken=False, missing=False, empty=False):
        self.unready, self.broken, self.missing, self.empty = unready, broken, missing, empty
        self.calls = []

    def versions(self):
        self.calls.append(("versions",))
        return () if self.unready else ("fixture-primary-old", "fixture-primary-active")

    def view(self, version=None):
        self.calls.append(("view", version))
        if self.unready:
            raise PrimaryNotReadyError("No accepted publication")
        if self.broken:
            raise ValueError("Do not expose technical exception details")
        if self.missing:
            raise FileNotFoundError("Registered proof is missing")
        protocol = {
            "fit_start": "2006-01-01",
            "fit_end": "2019-12-31",
            "calibration_start": "2020-01-01",
            "calibration_end": "2021-12-31",
            "assessment_start": "2022-01-01",
            "assessment_end": "2023-12-31",
            "development_end": "2023-12-31",
            "primary_horizon": 20,
            "sensitivity_horizons": [10, 30],
            "primary_family": "logistic",
            "primary_b_variant": "both",
        }
        report = {
            "models": {
                "logistic": {
                    "B_both": {
                        "paired_assessment": {
                            "brier_delta_B_minus_A": 0.05,
                            "observed_quarter_blocks": 8,
                            "quarter_block_percentile_interval_95": [-0.01, 0.11],
                        },
                        "calibrated_assessment_slices": {
                            "ACTIVE": {"True": {"n": 3, "positives": 1}},
                            "business_group": {"Empty frozen group": {"n": 0}},
                        },
                    }
                }
            },
            "cohorts": {"assessment": {"n": 5, "positives": 2, "ACTIVE": 3}},
            "text_coverage": {"assessment": {"n": 5, "flags": {"event_type_UNKNOWN": {"ones": 4}}}},
        }
        return PrimaryResearchView(
            version or "fixture-primary-active",
            "fixture-registry",
            "fixture-intelligence",
            protocol,
            {horizon: f"fixture-evaluation-{horizon}" for horizon in (20, 10, 30)},
            {horizon: report for horizon in (20, 10, 30)},
        )

    def comparison(self, view, horizon, *, active_only=False):
        self.calls.append(("comparison", view.primary_version, horizon, active_only))
        return pd.DataFrame(
            [
                {
                    "family": "logistic",
                    "variant": variant,
                    "n": 3 if active_only else 5,
                    "positives": 1 if active_only else 2,
                    "brier": loss,
                    "log_loss": 0.7,
                    "brier_delta_B_minus_A": None if variant == "A" else 0.05,
                }
                for variant, loss in (("A", 0.2), ("B_both", 0.25))
            ]
        )

    def predictions(self, view, horizon, *, as_of, active_only=False):
        self.calls.append(("predictions", view.primary_version, horizon, as_of, active_only))
        if self.empty:
            return pd.DataFrame()
        rows = pd.DataFrame(
            [
                {
                    "event_id": f"fixture-{pair}",
                    "event_date": date(2023, 12, 15),
                    "pair_id": pair,
                    "ACTIVE_at_event": active,
                    "research_partition": "assessment",
                    "model_a_calibrated": 0.6,
                    "model_b_calibrated": 0.5,
                }
                for pair, active in (("KO__PEP", True), ("BAC__JPM", False))
            ]
        )
        return rows.loc[rows["ACTIVE_at_event"]] if active_only else rows


def app_script(service):
    from app.streamlit_app import main

    main(service)


def run_app(service):
    return AppTest.from_function(app_script, args=(service,), default_timeout=20).run()


def test_default_v2_shows_fixed_primary_and_unfavorable_results_honestly():
    service = FrozenV2Service()
    app = run_app(service)
    assert not app.exception and not app.error
    assert app.title[0].value == "Structural-Break Research v2"
    assert app.sidebar.selectbox[0].value == "fixture-primary-active"
    assert app.sidebar.selectbox[1].value == 20
    assert app.metric[0].value == "0.2000"
    assert app.metric[1].value == "0.2500"
    assert app.dataframe[0].value["n"].tolist() == [5, 5]
    assert app.dataframe[0].value["positives"].tolist() == [2, 2]
    assert any("negative B-minus-A" in caption.value for caption in app.caption)
    assert any("Final-test outcomes" in caption.value for caption in app.caption)
    assert any("Coverage flags retain UNKNOWN" in caption.value for caption in app.caption)
    assert not app.button
    assert all(call[0] in {"versions", "view", "comparison"} for call in service.calls)


def test_unready_primary_has_no_reference_fallback_or_fake_scores():
    service = FrozenV2Service(unready=True)
    app = run_app(service)
    assert not app.exception and not app.error
    assert len(app.info) == 1
    assert "all three model evaluations" in app.info[0].value
    assert not app.metric and not app.dataframe and not app.button
    assert service.calls == [("versions",), ("view", None)]


@pytest.mark.parametrize("reason", ["broken", "missing"])
def test_registered_publication_verification_failure_is_an_error(reason):
    service = FrozenV2Service(**{reason: True})
    app = run_app(service)
    assert not app.exception
    assert len(app.error) == 1 and not app.info
    assert "publication failed verification" in app.error[0].value
    assert "technical exception" not in app.error[0].value
    assert not app.metric and not app.dataframe and not app.button
    assert all(call[0] in {"versions", "view"} for call in service.calls)


def test_explicit_generation_selection_uses_registered_identity():
    service = FrozenV2Service()
    app = run_app(service)
    app.sidebar.selectbox[0].set_value("fixture-primary-old").run()
    assert not app.exception and not app.error
    assert ("view", "fixture-primary-old") in service.calls
    assert service.calls[-1] == ("comparison", "fixture-primary-old", 20, False)
    assert any("Primary: fixture-primary-old" in caption.value for caption in app.caption)


@pytest.mark.parametrize("horizon", [10, 30])
def test_sensitivity_selection_and_active_subset_keep_actual_denominators(horizon):
    service = FrozenV2Service()
    app = run_app(service)
    app.sidebar.selectbox[1].set_value(horizon).run()
    app.sidebar.checkbox[0].set_value(True).run()
    assert not app.exception and not app.error
    assert service.calls[-1] == ("comparison", "fixture-primary-active", horizon, True)
    assert app.dataframe[0].value["n"].tolist() == [3, 3]
    assert app.dataframe[0].value["positives"].tolist() == [1, 1]
    assert any("exploratory subset" in caption.value for caption in app.caption)
    assert all(header.value != "Paired assessment uncertainty" for header in app.subheader)


def test_event_browser_caps_final_period_and_filters_pairs_without_outcomes():
    service = FrozenV2Service()
    app = run_app(service)
    app.sidebar.radio[0].set_value("Event scores").run()
    assert not app.exception and not app.error
    assert app.sidebar.date_input[0].value == date(2023, 12, 31)
    assert service.calls[-1] == (
        "predictions",
        "fixture-primary-active",
        20,
        date(2023, 12, 31),
        False,
    )
    app.sidebar.selectbox[2].set_value("KO__PEP").run()
    assert app.dataframe[0].value["pair_id"].tolist() == ["KO__PEP"]
    assert "y_revert_success" not in app.dataframe[0].value
    assert any("not forecasts issued" in caption.value for caption in app.caption)
    assert any("not a trade signal" in caption.value for caption in app.caption)
    assert not app.button
    assert all(
        call[0] in {"versions", "view", "comparison", "predictions"} for call in service.calls
    )


def test_empty_event_selection_has_no_invented_prediction():
    service = FrozenV2Service(empty=True)
    app = run_app(service)
    app.sidebar.radio[0].set_value("Event scores").run()
    assert not app.exception and not app.error
    assert any("No stored event scores" in info.value for info in app.info)
    assert not app.dataframe and not app.metric and not app.button


@pytest.mark.parametrize("custom", [False, True])
def test_service_creation_resolves_workspace_without_creating_it(tmp_path, monkeypatch, custom):
    from app import streamlit_app

    workspace = tmp_path / "uncreated-v2-workspace" if custom else None
    monkeypatch.setattr(
        streamlit_app, "RuntimeSettings", lambda **kwargs: SimpleNamespace(workspace_root=workspace)
    )
    service = streamlit_app.create_service()
    expected = workspace or service.paths.project_root / "data/research_v2"
    assert service.paths.workspace_root == expected.resolve()
    if workspace is not None:
        assert not workspace.exists()

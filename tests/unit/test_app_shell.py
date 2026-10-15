"""The two-page presentation shell renders stored rows without running batch jobs."""

import socket
from datetime import date

import pandas as pd
import pytest
from pytest_socket import SocketConnectBlockedError
from streamlit.testing.v1 import AppTest

from structural_break.services.app_queries import (
    PairDetailView,
    ResearchVersions,
    ScannerView,
)

# AppTest's asyncio wake-up pipe uses a loopback socket pair on Windows.
# External hosts remain blocked; Linux uses a local socket pair.
pytestmark = [
    pytest.mark.allow_hosts(["127.0.0.1", "::1"]),
    pytest.mark.usefixtures("preserve_main_module"),
]


class FrozenService:
    def __init__(
        self, *, no_history: bool = False, broken: bool = False, model: bool = False
    ) -> None:
        self.no_history, self.broken, self.model = no_history, broken, model
        self.calls: list[str] = []

    def versions(self) -> ResearchVersions:
        self.calls.append("versions")
        if self.no_history:
            raise FileNotFoundError("not published")
        if self.broken:
            raise ValueError("checksum mismatch")
        return ResearchVersions(
            "fixture-data",
            "fixture-relationships",
            True,
            date(2016, 1, 4),
            date(2025, 12, 31),
            {"model_version": "fixture-model-a"} if self.model else None,
        )

    def scanner(self, as_of: date) -> ScannerView:
        self.calls.append("scanner")
        rows = pd.DataFrame([{"pair_id": "KO__PEP", "z_score": 2.1, "pair_status": "ACTIVE"}])
        return ScannerView(as_of, as_of, ("KO__PEP",), rows, self.versions())

    def pair_detail(self, pair_id: str, as_of: date, *, lookback_days: int = 365) -> PairDetailView:
        self.calls.append("pair_detail")
        return PairDetailView(
            pair_id,
            as_of,
            as_of,
            {"pair_status": "ACTIVE", "z_score": 2.1, "beta": 1.2},
            {"estimation_date": "2023-11-30", "effective_start": "2023-12-01"},
            pd.DataFrame(
                [
                    {"trading_date": date(2023, 12, 28), "z_score": 1.8, "spread": 0.1},
                    {"trading_date": date(2023, 12, 29), "z_score": 2.1, "spread": 0.2},
                ]
            ),
            pd.DataFrame(),
            pd.DataFrame(
                [
                    {
                        "event_id": "event-1",
                        "event_timestamp": "2023-12-28T21:00:00Z",
                        "evaluation_role": "VALIDATION_CALIBRATION_DESCRIPTIVE",
                        "calibrated_probability": 0.7,
                        "raw_probability": 0.6,
                        "ml_qualified": True,
                        "top_shap_positive": [{"feature": "abs_z", "contribution": 0.2}],
                        "top_shap_negative": [{"feature": "half_life", "contribution": -0.1}],
                    }
                ]
            )
            if self.model
            else pd.DataFrame(),
            self.versions(),
        )


def app_script(service) -> None:
    from app.reference_streamlit_app import main

    main(service)


def test_scanner_renders_frozen_rows_and_keeps_final_period_locked() -> None:
    service = FrozenService()
    app = AppTest.from_function(app_script, args=(service,), default_timeout=20).run()
    assert not app.exception
    assert not app.error
    assert app.header[0].value == "Scanner"
    assert len(app.dataframe) == 1
    assert app.sidebar.date_input[0].value == date(2023, 12, 31)
    assert all(name in {"versions", "scanner"} for name in service.calls)


def test_app_wakeup_pipe_exception_does_not_allow_external_connections() -> None:
    with socket.socket() as connection:
        with (
            pytest.warns(UserWarning, match="socket.socket.connect"),
            pytest.raises(SocketConnectBlockedError),
        ):
            connection.connect(("203.0.113.1", 443))


def test_pair_detail_renders_without_training_or_fake_predictions() -> None:
    service = FrozenService()
    app = AppTest.from_function(app_script, args=(service,), default_timeout=20).run()
    app.sidebar.radio[0].set_value("Pair Detail").run()
    assert not app.exception
    assert not app.error
    assert app.header[0].value == "KO / PEP"
    assert app.metric[0].value == "ACTIVE"
    assert any("No Model A generation" in item.value for item in app.info)
    assert "pair_detail" in service.calls
    assert all(name in {"versions", "scanner", "pair_detail"} for name in service.calls)


def test_pair_detail_renders_stored_probability_and_raw_margin_drivers() -> None:
    service = FrozenService(model=True)
    app = AppTest.from_function(app_script, args=(service,), default_timeout=20).run()
    app.sidebar.radio[0].set_value("Pair Detail").run()
    assert not app.exception
    assert not app.error
    assert any(
        item.label == "Calibrated P(revert)" and item.value == "0.700" for item in app.metric
    )
    assert any("raw model margin" in item.value for item in app.caption)
    assert not app.button


@pytest.mark.parametrize("broken", [False, True])
def test_missing_or_corrupt_published_history_has_explicit_state(broken: bool) -> None:
    service = FrozenService(no_history=not broken, broken=broken)
    app = AppTest.from_function(app_script, args=(service,), default_timeout=20).run()
    assert not app.exception
    assert len(app.error if broken else app.info) == 1
    assert not app.dataframe
    assert not app.button


def test_missing_registered_artifact_is_a_display_error() -> None:
    class MissingArtifactService(FrozenService):
        def versions(self) -> ResearchVersions:
            raise FileNotFoundError(2, "Registered artifact missing", "frozen-model.json")

    app = AppTest.from_function(
        app_script, args=(MissingArtifactService(),), default_timeout=20
    ).run()
    assert not app.exception
    assert len(app.error) == 1
    assert "registered research artifact is missing" in app.error[0].value
    assert not app.info

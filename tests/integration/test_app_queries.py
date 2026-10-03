"""Frozen app queries must remain point-in-time, versioned and read-only."""

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from structural_break.config.loader import load_config
from structural_break.config.paths import ProjectPaths
from structural_break.services.app_queries import ResearchQueryService
from structural_break.services.model_a import ModelARepository
from structural_break.services.relationships import build_relationships
from structural_break.storage.database import DuckDBConnectionFactory


@pytest.fixture(scope="module")
def app_paths(tmp_path_factory: pytest.TempPathFactory) -> ProjectPaths:
    root = Path(__file__).resolve().parents[2]
    paths = ProjectPaths.resolve(root, tmp_path_factory.mktemp("app-queries"))
    build_relationships(
        paths, load_config(root / "configs"), fixture=True, relationship_version="app-fixture"
    )
    return paths


class FakeModelReader:
    def __init__(self, manifest: dict[str, Any], predictions: pd.DataFrame) -> None:
        self.saved_manifest, self.saved_predictions = manifest, predictions

    def active_manifest(self) -> dict[str, Any]:
        return self.saved_manifest

    def predictions(
        self, pair_id: str | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        return self.saved_predictions.copy()


def test_scanner_selects_last_research_session_without_future_rows(app_paths: ProjectPaths) -> None:
    service = ResearchQueryService(app_paths)
    view = service.scanner(date(2018, 12, 30))
    assert view.requested_as_of == date(2018, 12, 30)
    assert view.session == date(2018, 12, 28)
    assert pd.to_datetime(view.rows["trading_date"]).dt.date.eq(view.session).all()
    assert view.versions.synthetic
    assert view.versions.relationship_version == "app-fixture"
    assert set(view.pair_ids) == {"KO__PEP", "HD__LOW", "WMT__TGT"}


def test_no_history_before_first_effective_fit(app_paths: ProjectPaths) -> None:
    view = ResearchQueryService(app_paths).scanner(date(2014, 1, 2))
    assert view.session is None
    assert view.rows.empty


def test_unpublished_model_keeps_quantitative_history_available(app_paths: ProjectPaths) -> None:
    view = ResearchQueryService(app_paths, ModelARepository(app_paths)).scanner(date(2018, 6, 15))
    assert not view.rows.empty
    assert view.versions.model is None


def test_missing_registered_model_artifact_is_not_an_unpublished_fallback(
    app_paths: ProjectPaths,
) -> None:
    class MissingArtifactReader(FakeModelReader):
        def active_manifest(self) -> dict[str, Any]:
            raise FileNotFoundError(2, "Registered artifact missing", "frozen-model.json")

    reader = MissingArtifactReader({}, pd.DataFrame())
    with pytest.raises(FileNotFoundError, match="Registered artifact"):
        ResearchQueryService(app_paths, reader).versions()


def test_pair_detail_uses_latest_effective_snapshot_and_bounded_history(
    app_paths: ProjectPaths,
) -> None:
    view = ResearchQueryService(app_paths).pair_detail("KO__PEP", date(2018, 6, 15))
    assert view.state is not None
    assert view.snapshot is not None
    assert view.state["relationship_snapshot_id"] == view.snapshot["relationship_snapshot_id"]
    assert pd.Timestamp(view.snapshot["effective_start"]).date() <= date(2018, 6, 15)
    assert pd.to_datetime(view.history["trading_date"]).dt.date.max() <= date(2018, 6, 15)
    assert pd.to_datetime(view.crossings["trading_date"]).dt.date.max() <= date(2018, 6, 15)
    assert view.predictions.empty


@pytest.mark.parametrize("pair", ["PEP__KO", "UNKNOWN", "KO__PEP';DROP TABLE x;--"])
def test_pair_orientation_and_unknown_pairs_are_checked(app_paths: ProjectPaths, pair: str) -> None:
    with pytest.raises(ValueError, match="Unknown fixed-orientation"):
        ResearchQueryService(app_paths).pair_detail(pair, date(2018, 6, 15))


def test_all_query_connections_are_read_only(
    app_paths: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = DuckDBConnectionFactory.connect
    modes: list[bool] = []

    def connect(self: DuckDBConnectionFactory, *, read_only: bool = True) -> Any:
        modes.append(read_only)
        return original(self, read_only=read_only)

    monkeypatch.setattr(DuckDBConnectionFactory, "connect", connect)
    ResearchQueryService(app_paths).pair_detail("KO__PEP", date(2018, 6, 15))
    assert modes and all(modes)


def test_model_relationship_lineage_mismatch_is_rejected(app_paths: ProjectPaths) -> None:
    reader = FakeModelReader({"relationship_version": "another-generation"}, pd.DataFrame())
    with pytest.raises(ValueError, match="different versions"):
        ResearchQueryService(app_paths, reader).versions()


def test_prediction_view_excludes_targets_and_outcome_metadata(app_paths: ProjectPaths) -> None:
    reader = FakeModelReader(
        {"relationship_version": "app-fixture", "model_version": "model-a-fixture"},
        pd.DataFrame(
            [
                {
                    "event_id": "event-1",
                    "pair_id": "KO__PEP",
                    "event_timestamp": "2018-06-14T20:00:00Z",
                    "calibrated_probability": 0.7,
                    "model_version": "model-a-fixture",
                    "target": 1,
                    "outcome_type": "CONVERGED",
                    "resolution_date": "2018-06-20",
                    "net_return": 0.1,
                }
            ]
        ),
    )
    view = ResearchQueryService(app_paths, reader).pair_detail("KO__PEP", date(2018, 6, 15))
    assert view.predictions.iloc[0]["calibrated_probability"] == 0.7
    assert not {"target", "outcome_type", "resolution_date", "net_return"}.intersection(
        view.predictions.columns
    )


@pytest.mark.parametrize(
    "pair,timestamp", [("HD__LOW", "2018-06-14T20:00:00Z"), ("KO__PEP", "2018-06-18T20:00:00Z")]
)
def test_prediction_information_set_is_checked(
    app_paths: ProjectPaths, pair: str, timestamp: str
) -> None:
    reader = FakeModelReader(
        {"relationship_version": "app-fixture"},
        pd.DataFrame([{"pair_id": pair, "event_timestamp": timestamp}]),
    )
    with pytest.raises(ValueError, match="information set"):
        ResearchQueryService(app_paths, reader).pair_detail("KO__PEP", date(2018, 6, 15))

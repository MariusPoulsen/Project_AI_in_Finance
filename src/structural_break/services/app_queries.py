"""Read-only presentation contracts for frozen quantitative research outputs."""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.services.model_a import UnpublishedVersionError
from structural_break.services.relationships import RelationshipsRepository
from structural_break.storage.database import DuckDBConnectionFactory


class ModelAReader(Protocol):
    """A verified, read-only view of an explicitly published model generation."""

    def active_manifest(self) -> dict[str, Any]: ...

    def predictions(
        self, pair_id: str | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class ResearchVersions:
    data_snapshot_id: str
    relationship_version: str
    synthetic: bool
    first_session: date
    last_session: date
    model: dict[str, Any] | None = None


@dataclass(frozen=True)
class ScannerView:
    requested_as_of: date
    session: date | None
    pair_ids: tuple[str, ...]
    rows: pd.DataFrame
    versions: ResearchVersions


@dataclass(frozen=True)
class PairDetailView:
    pair_id: str
    requested_as_of: date
    session: date | None
    state: dict[str, Any] | None
    snapshot: dict[str, Any] | None
    history: pd.DataFrame
    crossings: pd.DataFrame
    predictions: pd.DataFrame
    versions: ResearchVersions


def _unpack(row: dict[Any, Any], column: str) -> dict[str, Any]:
    payload = row.get(column)
    fields = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(fields, dict):
        raise ValueError("Stored quantitative payload is malformed")
    return {**fields, **{key: value for key, value in row.items() if key != column}}


class ResearchQueryService:
    """Query published rows; never estimate, label, predict, train or write."""

    def __init__(self, paths: ProjectPaths, model_reader: ModelAReader | None = None) -> None:
        self.paths = paths
        self.factory = DuckDBConnectionFactory(paths.database)
        self.relationships = RelationshipsRepository(paths)
        self.model_reader = model_reader

    def versions(self) -> ResearchVersions:
        manifest = self.relationships.manifest()
        version = manifest["relationship_version"]
        with self.factory.connect() as connection:
            bounds = connection.execute(
                """SELECT min(trading_date),max(trading_date)
                FROM analytics.pair_state_daily WHERE relationship_version=?""",
                [version],
            ).fetchone()
        if bounds is None or bounds[0] is None or bounds[1] is None:
            raise ValueError("Published relationships have no usable daily states")
        model = None
        if self.model_reader is not None:
            try:
                model = self.model_reader.active_manifest()
            except UnpublishedVersionError:
                pass
            if model is not None and model.get("relationship_version") != version:
                raise ValueError("Model and displayed relationships have different versions")
        return ResearchVersions(
            data_snapshot_id=str(manifest["data_snapshot_id"]),
            relationship_version=str(version),
            synthetic=bool(manifest["synthetic"]),
            first_session=bounds[0],
            last_session=bounds[1],
            model=model,
        )

    def _session(self, as_of: date, version: str) -> date | None:
        with self.factory.connect() as connection:
            row = connection.execute(
                """SELECT max(trading_date) FROM analytics.pair_state_daily
                WHERE relationship_version=? AND trading_date<=?""",
                [version, as_of],
            ).fetchone()
        return None if row is None else row[0]

    def scanner(self, as_of: date) -> ScannerView:
        versions = self.versions()
        version = versions.relationship_version
        session = self._session(as_of, version)
        with self.factory.connect() as connection:
            pairs = connection.execute(
                """SELECT DISTINCT pair_id FROM analytics.relationship_snapshots
                WHERE relationship_version=? ORDER BY pair_id""",
                [version],
            ).fetchall()
            rows = connection.execute(
                """SELECT pair_id,trading_date,pair_status,z_score,abs_z,beta,
                z_velocity_1d,data_available_at,relationship_snapshot_id
                FROM analytics.pair_state_daily
                WHERE relationship_version=? AND trading_date=? ORDER BY abs_z DESC,pair_id""",
                [version, session],
            ).fetchdf()
        return ScannerView(as_of, session, tuple(row[0] for row in pairs), rows, versions)

    def pair_detail(self, pair_id: str, as_of: date, *, lookback_days: int = 365) -> PairDetailView:
        if not 1 <= lookback_days <= 3660:
            raise ValueError("History range must be between 1 and 3660 calendar days")
        overview = self.scanner(as_of)
        if pair_id not in overview.pair_ids:
            raise ValueError("Unknown fixed-orientation pair")
        version = overview.versions.relationship_version
        start = as_of - timedelta(days=lookback_days)
        with self.factory.connect() as connection:
            history = connection.execute(
                """SELECT trading_date,spread,z_score,pair_status,relationship_snapshot_id
                FROM analytics.pair_state_daily WHERE relationship_version=? AND pair_id=?
                AND trading_date BETWEEN ? AND ? ORDER BY trading_date""",
                [version, pair_id, start, as_of],
            ).fetchdf()
            current = connection.execute(
                """SELECT * FROM analytics.pair_state_daily
                WHERE relationship_version=? AND pair_id=? AND trading_date=?""",
                [version, pair_id, overview.session],
            ).fetchdf()
            snapshots = connection.execute(
                """SELECT * FROM analytics.relationship_snapshots
                WHERE relationship_version=? AND pair_id=? AND effective_start<=?
                AND (effective_end IS NULL OR ?<effective_end)
                ORDER BY effective_start DESC LIMIT 1""",
                [version, pair_id, overview.session, overview.session],
            ).fetchdf()
            crossings = connection.execute(
                """SELECT trading_date,z_score,direction,baseline1_eligible,relationship_snapshot_id
                FROM analytics.divergence_crossings WHERE relationship_version=? AND pair_id=?
                AND trading_date BETWEEN ? AND ? ORDER BY trading_date DESC""",
                [version, pair_id, start, as_of],
            ).fetchdf()
        predictions = pd.DataFrame()
        if self.model_reader is not None and overview.versions.model is not None:
            predictions = self.model_reader.predictions(pair_id=pair_id, end=as_of)
            if not predictions.empty:
                if "details" in predictions:
                    predictions = pd.DataFrame(
                        [_unpack(row, "details") for row in predictions.to_dict("records")]
                    )
                if (
                    predictions["pair_id"].ne(pair_id)
                    | pd.to_datetime(predictions["event_timestamp"], utc=True).dt.date.gt(as_of)
                ).any():
                    raise ValueError(
                        "Stored model prediction is outside the selected information set"
                    )
                allowed = (
                    "event_id",
                    "event_timestamp",
                    "partition",
                    "raw_probability",
                    "calibrated_probability",
                    "probability_bucket",
                    "ml_qualified",
                    "shap_positive",
                    "shap_negative",
                    "full_shap",
                    "top_shap_positive",
                    "top_shap_negative",
                    "shap_values",
                    "shap_base_value",
                    "evaluation_role",
                    "explanation_status",
                    "prediction_timestamp",
                    "code_revision",
                    "model_version",
                    "calibrator_version",
                    "feature_schema_version",
                    "policy_version",
                    "ml_policy_version",
                )
                predictions = predictions.loc[
                    :, [name for name in allowed if name in predictions]
                ].sort_values("event_timestamp", ascending=False)
        return PairDetailView(
            pair_id=pair_id,
            requested_as_of=as_of,
            session=overview.session,
            state=None if current.empty else _unpack(current.iloc[0].to_dict(), "details"),
            snapshot=None
            if snapshots.empty
            else _unpack(snapshots.iloc[0].to_dict(), "diagnostics"),
            history=history,
            crossings=crossings,
            predictions=predictions,
            versions=overview.versions,
        )

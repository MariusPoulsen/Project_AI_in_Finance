"""Historical source queries use local frozen inputs and never retrieve live data."""

import json
from datetime import date, datetime
from typing import Any

import pandas as pd

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.snapshots import verify_snapshot
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file


class DataRepository:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.factory = DuckDBConnectionFactory(paths.database)

    def active_manifest(self, *, verify: bool = True) -> dict[str, Any]:
        with self.factory.connect() as connection:
            row = connection.execute(
                """SELECT active.manifest_path, versions.checksum
                FROM ops.active_data_snapshot active JOIN ops.dataset_versions versions
                ON active.data_snapshot_id=versions.dataset_version WHERE singleton"""
            ).fetchone()
        if row is None:
            raise FileNotFoundError("No data snapshot is published; run ingest-data first")
        path = confined_path(self.paths.workspace_root, row[0])
        if verify and sha256_file(path) != row[1]:
            raise ValueError("Registered snapshot manifest checksum mismatch")
        manifest: dict[str, Any] = json.loads(path.read_bytes())
        if verify:
            verify_snapshot(self.paths, manifest)
        return manifest

    def pair_prices(self, pair_id: str, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError("Query start must not follow end")
        self.active_manifest()
        with self.factory.connect() as connection:
            pair = connection.execute(
                """SELECT leg_a_security_id,leg_b_security_id FROM ref.pair_universe
                WHERE pair_id=? AND enabled""",
                [pair_id],
            ).fetchone()
            if pair is None:
                raise ValueError("Unknown or disabled pair")
            return connection.execute(
                """SELECT * FROM market.prices_daily
                WHERE security_id IN (?, ?) AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date,security_id""",
                [*pair, start, end],
            ).fetchdf()

    def eligible_filings(self, security_id: str, cutoff: datetime) -> pd.DataFrame:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("Evidence cutoff must be timezone aware")
        self.active_manifest()
        with self.factory.connect() as connection:
            return connection.execute(
                """SELECT * FROM ref.sec_filing_index
                WHERE security_id=? AND point_in_time_eligible
                AND acceptance_datetime_utc<=?
                ORDER BY acceptance_datetime_utc,filing_id""",
                [security_id, cutoff],
            ).fetchdf()

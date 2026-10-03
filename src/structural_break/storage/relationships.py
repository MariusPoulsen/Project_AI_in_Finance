"""Transactional persistence of versioned econometric outputs."""

import json
import math
from datetime import date, datetime
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.storage.files import sha256_file

TABLE_COLUMNS = {
    "relationship_snapshots": (
        "relationship_snapshot_id",
        "pair_id",
        "estimation_date",
        "effective_start",
        "effective_end",
        "data_snapshot_id",
        "config_hash",
        "pair_status",
        "n_obs",
        "alpha",
        "beta",
        "spread_mean",
        "spread_std",
    ),
    "pair_state_daily": (
        "pair_id",
        "trading_date",
        "relationship_snapshot_id",
        "alpha",
        "beta",
        "spread",
        "z_score",
        "abs_z",
        "spread_velocity_1d",
        "z_velocity_1d",
        "pair_status",
        "data_available_at",
        "data_snapshot_id",
    ),
    "divergence_crossings": (
        "crossing_id",
        "pair_id",
        "trading_date",
        "event_timestamp",
        "relationship_snapshot_id",
        "direction",
        "z_score",
        "baseline1_eligible",
        "data_snapshot_id",
    ),
}


def json_value(value: Any) -> Any:
    """Represent explicit missing diagnostics as JSON null, never nonstandard NaN."""
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_value(item) for item in value]
    if isinstance(value, np.generic):
        return json_value(value.item())
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def payload_json(row: dict[Any, Any]) -> str:
    return json.dumps(json_value(row), sort_keys=True, allow_nan=False)


def publish_relationships(
    connection: duckdb.DuckDBPyConnection,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    run_id: str,
) -> None:
    version = manifest["relationship_version"]
    path = paths.artifacts / "relationships" / version / "manifest.json"
    connection.execute(
        """INSERT INTO analytics.relationship_versions
        (relationship_version,data_snapshot_id,config_hash,synthetic,manifest_path,checksum,run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            version,
            manifest["data_snapshot_id"],
            manifest["config_hash"],
            manifest["synthetic"],
            path.relative_to(paths.workspace_root).as_posix(),
            sha256_file(path),
            run_id,
        ],
    )
    for table, columns in TABLE_COLUMNS.items():
        frame = frames[table]
        if frame.empty:
            continue
        projected = frame.loc[:, list(columns)].copy()
        payload = "diagnostics" if table == "relationship_snapshots" else "details"
        projected[payload] = [payload_json(row) for row in frame.to_dict("records")]
        connection.register("_relationship_payload", projected)
        try:
            names = ",".join([*columns, payload])
            connection.execute(
                f"INSERT INTO analytics.{table} (relationship_version,{names}) "
                f"SELECT ?,{names} FROM _relationship_payload",
                [version],
            )
        finally:
            connection.unregister("_relationship_payload")
    connection.execute(
        """INSERT INTO ops.active_relationship_version VALUES (true, ?)
        ON CONFLICT(singleton) DO UPDATE SET relationship_version=excluded.relationship_version""",
        [version],
    )

"""Transactional publication of event datasets and model predictions."""

from typing import Any

import duckdb
import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.storage.files import sha256_file
from structural_break.storage.relationships import payload_json

EVENT_TABLES = {
    "divergence_events": (
        "event_id",
        "pair_id",
        "event_timestamp",
        "relationship_version",
        "relationship_snapshot_id",
        "entry_z",
        "baseline1_eligible",
        "partition",
        "feature_complete",
        "model_ready",
    ),
    "event_features": (
        "event_id",
        "feature_schema_version",
        "feature_cutoff_timestamp",
        "feature_complete",
    ),
    "event_targets": ("event_id", "y_revert_success", "outcome_type", "label_eligible"),
    "event_partitions": ("event_id", "partition", "supervised_eligible", "exclusion_reason"),
}


def insert_frame(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    key: str,
    value: str,
) -> None:
    if frame.empty:
        return
    selected = frame.loc[:, list(columns)].copy()
    selected["details"] = [payload_json(row) for row in frame.to_dict("records")]
    connection.register("_model_a_payload", selected)
    try:
        names = ",".join([*columns, "details"])
        connection.execute(
            f"INSERT INTO analytics.{table} ({key},{names}) SELECT ?,{names} FROM _model_a_payload",
            [value],
        )
    finally:
        connection.unregister("_model_a_payload")


def publish_events(
    connection: duckdb.DuckDBPyConnection,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    run_id: str,
) -> None:
    identity = manifest["dataset_version"]
    path = paths.artifacts / "events" / identity / "manifest.json"
    connection.execute(
        """INSERT INTO analytics.event_dataset_versions VALUES (?,?,?,?,?,?,?)""",
        [
            identity,
            manifest["data_snapshot_id"],
            manifest["relationship_version"],
            manifest["config_hash"],
            path.relative_to(paths.workspace_root).as_posix(),
            sha256_file(path),
            run_id,
        ],
    )
    for table, columns in EVENT_TABLES.items():
        insert_frame(connection, table, frames[table], columns, "dataset_version", identity)
    connection.execute(
        """INSERT INTO ops.active_event_dataset VALUES (true,?)
      ON CONFLICT(singleton) DO UPDATE SET dataset_version=excluded.dataset_version""",
        [identity],
    )


def publish_model(
    connection: duckdb.DuckDBPyConnection,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    predictions: pd.DataFrame,
    run_id: str,
) -> None:
    identity = manifest["model_version"]
    path = paths.artifacts / "models" / identity / "manifest.json"
    connection.execute(
        "INSERT INTO analytics.model_versions VALUES (?,?,?,?,?)",
        [
            identity,
            manifest["dataset_version"],
            path.relative_to(paths.workspace_root).as_posix(),
            sha256_file(path),
            run_id,
        ],
    )
    insert_frame(
        connection,
        "model_predictions",
        predictions,
        (
            "dataset_version",
            "event_id",
            "pair_id",
            "event_timestamp",
            "raw_probability",
            "calibrated_probability",
        ),
        "model_version",
        identity,
    )
    connection.execute(
        """INSERT INTO ops.active_model_a VALUES (true,?)
      ON CONFLICT(singleton) DO UPDATE SET model_version=excluded.model_version""",
        [identity],
    )

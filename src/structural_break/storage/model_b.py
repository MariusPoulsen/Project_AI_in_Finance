"""Atomic publication of Model B without replacing Model A or its event dataset."""

from typing import Any

import duckdb
import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.storage.files import sha256_file
from structural_break.storage.model_a import insert_frame


def publish_model_b(
    connection: duckdb.DuckDBPyConnection,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    predictions: pd.DataFrame,
    run_id: str,
) -> None:
    identity = manifest["model_version"]
    path = paths.artifacts / "models" / identity / "manifest.json"
    connection.execute(
        "INSERT INTO analytics.model_b_versions VALUES (?,?,?,?,?,?,?)",
        [
            identity,
            manifest["dataset_version"],
            manifest["event_feature_version"],
            manifest["model_a_version"],
            path.relative_to(paths.workspace_root).as_posix(),
            sha256_file(path),
            run_id,
        ],
    )
    insert_frame(
        connection,
        "model_b_predictions",
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
        """INSERT INTO ops.active_model_b VALUES (true,?)
        ON CONFLICT(singleton) DO UPDATE SET model_version=excluded.model_version""",
        [identity],
    )

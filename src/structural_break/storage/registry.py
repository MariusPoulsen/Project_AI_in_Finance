"""Run lifecycle and version provenance; only successful runs publish registrations."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb

from structural_break.config.loader import config_hash, normalized_config
from structural_break.config.models import ProjectConfig
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file


@dataclass(frozen=True)
class Registration:
    kind: str
    version: str
    path: Path


@dataclass(frozen=True)
class RunRegistry:
    factory: DuckDBConnectionFactory
    workspace: Path

    def start(
        self, run_id: str, job: str, config: ProjectConfig, git_commit: str, dataset_version: str
    ) -> None:
        with self.factory.connect(read_only=False) as connection:
            connection.execute(
                """INSERT INTO ops.job_runs
                (run_id, job, started_at, status, config_hash, config_snapshot,
                 git_commit, dataset_version) VALUES (?, ?, ?, 'RUNNING', ?, ?, ?, ?)""",
                [
                    run_id,
                    job,
                    datetime.now(UTC),
                    config_hash(config),
                    normalized_config(config),
                    git_commit,
                    dataset_version,
                ],
            )

    def finish(
        self,
        run_id: str,
        *,
        status: Literal["SUCCESS", "FAILED"],
        record_count: int = 0,
        error_type: str | None = None,
        artifacts: tuple[Registration, ...] = (),
        dataset: Registration | None = None,
        publish: Callable[[duckdb.DuckDBPyConnection], None] | None = None,
    ) -> None:
        if status == "FAILED" and (artifacts or dataset):
            raise ValueError("Failed runs cannot publish versions")
        if record_count < 0:
            raise ValueError("Record count cannot be negative")
        prepared = []
        for item in (*artifacts, *((dataset,) if dataset else ())):
            relative = item.path.resolve().relative_to(self.workspace.resolve()).as_posix()
            prepared.append((item, relative, sha256_file(item.path)))
        with self.factory.connect(read_only=False) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                row = connection.execute(
                    "SELECT status FROM ops.job_runs WHERE run_id = ?", [run_id]
                ).fetchone()
                if row != ("RUNNING",):
                    raise ValueError("Run must exist and be RUNNING")
                connection.execute(
                    """UPDATE ops.job_runs SET finished_at = ?, status = ?, record_count = ?,
                    error_type = ? WHERE run_id = ?""",
                    [datetime.now(UTC), status, record_count, error_type, run_id],
                )
                if publish is not None:
                    if status != "SUCCESS":
                        raise ValueError("Only successful runs can publish canonical data")
                    publish(connection)
                for item, relative, checksum in prepared:
                    if dataset is not None and item is dataset:
                        existing = connection.execute(
                            """SELECT manifest_path, checksum FROM ops.dataset_versions
                            WHERE dataset_version = ?""",
                            [item.version],
                        ).fetchone()
                        if existing and existing != (relative, checksum):
                            raise ValueError("Dataset version already has different content")
                        if not existing:
                            connection.execute(
                                """INSERT INTO ops.dataset_versions
                                (dataset_version, manifest_path, checksum, run_id)
                                VALUES (?, ?, ?, ?)""",
                                [item.version, relative, checksum, run_id],
                            )
                    else:
                        identity = hashlib.sha256(relative.encode()).hexdigest()
                        existing = connection.execute(
                            """SELECT kind, version, checksum FROM ops.artifact_registry
                            WHERE artifact_id = ?""",
                            [identity],
                        ).fetchone()
                        if existing and existing != (item.kind, item.version, checksum):
                            raise ValueError("Artifact version already has different content")
                        if not existing:
                            connection.execute(
                                """INSERT INTO ops.artifact_registry
                                (artifact_id, kind, version, path, checksum, run_id)
                                VALUES (?, ?, ?, ?, ?, ?)""",
                                [identity, item.kind, item.version, relative, checksum, run_id],
                            )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

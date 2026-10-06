"""Batch publication keeps reader views on complete immutable snapshots."""

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from structural_break.config.paths import ProjectPaths, confined_path

VIEW_NAMES = {
    "reference/security_master.parquet": "ref.security_master",
    "reference/pair_universe.parquet": "ref.pair_universe",
    "reference/sector_etf_map.parquet": "ref.sector_etf_map",
    "curated/market/prices_daily.parquet": "market.prices_daily",
    "curated/market/corporate_actions.parquet": "market.corporate_actions",
    "curated/market/market_context_daily.parquet": "market.market_context_daily",
    "curated/evidence/sec_filing_index.parquet": "ref.sec_filing_index",
}


@contextmanager
def canonical_aliases(paths: ProjectPaths, files: list[dict[str, Any]]) -> Iterator[None]:
    """Rollback the latest-file aliases if the subsequent catalogue transaction fails."""
    backups: list[tuple[Path, Path | None]] = []
    try:
        for item in files:
            source = confined_path(paths.workspace_root, item["path"])
            logical_target = paths.data / item["dataset"]
            if any(
                part.is_symlink()
                for part in (logical_target, *logical_target.parents)
                if part.is_relative_to(paths.data)
            ):
                raise ValueError("Canonical publication targets must not contain symlinks")
            target = paths.data_path(item["dataset"])
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if target.exists():
                descriptor, name = tempfile.mkstemp(prefix=".rollback-", dir=target.parent)
                os.close(descriptor)
                backup = Path(name)
                backup.unlink()
                os.link(target, backup)
            backups.append((target, backup))
            descriptor, name = tempfile.mkstemp(prefix=".publish-", dir=target.parent)
            os.close(descriptor)
            temporary = Path(name)
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        yield
    except Exception:
        for target, backup in reversed(backups):
            if backup is not None:
                os.replace(backup, target)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        for _, backup in backups:
            if backup is not None:
                backup.unlink(missing_ok=True)


def publish_catalogue(
    connection: duckdb.DuckDBPyConnection,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    run_id: str,
) -> None:
    for file in manifest["curated_files"]:
        view = VIEW_NAMES[file["dataset"]]
        path = confined_path(paths.workspace_root, file["path"]).as_posix().replace("'", "''")
        connection.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM read_parquet('{path}')")
    for entry in manifest["sources"]:
        connection.execute(
            """INSERT INTO ops.ingestion_runs VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                run_id,
                entry["source_snapshot_id"],
                entry["role"],
                entry["source_provider"],
                entry["source_url"],
                json.dumps(entry["parameters"]),
                entry["library_version"],
                entry["retrieved_at_utc"],
                entry["raw_file_path"],
                entry["sha256"],
                entry["bytes"],
                entry["row_count"],
                entry["http_status"],
                entry["result_status"],
                manifest["data_snapshot_id"],
            ],
        )
    record_quality(connection, manifest["quality"], manifest["data_snapshot_id"], run_id)
    for provider in sorted({entry["source_provider"] for entry in manifest["sources"]}):
        latest = max(
            entry["retrieved_at_utc"]
            for entry in manifest["sources"]
            if entry["source_provider"] == provider
        )
        connection.execute(
            """INSERT INTO ops.source_health VALUES (?, 'OK', current_timestamp, ?, ?, NULL)
            ON CONFLICT(source) DO UPDATE SET status='OK', checked_at=excluded.checked_at,
            last_success_at=excluded.last_success_at,run_id=excluded.run_id,error_type=NULL""",
            [provider, latest, run_id],
        )
    connection.execute(
        """INSERT INTO ops.active_data_snapshot(singleton,data_snapshot_id,manifest_path)
        VALUES (true, ?, ?) ON CONFLICT(singleton) DO UPDATE SET
        data_snapshot_id=excluded.data_snapshot_id,manifest_path=excluded.manifest_path,
        activated_at=now()""",
        [
            manifest["data_snapshot_id"],
            f"data/snapshots/{manifest['data_snapshot_id']}/manifest.json",
        ],
    )


def record_quality(
    connection: duckdb.DuckDBPyConnection,
    quality: list[dict[str, object]],
    snapshot_id: str,
    run_id: str,
) -> None:
    for check in quality:
        connection.execute(
            """INSERT INTO ops.data_quality_results
            (run_id,data_snapshot_id,dataset,check_name,severity,affected_rows,message)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                run_id,
                snapshot_id,
                check["dataset"],
                check["check"],
                check["severity"],
                check["affected_rows"],
                check["message"],
            ],
        )

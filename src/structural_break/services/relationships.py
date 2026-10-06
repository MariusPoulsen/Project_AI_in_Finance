"""Offline jobs and verified queries for the Phase 2 econometric engine."""

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from structural_break.common.logging import configure_logging, new_run_id
from structural_break.config.loader import config_hash
from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.snapshots import date_coverage, json_bytes
from structural_break.services.data_queries import DataRepository
from structural_break.services.foundation import git_revision
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import segment, sha256_file, write_bytes
from structural_break.storage.registry import Registration, RunRegistry
from structural_break.storage.relationships import publish_relationships


def computation_identity() -> dict[str, Any]:
    """Bind a generation to installed source and numerical dependencies, across OSes."""
    source_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*.py")):
        digest.update(path.relative_to(source_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return {
        "source_sha256": digest.hexdigest(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "libraries": {
            name: version(name)
            for name in (
                "numpy",
                "pandas",
                "scipy",
                "statsmodels",
                "exchange-calendars",
                "pyarrow",
                "duckdb",
                "pydantic",
            )
        },
    }


def _input_frames(paths: ProjectPaths) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    manifest = DataRepository(paths).active_manifest()
    entries = {file["dataset"]: file for file in manifest["curated_files"]}

    def read(name: str) -> pd.DataFrame:
        return pd.DataFrame(
            pq.read_table(confined_path(paths.workspace_root, entries[name]["path"])).to_pandas()
        )

    prices = read("curated/market/prices_daily.parquet")
    pairs = read("reference/pair_universe.parquet")
    securities = read("reference/security_master.parquet").set_index("ticker")
    starts: list[date | None] = []
    ends: list[date | None] = []
    for row in pairs.to_dict("records"):
        active_from = securities.loc[[row["leg_a"], row["leg_b"]], "active_from"].dropna()
        active_to = securities.loc[[row["leg_a"], row["leg_b"]], "active_to"].dropna()
        starts.append(max(active_from) if len(active_from) else None)
        ends.append(min(active_to) if len(active_to) else None)
    pairs["active_from"], pairs["active_to"] = starts, ends
    return prices, pairs, manifest


def build_relationships(
    paths: ProjectPaths,
    config: ProjectConfig,
    *,
    fixture: bool = False,
    relationship_version: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    from structural_break.econometrics.engine import build_relationship_history

    run_id, revision = new_run_id(), git_revision(paths.project_root)
    logger = configure_logging()
    paths.create_directories()
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    input_manifest: dict[str, Any]
    if fixture:
        from structural_break.econometrics.fixtures import fixture_inputs

        prices, pairs, fixture_start, fixture_end, identity = fixture_inputs()
        input_manifest = {
            "data_snapshot_id": "synthetic_p2_" + identity[:16],
            "synthetic": True,
            "source_identity": identity,
        }
        default_start, default_end = fixture_start, fixture_end
    else:
        prices, pairs, input_manifest = _input_frames(paths)
        default_start, default_end = config.data.start, config.data.end
    start, end = start or default_start, end or default_end
    if start > end or end > default_end:
        raise ValueError("Relationship build bounds exceed available input scope")
    identity_payload = {
        "data_snapshot_id": input_manifest["data_snapshot_id"],
        "config_hash": config_hash(config),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "computation_identity": computation_identity(),
    }
    from structural_break.data.snapshots import content_identity

    output_version = segment(
        relationship_version or "relationships_" + content_identity(identity_payload)[:24]
    )
    destination = paths.artifacts / "relationships" / output_version
    existing = destination / "manifest.json"
    repository = RelationshipsRepository(paths)
    with factory.connect() as connection:
        registered = connection.execute(
            "SELECT count(*) FROM analytics.relationship_versions WHERE relationship_version=?",
            [output_version],
        ).fetchone()
    if registered and registered[0]:
        previous = repository.manifest(output_version)
        if any(previous.get(key) != value for key, value in identity_payload.items()):
            raise ValueError(
                "Relationship identity already has different input/settings/computation"
            )
        return previous
    if destination.exists():
        archive = destination.with_name(output_version + ".unregistered-" + run_id)
        root = paths.artifacts.resolve()
        if destination.is_symlink() or not all(
            path.resolve().is_relative_to(root) for path in (destination, archive)
        ):
            raise ValueError("Unregistered output archive escapes the artifact workspace")
        destination.rename(archive)
    registry = RunRegistry(factory, paths.workspace_root)
    registry.start(
        run_id, "build-relationships", config, revision, input_manifest["data_snapshot_id"]
    )
    logger.info(
        "Relationship build started",
        extra={
            "run_id": run_id,
            "stage": "estimate",
            "relationship_version": output_version,
            "dataset_version": input_manifest["data_snapshot_id"],
        },
    )
    try:
        created_at = datetime.now(UTC)
        snapshots, daily, crossings = build_relationship_history(
            prices,
            pairs,
            config.econometrics,
            data_snapshot_id=input_manifest["data_snapshot_id"],
            config_hash=config_hash(config),
            start=start,
            end=end,
            created_at=created_at,
        )
        frames = {
            "relationship_snapshots": snapshots,
            "pair_state_daily": daily,
            "divergence_crossings": crossings,
        }
        validate_relationships(frames)
        files = []
        for name, frame in frames.items():
            table = pa.Table.from_pandas(frame, preserve_index=False).replace_schema_metadata(None)
            buffer = pa.BufferOutputStream()
            pq.write_table(table, buffer, compression="zstd")
            path = write_bytes(destination / f"{name}.parquet", buffer.getvalue().to_pybytes())
            files.append(
                {
                    "dataset": name,
                    "path": path.relative_to(paths.workspace_root).as_posix(),
                    "sha256": sha256_file(path),
                    "rows": len(frame),
                    "date_coverage": date_coverage(frame),
                }
            )
        manifest: dict[str, Any] = {
            **identity_payload,
            "relationship_version": output_version,
            "run_id": run_id,
            "created_at_utc": created_at.isoformat(),
            "code_revision": revision,
            "synthetic": bool(input_manifest["synthetic"]),
            "input_manifest": input_manifest,
            "config_snapshot": config.model_dump(mode="json"),
            "files": files,
            "counts": {name: len(frame) for name, frame in frames.items()},
            "statsmodels_version": version("statsmodels"),
            "final_test_outcomes_computed": False,
        }
        write_bytes(existing, json_bytes(manifest))
        registry.finish(
            run_id,
            status="SUCCESS",
            record_count=sum(len(frame) for frame in frames.values()),
            artifacts=(Registration("relationships", output_version, existing),),
            publish=lambda connection: publish_relationships(
                connection, paths, manifest, frames, run_id
            ),
        )
        logger.info(
            "Relationship build published",
            extra={
                "run_id": run_id,
                "stage": "complete",
                "status": "SUCCESS",
                "record_count": len(daily),
            },
        )
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        failure = {
            "run_id": run_id,
            "relationship_version": output_version,
            "config_hash": config_hash(config),
            "data_snapshot_id": input_manifest["data_snapshot_id"],
            "error_type": type(error).__name__,
            "pair_id": getattr(error, "pair_id", None),
            "estimation_date": str(getattr(error, "estimation_date", "unknown")),
        }
        write_bytes(destination / "failures" / f"{run_id}.json", json_bytes(failure))
        logger.error(
            "Relationship build failed",
            extra={"run_id": run_id, "status": "FAILED", "error_type": type(error).__name__},
        )
        raise


def validate_relationships(frames: dict[str, pd.DataFrame]) -> None:
    snapshots, daily, crossings = (
        frames[key]
        for key in ("relationship_snapshots", "pair_state_daily", "divergence_crossings")
    )
    if snapshots.empty:
        raise ValueError("Relationship build contains no monthly attempts")
    if snapshots["relationship_snapshot_id"].duplicated().any():
        raise ValueError("Duplicate monthly snapshot identities")
    if not snapshots["pair_status"].isin(["ACTIVE", "WATCH", "RETIRED"]).all():
        raise ValueError("Invalid lifecycle state")
    if (snapshots["effective_start"] <= snapshots["estimation_date"]).any():
        raise ValueError("A relationship cannot be effective on/before its estimation date")
    if (
        (snapshots["window_end"].notna()) & (snapshots["window_end"] > snapshots["estimation_date"])
    ).any():
        raise ValueError("Formation window includes future observations")
    for _, history in snapshots.groupby("pair_id", sort=False):
        ordered = history.sort_values("effective_start")
        if ordered["effective_start"].duplicated().any():
            raise ValueError("Overlapping monthly effective starts")
        if len(ordered) > 1 and not ordered["effective_end"].iloc[:-1].reset_index(
            drop=True
        ).equals(ordered["effective_start"].iloc[1:].reset_index(drop=True)):
            raise ValueError("Monthly validity intervals overlap or leave an unintended gap")
    if daily.empty:
        if not crossings.empty:
            raise ValueError("Crossings have no corresponding daily state")
        return
    if daily.duplicated(["pair_id", "trading_date"]).any():
        raise ValueError("Duplicate daily pair state")
    if not np.isfinite(
        daily[["alpha", "beta", "spread", "z_score", "abs_z"]].to_numpy(dtype=float)
    ).all():
        raise ValueError("Daily pair state has undefined/nonfinite numerical values")
    joined = daily.merge(
        snapshots[["relationship_snapshot_id", "effective_start", "effective_end"]],
        on="relationship_snapshot_id",
        how="left",
        validate="many_to_one",
    )
    if (
        joined["effective_start"].isna() | (joined["trading_date"] < joined["effective_start"])
    ).any():
        raise ValueError("Daily state references a future/unknown estimate")
    if (
        (joined["effective_end"].notna()) & (joined["trading_date"] >= joined["effective_end"])
    ).any():
        raise ValueError("Daily state references an expired estimate")
    if crossings.empty:
        return
    if crossings["crossing_id"].duplicated().any():
        raise ValueError("Duplicate crossing identities")
    matched = crossings.merge(
        daily[
            [
                "pair_id",
                "trading_date",
                "relationship_snapshot_id",
                "data_available_at",
                "z_score",
                "fresh_threshold_crossing",
                "pair_status",
            ]
        ],
        on=["pair_id", "trading_date"],
        how="left",
        suffixes=("", "_daily"),
        validate="one_to_one",
    )
    if (
        matched["relationship_snapshot_id_daily"].isna()
        | matched["relationship_snapshot_id"].ne(matched["relationship_snapshot_id_daily"])
        | matched["event_timestamp"].ne(matched["data_available_at_daily"])
        | matched["z_score"].ne(matched["z_score_daily"])
        | ~matched["fresh_threshold_crossing_daily"].fillna(False)
        | matched["fresh_threshold_crossing"].ne(matched["fresh_threshold_crossing_daily"])
        | matched["pair_status"].ne(matched["pair_status_daily"])
        | matched["baseline1_eligible"].ne(matched["pair_status_daily"].eq("ACTIVE"))
        | ~matched["baseline0_eligible"]
    ).any():
        raise ValueError("Crossing disagrees with its exact historical daily state")
    if ((crossings["baseline1_eligible"]) & crossings["pair_status"].ne("ACTIVE")).any():
        raise ValueError("Baseline 1 crossing is not ACTIVE")


class RelationshipsRepository:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths, self.factory = paths, DuckDBConnectionFactory(paths.database)

    def manifest(self, relationship_version: str | None = None) -> dict[str, Any]:
        with self.factory.connect() as connection:
            if relationship_version is None:
                row = connection.execute(
                    """SELECT versions.manifest_path,versions.checksum
                    FROM ops.active_relationship_version active
                    JOIN analytics.relationship_versions versions
                    ON active.relationship_version=versions.relationship_version WHERE singleton"""
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT manifest_path,checksum FROM analytics.relationship_versions
                    WHERE relationship_version=?""",
                    [relationship_version],
                ).fetchone()
        if row is None:
            raise FileNotFoundError("No published relationship version")
        path = confined_path(self.paths.workspace_root, row[0])
        if sha256_file(path) != row[1]:
            raise ValueError("Relationship manifest checksum mismatch")
        manifest: dict[str, Any] = json.loads(path.read_bytes())
        for item in manifest["files"]:
            if (
                sha256_file(confined_path(self.paths.workspace_root, item["path"]))
                != item["sha256"]
            ):
                raise ValueError("Relationship artifact checksum mismatch")
        return manifest

    def active_manifest(self) -> dict[str, Any]:
        return self.manifest()

    def _check_pair(self, pair_id: str, manifest: dict[str, Any]) -> None:
        with self.factory.connect() as connection:
            row = connection.execute(
                """SELECT count(*) FROM analytics.relationship_snapshots
                WHERE relationship_version=? AND pair_id=?""",
                [manifest["relationship_version"], pair_id],
            ).fetchone()
        if row is None or row[0] == 0:
            raise ValueError("Unknown fixed-orientation pair")

    def pair_states(self, pair_id: str, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError("Query start follows end")
        manifest = self.manifest()
        self._check_pair(pair_id, manifest)
        with self.factory.connect() as connection:
            return connection.execute(
                """SELECT * FROM analytics.pair_state_daily
                WHERE relationship_version=? AND pair_id=? AND trading_date BETWEEN ? AND ?
                ORDER BY trading_date""",
                [manifest["relationship_version"], pair_id, start, end],
            ).fetchdf()

    def crossings(self, pair_id: str, *, eligible_only: bool = False) -> pd.DataFrame:
        manifest = self.manifest()
        self._check_pair(pair_id, manifest)
        with self.factory.connect() as connection:
            return connection.execute(
                """SELECT * FROM analytics.divergence_crossings
                WHERE relationship_version=? AND pair_id=? AND (NOT ? OR baseline1_eligible)
                ORDER BY trading_date""",
                [manifest["relationship_version"], pair_id, eligible_only],
            ).fetchdf()

    def snapshot_for_session(self, pair_id: str, day: date) -> pd.DataFrame:
        manifest = self.manifest()
        self._check_pair(pair_id, manifest)
        with self.factory.connect() as connection:
            return connection.execute(
                """SELECT * FROM analytics.relationship_snapshots
                WHERE relationship_version=? AND pair_id=? AND effective_start<=?
                AND (effective_end IS NULL OR ?<effective_end)
                ORDER BY effective_start DESC LIMIT 1""",
                [manifest["relationship_version"], pair_id, day, day],
            ).fetchdf()

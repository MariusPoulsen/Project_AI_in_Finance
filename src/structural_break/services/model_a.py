"""Offline event/model jobs and verified, read-only Model A queries."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from structural_break.common.logging import configure_logging, new_run_id
from structural_break.config.loader import config_hash
from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.snapshots import content_identity, json_bytes
from structural_break.services.data_queries import DataRepository
from structural_break.services.foundation import git_revision
from structural_break.services.relationships import (
    RelationshipsRepository,
    computation_identity,
    validate_relationships,
)
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import segment, sha256_file, write_bytes
from structural_break.storage.model_a import publish_events, publish_model
from structural_break.storage.registry import Registration, RunRegistry
from structural_break.storage.relationships import publish_relationships


class UnpublishedVersionError(FileNotFoundError):
    """No registry entry exists, distinct from a missing registered artifact."""


def ml_computation_identity() -> dict[str, Any]:
    identity = computation_identity()
    identity["libraries"].update(
        {name: version(name) for name in ("scikit-learn", "xgboost", "shap", "numba", "mlflow")}
    )
    return identity


def _read_frames(paths: ProjectPaths, manifest: dict[str, Any]) -> dict[str, pd.DataFrame]:
    return {
        item["dataset"]: pd.DataFrame(
            pq.read_table(confined_path(paths.workspace_root, item["path"])).to_pandas()
        )
        for item in manifest["files"]
        if item["path"].endswith(".parquet")
    }


def _freeze_frames(
    paths: ProjectPaths, destination: Path, frames: dict[str, pd.DataFrame]
) -> list[dict[str, Any]]:
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
            }
        )
    return files


def _archive_unregistered(paths: ProjectPaths, destination: Path, run_id: str) -> None:
    archive = destination.with_name(destination.name + ".unregistered-" + run_id)
    root = paths.artifacts.resolve()
    if destination.is_symlink() or not all(
        path.resolve().is_relative_to(root) for path in (destination, archive)
    ):
        raise ValueError("Unregistered output archive escapes the artifact workspace")
    relative = destination.resolve().relative_to(paths.workspace_root.resolve()).as_posix()
    # Model A and B share one physical model namespace. The generic registry
    # protects every published kind, even if its directory has gone missing.
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        registered = connection.execute(
            "SELECT path FROM ops.artifact_registry "
            "WHERE lower(path)=lower(?) OR starts_with(lower(path),lower(?)) LIMIT 1",
            [relative, relative + "/"],
        ).fetchone()
    if registered is not None:
        raise ValueError("Cannot archive a destination containing a registered artifact")
    if destination.exists():
        destination.rename(archive)


def _label_policy(config: ProjectConfig) -> dict[str, Any]:
    from structural_break.ml.dataset import label_policy_version

    return {
        "version": label_policy_version(config),
        "declared_version": config.ml.label_policy_version,
        "entry_z": config.econometrics.entry_z,
        "success_z": config.econometrics.success_z,
        "adverse_z": config.econometrics.adverse_z,
        "horizon_sessions": config.econometrics.horizon_days,
        "numerical_epsilon": config.econometrics.numerical_epsilon,
        "parameters": "entry-frozen-alpha-beta-mean-std",
        "episode_protocol": "one-open-episode-inside-band-reset-v1",
        "eligibility": "ACTIVE-at-entry-no-statistical-status-exit",
        "missing_future": "censor-no-gap-bridge",
        "final_test": "causal-episode-gating-only-no-persisted-outcomes",
    }


def validate_event_frames(frames: dict[str, pd.DataFrame]) -> None:
    from structural_break.ml.features import validate_feature_timestamps

    events = frames["divergence_events"]
    if events.empty:
        raise ValueError("No divergence episodes available")
    keys = set(events["event_id"])
    if events["event_id"].isna().any():
        raise ValueError("Event identities cannot be missing")
    indexed_events = events.set_index("event_id")
    for frame in frames.values():
        if frame["event_id"].duplicated().any() or set(frame["event_id"]) != keys:
            raise ValueError("Event tables have duplicate or mismatched identities")
        indexed = frame.set_index("event_id").reindex(indexed_events.index)
        for name in ("data_snapshot_id", "relationship_version", "dataset_version"):
            if indexed[name].isna().any() or indexed[name].ne(indexed_events[name]).any():
                raise ValueError("Event tables have inconsistent source lineage")
    if not events["partition"].isin(("train", "validation", "final_test", "outside")).all():
        raise ValueError("Unknown chronological event partition")
    validate_feature_timestamps(frames["event_features"])
    features = frames["event_features"].set_index("event_id").reindex(indexed_events.index)
    partitions = frames["event_partitions"].set_index("event_id").reindex(indexed_events.index)
    times = pd.to_datetime(indexed_events["event_timestamp"], utc=True)
    cutoff = pd.to_datetime(features["feature_cutoff_timestamp"], utc=True)
    if times.isna().any() or cutoff.isna().any() or cutoff.gt(times).any():
        raise ValueError("Feature cutoff exceeds its event information set")
    for frame, names in (
        (features, ("feature_complete", "relationship_snapshot_id", "feature_schema_version")),
        (partitions, ("partition", "feature_complete", "horizon_end_date")),
    ):
        for name in names:
            if frame[name].ne(indexed_events[name]).any():
                raise ValueError("Event metadata disagrees across analytical tables")
    targets = frames["event_targets"].set_index("event_id")
    targets = targets.reindex(indexed_events.index)
    for name in ("label_policy_version", "horizon_end_date"):
        if targets[name].ne(indexed_events[name]).any():
            raise ValueError("Target policy or horizon differs from its frozen event")
    labelled = targets["label_eligible"].astype(bool)
    known = targets["y_revert_success"]
    if (
        not known.loc[labelled].isin((0, 1)).all()
        or known.loc[~labelled].notna().any()
        or not targets.loc[labelled, "outcome_type"].isin(("CONVERGED", "STOPPED", "TIMEOUT")).all()
        or known.loc[labelled]
        .ne(targets.loc[labelled, "outcome_type"].eq("CONVERGED").astype(int))
        .any()
    ):
        raise ValueError("Binary targets disagree with eligible outcome types")
    expected_supervised = (
        indexed_events["baseline1_eligible"].astype(bool)
        & indexed_events["feature_complete"].astype(bool)
        & labelled
        & indexed_events["partition"].isin(("train", "validation"))
    )
    if partitions["supervised_eligible"].ne(expected_supervised).any():
        raise ValueError("Supervised eligibility differs from its chronological target/features")
    final_ids = events.loc[events["partition"].eq("final_test"), "event_id"]
    locked = targets.loc[final_ids]
    forbidden = [
        "y_revert_success",
        "resolution_date",
        "time_to_resolution",
        "max_adverse_z",
        "max_favourable_z",
        "censor_reason",
    ]
    if (
        not locked[forbidden].isna().all().all()
        or locked["label_eligible"].any()
        or not locked["outcome_type"].eq("LOCKED").all()
    ):
        raise ValueError("Final-test outcome lock violated")
    expected_ready = events["baseline1_eligible"] & events["feature_complete"]
    if not events["model_ready"].equals(expected_ready):
        raise ValueError("Model inference eligibility differs from ACTIVE complete features")


def build_events(
    paths: ProjectPaths,
    config: ProjectConfig,
    *,
    fixture: bool = False,
    event_version: str | None = None,
) -> dict[str, Any]:
    from structural_break.ml.dataset import build_event_dataset

    paths.create_directories()
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    run_id = new_run_id()
    fixture_payload: tuple[dict[str, Any], dict[str, pd.DataFrame]] | None = None
    relation_frames: dict[str, pd.DataFrame]
    build_fixture_relationships = False
    if fixture:
        from structural_break.ml.fixtures import fixture_inputs

        prices, pairs, securities, market, source_id = fixture_inputs()
        relationship_id = (
            "relationships_p3_"
            + content_identity(
                {"source": source_id, "config": config_hash(config), "code": computation_identity()}
            )[:24]
        )
        input_manifest: dict[str, Any] = {"data_snapshot_id": source_id, "synthetic": True}
        relationship_manifest: dict[str, Any] = {
            "relationship_version": relationship_id,
            "data_snapshot_id": source_id,
            "config_snapshot": config.model_dump(mode="json"),
        }
        with factory.connect() as connection:
            registered = connection.execute(
                "SELECT count(*) FROM analytics.relationship_versions WHERE relationship_version=?",
                [relationship_id],
            ).fetchone()
        if registered and registered[0]:
            relationship_manifest = RelationshipsRepository(paths).manifest(relationship_id)
            if (
                relationship_manifest["data_snapshot_id"] != source_id
                or relationship_manifest["config_hash"] != config_hash(config)
                or relationship_manifest["computation_identity"] != computation_identity()
            ):
                raise ValueError("Synthetic upstream relationship identity has different inputs")
            relation_frames = _read_frames(paths, relationship_manifest)
            validate_relationships(relation_frames)
        else:
            build_fixture_relationships = True
    else:
        input_manifest = DataRepository(paths).active_manifest()
        entries = {item["dataset"]: item for item in input_manifest["curated_files"]}

        def read(name: str) -> pd.DataFrame:
            return pd.DataFrame(
                pq.read_table(
                    confined_path(paths.workspace_root, entries[name]["path"])
                ).to_pandas()
            )

        prices = read("curated/market/prices_daily.parquet")
        pairs = read("reference/pair_universe.parquet")
        securities = read("reference/security_master.parquet")
        market = read("curated/market/market_context_daily.parquet")
        relationship_manifest = RelationshipsRepository(paths).active_manifest()
        source_id = input_manifest["data_snapshot_id"]
        relationship_id = relationship_manifest["relationship_version"]
        if relationship_manifest["data_snapshot_id"] != source_id:
            raise ValueError("Active data and relationship generations disagree")
        for section in ("data", "universe", "econometrics"):
            if (
                relationship_manifest["config_snapshot"][section]
                != config.model_dump(mode="json")[section]
            ):
                raise ValueError(
                    "Upstream relationship settings differ from current data/economics"
                )
        relation_frames = _read_frames(paths, relationship_manifest)
    identity = {
        "data_snapshot_id": source_id,
        "relationship_version": relationship_id,
        "config_hash": config_hash(config),
        "computation_identity": ml_computation_identity(),
    }
    dataset_id = segment(event_version or "events_" + content_identity(identity)[:24])
    repository = ModelARepository(paths)
    with factory.connect() as connection:
        row = connection.execute(
            "SELECT count(*) FROM analytics.event_dataset_versions WHERE dataset_version=?",
            [dataset_id],
        ).fetchone()
    if row and row[0]:
        previous = repository.dataset_manifest(dataset_id)
        if any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError("Event identity already has different input/settings/computation")
        return previous
    destination = paths.artifacts / "events" / dataset_id
    _archive_unregistered(paths, destination, run_id)
    registry = RunRegistry(factory, paths.workspace_root)
    revision = git_revision(paths.project_root)
    registry.start(run_id, "build-events", config, revision, source_id)
    logger = configure_logging()
    logger.info("Event build started", extra={"run_id": run_id, "dataset_version": dataset_id})
    try:
        created_at = datetime.now(UTC)
        if build_fixture_relationships:
            from structural_break.econometrics.engine import build_relationship_history

            snapshots, daily, crossings = build_relationship_history(
                prices,
                pairs,
                config.econometrics,
                data_snapshot_id=source_id,
                config_hash=config_hash(config),
                start=config.data.start,
                end=config.data.end,
                created_at=created_at,
            )
            relation_frames = dict(
                zip(
                    ("relationship_snapshots", "pair_state_daily", "divergence_crossings"),
                    (snapshots, daily, crossings),
                    strict=True,
                )
            )
            validate_relationships(relation_frames)
            relationship_destination = paths.artifacts / "relationships" / relationship_id
            _archive_unregistered(paths, relationship_destination, run_id)
            relationship_manifest.update(
                {
                    "config_hash": config_hash(config),
                    "synthetic": True,
                    "run_id": run_id,
                    "created_at_utc": created_at.isoformat(),
                    "code_revision": revision,
                    "input_manifest": input_manifest,
                    "files": _freeze_frames(paths, relationship_destination, relation_frames),
                    "counts": {key: len(frame) for key, frame in relation_frames.items()},
                    "computation_identity": computation_identity(),
                    "final_test_outcomes_computed": False,
                }
            )
            write_bytes(
                relationship_destination / "manifest.json", json_bytes(relationship_manifest)
            )
            fixture_payload = (relationship_manifest, relation_frames)
        result = build_event_dataset(
            prices,
            pairs,
            securities,
            market,
            relation_frames["relationship_snapshots"],
            relation_frames["pair_state_daily"],
            relation_frames["divergence_crossings"],
            config,
            data_snapshot_id=source_id,
            relationship_version=relationship_id,
            dataset_version=dataset_id,
        )
        frames = dict(
            zip(
                ("divergence_events", "event_features", "event_targets", "event_partitions"),
                (result.events, result.features, result.targets, result.partitions),
                strict=True,
            )
        )
        validate_event_frames(frames)
        files = _freeze_frames(paths, destination, frames)
        schema_path = write_bytes(
            destination / "feature_schema.json", json_bytes(result.feature_schema)
        )
        files.append(
            {
                "dataset": "feature_schema",
                "path": schema_path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(schema_path),
            }
        )
        partition_counts = {}
        joined = merge_event_rows(frames)
        for name, part in joined.groupby("partition"):
            eligible = part[part["supervised_eligible"]]
            partition_counts[str(name)] = {
                "episodes": len(part),
                "model_ready": int(part["model_ready"].sum()),
                "supervised_eligible": len(eligible),
                "positives": int(eligible["y_revert_success"].sum())
                if name != "final_test"
                else None,
                "negatives": int(len(eligible) - eligible["y_revert_success"].sum())
                if name != "final_test"
                else None,
            }
        manifest = {
            **identity,
            "dataset_version": dataset_id,
            "run_id": run_id,
            "created_at_utc": created_at.isoformat(),
            "code_revision": revision,
            "synthetic": bool(input_manifest["synthetic"]),
            "input_manifest": input_manifest,
            "upstream_relationship_manifest_sha256": sha256_file(
                paths.artifacts / "relationships" / relationship_id / "manifest.json"
            ),
            "config_snapshot": config.model_dump(mode="json"),
            "files": files,
            "counts": {key: len(frame) for key, frame in frames.items()},
            "partition_counts": partition_counts,
            "feature_schema": result.feature_schema,
            "label_policy": _label_policy(config),
            "final_test_outcomes_computed": False,
        }
        manifest_path = write_bytes(destination / "manifest.json", json_bytes(manifest))

        def publish(connection: duckdb.DuckDBPyConnection) -> None:
            if fixture_payload is not None:
                publish_relationships(connection, paths, *fixture_payload, run_id)
            publish_events(connection, paths, manifest, frames, run_id)

        registrations = [Registration("event-dataset", dataset_id, manifest_path)]
        if fixture_payload is not None:
            registrations.append(
                Registration(
                    "relationships",
                    relationship_id,
                    paths.artifacts / "relationships" / relationship_id / "manifest.json",
                )
            )
        registry.finish(
            run_id,
            status="SUCCESS",
            record_count=len(result.events),
            artifacts=tuple(registrations),
            publish=publish,
        )
        logger.info("Event build published", extra={"run_id": run_id, "status": "SUCCESS"})
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        write_bytes(
            destination / "failures" / f"{run_id}.json",
            json_bytes(
                {
                    "run_id": run_id,
                    "dataset_version": dataset_id,
                    "error_type": type(error).__name__,
                }
            ),
        )
        raise


def merge_event_rows(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Keep the feature matrix authoritative when joining shared metadata."""
    rows = frames["event_features"].copy()
    for name in ("divergence_events", "event_targets", "event_partitions"):
        frame = frames[name]
        columns = ["event_id", *[column for column in frame if column not in rows.columns]]
        rows = rows.merge(frame[columns], on="event_id", validate="one_to_one")
    return rows


def train_model_a_job(
    paths: ProjectPaths,
    config: ProjectConfig,
    *,
    model_version: str | None = None,
) -> dict[str, Any]:
    from structural_break.ml.model import train_model_a

    paths.create_directories()
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    repository = ModelARepository(paths)
    dataset = repository.dataset_manifest()
    current_config = config.model_dump(mode="json")
    for section in ("data", "universe", "econometrics", "ml"):
        if dataset["config_snapshot"][section] != current_config[section]:
            raise ValueError("Event dataset scientific settings differ from training settings")
    frames = _read_frames(paths, dataset)
    validate_event_frames(frames)
    rows = merge_event_rows(frames)
    identity = {
        "dataset_version": dataset["dataset_version"],
        "config_hash": config_hash(config),
        "computation_identity": ml_computation_identity(),
    }
    model_id = segment(model_version or "model_a_" + content_identity(identity)[:24])
    with factory.connect() as connection:
        row = connection.execute(
            "SELECT count(*) FROM analytics.model_versions WHERE model_version=?", [model_id]
        ).fetchone()
    if row and row[0]:
        previous = repository.manifest(model_id)
        if any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError("Model identity already has different input/settings/computation")
        return previous
    run_id = new_run_id()
    destination = paths.artifacts / "models" / model_id
    _archive_unregistered(paths, destination, run_id)
    registry = RunRegistry(factory, paths.workspace_root)
    revision = git_revision(paths.project_root)
    registry.start(run_id, "train-model-a", config, revision, dataset["dataset_version"])
    logger = configure_logging()
    logger.info("Model A training started", extra={"run_id": run_id, "model_version": model_id})
    try:
        result = train_model_a(
            rows,
            dataset["feature_schema"],
            config.ml,
            destination,
            model_version=model_id,
            dataset_version=dataset["dataset_version"],
            tracking_directory=paths.artifacts / "mlflow",
            label_policy=dataset["label_policy"],
        )
        ready = rows.loc[rows["model_ready"], :].reset_index(drop=True)
        predictions = pd.concat(
            [
                ready[["event_id", "pair_id", "event_timestamp", "partition"]],
                result.bundle.predict(ready[dataset["feature_schema"]["feature_columns"]]),
            ],
            axis=1,
        )
        predictions["dataset_version"] = dataset["dataset_version"]
        predictions["relationship_version"] = dataset["relationship_version"]
        predictions["prediction_timestamp"] = datetime.now(UTC)
        predictions["code_revision"] = revision
        predictions["evaluation_role"] = predictions["partition"].map(
            {
                "train": "TRAINING_RESUBSTITUTION",
                "validation": "CALIBRATION_FIT_DESCRIPTIVE",
                "final_test": "LOCKED_FEATURE_ONLY_INFERENCE",
                "outside": "EXCLUDED",
            }
        )
        excluded = ready["partition"].isin(["train", "validation"]) & ~ready["supervised_eligible"]
        predictions.loc[excluded, "evaluation_role"] = "EXCLUDED_FROM_SUPERVISION"
        prediction_files = _freeze_frames(paths, destination, {"model_predictions": predictions})
        native_files = [
            {
                "dataset": path.stem,
                "path": path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in sorted(destination.iterdir())
            if path.is_file() and path.name not in {"manifest.json", "model_predictions.parquet"}
        ]
        manifest: dict[str, Any] = {
            **identity,
            "model_version": model_id,
            "data_snapshot_id": dataset["data_snapshot_id"],
            "relationship_version": dataset["relationship_version"],
            "synthetic": dataset["synthetic"],
            "run_id": run_id,
            "code_revision": revision,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "config_snapshot": config.model_dump(mode="json"),
            "files": native_files + prediction_files,
            "model_manifest": result.manifest,
            "feature_schema": dataset["feature_schema"],
            "metrics": result.metrics,
            "counts": {"predictions": len(predictions)},
            "upstream_event_manifest_sha256": sha256_file(
                paths.artifacts / "events" / dataset["dataset_version"] / "manifest.json"
            ),
            "final_test_outcomes_computed": False,
        }
        manifest_path = write_bytes(destination / "manifest.json", json_bytes(manifest))
        registry.finish(
            run_id,
            status="SUCCESS",
            record_count=len(predictions),
            artifacts=(Registration("model-a", model_id, manifest_path),),
            publish=lambda connection: publish_model(
                connection, paths, manifest, predictions, run_id
            ),
        )
        logger.info("Model A published", extra={"run_id": run_id, "status": "SUCCESS"})
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        write_bytes(
            destination / "failures" / f"{run_id}.json",
            json_bytes(
                {"run_id": run_id, "model_version": model_id, "error_type": type(error).__name__}
            ),
        )
        raise


class ModelARepository:
    """Verify all bytes and lineage before returning frozen analytical data."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.factory = DuckDBConnectionFactory(paths.database)

    def _manifest(self, kind: str, identity: str | None) -> dict[str, Any]:
        if kind == "model":
            table, key, active = "model_versions", "model_version", "active_model_a"
        else:
            table, key, active = "event_dataset_versions", "dataset_version", "active_event_dataset"
        try:
            with self.factory.connect() as connection:
                if identity is None:
                    row = connection.execute(
                        f"SELECT v.manifest_path,v.checksum,v.{key} FROM ops.{active} a "
                        f"JOIN analytics.{table} v ON a.{key}=v.{key} WHERE singleton"
                    ).fetchone()
                else:
                    row = connection.execute(
                        f"SELECT manifest_path,checksum,{key} FROM analytics.{table} WHERE {key}=?",
                        [identity],
                    ).fetchone()
        except duckdb.CatalogException as error:
            raise UnpublishedVersionError(f"No published {kind} version") from error
        if row is None:
            raise UnpublishedVersionError(f"No published {kind} version")
        path = confined_path(self.paths.workspace_root, row[0])
        if sha256_file(path) != row[1]:
            raise ValueError(f"{kind} manifest checksum mismatch")
        manifest: dict[str, Any] = json.loads(path.read_bytes())
        if manifest[key] != row[2]:
            raise ValueError(f"{kind} manifest identity differs from its registered version")
        if manifest.get("final_test_outcomes_computed") is not False:
            raise ValueError("Final-test outcome lock is missing or violated in the manifest")
        for item in manifest["files"]:
            if (
                sha256_file(confined_path(self.paths.workspace_root, item["path"]))
                != item["sha256"]
            ):
                raise ValueError(f"{kind} artifact checksum mismatch")
        if kind == "model":
            upstream = self.dataset_manifest(manifest["dataset_version"])
            upstream_path = (
                self.paths.artifacts / "events" / upstream["dataset_version"] / "manifest.json"
            )
            if sha256_file(upstream_path) != manifest["upstream_event_manifest_sha256"]:
                raise ValueError("Model upstream event manifest mismatch")
            if upstream["relationship_version"] != manifest["relationship_version"]:
                raise ValueError("Model upstream relationship version mismatch")
            nested = manifest["model_manifest"]
            if (
                nested["model_version"] != manifest["model_version"]
                or nested["dataset_version"] != manifest["dataset_version"]
                or nested["feature_schema_version"] != manifest["feature_schema"]["version"]
                or upstream["feature_schema"] != manifest["feature_schema"]
                or nested.get("final_test_locked") is not True
            ):
                raise ValueError("Model bundle schema, identity or final-test lock differs")
        else:
            upstream = RelationshipsRepository(self.paths).manifest(
                manifest["relationship_version"]
            )
            upstream_path = (
                self.paths.artifacts
                / "relationships"
                / upstream["relationship_version"]
                / "manifest.json"
            )
            if sha256_file(upstream_path) != manifest["upstream_relationship_manifest_sha256"]:
                raise ValueError("Event upstream relationship manifest mismatch")
        if upstream["data_snapshot_id"] != manifest["data_snapshot_id"] or bool(
            upstream["synthetic"]
        ) != bool(manifest["synthetic"]):
            raise ValueError("Upstream source identity or synthetic status differs")
        return manifest

    def manifest(self, model_version: str | None = None) -> dict[str, Any]:
        return self._manifest("model", model_version)

    def active_manifest(self) -> dict[str, Any]:
        return self.manifest()

    def dataset_manifest(self, dataset_version: str | None = None) -> dict[str, Any]:
        return self._manifest("event", dataset_version)

    def dataset_frames(self, dataset_version: str | None = None) -> dict[str, pd.DataFrame]:
        return _read_frames(self.paths, self.dataset_manifest(dataset_version))

    @staticmethod
    def _filter(
        frame: pd.DataFrame, pair_id: str | None, start: date | None, end: date | None
    ) -> pd.DataFrame:
        if start and end and start > end:
            raise ValueError("Query start follows end")
        if pair_id:
            frame = frame.loc[frame["pair_id"].eq(pair_id)]
        days = pd.to_datetime(frame["event_timestamp"], utc=True).dt.date
        if start:
            frame = frame.loc[days >= start]
        if end:
            frame = frame.loc[days.loc[frame.index] <= end]
        return frame.sort_values("event_timestamp").reset_index(drop=True)

    def events(
        self, pair_id: str | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        frame = self.dataset_frames()["divergence_events"]
        return self._filter(frame, pair_id, start, end)

    def predictions(
        self, pair_id: str | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        manifest = self.active_manifest()
        entry = next(item for item in manifest["files"] if item["dataset"] == "model_predictions")
        frame = pd.DataFrame(
            pq.read_table(confined_path(self.paths.workspace_root, entry["path"])).to_pandas()
        )
        return self._filter(frame, pair_id, start, end)

    def features(self, event_ids: list[str] | None = None) -> pd.DataFrame:
        try:
            dataset_version = str(self.active_manifest()["dataset_version"])
        except UnpublishedVersionError:
            dataset_version = None
        frame = self.dataset_frames(dataset_version)["event_features"]
        return frame if event_ids is None else frame.loc[frame["event_id"].isin(event_ids)].copy()

    def load_bundle(self) -> Any:
        from structural_break.ml.model import load_bundle

        manifest = self.active_manifest()
        return load_bundle(self.paths.artifacts / "models" / manifest["model_version"])

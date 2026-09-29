"""Phase 0 batch commands and a real deterministic storage acceptance job."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import pyarrow as pa
import pyarrow.csv as csv

from structural_break.common.logging import configure_logging, new_run_id
from structural_break.config.loader import config_hash, load_config
from structural_break.config.models import ProjectConfig, RuntimeSettings
from structural_break.config.paths import ProjectPaths, find_project_root
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import (
    ArtifactStore,
    DocumentStore,
    ParquetStore,
    sha256_file,
    write_bytes,
)
from structural_break.storage.registry import Registration, RunRegistry

FIXTURE_VERSION = "foundation-fixture-v1"


def git_revision(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def storage_smoke(
    paths: ProjectPaths, config: ProjectConfig, run_id: str, revision: str
) -> tuple[int, tuple[Registration, ...], Registration]:
    """Exercise production persistence helpers with tiny synthetic, non-research data."""
    fixtures = paths.project_root / "tests/fixtures"
    table = csv.read_csv(
        fixtures / "tiny_market/prices.csv",
        convert_options=csv.ConvertOptions(
            column_types={"date": pa.date32(), "ticker": pa.string(), "close": pa.float64()}
        ),
    )
    parquet = ParquetStore(paths)
    relative = "demo/foundation_prices.parquet"
    parquet_path = parquet.write(relative, table, schema=table.schema)
    if not parquet.read(relative, schema=table.schema).equals(table):
        raise ValueError("Parquet round trip changed fixture values")
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(parquet_path)]
        ).fetchone()
        if count is None or count[0] != table.num_rows:
            raise ValueError("DuckDB/Parquet fixture count mismatch")

    documents = DocumentStore(paths)
    content = (fixtures / "tiny_documents/filing.txt").read_bytes()
    document = documents.write("0", "foundation-fixture-v1", "filing.txt", content)
    if documents.read("0", "foundation-fixture-v1", "filing.txt") != content:
        raise ValueError("Document round trip changed bytes")
    dataset_manifest = {
        "dataset_version": FIXTURE_VERSION,
        "synthetic": True,
        "files": [
            {"path": file.relative_to(paths.workspace_root).as_posix(), "sha256": sha256_file(file)}
            for file in (parquet_path, document)
        ],
    }
    snapshot = write_bytes(
        paths.data_path(f"snapshots/{FIXTURE_VERSION}/manifest.json"),
        json.dumps(dataset_manifest, sort_keys=True, indent=2).encode(),
    )
    manifest: dict[str, object] = {
        "run_id": run_id,
        "git_commit": revision,
        "config_hash": config_hash(config),
        "config_snapshot": config.model_dump(mode="json"),
        "dataset_version": FIXTURE_VERSION,
        "pair_universe_version": config.universe.version,
        "feature_schema_version": config.ml.feature_schema_version,
        "model_version": "not-built",
        "prompt_graph_version": config.agents.prompt_graph_version,
        "policy_version": config.decision.version,
        "backtest_config_version": config.backtest.version,
        "created_at": datetime.now(UTC).isoformat(),
        "record_count": table.num_rows,
    }
    artifacts = ArtifactStore(paths)
    report = artifacts.write_json("manifests", run_id, "run.json", manifest)
    if json.loads(artifacts.read("manifests", run_id, "run.json")) != manifest:
        raise ValueError("Artifact round trip changed the manifest")
    return (
        table.num_rows,
        (Registration("manifests", run_id, report),),
        Registration("dataset", FIXTURE_VERSION, snapshot),
    )


def run_job(command: str, paths: ProjectPaths, config: ProjectConfig) -> str:
    run_id = new_run_id()
    logger = configure_logging()
    started = perf_counter()
    context = {
        "run_id": run_id,
        "job": command,
        "config_hash": config_hash(config),
        "dataset_version": FIXTURE_VERSION if command == "storage-smoke" else "none",
    }
    logger.info("Job started", extra={**context, "stage": "start", "status": "RUNNING"})
    registry = RunRegistry(DuckDBConnectionFactory(paths.database), paths.workspace_root)
    registered = False
    try:
        paths.create_directories()
        migrate(registry.factory, paths.migrations)
        revision = git_revision(paths.project_root)
        registry.start(run_id, command, config, revision, str(context["dataset_version"]))
        registered = True
        count = 0
        artifacts: tuple[Registration, ...] = ()
        dataset: Registration | None = None
        if command == "storage-smoke":
            count, artifacts, dataset = storage_smoke(paths, config, run_id, revision)
        registry.finish(
            run_id, status="SUCCESS", record_count=count, artifacts=artifacts, dataset=dataset
        )
        logger.info(
            "Job completed",
            extra={
                **context,
                "stage": "complete",
                "status": "SUCCESS",
                "record_count": count,
                "duration_seconds": perf_counter() - started,
            },
        )
        return run_id
    except Exception as error:
        if registered:
            registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        logger.error(
            "Job failed",
            extra={
                **context,
                "stage": "failed",
                "status": "FAILED",
                "error_type": type(error).__name__,
                "duration_seconds": perf_counter() - started,
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["check-config", "init-db", "migrate-db", "storage-smoke"]
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    args = parser.parse_args(argv)
    try:
        root = find_project_root(args.project_root)
        config = load_config(root / "configs")
        runtime = RuntimeSettings(_env_file=root / ".env")
        paths = ProjectPaths.resolve(root, args.workspace_root or runtime.workspace_root)
        if args.command == "check-config":
            print(json.dumps({"config_hash": config_hash(config), "status": "VALID"}))
        else:
            run_job(args.command, paths, config)
        return 0
    except Exception as error:
        # Do not echo Pydantic values, provider responses or credentials to logs.
        logger = configure_logging()
        logger.error(
            "Command failed; check configuration, paths and migration history",
            extra={"status": "FAILED", "error_type": type(error).__name__},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

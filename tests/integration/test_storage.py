import json
import shutil

import duckdb
import pyarrow as pa
import pytest

from structural_break.services.foundation import main, run_job
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import ArtifactStore, DocumentStore, ParquetStore, write_bytes
from structural_break.storage.registry import Registration, RunRegistry


def test_migrations_build_fresh_db_and_are_idempotent(paths):
    factory = DuckDBConnectionFactory(paths.database)
    assert migrate(factory, paths.migrations) == [1, 2]
    assert migrate(factory, paths.migrations) == []
    with factory.connect() as connection:
        schemas = {
            row[0]
            for row in connection.execute(
                "SELECT schema_name FROM information_schema.schemata"
            ).fetchall()
        }
        assert {"ref", "market", "analytics", "ops"} <= schemas
        assert connection.execute("SELECT count(*) FROM ops.schema_migrations").fetchone() == (2,)
        with pytest.raises(duckdb.InvalidInputException):
            connection.execute("CREATE TABLE analytics.should_fail (id INTEGER)")


def test_read_only_missing_database_is_not_created(paths):
    with pytest.raises(FileNotFoundError), DuckDBConnectionFactory(paths.database).connect():
        pass
    assert not paths.database.exists()


def test_checksum_and_missing_history_are_rejected(paths, tmp_path):
    migrations = tmp_path / "sql"
    shutil.copytree(paths.migrations, migrations)
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, migrations)
    original = (migrations / "001_schemas.sql").read_text()
    (migrations / "001_schemas.sql").write_text(original + "\n-- modified\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        migrate(factory, migrations)
    (migrations / "001_schemas.sql").write_text(original)
    (migrations / "002_ops_tables.sql").unlink()
    with pytest.raises(ValueError, match="checksum mismatch"):
        migrate(factory, migrations)


def test_migration_failure_rolls_back_entire_batch(paths, tmp_path):
    migrations = tmp_path / "sql"
    shutil.copytree(paths.migrations, migrations)
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, migrations)
    (migrations / "003_good.sql").write_text("CREATE TABLE analytics.temporary (id INTEGER);")
    (migrations / "004_bad.sql").write_text("THIS IS INVALID SQL;")
    with pytest.raises(duckdb.ParserException):
        migrate(factory, migrations)
    with factory.connect() as connection:
        assert connection.execute("SELECT count(*) FROM ops.schema_migrations").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'temporary'"
        ).fetchone() == (0,)


def test_migration_line_endings_are_portable(paths, tmp_path):
    migrations = tmp_path / "sql"
    shutil.copytree(paths.migrations, migrations)
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, migrations)
    for file in migrations.glob("*.sql"):
        file.write_bytes(file.read_text().replace("\n", "\r\n").encode())
    assert migrate(factory, migrations) == []


def test_stores_are_immutable_and_parquet_validated(paths):
    documents = DocumentStore(paths)
    file = documents.write("0", "fixture", "filing.txt", b"first")
    assert documents.write("0", "fixture", "filing.txt", b"first") == file
    with pytest.raises(FileExistsError):
        documents.write("0", "fixture", "filing.txt", b"changed")
    assert file.read_bytes() == b"first"
    with pytest.raises(ValueError):
        documents.write("0", "../escape", "filing.txt", b"bad")
    artifacts = ArtifactStore(paths)
    artifacts.write("models", "v1", "fixture.json", b"{}")
    with pytest.raises(FileExistsError):
        artifacts.write("models", "v1", "fixture.json", b"changed")
    with pytest.raises(ValueError):
        artifacts.write("models", "v1", "../bad", b"changed")
    table = pa.table({"value": [1, 2]})
    parquet = ParquetStore(paths)
    path = parquet.write("demo/test.parquet", table, schema=table.schema)
    with pytest.raises(ValueError, match="schema mismatch"):
        parquet.write("demo/test.parquet", pa.table({"wrong": [1]}), schema=table.schema)
    assert parquet.read("demo/test.parquet").equals(table)
    assert path.exists()
    required = pa.schema([pa.field("value", pa.int64(), nullable=False)])
    with pytest.raises(ValueError, match="Null values"):
        parquet.write(
            "demo/null.parquet",
            pa.Table.from_pydict({"value": [None]}, schema=required),
            schema=required,
        )
    assert not paths.data_path("demo/null.parquet").exists()
    changed = pa.table({"value": [3, 4]})
    with pytest.raises(FileExistsError):
        parquet.write("demo/test.parquet", changed, schema=table.schema)
    parquet.write("demo/test.parquet", changed, schema=table.schema, replace=True)
    assert parquet.read("demo/test.parquet").equals(changed)
    assert not list(paths.data.rglob(".pending-*"))


def test_full_fixture_job_and_repeat_preserve_dataset(paths, config):
    first = run_job("storage-smoke", paths, config)
    second = run_job("storage-smoke", paths, config)
    assert first != second
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        rows = connection.execute("SELECT status, record_count FROM ops.job_runs").fetchall()
        assert rows == [("SUCCESS", 4), ("SUCCESS", 4)]
        assert connection.execute("SELECT count(*) FROM ops.dataset_versions").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM ops.artifact_registry").fetchone() == (2,)
        snapshot = connection.execute("SELECT config_snapshot FROM ops.job_runs LIMIT 1").fetchone()
        assert json.loads(snapshot[0])["ml"]["final_test_locked"] is True
    manifest = json.loads((paths.artifacts / "manifests" / first / "run.json").read_text())
    assert manifest["model_version"] == "not-built"
    assert manifest["run_id"] == first
    assert manifest["record_count"] == 4


def test_failed_job_publishes_no_dataset_or_artifact(paths, config, monkeypatch):
    from structural_break.services import foundation

    def failure(*args, **kwargs):
        raise ValueError("fixture failure with sensitive values")

    monkeypatch.setattr(foundation, "storage_smoke", failure)
    with pytest.raises(ValueError):
        run_job("storage-smoke", paths, config)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT status, error_type FROM ops.job_runs").fetchone() == (
            "FAILED",
            "ValueError",
        )
        assert connection.execute("SELECT count(*) FROM ops.dataset_versions").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM ops.artifact_registry").fetchone() == (0,)


def test_registry_rejects_mutated_artifact_transactionally(paths, config):
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    registry = RunRegistry(factory, paths.workspace_root)
    file = write_bytes(paths.artifacts / "reports/v1/result.json", b"first")
    registration = Registration("reports", "v1", file)
    registry.start("first", "fixture", config, "fixture-revision", "fixture")
    registry.finish("first", status="SUCCESS", artifacts=(registration,))
    registry.start("second", "fixture", config, "fixture-revision", "fixture")
    file.write_bytes(b"changed behind store")
    with pytest.raises(ValueError, match="different content"):
        registry.finish("second", status="SUCCESS", artifacts=(registration,))
    with factory.connect() as connection:
        assert connection.execute(
            "SELECT status FROM ops.job_runs WHERE run_id = 'second'"
        ).fetchone() == ("RUNNING",)
    registry.finish("second", status="FAILED", error_type="ValueError")
    with pytest.raises(ValueError, match="RUNNING"):
        registry.finish("second", status="SUCCESS")


def test_cli_works_outside_repo_and_rejects_config_before_writes(paths, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "storage-smoke",
                "--project-root",
                str(paths.project_root),
                "--workspace-root",
                str(paths.workspace_root),
            ]
        )
        == 0
    )
    bad = tmp_path / "bad-project"
    shutil.copytree(paths.project_root / "configs", bad / "configs")
    (bad / "pyproject.toml").write_text("")
    (bad / "configs/ml.yaml").write_text("final_test_locked: false\n")
    assert main(["init-db", "--project-root", str(bad)]) == 1
    assert not (bad / "data").exists()

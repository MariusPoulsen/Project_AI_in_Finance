"""Export accepted outputs and restore their registrations in a fresh workspace.

Original scientific manifests remain byte-identical. A working snapshot omits
raw SEC bodies and per-event text checkpoints; it cannot verify sources or fit
replacement canonical models. Import does not mint a new scientific acceptance.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.primary import (
    load_primary,
    read_json,
    registered_manifest,
)
from structural_break.research.protocol import canonical_bytes, identity
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import sha256_file

SCHEMA = "research-team-working-snapshot-v1"
TABLES = ("ops.job_runs", "analytics.research_versions", "ops.artifact_registry")
DATE_COLUMNS = {
    "event_date",
    "event_timestamp",
    "trading_date",
    "estimation_date",
    "resolution_date",
}


def _development_file(path: Path, end: str) -> None:
    if path.suffix != ".parquet":
        return
    columns = sorted(DATE_COLUMNS.intersection(pq.read_schema(path).names))
    if columns:
        rows = pd.read_parquet(path, columns=columns)
        cutoff = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        for column in columns:
            values = pd.to_datetime(rows[column], utc=True, errors="raise")
            if values.dropna().ge(cutoff).any():
                raise ValueError(
                    "A working snapshot cannot include final-test observations/outcomes"
                )


def _portable_name(name: str) -> str:
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        raise ValueError("Snapshot paths must be portable relative paths")
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError("Snapshot path traverses outside its workspace")
    if name.casefold().endswith(".env") or any(
        part.casefold() in {"cache", "events", ".env", ".venv"} for part in name.split("/")
    ):
        raise ValueError(
            "Raw archives, event checkpoints and credentials do not belong in a working snapshot"
        )
    if not name.startswith(
        ("artifacts/", "intelligence/", "market/", "universe/", "sec_metadata/")
    ):
        raise ValueError("Unsupported working snapshot payload")
    return name


def _inventory(paths: ProjectPaths, primary: dict[str, Any]) -> dict[str, str]:
    files: dict[str, str] = {}
    end = primary["identity_inputs"]["protocol"]["development_end"]

    def add(path: Path, expected: str | None = None) -> None:
        name = _portable_name(path.relative_to(paths.workspace_root).as_posix())
        actual = sha256_file(path)
        if expected is not None and actual != expected:
            raise ValueError("Working snapshot source checksum differs")
        _development_file(path, end)
        files[name] = actual

    def manifest_files(path: Path, *, include_raw: bool = True) -> None:
        manifest = read_json(path)
        add(path)
        entries = manifest["files"]
        if isinstance(entries, dict):
            for name, digest in entries.items():
                if not include_raw and name.startswith("raw/"):
                    continue
                add(confined_path(path.parent, name), digest)
        else:
            for item in entries:
                add(confined_path(path.parent, item["path"]), item["sha256"])

    for name, digest in primary["bindings"].items():
        add(confined_path(paths.workspace_root, name), digest)
    directory = paths.artifacts / "research" / primary["primary_version"]
    add(directory / "manifest.json")
    add(directory / "verification_receipt.json", primary["verification_receipt_sha256"])
    add(directory / "hosted_ci_gate.json")
    registry_path, registry = registered_manifest(
        paths, primary["identity_inputs"]["registry_version"], "registry"
    )
    if registry.get("final_test_read") is not False:
        raise ValueError("Registry final-test lock is unavailable")
    manifest_files(registry_path)
    add(registry_path.parent / "funnel.json", registry["funnel_sha256"])
    for parent in registry["inputs"]:
        manifest_files(confined_path(paths.workspace_root, parent["path"]), include_raw=False)
    for item in registry["pair_manifests"]:
        path = confined_path(registry_path.parent / "pairs", item["pair_id"] + "/manifest.json")
        add(path, item["sha256"])
        pair = read_json(path)
        if pair["pair_id"] != item["pair_id"]:
            raise ValueError("Frozen pair identity differs")
        manifest_files(path)
    return dict(sorted(files.items()))


def _registrations(paths: ProjectPaths, primary: dict[str, Any]) -> dict[str, Any]:
    versions = [primary["primary_version"], primary["identity_inputs"]["registry_version"]]
    versions += [
        row["research_version"] for row in primary["identity_inputs"]["evaluations"].values()
    ]
    placeholders = ",".join("?" for _ in versions)
    result: dict[str, Any] = {}
    with DuckDBConnectionFactory(paths.database, coordinated=True).connect() as connection:
        selections = {
            "analytics.research_versions": (f"research_version IN ({placeholders})", versions),
            "ops.job_runs": (
                "run_id IN (SELECT run_id FROM analytics.research_versions "
                f"WHERE research_version IN ({placeholders}))",
                versions,
            ),
            "ops.artifact_registry": (f"version IN ({placeholders})", versions),
        }
        for table in TABLES:
            predicate, parameters = selections[table]
            query = connection.execute(f"SELECT * FROM {table} WHERE {predicate}", parameters)
            columns = [row[0] for row in query.description]
            rows = [list(row) for row in query.fetchall()]
            result[table] = {
                "columns": columns,
                "rows": [
                    [
                        value.isoformat() if isinstance(value, (date, datetime)) else value
                        for value in row
                    ]
                    for row in rows
                ],
            }
    if len(result["analytics.research_versions"]["rows"]) != len(versions):
        raise ValueError("Every accepted research generation must be registered")
    runs = result["ops.job_runs"]
    if not runs["rows"] or any(
        row[runs["columns"].index("status")] != "SUCCESS" for row in runs["rows"]
    ):
        raise ValueError("Working snapshot requires successful original registrations")
    return result


def export_snapshot(
    paths: ProjectPaths, output: Path, *, primary_version: str | None = None
) -> dict[str, Any]:
    """Read accepted data only; never fit, replay raw sources or publish research."""
    output = output.resolve()
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        raise FileExistsError("Snapshot export must use a new filename")
    if output.is_relative_to(paths.workspace_root):
        raise ValueError("Export the shareable bundle outside the canonical workspace")
    primary = load_primary(paths, primary_version)
    protocol = primary["identity_inputs"]["protocol"]
    if protocol["final_test_locked"] is not True or protocol["development_end"] > "2023-12-31":
        raise ValueError("Working snapshots retain the locked development-only protocol")
    files = _inventory(paths, primary)
    registrations = canonical_bytes(_registrations(paths, primary))
    metadata = {
        "schema_version": SCHEMA,
        "primary_version": primary["primary_version"],
        "registry_version": primary["identity_inputs"]["registry_version"],
        "protocol": protocol,
        "capabilities": ["app", "analysis", "existing_event_prediction", "backtest_inputs"],
        "raw_sec_archive_included": False,
        "raw_market_archive_included": False,
        "event_text_checkpoints_included": False,
        "canonical_retraining_supported": False,
        "source_reverification_supported": False,
        "final_test_unlocked": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "registrations_sha256": hashlib.sha256(registrations).hexdigest(),
        "files": {
            name: {
                "sha256": digest,
                "bytes": confined_path(paths.workspace_root, name).stat().st_size,
            }
            for name, digest in files.items()
        },
    }
    metadata["snapshot_version"] = "team_snapshot_" + identity(metadata)[:24]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        with zipfile.ZipFile(
            stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            archive.writestr("snapshot.json", canonical_bytes(metadata))
            archive.writestr("registrations.json", registrations)
            for name, digest in files.items():
                path = confined_path(paths.workspace_root, name)
                archive.write(path, "workspace/" + name)
                if sha256_file(path) != digest:
                    raise ValueError("Source bytes changed during snapshot export")
    load_primary(paths, primary["primary_version"])
    digest = sha256_file(output)
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "\n", encoding="ascii")
    return {
        "snapshot_version": metadata["snapshot_version"],
        "primary_version": primary["primary_version"],
        "archive": str(output),
        "sha256": digest,
        "archive_bytes": output.stat().st_size,
        "files": len(files),
    }


def _restore_database(
    paths: ProjectPaths, metadata: dict[str, Any], registrations: dict[str, Any]
) -> None:
    if set(registrations) != set(TABLES):
        raise ValueError("Unexpected portable registration tables")
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    with factory.connect(read_only=False) as connection:
        connection.execute("BEGIN TRANSACTION")
        try:
            for table in TABLES:
                expected_columns = [
                    row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()
                ]
                payload = registrations[table]
                if payload["columns"] != expected_columns:
                    raise ValueError(
                        "Portable registration schema differs from the installed project"
                    )
                values = ",".join("?" for _ in expected_columns)
                for row in payload["rows"]:
                    if len(row) != len(expected_columns):
                        raise ValueError("Malformed portable registration")
                    connection.execute(f"INSERT INTO {table} VALUES ({values})", row)
            connection.execute(
                "INSERT INTO ops.active_primary_research VALUES (true, ?)",
                [metadata["primary_version"]],
            )
            rows = connection.execute(
                "SELECT research_version, manifest_path FROM analytics.research_versions"
            ).fetchall()
            for version, relative in rows:
                path = confined_path(paths.workspace_root, relative)
                manifest = read_json(path)
                if manifest["research_version"] != version:
                    raise ValueError("Imported registration identity differs")
                for item in manifest.get("files", []):
                    name = item["name"]
                    if re.fullmatch(r"[a-zA-Z0-9_]+", name) is None:
                        raise ValueError("Invalid portable research view name")
                    view = f"research_{manifest['stage']}_{name}_{version.rsplit('_', 1)[-1]}"
                    target = str(confined_path(path.parent, item["path"])).replace("'", "''")
                    connection.execute(
                        f"CREATE VIEW analytics.{view} AS SELECT * FROM read_parquet('{target}')"
                    )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def import_snapshot(
    project_root: Path, archive_path: Path, workspace: Path, *, expected_sha256: str
) -> dict[str, Any]:
    """Verify the externally supplied archive hash before restoring any data."""
    if (
        re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        or sha256_file(archive_path) != expected_sha256
    ):
        raise ValueError("Snapshot archive SHA-256 differs; use the checksum provided by its owner")
    workspace = workspace.resolve()
    if workspace.exists():
        receipt = (
            read_json(workspace / "team_snapshot.json")
            if (workspace / "team_snapshot.json").is_file()
            else {}
        )
        if receipt.get("archive_sha256") != expected_sha256:
            raise FileExistsError(
                "Choose a new workspace; existing research data is never overwritten"
            )
        check_snapshot(ProjectPaths.resolve(project_root, workspace))
        _relocate_views(ProjectPaths.resolve(project_root, workspace))
        return {
            "status": "ALREADY_IMPORTED",
            "workspace": str(workspace),
            "primary_version": receipt["primary_version"],
        }
    workspace.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="team-import-", dir=workspace.parent) as temporary:
        stage = Path(temporary).resolve()
        if not stage.is_relative_to(workspace.parent):
            raise ValueError("Import staging escaped its parent")
        with zipfile.ZipFile(archive_path) as archive:
            metadata = json.loads(archive.read("snapshot.json"))
            supplied_version = metadata.pop("snapshot_version")
            if supplied_version != "team_snapshot_" + identity(metadata)[:24]:
                raise ValueError("Snapshot identity differs")
            metadata["snapshot_version"] = supplied_version
            if (
                metadata["schema_version"] != SCHEMA
                or metadata["final_test_unlocked"] is not False
                or metadata["protocol"]["final_test_locked"] is not True
                or metadata["protocol"]["development_end"] > "2023-12-31"
            ):
                raise ValueError("Import requires a locked development working snapshot")
            names = archive.namelist()
            expected_names = {
                "snapshot.json",
                "registrations.json",
                *("workspace/" + _portable_name(name) for name in metadata["files"]),
            }
            if len(names) != len(set(names)) or set(names) != expected_names:
                raise ValueError("Archive includes missing, duplicate or unexpected files")
            registrations_bytes = archive.read("registrations.json")
            if hashlib.sha256(registrations_bytes).hexdigest() != metadata["registrations_sha256"]:
                raise ValueError("Portable registration checksum differs")
            payload_root = stage / "workspace"
            payload_root.mkdir()
            for name, item in metadata["files"].items():
                info = archive.getinfo("workspace/" + name)
                if info.file_size != item["bytes"]:
                    raise ValueError("Snapshot file size differs")
                target = confined_path(payload_root, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
                if sha256_file(target) != item["sha256"]:
                    raise ValueError("Snapshot payload checksum differs")
                _development_file(target, metadata["protocol"]["development_end"])
        paths = ProjectPaths.resolve(project_root, payload_root)
        _restore_database(paths, metadata, json.loads(registrations_bytes))
        load_primary(paths, metadata["primary_version"])
        receipt = {
            **metadata,
            "archive_sha256": expected_sha256,
            "imported_at_utc": datetime.now(UTC).isoformat(),
        }
        (payload_root / "team_snapshot.json").write_bytes(canonical_bytes(receipt))
        payload_root.rename(workspace)
    # Recreate absolute Parquet view paths after the atomic relocation.
    _relocate_views(ProjectPaths.resolve(project_root, workspace))
    check_snapshot(ProjectPaths.resolve(project_root, workspace))
    return {
        "status": "IMPORTED",
        "workspace": str(workspace),
        "primary_version": metadata["primary_version"],
    }


def _relocate_views(paths: ProjectPaths) -> None:
    with DuckDBConnectionFactory(paths.database).connect(read_only=False) as connection:
        rows = connection.execute(
            "SELECT research_version, manifest_path FROM analytics.research_versions"
        ).fetchall()
        for version, relative in rows:
            path = confined_path(paths.workspace_root, relative)
            manifest = read_json(path)
            for item in manifest.get("files", []):
                name = item["name"]
                if re.fullmatch(r"[a-zA-Z0-9_]+", name) is None:
                    raise ValueError("Invalid portable research view")
                view = f"research_{manifest['stage']}_{name}_{version.rsplit('_', 1)[-1]}"
                target = str(confined_path(path.parent, item["path"])).replace("'", "''")
                connection.execute(
                    f"CREATE OR REPLACE VIEW analytics.{view} "
                    f"AS SELECT * FROM read_parquet('{target}')"
                )


def check_snapshot(paths: ProjectPaths) -> dict[str, Any]:
    receipt = read_json(paths.workspace_root / "team_snapshot.json")
    if receipt["schema_version"] != SCHEMA or receipt["final_test_unlocked"] is not False:
        raise ValueError("A locked team working snapshot is required")
    original = {
        key: value
        for key, value in receipt.items()
        if key not in {"snapshot_version", "archive_sha256", "imported_at_utc"}
    }
    if receipt["snapshot_version"] != "team_snapshot_" + identity(original)[:24]:
        raise ValueError("Imported snapshot inventory identity differs")
    for name, item in receipt["files"].items():
        if sha256_file(confined_path(paths.workspace_root, _portable_name(name))) != item["sha256"]:
            raise ValueError("Imported working data checksum differs")
    primary = load_primary(paths, receipt["primary_version"])
    return {
        "primary_version": primary["primary_version"],
        "snapshot_version": receipt["snapshot_version"],
        "workspace": str(paths.workspace_root),
        "files_checked": len(receipt["files"]),
        "final_test_unlocked": False,
    }

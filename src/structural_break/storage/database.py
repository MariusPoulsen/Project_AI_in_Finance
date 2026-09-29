"""Explicit writer connections and transactional, checksum-checked SQL migrations."""

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class DuckDBConnectionFactory:
    path: Path

    @contextmanager
    def connect(self, *, read_only: bool = True) -> Iterator[duckdb.DuckDBPyConnection]:
        if read_only and not self.path.is_file():
            raise FileNotFoundError("Database is not initialized; run init-db first")
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.path), read_only=read_only)
        try:
            connection.execute("SET TimeZone = 'UTC'")
            yield connection
        finally:
            connection.close()


def migrate(factory: DuckDBConnectionFactory, directory: Path) -> list[int]:
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise ValueError("No SQL migrations found")
    migrations: dict[int, tuple[str, str, str]] = {}
    for file in files:
        match = re.fullmatch(r"(\d{3})_[a-z0-9_]+\.sql", file.name)
        if match is None:
            raise ValueError(f"Invalid migration filename: {file.name}")
        version = int(match[1])
        if version in migrations:
            raise ValueError(f"Duplicate migration number: {version}")
        # Normalize line endings so Windows checkouts share Linux checksums.
        sql = file.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        migrations[version] = (file.name, checksum, sql)
    if sorted(migrations) != list(range(1, len(migrations) + 1)):
        raise ValueError("Migration numbers must be contiguous starting at 001")

    applied_now = []
    with factory.connect(read_only=False) as connection:
        connection.execute("BEGIN TRANSACTION")
        try:
            # Bootstrap only the ledger needed to execute the versioned schema.
            connection.execute("CREATE SCHEMA IF NOT EXISTS ops")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ops.schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    checksum VARCHAR NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
                )
            """)
            rows = connection.execute(
                "SELECT version, name, checksum FROM ops.schema_migrations ORDER BY version"
            ).fetchall()
            if [row[0] for row in rows] != list(range(1, len(rows) + 1)):
                raise ValueError("Applied migration history is not a contiguous prefix")
            for version, name, checksum in rows:
                if version not in migrations or migrations[version][:2] != (name, checksum):
                    raise ValueError(f"Migration history/checksum mismatch: {version}")
            for version, (name, checksum, sql) in sorted(migrations.items()):
                if version <= len(rows):
                    continue
                connection.execute(sql)
                connection.execute(
                    "INSERT INTO ops.schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                    [version, name, checksum],
                )
                applied_now.append(version)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return applied_now

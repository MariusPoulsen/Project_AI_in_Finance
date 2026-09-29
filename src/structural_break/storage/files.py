"""Validated paths, atomic publication and immutable versioned file stores."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pyarrow as pa
import pyarrow.parquet as pq

from structural_break.config.paths import ProjectPaths, confined_path


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_bytes(path: Path, content: bytes, *, replace: bool = False) -> Path:
    """Publish a complete file; identical immutable reruns are idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temp, path)
        else:
            try:
                # Same-filesystem hard link is atomic and cannot replace a winner.
                os.link(temp, path)
            except FileExistsError:
                if sha256_file(path) != hashlib.sha256(content).hexdigest():
                    raise FileExistsError(f"Immutable file already exists: {path}") from None
        return path
    finally:
        temp.unlink(missing_ok=True)


def segment(value: str) -> str:
    if not value or value in {".", ".."} or any(c in value for c in "/\\:"):
        raise ValueError("Expected one portable path segment")
    return value


@dataclass(frozen=True)
class ParquetStore:
    paths: ProjectPaths

    def _path(self, relative: str) -> Path:
        path = self.paths.data_path(relative)
        if path.suffix != ".parquet":
            raise ValueError("Parquet filename must end in .parquet")
        return path

    def write(
        self, relative: str, table: pa.Table, *, schema: pa.Schema, replace: bool = False
    ) -> Path:
        if not table.schema.equals(schema, check_metadata=False):
            raise ValueError("Parquet schema mismatch")
        table.validate(full=True)
        for field in schema:
            if not field.nullable and table.column(field.name).null_count:
                raise ValueError(f"Null values in required column: {field.name}")
        output = pa.BufferOutputStream()
        pq.write_table(table, output, compression="zstd")
        return write_bytes(self._path(relative), output.getvalue().to_pybytes(), replace=replace)

    def read(self, relative: str, *, schema: pa.Schema | None = None) -> pa.Table:
        table = pq.read_table(self._path(relative))
        if schema is not None and not table.schema.equals(schema, check_metadata=False):
            raise ValueError("Stored Parquet schema mismatch")
        return table


@dataclass(frozen=True)
class DocumentStore:
    paths: ProjectPaths

    def path(self, cik: str, accession: str, filename: str) -> Path:
        if not cik.isdigit() or len(cik) > 10:
            raise ValueError("CIK must contain at most ten digits")
        return confined_path(
            self.paths.data / "raw/sec/filings",
            f"{cik.zfill(10)}/{segment(accession)}/{segment(filename)}",
        )

    def write(self, cik: str, accession: str, filename: str, content: bytes) -> Path:
        return write_bytes(self.path(cik, accession, filename), content)

    def read(self, cik: str, accession: str, filename: str) -> bytes:
        return self.path(cik, accession, filename).read_bytes()


ArtifactKind = Literal["models", "calibrators", "shap", "manifests", "reports", "mlflow"]


@dataclass(frozen=True)
class ArtifactStore:
    paths: ProjectPaths

    def path(self, kind: ArtifactKind, version: str, filename: str) -> Path:
        if kind not in {"models", "calibrators", "shap", "manifests", "reports", "mlflow"}:
            raise ValueError("Unknown artifact kind")
        return confined_path(self.paths.artifacts, f"{kind}/{segment(version)}/{segment(filename)}")

    def write(self, kind: ArtifactKind, version: str, filename: str, content: bytes) -> Path:
        return write_bytes(self.path(kind, version, filename), content)

    def read(self, kind: ArtifactKind, version: str, filename: str) -> bytes:
        return self.path(kind, version, filename).read_bytes()

    def write_json(
        self, kind: ArtifactKind, version: str, filename: str, payload: dict[str, object]
    ) -> Path:
        content = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode()
        return self.write(kind, version, filename, content)

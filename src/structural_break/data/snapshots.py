"""Immutable source inventories, integrity checks and portable frozen Parquet files."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.http import FetchedResponse
from structural_break.storage.files import ParquetStore, sha256_file, write_bytes


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode()


def frame_table(frame: pd.DataFrame) -> pa.Table:
    return pa.Table.from_pandas(frame, preserve_index=False).replace_schema_metadata(None)


def date_coverage(frame: pd.DataFrame) -> dict[str, dict[str, str | int | None]]:
    result: dict[str, dict[str, str | int | None]] = {}
    for name in ("trading_date", "filing_date", "acceptance_datetime_utc"):
        if name in frame:
            values = frame[name].dropna()
            result[name] = {
                "min": values.min().isoformat() if not values.empty else None,
                "max": values.max().isoformat() if not values.empty else None,
                "null_rows": int(frame[name].isna().sum()),
            }
    return result


@dataclass
class RawInventory:
    paths: ProjectPaths
    snapshot_id: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def capture_bytes(
        self,
        relative: str,
        response: FetchedResponse,
        *,
        role: str,
        provider: str,
        source_snapshot_id: str,
        library_version: str = "stdlib",
        identity: str = "",
        parameters: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        path = write_bytes(self.paths.data_path(relative), response.body)
        return self._record(
            path,
            role,
            provider,
            source_snapshot_id,
            response.retrieved_at,
            response.url,
            response.status_code,
            library_version,
            identity,
            parameters,
        )

    def capture_frame(
        self,
        relative: str,
        frame: pd.DataFrame,
        *,
        role: str,
        provider: str,
        source_snapshot_id: str,
        retrieved_at: datetime,
        source_url: str,
        library_version: str,
        identity: str = "",
        parameters: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        table = frame_table(frame)
        path = ParquetStore(self.paths).write(relative, table, schema=table.schema)
        return self._record(
            path,
            role,
            provider,
            source_snapshot_id,
            retrieved_at,
            source_url,
            None,
            library_version,
            identity,
            parameters,
            row_count=len(frame),
        )

    def _record(
        self,
        path: Path,
        role: str,
        provider: str,
        source_snapshot_id: str,
        retrieved_at: datetime,
        source_url: str,
        status: int | None,
        library_version: str,
        identity: str,
        parameters: dict[str, object] | None,
        row_count: int | None = None,
    ) -> dict[str, Any]:
        if retrieved_at.tzinfo is None:
            raise ValueError("Source retrieval timestamp must be timezone aware")
        entry: dict[str, Any] = {
            "role": role,
            "identity": identity,
            "source_provider": provider,
            "source_snapshot_id": source_snapshot_id,
            "data_snapshot_id": self.snapshot_id,
            "raw_file_path": path.relative_to(self.paths.workspace_root).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "source_url": source_url,
            "retrieved_at_utc": retrieved_at.astimezone(UTC).isoformat(),
            "http_status": None if provider == "MANUAL_REFERENCE" else status,
            "result_status": "SUCCESS",
            "library_version": library_version,
            "parameters": parameters or {},
            "row_count": row_count,
        }
        # Every raw download has an adjacent source manifest, separate from its bytes.
        sidecar = path.with_name(path.name + ".source.json")
        write_bytes(sidecar, json_bytes(entry))
        self.entries.append(entry)
        return entry

    def freeze(self, metadata: dict[str, object]) -> Path:
        return write_bytes(
            self.paths.data_path(f"snapshots/{self.snapshot_id}/raw_manifest.json"),
            json_bytes({**metadata, "data_snapshot_id": self.snapshot_id, "sources": self.entries}),
        )


def lineage(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        key: datetime.fromisoformat(value) if key == "retrieved_at_utc" else value
        for key, value in entry.items()
        if key
        in {
            "source_provider",
            "source_snapshot_id",
            "data_snapshot_id",
            "raw_file_path",
            "sha256",
            "source_url",
            "retrieved_at_utc",
            "library_version",
        }
    }


def verify_sources(paths: ProjectPaths, manifest: dict[str, Any]) -> None:
    entries = manifest.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Snapshot has no raw-source inventory")
    for entry in entries:
        path = confined_path(paths.workspace_root, entry["raw_file_path"])
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Raw source checksum mismatch: {entry['raw_file_path']}")
        sidecar = json.loads(path.with_name(path.name + ".source.json").read_bytes())
        if sidecar != entry:
            raise ValueError("Raw source manifest changed")


def freeze_frames(
    paths: ProjectPaths, snapshot_id: str, frames: dict[str, pd.DataFrame]
) -> list[dict[str, Any]]:
    result = []
    store = ParquetStore(paths)
    for relative, frame in sorted(frames.items()):
        table = frame_table(frame)
        frozen = f"snapshots/{snapshot_id}/{relative}"
        path = store.write(frozen, table, schema=table.schema)
        result.append(
            {
                "dataset": relative,
                "path": path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(path),
                "rows": len(frame),
                "schema": str(table.schema),
                "date_coverage": date_coverage(frame),
            }
        )
    return result


def verify_snapshot(paths: ProjectPaths, manifest: dict[str, Any]) -> None:
    if "raw_manifest_path" in manifest:
        raw_manifest = confined_path(paths.workspace_root, manifest["raw_manifest_path"])
        if sha256_file(raw_manifest) != manifest["raw_manifest_sha256"]:
            raise ValueError("Raw inventory manifest checksum mismatch")
    verify_sources(paths, manifest)
    for entry in manifest["curated_files"]:
        path = confined_path(paths.workspace_root, entry["path"])
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Frozen dataset checksum mismatch: {entry['path']}")
        if pq.read_metadata(path).num_rows != entry["rows"]:
            raise ValueError("Frozen dataset row count mismatch")


def content_identity(payload: object) -> str:
    return hashlib.sha256(json_bytes(payload)).hexdigest()

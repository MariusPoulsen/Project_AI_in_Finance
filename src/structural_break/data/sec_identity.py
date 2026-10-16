"""Reviewed dated SEC identity recovery without mutating frozen P1 sources.

ExxonMobil's July 2026 successor CIK cannot stand in for its predecessor in
2014--2025. This is an administrative source-route correction, not a predictor.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pandas as pd

from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.http import FetchedResponse
from structural_break.data.sec import (
    fetch_submissions,
    normalize_filings,
    parse_json_response,
)
from structural_break.data.snapshots import (
    RawInventory,
    frame_table,
    json_bytes,
    lineage,
    verify_sources,
)
from structural_break.storage.files import ParquetStore, segment, sha256_file, write_bytes

IDENTITY_MAPPING_VERSION = "sec-identity-xom-20260701-v1"
PREDECESSOR_CIK = "0000034088"
SUCCESSOR_CIK = "0002115436"
EFFECTIVE_DATE = date(2026, 7, 1)
IDENTITY_SOURCES = (
    "https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm",
    "https://www.sec.gov/Archives/edgar/data/34088/000119312526291986/d70995d8k.htm",
)


def apply_reviewed_sec_identities(index: pd.DataFrame) -> pd.DataFrame:
    """Copy the index and stamp the reviewed predecessor/successor date bounds."""
    required = {"security_id", "cik"}
    if not required.issubset(index.columns):
        raise ValueError("Dated SEC identity resolution needs security_id and cik")
    result = index.copy()
    for name in ("identity_valid_from", "identity_valid_to", "identity_mapping_version"):
        if name not in result:
            result[name] = pd.Series(None, index=result.index, dtype="object")
    issuer = result["security_id"].eq("US:XOM")
    for cik, start, end in (
        (PREDECESSOR_CIK, None, EFFECTIVE_DATE.isoformat()),
        (SUCCESSOR_CIK, EFFECTIVE_DATE.isoformat(), None),
    ):
        mask = issuer & result["cik"].eq(cik)
        result.loc[mask, "identity_valid_from"] = start
        result.loc[mask, "identity_valid_to"] = end
        result.loc[mask, "identity_mapping_version"] = IDENTITY_MAPPING_VERSION
    unexpected = issuer & ~result["cik"].isin([PREDECESSOR_CIK, SUCCESSOR_CIK])
    if unexpected.any():
        raise ValueError("XOM SEC identity requires a new reviewed mapping for an unknown CIK")
    return result


def recover_historical_sec_index(
    paths: ProjectPaths,
    config: ProjectConfig,
    get: Callable[[str], FetchedResponse],
    *,
    parent_snapshot_id: str,
    offline: bool = False,
    capture_id: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Capture/cache a supplemental predecessor index under a new source identity.

    A matching capture replays stored bytes, including a partially captured
    metadata history. Explicit ``capture_id`` chooses a separate immutable
    generation; ordinary reruns cannot revise the frozen input or this capture.
    """
    if not any("XOM" in (pair.leg_a, pair.leg_b) for pair in config.universe.pairs):
        raise ValueError("Reviewed XOM recovery is only available for a universe containing XOM")
    segment(parent_snapshot_id)
    if capture_id is not None:
        segment(capture_id)
    start, end = config.data.start, min(config.data.end, date(2026, 6, 30))
    if start > end:
        raise ValueError("The research range contains no reviewed predecessor interval")
    identity = {
        "identity_mapping_version": IDENTITY_MAPPING_VERSION,
        "parent_snapshot_id": parent_snapshot_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "capture_id": capture_id,
    }
    source_id = "phase4_identity_" + hashlib.sha256(json_bytes(identity)).hexdigest()[:24]
    curated_relative = f"curated/evidence/identity_sources/{source_id}/sec_filing_index.parquet"
    manifest_relative = f"curated/evidence/identity_sources/{source_id}/manifest.json"
    manifest_path = paths.data_path(manifest_relative)
    if manifest_path.is_file():
        manifest: dict[str, Any] = json.loads(manifest_path.read_bytes())
        if manifest.get("identity") != identity:
            raise ValueError("SEC identity recovery manifest does not match the requested source")
        verify_sources(paths, manifest)
        for item in manifest["files"]:
            if sha256_file(confined_path(paths.workspace_root, item["path"])) != item["sha256"]:
                raise ValueError("SEC identity recovery artifact checksum mismatch")
        frame = ParquetStore(paths).read(curated_relative).to_pandas()
        return frame, manifest
    if offline:
        raise FileNotFoundError("No complete supplemental SEC identity capture exists offline")
    inventory = RawInventory(paths, source_id)

    def capture(url: str) -> FetchedResponse:
        filename = url.rsplit("/", 1)[-1]
        if filename == f"CIK{PREDECESSOR_CIK}.json":
            relative = f"raw/sec/submissions/{PREDECESSOR_CIK}/{source_id}.json"
        else:
            relative = (
                f"raw/sec/submissions/{PREDECESSOR_CIK}/history/{source_id}_{segment(filename)}"
            )
        target = paths.data_path(relative)
        sidecar = target.with_name(target.name + ".source.json")
        if target.is_file() and sidecar.is_file():
            entry = json.loads(sidecar.read_bytes())
            if (
                entry["sha256"] != sha256_file(target)
                or entry["source_url"] != url
                or entry["source_snapshot_id"] != source_id
            ):
                raise ValueError("Cached supplemental SEC source changed")
            inventory.entries.append(entry)
            return FetchedResponse(
                target.read_bytes(),
                url,
                entry["http_status"],
                datetime.fromisoformat(entry["retrieved_at_utc"]),
            )
        response = get(url)
        parse_json_response(response)
        inventory.capture_bytes(
            relative,
            response,
            role="sec_identity_submissions",
            provider="SEC_EDGAR",
            source_snapshot_id=source_id,
            identity=PREDECESSOR_CIK,
            parameters={
                "parent_snapshot_id": parent_snapshot_id,
                "mapping_version": IDENTITY_MAPPING_VERSION,
            },
        )
        return response

    fetched = fetch_submissions([PREDECESSOR_CIK], start, end, capture)
    entries = {entry["source_url"]: entry for entry in inventory.entries}
    sources = [
        (cik, parse_json_response(response), lineage(entries[response.url]))
        for cik, _, response in fetched
    ]
    frame = normalize_filings(sources, start, end)
    frame["security_id"] = "US:XOM"
    frame["ticker"] = "XOM"
    frame["parent_snapshot_id"] = parent_snapshot_id
    frame = apply_reviewed_sec_identities(frame)
    table = frame_table(frame)
    curated_path = ParquetStore(paths).write(curated_relative, table, schema=table.schema)
    files = [
        {
            "path": curated_path.relative_to(paths.workspace_root).as_posix(),
            "sha256": sha256_file(curated_path),
        }
    ]
    for entry in inventory.entries:
        raw = confined_path(paths.workspace_root, entry["raw_file_path"])
        files.extend(
            [
                {"path": entry["raw_file_path"], "sha256": entry["sha256"]},
                {
                    "path": raw.with_name(raw.name + ".source.json")
                    .relative_to(paths.workspace_root)
                    .as_posix(),
                    "sha256": sha256_file(raw.with_name(raw.name + ".source.json")),
                },
            ]
        )
    manifest = {
        "source_capture_id": source_id,
        "identity": identity,
        "identity_mapping_version": IDENTITY_MAPPING_VERSION,
        "reviewed_mapping": {
            "security_id": "US:XOM",
            "predecessor_cik": PREDECESSOR_CIK,
            "successor_cik": SUCCESSOR_CIK,
            "effective_date": EFFECTIVE_DATE.isoformat(),
            "official_review_sources": list(IDENTITY_SOURCES),
            "usage": "ADMINISTRATIVE_SOURCE_IDENTITY_ONLY",
        },
        "parent_snapshot_id": parent_snapshot_id,
        "curated_filing_index_path": curated_path.relative_to(paths.workspace_root).as_posix(),
        "row_count": len(frame),
        "sources": inventory.entries,
        "files": files,
        "manifest_path": manifest_path.relative_to(paths.workspace_root).as_posix(),
    }
    write_bytes(manifest_path, json_bytes(manifest))
    return ParquetStore(paths).read(curated_relative).to_pandas(), manifest

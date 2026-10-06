"""Immutable source inventories and frozen publication integrity, without APIs."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import pytest

from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse
from structural_break.data.snapshots import (
    RawInventory,
    content_identity,
    date_coverage,
    frame_table,
    freeze_frames,
    json_bytes,
    lineage,
    verify_snapshot,
    verify_sources,
)
from structural_break.storage.files import sha256_file
from structural_break.storage.publication import canonical_aliases


def captured_inventory(paths: ProjectPaths) -> tuple[RawInventory, dict[str, Any]]:
    inventory = RawInventory(paths, "snapshot_unit")
    entry = inventory.capture_bytes(
        "raw/sec/company_tickers/source_unit.json",
        FetchedResponse(
            b'{"source":"unaltered"}\r\n',
            "https://www.sec.gov/files/company_tickers.json",
            200,
            datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        ),
        role="sec_ticker_map",
        provider="SEC",
        source_snapshot_id="source_unit",
    )
    return inventory, entry


def frozen_manifest(paths: ProjectPaths) -> dict[str, Any]:
    inventory, _ = captured_inventory(paths)
    raw_manifest = inventory.freeze({"format_version": 1})
    files = freeze_frames(
        paths,
        inventory.snapshot_id,
        {"curated/market/prices_daily.parquet": pd.DataFrame({"ticker": ["KO"], "close": [42.0]})},
    )
    return {
        **json.loads(raw_manifest.read_bytes()),
        "raw_manifest_path": raw_manifest.relative_to(paths.workspace_root).as_posix(),
        "raw_manifest_sha256": sha256_file(raw_manifest),
        "curated_files": files,
    }


def test_capture_keeps_exact_native_bytes_and_adjacent_immutable_lineage(
    paths: ProjectPaths,
) -> None:
    inventory, entry = captured_inventory(paths)
    path = paths.workspace_root / entry["raw_file_path"]
    assert path.read_bytes() == b'{"source":"unaltered"}\r\n'
    assert path.with_name(path.name + ".source.json").read_bytes() == json_bytes(entry)
    assert entry["sha256"] == sha256_file(path)
    assert entry["bytes"] == path.stat().st_size
    assert entry["result_status"] == "SUCCESS"
    assert entry["data_snapshot_id"] == "snapshot_unit"
    assert not Path(entry["raw_file_path"]).is_absolute()
    verify_sources(paths, {"sources": inventory.entries})
    typed_lineage = lineage(entry)
    assert typed_lineage["retrieved_at_utc"] == datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    assert "role" not in typed_lineage and "parameters" not in typed_lineage


def test_offset_source_retrieval_is_normalized_to_utc(paths: ProjectPaths) -> None:
    inventory = RawInventory(paths, "offset_unit")
    entry = inventory.capture_bytes(
        "raw/source_offset.json",
        FetchedResponse(
            b"{}",
            "https://data.sec.gov/source.json",
            200,
            datetime(2026, 1, 2, 10, tzinfo=timezone(timedelta(hours=7))),
        ),
        role="sec_submissions",
        provider="SEC",
        source_snapshot_id="source_offset",
    )
    assert entry["retrieved_at_utc"] == "2026-01-02T03:00:00+00:00"


def test_naive_retrieval_cannot_enter_a_source_inventory(paths: ProjectPaths) -> None:
    inventory = RawInventory(paths, "bad_timestamp")
    with pytest.raises(ValueError, match="timezone aware"):
        inventory.capture_bytes(
            "raw/bad_timestamp.json",
            FetchedResponse(b"{}", "https://data.sec.gov/source.json", 200, datetime(2026, 1, 1)),
            role="sec_submissions",
            provider="SEC",
            source_snapshot_id="bad_timestamp",
        )
    assert inventory.entries == []


@pytest.mark.parametrize("tamper", ["raw", "sidecar", "raw_manifest", "curated"])
def test_snapshot_verification_rejects_every_lineage_tamper(
    paths: ProjectPaths, tamper: str
) -> None:
    manifest = frozen_manifest(paths)
    verify_snapshot(paths, manifest)
    if tamper == "raw":
        path = paths.workspace_root / manifest["sources"][0]["raw_file_path"]
        path.write_bytes(b"changed native source")
        reason = "Raw source checksum mismatch"
    elif tamper == "sidecar":
        path = paths.workspace_root / manifest["sources"][0]["raw_file_path"]
        sidecar = path.with_name(path.name + ".source.json")
        changed = json.loads(sidecar.read_bytes())
        changed["source_url"] = "https://data.sec.gov/other-source.json"
        sidecar.write_bytes(json_bytes(changed))
        reason = "Raw source manifest changed"
    elif tamper == "raw_manifest":
        path = paths.workspace_root / manifest["raw_manifest_path"]
        changed = json.loads(path.read_bytes())
        changed["format_version"] = 999
        path.write_bytes(json_bytes(changed))
        reason = "Raw inventory manifest checksum mismatch"
    else:
        path = paths.workspace_root / manifest["curated_files"][0]["path"]
        frame = pq.read_table(path).to_pandas()
        frame["close"] *= 2
        pq.write_table(frame_table(frame), path)
        reason = "Frozen dataset checksum mismatch"
    with pytest.raises(ValueError, match=reason):
        verify_snapshot(paths, manifest)


def test_snapshot_verification_checks_recorded_row_counts(paths: ProjectPaths) -> None:
    manifest = frozen_manifest(paths)
    manifest["curated_files"][0]["rows"] = 999
    with pytest.raises(ValueError, match="row count mismatch"):
        verify_snapshot(paths, manifest)


@pytest.mark.parametrize("zone", ["source", "raw_manifest", "curated"])
@pytest.mark.parametrize(
    "unsafe", ["../outside.json", "/outside.json", "C:/outside.json", "..\\outside.json"]
)
def test_manifest_paths_cannot_escape_portable_workspace(
    paths: ProjectPaths, zone: str, unsafe: str
) -> None:
    manifest = frozen_manifest(paths)
    if zone == "source":
        manifest["sources"][0]["raw_file_path"] = unsafe
    elif zone == "raw_manifest":
        manifest["raw_manifest_path"] = unsafe
    else:
        manifest["curated_files"][0]["path"] = unsafe
    with pytest.raises(ValueError, match="portable relative|escapes"):
        verify_snapshot(paths, manifest)


def test_empty_source_inventory_is_not_a_valid_snapshot(paths: ProjectPaths) -> None:
    for manifest in ({}, {"sources": []}):
        with pytest.raises(ValueError, match="no raw-source inventory"):
            verify_sources(paths, manifest)


def test_native_source_identity_rejects_changed_bytes_or_metadata(paths: ProjectPaths) -> None:
    inventory, entry = captured_inventory(paths)
    path = paths.workspace_root / entry["raw_file_path"]
    original = path.read_bytes()
    with pytest.raises(FileExistsError, match="Immutable file already exists"):
        inventory.capture_bytes(
            "raw/sec/company_tickers/source_unit.json",
            FetchedResponse(
                b"changed", entry["source_url"], 200, datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
            ),
            role="sec_ticker_map",
            provider="SEC",
            source_snapshot_id="source_unit",
        )
    assert path.read_bytes() == original
    with pytest.raises(FileExistsError, match="Immutable file already exists"):
        inventory.capture_bytes(
            "raw/sec/company_tickers/source_unit.json",
            FetchedResponse(original, entry["source_url"], 200, datetime(2026, 1, 3, tzinfo=UTC)),
            role="sec_ticker_map",
            provider="SEC",
            source_snapshot_id="source_unit",
        )
    assert path.read_bytes() == original
    assert json.loads(path.with_name(path.name + ".source.json").read_bytes()) == entry


def test_frozen_frame_identity_is_idempotent_and_rejects_changed_content(
    paths: ProjectPaths,
) -> None:
    frame = pd.DataFrame({"ticker": ["KO"], "close": [42.0]})
    frames = {"curated/market/prices_daily.parquet": frame}
    first = freeze_frames(paths, "frozen_identity", frames)
    assert freeze_frames(paths, "frozen_identity", frames) == first
    changed = frame.copy()
    changed["close"] = 99.0
    with pytest.raises(FileExistsError, match="Immutable file already exists"):
        freeze_frames(paths, "frozen_identity", {"curated/market/prices_daily.parquet": changed})
    assert sha256_file(paths.workspace_root / first[0]["path"]) == first[0]["sha256"]


def test_canonical_alias_failure_restores_prior_files_and_keeps_frozen_inputs(
    paths: ProjectPaths,
) -> None:
    manifest = frozen_manifest(paths)
    file = manifest["curated_files"][0]
    canonical = paths.data_path(file["dataset"])
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"previous complete alias")
    with pytest.raises(RuntimeError, match="publication failed"):
        with canonical_aliases(paths, manifest["curated_files"]):
            assert sha256_file(canonical) == file["sha256"]
            raise RuntimeError("publication failed")
    assert canonical.read_bytes() == b"previous complete alias"
    assert sha256_file(paths.workspace_root / file["path"]) == file["sha256"]
    assert not list(paths.data.rglob(".rollback-*"))
    assert not list(paths.data.rglob(".publish-*"))


def test_failed_initial_publication_removes_new_aliases(paths: ProjectPaths) -> None:
    manifest = frozen_manifest(paths)
    canonical = paths.data_path(manifest["curated_files"][0]["dataset"])
    assert not canonical.exists()
    with pytest.raises(RuntimeError):
        with canonical_aliases(paths, manifest["curated_files"]):
            assert canonical.exists()
            raise RuntimeError("failed initial catalogue")
    assert not canonical.exists()
    verify_snapshot(paths, manifest)


def test_alias_copy_does_not_allow_canonical_edits_to_change_frozen_file(
    paths: ProjectPaths,
) -> None:
    manifest = frozen_manifest(paths)
    with canonical_aliases(paths, manifest["curated_files"]):
        pass
    canonical = paths.data_path(manifest["curated_files"][0]["dataset"])
    canonical.write_bytes(b"edited alias only")
    verify_snapshot(paths, manifest)


@pytest.mark.parametrize("link_kind", ["file", "parent"])
def test_alias_publication_rejects_symlink_to_an_existing_frozen_snapshot(
    paths: ProjectPaths, link_kind: str
) -> None:
    manifest = frozen_manifest(paths)
    old_file = manifest["curated_files"][0]
    frozen_path = paths.workspace_root / old_file["path"]
    files = freeze_frames(
        paths,
        "replacement_unit",
        {old_file["dataset"]: pd.DataFrame({"ticker": ["KO"], "close": [99.0]})},
    )
    logical_target = paths.data / old_file["dataset"]
    try:
        if link_kind == "file":
            logical_target.parent.mkdir(parents=True, exist_ok=True)
            logical_target.symlink_to(frozen_path)
        else:
            logical_target.parent.parent.mkdir(parents=True, exist_ok=True)
            logical_target.parent.symlink_to(frozen_path.parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("This host cannot create test symlinks; Linux CI checks the same guard")
    with pytest.raises(ValueError, match="must not contain symlinks"):
        with canonical_aliases(paths, files):
            pytest.fail("A symlinked target must be rejected before publication")
    assert sha256_file(frozen_path) == old_file["sha256"]
    verify_snapshot(paths, manifest)


def test_identity_is_order_independent_and_json_never_contains_nonfinite_numbers() -> None:
    assert content_identity({"a": 1, "b": 2}) == content_identity({"b": 2, "a": 1})
    assert content_identity({"a": 1}) != content_identity({"a": 2})
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            json_bytes({"invalid": invalid})


def test_source_inventory_check_does_not_mutate_manifest(paths: ProjectPaths) -> None:
    manifest = frozen_manifest(paths)
    original = deepcopy(manifest)
    verify_snapshot(paths, manifest)
    assert manifest == original


def test_frozen_manifest_records_actual_dates_utc_acceptance_ranges_and_missingness(
    paths: ProjectPaths,
) -> None:
    frame = pd.DataFrame(
        {
            "trading_date": [date(2021, 1, 5), None, date(2021, 1, 4)],
            "filing_date": [date(2021, 1, 6), None, date(2021, 1, 5)],
            "acceptance_datetime_utc": pd.to_datetime(
                ["2021-01-06T16:00:00Z", None, "2021-01-05T13:30:00Z"], utc=True
            ),
        }
    )
    expected = {
        "trading_date": {"min": "2021-01-04", "max": "2021-01-05", "null_rows": 1},
        "filing_date": {"min": "2021-01-05", "max": "2021-01-06", "null_rows": 1},
        "acceptance_datetime_utc": {
            "min": "2021-01-05T13:30:00+00:00",
            "max": "2021-01-06T16:00:00+00:00",
            "null_rows": 1,
        },
    }
    assert date_coverage(frame) == expected
    files = freeze_frames(
        paths, "coverage_unit", {"curated/evidence/sec_filing_index.parquet": frame}
    )
    assert files[0]["date_coverage"] == expected
    assert files[0]["rows"] == 3


@pytest.mark.parametrize("rows", [0, 2])
def test_empty_or_all_missing_dataset_has_no_invented_date_coverage(
    paths: ProjectPaths, rows: int
) -> None:
    frame = pd.DataFrame(
        {
            "trading_date": pd.Series([None] * rows, dtype="object"),
            "acceptance_datetime_utc": pd.Series([pd.NaT] * rows, dtype="datetime64[ns, UTC]"),
            "unrelated_date": pd.Series([None] * rows, dtype="object"),
        }
    )
    expected = {
        "trading_date": {"min": None, "max": None, "null_rows": rows},
        "acceptance_datetime_utc": {"min": None, "max": None, "null_rows": rows},
    }
    assert date_coverage(frame) == expected
    files = freeze_frames(
        paths, "empty_coverage_unit", {"curated/market/prices_daily.parquet": frame}
    )
    assert files[0]["date_coverage"] == expected
    assert files[0]["rows"] == rows

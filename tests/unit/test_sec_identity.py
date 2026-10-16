"""Dated SEC predecessor recovery uses new immutable source generations."""

import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest

from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse, SourceError
from structural_break.data.sec import SecDataError
from structural_break.data.sec_identity import (
    EFFECTIVE_DATE,
    IDENTITY_MAPPING_VERSION,
    IDENTITY_SOURCES,
    PREDECESSOR_CIK,
    SUCCESSOR_CIK,
    apply_reviewed_sec_identities,
    recover_historical_sec_index,
)
from structural_break.intelligence.evidence import select_event_filings

RETRIEVED = datetime(2026, 10, 3, 12, tzinfo=UTC)
HISTORY = f"CIK{PREDECESSOR_CIK}-submissions-001.json"


def metadata(year: int) -> dict[str, object]:
    return {
        "accessionNumber": [f"{PREDECESSOR_CIK}-{year % 100:02d}-000001"],
        "form": ["10-K"],
        "filingDate": [f"{year}-02-20"],
        "reportDate": [f"{year - 1}-12-31"],
        "acceptanceDateTime": [f"{year}-02-20T17:00:00Z"],
        "primaryDocument": ["xom10k.htm"],
    }


def source_get(
    calls: list[str], *, fail_history_once: bool = False, wrong_cik: bool = False
) -> Any:
    failures = 0

    def get(url: str) -> FetchedResponse:
        nonlocal failures
        calls.append(url)
        if url.endswith(HISTORY):
            if fail_history_once and failures == 0:
                failures += 1
                raise SourceError(url, 503)
            payload = metadata(2014)
        else:
            payload = {
                "cik": SUCCESSOR_CIK if wrong_cik else PREDECESSOR_CIK,
                "filings": {
                    "recent": metadata(2023),
                    "files": [
                        {"name": HISTORY, "filingFrom": "2014-01-01", "filingTo": "2014-12-31"}
                    ],
                },
            }
        return FetchedResponse(json.dumps(payload).encode(), url, 200, RETRIEVED)

    return get


def test_recovery_has_reviewed_date_bounds_and_parent_without_p1_mutation(
    paths: ProjectPaths, config: ProjectConfig
) -> None:
    p1 = paths.data_path("curated/evidence/sec_filing_index.parquet")
    p1.parent.mkdir(parents=True)
    p1.write_bytes(b"frozen phase 1")
    calls: list[str] = []
    frame, manifest = recover_historical_sec_index(
        paths, config, source_get(calls), parent_snapshot_id="parent_frozen"
    )
    assert len(calls) == 2 and len(frame) == 2
    assert set(frame["security_id"]) == {"US:XOM"}
    assert set(frame["cik"]) == {PREDECESSOR_CIK}
    assert frame["identity_valid_from"].isna().all()
    assert set(frame["identity_valid_to"]) == {EFFECTIVE_DATE.isoformat()}
    assert set(frame["identity_mapping_version"]) == {IDENTITY_MAPPING_VERSION}
    assert manifest["parent_snapshot_id"] == "parent_frozen"
    assert manifest["reviewed_mapping"]["official_review_sources"] == list(IDENTITY_SOURCES)
    assert all("phase4_identity_" in item["raw_file_path"] for item in manifest["sources"])
    assert p1.read_bytes() == b"frozen phase 1"
    assert "identity_sources" in manifest["curated_filing_index_path"]


def test_recovery_cached_offline_is_identical_and_never_calls_source(
    paths: ProjectPaths, config: ProjectConfig
) -> None:
    calls: list[str] = []
    first, manifest = recover_historical_sec_index(
        paths, config, source_get(calls), parent_snapshot_id="parent_frozen"
    )
    repeated, repeated_manifest = recover_historical_sec_index(
        paths, config, source_get(calls), parent_snapshot_id="parent_frozen", offline=True
    )
    pd.testing.assert_frame_equal(first, repeated)
    assert manifest == repeated_manifest
    assert len(calls) == 2


def test_missing_offline_identity_capture_is_explicit(
    paths: ProjectPaths, config: ProjectConfig
) -> None:
    calls: list[str] = []
    with pytest.raises(FileNotFoundError, match="offline"):
        recover_historical_sec_index(
            paths, config, source_get(calls), parent_snapshot_id="parent_frozen", offline=True
        )
    assert not calls


def test_changed_supplemental_source_is_blocking(
    paths: ProjectPaths, config: ProjectConfig
) -> None:
    _, manifest = recover_historical_sec_index(
        paths, config, source_get([]), parent_snapshot_id="parent_frozen"
    )
    source = paths.workspace_root / manifest["sources"][0]["raw_file_path"]
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        recover_historical_sec_index(
            paths, config, source_get([]), parent_snapshot_id="parent_frozen", offline=True
        )


def test_new_explicit_capture_preserves_previous_identity_generation(
    paths: ProjectPaths, config: ProjectConfig
) -> None:
    _, first = recover_historical_sec_index(
        paths, config, source_get([]), parent_snapshot_id="parent_frozen"
    )
    original = (paths.workspace_root / first["manifest_path"]).read_bytes()
    _, second = recover_historical_sec_index(
        paths, config, source_get([]), parent_snapshot_id="parent_frozen", capture_id="retry_2"
    )
    assert first["source_capture_id"] != second["source_capture_id"]
    assert (paths.workspace_root / first["manifest_path"]).read_bytes() == original


def test_partial_source_capture_resumes_without_recapturing_successful_response(
    paths: ProjectPaths, config: ProjectConfig
) -> None:
    calls: list[str] = []
    get = source_get(calls, fail_history_once=True)
    with pytest.raises(SourceError):
        recover_historical_sec_index(paths, config, get, parent_snapshot_id="parent_frozen")
    frame, manifest = recover_historical_sec_index(
        paths, config, get, parent_snapshot_id="parent_frozen"
    )
    assert len(frame) == 2 and len(manifest["sources"]) == 2
    assert len(calls) == 3
    assert sum(url.endswith(f"CIK{PREDECESSOR_CIK}.json") for url in calls) == 1


def test_wrong_source_cik_rejects_recovery(paths: ProjectPaths, config: ProjectConfig) -> None:
    with pytest.raises(SecDataError, match="disagrees"):
        recover_historical_sec_index(
            paths, config, source_get([], wrong_cik=True), parent_snapshot_id="parent_frozen"
        )
    assert not list(paths.data.rglob("sec_filing_index.parquet"))


def test_reviewed_map_cannot_route_successor_filings_before_2026() -> None:
    index = pd.DataFrame(
        [
            {
                "security_id": "US:XOM",
                "cik": PREDECESSOR_CIK,
                "filing_id": "old",
                "form": "10-K",
                "acceptance_datetime_utc": "2022-02-20T17:00:00Z",
            },
            {
                "security_id": "US:XOM",
                "cik": SUCCESSOR_CIK,
                "filing_id": "new",
                "form": "10-K",
                "acceptance_datetime_utc": "2022-02-25T17:00:00Z",
            },
        ]
    )
    original = index.copy()
    resolved = apply_reviewed_sec_identities(index)
    pd.testing.assert_frame_equal(index, original)
    cutoff = datetime(2022, 3, 1, 21, tzinfo=UTC)
    selected, coverage = select_event_filings(
        {"event_id": "event", "pair_id": "XOM__CVX", "event_timestamp": cutoff},
        resolved,
        ["US:XOM", "US:CVX"],
    )
    assert [row["filing_id"] for row in selected] == ["old"]
    assert coverage["B"]["status"] == "UNKNOWN"


def test_unreviewed_xom_cik_is_not_silently_accepted() -> None:
    with pytest.raises(ValueError, match="new reviewed mapping"):
        apply_reviewed_sec_identities(
            pd.DataFrame([{"security_id": "US:XOM", "cik": "0000000001"}])
        )

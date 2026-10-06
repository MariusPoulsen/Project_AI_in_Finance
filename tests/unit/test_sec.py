"""Deterministic SEC metadata tests; no external requests or document bodies."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytest

from structural_break.data.http import FetchedResponse
from structural_break.data.sec import (
    COMPANY_TICKERS_URL,
    SUBMISSIONS_BASE_URL,
    SecDataError,
    fetch_company_tickers,
    fetch_submissions,
    normalize_cik,
    normalize_filings,
    parse_acceptance_timestamp,
)

START = date(2014, 1, 1)
END = date(2025, 12, 31)
CIK = "0000021344"
ACCESSION = "0000021344-18-000031"
RETRIEVED = datetime(2026, 10, 2, 2, 0, tzinfo=UTC)


def lineage(**overrides: Any) -> dict[str, object]:
    return {
        "source_snapshot_id": "sec_fixture_v1",
        "data_snapshot_id": "snap_fixture_v1",
        "raw_file_path": f"data/raw/sec/submissions/{CIK}/sec_fixture_v1.json",
        "sha256": "a" * 64,
        "source_url": SUBMISSIONS_BASE_URL + f"CIK{CIK}.json",
        "retrieved_at_utc": RETRIEVED,
        "source_provider": "SEC_EDGAR",
        "library_version": None,
        **overrides,
    }


def metadata(**overrides: Any) -> dict[str, object]:
    return {
        "accessionNumber": [ACCESSION],
        "form": ["8-K"],
        "filingDate": ["2018-04-26"],
        "reportDate": ["2018-04-24"],
        "acceptanceDateTime": ["2018-04-26T19:51:01.000Z"],
        "primaryDocument": ["ko-20180424x8k.htm"],
        "primaryDocDescription": ["FORM 8-K"],
        "items": ["2.02,9.01"],
        "size": [129921],
        "isXBRL": [0],
        "isInlineXBRL": [0],
        "isXBRLNumeric": [0],
        "fileNumber": ["001-02217"],
        "filmNumber": ["18780660"],
        "act": ["34"],
        "core_type": ["8-K"],
        **overrides,
    }


def response(url: str, payload: object, status: int = 200) -> FetchedResponse:
    return FetchedResponse(json.dumps(payload).encode(), url, status, RETRIEVED)


def test_current_and_older_metadata_keep_availability_and_lineage() -> None:
    main: dict[str, object] = {"cik": int(CIK), "filings": {"recent": metadata()}}
    older = metadata(
        accessionNumber=["0000021344-14-000002"],
        filingDate=["2014-01-01"],
        reportDate=["2013-12-31"],
        acceptanceDateTime=["2014-01-01T18:05:00-05:00"],
        form=["10-K/A"],
    )
    frame = normalize_filings([(CIK, main, lineage()), (CIK, older, lineage())], START, END)
    assert frame["accession_number"].tolist() == ["0000021344-14-000002", ACCESSION]
    amendment = frame.iloc[0]
    assert amendment["base_form"] == "10-K"
    assert amendment["is_amendment"]
    assert amendment["acceptance_datetime_raw"] == "2014-01-01T18:05:00-05:00"
    assert amendment["acceptance_datetime_utc"] == pd.Timestamp("2014-01-01T23:05:00Z")
    assert frame["point_in_time_eligible"].all()
    assert (frame["sha256"] == "a" * 64).all()
    assert (frame["retrieved_at_utc"] == RETRIEVED).all()
    row = frame.iloc[1]
    assert row["archive_url"] == (
        "https://www.sec.gov/Archives/edgar/data/21344/000002134418000031/"
    )
    assert row["primary_document_url"] == row["archive_url"] + "ko-20180424x8k.htm"
    assert row["complete_submission_url"] == row["archive_url"] + ACCESSION + ".txt"


@pytest.mark.parametrize("acceptance", [None, ""])
def test_missing_acceptance_is_retained_but_ineligible(acceptance: object) -> None:
    frame = normalize_filings(
        [(CIK, metadata(acceptanceDateTime=[acceptance]), lineage())], START, END
    )
    row = frame.iloc[0]
    assert pd.isna(row["acceptance_datetime_utc"])
    assert not row["point_in_time_eligible"]
    assert row["timestamp_quality_flag"] == "MISSING"
    assert row["filing_date"] == date(2018, 4, 26)
    if acceptance is None:
        assert pd.isna(row["acceptance_datetime_raw"])
    else:
        assert row["acceptance_datetime_raw"] == ""


def test_absent_history_acceptance_column_is_never_imputed() -> None:
    older = metadata()
    del older["acceptanceDateTime"]
    row = normalize_filings([(CIK, older, lineage())], START, END).iloc[0]
    assert pd.isna(row["acceptance_datetime_utc"])
    assert not row["point_in_time_eligible"]


@pytest.mark.parametrize(
    ("raw", "expected", "quality"),
    [
        ("2018-07-02T16:30:00", "2018-07-02T20:30:00Z", "SEC_LOCAL_CONVERTED"),
        ("2018-01-02T16:30:00", "2018-01-02T21:30:00Z", "SEC_LOCAL_CONVERTED"),
        ("20180102163000", "2018-01-02T21:30:00Z", "SEC_LOCAL_CONVERTED"),
        ("2018-07-02T20:30:00Z", "2018-07-02T20:30:00Z", "AWARE_SOURCE"),
        ("2018-11-04T01:30:00-04:00", "2018-11-04T05:30:00Z", "AWARE_SOURCE"),
    ],
)
def test_sec_acceptance_timezone_conversion(raw: str, expected: str, quality: str) -> None:
    parsed, flag = parse_acceptance_timestamp(raw)
    assert parsed == datetime.fromisoformat(expected)
    assert parsed is not None and parsed.tzinfo == UTC
    assert flag == quality


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("2018-11-04T01:30:00", "Ambiguous"),
        ("2018-03-11T02:30:00", "Nonexistent"),
        ("2018-04-26", "requires a timestamp"),
        ("not-a-timestamp", "requires a timestamp"),
        (123, "must be text"),
        ("20181301100000", "Invalid SEC acceptance timestamp"),
    ],
)
def test_invalid_or_ambiguous_acceptance_rejects_batch(raw: object, reason: str) -> None:
    with pytest.raises(SecDataError, match=reason):
        normalize_filings([(CIK, metadata(acceptanceDateTime=[raw]), lineage())], START, END)


def test_exact_overlap_deduplicates_but_conflict_rejects() -> None:
    original = metadata()
    frame = normalize_filings(
        [(CIK, original, lineage()), (CIK, deepcopy(original), lineage(sha256="b" * 64))],
        START,
        END,
    )
    assert len(frame) == 1
    conflicting = metadata(acceptanceDateTime=["2018-04-26T19:52:01Z"])
    with pytest.raises(SecDataError, match="Conflicting SEC metadata"):
        normalize_filings([(CIK, original, lineage()), (CIK, conflicting, lineage())], START, END)


@pytest.mark.parametrize("form", ["8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A"])
def test_all_core_forms_and_amendments_are_included(form: str) -> None:
    frame = normalize_filings([(CIK, metadata(form=[form]), lineage())], START, END)
    assert len(frame) == 1
    assert frame.iloc[0]["form"] == form


@pytest.mark.parametrize(
    "overrides", [{"form": ["4"]}, {"filingDate": ["2013-12-31"]}, {"filingDate": ["2026-01-01"]}]
)
def test_out_of_scope_forms_and_dates_are_excluded(overrides: dict[str, object]) -> None:
    frame = normalize_filings([(CIK, metadata(**overrides), lineage())], START, END)
    assert frame.empty
    assert "acceptance_datetime_utc" in frame
    assert str(frame["acceptance_datetime_utc"].dtype) == "datetime64[ns, UTC]"
    assert str(frame["point_in_time_eligible"].dtype) == "boolean"
    assert str(frame["size"].dtype) == "Int64"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"acceptanceDateTime": []}, "column length mismatch"),
        ({"filingDate": [""]}, "Missing SEC filingDate"),
        ({"accessionNumber": ["not-an-accession"]}, "Invalid SEC accession"),
        ({"size": [-1]}, "nonnegative integer"),
        ({"isXBRL": [2]}, "must be 0 or 1"),
        ({"primaryDocument": ["../outside.htm"]}, "Invalid SEC primaryDocument"),
    ],
)
def test_malformed_metadata_is_rejected(overrides: dict[str, object], reason: str) -> None:
    with pytest.raises(SecDataError, match=reason):
        normalize_filings([(CIK, metadata(**overrides), lineage())], START, END)


@pytest.mark.parametrize("cik", ["", "0", "not-a-cik", "12345678901", "-1"])
def test_invalid_ciks_are_rejected(cik: str) -> None:
    with pytest.raises(SecDataError):
        normalize_cik(cik)


def test_payload_cik_mismatch_is_rejected() -> None:
    with pytest.raises(SecDataError, match="disagrees"):
        normalize_filings(
            [(CIK, {"cik": 1, "filings": {"recent": metadata()}}, lineage())], START, END
        )


@pytest.mark.parametrize("field", ["sha256", "raw_file_path", "retrieved_at_utc"])
def test_source_lineage_is_required(field: str) -> None:
    source = lineage()
    del source[field]
    with pytest.raises(SecDataError, match="lineage|timezone|sha256"):
        normalize_filings([(CIK, metadata(), source)], START, END)


def test_fetch_loads_every_intersecting_history_and_preserves_bytes() -> None:
    main_url = SUBMISSIONS_BASE_URL + f"CIK{CIK}.json"
    filenames = [f"CIK{CIK}-submissions-{index:03d}.json" for index in range(1, 5)]
    main_payload = {
        "cik": int(CIK),
        "filings": {
            "recent": metadata(),
            "files": [
                {"name": filenames[0], "filingFrom": "2014-01-01", "filingTo": "2020-01-01"},
                {"name": filenames[1], "filingFrom": "2010-01-01", "filingTo": "2014-01-01"},
                {"name": filenames[2], "filingFrom": "1999-01-01", "filingTo": "2013-12-31"},
                {"name": filenames[3]},
            ],
        },
    }
    calls: list[str] = []
    responses = {main_url: response(main_url, main_payload)}
    responses.update(
        {
            SUBMISSIONS_BASE_URL + name: response(SUBMISSIONS_BASE_URL + name, metadata())
            for name in filenames
        }
    )

    def get(url: str) -> FetchedResponse:
        calls.append(url)
        return responses[url]

    fetched = fetch_submissions([CIK, "21344"], START, END, get)
    assert [item[1] for item in fetched] == [f"CIK{CIK}.json", *filenames[:2], filenames[3]]
    assert len(calls) == 4
    assert all("Archives" not in url for url in calls)
    assert fetched[0][2] is responses[main_url]


@pytest.mark.parametrize(
    "descriptor",
    [
        {"name": "../../outside.json"},
        {"name": "CIK0000000001-submissions-001.json"},
        {"name": f"CIK{CIK}-submissions-001.json", "filingFrom": "bad"},
        {
            "name": f"CIK{CIK}-submissions-001.json",
            "filingFrom": "2020-01-01",
            "filingTo": "2019-01-01",
        },
    ],
)
def test_malformed_history_descriptor_is_rejected(descriptor: dict[str, object]) -> None:
    payload = {"cik": int(CIK), "filings": {"recent": metadata(), "files": [descriptor]}}
    with pytest.raises(SecDataError):
        fetch_submissions([CIK], START, END, lambda url: response(url, payload))


def test_fetch_company_map_is_immutable_response_and_rejects_http_failure() -> None:
    fetched = response(COMPANY_TICKERS_URL, {"0": {"cik_str": int(CIK), "ticker": "KO"}})
    assert fetch_company_tickers(lambda _: fetched) is fetched
    with pytest.raises(SecDataError, match="HTTP status 403"):
        fetch_company_tickers(lambda _: response(COMPANY_TICKERS_URL, {}, 403))


def test_empty_batch_has_identical_schema_to_populated_batch() -> None:
    empty = normalize_filings([], START, END)
    populated = normalize_filings([(CIK, metadata(), lineage())], START, END)
    assert empty.columns.tolist() == populated.columns.tolist()
    assert empty.dtypes.equals(populated.dtypes)


def test_naive_retrieval_timestamp_is_rejected() -> None:
    with pytest.raises(SecDataError, match="timezone aware"):
        normalize_filings(
            [(CIK, metadata(), lineage(retrieved_at_utc=datetime(2026, 1, 1)))], START, END
        )


def test_acceptance_cannot_follow_source_retrieval() -> None:
    with pytest.raises(SecDataError, match="follows retrieval"):
        normalize_filings(
            [(CIK, metadata(), lineage(retrieved_at_utc=datetime(2017, 1, 1, tzinfo=UTC)))],
            START,
            END,
        )

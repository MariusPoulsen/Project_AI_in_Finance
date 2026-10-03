"""SEC submissions metadata ingestion, with explicit point-in-time availability.

This adapter downloads metadata only. Filing bodies and evidence selection belong
to the later event-intelligence phase. Missing acceptance timestamps are retained
as ineligible records; filing/report dates are never substituted for availability.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd

from structural_break.data.http import FetchedResponse

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions/"
_FORMS = frozenset({"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A"})
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_NEW_YORK = ZoneInfo("America/New_York")
_SOURCE_FIELDS = (
    "source_snapshot_id",
    "data_snapshot_id",
    "raw_file_path",
    "sha256",
    "source_url",
    "retrieved_at_utc",
    "source_provider",
    "library_version",
)
_FILING_FIELDS = (
    "accessionNumber",
    "form",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "primaryDocument",
    "primaryDocDescription",
    "items",
    "size",
    "isXBRL",
    "isInlineXBRL",
    "isXBRLNumeric",
    "fileNumber",
    "filmNumber",
    "act",
    "core_type",
)
_STRING_COLUMNS = (
    "filing_id",
    "accession_number",
    "cik",
    "form",
    "base_form",
    "acceptance_datetime_raw",
    "timestamp_quality_flag",
    "primary_document",
    "primary_document_description",
    "items",
    "file_number",
    "film_number",
    "act",
    "core_type",
    "archive_url",
    "primary_document_url",
    "complete_submission_url",
    "source_snapshot_id",
    "data_snapshot_id",
    "raw_file_path",
    "sha256",
    "source_url",
    "source_provider",
    "library_version",
)
_BOOL_COLUMNS = (
    "is_amendment",
    "point_in_time_eligible",
    "is_xbrl",
    "is_inline_xbrl",
    "is_xbrl_numeric",
)
_COLUMNS = (
    "filing_id",
    "accession_number",
    "cik",
    "form",
    "base_form",
    "is_amendment",
    "filing_date",
    "report_date",
    "acceptance_datetime_raw",
    "acceptance_datetime_utc",
    "point_in_time_eligible",
    "timestamp_quality_flag",
    "primary_document",
    "primary_document_description",
    "items",
    "size",
    "is_xbrl",
    "is_inline_xbrl",
    "is_xbrl_numeric",
    "file_number",
    "film_number",
    "act",
    "core_type",
    "archive_url",
    "primary_document_url",
    "complete_submission_url",
    *_SOURCE_FIELDS,
)


class SecDataError(ValueError):
    """Source metadata cannot satisfy the SEC data contract."""


def normalize_cik(value: str | int) -> str:
    """Return the SEC's ten-digit CIK without accepting malformed identities."""
    text = str(value)
    if not text.isascii() or not text.isdigit() or not 1 <= len(text) <= 10:
        raise SecDataError(f"Invalid SEC CIK: {value!r}")
    if int(text) == 0:
        raise SecDataError("SEC CIK must be positive")
    return text.zfill(10)


def parse_json_response(response: FetchedResponse) -> dict[str, object]:
    """Decode a successful JSON metadata response without hiding HTTP failures."""
    if response.status_code != 200:
        raise SecDataError(f"SEC metadata HTTP status {response.status_code}: {response.url}")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecDataError(f"Invalid SEC JSON response: {response.url}") from exc
    if not isinstance(payload, dict):
        raise SecDataError(f"SEC JSON must contain an object: {response.url}")
    return cast(dict[str, object], payload)


def fetch_company_tickers(get: Callable[[str], FetchedResponse]) -> FetchedResponse:
    """Fetch the official ticker map; the caller persists its unmodified bytes."""
    response = get(COMPANY_TICKERS_URL)
    parse_json_response(response)
    return response


def fetch_submissions(
    ciks: Sequence[str],
    start: date,
    end: date,
    get: Callable[[str], FetchedResponse],
) -> list[tuple[str, str, FetchedResponse]]:
    """Fetch each CIK's current metadata and every intersecting older history file.

    Bounds are inclusive filing dates. A missing history-file range causes the
    file to be downloaded conservatively; a malformed declared range is rejected.
    """
    _validate_range(start, end)
    fetched: list[tuple[str, str, FetchedResponse]] = []
    for cik in sorted({normalize_cik(value) for value in ciks}):
        filename = f"CIK{cik}.json"
        response = get(SUBMISSIONS_BASE_URL + filename)
        payload = parse_json_response(response)
        _check_payload_cik(payload, cik)
        fetched.append((cik, filename, response))
        filings = payload.get("filings")
        if not isinstance(filings, dict):
            raise SecDataError(f"SEC submissions missing filings object for CIK {cik}")
        files = filings.get("files", [])
        if not isinstance(files, list):
            raise SecDataError(f"SEC history files must be an array for CIK {cik}")
        seen: set[str] = set()
        for descriptor in files:
            if not isinstance(descriptor, dict):
                raise SecDataError(f"Malformed SEC history descriptor for CIK {cik}")
            history_name = descriptor.get("name")
            if not isinstance(history_name, str) or not re.fullmatch(
                rf"CIK{cik}-submissions-\d+\.json", history_name
            ):
                raise SecDataError(f"Invalid SEC history filename: {history_name!r}")
            from_date = _date(descriptor.get("filingFrom"), "filingFrom", required=False)
            to_date = _date(descriptor.get("filingTo"), "filingTo", required=False)
            if from_date is not None and to_date is not None and from_date > to_date:
                raise SecDataError(f"Reversed SEC history range in {history_name}")
            if (from_date is not None and from_date > end) or (
                to_date is not None and to_date < start
            ):
                continue
            if history_name in seen:
                continue
            seen.add(history_name)
            history = get(SUBMISSIONS_BASE_URL + history_name)
            parse_json_response(history)
            fetched.append((cik, history_name, history))
    return fetched


def parse_acceptance_timestamp(value: object) -> tuple[datetime | None, str]:
    """Parse availability as UTC and reject ambiguous/nonexistent SEC local times.

    Offset-aware source values govern their own offset. Naive SEC values are
    America/New_York wall-clock times, with no guessed DST fold. The raw value is
    retained separately by ``normalize_filings``.
    """
    if value is None or value == "":
        return None, "MISSING"
    if not isinstance(value, str):
        raise SecDataError(f"SEC acceptance timestamp must be text: {value!r}")
    if re.fullmatch(r"\d{14}", value):
        try:
            parsed = datetime.strptime(value, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise SecDataError(f"Invalid SEC acceptance timestamp: {value!r}") from exc
    else:
        if "T" not in value and " " not in value:
            raise SecDataError(f"SEC acceptance value requires a timestamp: {value!r}")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SecDataError(f"Invalid SEC acceptance timestamp: {value!r}") from exc
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone(UTC), "AWARE_SOURCE"
    candidates = {
        local.astimezone(UTC)
        for fold in (0, 1)
        if (local := parsed.replace(tzinfo=_NEW_YORK, fold=fold))
        .astimezone(UTC)
        .astimezone(_NEW_YORK)
        .replace(tzinfo=None)
        == parsed
    }
    if not candidates:
        raise SecDataError(f"Nonexistent SEC local acceptance timestamp: {value!r}")
    if len(candidates) != 1:
        raise SecDataError(f"Ambiguous SEC local acceptance timestamp: {value!r}")
    return candidates.pop(), "SEC_LOCAL_CONVERTED"


def normalize_filings(
    sources: list[tuple[str, dict[str, object], dict[str, object]]],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Normalize relevant domestic forms from current and older submissions JSON.

    Source tuples contain CIK, parsed source JSON, and caller-supplied immutable
    source lineage. Exact overlapping metadata is deduplicated. Any conflicting
    metadata under the same accession rejects the batch instead of choosing an
    arbitrary version. Security identities are joined from the reviewed master
    by the orchestration layer after normalization.
    """
    _validate_range(start, end)
    rows: list[dict[str, object]] = []
    identities: dict[str, tuple[str, dict[str, object]]] = {}
    for source_cik, payload, lineage in sources:
        cik = normalize_cik(source_cik)
        _check_payload_cik(payload, cik)
        metadata = _columnar_metadata(payload, cik)
        source_lineage = _validate_lineage(lineage)
        accessions = metadata.get("accessionNumber")
        if not isinstance(accessions, list):
            raise SecDataError(f"SEC accessionNumber must be an array for CIK {cik}")
        length = len(accessions)
        for field in _FILING_FIELDS:
            values = metadata.get(field)
            if values is None:
                if field in {"accessionNumber", "form", "filingDate"}:
                    raise SecDataError(f"SEC metadata missing required array {field} for CIK {cik}")
                continue
            if not isinstance(values, list) or len(values) != length:
                raise SecDataError(f"SEC column length mismatch for {field}, CIK {cik}")
        for offset in range(length):
            record = {
                field: cast(list[object], metadata[field])[offset]
                if metadata.get(field) is not None
                else None
                for field in _FILING_FIELDS
            }
            form = _text(record["form"], "form", required=True)
            if form not in _FORMS:
                continue
            filing_date = _date(record["filingDate"], "filingDate", required=True)
            assert filing_date is not None
            if not start <= filing_date <= end:
                continue
            accession = _text(record["accessionNumber"], "accessionNumber", required=True)
            assert accession is not None
            if not _ACCESSION.fullmatch(accession):
                raise SecDataError(f"Invalid SEC accession: {accession!r}")
            previous = identities.get(accession)
            if previous is not None:
                if previous != (cik, record):
                    raise SecDataError(f"Conflicting SEC metadata for accession {accession}")
                continue
            identities[accession] = (cik, record)
            accepted, quality = parse_acceptance_timestamp(record["acceptanceDateTime"])
            if accepted is not None and accepted > cast(
                datetime, source_lineage["retrieved_at_utc"]
            ):
                raise SecDataError(f"SEC acceptance timestamp follows retrieval for {accession}")
            primary = _text(record["primaryDocument"], "primaryDocument")
            archive = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
            )
            primary_url = None
            if primary is not None:
                path = PurePosixPath(primary)
                if path.is_absolute() or ".." in path.parts or "\\" in primary:
                    raise SecDataError(f"Invalid SEC primaryDocument path: {primary!r}")
                primary_url = archive + quote(primary, safe="/._-")
            rows.append(
                {
                    "filing_id": accession,
                    "accession_number": accession,
                    "cik": cik,
                    "form": form,
                    "base_form": form.removesuffix("/A"),
                    "is_amendment": form.endswith("/A"),
                    "filing_date": filing_date,
                    "report_date": _date(record["reportDate"], "reportDate", required=False),
                    "acceptance_datetime_raw": record["acceptanceDateTime"],
                    "acceptance_datetime_utc": accepted,
                    "point_in_time_eligible": accepted is not None,
                    "timestamp_quality_flag": quality,
                    "primary_document": primary,
                    "primary_document_description": _text(
                        record["primaryDocDescription"], "primaryDocDescription"
                    ),
                    "items": _text(record["items"], "items"),
                    "size": _integer(record["size"], "size"),
                    "is_xbrl": _flag(record["isXBRL"], "isXBRL"),
                    "is_inline_xbrl": _flag(record["isInlineXBRL"], "isInlineXBRL"),
                    "is_xbrl_numeric": _flag(record["isXBRLNumeric"], "isXBRLNumeric"),
                    "file_number": _text(record["fileNumber"], "fileNumber"),
                    "film_number": _text(record["filmNumber"], "filmNumber"),
                    "act": _text(record["act"], "act"),
                    "core_type": _text(record["core_type"], "core_type"),
                    "archive_url": archive,
                    "primary_document_url": primary_url,
                    "complete_submission_url": archive + accession + ".txt",
                    **source_lineage,
                }
            )
    result = pd.DataFrame(rows, columns=list(_COLUMNS))
    for column in _STRING_COLUMNS:
        result[column] = result[column].astype("string")
    for column in _BOOL_COLUMNS:
        result[column] = result[column].astype("boolean")
    result["size"] = result["size"].astype("Int64")
    for column in ("acceptance_datetime_utc", "retrieved_at_utc"):
        result[column] = pd.to_datetime(result[column], utc=True)
    return result.sort_values(["cik", "filing_date", "accession_number"]).reset_index(drop=True)


def _columnar_metadata(payload: Mapping[str, object], cik: str) -> dict[str, object]:
    if "filings" not in payload:
        return dict(payload)
    filings = payload["filings"]
    if not isinstance(filings, dict) or not isinstance(filings.get("recent"), dict):
        raise SecDataError(f"SEC submissions missing filings.recent object for CIK {cik}")
    return cast(dict[str, object], filings["recent"])


def _check_payload_cik(payload: Mapping[str, object], cik: str) -> None:
    value = payload.get("cik")
    if value is not None:
        if not isinstance(value, str | int) or isinstance(value, bool):
            raise SecDataError(f"Malformed CIK in SEC submissions: {value!r}")
        if normalize_cik(value) != cik:
            raise SecDataError(f"SEC payload CIK disagrees with request CIK {cik}")


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise SecDataError("SEC ingestion start date must not exceed end date")


def _date(value: object, field: str, *, required: bool) -> date | None:
    if value is None or value == "":
        if required:
            raise SecDataError(f"Missing SEC {field}")
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise SecDataError(f"Invalid SEC {field}: {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SecDataError(f"Invalid SEC {field}: {value!r}") from exc


def _text(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise SecDataError(f"Missing SEC {field}")
        return None
    if not isinstance(value, str):
        raise SecDataError(f"SEC {field} must be text: {value!r}")
    return value


def _integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SecDataError(f"SEC {field} must be a nonnegative integer: {value!r}")
    return value


def _flag(value: object, field: str) -> bool | None:
    if value is None:
        return None
    if value not in (0, 1) or not isinstance(value, int | bool):
        raise SecDataError(f"SEC {field} must be 0 or 1: {value!r}")
    return bool(value)


def _validate_lineage(lineage: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in _SOURCE_FIELDS:
        value = lineage.get(field)
        if field == "retrieved_at_utc":
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise SecDataError("SEC source retrieved_at_utc must be timezone aware")
            result[field] = value.astimezone(UTC)
        elif field == "library_version" and value is None:
            result[field] = None
        else:
            if not isinstance(value, str) or not value:
                raise SecDataError(f"Missing SEC source lineage field {field}")
            if field == "sha256" and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise SecDataError("SEC source sha256 must be a lowercase SHA-256 digest")
            result[field] = value
    return result

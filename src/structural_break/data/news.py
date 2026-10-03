"""Optional GDELT Article List metadata for explicitly requested current demos.

Official format: https://blog.gdeltproject.org/announcing-the-gdelt-article-list-rss-feed/
GAL is gzip-compressed UTF-8 newline-delimited JSON. Its ``date`` field mixes
publisher timestamps and GDELT observation times without a distinguishing flag.
Consequently, GAL alone cannot establish an original publication time. This
adapter preserves the ambiguous value and never makes it historical evidence.
"""

import gzip
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from structural_break.data.http import FetchedResponse, HttpClient

GAL_BASE_URL = "https://data.gdeltproject.org/gdeltv3/gal/"
_GAL_ARCHIVE = re.compile(r"^https://data\.gdeltproject\.org/gdeltv3/gal/(\d{14})\.gal\.json\.gz$")
_STRING_COLUMNS = (
    "news_id",
    "security_id",
    "matched_entity",
    "title",
    "publisher_domain",
    "url",
    "article_text",
    "source_quality_flag",
    "timestamp_quality_flag",
    "seen_at_quality_flag",
    "gdelt_date_raw",
    "outlet_name",
    "outlet_logo",
    "outlet_twitter",
    "image_url",
    "description",
    "language",
    "author",
    "raw_metadata_json",
    "source_url",
    "raw_file_path",
    "sha256",
    "source_snapshot_id",
    "data_snapshot_id",
    "source_provider",
    "usage_scope",
)
_TIME_COLUMNS = ("published_at", "gdelt_reported_at", "gdelt_seen_at", "retrieved_at_utc")


def _require_current_demo(purpose: str) -> None:
    if purpose != "current_demo":
        raise ValueError("Optional GDELT metadata is allowed only for purpose='current_demo'")


def gal_archive_url(batch_at: datetime) -> str:
    """Address the documented timestamped public GAL archive; no invented API."""
    if batch_at.tzinfo is None or batch_at.utcoffset() is None:
        raise ValueError("GAL batch timestamp must include a timezone")
    utc_time = batch_at.astimezone(UTC)
    if utc_time.second or utc_time.microsecond:
        raise ValueError("GAL archives have minute resolution")
    return f"{GAL_BASE_URL}{utc_time.strftime('%Y%m%d%H%M%S')}.gal.json.gz"


def fetch_gal(client: HttpClient, batch_at: datetime, *, purpose: str) -> FetchedResponse:
    """Fetch raw bytes for the caller to snapshot immutably before normalization."""
    _require_current_demo(purpose)
    return client.get(gal_archive_url(batch_at))


def parse_gal_gzip(body: bytes, *, purpose: str) -> tuple[dict[str, object], ...]:
    """Read the actual GAL JSON-NL format, retaining all supplied source fields."""
    _require_current_demo(purpose)
    try:
        text = gzip.decompress(body).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as error:
        raise ValueError("Invalid gzip-compressed UTF-8 GAL snapshot") from error
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid GAL JSON at line {line_number}") from error
        if not isinstance(record, dict):
            raise ValueError(f"GAL line {line_number} is not an article metadata object")
        records.append(record)
    return tuple(records)


def _text(record: Mapping[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"GAL field {field} must be text or null")
    return value.strip() or None


def _normalized_url(value: str | None) -> str | None:
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("GAL article URL must be an absolute HTTP(S) URL")
    if parts.username or parts.password:
        raise ValueError("GAL article URL must not contain credentials")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    port = parts.port
    if port and not (scheme == "https" and port == 443 or scheme == "http" and port == 80):
        host = f"{host}:{port}"
    return urlunsplit((scheme, host, parts.path or "/", parts.query, ""))


def _utc_timestamp(value: object, name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{name} must be an ISO timestamp") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(UTC)


def normalize_gal(
    records: Sequence[Mapping[str, object]],
    lineage: Mapping[str, object],
    *,
    purpose: str,
) -> pd.DataFrame:
    """Normalize snapshotted GAL records without promoting ambiguous timestamps.

    ``gdelt_seen_at`` records the archive's batch observation time, rather than an
    inferred exact first-seen time. Its quality flag states that distinction.
    Original publication, entity matches and article text are unknown in this
    source and remain nullable. They require separately governed enrichment.
    Repeated URLs are collapsed deterministically; the immutable raw snapshot
    retains every source record and ``source_record_count`` exposes duplicates.
    """
    _require_current_demo(purpose)
    required = ("source_url", "raw_file_path", "sha256", "source_snapshot_id", "data_snapshot_id")
    for key in required:
        if not isinstance(lineage.get(key), str) or not lineage[key]:
            raise ValueError(f"Missing GAL source lineage: {key}")
    source_url = cast(str, lineage["source_url"])
    archive_match = _GAL_ARCHIVE.fullmatch(source_url)
    if archive_match is None:
        raise ValueError("GAL source_url must identify the documented timestamped archive")
    batch_at = datetime.strptime(archive_match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    # Also checks minute alignment without silently rounding an archive identity.
    gal_archive_url(batch_at)
    retrieved_at = _utc_timestamp(lineage.get("retrieved_at_utc"), "retrieved_at_utc")
    if batch_at > retrieved_at:
        raise ValueError("GAL archive observation cannot be after retrieval")
    if not re.fullmatch(r"[0-9a-f]{64}", cast(str, lineage["sha256"])):
        raise ValueError("GAL source lineage requires a SHA-256 hex digest")
    rows: dict[str, dict[str, object]] = {}
    # Stable selection for duplicate URLs, regardless of upstream record order.
    ordered = sorted(
        records,
        key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False),
    )
    for record in ordered:
        metadata_json = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False)
        url = _normalized_url(_text(record, "url"))
        raw_date = _text(record, "date")
        try:
            reported_at: datetime | None = _utc_timestamp(raw_date, "GAL date")
        except ValueError:
            reported_at = None
        identity = json.dumps([url, None] if url else [None, metadata_json], ensure_ascii=False)
        news_id = "news_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if news_id in rows:
            count = cast(int, rows[news_id]["source_record_count"])
            rows[news_id]["source_record_count"] = count + 1
            continue
        domain = _text(record, "domain")
        rows[news_id] = {
            "news_id": news_id,
            "security_id": None,
            "matched_entity": None,
            "title": _text(record, "title"),
            "publisher_domain": domain.lower() if domain else None,
            "url": url,
            "article_text": None,
            "published_at": None,
            "gdelt_date_raw": raw_date,
            "gdelt_reported_at": reported_at,
            "gdelt_seen_at": batch_at,
            "seen_at_quality_flag": "ARCHIVE_BATCH_OBSERVATION",
            "point_in_time_eligible": False,
            "headline_eligible": False,
            "source_quality_flag": "UNKNOWN",
            "timestamp_quality_flag": "AMBIGUOUS_GAL_DATE" if reported_at else "INVALID_OR_MISSING",
            "outlet_name": _text(record, "outletName"),
            "outlet_logo": _text(record, "outletLogo"),
            "outlet_twitter": _text(record, "outletTwitter"),
            "image_url": _text(record, "image"),
            "description": _text(record, "desc"),
            "language": _text(record, "lang"),
            "author": _text(record, "author"),
            "raw_metadata_json": metadata_json,
            "source_record_count": 1,
            **{key: lineage[key] for key in required},
            "retrieved_at_utc": retrieved_at,
            "source_provider": "gdelt",
            "usage_scope": "current_demo",
        }
    frame = pd.DataFrame(rows.values())
    for column in _STRING_COLUMNS:
        frame[column] = pd.Series(frame[column].tolist() if column in frame else [], dtype="string")
    for column in _TIME_COLUMNS:
        frame[column] = pd.to_datetime(frame[column] if column in frame else [], utc=True)
    for column in ("point_in_time_eligible", "headline_eligible"):
        frame[column] = pd.Series(frame[column].tolist() if column in frame else [], dtype="bool")
    frame["source_record_count"] = pd.Series(
        frame["source_record_count"].tolist() if "source_record_count" in frame else [],
        dtype="int64",
    )
    return frame.sort_values("news_id").reset_index(drop=True)

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest

from structural_break.data.http import FetchedResponse
from structural_break.data.news import fetch_gal, gal_archive_url, normalize_gal, parse_gal_gzip


@pytest.fixture
def gal_records():
    # Actual GAL field shape and ISO UTC date format documented by GDELT at:
    # https://blog.gdeltproject.org/custom-entity-extraction-over-the-news-using-web-ngrams-3-0/
    # Content is a deterministic fictitious article, not research evidence.
    return [
        {
            "date": "2026-10-03T09:01:00.000Z",
            "url": "https://EXAMPLE.org:443/finance/issuer-update?lang=en#section",
            "domain": "EXAMPLE.org",
            "outletName": "Fixture News",
            "outletLogo": "https://example.org/icon.ico",
            "outletTwitter": "@fixture",
            "title": "Fixture issuer announces an update",
            "image": "https://example.org/photo.jpg",
            "desc": "Deterministic test description.",
            "lang": "en",
            "author": "Fixture Author",
        }
    ]


@pytest.fixture
def lineage():
    return {
        "source_url": "https://data.gdeltproject.org/gdeltv3/gal/20261003091000.gal.json.gz",
        "raw_file_path": "data/raw/gdelt/2026/10/03/20261003091000.gal.json.gz",
        "sha256": hashlib.sha256(b"offline raw metadata").hexdigest(),
        "source_snapshot_id": "gdelt_20261003_091100Z",
        "data_snapshot_id": "demo_20261003_091100Z",
        "retrieved_at_utc": "2026-10-03T09:11:00Z",
    }


def test_real_gal_field_shape_survives_gzip_json_lines(gal_records):
    body = gzip.compress((json.dumps(gal_records[0]) + "\n\n").encode("utf-8"))
    assert parse_gal_gzip(body, purpose="current_demo") == tuple(gal_records)


def test_gal_ambiguous_date_is_never_promoted_to_original_publication(gal_records, lineage):
    frame = normalize_gal(gal_records, lineage, purpose="current_demo")
    row = frame.iloc[0]
    assert pd.isna(row["published_at"])
    assert row["gdelt_reported_at"] == pd.Timestamp("2026-10-03T09:01:00Z")
    assert row["gdelt_seen_at"] == pd.Timestamp("2026-10-03T09:10:00Z")
    assert row["retrieved_at_utc"] == pd.Timestamp("2026-10-03T09:11:00Z")
    assert row["timestamp_quality_flag"] == "AMBIGUOUS_GAL_DATE"
    assert row["seen_at_quality_flag"] == "ARCHIVE_BATCH_OBSERVATION"
    assert not row["point_in_time_eligible"]
    assert not row["headline_eligible"]
    assert row["usage_scope"] == "current_demo"
    assert row["url"] == "https://example.org/finance/issuer-update?lang=en"
    assert row["publisher_domain"] == "example.org"
    assert row["title"] == gal_records[0]["title"]
    assert row["description"] == gal_records[0]["desc"]
    assert row["outlet_name"] == gal_records[0]["outletName"]
    assert json.loads(row["raw_metadata_json"]) == gal_records[0]
    for key in ("source_url", "raw_file_path", "sha256", "source_snapshot_id", "data_snapshot_id"):
        assert row[key] == lineage[key]


@pytest.mark.parametrize("purpose", ["historical", "headline", "historical_model_b", "", "demo"])
def test_forbidden_usage_fails_before_any_network(gal_records, lineage, purpose):
    class ForbiddenClient:
        def get(self, url):
            pytest.fail("News purpose validation must happen before retrieval")

    with pytest.raises(ValueError, match="current_demo"):
        fetch_gal(ForbiddenClient(), datetime(2026, 10, 3, tzinfo=UTC), purpose=purpose)
    with pytest.raises(ValueError, match="current_demo"):
        normalize_gal(gal_records, lineage, purpose=purpose)
    with pytest.raises(ValueError, match="current_demo"):
        parse_gal_gzip(b"invalid", purpose=purpose)


@pytest.mark.parametrize("bad_date", [None, "", "not-a-time", "2026-10-03T09:01:00"])
def test_missing_or_unzoned_timestamp_preserves_unknown(gal_records, lineage, bad_date):
    gal_records[0]["date"] = bad_date
    row = normalize_gal(gal_records, lineage, purpose="current_demo").iloc[0]
    assert pd.isna(row["published_at"])
    assert pd.isna(row["gdelt_reported_at"])
    assert not row["point_in_time_eligible"]
    assert row["timestamp_quality_flag"] == "INVALID_OR_MISSING"
    assert row["retrieved_at_utc"] != row["published_at"]


def test_optional_article_metadata_does_not_invent_company_matches(lineage):
    frame = normalize_gal([{"date": "2026-10-03T09:01:00Z"}, {}], lineage, purpose="current_demo")
    assert len(frame) == 2
    assert frame["news_id"].is_unique
    for column in (
        "url",
        "title",
        "publisher_domain",
        "matched_entity",
        "security_id",
        "article_text",
    ):
        assert frame[column].isna().all()
    assert frame["published_at"].isna().all()
    assert not frame["point_in_time_eligible"].any()


def test_empty_gal_has_queryable_typed_contract(lineage):
    frame = normalize_gal([], lineage, purpose="current_demo")
    assert frame.empty
    assert frame["published_at"].dtype == "datetime64[ns, UTC]"
    assert frame["retrieved_at_utc"].dtype == "datetime64[ns, UTC]"
    assert frame["news_id"].dtype == "string"
    assert frame["point_in_time_eligible"].dtype == "bool"


def test_duplicate_url_count_is_deterministic(gal_records, lineage):
    original = gal_records[0]
    revised = {**original, "title": "Updated title"}
    first = normalize_gal([original, revised, original], lineage, purpose="current_demo")
    second = normalize_gal([revised, original, original], lineage, purpose="current_demo")
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 1
    assert first.iloc[0]["source_record_count"] == 3


def test_retrieval_and_seen_time_never_change_news_identity(gal_records, lineage):
    first = normalize_gal(gal_records, lineage, purpose="current_demo")
    later = {
        **lineage,
        "source_url": "https://data.gdeltproject.org/gdeltv3/gal/20261003092000.gal.json.gz",
        "retrieved_at_utc": "2026-10-03T09:21:00Z",
    }
    second = normalize_gal(gal_records, later, purpose="current_demo")
    assert first.iloc[0]["news_id"] == second.iloc[0]["news_id"]
    assert pd.isna(first.iloc[0]["published_at"])
    assert pd.isna(second.iloc[0]["published_at"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "missing-hash"),
        ("source_snapshot_id", ""),
        ("raw_file_path", None),
        ("source_url", "https://example.org/20261003091000.gal.json.gz"),
        ("retrieved_at_utc", "2026-10-03T09:11:00"),
        ("retrieved_at_utc", "2026-10-03T09:09:00Z"),
    ],
)
def test_news_requires_valid_source_lineage(gal_records, lineage, field, value):
    with pytest.raises(ValueError):
        normalize_gal(gal_records, {**lineage, field: value}, purpose="current_demo")


@pytest.mark.parametrize(
    "body",
    [
        b"plain JSON",
        # mtime=0 keeps gzip bytes, and so test ids, identical across xdist workers.
        gzip.compress(b"[]\n", mtime=0),
        gzip.compress(b"{oops}\n", mtime=0),
        gzip.compress(b"\xff\n", mtime=0),
    ],
    ids=["plain-json", "gzip-list", "gzip-invalid-json", "gzip-invalid-utf8"],
)
def test_malformed_raw_gal_is_rejected(body):
    with pytest.raises(ValueError):
        parse_gal_gzip(body, purpose="current_demo")


def test_fetch_uses_official_archive_url_without_fetching_article_bodies():
    class FixtureClient:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            return FetchedResponse(b"fixture", url, 200, datetime(2026, 10, 3, 10, tzinfo=UTC))

    client = FixtureClient()
    utc_time = datetime(2026, 10, 3, 9, 10, tzinfo=UTC)
    offset_time = utc_time.astimezone(timezone(timedelta(hours=10)))
    result = fetch_gal(client, offset_time, purpose="current_demo")
    expected = "https://data.gdeltproject.org/gdeltv3/gal/20261003091000.gal.json.gz"
    assert client.urls == [expected]
    assert result.url == expected
    assert gal_archive_url(offset_time) == expected
    with pytest.raises(ValueError, match="timezone"):
        gal_archive_url(datetime(2026, 10, 3))
    with pytest.raises(ValueError, match="minute"):
        gal_archive_url(utc_time + timedelta(seconds=1))

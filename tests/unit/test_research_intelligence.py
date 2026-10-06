"""Offline end-to-end research SEC capture, bounded extraction and gap retention."""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from structural_break.config.models import ProjectConfig
from structural_break.data.http import FetchedResponse, SourceError
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.extraction import ProviderFailure
from structural_break.intelligence.sentiment import (
    FINBERT_MODEL,
    FINBERT_REVISION,
    SENTIMENT_FEATURE_COLUMNS,
)
from structural_break.research.intelligence import (
    METADATA_FEATURE_COLUMNS,
    build_event_intelligence,
    collect_sec_metadata,
    metadata_event_features,
    verify_event_intelligence,
    verify_sec_metadata,
)
from structural_break.research.universe import freeze_universe


@pytest.fixture
def freeze(tmp_path: Path, project_root: Path, config: ProjectConfig) -> Path:
    payload = yaml.safe_load(
        (project_root / "configs/research_v2_universe.yaml").read_text(encoding="utf-8")
    )
    payload["groups"] = [payload["groups"][0]]
    payload["groups"][0]["tickers"] = ["KO", "PEP", "KDP"]
    payload["issuer_rules"] = {}
    path = tmp_path / "small_roster.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config_payload = config.model_dump(mode="json")
    config_payload["universe"]["pairs"] = config_payload["universe"]["pairs"][:1]
    small = ProjectConfig.model_validate(config_payload)
    directory = json.dumps(
        {
            str(i): {"ticker": ticker, "cik_str": 9000000 + i, "title": f"Fixture {ticker}"}
            for i, ticker in enumerate(("KO", "PEP", "KDP"))
        }
    ).encode()
    output = tmp_path / "freeze"
    freeze_universe(path, small, directory, output)
    return output


def source(gets: list[str], *, missing_acceptance: bool = False, fail_cik: str | None = None):
    def get(url: str) -> FetchedResponse:
        gets.append(url)
        match = re.search(r"CIK(\d{10})", url)
        if match:
            cik = match[1]
            if cik == fail_cik:
                raise SourceError(url, 403)
            if "-submissions-" in url:
                payload = {
                    "accessionNumber": [f"{cik}-10-000001"],
                    "form": ["10-K"],
                    "filingDate": ["2010-02-01"],
                    "reportDate": ["2009-12-31"],
                    "acceptanceDateTime": ["2010-02-01T16:30:00-05:00"],
                    "primaryDocument": ["report.htm"],
                }
            else:
                recent = {
                    "accessionNumber": [f"{cik}-22-000001", f"{cik}-22-000002"],
                    "form": ["10-K", "8-K"],
                    "filingDate": ["2022-02-01", "2022-03-08"],
                    "reportDate": ["2021-12-31", "2022-03-08"],
                    "acceptanceDateTime": [
                        "2022-02-01T16:30:00-05:00",
                        None if missing_acceptance else "2022-03-08T16:30:00-05:00",
                    ],
                    "primaryDocument": ["report.htm", "report.htm"],
                }
                payload = {
                    "cik": int(cik),
                    "filings": {
                        "recent": recent,
                        "files": [
                            {
                                "name": f"CIK{cik}-submissions-001.json",
                                "filingFrom": "2004-01-01",
                                "filingTo": "2015-12-31",
                            }
                        ],
                    },
                }
            body = json.dumps(payload).encode()
        elif url.endswith("index.json"):
            body = json.dumps(
                {"directory": {"item": [{"name": "report.htm", "type": "file"}]}}
            ).encode()
        elif url.endswith(".txt"):
            form = "8-K" if "22000002" in url else "10-K"
            body = (
                "<DOCUMENT>\n<TYPE>" + form + "\n<SEQUENCE>1\n<FILENAME>report.htm\n<TEXT>"
                "<html><body><h1>Item 7 Financial results</h1><p>Quarterly earnings and revenue "
                "increased substantially. Net income increased 20 percent.</p></body></html>"
                "</TEXT>\n</DOCUMENT>"
            ).encode()
        else:
            body = (
                b"<html><body><h1>Item 7 Financial results</h1><p>Quarterly earnings and revenue "
                b"increased substantially. Net income increased 20 percent.</p></body></html>"
            )
        return FetchedResponse(body, url, 200, datetime(2026, 10, 6, tzinfo=UTC))

    return get


def event_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"event_id": "later", "pair_id": "KO__PEP", "event_timestamp": "2022-03-12T21:00:00Z"},
            {
                "event_id": "earlier",
                "pair_id": "KO__PEP",
                "event_timestamp": "2022-03-10T21:00:00Z",
            },
        ]
    )


class Tone:
    model_name, model_revision = FINBERT_MODEL, FINBERT_REVISION

    def token_ids(self, text: str) -> list[int]:
        return list(range(1, len(text.split()) + 1))

    def predict(self, windows: list[list[int]]) -> list[dict[str, float]]:
        return [{"positive": 0.7, "negative": 0.1, "neutral": 0.2} for _ in windows]


def provider(calls: list[str]):
    def call(request: dict[str, Any]) -> dict[str, Any]:
        pack = json.loads(request["messages"][1]["content"])
        calls.append(pack["event_id"])
        chunk = next(chunk for chunk in pack["chunks"] if chunk["leg"] == "A")
        return {
            "event_type": "EARNINGS",
            "affected_leg": "A",
            "direction": "POSITIVE",
            "materiality": "MEDIUM",
            "relationship_relevance": "INDIRECT",
            "extraction_confidence": 0.8,
            "citations": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "leg": "A",
                    "quote": "Quarterly earnings and revenue increased substantially.",
                }
            ],
        }

    return call


def test_metadata_fetches_history_preserves_missing_acceptance_and_replays(
    freeze: Path, tmp_path: Path
) -> None:
    gets: list[str] = []
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(freeze, output, get=source(gets, missing_acceptance=True))
    assert len(gets) == 6 and manifest["filing_count"] == 9
    assert manifest["missing_acceptance_count"] == 3
    filings = pd.read_parquet(output / "filings.parquet")
    assert len(filings.loc[filings.filing_date.eq(date(2010, 2, 1))]) == 3
    assert not filings.loc[filings.acceptance_datetime_utc.isna(), "point_in_time_eligible"].any()
    assert verify_sec_metadata(output, freeze) == manifest
    assert (
        collect_sec_metadata(freeze, output, get=lambda _: pytest.fail("Must replay cache"))
        == manifest
    )


def test_metadata_limit_and_failed_source_are_explicit_not_complete(
    freeze: Path, tmp_path: Path
) -> None:
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(
        freeze, output, max_issuers=2, get=source([], fail_cik="0009000002")
    )
    coverage = json.loads((output / "coverage.json").read_bytes())
    assert {row["status"] for row in coverage} == {"OK", "UNKNOWN", "NOT_SCHEDULED"}
    assert manifest["complete_source_issuer_count"] == 1


def test_bounded_event_pipeline_has_all48_features_and_keeps_every_event(
    freeze: Path, tmp_path: Path
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    calls: list[str] = []
    output = tmp_path / "intelligence"
    manifest = build_event_intelligence(
        event_rows(),
        freeze,
        metadata_dir,
        output,
        provider=provider(calls),
        get=source([]),
        sentiment_backend=Tone(),
        max_events=1,
        event_registry_id="fixture-events",
    )
    assert calls == ["earlier"] and manifest["event_count"] == 2
    assert manifest["scheduled_event_count"] == 1
    assert len(manifest["feature_columns"]) == 62
    frame = pd.read_parquet(output / "features.parquet").set_index("event_id")
    assert frame.loc["earlier", "event_type_EARNINGS"] == 1
    assert frame.loc["later", "event_type_UNKNOWN"] == 1
    assert frame.loc["earlier", "sentiment_both_known"] == 1
    assert frame.loc["later", "sentiment_a_unknown"] == 1
    assert frame.loc["earlier", "sentiment_net_contrast"] == 0
    assert set(EVENT_FEATURE_NAMES + SENTIMENT_FEATURE_COLUMNS).issubset(frame.columns)
    assert verify_event_intelligence(output, freeze, metadata_dir) == manifest
    repeat = build_event_intelligence(
        event_rows(),
        freeze,
        metadata_dir,
        output,
        provider=provider(calls),
        get=lambda _: pytest.fail("Must replay"),
        sentiment_backend=Tone(),
        max_events=1,
        event_registry_id="fixture-events",
    )
    assert repeat == manifest and calls == ["earlier"]


def test_quota_keeps_rows_and_does_not_hide_tone_features(freeze: Path, tmp_path: Path) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    calls: list[str] = []

    def limited(request: dict[str, Any]) -> str:
        calls.append("request")
        raise ProviderFailure("PROVIDER_QUOTA_OR_RATE_LIMIT", retriable=False)

    output = tmp_path / "intelligence"
    manifest = build_event_intelligence(
        event_rows(),
        freeze,
        metadata_dir,
        output,
        provider=limited,
        get=source([]),
        sentiment_backend=Tone(),
    )
    assert manifest["catalyst_counts"] == {"UNKNOWN": 2}
    frame = pd.read_parquet(output / "features.parquet")
    assert frame.sentiment_both_known.eq(1).all() and frame.event_type_UNKNOWN.eq(1).all()
    audit = json.loads((output / "coverage.json").read_bytes())
    assert all(row["reason_codes"] == ["PROVIDER_QUOTA_OR_RATE_LIMIT"] for row in audit)


@pytest.mark.parametrize("mutation", ["target", "score", "future", "orientation", "duplicate"])
def test_unsafe_events_rejected_before_source_or_provider(
    freeze: Path, tmp_path: Path, mutation: str
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    events = event_rows()
    if mutation == "target":
        events["y_revert_success"] = 1
    elif mutation == "score":
        events["raw_probability"] = 0.9
    elif mutation == "future":
        events.loc[0, "event_timestamp"] = "2024-03-10T21:00:00Z"
    elif mutation == "orientation":
        events["leg_a"] = "PEP"
    else:
        events.loc[0, "event_id"] = "earlier"
    with pytest.raises(ValueError):
        build_event_intelligence(
            events,
            freeze,
            metadata_dir,
            tmp_path / "bad",
            provider=None,
            get=lambda _: pytest.fail("Must not call source"),
        )


@pytest.mark.parametrize("target", ["metadata", "raw_body", "features", "checkpoint"])
def test_tampered_inputs_or_outputs_fail_verification(
    freeze: Path, tmp_path: Path, target: str
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    output = tmp_path / "intelligence"
    build_event_intelligence(
        event_rows(),
        freeze,
        metadata_dir,
        output,
        provider=provider([]),
        get=source([]),
        sentiment_backend=Tone(),
        max_events=1,
    )
    paths = {
        "metadata": metadata_dir / "filings.parquet",
        "features": output / "features.parquet",
        "checkpoint": next((output / "events").glob("*.json")),
        "raw_body": next((output / "data/raw/sec/filings").glob("**/primary_document.html")),
    }
    path = paths[target]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_event_intelligence(output, freeze, metadata_dir)


def test_final_test_metadata_dates_never_reach_source(freeze: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="2023"):
        collect_sec_metadata(
            freeze,
            tmp_path / "bad",
            end=date(2024, 1, 1),
            get=lambda _: pytest.fail("Must not call source"),
        )


def test_metadata_missing_timestamps_prevent_none(freeze: Path, tmp_path: Path) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([], missing_acceptance=True))

    def none(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_type": "NONE",
            "affected_leg": "NONE",
            "direction": "UNKNOWN",
            "materiality": "UNKNOWN",
            "relationship_relevance": "NONE",
            "extraction_confidence": 0.5,
            "citations": [],
        }

    output = tmp_path / "intelligence"
    build_event_intelligence(
        event_rows(), freeze, metadata_dir, output, provider=none, get=source([]), max_events=1
    )
    assert pd.read_parquet(output / "features.parquet").event_type_UNKNOWN.eq(1).all()


def test_provider_config_credentials_do_not_enter_checkpoint(freeze: Path, tmp_path: Path) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    output = tmp_path / "bad"
    with pytest.raises(ValueError, match="credentials"):
        build_event_intelligence(
            event_rows(),
            freeze,
            metadata_dir,
            output,
            provider=None,
            provider_config={"api_key": "must-stay-secret"},
        )
    assert not (output / "inputs.json").exists()


def test_current_cik_inventory_cannot_prove_absence_before_first_observed_filing(
    freeze: Path, tmp_path: Path
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    events = event_rows().iloc[:1].copy()
    events["event_timestamp"] = "2006-03-10T21:00:00Z"
    output = tmp_path / "early"
    build_event_intelligence(
        events,
        freeze,
        metadata_dir,
        output,
        provider=None,
        sentiment_backend=Tone(),
        get=lambda _: pytest.fail("No accepted filing should be downloaded"),
    )
    row = pd.read_parquet(output / "features.parquet").iloc[0]
    assert row.sec_a_metadata_coverage_unknown == row.sec_b_metadata_coverage_unknown == 1
    assert pd.isna(row.sec_a_recent_8k_count_30d)
    assert row.event_type_UNKNOWN == 1
    assert verify_event_intelligence(output, freeze, metadata_dir)["event_count"] == 1


def test_metadata_features_exclude_future_items_and_keep_missing_items_unknown(
    freeze: Path, tmp_path: Path
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    filings = pd.read_parquet(metadata_dir / "filings.parquet")
    filings["items"] = None
    future = filings.loc[filings.form.eq("8-K")].copy()
    future["acceptance_datetime_utc"] = pd.Timestamp("2022-03-11T21:00:00Z")
    future["filing_id"] = future["filing_id"].str.replace("000002", "000003")
    future["items"] = "2.02,5.02"
    augmented = pd.concat([filings, future], ignore_index=True)
    event = {
        "event_id": "earlier",
        "pair_id": "KO__PEP",
        "event_timestamp": "2022-03-10T21:00:00Z",
        "evidence_cutoff": "2022-03-10T21:00:00Z",
        "leg_a_security_id": "US:KO",
        "leg_b_security_id": "US:PEP",
    }
    coverage = {
        row["security_id"]: row for row in json.loads((metadata_dir / "coverage.json").read_bytes())
    }
    original = metadata_event_features(event, filings, coverage)
    assert metadata_event_features(event, augmented, coverage) == original
    assert set(original) == set(METADATA_FEATURE_COLUMNS)
    assert original["sec_a_recent_8k_count_30d"] == 1
    assert original["sec_a_recent_items_2_02_earnings"] is None


def test_new_generation_reuses_shared_verified_sources_and_inference(
    freeze: Path, tmp_path: Path
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    cache = tmp_path / "shared"
    calls: list[str] = []
    for batch in ("first", "second"):
        manifest = build_event_intelligence(
            event_rows(),
            freeze,
            metadata_dir,
            tmp_path / batch,
            provider=provider(calls),
            sentiment_backend=Tone(),
            cache_workspace=cache,
            get=source([]) if batch == "first" else lambda _: pytest.fail("Reuse raw sources"),
        )
        assert manifest["inputs"]["shared_cache_workspace"] is True
        assert (
            verify_event_intelligence(tmp_path / batch, freeze, metadata_dir, cache_workspace=cache)
            == manifest
        )
    assert calls == ["earlier", "later"]
    with pytest.raises(ValueError, match="explicit shared cache"):
        verify_event_intelligence(tmp_path / "second", freeze, metadata_dir)
    body = next((cache / "data/raw/sec/filings").glob("**/primary_document.html"))
    body.write_bytes(body.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_event_intelligence(tmp_path / "second", freeze, metadata_dir, cache_workspace=cache)

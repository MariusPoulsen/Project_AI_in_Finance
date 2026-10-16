"""Offline end-to-end research SEC capture, bounded extraction and gap retention."""

import hashlib
import json
import re
import threading
import weakref
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse, SourceError
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.extraction import (
    CatalystResponse,
    ProviderFailure,
    extract_pack,
    validate_response,
)
from structural_break.intelligence.sentiment import (
    FINBERT_ASSETS_SHA256,
    FINBERT_MODEL,
    FINBERT_REVISION,
    QUALITY_PREPROCESSING_VERSION,
    SENTIMENT_FEATURE_COLUMNS,
    FinBERTPolicy,
)
from structural_break.research import intelligence
from structural_break.research.intelligence import (
    METADATA_FEATURE_COLUMNS,
    build_event_intelligence,
    collect_sec_metadata,
    metadata_event_features,
    verify_event_intelligence,
    verify_sec_metadata,
)
from structural_break.research.parsing_cache import OperationParsingCache
from structural_break.research.parsing_workers import VerificationParsingPool
from structural_break.research.universe import freeze_universe
from structural_break.storage.files import sha256_file


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


def checkpoint_path(output: Path, event_id: str) -> Path:
    return output / "events" / (hashlib.sha256(event_id.encode()).hexdigest() + ".json")


def test_empty_recent_clock_keeps_valid_periodic_text_and_prevents_absence_claims(
    freeze: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata, output, workspace = tmp_path / "metadata", tmp_path / "output", tmp_path / "cache"
    collect_sec_metadata(freeze, metadata, get=source([]))
    raw_get = source([])
    excluded = "0009000000-22-000002"

    def clocked_get(url: str) -> FetchedResponse:
        response = raw_get(url)
        empty = excluded in url
        body = response.body
        if url.endswith(".txt"):
            header = (
                b"<ACCEPTANCE-DATETIME>\n\nACCESSION NUMBER: preserved\n"
                if empty
                else b"<ACCEPTANCE-DATETIME>20220308163000\n"
                if "22000002" in url
                else b"<ACCEPTANCE-DATETIME>20220201163000\n"
            )
            body = header + body
        if empty:
            body = body.replace(b"Quarterly earnings", b"FORBIDDEN_UNTIMED_TEXT earnings")
        return FetchedResponse(body, response.url, response.status_code, response.retrieved_at)

    original_parse = intelligence.parse_documents

    def checked_parse(documents, policy):
        assert all(document["filing_id"] != excluded for document in documents)
        return original_parse(documents, policy)

    class CheckedTone(Tone):
        def token_ids(self, text: str) -> list[int]:
            assert "FORBIDDEN_UNTIMED_TEXT" not in text
            return super().token_ids(text)

    monkeypatch.setattr(intelligence, "parse_documents", checked_parse)
    manifest = build_event_intelligence(
        event_rows(),
        freeze,
        metadata,
        output,
        provider=None,
        sentiment_backend=CheckedTone(),
        cache_workspace=workspace,
        get=clocked_get,
    )
    assert manifest["event_count"] == 2 and manifest["all_events_retained"] is True
    record = json.loads(checkpoint_path(output, "earlier").read_bytes())
    pack = record["pack"]
    assert record["selected_filing_count"] == len(pack["selected_filing_ids"]) == 4
    assert excluded in pack["selected_filing_ids"]
    gap = pack["coverage"]["A"]
    assert gap["status"] == "PARTIAL" and gap["empty_acceptance_filing_ids"] == [excluded]
    assert gap["failed_filing_ids"] == [excluded]
    assert pack["coverage"]["B"]["status"] == "COMPLETE"
    assert {chunk["leg"] for chunk in pack["chunks"]} == {"A", "B"}
    assert all(chunk["filing_id"] != excluded for chunk in pack["chunks"])
    assert record["tone"]["legs"]["A"]["status"] == "PARTIAL"
    assert record["tone"]["legs"]["A"]["source_coverage_status"] == "PARTIAL"
    assert record["tone"]["legs"]["B"]["status"] == "SUCCESS"
    none = CatalystResponse(
        event_type="NONE",
        affected_leg="NONE",
        direction="UNKNOWN",
        materiality="UNKNOWN",
        relationship_relevance="NONE",
        extraction_confidence=None,
        citations=[],
    )
    with pytest.raises(ValueError, match="cannot establish NONE"):
        validate_response(none, pack)

    def supported_other_leg(request: dict[str, Any]) -> dict[str, Any]:
        evidence = json.loads(request["messages"][1]["content"])
        assert "FORBIDDEN_UNTIMED_TEXT" not in request["messages"][1]["content"]
        chunk = next(chunk for chunk in evidence["chunks"] if chunk["leg"] == "B")
        return {
            "event_type": "EARNINGS",
            "affected_leg": "B",
            "direction": "POSITIVE",
            "materiality": "MEDIUM",
            "relationship_relevance": "INDIRECT",
            "extraction_confidence": 0.8,
            "citations": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "leg": "B",
                    "quote": "Quarterly earnings and revenue increased substantially.",
                }
            ],
        }

    extraction = extract_pack(
        pack, supported_other_leg, tmp_path / "fixture_extraction", "fixture", "fixture"
    )
    assert extraction["status"] == "SUCCESS" and extraction["one_sided_event"] is False
    features = pd.read_parquet(output / "features.parquet").set_index("event_id")
    assert features.loc["earlier", "sec_a_recent_8k_count_30d"] == 1
    assert features.loc["earlier", "sec_a_metadata_coverage_unknown"] == 0


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
    observed: list[dict[str, Any]] = []
    assert (
        verify_event_intelligence(output, freeze, metadata_dir, progress=observed.append)
        == manifest
    )
    assert observed[0]["stage"] == "SOURCE_INPUT_BINDINGS"
    assert observed[-1]["stage"] == "SOURCE_VERIFICATION_COMPLETE"
    assert observed[-1]["verified_source_events"] == observed[-1]["total_source_events"] == 2
    assert all("y_revert_success" not in record for record in observed)
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


@pytest.mark.parametrize("max_events", [None, 1])
def test_source_prefetch_matches_cold_serial_bytes(
    freeze: Path, tmp_path: Path, max_events: int | None
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    manifests = []
    outputs = []
    call_sequences = []
    for enabled in (False, True):
        output = tmp_path / str(enabled)
        outputs.append(output)
        calls: list[str] = []
        call_sequences.append(calls)
        manifests.append(
            build_event_intelligence(
                event_rows(),
                freeze,
                metadata,
                output,
                provider=provider(calls),
                get=source([]),
                sentiment_backend=Tone(),
                max_events=max_events,
                cache_workspace=tmp_path / (str(enabled) + "_cache"),
                source_prefetch=enabled,
            )
        )
    assert manifests[0] == manifests[1]
    assert (
        call_sequences[0]
        == call_sequences[1]
        == (["earlier", "later"] if max_events is None else ["earlier"])
    )
    assert "source_prefetch" not in manifests[0]["inputs"]
    for filename in [*manifests[0]["files"], "manifest.json"]:
        assert (outputs[0] / filename).read_bytes() == (outputs[1] / filename).read_bytes()


def test_source_prefetch_overlaps_one_next_event_and_confines_owners(
    freeze: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    output = tmp_path / "intelligence"
    events = pd.concat(
        [
            event_rows(),
            pd.DataFrame(
                [
                    {
                        "event_id": "third",
                        "pair_id": "KO__PEP",
                        "event_timestamp": "2022-03-14T21:00Z",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    coordinator = threading.get_ident()
    next_started, inference_started = threading.Event(), threading.Event()
    source_events: list[str] = []
    http_owners: list[int] = []
    cache_owners: list[list[int]] = []
    extraction_events: list[str] = []
    event_pack, extraction, write = (
        intelligence._event_pack,
        intelligence.extract_pack,
        intelligence.write_bytes,
    )

    class OwnedCache(OperationParsingCache):
        def __init__(self) -> None:
            super().__init__()
            self.owners = [threading.get_ident()]
            cache_owners.append(self.owners)

        def close(self) -> None:
            self.owners.append(threading.get_ident())
            super().close()

    class OwnedHttp:
        def __init__(self, *_args, **_kwargs) -> None:
            http_owners.append(threading.get_ident())

        def get(self, url: str) -> FetchedResponse:
            assert threading.get_ident() == http_owners[0] != coordinator
            return source([])(url)

    def prepare(event, *args, **kwargs):
        if threading.get_ident() != coordinator:
            source_events.append(event["event_id"])
            if event["event_id"] == "later":
                next_started.set()
                assert inference_started.wait(5), "Source and model work did not overlap"
            elif event["event_id"] == "third":
                assert checkpoint_path(output, "earlier").exists(), "Prefetched beyond next event"
        return event_pack(event, *args, **kwargs)

    def extract(pack, *args, **kwargs):
        assert threading.get_ident() == coordinator
        extraction_events.append(pack["event_id"])
        return extraction(pack, *args, **kwargs)

    def publish(path, body):
        if path.parent.name == "events":
            assert threading.get_ident() == coordinator
        return write(path, body)

    class CoordinatedTone(Tone):
        def predict(self, windows):
            assert threading.get_ident() == coordinator
            if not inference_started.is_set():
                assert next_started.wait(5), "Next event was not prepared during inference"
                inference_started.set()
            return super().predict(windows)

    monkeypatch.setattr(intelligence, "OperationParsingCache", OwnedCache)
    monkeypatch.setattr(intelligence, "HttpClient", OwnedHttp)
    monkeypatch.setattr(intelligence, "_event_pack", prepare)
    monkeypatch.setattr(intelligence, "extract_pack", extract)
    monkeypatch.setattr(intelligence, "write_bytes", publish)
    manifest = build_event_intelligence(
        events,
        freeze,
        metadata,
        output,
        provider=None,
        sentiment_backend=CoordinatedTone(),
        source_prefetch=True,
    )
    assert source_events == extraction_events == ["earlier", "later", "third"]
    assert http_owners == [cache_owners[0][0]]
    assert len(cache_owners) == 2  # Source owner, then fresh independent verifier.
    assert all(len(owners) == 2 and owners[0] == owners[1] for owners in cache_owners)
    assert cache_owners[0][0] != coordinator == cache_owners[1][0]
    assert [
        json.loads((output / row["file"]).read_bytes())["event"]["event_id"]
        for row in manifest["source_identity"]["records"]
    ] == source_events


@pytest.mark.parametrize("failure_owner", ["source", "coordinator"])
def test_source_prefetch_errors_stop_in_order_and_close_source_cache(
    freeze: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_owner: str
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    output = tmp_path / "intelligence"
    coordinator = threading.get_ident()
    next_started, release_source = threading.Event(), threading.Event()
    source_events: list[str] = []
    caches: list[OperationParsingCache] = []
    event_pack, extraction = intelligence._event_pack, intelligence.extract_pack

    class OwnedCache(OperationParsingCache):
        def __init__(self) -> None:
            super().__init__()
            self.owner = threading.get_ident()
            caches.append(self)

        def close(self) -> None:
            assert threading.get_ident() == self.owner != coordinator
            super().close()

    def prepare(event, *args, **kwargs):
        assert threading.get_ident() != coordinator
        source_events.append(event["event_id"])
        if event["event_id"] == "later":
            next_started.set()
            if failure_owner == "source":
                raise ValueError("source failure")
            assert release_source.wait(5)
        return event_pack(event, *args, **kwargs)

    def extract(pack, *args, **kwargs):
        assert threading.get_ident() == coordinator
        assert pack["event_id"] == "earlier", "Future error was not propagated in order"
        assert next_started.wait(5)
        if failure_owner == "coordinator":
            release_source.set()
            raise ValueError("coordinator failure")
        return extraction(pack, *args, **kwargs)

    monkeypatch.setattr(intelligence, "OperationParsingCache", OwnedCache)
    monkeypatch.setattr(intelligence, "_event_pack", prepare)
    monkeypatch.setattr(intelligence, "extract_pack", extract)
    with pytest.raises(ValueError, match=failure_owner + " failure"):
        build_event_intelligence(
            event_rows(),
            freeze,
            metadata,
            output,
            provider=None,
            sentiment_backend=Tone(),
            get=source([]),
            source_prefetch=True,
        )
    assert source_events == ["earlier", "later"]
    assert checkpoint_path(output, "earlier").exists() == (failure_owner == "source")
    assert not checkpoint_path(output, "later").exists()
    assert not (output / "manifest.json").exists()
    assert len(caches) == 1 and caches[0]._closed and not caches[0]._directory.exists()
    assert not any(thread.name.startswith("sec-source") for thread in threading.enumerate())


def test_source_prefetch_cannot_queue_or_consume_another_event_early() -> None:
    started, release = threading.Event(), threading.Event()

    def prepare(index, _cache):
        started.set()
        assert release.wait(5)
        return {"event_index": index}, 0

    with intelligence._SourcePackPreparation(prepare, enabled=True) as preparation:
        preparation.prefetch(0)
        assert started.wait(5)
        try:
            with pytest.raises(RuntimeError, match="Only one"):
                preparation.prefetch(1)
            with pytest.raises(RuntimeError, match="event order"):
                preparation.get(1)
        finally:
            release.set()
        assert preparation.get(0) == ({"event_index": 0}, 0)


@pytest.mark.parametrize("checkpoint_count", [1, 2])
def test_source_prefetch_reuses_sha_audited_checkpoints_without_source_or_inference(
    freeze: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint_count: int
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    workspace, old, new = tmp_path / "cache", tmp_path / "old", tmp_path / "new"
    baseline, audit = tmp_path / "baseline.json", tmp_path / "audit.json"
    raw_get = source([])

    def clocked_source(url: str) -> FetchedResponse:
        response = raw_get(url)
        if url.endswith(".txt"):
            clock = b"20220308163000" if "22000002" in url else b"20220201163000"
            return FetchedResponse(
                b"<ACCEPTANCE-DATETIME>" + clock + b"\n" + response.body,
                response.url,
                response.status_code,
                response.retrieved_at,
            )
        return response

    class AssetBoundTone(Tone):
        runtime = {"model_assets_sha256": dict(FINBERT_ASSETS_SHA256)}

    settings = {
        "provider": None,
        "sentiment_backend": AssetBoundTone(),
        "sentiment_policy": FinBERTPolicy(preprocessing_version=QUALITY_PREPROCESSING_VERSION),
        "cache_workspace": workspace,
        "catalyst_max_events": 1,
        "event_registry_id": "frozen-registry-fixture",
    }
    original = build_event_intelligence(
        event_rows(), freeze, metadata, old, get=clocked_source, **settings
    )
    (old / "manifest.json").unlink()
    if checkpoint_count == 1:
        checkpoint_path(old, "later").unlink()
    baseline.write_bytes(
        intelligence.json_bytes(
            {
                "recorded_processes_absent": True,
                "checkpoint_count": checkpoint_count,
                "inputs_sha256": sha256_file(old / "inputs.json"),
                "catalyst_schedule_sha256": sha256_file(old / "catalyst_schedule.json"),
                "checkpoint_inventory": [
                    {
                        "filename": path.name,
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
                    for path in sorted((old / "events").iterdir())
                ],
            }
        )
    )
    build_event_intelligence(
        event_rows(),
        freeze,
        metadata,
        new,
        checkpoint_source=old,
        checkpoint_baseline=baseline,
        checkpoint_baseline_sha256=sha256_file(baseline),
        audit_output=audit,
        source_prefetch=True,
        **settings,
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Audited checkpoints must not prepare sources or run inference")

    source_events: list[str] = []
    raw_pack = intelligence._event_pack

    def fresh_source(event, *args, **kwargs):
        assert checkpoint_count == 1 and event["event_id"] == "later"
        source_events.append(event["event_id"])
        return raw_pack(event, *args, **kwargs)

    monkeypatch.setattr(intelligence, "_event_pack", fresh_source)
    for name in ("extract_pack", "score_sentiment_pack", "validate_sentiment_result"):
        original_operation = getattr(intelligence, name)

        def only_fresh_event(event_or_pack, *args, operation=original_operation, **kwargs):
            assert checkpoint_count == 1 and event_or_pack["event_id"] == "later", (
                "Audited event must not replay sources or inference"
            )
            return operation(event_or_pack, *args, **kwargs)

        monkeypatch.setattr(intelligence, name, only_fresh_event)
    monkeypatch.setattr(AssetBoundTone, "predict", forbidden)
    result = build_event_intelligence(
        event_rows(),
        freeze,
        metadata,
        new,
        get=forbidden,
        resume_audit=audit,
        resume_audit_sha256=sha256_file(audit),
        source_prefetch=True,
        **settings,
    )
    assert result["inputs"] == original["inputs"]
    assert result["source_identity"] == original["source_identity"]
    assert result["event_count"] == 2
    assert source_events == (["later"] if checkpoint_count == 1 else [])
    assert result["checkpoint_recovery"]["independent_full_raw_verification_complete"] is False
    assert result["files"] == original["files"]
    for filename in original["files"]:
        if (old / filename).exists():
            assert (old / filename).read_bytes() == (new / filename).read_bytes()


def test_operation_spill_parses_once_and_independent_verifier_starts_fresh(
    freeze: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    output = tmp_path / "intelligence"
    caches: list[OperationParsingCache] = []
    parse_keys: list[list[str]] = []
    spill_reads: list[int] = []
    active: list[int] = []
    parse = intelligence.parse_documents

    class OneHotCache(OperationParsingCache):
        def __init__(self) -> None:
            assert not active, "Builder cache must close before independent verifier starts"
            super().__init__(max_hot_frames=1)
            self.operation_index = len(caches)
            caches.append(self)
            parse_keys.append([])
            spill_reads.append(0)

        def __enter__(self):
            active.append(self.operation_index)
            return super().__enter__()

        def __getitem__(self, key: str) -> pd.DataFrame:
            if key not in self._hot:
                spill_reads[self.operation_index] += 1
            return super().__getitem__(key)

        def __exit__(self, *args: Any) -> None:
            super().__exit__(*args)
            active.pop()

    def tracked_parse(documents, policy):
        assert active, "Every operation must own an empty, scoped parsing cache"
        parse_keys[active[-1]].append(intelligence._sha(documents))
        return parse(documents, policy)

    monkeypatch.setattr(intelligence, "OperationParsingCache", OneHotCache)
    monkeypatch.setattr(intelligence, "parse_documents", tracked_parse)
    manifest = build_event_intelligence(
        event_rows(), freeze, metadata_dir, output, provider=None, get=source([])
    )
    assert len(caches) == 2  # builder and its fully independent raw verifier
    assert verify_event_intelligence(output, freeze, metadata_dir) == manifest
    assert len(caches) == 3
    assert len(parse_keys[0]) > 1  # every pass must force genuine hot-frame eviction
    assert parse_keys[0] == parse_keys[1] == parse_keys[2]
    assert all(len(keys) == len(set(keys)) for keys in parse_keys)
    assert all(reads > 0 for reads in spill_reads)
    assert all(cache._closed and not cache._directory.exists() for cache in caches)
    assert not active
    frame = pd.read_parquet(output / "features.parquet")
    assert frame.sentiment_a_unknown.eq(1).all() and frame.sentiment_b_unknown.eq(1).all()


def test_raw_source_tampering_is_checked_before_reusing_a_parsed_cache_hit(
    freeze: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata_dir = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata_dir, get=source([]))
    output = tmp_path / "intelligence"
    event_pack = intelligence._event_pack
    calls = 0
    caches: list[OperationParsingCache] = []

    class TrackedCache(OperationParsingCache):
        def __init__(self) -> None:
            super().__init__()
            caches.append(self)

    def mutate_before_second_event(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            assert caches[0].entry_count > 0
            body = next((output / "data/raw/sec/filings").glob("**/primary_document.html"))
            body.write_bytes(body.read_bytes() + b"changed source")
        return event_pack(*args, **kwargs)

    monkeypatch.setattr(intelligence, "OperationParsingCache", TrackedCache)
    monkeypatch.setattr(intelligence, "_event_pack", mutate_before_second_event)
    with pytest.raises(ValueError, match="hash mismatch|checksum"):
        build_event_intelligence(
            event_rows(), freeze, metadata_dir, output, provider=None, get=source([])
        )
    assert calls == 2 and len(caches) == 1
    assert caches[0]._closed and not caches[0]._directory.exists()
    assert not (output / "manifest.json").exists()


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
    with pytest.raises(ValueError, match="checksum|hash mismatch"):
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


def test_balanced_catalyst_pilot_reuses_caches_without_filling_unscheduled_catalysts(
    freeze: Path, tmp_path: Path
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    shared_cache = tmp_path / "shared-cache"
    first = tmp_path / "all-catalysts"
    calls: list[str] = []
    build_event_intelligence(
        event_rows(),
        freeze,
        metadata,
        first,
        provider=provider(calls),
        sentiment_backend=Tone(),
        get=source([]),
        cache_workspace=shared_cache,
        catalyst_max_events=2,
        max_retries=1,
    )
    assert len(calls) == 2

    class CachedTone(Tone):
        def predict(self, windows: list[list[int]]) -> list[dict[str, float]]:
            pytest.fail("Successful FinBERT windows must be reused")

    second = tmp_path / "small-pilot"
    manifest = build_event_intelligence(
        event_rows().iloc[::-1],
        freeze,
        metadata,
        second,
        provider=lambda _: pytest.fail("Scheduled successful Gemma result must be reused"),
        sentiment_backend=CachedTone(),
        get=lambda _: pytest.fail("Verified sources must be reused"),
        cache_workspace=shared_cache,
        catalyst_max_events=1,
        max_retries=1,
    )
    schedule = json.loads((second / "catalyst_schedule.json").read_bytes())
    selected = schedule["selected_event_ids"]
    assert len(selected) == manifest["catalyst_scheduled_event_count"] == 1
    assert manifest["scheduled_event_count"] == 2
    assert manifest["catalyst_call_upper_bound"] == 2
    frame = pd.read_parquet(second / "features.parquet").set_index("event_id")
    assert frame.loc[selected[0], "event_type_EARNINGS"] == 1
    assert frame.drop(index=selected).event_type_UNKNOWN.eq(1).all()
    assert frame.sentiment_both_known.eq(1).all()
    assert frame.sec_a_recent_8k_count_30d.eq(1).all()
    assert (
        verify_event_intelligence(second, freeze, metadata, cache_workspace=shared_cache)
        == manifest
    )
    for checkpoint in (second / "events").glob("*.json"):
        row = json.loads(checkpoint.read_bytes())
        assert row["pack"]["chunks"]
        assert bool(row["catalyst_pack"]["chunks"]) is row["catalyst_scheduled"]


def test_catalyst_retry_reservation_keeps_actual_calls_within_frozen_budget(
    freeze: Path, tmp_path: Path
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    calls: list[str] = []
    successful = provider(calls)

    class Limited:
        max_calls = 2

        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                raise ProviderFailure("PROVIDER_UNAVAILABLE", retriable=True)
            return successful(request)

    limited = Limited()
    output = tmp_path / "pilot"
    manifest = build_event_intelligence(
        event_rows(),
        freeze,
        metadata,
        output,
        provider=limited,
        get=source([]),
        sentiment_backend=Tone(),
        max_retries=1,
    )
    assert limited.calls == 2
    assert manifest["catalyst_selected_event_count"] == 1
    assert manifest["catalyst_call_upper_bound"] == 2
    assert pd.read_parquet(output / "features.parquet").sentiment_both_known.eq(1).all()


def test_schedule_is_reconstructed_even_if_its_file_checksum_is_resealed(
    freeze: Path, tmp_path: Path
) -> None:
    import hashlib

    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    output = tmp_path / "pilot"
    build_event_intelligence(
        event_rows(),
        freeze,
        metadata,
        output,
        provider=provider([]),
        get=source([]),
        catalyst_max_events=1,
    )
    schedule_path = output / "catalyst_schedule.json"
    schedule = json.loads(schedule_path.read_bytes())
    schedule["selected_event_ids"] = ["event-outside-registry"]
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["catalyst_schedule.json"] = hashlib.sha256(
        schedule_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="schedule differs"):
        verify_event_intelligence(output, freeze, metadata)


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
    with pytest.raises(ValueError, match="checksum|hash mismatch"):
        verify_event_intelligence(tmp_path / "second", freeze, metadata_dir, cache_workspace=cache)


def test_source_inventory_union_preserves_legacy_bytes_and_does_not_retain_packs(
    freeze: Path, tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    output = tmp_path / "intelligence"
    original_pack = intelligence._event_pack
    original_inventory = intelligence._cache_inventory
    tracked: list[weakref.ReferenceType[Any]] = []
    inventory_calls: list[set[str]] = []

    class TrackedPack(dict):
        pass

    def observe_pack(*args: Any, **kwargs: Any):
        pack, count = original_pack(*args, **kwargs)
        wrapped = TrackedPack(pack)
        tracked.append(weakref.ref(wrapped))
        return wrapped, count

    def observe_inventory(selected: Any, paths: ProjectPaths, filings: pd.DataFrame):
        assert isinstance(selected, set)
        assert all(isinstance(value, str) for value in selected)
        # Builder and scientific replay keep only the latest pack, rather than
        # retaining a full text dictionary for every event.
        assert sum(ref() is not None for ref in tracked) <= 2
        inventory_calls.append(set(selected))
        return original_inventory(selected, paths, filings)

    monkeypatch.setattr(intelligence, "_event_pack", observe_pack)
    monkeypatch.setattr(intelligence, "_cache_inventory", observe_inventory)
    events = pd.DataFrame(
        [
            dict(
                event_id=f"event_{index}",
                pair_id="KO__PEP",
                event_timestamp=f"2022-03-{10 + index:02d}T21:00:00Z",
            )
            for index in range(12)
        ]
    )
    manifest = build_event_intelligence(
        events,
        freeze,
        metadata,
        output,
        provider=None,
        sentiment_backend=Tone(),
        get=source([]),
    )
    assert len(inventory_calls) == 2 and inventory_calls[0] == inventory_calls[1]
    checkpoint_packs = [
        json.loads((output / row["file"]).read_bytes())["pack"]
        for row in manifest["source_identity"]["records"]
    ]
    legacy_selected = {
        filing for pack in checkpoint_packs for filing in pack.get("selected_filing_ids", [])
    }
    assert inventory_calls[0] == legacy_selected
    filings = pd.read_parquet(metadata / "filings.parquet")
    paths = ProjectPaths(project_root, output)
    legacy_inventory = {}
    for row in filings.loc[filings["filing_id"].isin(legacy_selected)].to_dict("records"):
        folder = paths.data_path(f"raw/sec/filings/{row['cik']}/{row['filing_id']}")
        for filename in folder.rglob("*"):
            if filename.is_file() and "attempts" not in filename.relative_to(folder).parts:
                legacy_inventory[filename.relative_to(paths.workspace_root).as_posix()] = (
                    sha256_file(filename)
                )
    assert manifest["cache_files"] == legacy_inventory
    assert intelligence.json_bytes(manifest["cache_files"]) == intelligence.json_bytes(
        legacy_inventory
    )
    # A rehashed manifest cannot omit selected response metadata from its inventory.
    manifest["cache_files"].pop(next(iter(manifest["cache_files"])))
    (output / "manifest.json").write_bytes(intelligence.json_bytes(manifest))
    with pytest.raises(ValueError, match="source cache inventory/checksum"):
        verify_event_intelligence(output, freeze, metadata)


@pytest.fixture
def parsing_batch(freeze: Path, tmp_path: Path, project_root: Path) -> dict[str, Any]:
    metadata = tmp_path / "metadata"
    collect_sec_metadata(freeze, metadata, get=source([]))
    output = tmp_path / "intelligence"
    manifest = build_event_intelligence(
        event_rows(), freeze, metadata, output, provider=None, get=source([])
    )
    first = manifest["source_identity"]["records"][0]
    event = json.loads((output / first["file"]).read_bytes())["event"]
    return {
        "freeze": freeze,
        "metadata": metadata,
        "output": output,
        "manifest": manifest,
        "event": event,
        "filings": pd.read_parquet(metadata / "filings.parquet"),
        "coverage": json.loads((output / "metadata_observed_bounds.json").read_bytes()),
        "paths": ProjectPaths(project_root, output),
    }


def test_parallel_verifier_replays_fresh_sources_owns_cache_and_preserves_manifest(
    parsing_batch: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    caches: list[OperationParsingCache] = []
    pools: list[VerificationParsingPool] = []
    parse_keys: list[list[str]] = []
    checked: set[str] = set()
    coordinator = threading.get_ident()
    cache_filing = intelligence.cache_filing

    class OneHotCache(OperationParsingCache):
        def __init__(self) -> None:
            super().__init__(max_hot_frames=1)
            assert self.entry_count == 0
            caches.append(self)

        def __setitem__(self, key: str, frame: pd.DataFrame) -> None:
            assert threading.get_ident() == coordinator
            super().__setitem__(key, frame)

    class TrackedPool(VerificationParsingPool):
        def __init__(self) -> None:
            super().__init__()
            pools.append(self)
            parse_keys.append([])

        def submit(self, documents, policy):
            assert threading.get_ident() == coordinator
            assert intelligence._sha(documents) in checked
            parse_keys[-1].append(intelligence._sha(documents))
            return super().submit(documents, policy)

    def checked_inventory(*args, **kwargs):
        assert threading.get_ident() == coordinator
        documents = cache_filing(*args, **kwargs)
        checked.add(intelligence._sha(documents))
        return documents

    def forbidden(*args, **kwargs):
        pytest.fail("Independent raw verification cannot perform provider or neural inference")

    monkeypatch.setattr(intelligence, "OperationParsingCache", OneHotCache)
    monkeypatch.setattr(intelligence, "VerificationParsingPool", TrackedPool)
    monkeypatch.setattr(intelligence, "cache_filing", checked_inventory)
    monkeypatch.setattr(intelligence, "extract_pack", forbidden)
    monkeypatch.setattr(intelligence, "score_sentiment_pack", forbidden)
    for _ in range(2):
        assert (
            verify_event_intelligence(
                parsing_batch["output"],
                parsing_batch["freeze"],
                parsing_batch["metadata"],
                parsing_workers=2,
            )
            == parsing_batch["manifest"]
        )
    assert len(caches) == len(pools) == 2
    assert parse_keys[0] == parse_keys[1] and len(parse_keys[0]) > 1
    assert len(parse_keys[0]) == len(set(parse_keys[0]))
    assert all(cache._closed and not cache._directory.exists() for cache in caches)
    assert all(pool._closed and not pool._pending for pool in pools)


def test_parallel_cache_reuses_pair_roles_with_exact_pack_equality_and_fresh_copies(
    parsing_batch: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = parsing_batch
    event = batch["event"]
    swapped = dict(
        event,
        event_id="swapped",
        pair_id="swapped",
        leg_a=event["leg_b"],
        leg_b=event["leg_a"],
        leg_a_security_id=event["leg_b_security_id"],
        leg_b_security_id=event["leg_a_security_id"],
    )

    def pack(row, *, cache=None, pool=None, filings=None):
        return intelligence._event_pack(
            row,
            batch["filings"] if filings is None else filings,
            batch["coverage"],
            batch["paths"],
            intelligence._offline_only,
            offline=True,
            parsed_cache=cache,
            parser_pool=pool,
        )

    expected = [pack(row) for row in (event, swapped)]
    submitted: list[str] = []
    with OperationParsingCache(max_hot_frames=1) as cache, VerificationParsingPool() as pool:
        original_submit = pool.submit

        def tracked_submit(documents, policy):
            submitted.append(intelligence._sha(documents))
            return original_submit(documents, policy)

        monkeypatch.setattr(pool, "submit", tracked_submit)
        first = pack(event, cache=cache, pool=pool)
        count = len(submitted)
        second = pack(swapped, cache=cache, pool=pool)
        assert count > 1 and len(submitted) == count == cache.entry_count
        assert intelligence.json_bytes(first) == intelligence.json_bytes(expected[0])
        assert intelligence.json_bytes(second) == intelligence.json_bytes(expected[1])
        # Restoring B on a returned copy cannot corrupt the cached A frame.
        assert intelligence.json_bytes(pack(event, cache=cache, pool=pool)) == (
            intelligence.json_bytes(expected[0])
        )
        assert len(submitted) == count
        # Changed acceptance must fail metadata validation before cache reuse.
        changed = batch["filings"].copy(deep=True)
        first_id = first[0]["selected_filing_ids"][0]
        selected = changed["filing_id"].eq(first_id)
        changed.loc[selected, "acceptance_datetime_utc"] += pd.Timedelta(seconds=1)
        for active_cache, active_pool in ((None, None), (cache, pool)):
            with pytest.raises(ValueError, match="Cached SEC acceptance timestamp mismatch"):
                pack(event, cache=active_cache, pool=active_pool, filings=changed)
        assert len(submitted) == count


@pytest.mark.parametrize("tampering", ["raw", "leg", "clock"])
def test_parallel_cache_cannot_hide_raw_leg_or_clock_failure_before_reuse(
    parsing_batch: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tampering: str
) -> None:
    batch = parsing_batch
    submitted: list[str] = []
    original_inventory = intelligence.cache_filing
    with OperationParsingCache() as cache, VerificationParsingPool() as pool:
        original_submit = pool.submit

        def tracked_submit(documents, policy):
            submitted.append(intelligence._sha(documents))
            return original_submit(documents, policy)

        monkeypatch.setattr(pool, "submit", tracked_submit)

        def pack():
            return intelligence._event_pack(
                batch["event"],
                batch["filings"],
                batch["coverage"],
                batch["paths"],
                intelligence._offline_only,
                offline=True,
                parsed_cache=cache,
                parser_pool=pool,
            )

        pack()
        count = len(submitted)
        if tampering == "raw":
            target = next(
                (batch["output"] / "data/raw/sec/filings").glob("**/primary_document.html")
            )
            target.write_bytes(target.read_bytes() + b"changed source")
        elif tampering == "leg":

            def conflicting_legs(*args, **kwargs):
                documents = original_inventory(*args, **kwargs)
                documents[0]["leg"] = "B" if documents[0]["leg"] == "A" else "A"
                return documents

            monkeypatch.setattr(intelligence, "cache_filing", conflicting_legs)
        else:
            # This check runs even when all relevant inventories are cached.
            def contradictory_clock(*args):
                raise ValueError("contradictory clock")

            monkeypatch.setattr(intelligence, "_submission_clock_state", contradictory_clock)
        with pytest.raises(ValueError, match="hash mismatch|checksum|inventory legs|clock"):
            pack()
        assert len(submitted) == count

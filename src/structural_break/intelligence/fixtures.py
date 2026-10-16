"""Explicitly synthetic SEC documents/provider for offline engineering acceptance.

The generated filing prose is independent of targets and cannot be reported as
genuine historical extraction or evidence of predictive improvement.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse, SourceError

_BUSINESS_TEXT = (
    ("EARNINGS", "Quarterly earnings and revenue increased substantially.", "POSITIVE", "MEDIUM"),
    (
        "GUIDANCE",
        "Management reduced its annual earnings guidance and outlook.",
        "NEGATIVE",
        "HIGH",
    ),
    ("M&A", "The company announced an acquisition of a complementary business.", "NEUTRAL", "HIGH"),
    (
        "REGULATORY",
        "The regulator granted approval for the company's new product.",
        "POSITIVE",
        "MEDIUM",
    ),
    ("LITIGATION", "The company disclosed a material litigation settlement.", "NEGATIVE", "HIGH"),
    (
        "MANAGEMENT",
        "The chief executive officer announced a planned resignation.",
        "NEUTRAL",
        "MEDIUM",
    ),
    (
        "PRODUCT_OTHER",
        "The company announced a product launch and supply contract.",
        "POSITIVE",
        "LOW",
    ),
)


class MockProvider:
    """Grounded deterministic test adapter, with no arbitrary outcome labels."""

    synthetic = True

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        pack = json.loads(request["messages"][1]["content"])
        complete = all(item["status"] == "COMPLETE" for item in pack["coverage"].values())
        if not complete:
            return {
                "event_type": "UNKNOWN",
                "affected_leg": "UNKNOWN",
                "direction": "UNKNOWN",
                "materiality": "UNKNOWN",
                "relationship_relevance": "UNKNOWN",
                "extraction_confidence": None,
                "citations": [],
            }
        for chunk in pack["chunks"]:
            for category, quote, direction, materiality in _BUSINESS_TEXT:
                if quote in chunk["chunk_text"]:
                    return {
                        "event_type": category,
                        "affected_leg": chunk["leg"],
                        "direction": direction,
                        "materiality": materiality,
                        "relationship_relevance": "INDIRECT",
                        "extraction_confidence": 0.8,
                        "citations": [
                            {"chunk_id": chunk["chunk_id"], "leg": chunk["leg"], "quote": quote}
                        ],
                    }
        return {
            "event_type": "NONE" if complete else "UNKNOWN",
            "affected_leg": "NONE" if complete else "UNKNOWN",
            "direction": "UNKNOWN",
            "materiality": "UNKNOWN",
            "relationship_relevance": "NONE" if complete else "UNKNOWN",
            "extraction_confidence": None,
            "citations": [],
        }


def make_fixture_pack(event: dict[str, Any]) -> dict[str, Any]:
    """Small stand-alone synthetic pack for direct extraction demos/tests."""
    at = pd.Timestamp(event["event_timestamp"])
    choice = int(hashlib.sha256(str(event["event_id"]).encode()).hexdigest()[:8], 16) % len(
        _BUSINESS_TEXT
    )
    text = _BUSINESS_TEXT[choice][1]
    ticker = str(event["pair_id"]).split("__")[0]
    return {
        "event_id": str(event["event_id"]),
        "pair_id": str(event["pair_id"]),
        "event_timestamp": at.isoformat(),
        "evidence_cutoff": at.isoformat(),
        "policy_version": "synthetic-sec-evidence-v1",
        "coverage": {leg: {"status": "COMPLETE"} for leg in ("A", "B")},
        "chunks": [
            {
                "chunk_id": "synthetic_chunk_" + hashlib.sha256(text.encode()).hexdigest()[:20],
                "filing_id": "synthetic_filing_" + str(event["event_id"]),
                "security_id": ticker,
                "leg": "A",
                "form": "8-K",
                "document_type": "EX-99.1",
                "acceptance_datetime_utc": (at - pd.Timedelta(days=3)).isoformat(),
                "chunk_text": text,
                "section_label": "Synthetic business event",
                "source_url": "https://www.sec.gov/Archives/SYNTHETIC-test-only",
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "status": "OK",
            }
        ],
    }


def make_evidence_fixture(
    events: pd.DataFrame,
    paths: ProjectPaths,
) -> tuple[pd.DataFrame, Callable[[str], FetchedResponse]]:
    """HTTP fixtures consumed by actual production selection/download/parser code.

    Security IDs are the oriented pair's ticker strings, matching the P3 synthetic
    fixture reference data. Each event/leg supplies a recent 8-K and periodic 10-Q;
    an EX-99.1 in the complete submission is separately downloaded by the cache.
    ``paths`` is accepted for the batch fixture interface; source bytes are only
    written by the production document cache, never by this fixture generator.
    """
    del paths
    tickers = sorted(
        {ticker for pair in events["pair_id"].astype(str) for ticker in pair.split("__")}
    )
    ciks = {ticker: str(9000000 + number).zfill(10) for number, ticker in enumerate(tickers)}
    responses: dict[str, bytes] = {}
    unavailable: set[str] = set()
    filings: list[dict[str, Any]] = []
    for index, event in enumerate(
        events.sort_values(["event_timestamp", "event_id"]).to_dict("records")
    ):
        at = pd.Timestamp(event["event_timestamp"])
        choice = int(hashlib.sha256(str(event["event_id"]).encode()).hexdigest()[:8], 16) % len(
            _BUSINESS_TEXT
        )
        for leg_index, ticker in enumerate(str(event["pair_id"]).split("__")):
            cik = ciks[ticker]
            for form_index, (form, offset) in enumerate((("8-K", 3), ("10-Q", 60))):
                accepted = at - pd.Timedelta(days=offset)
                sequence = index * 4 + leg_index * 2 + form_index + 1
                accession = f"{cik}-{accepted.year % 100:02d}-{sequence:06d}"
                primary = "primary.htm"
                base = (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession.replace('-', '')}/"
                )
                topic = _BUSINESS_TEXT[(choice + leg_index) % len(_BUSINESS_TEXT)][1]
                context = (
                    "Synthetic periodic context. Item 1. Business. The company conducts ordinary "
                    "business operations. Item 1A. Risk Factors. Historical business risk remains "
                    "uncertain and depends on economic demand."
                )
                text = topic if form == "8-K" else context
                html = (
                    f"<html><body><h1>SYNTHETIC TEST DOCUMENT {ticker}</h1>"
                    f"<h2>Item 2.02 Financial results</h2><p>{text}</p>"
                    "<p>This is a fabricated engineering fixture, not an SEC disclosure.</p>"
                    "</body></html>"
                ).encode()
                exhibit = (
                    f"<html><body><h1>SYNTHETIC EX-99.1</h1><p>{topic}</p>"
                    "<p>Test-only source prose.</p></body></html>"
                ).encode()
                item_names = [primary] + (["ex99.htm"] if form == "8-K" else [])
                responses[base + "index.json"] = json.dumps(
                    {"directory": {"item": [{"name": name} for name in item_names]}}
                ).encode()
                responses[base + primary] = html
                # A deterministic incomplete-source cohort exercises UNKNOWN retention.
                # It depends on event ordering only, never on the target or model scores.
                if index % 4 == 0 and leg_index == 1 and form == "8-K":
                    unavailable.add(base + primary)
                sgml = (
                    f"<DOCUMENT>\n<TYPE>{form}\n<SEQUENCE>1\n<FILENAME>{primary}\n"
                    "<TEXT>" + html.decode() + "</TEXT>\n</DOCUMENT>\n"
                )
                if form == "8-K":
                    responses[base + "ex99.htm"] = exhibit
                    sgml += (
                        "<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>ex99.htm\n"
                        "<TEXT>" + exhibit.decode() + "</TEXT>\n</DOCUMENT>\n"
                    )
                responses[base + accession + ".txt"] = sgml.encode()
                filings.append(
                    {
                        "security_id": ticker,
                        "filing_id": accession,
                        "accession_number": accession,
                        "cik": cik,
                        "form": form,
                        "base_form": form,
                        "is_amendment": False,
                        "acceptance_datetime_utc": accepted,
                        "point_in_time_eligible": True,
                        "timestamp_quality_flag": "OK",
                        "report_date": accepted.date(),
                        "filing_date": accepted.date(),
                        "primary_document": primary,
                        "archive_url": base,
                        "primary_document_url": base + primary,
                        "complete_submission_url": base + accession + ".txt",
                        "source_provider": "SYNTHETIC",
                        "synthetic": True,
                    }
                )

    def get(url: str) -> FetchedResponse:
        if url in unavailable:
            raise SourceError(url, 503)
        if url not in responses:
            raise ValueError("Synthetic fixture contains no response for requested document")
        return FetchedResponse(responses[url], url, 200, datetime(2026, 1, 1, tzinfo=UTC))

    return pd.DataFrame(filings), get

"""Separate, target-free SEC capture and bounded research-v2 event intelligence.

The frozen roster fixes issuer mappings and orientations before any source or
outcome inspection. Every event survives source/provider/inference gaps. These
files never publish into the registered Phase 4 database or alter its artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.http import FetchedResponse, HttpClient, SourceError
from structural_break.data.sec import (
    SUBMISSIONS_BASE_URL,
    SecDataError,
    fetch_submissions,
    normalize_filings,
    parse_json_response,
)
from structural_break.intelligence.event_features import (
    EVENT_FEATURE_NAMES,
    build_event_feature_frame,
)
from structural_break.intelligence.evidence import (
    EvidencePolicy,
    build_evidence_pack,
    cache_filing,
    parse_documents,
    select_event_filings,
)
from structural_break.intelligence.extraction import (
    ExtractionProvider,
    ProviderFailure,
    extract_pack,
    validate_pack,
    validate_stored_extraction,
)
from structural_break.intelligence.gemma import GEMMA_ADAPTER_VERSION
from structural_break.intelligence.sentiment import (
    SENTIMENT_FEATURE_COLUMNS,
    FinBERTPolicy,
    SentimentBackend,
    SentimentFailure,
    score_sentiment_pack,
    validate_sentiment_result,
)
from structural_break.research.availability import (
    ACCEPTANCE_POLICY,
    ambiguous_cutoff,
    apply_availability_bounds,
)
from structural_break.research.scheduling import (
    DEFAULT_CATALYST_EVENTS,
    MAX_CATALYST_CALLS,
    build_catalyst_schedule,
)
from structural_break.research.universe import json_bytes, parquet_bytes, verify_universe_freeze
from structural_break.storage.files import sha256_file, write_bytes

Progress = Callable[[dict[str, Any]], None]
_EVENT_COLUMNS = frozenset(
    {
        "event_id",
        "pair_id",
        "event_timestamp",
        "event_date",
        "trading_date",
        "evidence_cutoff",
        "leg_a",
        "leg_b",
        "leg_a_security_id",
        "leg_b_security_id",
    }
)
RESEARCH_EVIDENCE_POLICY = EvidencePolicy(
    max_chunks_per_leg=3, max_total_chars=12_000, version="sec-evidence-research-v2-small-v1"
)
METADATA_FEATURE_COLUMNS = tuple(
    f"sec_{leg}_{name}"
    for leg in ("a", "b")
    for name in (
        "recent_8k_count_30d",
        "days_since_latest_8k",
        "recent_items_2_02_earnings",
        "recent_items_5_02_management",
        "periodic_recency_days",
        "metadata_coverage_unknown",
    )
) + ("sec_recent_8k_count_asymmetry", "sec_one_sided_recent_8k")


def _sha(payload: object) -> str:
    return hashlib.sha256(json_bytes(payload)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    result = json.loads(path.read_bytes())
    if not isinstance(result, dict):
        raise ValueError("Research intelligence JSON must contain an object")
    return result


_SOURCE_FIELDS = frozenset(
    {"request_url", "source_url", "file", "sha256", "status_code", "retrieved_at_utc"}
)


def _checked_metadata_source(
    source: Mapping[str, Any], directory: Path, *, inventory: bool
) -> FetchedResponse:
    """Bind each cached response to one canonical SEC request and immutable bytes."""
    fields = _SOURCE_FIELDS | {"cik", "included"} if inventory else _SOURCE_FIELDS
    if set(source) != fields:
        raise ValueError("SEC metadata response schema differs")
    request = source["request_url"]
    match = (
        re.fullmatch(
            re.escape(SUBMISSIONS_BASE_URL) + r"CIK(\d{10})(?:-submissions-\d+)?\.json",
            request,
        )
        if isinstance(request, str)
        else None
    )
    if (
        match is None
        or source["source_url"] != request
        or source["file"] != "data/raw/sec/submissions/" + request.rsplit("/", 1)[1]
        or type(source["status_code"]) is not int
        or not 100 <= source["status_code"] <= 599
        or not isinstance(source["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is None
    ):
        raise ValueError("SEC metadata exact source identity differs")
    if inventory and (source["cik"] != match[1] or type(source["included"]) is not bool):
        raise ValueError("SEC metadata source issuer or inclusion identity differs")
    try:
        retrieved = datetime.fromisoformat(source["retrieved_at_utc"])
    except (TypeError, ValueError) as exc:
        raise ValueError("SEC metadata retrieval timestamp must be UTC aware") from exc
    if retrieved.tzinfo is None or retrieved.utcoffset() != UTC.utcoffset(retrieved):
        raise ValueError("SEC metadata retrieval timestamp must be UTC aware")
    body = confined_path(directory, source["file"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != source["sha256"]:
        raise ValueError("Cached SEC metadata raw checksum differs")
    return FetchedResponse(body, request, source["status_code"], retrieved)


def _source_get(
    directory: Path, get: Callable[[str], FetchedResponse], sources: dict[str, dict[str, Any]]
) -> Callable[[str], FetchedResponse]:
    def cached(url: str) -> FetchedResponse:
        if (
            re.fullmatch(
                re.escape(SUBMISSIONS_BASE_URL) + r"CIK\d{10}(?:-submissions-\d+)?\.json", url
            )
            is None
        ):
            raise ValueError("SEC metadata cache requires the official submissions endpoint")
        name = url.removeprefix(SUBMISSIONS_BASE_URL)
        if "/" in name or "\\" in name or not name.endswith(".json"):
            raise ValueError("SEC metadata requires a plain JSON source filename")
        file = f"data/raw/sec/submissions/{name}"
        metadata_path = confined_path(directory, file + ".source.json")
        if metadata_path.exists():
            metadata = _load_json(metadata_path)
            if metadata.get("request_url") != url or metadata.get("file") != file:
                raise ValueError("Cached SEC source identity disagrees with its request")
            response = _checked_metadata_source(metadata, directory, inventory=False)
        else:
            response = get(url)
            if (
                response.url != url
                or response.retrieved_at.tzinfo is None
                or response.retrieved_at.utcoffset() is None
                or type(response.status_code) is not int
                or not 100 <= response.status_code <= 599
            ):
                raise ValueError("SEC metadata response lacks exact source or retrieval identity")
            metadata = {
                "request_url": url,
                "source_url": response.url,
                "file": file,
                "sha256": hashlib.sha256(response.body).hexdigest(),
                "status_code": response.status_code,
                "retrieved_at_utc": response.retrieved_at.astimezone(UTC).isoformat(),
            }
            write_bytes(confined_path(directory, file), response.body)
            write_bytes(metadata_path, json_bytes(metadata))
        sources[url] = metadata
        return response

    return cached


def _normalized_metadata(
    sources: Sequence[Mapping[str, Any]],
    directory: Path,
    securities: pd.DataFrame,
    inputs: Mapping[str, Any],
    snapshot_id: str,
) -> pd.DataFrame:
    normalized = []
    for source in sources:
        if not source.get("included", False):
            continue
        body = confined_path(directory, source["file"]).read_bytes()
        response = FetchedResponse(
            body,
            source["source_url"],
            source["status_code"],
            datetime.fromisoformat(source["retrieved_at_utc"]),
        )
        lineage: dict[str, object] = {
            "source_snapshot_id": "sec_" + str(source["sha256"])[:24],
            "data_snapshot_id": snapshot_id,
            "raw_file_path": source["file"],
            "sha256": source["sha256"],
            "source_url": source["source_url"],
            "retrieved_at_utc": response.retrieved_at,
            "source_provider": "SEC_EDGAR",
            "library_version": "official_submissions_json",
        }
        normalized.append((str(source["cik"]), parse_json_response(response), lineage))
    filings = normalize_filings(
        normalized, date.fromisoformat(inputs["start"]), date.fromisoformat(inputs["end"])
    )
    if inputs.get("acceptance_policy") == ACCEPTANCE_POLICY:
        filings = apply_availability_bounds(filings)
    identities = securities[
        [
            "cik",
            "security_id",
            "identity_valid_from",
            "identity_valid_to",
            "historical_cik_valid_to",
        ]
    ].copy()
    # The frozen historical CIK override has its own explicit exclusive endpoint.
    for row_index, row in identities.iterrows():
        if pd.notna(row["historical_cik_valid_to"]):
            endpoint = pd.Timestamp(row["historical_cik_valid_to"]).date()
            current = row["identity_valid_to"]
            identities.at[row_index, "identity_valid_to"] = (
                min(endpoint, pd.Timestamp(current).date()) if pd.notna(current) else endpoint
            )
    identities = identities.drop(columns="historical_cik_valid_to")
    return filings.merge(identities, on="cik", how="left", validate="many_to_one")


def collect_sec_metadata(
    frozen_universe_dir: Path,
    output_dir: Path,
    start: date = date(2004, 1, 1),
    end: date = date(2023, 12, 31),
    *,
    max_issuers: int | None = None,
    get: Callable[[str], FetchedResponse] | None = None,
    sec_user_agent: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Freeze exact current and intersecting older submissions JSON, with gaps.

    Per-response caches survive interrupted captures. An explicit issuer limit
    produces an auditable partial capture, never a completed coverage assertion.
    Missing acceptance times remain ineligible; filing dates are not substitutes.
    """
    if start > end or end > date(2023, 12, 31):
        raise ValueError("Research SEC development sources must end by 2023-12-31")
    if max_issuers is not None and (type(max_issuers) is not int or max_issuers < 1):
        raise ValueError("SEC metadata issuer limit must be a positive integer")
    freeze = verify_universe_freeze(frozen_universe_dir)
    securities = pd.read_parquet(frozen_universe_dir / "security_master.parquet")
    inputs = {
        "universe_freeze_id": freeze["freeze_id"],
        "universe_manifest_sha256": sha256_file(frozen_universe_dir / "manifest.json"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "max_issuers": max_issuers,
        "code_sha256": sha256_file(Path(__file__)),
        "normalizer_sha256": sha256_file(Path(__file__).parents[1] / "data/sec.py"),
        "acceptance_policy": ACCEPTANCE_POLICY,
        "availability_implementation_sha256": sha256_file(
            Path(__file__).with_name("availability.py")
        ),
    }
    if (output_dir / "manifest.json").exists():
        manifest = verify_sec_metadata(output_dir, frozen_universe_dir)
        if any(
            manifest["inputs"].get(key) != value
            for key, value in inputs.items()
            if key != "code_sha256"
        ):
            raise ValueError("SEC metadata output directory already binds another capture")
        return manifest
    source_index: dict[str, dict[str, Any]] = {}
    raw_get = _source_get(output_dir, get or HttpClient(sec_user_agent).get, source_index)
    coverage = []
    ordered = securities.sort_values("security_id").to_dict("records")
    for index, security in enumerate(ordered):
        cik = str(security["cik"])
        status = "NOT_SCHEDULED" if max_issuers is not None and index >= max_issuers else "OK"
        reason: str | None = "METADATA_BATCH_LIMIT" if status == "NOT_SCHEDULED" else None
        included: set[str] = set()
        if status == "OK":
            try:
                fetched = fetch_submissions([cik], start, end, raw_get)
                included = {response.url for _, _, response in fetched}
            except (SourceError, SecDataError):
                status, reason = "UNKNOWN", "SEC_METADATA_SOURCE_FAILED"
                # Retain any successful prefix, but mark the issuer coverage incomplete.
                for url, source in source_index.items():
                    if f"CIK{cik}" in url and source["status_code"] == 200:
                        try:
                            parse_json_response(
                                FetchedResponse(
                                    confined_path(output_dir, source["file"]).read_bytes(),
                                    source["source_url"],
                                    source["status_code"],
                                    datetime.fromisoformat(source["retrieved_at_utc"]),
                                )
                            )
                            included.add(url)
                        except SecDataError:
                            pass
            for url, source in source_index.items():
                if f"CIK{cik}" in url:
                    source.update(cik=cik, included=url in included)
        coverage.append(
            {
                "security_id": security["security_id"],
                "cik": cik,
                "status": status,
                "reason": reason,
                "metadata_sources": len(included),
            }
        )
        if progress:
            progress(
                {
                    "stage": "SEC_METADATA",
                    "security_id": security["security_id"],
                    "status": status,
                    "completed": index + 1,
                    "total": len(ordered),
                }
            )
    sources = [source_index[url] for url in sorted(source_index)]
    identity = {"inputs": inputs, "sources": sources, "coverage": coverage}
    snapshot_id = "research_sec_" + _sha(identity)[:24]
    filings = _normalized_metadata(sources, output_dir, securities, inputs, snapshot_id)
    missing_counts = filings.loc[
        filings["acceptance_datetime_utc"].isna(), "security_id"
    ].value_counts()
    for row in coverage:
        row["missing_acceptance_count"] = int(missing_counts.get(row["security_id"], 0))
    snapshot_id = "research_sec_" + _sha(identity)[:24]
    filings["data_snapshot_id"] = snapshot_id
    files: dict[str, str] = {}
    for filename, body in {
        "filings.parquet": parquet_bytes(filings),
        "coverage.json": json_bytes(coverage),
        "sources.json": json_bytes(sources),
    }.items():
        write_bytes(output_dir / filename, body)
        files[filename] = hashlib.sha256(body).hexdigest()
    for source in sources:
        for filename in (source["file"], source["file"] + ".source.json"):
            files[filename] = sha256_file(confined_path(output_dir, filename))
    manifest = {
        "schema_version": "research-sec-metadata-v2",
        "inputs": inputs,
        "data_snapshot_id": snapshot_id,
        "source_identity": identity,
        "files": files,
        "filing_count": len(filings),
        "issuer_count": len(securities),
        "scheduled_issuer_count": sum(row["status"] != "NOT_SCHEDULED" for row in coverage),
        "complete_source_issuer_count": sum(row["status"] == "OK" for row in coverage),
        "missing_acceptance_count": int(filings["acceptance_datetime_utc"].isna().sum()),
        "final_test_sources_requested": False,
        "timestamp_recovery_from_filing_date": False,
    }
    write_bytes(output_dir / "manifest.json", json_bytes(manifest))
    verify_sec_metadata(output_dir, frozen_universe_dir)
    return manifest


def _replay_metadata_coverage(
    sources: Sequence[Mapping[str, Any]],
    responses: Mapping[str, FetchedResponse],
    securities: pd.DataFrame,
    inputs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Replay the required current/history inventory without any network access.

    A missing required response can only reconstruct UNKNOWN. Hash consistency
    alone cannot establish complete history when the current JSON declares an
    intersecting older file that is absent from the stored response inventory.
    """
    coverage = []
    known_ciks = set(securities["cik"])
    if any(source["cik"] not in known_ciks for source in sources):
        raise ValueError("SEC metadata source lies outside the frozen issuer roster")
    start, end = date.fromisoformat(inputs["start"]), date.fromisoformat(inputs["end"])
    limit = inputs["max_issuers"]
    if start > end or (limit is not None and (type(limit) is not int or limit < 1)):
        raise ValueError("SEC metadata capture range or issuer scheduling limit differs")
    for index, security in enumerate(securities.sort_values("security_id").to_dict("records")):
        cik = str(security["cik"])
        issuer_sources = {
            source["request_url"]: source for source in sources if source["cik"] == cik
        }
        status = "NOT_SCHEDULED" if limit is not None and index >= limit else "OK"
        reason = "METADATA_BATCH_LIMIT" if status == "NOT_SCHEDULED" else None
        attempted: set[str] = set()
        included: set[str] = set()

        def offline_get(
            url: str,
            _attempted: set[str] = attempted,
            _issuer_sources: Mapping[str, Mapping[str, Any]] = issuer_sources,
        ) -> FetchedResponse:
            _attempted.add(url)
            if url not in _issuer_sources:
                raise SourceError(url)
            return responses[url]

        if status == "OK":
            try:
                included = {
                    response.url
                    for _, _, response in fetch_submissions([cik], start, end, offline_get)
                }
            except (SourceError, SecDataError):
                status, reason = "UNKNOWN", "SEC_METADATA_SOURCE_FAILED"
                for url, source in issuer_sources.items():
                    if source["status_code"] == 200:
                        try:
                            parse_json_response(responses[url])
                            included.add(url)
                        except SecDataError:
                            pass
        if set(issuer_sources) != attempted & set(responses):
            raise ValueError("SEC metadata inventory differs from its required source requests")
        if any(
            source["included"] is not (url in included) for url, source in issuer_sources.items()
        ):
            raise ValueError("SEC metadata source inclusion differs from offline request replay")
        coverage.append(
            {
                "security_id": security["security_id"],
                "cik": cik,
                "status": status,
                "reason": reason,
                "metadata_sources": len(included),
            }
        )
    return coverage


def verify_sec_metadata(directory: Path, frozen_universe_dir: Path) -> dict[str, Any]:
    """Hash and reconstruct source-derived filings before they enter evidence selection."""
    freeze = verify_universe_freeze(frozen_universe_dir)
    manifest = _load_json(directory / "manifest.json")
    inputs = manifest["inputs"]
    if (
        inputs.get("acceptance_policy") not in {None, ACCEPTANCE_POLICY}
        or manifest.get("schema_version")
        != (
            "research-sec-metadata-v2"
            if inputs.get("acceptance_policy") == ACCEPTANCE_POLICY
            else "research-sec-metadata-v1"
        )
        or inputs["universe_freeze_id"] != freeze["freeze_id"]
        or inputs["universe_manifest_sha256"] != sha256_file(frozen_universe_dir / "manifest.json")
        or date.fromisoformat(inputs["end"]) > date(2023, 12, 31)
        or manifest.get("final_test_sources_requested") is not False
    ):
        raise ValueError("SEC metadata violates its frozen universe or final-test boundary")
    sources = json.loads((directory / "sources.json").read_bytes())
    coverage = json.loads((directory / "coverage.json").read_bytes())
    if not isinstance(sources, list) or not isinstance(coverage, list):
        raise ValueError("SEC metadata source and coverage inventories must be arrays")
    expected_files = {"sources.json", "coverage.json", "filings.parquet"}
    responses = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("SEC metadata source inventory schema differs")
        response = _checked_metadata_source(source, directory, inventory=True)
        if response.url in responses:
            raise ValueError("SEC metadata source requests must be unique")
        responses[response.url] = response
        metadata_file = source["file"] + ".source.json"
        if _load_json(confined_path(directory, metadata_file)) != {
            field: source[field] for field in _SOURCE_FIELDS
        }:
            raise ValueError("SEC metadata cached response provenance differs from its inventory")
        expected_files.update((source["file"], metadata_file))
    if list(responses) != sorted(responses) or set(manifest["files"]) != expected_files:
        raise ValueError("SEC metadata source or file inventory differs")
    for filename, digest in manifest["files"].items():
        if sha256_file(confined_path(directory, filename)) != digest:
            raise ValueError("SEC metadata file checksum differs")
    expected_identity = {"inputs": inputs, "sources": sources, "coverage": coverage}
    if (
        manifest["data_snapshot_id"] != "research_sec_" + _sha(expected_identity)[:24]
        or manifest["source_identity"] != expected_identity
    ):
        raise ValueError("SEC metadata identity differs from its raw source freeze")
    securities = pd.read_parquet(frozen_universe_dir / "security_master.parquet")
    expected_coverage = _replay_metadata_coverage(sources, responses, securities, inputs)
    expected = _normalized_metadata(
        sources, directory, securities, inputs, manifest["data_snapshot_id"]
    )
    missing_counts = expected.loc[
        expected["acceptance_datetime_utc"].isna(), "security_id"
    ].value_counts()
    for row in expected_coverage:
        row["missing_acceptance_count"] = int(missing_counts.get(row["security_id"], 0))
    if coverage != expected_coverage or any(
        not isinstance(row, dict)
        or type(row.get("metadata_sources")) is not int
        or type(row.get("missing_acceptance_count")) is not int
        for row in coverage
    ):
        raise ValueError("SEC metadata coverage differs from offline source reconstruction")
    actual = pd.read_parquet(directory / "filings.parquet")
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
    counts = {
        "filing_count": len(expected),
        "issuer_count": len(securities),
        "scheduled_issuer_count": sum(
            row["status"] != "NOT_SCHEDULED" for row in expected_coverage
        ),
        "complete_source_issuer_count": sum(row["status"] == "OK" for row in expected_coverage),
        "missing_acceptance_count": int(expected["acceptance_datetime_utc"].isna().sum()),
    }
    if (
        any(
            type(manifest.get(key)) is not int or manifest[key] != value
            for key, value in counts.items()
        )
        or manifest.get("timestamp_recovery_from_filing_date") is not False
    ):
        raise ValueError("SEC metadata capture counts or missing timestamp contract differs")
    return manifest


def _event_inputs(events: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    if set(events.columns) - _EVENT_COLUMNS:
        raise ValueError(
            "Research evidence accepts event identity/timestamps only, never targets or scores"
        )
    if not {"event_id", "pair_id", "event_timestamp"}.issubset(events.columns):
        raise ValueError("Research evidence requires event_id, pair_id and event_timestamp")
    if events.empty or events["event_id"].duplicated().any():
        raise ValueError("Research evidence requires nonempty unique event identities")
    pair_index = pairs.set_index("pair_id").to_dict("index")
    rows = []
    for event in events.to_dict("records"):
        if event["pair_id"] not in pair_index:
            raise ValueError("Research event pair is outside the frozen universe")
        pair = pair_index[event["pair_id"]]
        stamp = pd.Timestamp(event["event_timestamp"])
        cutoff = pd.Timestamp(event.get("evidence_cutoff", stamp))
        if pd.isna(stamp) or pd.isna(cutoff) or stamp.tzinfo is None or cutoff.tzinfo is None:
            raise ValueError("Research SEC event cutoff violates the development information set")
        stamp, cutoff = stamp.tz_convert("UTC"), cutoff.tz_convert("UTC")
        if cutoff > stamp or stamp.date() > date(2023, 12, 31) or stamp.date() < date(2004, 1, 1):
            raise ValueError("Research SEC event cutoff violates the development information set")
        start, end = pair.get("active_from"), pair.get("active_to")
        if (pd.notna(start) and min(stamp.date(), cutoff.date()) < pd.Timestamp(start).date()) or (
            pd.notna(end) and max(stamp.date(), cutoff.date()) >= pd.Timestamp(end).date()
        ):
            raise ValueError("Research SEC event cutoff violates frozen issuer continuity")
        for field in ("leg_a", "leg_b", "leg_a_security_id", "leg_b_security_id"):
            if field in event and event[field] != pair[field]:
                raise ValueError("Research event fixed orientation disagrees with the universe")
        for field in ("event_date", "trading_date"):
            if field in event and pd.Timestamp(event[field]).date() != stamp.date():
                raise ValueError("Research event date disagrees with its declared signal cutoff")
        rows.append(
            {
                "event_id": str(event["event_id"]),
                "pair_id": str(event["pair_id"]),
                "event_timestamp": stamp.isoformat(),
                "evidence_cutoff": cutoff.isoformat(),
                **{
                    field: pair[field]
                    for field in ("leg_a", "leg_b", "leg_a_security_id", "leg_b_security_id")
                },
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["event_timestamp", "pair_id", "event_id"])
        .reset_index(drop=True)
    )


class _UnavailableTone:
    def __init__(self, policy: FinBERTPolicy) -> None:
        self.model_name, self.model_revision = policy.model_name, policy.model_revision

    def token_ids(self, text: str) -> Sequence[int]:
        raise SentimentFailure("NLP_NOT_CONFIGURED")

    def predict(self, windows: Sequence[Sequence[int]]) -> Sequence[Mapping[str, float]]:
        raise SentimentFailure("NLP_NOT_CONFIGURED")


def _disabled_provider(request: dict[str, Any]) -> str:
    raise ProviderFailure("CATALYST_NOT_CONFIGURED", retriable=False)


def _empty_pack(event: Mapping[str, Any], policy: EvidencePolicy) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "pair_id": event["pair_id"],
        "event_timestamp": event["event_timestamp"],
        "evidence_cutoff": event["evidence_cutoff"],
        "policy_version": policy.version,
        "coverage": {
            leg: {
                "status": "UNKNOWN",
                "security_id": event[f"leg_{leg.lower()}_security_id"],
                "reason": "EVENT_NOT_SCHEDULED",
            }
            for leg in ("A", "B")
        },
        "chunks": [],
    }


def metadata_event_features(
    event: Mapping[str, Any],
    filing_index: pd.DataFrame,
    issuer_coverage: Mapping[str, Mapping[str, Any]],
) -> dict[str, float | None]:
    """Fourteen fixed metadata-only features, with no LLM or outcome input.

    Counts and item flags use only selected SEC acceptance timestamps <= cutoff.
    An incomplete source inventory or missing acceptance timestamps never proves
    absence: its leg's fields are null and its unknown flag is one. Missing item
    values in otherwise known recent filings leave the corresponding flags null.
    """
    if any("earliest_observed_acceptance" not in row for row in issuer_coverage.values()):
        issuer_coverage = _coverage_bounds(list(issuer_coverage.values()), filing_index)
    selected, _ = select_event_filings(
        event,
        filing_index,
        [event["leg_a_security_id"], event["leg_b_security_id"]],
        RESEARCH_EVIDENCE_POLICY,
    )
    cutoff = pd.Timestamp(event["evidence_cutoff"])
    values: dict[str, float | None] = {}
    counts: dict[str, float | None] = {}
    for leg in ("A", "B"):
        prefix = f"sec_{leg.lower()}_"
        coverage = issuer_coverage[event[f"leg_{leg.lower()}_security_id"]]
        unknown = not _coverage_known(coverage, cutoff) or ambiguous_cutoff(
            filing_index, event[f"leg_{leg.lower()}_security_id"], cutoff
        )
        names = METADATA_FEATURE_COLUMNS[:6]
        for name in names:
            values[prefix + name.removeprefix("sec_a_")] = None
        values[prefix + "metadata_coverage_unknown"] = float(unknown)
        if unknown:
            counts[leg] = None
            continue
        rows = [row for row in cast(list[dict[str, Any]], selected) if row["leg"] == leg]
        recent = [row for row in rows if row["base_form"] == "8-K"]
        periodic = [row for row in rows if row["base_form"] in {"10-Q", "10-K"}]
        counts[leg] = float(len(recent))
        values[prefix + "recent_8k_count_30d"] = counts[leg]
        values[prefix + "days_since_latest_8k"] = (
            (
                cutoff - max(pd.Timestamp(row["acceptance_datetime_utc"]) for row in recent)
            ).total_seconds()
            / 86400
            if recent
            else None
        )
        values[prefix + "periodic_recency_days"] = (
            (
                cutoff - max(pd.Timestamp(row["acceptance_datetime_utc"]) for row in periodic)
            ).total_seconds()
            / 86400
            if periodic
            else None
        )
        items_known = all(pd.notna(row.get("items")) for row in recent)
        items = {
            item
            for row in recent
            for item in re.findall(r"\b\d+\.\d+\b", str(row.get("items", "")))
        }
        for field, item in (
            ("recent_items_2_02_earnings", "2.02"),
            ("recent_items_5_02_management", "5.02"),
        ):
            values[prefix + field] = 1.0 if item in items else 0.0 if items_known else None
    count_a, count_b = counts["A"], counts["B"]
    if count_a is not None and count_b is not None:
        values["sec_recent_8k_count_asymmetry"] = abs(count_a - count_b)
        values["sec_one_sided_recent_8k"] = float((count_a > 0) != (count_b > 0))
    else:
        values["sec_recent_8k_count_asymmetry"] = values["sec_one_sided_recent_8k"] = None
    return {name: values[name] for name in METADATA_FEATURE_COLUMNS}


def _event_pack(
    event: Mapping[str, Any],
    filings: pd.DataFrame,
    source_coverage: Mapping[str, Mapping[str, Any]],
    paths: ProjectPaths,
    source_get: Callable[[str], FetchedResponse],
    *,
    offline: bool,
    parsed_cache: OrderedDict[str, pd.DataFrame] | None = None,
) -> tuple[dict[str, Any], int]:
    policy = RESEARCH_EVIDENCE_POLICY
    selected, coverage = select_event_filings(
        event, filings, [event["leg_a_security_id"], event["leg_b_security_id"]], policy
    )
    parsed = []
    for filing in selected:
        # cache_filing checks the current raw bytes and response metadata even
        # when this operation has already parsed the exact document inventory.
        documents = cache_filing(paths, filing, source_get, offline=offline)
        key = _sha(documents)
        if parsed_cache is not None and key in parsed_cache:
            chunks = parsed_cache[key]
            parsed_cache.move_to_end(key)
        else:
            chunks = parse_documents(documents, policy)
            if parsed_cache is not None:
                parsed_cache[key] = chunks
                if len(parsed_cache) > 128:
                    parsed_cache.popitem(last=False)
        parsed.append(chunks)
    chunks = pd.concat(parsed, ignore_index=True) if parsed else parse_documents([], policy)
    pack = cast(dict[str, Any], build_evidence_pack(event, selected, chunks, coverage, policy))
    for leg in ("A", "B"):
        coverage_row = source_coverage[event[f"leg_{leg.lower()}_security_id"]]
        cutoff = pd.Timestamp(event["evidence_cutoff"])
        if not _coverage_known(coverage_row, cutoff) or ambiguous_cutoff(
            filings, event[f"leg_{leg.lower()}_security_id"], cutoff
        ):
            pack["coverage"][leg]["status"] = (
                "PARTIAL" if any(chunk["leg"] == leg for chunk in pack["chunks"]) else "UNKNOWN"
            )
            pack["coverage"][leg]["reason"] = "SEC_METADATA_OR_TIME_COVERAGE_INCOMPLETE"
    pack["coverage_status"] = (
        "COMPLETE"
        if all(pack["coverage"][leg]["status"] == "COMPLETE" for leg in ("A", "B"))
        else "PARTIAL"
        if pack["chunks"]
        else "UNKNOWN"
    )
    pack.pop("evidence_hash", None)
    pack["evidence_hash"] = _sha(pack)
    return pack, len(selected)


def _offline_only(url: str) -> FetchedResponse:
    raise ValueError("Stored research intelligence must replay without network calls")


def _coverage_bounds(
    rows: Sequence[Mapping[str, Any]], filings: pd.DataFrame
) -> dict[str, dict[str, Any]]:
    result = {}
    for source in rows:
        row = dict(source)
        accepted = filings.loc[
            filings["security_id"].eq(row["security_id"]), "acceptance_datetime_utc"
        ].dropna()
        row.update(
            earliest_observed_acceptance=accepted.min().isoformat() if len(accepted) else None,
            latest_observed_acceptance=accepted.max().isoformat() if len(accepted) else None,
            legal_listing_date=None,
            predecessor_history_complete=False,
            bounds_meaning="Observed accepted forms in this current-CIK source capture only",
        )
        result[row["security_id"]] = row
    return result


def _coverage_known(coverage: Mapping[str, Any], cutoff: pd.Timestamp) -> bool:
    earliest = coverage.get("earliest_observed_acceptance")
    return (
        coverage["status"] == "OK"
        and coverage.get("missing_acceptance_count", 0) == 0
        and earliest is not None
        and pd.Timestamp(earliest) <= cutoff
    )


def _pair_filing_indices(events: pd.DataFrame, filings: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Reduce repeated selection to the two issuers, preserving exact index rows."""
    groups = {security: group for security, group in filings.groupby("security_id", sort=False)}
    empty = filings.iloc[:0]
    return {
        str(event["pair_id"]): pd.concat(
            [
                groups.get(event[field], empty)
                for field in ("leg_a_security_id", "leg_b_security_id")
            ],
            ignore_index=True,
        )
        for event in events.drop_duplicates("pair_id").to_dict("records")
    }


def _cache_inventory(
    packs: Sequence[Mapping[str, Any]], paths: ProjectPaths, filings: pd.DataFrame
) -> dict[str, str]:
    """Bind only this batch's selected source captures, not unrelated cache entries."""
    selected = {filing for pack in packs for filing in pack.get("selected_filing_ids", [])}
    inventory = {}
    for row in filings.loc[filings["filing_id"].isin(selected)].to_dict("records"):
        folder = paths.data_path(f"raw/sec/filings/{row['cik']}/{row['filing_id']}")
        for source in folder.rglob("*"):
            if source.is_file() and "attempts" not in source.relative_to(folder).parts:
                inventory[source.relative_to(paths.workspace_root).as_posix()] = sha256_file(source)
    return inventory


def build_event_intelligence(
    events: pd.DataFrame,
    frozen_universe_dir: Path,
    sec_metadata_dir: Path,
    output_dir: Path,
    *,
    provider: ExtractionProvider | None,
    provider_name: str = "gemma",
    model_name: str = "gemma-4-26b-a4b-it",
    prompt_version: str = GEMMA_ADAPTER_VERSION,
    provider_config: Mapping[str, Any] | None = None,
    sentiment_backend: SentimentBackend | None = None,
    sentiment_policy: FinBERTPolicy | None = None,
    cache_workspace: Path | None = None,
    max_events: int | None = None,
    catalyst_max_events: int = DEFAULT_CATALYST_EVENTS,
    timeout_seconds: float = 90,
    max_retries: int = 0,
    get: Callable[[str], FetchedResponse] | None = None,
    sec_user_agent: str | None = None,
    offline: bool = False,
    event_registry_id: str = "content-addressed-event-inputs",
    market_manifest_sha256: str | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Retain 31 catalyst, 17 tone and 14 metadata features for every input event.

    ``max_events`` is an explicit partial source/tone inventory. The separate
    catalyst pilot covers years/business groups without targets, then processes
    its selected events chronologically. Unselected catalysts remain UNKNOWN;
    tone and metadata still cover all source-scheduled rows. Checkpoints permit
    interruption recovery; completed batches and their schedules are immutable.
    """
    if max_events is not None and (type(max_events) is not int or max_events < 1):
        raise ValueError("Research event batch limit must be a positive integer")
    if not 0 < timeout_seconds <= 300 or not 0 <= max_retries <= 5:
        raise ValueError("Research extraction timeout exceeds bounded controls")
    freeze = verify_universe_freeze(frozen_universe_dir)
    metadata_capture = verify_sec_metadata(sec_metadata_dir, frozen_universe_dir)
    if metadata_capture["inputs"].get("acceptance_policy") != ACCEPTANCE_POLICY:
        raise ValueError("New research intelligence requires conservative SEC availability bounds")
    pairs = pd.read_parquet(frozen_universe_dir / "pair_universe.parquet")
    clean = _event_inputs(events, pairs)
    catalyst_schedule = build_catalyst_schedule(
        clean.loc[:, ["event_id", "pair_id", "event_timestamp"]],
        pairs,
        max_events=catalyst_max_events,
        max_calls=getattr(provider, "max_calls", MAX_CATALYST_CALLS),
        max_retries=max_retries,
    )
    catalyst_ids = set(catalyst_schedule["selected_event_ids"])
    tone_policy = sentiment_policy or FinBERTPolicy()
    policy = RESEARCH_EVIDENCE_POLICY
    inputs = {
        "universe_freeze_id": freeze["freeze_id"],
        "event_registry_id": event_registry_id,
        "events_sha256": _sha(clean.to_dict("records")),
        "sec_manifest_sha256": sha256_file(sec_metadata_dir / "manifest.json"),
        "market_manifest_sha256": market_manifest_sha256,
        "evidence_policy": asdict(policy),
        "sentiment_policy": asdict(tone_policy),
        "provider": provider_name,
        "model": model_name,
        "prompt_version": prompt_version,
        "provider_config": dict(provider_config or {}),
        "max_events": max_events,
        "catalyst_max_events": catalyst_max_events,
        "catalyst_schedule_sha256": catalyst_schedule["schedule_sha256"],
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "shared_cache_workspace": cache_workspace is not None,
        "provider_limits": {
            name: getattr(provider, name, None)
            for name in (
                "max_calls",
                "min_interval_seconds",
                "max_chunks",
                "max_evidence_chars",
                "max_prompt_chars",
                "max_output_tokens",
            )
        },
        "offline_sources": offline,
        "catalyst_configured": provider is not None,
        "tone_configured": sentiment_backend is not None,
        "code_sha256": sha256_file(Path(__file__)),
    }
    # Credentials are never accepted as manifest/provider configuration.
    if set(inputs["provider_config"]) - {"max_tokens", "max_completion_tokens", "top_p", "seed"}:
        raise ValueError("Research provider credentials must stay outside cache metadata")
    if (output_dir / "manifest.json").exists():
        manifest = verify_event_intelligence(
            output_dir, frozen_universe_dir, sec_metadata_dir, cache_workspace=cache_workspace
        )
        if manifest["inputs"] != inputs:
            raise ValueError("Research intelligence output directory binds another batch")
        return manifest
    if (output_dir / "inputs.json").exists() and _load_json(output_dir / "inputs.json") != inputs:
        raise ValueError("Interrupted intelligence checkpoint belongs to different batch inputs")
    write_bytes(output_dir / "inputs.json", json_bytes(inputs))
    write_bytes(output_dir / "catalyst_schedule.json", json_bytes(catalyst_schedule))
    filings = pd.read_parquet(sec_metadata_dir / "filings.parquet")
    pair_filings = _pair_filing_indices(clean, filings)
    source_coverage = _coverage_bounds(
        json.loads((sec_metadata_dir / "coverage.json").read_bytes()), filings
    )
    paths = ProjectPaths(
        Path(__file__).resolve().parents[3], (cache_workspace or output_dir).resolve()
    )
    source_get = get or HttpClient(sec_user_agent).get
    backend = sentiment_backend or _UnavailableTone(tone_policy)
    records, extractions, tones, metadata_rows, audits, packs = [], [], [], [], [], []
    parsed_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
    for index, event in enumerate(cast(list[dict[str, Any]], clean.to_dict("records"))):
        event_filings = pair_filings[event["pair_id"]]
        scheduled = max_events is None or index < max_events
        catalyst_scheduled = scheduled and event["event_id"] in catalyst_ids
        filename = "events/" + hashlib.sha256(event["event_id"].encode()).hexdigest() + ".json"
        checkpoint = output_dir / filename
        if checkpoint.exists():
            record = _load_json(checkpoint)
            if (
                record["event"] != event
                or record["scheduled"] is not scheduled
                or record["catalyst_scheduled"] is not catalyst_scheduled
            ):
                raise ValueError("Research event checkpoint identity differs")
            validate_stored_extraction(record["catalyst_pack"], record["extraction"])
            expected_pack = (
                _event_pack(
                    event,
                    event_filings,
                    source_coverage,
                    paths,
                    _offline_only,
                    offline=True,
                    parsed_cache=parsed_cache,
                )[0]
                if scheduled
                else _empty_pack(event, policy)
            )
            if record["pack"] != expected_pack:
                raise ValueError("Research checkpoint evidence differs from raw reconstruction")
            if record["catalyst_pack"] != (
                expected_pack if catalyst_scheduled else _empty_pack(event, policy)
            ):
                raise ValueError("Research checkpoint catalyst evidence violates its schedule")
        else:
            selected_count = 0
            pack = _empty_pack(event, policy)
            if scheduled:
                pack, selected_count = _event_pack(
                    event,
                    event_filings,
                    source_coverage,
                    paths,
                    source_get,
                    offline=offline,
                    parsed_cache=parsed_cache,
                )
            validate_pack(pack)
            catalyst_pack = pack if catalyst_scheduled else _empty_pack(event, policy)
            extraction = extract_pack(
                catalyst_pack,
                (provider or _disabled_provider) if catalyst_scheduled else _disabled_provider,
                paths.data / "cache",
                provider_name,
                model_name,
                prompt_version=prompt_version,
                provider_config=provider_config,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            tone = score_sentiment_pack(
                pack,
                backend,
                paths.data / "cache" / "sentiment",
                leg_security_ids=[event["leg_a_security_id"], event["leg_b_security_id"]],
                policy=tone_policy,
            )
            record = {
                "event": event,
                "scheduled": scheduled,
                "catalyst_scheduled": catalyst_scheduled,
                "pack": pack,
                "catalyst_pack": catalyst_pack,
                "extraction": extraction,
                "tone": tone,
                "selected_filing_count": selected_count,
            }
            write_bytes(checkpoint, json_bytes(record))
        extractions.append(record["extraction"])
        packs.append(record["pack"])
        tone_features = validate_sentiment_result(
            record["pack"],
            record["tone"],
            leg_security_ids=[event["leg_a_security_id"], event["leg_b_security_id"]],
            policy=tone_policy,
        )
        tones.append(dict(event_id=event["event_id"], **tone_features))
        metadata_rows.append(
            dict(
                event_id=event["event_id"],
                **metadata_event_features(event, event_filings, source_coverage),
            )
        )
        audits.append(
            {
                "event_id": event["event_id"],
                "pair_id": event["pair_id"],
                "event_timestamp": event["event_timestamp"],
                "scheduled": scheduled,
                "catalyst_scheduled": catalyst_scheduled,
                "catalyst_status": record["extraction"]["status"],
                "reason_codes": record["extraction"]["reason_codes"],
                "coverage_a": record["pack"]["coverage"]["A"]["status"],
                "coverage_b": record["pack"]["coverage"]["B"]["status"],
                "tone_a": record["tone"]["legs"]["A"]["status"],
                "tone_b": record["tone"]["legs"]["B"]["status"],
            }
        )
        records.append({"file": filename, "sha256": sha256_file(checkpoint)})
        if progress:
            progress(
                {
                    "stage": "EVENT_INTELLIGENCE",
                    "event_id": event["event_id"],
                    "scheduled": scheduled,
                    "catalyst_scheduled": catalyst_scheduled,
                    "status": record["extraction"]["status"],
                    "completed": index + 1,
                    "total": len(clean),
                }
            )
    identity = {"inputs": inputs, "records": records}
    version = "research_intelligence_" + _sha(identity)[:24]
    features = (
        build_event_feature_frame(clean, extractions, version)
        .merge(
            pd.DataFrame(tones, columns=["event_id", *SENTIMENT_FEATURE_COLUMNS]),
            on="event_id",
            validate="one_to_one",
        )
        .merge(
            pd.DataFrame(metadata_rows, columns=["event_id", *METADATA_FEATURE_COLUMNS]),
            on="event_id",
            validate="one_to_one",
        )
    )
    files: dict[str, str] = {}
    for filename, body in {
        "features.parquet": parquet_bytes(features),
        "events.parquet": parquet_bytes(clean),
        "event_mapping.parquet": parquet_bytes(clean),
        "coverage.json": json_bytes(audits),
        "metadata_observed_bounds.json": json_bytes(source_coverage),
    }.items():
        write_bytes(output_dir / filename, body)
        files[filename] = hashlib.sha256(body).hexdigest()
    files["inputs.json"] = sha256_file(output_dir / "inputs.json")
    files["catalyst_schedule.json"] = sha256_file(output_dir / "catalyst_schedule.json")
    files.update({row["file"]: row["sha256"] for row in records})
    cache_files = _cache_inventory(packs, paths, filings)
    manifest = {
        "schema_version": "research-event-intelligence-v2",
        "inputs": inputs,
        "intelligence_version": version,
        "source_identity": identity,
        "files": files,
        "cache_files": cache_files,
        "feature_columns": list(
            EVENT_FEATURE_NAMES + SENTIMENT_FEATURE_COLUMNS + METADATA_FEATURE_COLUMNS
        ),
        "event_count": len(clean),
        "scheduled_event_count": sum(row["scheduled"] for row in audits),
        "catalyst_selected_event_count": catalyst_schedule["selected_event_count"],
        "catalyst_scheduled_event_count": sum(row["catalyst_scheduled"] for row in audits),
        "catalyst_call_upper_bound": sum(row["catalyst_scheduled"] for row in audits)
        * (1 + max_retries),
        "catalyst_counts": pd.Series([row["catalyst_status"] for row in audits])
        .value_counts()
        .to_dict(),
        "all_events_retained": True,
        "final_test_outcomes_inspected": False,
        "representative_nlp_study_complete": False,
    }
    write_bytes(output_dir / "manifest.json", json_bytes(manifest))
    verify_event_intelligence(
        output_dir, frozen_universe_dir, sec_metadata_dir, cache_workspace=cache_workspace
    )
    return manifest


def verify_event_intelligence(
    directory: Path,
    frozen_universe_dir: Path,
    sec_metadata_dir: Path,
    *,
    cache_workspace: Path | None = None,
) -> dict[str, Any]:
    """Reject changed raw bytes, evidence timestamps, grounded responses or features."""
    freeze = verify_universe_freeze(frozen_universe_dir)
    verify_sec_metadata(sec_metadata_dir, frozen_universe_dir)
    manifest = _load_json(directory / "manifest.json")
    inputs = manifest["inputs"]
    if inputs["shared_cache_workspace"] and cache_workspace is None:
        raise ValueError("Research intelligence requires its explicit shared cache workspace")
    cache_root = (cache_workspace or directory).resolve()
    if (
        manifest.get("schema_version") != "research-event-intelligence-v2"
        or inputs["universe_freeze_id"] != freeze["freeze_id"]
        or inputs["sec_manifest_sha256"] != sha256_file(sec_metadata_dir / "manifest.json")
        or manifest.get("final_test_outcomes_inspected") is not False
    ):
        raise ValueError("Research intelligence input lineage or final-test lock differs")
    for filename, digest in manifest["files"].items():
        if sha256_file(confined_path(directory, filename)) != digest:
            raise ValueError("Research intelligence file checksum differs")
    for filename, digest in manifest["cache_files"].items():
        if sha256_file(confined_path(cache_root, filename)) != digest:
            raise ValueError("Research intelligence source cache checksum differs")
    if (
        manifest["intelligence_version"]
        != "research_intelligence_" + _sha(manifest["source_identity"])[:24]
        or manifest["source_identity"]["inputs"] != inputs
        or _load_json(directory / "inputs.json") != inputs
        or inputs["evidence_policy"] != asdict(RESEARCH_EVIDENCE_POLICY)
    ):
        raise ValueError("Research intelligence identity differs")
    clean = pd.read_parquet(directory / "events.parquet")
    pairs = pd.read_parquet(frozen_universe_dir / "pair_universe.parquet")
    canonical = _event_inputs(clean, pairs)
    pd.testing.assert_frame_equal(pd.read_parquet(directory / "event_mapping.parquet"), clean)
    if _sha(canonical.to_dict("records")) != inputs["events_sha256"]:
        raise ValueError("Research intelligence event registry differs")
    catalyst_schedule = build_catalyst_schedule(
        canonical.loc[:, ["event_id", "pair_id", "event_timestamp"]],
        pairs,
        max_events=inputs["catalyst_max_events"],
        max_calls=inputs["provider_limits"]["max_calls"] or MAX_CATALYST_CALLS,
        max_retries=inputs["max_retries"],
    )
    if (
        _load_json(directory / "catalyst_schedule.json") != catalyst_schedule
        or inputs["catalyst_schedule_sha256"] != catalyst_schedule["schedule_sha256"]
    ):
        raise ValueError("Research catalyst schedule differs from target-blind reconstruction")
    catalyst_ids = set(catalyst_schedule["selected_event_ids"])
    filings = pd.read_parquet(sec_metadata_dir / "filings.parquet")
    pair_filings = _pair_filing_indices(clean, filings)
    source_coverage = _coverage_bounds(
        json.loads((sec_metadata_dir / "coverage.json").read_bytes()), filings
    )
    if _load_json(directory / "metadata_observed_bounds.json") != source_coverage:
        raise ValueError("Research metadata observed coverage bounds differ")
    paths = ProjectPaths(Path(__file__).resolve().parents[3], cache_root)
    tone_policy = FinBERTPolicy(**inputs["sentiment_policy"])
    extractions, tones, metadata_rows, audits = [], [], [], []
    canonical_rows = canonical.to_dict("records")
    records = manifest["source_identity"]["records"]
    parsed_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
    if len(records) != len(canonical_rows):
        raise ValueError("Research checkpoints do not cover the exact event registry")
    for index, row in enumerate(records):
        if manifest["files"].get(row["file"]) != row["sha256"]:
            raise ValueError("Research checkpoint source identity checksum differs")
        record = _load_json(confined_path(directory, row["file"]))
        event = record["event"]
        scheduled = inputs["max_events"] is None or index < inputs["max_events"]
        catalyst_scheduled = scheduled and event["event_id"] in catalyst_ids
        if (
            event != canonical_rows[index]
            or record["scheduled"] is not scheduled
            or record["catalyst_scheduled"] is not catalyst_scheduled
        ):
            raise ValueError("Research checkpoint event or label-blind scheduling differs")
        event_filings = pair_filings[event["pair_id"]]
        validate_pack(record["pack"])
        validate_stored_extraction(record["catalyst_pack"], record["extraction"])
        expected_pack = (
            _event_pack(
                record["event"],
                event_filings,
                source_coverage,
                paths,
                _offline_only,
                offline=True,
                parsed_cache=parsed_cache,
            )[0]
            if record["scheduled"]
            else _empty_pack(record["event"], RESEARCH_EVIDENCE_POLICY)
        )
        if record["pack"] != expected_pack:
            raise ValueError("Research evidence differs from raw-source scientific reconstruction")
        if record["catalyst_pack"] != (
            expected_pack if catalyst_scheduled else _empty_pack(event, RESEARCH_EVIDENCE_POLICY)
        ) or (not catalyst_scheduled and record["extraction"]["status"] != "UNKNOWN"):
            raise ValueError("Research catalyst evidence or response violates the frozen schedule")
        for chunk in record["pack"]["chunks"]:
            if sha256_file(confined_path(cache_root, chunk["raw_file_path"])) != chunk["sha256"]:
                raise ValueError("Research intelligence evidence raw provenance differs")
        extractions.append(record["extraction"])
        tone_features = validate_sentiment_result(
            record["pack"],
            record["tone"],
            leg_security_ids=[event["leg_a_security_id"], event["leg_b_security_id"]],
            policy=tone_policy,
        )
        tones.append(dict(event_id=event["event_id"], **tone_features))
        metadata_rows.append(
            dict(
                event_id=event["event_id"],
                **metadata_event_features(event, event_filings, source_coverage),
            )
        )
        audits.append(
            {
                "event_id": event["event_id"],
                "pair_id": event["pair_id"],
                "event_timestamp": event["event_timestamp"],
                "scheduled": scheduled,
                "catalyst_scheduled": catalyst_scheduled,
                "catalyst_status": record["extraction"]["status"],
                "reason_codes": record["extraction"]["reason_codes"],
                "coverage_a": record["pack"]["coverage"]["A"]["status"],
                "coverage_b": record["pack"]["coverage"]["B"]["status"],
                "tone_a": record["tone"]["legs"]["A"]["status"],
                "tone_b": record["tone"]["legs"]["B"]["status"],
            }
        )
    expected = (
        build_event_feature_frame(canonical, extractions, manifest["intelligence_version"])
        .merge(
            pd.DataFrame(tones, columns=["event_id", *SENTIMENT_FEATURE_COLUMNS]),
            on="event_id",
            validate="one_to_one",
        )
        .merge(
            pd.DataFrame(metadata_rows, columns=["event_id", *METADATA_FEATURE_COLUMNS]),
            on="event_id",
            validate="one_to_one",
        )
    )
    actual = pd.read_parquet(directory / "features.parquet")
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
    if (
        len(actual) != manifest["event_count"]
        or actual["event_id"].duplicated().any()
        or set(actual["event_id"]) != set(canonical["event_id"])
        or manifest["feature_columns"]
        != list(EVENT_FEATURE_NAMES + SENTIMENT_FEATURE_COLUMNS + METADATA_FEATURE_COLUMNS)
        or manifest["scheduled_event_count"] != sum(row["scheduled"] for row in audits)
        or manifest["catalyst_selected_event_count"] != catalyst_schedule["selected_event_count"]
        or manifest["catalyst_scheduled_event_count"]
        != sum(row["catalyst_scheduled"] for row in audits)
        or manifest["catalyst_call_upper_bound"]
        != sum(row["catalyst_scheduled"] for row in audits) * (1 + inputs["max_retries"])
        or json.loads((directory / "coverage.json").read_bytes()) != audits
        or manifest["catalyst_counts"]
        != pd.Series([row["catalyst_status"] for row in audits]).value_counts().to_dict()
    ):
        raise ValueError("Research intelligence does not retain the exact event/feature population")
    return manifest

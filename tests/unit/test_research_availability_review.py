"""Independent SEC clock endpoints and scientific source-inventory reconstruction."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse
from structural_break.data.sec import SUBMISSIONS_BASE_URL, SecDataError
from structural_break.research.availability import acceptance_bounds, ambiguous_cutoff
from structural_break.research.intelligence import (
    _event_inputs,
    _normalized_metadata,
    _source_get,
    collect_sec_metadata,
    verify_sec_metadata,
)
from structural_break.research.model_job import _sec_source
from structural_break.research.universe import freeze_universe, json_bytes, parquet_bytes
from structural_break.storage.files import sha256_file


def _clock_frame() -> pd.DataFrame:
    lower, upper = acceptance_bounds("2021-07-01T17:30:00Z")
    return pd.DataFrame(
        [
            {
                "security_id": "US:KO",
                "form": "8-K",
                "acceptance_lower_bound_utc": lower,
                "acceptance_upper_bound_utc": upper,
            }
        ]
    )


@pytest.mark.parametrize("days", [30, 180, 400])
def test_inclusive_lookback_upper_endpoint_is_uncertain(days: int) -> None:
    frame = _clock_frame()
    cutoff = frame.iloc[0].acceptance_upper_bound_utc + pd.Timedelta(days=days)
    assert ambiguous_cutoff(frame, "US:KO", cutoff)


@pytest.mark.parametrize("days", [30, 180, 400])
def test_inclusive_lookback_lower_endpoint_is_fully_included(days: int) -> None:
    frame = _clock_frame()
    cutoff = frame.iloc[0].acceptance_lower_bound_utc + pd.Timedelta(days=days)
    assert not ambiguous_cutoff(frame, "US:KO", cutoff)


def test_admission_upper_endpoint_is_known_but_lower_is_uncertain() -> None:
    frame = _clock_frame()
    assert not ambiguous_cutoff(frame, "US:KO", frame.iloc[0].acceptance_upper_bound_utc)
    assert ambiguous_cutoff(frame, "US:KO", frame.iloc[0].acceptance_lower_bound_utc)


@pytest.mark.parametrize(
    "raw",
    ["2021-11-07T01:30:00", "2021-11-07T01:30:00Z", "2021-03-14T02:30:00", "2021-03-14T02:30:00Z"],
)
def test_dst_uncertainty_fails_closed_instead_of_guessing_a_fold(raw: str) -> None:
    with pytest.raises(SecDataError):
        acceptance_bounds(raw)


def _pairs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pair_id": "KO__PEP",
                "leg_a": "KO",
                "leg_b": "PEP",
                "leg_a_security_id": "US:KO",
                "leg_b_security_id": "US:PEP",
            }
        ]
    )


def test_nonzero_offset_cannot_hide_utc_final_test_event() -> None:
    events = pd.DataFrame(
        [{"event_id": "x", "pair_id": "KO__PEP", "event_timestamp": "2023-12-31T23:00:00-05:00"}]
    )
    with pytest.raises(ValueError, match="development"):
        _event_inputs(events, _pairs())


def test_mixed_offsets_are_normalized_before_chronological_scheduling() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "later",
                "pair_id": "KO__PEP",
                "event_timestamp": "2022-03-10T10:00:00-05:00",
            },
            {
                "event_id": "earlier",
                "pair_id": "KO__PEP",
                "event_timestamp": "2022-03-10T13:00:00Z",
            },
        ]
    )
    result = _event_inputs(events, _pairs())
    assert result.event_id.tolist() == ["earlier", "later"]
    assert result.event_timestamp.tolist() == [
        "2022-03-10T13:00:00+00:00",
        "2022-03-10T15:00:00+00:00",
    ]


@pytest.mark.parametrize("cutoff", [None, pd.NaT, "NaT"])
def test_missing_cutoff_is_blocked_before_any_evidence(cutoff: object) -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "x",
                "pair_id": "KO__PEP",
                "event_timestamp": "2022-03-10T21:00:00Z",
                "evidence_cutoff": cutoff,
            }
        ]
    )
    with pytest.raises(ValueError):
        _event_inputs(events, _pairs())


@pytest.mark.parametrize(
    "stamp,cutoff",
    [
        ("2022-03-10T00:00:00Z", "2022-03-10T00:00:00Z"),
        ("2022-03-09T20:00:00-04:00", "2022-03-10T00:00:00Z"),
        ("2022-03-12T01:30:00+02:00", "2022-03-11T23:30:00Z"),
    ],
)
def test_continuity_inclusive_start_and_pre_exclusive_end_are_admissible(
    stamp: str, cutoff: str
) -> None:
    pairs = _pairs().assign(active_from="2022-03-10", active_to="2022-03-12")
    events = pd.DataFrame(
        [
            {
                "event_id": "x",
                "pair_id": "KO__PEP",
                "event_timestamp": stamp,
                "evidence_cutoff": cutoff,
            }
        ]
    )
    result = _event_inputs(events, pairs)
    assert len(result) == 1
    assert result.iloc[0].event_timestamp == pd.Timestamp(stamp).tz_convert("UTC").isoformat()
    assert result.iloc[0].evidence_cutoff == pd.Timestamp(cutoff).tz_convert("UTC").isoformat()


@pytest.mark.parametrize(
    "stamp,cutoff",
    [
        ("2022-03-09T23:59:59Z", "2022-03-09T23:59:59Z"),
        ("2022-03-10T00:00:00Z", "2022-03-09T23:59:59Z"),
        ("2022-03-10T00:00:00Z", "2022-03-10T01:59:59+02:00"),
        ("2022-03-12T00:00:00Z", "2022-03-11T23:59:59Z"),
        ("2022-03-13T00:00:00Z", "2022-03-13T00:00:00Z"),
        ("2022-03-11T20:30:00-04:00", "2022-03-12T00:00:00Z"),
    ],
)
def test_continuity_rejects_pre_floor_signal_or_cutoff_and_on_after_exclusive_end(
    stamp: str, cutoff: str
) -> None:
    pairs = _pairs().assign(active_from="2022-03-10", active_to="2022-03-12")
    events = pd.DataFrame(
        [
            {
                "event_id": "x",
                "pair_id": "KO__PEP",
                "event_timestamp": stamp,
                "evidence_cutoff": cutoff,
            }
        ]
    )
    with pytest.raises(ValueError, match="continuity"):
        _event_inputs(events, pairs)


@pytest.fixture
def review_freeze(tmp_path: Path, project_root: Path, config: ProjectConfig) -> Path:
    payload = yaml.safe_load(
        (project_root / "configs/research_v2_universe.yaml").read_text(encoding="utf-8")
    )
    payload["groups"] = [payload["groups"][0]]
    payload["groups"][0]["tickers"] = ["KO", "PEP", "KDP"]
    payload["issuer_rules"] = {}
    roster = tmp_path / "review_roster.yaml"
    roster.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config_payload = config.model_dump(mode="json")
    config_payload["universe"]["pairs"] = config_payload["universe"]["pairs"][:1]
    original = ProjectConfig.model_validate(config_payload)
    company_map = json_bytes(
        {
            str(index): {
                "ticker": ticker,
                "cik_str": 9000000 + index,
                "title": f"Review fixture {ticker}",
            }
            for index, ticker in enumerate(("KO", "PEP", "KDP"))
        }
    )
    output = tmp_path / "review_freeze"
    freeze_universe(roster, original, company_map, output)
    return output


def _review_source(*, missing: bool = False):
    def get(url: str) -> FetchedResponse:
        name = url.rsplit("/", 1)[1]
        cik = name[3:13]
        historical = "-submissions-" in name
        rows = {
            "accessionNumber": [f"{cik}-{'10' if historical else '22'}-000001"],
            "form": ["10-K"],
            "filingDate": ["2010-02-01" if historical else "2022-02-01"],
            "acceptanceDateTime": [
                None
                if missing
                else ("2010-02-01T21:30:00-05:00" if historical else "2022-02-01T21:30:00-05:00")
            ],
            "primaryDocument": ["report.htm"],
        }
        payload = (
            rows
            if historical
            else {
                "cik": int(cik),
                "filings": {
                    "recent": rows,
                    "files": [
                        {
                            "name": f"CIK{cik}-submissions-001.json",
                            "filingFrom": "2004-01-01",
                            "filingTo": "2015-12-31",
                        }
                    ],
                },
            }
        )
        return FetchedResponse(json_bytes(payload), url, 200, datetime(2026, 10, 6, tzinfo=UTC))

    return get


def _restamp(directory: Path, freeze: Path, manifest: dict, sources: list, coverage: list) -> None:
    """Make a self-consistent candidate: scientific reconstruction must still reject it."""
    manifest["source_identity"] = {
        "inputs": manifest["inputs"],
        "sources": sources,
        "coverage": coverage,
    }
    manifest["data_snapshot_id"] = (
        "research_sec_" + hashlib.sha256(json_bytes(manifest["source_identity"])).hexdigest()[:24]
    )
    securities = pd.read_parquet(freeze / "security_master.parquet")
    filings = _normalized_metadata(
        sources, directory, securities, manifest["inputs"], manifest["data_snapshot_id"]
    )
    (directory / "sources.json").write_bytes(json_bytes(sources))
    (directory / "coverage.json").write_bytes(json_bytes(coverage))
    (directory / "filings.parquet").write_bytes(parquet_bytes(filings))
    manifest["filing_count"] = len(filings)
    manifest["files"] = {
        name: sha256_file(directory / name)
        for name in ("filings.parquet", "sources.json", "coverage.json")
    }
    for source in sources:
        for name in (source["file"], source["file"] + ".source.json"):
            manifest["files"][name] = sha256_file(directory / name)
    (directory / "manifest.json").write_bytes(json_bytes(manifest))


def test_declared_intersecting_history_cannot_be_omitted_as_complete(
    review_freeze: Path, tmp_path: Path
) -> None:
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(review_freeze, output, get=_review_source())
    sources = json.loads((output / "sources.json").read_bytes())
    coverage = json.loads((output / "coverage.json").read_bytes())
    cik = coverage[0]["cik"]
    sources = [
        source
        for source in sources
        if not (source["cik"] == cik and "-submissions-" in source["request_url"])
    ]
    coverage[0]["metadata_sources"] = 1
    _restamp(output, review_freeze, manifest, sources, coverage)
    with pytest.raises(ValueError, match="coverage"):
        verify_sec_metadata(output, review_freeze)


def test_missing_acceptance_count_is_reconstructed_not_trusted(
    review_freeze: Path, tmp_path: Path
) -> None:
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(review_freeze, output, get=_review_source(missing=True))
    sources = json.loads((output / "sources.json").read_bytes())
    coverage = json.loads((output / "coverage.json").read_bytes())
    coverage[0]["missing_acceptance_count"] = 0
    _restamp(output, review_freeze, manifest, sources, coverage)
    with pytest.raises(ValueError, match="coverage"):
        verify_sec_metadata(output, review_freeze)


def test_successful_required_history_cannot_be_excluded_as_complete(
    review_freeze: Path, tmp_path: Path
) -> None:
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(review_freeze, output, get=_review_source())
    sources = json.loads((output / "sources.json").read_bytes())
    coverage = json.loads((output / "coverage.json").read_bytes())
    source = next(row for row in sources if "-submissions-" in row["request_url"])
    source["included"] = False
    next(row for row in coverage if row["cik"] == source["cik"])["metadata_sources"] -= 1
    _restamp(output, review_freeze, manifest, sources, coverage)
    with pytest.raises(ValueError, match="inclusion"):
        verify_sec_metadata(output, review_freeze)


def test_legitimate_legacy_clock_snapshot_still_replays(
    review_freeze: Path, tmp_path: Path
) -> None:
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(review_freeze, output, get=_review_source())
    manifest["schema_version"] = "research-sec-metadata-v1"
    manifest["inputs"].pop("acceptance_policy")
    manifest["inputs"].pop("availability_implementation_sha256")
    _restamp(
        output,
        review_freeze,
        manifest,
        json.loads((output / "sources.json").read_bytes()),
        json.loads((output / "coverage.json").read_bytes()),
    )
    assert verify_sec_metadata(output, review_freeze) == manifest


@pytest.mark.parametrize("failure", ["http_403", "bad_json", "network"])
def test_source_failures_reconstruct_unknown_with_successful_prefix_retained(
    review_freeze: Path, tmp_path: Path, failure: str
) -> None:
    from structural_break.data.http import SourceError

    valid = _review_source()

    def failed(url: str) -> FetchedResponse:
        if "-submissions-" not in url:
            return valid(url)
        if failure == "network":
            raise SourceError(url)
        return FetchedResponse(
            b"invalid JSON" if failure == "bad_json" else b"{}",
            url,
            200 if failure == "bad_json" else 403,
            datetime(2026, 10, 6, tzinfo=UTC),
        )

    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(review_freeze, output, get=failed)
    coverage = json.loads((output / "coverage.json").read_bytes())
    assert all(row["status"] == "UNKNOWN" and row["metadata_sources"] == 1 for row in coverage)
    assert manifest["filing_count"] == 3 and manifest["complete_source_issuer_count"] == 0
    assert verify_sec_metadata(output, review_freeze) == manifest


def test_capture_summary_counts_cannot_disagree_with_reconstructed_rows(
    review_freeze: Path, tmp_path: Path
) -> None:
    output = tmp_path / "metadata"
    manifest = collect_sec_metadata(review_freeze, output, get=_review_source())
    manifest["complete_source_issuer_count"] = 999
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match="counts"):
        verify_sec_metadata(output, review_freeze)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://example.com/metadata.json"),
        ("retrieved_at_utc", "2026-10-06T00:00:00"),
        ("status_code", True),
    ],
)
def test_cached_response_cannot_relabel_source_time_or_status(
    tmp_path: Path, field: str, value: object
) -> None:
    url = SUBMISSIONS_BASE_URL + "CIK0009000000.json"
    getter = _source_get(tmp_path, _review_source(), {})
    getter(url)
    metadata = tmp_path / "data/raw/sec/submissions/CIK0009000000.json.source.json"
    record = json.loads(metadata.read_bytes())
    record[field] = value
    metadata.write_bytes(json_bytes(record))
    with pytest.raises(ValueError):
        _source_get(tmp_path, lambda _: pytest.fail("Must remain offline"), {})(url)


def test_model_job_selects_bound_sec_snapshot_even_when_active_alias_differs(
    tmp_path: Path, project_root: Path
) -> None:
    workspace = tmp_path / "workspace"
    old, exact = workspace / "sec_metadata/source_v1", workspace / "sec_metadata/source_v2"
    old.mkdir(parents=True)
    exact.mkdir(parents=True)
    (old / "manifest.json").write_bytes(json_bytes({"snapshot": "older"}))
    (exact / "manifest.json").write_bytes(json_bytes({"snapshot": "bound"}))
    intelligence = workspace / "intelligence/batch"
    intelligence.mkdir(parents=True)
    (intelligence / "manifest.json").write_bytes(
        json_bytes({"inputs": {"sec_manifest_sha256": sha256_file(exact / "manifest.json")}})
    )
    assert _sec_source(ProjectPaths(project_root, workspace), intelligence) == exact

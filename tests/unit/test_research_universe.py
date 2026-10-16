import copy
import hashlib
import json
from datetime import UTC, date, datetime

import pandas as pd
import pytest
import yaml

from structural_break.config.models import ProjectConfig
from structural_break.data.http import FetchedResponse
from structural_break.data.market import VIX_URL, session_schedule
from structural_break.research.market import collect_market, verify_market_capture
from structural_break.research.universe import (
    expand_pairs,
    freeze_universe,
    load_research_universe,
    verify_universe_freeze,
)


@pytest.fixture
def roster_path(project_root):
    return project_root / "configs/research_v2_universe.yaml"


@pytest.fixture
def directory(roster_path):
    universe = load_research_universe(roster_path)
    return json.dumps(
        {
            str(index): {"ticker": ticker, "cik_str": 9000000 + index, "title": f"Fixture {ticker}"}
            for index, ticker in enumerate(universe.tickers)
        }
    ).encode()


@pytest.fixture
def small_freeze(tmp_path, roster_path, config):
    payload = yaml.safe_load(roster_path.read_text(encoding="utf-8"))
    payload["groups"] = [payload["groups"][0]]
    payload["groups"][0]["tickers"] = ["KO", "PEP", "KDP"]
    payload["issuer_rules"] = {}
    path = tmp_path / "small.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config_payload = config.model_dump(mode="json")
    config_payload["universe"]["pairs"] = config_payload["universe"]["pairs"][:1]
    small = ProjectConfig.model_validate(config_payload)
    directory = json.dumps(
        {
            str(index): {"ticker": ticker, "cik_str": 9000000 + index, "title": f"Fixture {ticker}"}
            for index, ticker in enumerate(("KO", "PEP", "KDP"))
        }
    ).encode()
    output = tmp_path / "freeze"
    freeze_universe(path, small, directory, output)
    return output


def test_roster_expands_before_outcomes_preserves_all_originals(roster_path, config):
    universe = load_research_universe(roster_path)
    pairs = expand_pairs(universe, config.universe.pairs)
    assert len(universe.tickers) == 250
    assert 500 <= len(pairs) <= 1000
    assert universe.membership_policy == "current_survivor_conditioned_prototype"
    assert len(pairs.loc[pairs.original_reference_pair]) == 28
    for pair in config.universe.pairs:
        row = pairs.set_index("pair_id").loc[pair.pair_id]
        assert (row.leg_a, row.leg_b, row.peer_group) == (pair.leg_a, pair.leg_b, pair.peer_group)
    added = pairs.loc[~pairs.original_reference_pair]
    assert added.leg_a_security_id.lt(added.leg_b_security_id).all()
    identities = [frozenset((row.leg_a, row.leg_b)) for row in pairs.itertuples()]
    assert len(identities) == len(set(identities))
    assert pairs.orientation.eq("leg_a_is_y").all()


def test_reordered_inputs_reproduce_pairs(roster_path, config):
    universe = load_research_universe(roster_path)
    alternate = universe.model_copy(update={"groups": tuple(reversed(universe.groups))})
    left = expand_pairs(universe, config.universe.pairs)
    right = expand_pairs(alternate, tuple(reversed(config.universe.pairs)))
    pd.testing.assert_frame_equal(left, right)


def test_freeze_records_sources_identity_floors_and_survivor_limits(
    roster_path, config, directory, tmp_path
):
    manifest = freeze_universe(roster_path, config, directory, tmp_path)
    assert manifest["candidate_count"] == manifest["included_security_count"] == 250
    assert manifest["outcome_blind"] is True
    assert manifest["delisting_complete"] is False
    assert manifest["historical_membership_reconstructed"] is False
    assert manifest["domestic_reporting_source_check_complete"] is False
    assert manifest["inputs"]["sec_directory_sha256"] == hashlib.sha256(directory).hexdigest()
    securities = pd.read_parquet(tmp_path / "security_master.parquet").set_index("ticker")
    assert securities.loc["XOM", "cik"] == "0000034088"
    assert securities.loc["XOM", "cik"] != securities.loc["XOM", "directory_cik"]
    assert securities.loc["GM", "identity_valid_from"] == date(2010, 11, 18)
    assert securities.loc["CB", "identity_valid_from"] == date(2016, 1, 15)
    assert "legal_listing_date" not in securities
    assert freeze_universe(roster_path, config, directory, tmp_path) == manifest


@pytest.mark.parametrize("filename", ["roster.yaml", "sec_directory.json", "pair_universe.parquet"])
def test_frozen_source_or_pair_mutation_fails(small_freeze, filename):
    path = small_freeze / filename
    path.write_bytes(path.read_bytes() + b" changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_universe_freeze(small_freeze)


def test_missing_original_identity_is_a_freeze_blocker(roster_path, config, directory, tmp_path):
    payload = json.loads(directory)
    payload = {key: value for key, value in payload.items() if value["ticker"] != "KO"}
    with pytest.raises(ValueError, match="original issuer"):
        freeze_universe(roster_path, config, json.dumps(payload).encode(), tmp_path)
    assert not (tmp_path / "manifest.json").exists()


def test_missing_added_identity_is_audited_not_selected_by_outcome(
    roster_path, config, directory, tmp_path
):
    payload = json.loads(directory)
    payload = {key: value for key, value in payload.items() if value["ticker"] != "CELH"}
    manifest = freeze_universe(roster_path, config, json.dumps(payload).encode(), tmp_path)
    assert manifest["included_security_count"] == 249
    assert json.loads((tmp_path / "exclusions.json").read_bytes()) == [
        {"ticker": "CELH", "reason": "SEC_IDENTITY_MISSING_OR_AMBIGUOUS"}
    ]


def test_current_cik_collision_is_excluded_for_both_added_candidates(
    roster_path, config, directory, tmp_path
):
    payload = json.loads(directory)
    by_ticker = {value["ticker"]: value for value in payload.values()}
    by_ticker["CELH"]["cik_str"] = by_ticker["FIZZ"]["cik_str"]
    manifest = freeze_universe(roster_path, config, json.dumps(payload).encode(), tmp_path)
    assert manifest["included_security_count"] == 248
    exclusions = json.loads((tmp_path / "exclusions.json").read_bytes())
    assert {row["ticker"] for row in exclusions} == {"CELH", "FIZZ"}


def test_unrostered_identity_rule_and_duplicate_yaml_fail(roster_path, tmp_path):
    payload = yaml.safe_load(roster_path.read_text(encoding="utf-8"))
    changed = copy.deepcopy(payload)
    changed["issuer_rules"]["NOTINROSTER"] = changed["issuer_rules"]["GM"]
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="Identity rules"):
        load_research_universe(path)
    path.write_text(
        roster_path.read_text(encoding="utf-8") + "\nversion: duplicate\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Duplicate YAML key"):
        load_research_universe(path)


def fixture_download(requests, *, missing=None):
    def download(tickers, **kwargs):
        ticker = tickers[0]
        requests.append((ticker, kwargs))
        if ticker == missing:
            return pd.DataFrame()
        end = pd.Timestamp(kwargs["end"]).date()
        days = session_schedule(pd.Timestamp(kwargs["start"]).date(), end)["trading_date"]
        days = [day for day in days if day < end]
        # A deliberate missing source session is never forward-filled.
        days = [day for index, day in enumerate(days) if ticker != "KO" or index != 3]
        return pd.DataFrame(
            {
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Adj Close": 100.0,
                "Volume": 1000.0,
                "Dividends": 0.0,
                "Stock Splits": 0.0,
            },
            index=pd.DatetimeIndex(days),
        )

    return download


def fixture_vix(url):
    assert url == VIX_URL
    days = session_schedule(date(2003, 12, 20), date(2004, 2, 28))["trading_date"]
    frame = pd.DataFrame(
        {
            "DATE": [day.strftime("%m/%d/%Y") for day in days],
            "OPEN": 20.0,
            "HIGH": 22.0,
            "LOW": 18.0,
            "CLOSE": 21.0,
        }
    )
    return FetchedResponse(frame.to_csv(index=False).encode(), url, 200, datetime.now(UTC))


def test_offline_market_freeze_is_engine_compatible_and_reports_gaps(small_freeze, tmp_path):
    requests = []
    output = tmp_path / "market"
    manifest = collect_market(
        small_freeze,
        output,
        date(2004, 1, 1),
        date(2004, 2, 27),
        downloader=fixture_download(requests),
        get=fixture_vix,
        sleeper=lambda delay: None,
    )
    assert manifest["available_issuer_count"] == 3
    assert manifest["included_pair_count"] == 3
    assert manifest["final_test_prices_collected"] is False
    assert set(ticker for ticker, _ in requests) == {"KO", "PEP", "KDP", "SPY", "XLP"}
    for _, request in requests:
        assert request["auto_adjust"] is False and request["repair"] is False
        assert request["actions"] is True and request["threads"] is False
    prices = pd.read_parquet(output / "prices.parquet")
    assert {
        "ticker",
        "trading_date",
        "adj_close",
        "data_available_at",
        "quality_flag",
        "source_snapshot_id",
        "sha256",
        "data_snapshot_id",
    } <= set(prices)
    assert prices["data_snapshot_id"].eq(manifest["data_snapshot_id"]).all()
    report = json.loads((output / "coverage.json").read_bytes())
    ko = next(row for row in report if row["ticker"] == "KO")
    assert ko["internal_missing_or_invalid_sessions"] == 1
    assert ko["legal_listing_date"] is ko["legal_delisting_date"] is None
    context = pd.read_parquet(output / "market_context.parquet")
    assert context["vix_context_lag_sessions"].eq(1).all()
    assert context["vix_observation_date"].lt(context["trading_date"]).all()
    old_calls = len(requests)
    assert (
        collect_market(
            small_freeze,
            output,
            date(2004, 1, 1),
            date(2004, 2, 27),
            downloader=fixture_download(requests),
            get=fixture_vix,
            sleeper=lambda delay: None,
        )
        == manifest
    )
    assert len(requests) == old_calls


def test_failed_issuer_does_not_remove_other_sources_or_hide_exclusions(small_freeze, tmp_path):
    manifest = collect_market(
        small_freeze,
        tmp_path / "market",
        date(2004, 1, 1),
        date(2004, 2, 27),
        downloader=fixture_download([], missing="KDP"),
        get=fixture_vix,
        attempts=1,
        sleeper=lambda delay: None,
    )
    assert manifest["available_issuer_count"] == 2
    assert manifest["included_pair_count"] == 1
    exclusions = json.loads((tmp_path / "market/exclusions.json").read_bytes())
    assert exclusions["issuers"][0]["ticker"] == "KDP"
    assert len(exclusions["pairs"]) == 2


def test_final_test_source_range_rejected_before_any_source_calls(small_freeze, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("No source call may occur for a forbidden final-test range")

    with pytest.raises(ValueError, match="2023"):
        collect_market(
            small_freeze, tmp_path / "market", end=date(2024, 1, 1), downloader=forbidden
        )


def test_market_raw_and_curated_tampering_fail_verification(small_freeze, tmp_path):
    output = tmp_path / "market"
    collect_market(
        small_freeze,
        output,
        date(2004, 1, 1),
        date(2004, 2, 27),
        downloader=fixture_download([]),
        get=fixture_vix,
        sleeper=lambda delay: None,
    )
    raw = output / "raw/KO.parquet"
    raw.write_bytes(raw.read_bytes() + b"bad")
    with pytest.raises(ValueError, match="checksum"):
        verify_market_capture(output, small_freeze)


def test_interrupted_capture_corrupt_cache_is_not_relabelled_a_source_exclusion(
    small_freeze, tmp_path
):
    output = tmp_path / "market"
    collect_market(
        small_freeze,
        output,
        date(2004, 1, 1),
        date(2004, 2, 27),
        downloader=fixture_download([]),
        get=fixture_vix,
        sleeper=lambda delay: None,
    )
    (output / "manifest.json").unlink()
    raw = output / "raw/KO.parquet"
    raw.write_bytes(raw.read_bytes() + b"bad")
    with pytest.raises(ValueError, match="cache failed integrity"):
        collect_market(
            small_freeze,
            output,
            date(2004, 1, 1),
            date(2004, 2, 27),
            downloader=fixture_download([]),
            get=fixture_vix,
            sleeper=lambda delay: None,
        )
    assert not (output / "manifest.json").exists()


def test_reviewed_identity_floor_bounds_download_before_source_calls(
    small_freeze, tmp_path, config
):
    roster = yaml.safe_load((small_freeze / "roster.yaml").read_text("utf-8"))
    roster["issuer_rules"]["KO"] = {
        "identity_valid_from": "2004-01-20",
        "notes": "Synthetic reviewed continuity floor",
        "source_links": ["https://www.sec.gov/search-filings"],
    }
    path = tmp_path / "dated.yaml"
    path.write_text(yaml.safe_dump(roster), encoding="utf-8")
    settings = config.model_dump(mode="json")
    settings["universe"] = json.loads((small_freeze / "original_universe.json").read_bytes())
    new_freeze = tmp_path / "dated_freeze"
    freeze_universe(
        path,
        ProjectConfig.model_validate(settings),
        (small_freeze / "sec_directory.json").read_bytes(),
        new_freeze,
    )
    requests = []
    collect_market(
        new_freeze,
        tmp_path / "market",
        date(2004, 1, 1),
        date(2004, 2, 27),
        downloader=fixture_download(requests),
        get=fixture_vix,
        sleeper=lambda delay: None,
    )
    ko_requests = [kwargs for ticker, kwargs in requests if ticker == "KO"]
    assert len(ko_requests) == 1
    assert ko_requests[0]["start"] == "2004-01-20"
    coverage = json.loads((tmp_path / "market/coverage.json").read_bytes())
    ko = next(row for row in coverage if row["ticker"] == "KO")
    assert ko["identity_valid_from"] == "2004-01-20"
    assert ko["legal_listing_date"] is None

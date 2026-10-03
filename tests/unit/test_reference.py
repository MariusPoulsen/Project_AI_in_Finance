import copy
import hashlib
from datetime import UTC, datetime

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from structural_break.config.models import ProjectConfig
from structural_break.pairs.reference import build_reference, required_tickers


@pytest.fixture
def metadata_path(project_root):
    return project_root / "configs/securities.yaml"


@pytest.fixture
def ticker_map(config):
    """Synthetic identities for coverage testing, never external research data."""
    tickers = sorted(
        {ticker for pair in config.universe.pairs for ticker in (pair.leg_a, pair.leg_b)}
    )
    return {
        str(index): {"ticker": ticker, "cik_str": 9000000 + index, "title": f"Fixture {ticker}"}
        for index, ticker in enumerate(tickers)
    }


@pytest.fixture
def lineage():
    return {
        "source_snapshot_id": "sec_20261003_000000Z",
        "data_snapshot_id": "snap_20261003_000000Z",
        "raw_file_path": "raw/sec/company_tickers/sec_20261003_000000Z.json",
        "sha256": hashlib.sha256(b"offline ticker fixture").hexdigest(),
        "retrieved_at": datetime(2026, 10, 3, tzinfo=UTC),
    }


def test_reference_is_complete_and_preserves_fixed_orientation(
    config, metadata_path, ticker_map, lineage
):
    securities, pairs, sectors = build_reference(config, metadata_path, ticker_map, **lineage)
    assert len(securities) == 56
    assert securities["ticker"].is_unique
    assert securities["security_id"].str.startswith("US:").all()
    assert securities["cik"].str.fullmatch(r"\d{10}").all()
    assert len(pairs) == 28
    assert pairs["pair_id"].tolist() == [pair.pair_id for pair in config.universe.pairs]
    assert list(zip(pairs["leg_a"], pairs["leg_b"], strict=True)) == [
        (pair.leg_a, pair.leg_b) for pair in config.universe.pairs
    ]
    assert set(pairs["leg_a_security_id"]) | set(pairs["leg_b_security_id"]) == set(
        securities["security_id"]
    )
    assert pairs["orientation"].eq("leg_a_is_y").all()
    assert securities["active_from"].isna().all()
    assert securities["active_to"].isna().all()
    assert securities["lifecycle_status"].eq("UNKNOWN").all()
    assert len(sectors) == 8
    assert sectors["sector"].is_unique
    assert sectors["sector_etf"].is_unique
    for frame in (securities, pairs, sectors):
        for key, value in lineage.items():
            assert frame[key].eq(value).all()
        assert frame["reference_version"].eq("securities-28-v1").all()
        assert (
            frame["reference_sha256"]
            .eq(hashlib.sha256(metadata_path.read_bytes()).hexdigest())
            .all()
        )
        assert frame["manual_review_status"].eq("APPROVED").all()
        assert str(frame["reviewed_at"].dtype) == "datetime64[ns, UTC]"


def test_same_inputs_reproduce_reference(config, metadata_path, ticker_map, lineage):
    first = build_reference(config, metadata_path, ticker_map, **lineage)
    second = build_reference(
        config, metadata_path, dict(reversed(list(ticker_map.items()))), **lineage
    )
    for left, right in zip(first, second, strict=True):
        pd.testing.assert_frame_equal(left, right)


def test_benchmarks_are_separate_and_only_used_tickers_are_requested(config, metadata_path):
    requested = required_tickers(config, metadata_path)
    assert len(requested) == 65
    assert len(requested) == len(set(requested))
    assert requested == tuple(sorted(requested))
    assert set(requested) >= {"SPY", "XLP", "XLY", "XLE", "XLF", "XLV", "XLI", "XLK", "XLU"}
    assert {"XLC", "XLB", "XLRE"}.isdisjoint(requested)


def test_known_sec_json_shape_and_canonical_issuer_names(config, metadata_path, tmp_path, lineage):
    # Realistic SEC JSON subset retaining original title/cik_str/ticker field shapes.
    subset = {
        "0": {"cik_str": 21344, "ticker": "KO", "title": "COCA COLA CO"},
        "1": {"cik_str": 77476, "ticker": "PEP", "title": "PEPSICO INC"},
        "2": {"cik_str": 354950, "ticker": "HD", "title": "HOME DEPOT, INC."},
        "3": {"cik_str": 60667, "ticker": "LOW", "title": "LOWES COMPANIES INC"},
    }
    raw = config.model_dump(mode="json")
    raw["universe"]["pairs"] = raw["universe"]["pairs"][:2]
    small_config = ProjectConfig.model_validate(raw)
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["securities"] = metadata["securities"][:4]
    small_path = tmp_path / "securities.yaml"
    small_path.write_text(yaml.safe_dump(metadata), encoding="utf-8")
    securities, pairs, _ = build_reference(small_config, small_path, subset, **lineage)
    ko = securities.set_index("ticker").loc["KO"]
    assert ko["cik"] == "0000021344"
    assert ko["issuer_name"] == ko["name"] == "COCA COLA CO"
    assert pairs["pair_id"].tolist() == ["KO__PEP", "HD__LOW"]


@pytest.mark.parametrize("mode", ["missing", "symbol_case", "duplicate", "cik_collision"])
def test_missing_and_ambiguous_sec_identities_fail(
    config, metadata_path, ticker_map, lineage, mode
):
    identities = copy.deepcopy(ticker_map)
    first = identities["0"]
    if mode == "missing":
        del identities["0"]
    elif mode == "symbol_case":
        first["ticker"] = first["ticker"].lower()
    elif mode == "duplicate":
        identities["another"] = first.copy()
    elif mode == "cik_collision":
        identities["1"]["cik_str"] = first["cik_str"]
    with pytest.raises(ValueError, match="Missing exact|Ambiguous"):
        build_reference(config, metadata_path, identities, **lineage)


@pytest.mark.parametrize("bad_cik", [True, 0, -1, 1.5, "00000000000", "12bad", None])
def test_invalid_sec_cik_does_not_become_an_identity(
    config, metadata_path, ticker_map, lineage, bad_cik
):
    ticker_map["0"]["cik_str"] = bad_cik
    with pytest.raises(ValueError, match="Invalid SEC CIK"):
        build_reference(config, metadata_path, ticker_map, **lineage)


@pytest.mark.parametrize("bad_title", ["", "  ", None, 123])
def test_missing_sec_title_fails(config, metadata_path, ticker_map, lineage, bad_title):
    ticker_map["0"]["title"] = bad_title
    with pytest.raises(ValueError, match="issuer title"):
        build_reference(config, metadata_path, ticker_map, **lineage)


@pytest.mark.parametrize(
    "change",
    ["reject", "missing", "unexpected", "duplicate", "etf", "economic", "version", "lifecycle"],
)
def test_unreviewed_or_inconsistent_metadata_fails(config, metadata_path, tmp_path, change):
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    first = payload["securities"][0]
    if change == "reject":
        first["manual_review_status"] = "REJECTED"
    elif change == "missing":
        payload["securities"].pop()
    elif change == "unexpected":
        first["ticker"] = "EXTRA"
    elif change == "duplicate":
        payload["securities"].append(first.copy())
    elif change == "etf":
        first["sector_etf"] = "XLY"
    elif change == "economic":
        first["sub_industry"] = "Unrelated issuer"
    elif change == "version":
        payload["universe_version"] = "unapproved-v2"
    elif change == "lifecycle":
        first["active_from"], first["active_to"] = "2025-01-01", "2024-01-01"
    changed_path = tmp_path / "securities.yaml"
    changed_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        required_tickers(config, changed_path)


def test_invented_benchmark_map_is_rejected(config, metadata_path, tmp_path):
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    payload["securities"][0]["sector_etf"] = "MISSING"
    changed_path = tmp_path / "securities.yaml"
    changed_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Sector ETF mismatch"):
        required_tickers(config, changed_path)


def test_timezone_and_hash_required(config, metadata_path, ticker_map, lineage):
    with pytest.raises(ValueError, match="timezone"):
        build_reference(
            config, metadata_path, ticker_map, **{**lineage, "retrieved_at": datetime(2026, 10, 3)}
        )
    with pytest.raises(ValueError, match="SHA-256"):
        build_reference(config, metadata_path, ticker_map, **{**lineage, "sha256": "no-hash"})


def test_review_timestamp_requires_timezone(config, metadata_path, tmp_path):
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    payload["reviewed_at"] = "2026-10-03T00:00:00"
    changed_path = tmp_path / "securities.yaml"
    changed_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="timezone"):
        required_tickers(config, changed_path)

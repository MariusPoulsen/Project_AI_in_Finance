"""The production ingestion/replay/publication path against explicit source fixtures."""

import json
import shutil
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pyarrow.parquet as pq
import pytest

from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths
from structural_break.data.snapshots import verify_snapshot
from structural_break.services import ingestion
from structural_break.services.data_queries import DataRepository
from structural_break.services.ingestion import DataQualityError, ingest_data
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file
from structural_break.storage.publication import VIEW_NAMES


@pytest.fixture
def sources_fixture(project_root):
    return project_root / "tests/fixtures/phase1"


@pytest.fixture
def published(paths, config, sources_fixture):
    manifest = ingest_data(
        paths,
        config,
        RuntimeSettings(),
        snapshot_id="fixture_first",
        fixture=sources_fixture,
    )
    return manifest


def canonical_hashes(paths, manifest):
    return {
        item["dataset"]: sha256_file(paths.data_path(item["dataset"]))
        for item in manifest["curated_files"]
    }


def read_frozen(paths, manifest):
    return {
        item["dataset"]: pq.read_table(paths.workspace_root / item["path"]).to_pandas()
        for item in manifest["curated_files"]
    }


def assert_prior_remains_active(paths, published, expected_hashes):
    assert DataRepository(paths).active_manifest()["data_snapshot_id"] == "fixture_first"
    assert canonical_hashes(paths, published) == expected_hashes
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT count(*) FROM ops.dataset_versions").fetchone() == (1,)
        for view in VIEW_NAMES.values():
            assert connection.execute(
                f"SELECT DISTINCT data_snapshot_id FROM {view}"
            ).fetchall() == [("fixture_first",)]


def test_fixture_builds_all_frozen_datasets_and_queryable_catalogue(paths, config, published):
    assert published["synthetic"] is True
    assert published["headline_news_enabled"] is False
    assert published["vix_context_lag_sessions"] == 1
    assert {item["dataset"] for item in published["curated_files"]} == set(VIEW_NAMES)
    assert len(published["curated_files"]) == 7
    assert len(published["tickers"]) == 65
    assert len(set(published["tickers"])) == 65
    assert not any(check["severity"] == "FAIL" for check in published["quality"])
    verify_snapshot(paths, published)
    frames = read_frozen(paths, published)
    security = frames["reference/security_master.parquet"]
    pairs = frames["reference/pair_universe.parquet"]
    prices = frames["curated/market/prices_daily.parquet"]
    context = frames["curated/market/market_context_daily.parquet"]
    filings = frames["curated/evidence/sec_filing_index.parquet"]
    assert len(security) == 56
    assert len(pairs) == 28
    assert pairs["pair_id"].tolist() == [pair.pair_id for pair in config.universe.pairs]
    assert set(prices["ticker"]) == set(published["tickers"])
    assert not prices.duplicated(["security_id", "trading_date"]).any()
    assert prices["quality_flag"].eq("OK").all()
    assert prices["adj_close"].gt(0).all()
    assert filings["point_in_time_eligible"].all()
    assert len(filings) == 112
    assert published["sec_timestamp_coverage"] == {"total": 112, "eligible": 112}
    for frame in frames.values():
        assert frame["data_snapshot_id"].eq("fixture_first").all()
        if frame is context:
            for prefix in ("spy", "sector", "vix"):
                for field in ("source_snapshot_id", "raw_file_path", "sha256"):
                    assert frame[f"{prefix}_{field}"].notna().all()
        else:
            for field in ("source_snapshot_id", "raw_file_path", "sha256"):
                assert frame[field].notna().all()
    for source in published["sources"]:
        raw_path = paths.workspace_root / source["raw_file_path"]
        assert raw_path.is_file()
        assert raw_path.with_name(raw_path.name + ".source.json").is_file()
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT status FROM ops.job_runs").fetchall() == [("SUCCESS",)]
        assert connection.execute("SELECT count(*) FROM ops.ingestion_runs").fetchone() == (
            len(published["sources"]),
        )
        for item in published["curated_files"]:
            assert connection.execute(
                f"SELECT count(*) FROM {VIEW_NAMES[item['dataset']]}"
            ).fetchone() == (item["rows"],)
    assert canonical_hashes(paths, published) == {
        item["dataset"]: item["sha256"] for item in published["curated_files"]
    }


def test_point_in_time_local_queries_and_conservative_vix(paths, published, monkeypatch):
    def forbidden_network(*args, **kwargs):
        pytest.fail("Historical queries must use frozen local data")

    monkeypatch.setattr(ingestion.HttpClient, "get", forbidden_network)
    repository = DataRepository(paths)
    prices = repository.pair_prices("KO__PEP", date(2021, 1, 4), date(2021, 1, 8))
    assert set(prices["ticker"]) == {"KO", "PEP"}
    assert len(prices) == 10
    assert prices["data_snapshot_id"].eq("fixture_first").all()
    acceptance = datetime(2021, 1, 5, 13, 30, tzinfo=UTC)
    assert repository.eligible_filings("US:ABBV", acceptance - timedelta(microseconds=1)).empty
    at_cutoff = repository.eligible_filings("US:ABBV", acceptance)
    assert at_cutoff["form"].tolist() == ["8-K"]
    assert at_cutoff["acceptance_datetime_utc"].iloc[0] == pd.Timestamp(acceptance)
    assert at_cutoff["acceptance_datetime_raw"].iloc[0] == "2021-01-05T13:30:00Z"
    assert at_cutoff["raw_file_path"].str.contains("history/").all()
    later = repository.eligible_filings("US:ABBV", datetime(2021, 2, 5, 21, 30, tzinfo=UTC))
    assert later["form"].tolist() == ["8-K", "10-Q"]
    with pytest.raises(ValueError, match="timezone"):
        repository.eligible_filings("US:ABBV", datetime(2021, 2, 6))
    with pytest.raises(ValueError, match="Unknown"):
        repository.pair_prices("PEP__KO", date(2021, 1, 4), date(2021, 1, 8))
    context = read_frozen(paths, published)["curated/market/market_context_daily.parquet"]
    first = context.loc[context["trading_date"].eq(date(2021, 1, 4))]
    assert len(first) == 8
    assert first["vix_observation_date"].eq(date(2020, 12, 31)).all()
    assert first["vix_close"].eq(20.53).all()
    assert not first["vix_close"].eq(20.54).any()
    assert (context["vix_observation_date"] < context["trading_date"]).all()
    assert (context["vix_observed_at_utc"] < context["data_available_at"]).all()


def test_replay_rebuilds_curated_inputs_without_source_access(
    paths, config, published, monkeypatch
):
    def forbidden_source(*args, **kwargs):
        pytest.fail("Replay must use immutable raw bytes rather than source adapters")

    monkeypatch.setattr(ingestion, "capture_sources", forbidden_source)
    monkeypatch.setattr(ingestion.HttpClient, "get", forbidden_source)
    original_frames = read_frozen(paths, published)
    frozen_bytes = {
        paths.workspace_root / item["path"]: (paths.workspace_root / item["path"]).read_bytes()
        for item in published["curated_files"]
    }
    # A replay must not depend on previous curated outputs or active-file aliases.
    for frozen_path in frozen_bytes:
        frozen_path.unlink()
    for item in published["curated_files"]:
        paths.data_path(item["dataset"]).unlink()
    replayed = ingest_data(
        paths,
        config,
        RuntimeSettings(),
        snapshot_id="fixture_replay",
        replay_id="fixture_first",
    )
    assert replayed["replayed_from"] == "fixture_first"
    assert replayed["sources"] == published["sources"]
    assert DataRepository(paths).active_manifest()["data_snapshot_id"] == "fixture_replay"
    replayed_frames = read_frozen(paths, replayed)
    for dataset, original in original_frames.items():
        regenerated = replayed_frames[dataset]
        assert regenerated["data_snapshot_id"].eq("fixture_replay").all()
        identity_columns = [column for column in original if column.endswith("data_snapshot_id")]
        pd.testing.assert_frame_equal(
            original.drop(columns=identity_columns), regenerated.drop(columns=identity_columns)
        )
    # Restore the original immutable outputs to verify both snapshot histories.
    for frozen_path, content in frozen_bytes.items():
        frozen_path.write_bytes(content)
    verify_snapshot(paths, published)
    verify_snapshot(paths, replayed)


def test_copied_workspace_replay_rebinds_views_to_new_host_paths(
    paths, config, published, tmp_path, monkeypatch
):
    copied_root = tmp_path / "portable-copy"
    shutil.copytree(paths.workspace_root, copied_root)
    copied = ProjectPaths.resolve(paths.project_root, copied_root)

    def forbidden_source(*args, **kwargs):
        pytest.fail("Portable restoration must use copied immutable source files")

    monkeypatch.setattr(ingestion, "capture_sources", forbidden_source)
    rebuilt = ingest_data(
        copied,
        config,
        RuntimeSettings(),
        snapshot_id="fixture_portable",
        replay_id="fixture_first",
    )
    assert rebuilt["sources"] == published["sources"]
    repository = DataRepository(copied)
    assert repository.active_manifest()["data_snapshot_id"] == "fixture_portable"
    queried = repository.pair_prices("KO__PEP", date(2021, 1, 4), date(2021, 1, 8))
    assert len(queried) == 10
    assert queried["data_snapshot_id"].eq("fixture_portable").all()
    with DuckDBConnectionFactory(copied.database).connect() as connection:
        definitions = connection.execute(
            "SELECT view_name,sql FROM duckdb_views() WHERE schema_name IN ('ref','market')"
        ).fetchall()
    assert len(definitions) == 7
    assert all(copied_root.as_posix() in sql for _, sql in definitions)
    assert all(paths.workspace_root.as_posix() not in sql for _, sql in definitions)
    assert DataRepository(paths).active_manifest()["data_snapshot_id"] == "fixture_first"


@pytest.mark.parametrize("zone", ["raw", "curated", "raw_manifest", "registered_manifest"])
def test_tampered_snapshot_is_rejected(paths, config, published, monkeypatch, zone):
    if zone == "raw":
        relative = published["sources"][0]["raw_file_path"]
    elif zone == "curated":
        relative = published["curated_files"][0]["path"]
    elif zone == "raw_manifest":
        relative = "data/snapshots/fixture_first/raw_manifest.json"
    else:
        relative = "data/snapshots/fixture_first/manifest.json"
    path = paths.workspace_root / relative
    original = path.read_bytes()
    path.write_bytes(original + b"checksum tamper")
    with pytest.raises(ValueError, match="checksum mismatch"):
        DataRepository(paths).active_manifest()
    with pytest.raises(ValueError, match="checksum mismatch"):
        DataRepository(paths).pair_prices("KO__PEP", date(2021, 1, 4), date(2021, 1, 8))
    with pytest.raises(ValueError, match="checksum mismatch"):
        DataRepository(paths).eligible_filings("US:ABBV", datetime(2021, 2, 6, tzinfo=UTC))
    if zone != "curated":
        with pytest.raises(ValueError, match="checksum mismatch"):
            ingest_data(
                paths,
                config,
                RuntimeSettings(),
                snapshot_id="fixture_tampered_replay",
                replay_id="fixture_first",
            )
    path.write_bytes(original)
    assert DataRepository(paths).active_manifest()["data_snapshot_id"] == "fixture_first"
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT count(*) FROM ops.dataset_versions").fetchone() == (1,)


def test_failed_catalogue_transaction_restores_all_prior_reader_inputs(
    paths, config, published, sources_fixture, monkeypatch
):
    previous_hashes = canonical_hashes(paths, published)
    original_publish = ingestion.publish_catalogue

    def fail_after_catalogue_writes(connection, publication_paths, manifest, run_id):
        original_publish(connection, publication_paths, manifest, run_id)
        raise RuntimeError("Injected failure after all catalogue writes")

    monkeypatch.setattr(ingestion, "publish_catalogue", fail_after_catalogue_writes)
    with pytest.raises(RuntimeError, match="Injected failure"):
        ingest_data(
            paths,
            config,
            RuntimeSettings(),
            snapshot_id="fixture_failed_publication",
            fixture=sources_fixture,
        )
    assert_prior_remains_active(paths, published, previous_hashes)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute(
            "SELECT status,error_type FROM ops.job_runs WHERE dataset_version=?",
            ["fixture_failed_publication"],
        ).fetchone() == ("FAILED", "RuntimeError")
        assert connection.execute(
            "SELECT DISTINCT data_snapshot_id FROM ops.ingestion_runs"
        ).fetchall() == [("fixture_first",)]
    assert not list(paths.data.rglob(".rollback-*"))
    assert not list(paths.data.rglob(".publish-*"))


def test_real_missing_equity_observation_fails_qa_without_filling_or_publishing(
    paths, config, published, sources_fixture, tmp_path
):
    previous_hashes = canonical_hashes(paths, published)
    broken_fixture = tmp_path / "missing-equity"
    shutil.copytree(sources_fixture, broken_fixture)
    market_path = broken_fixture / "market.csv"
    raw = pd.read_csv(market_path)
    absent = raw["ticker"].eq("KO") & raw["trading_date"].eq("2021-01-08")
    assert absent.sum() == 1
    raw.loc[~absent].to_csv(market_path, index=False)
    with pytest.raises(DataQualityError, match="QA failed"):
        ingest_data(
            paths,
            config,
            RuntimeSettings(),
            snapshot_id="fixture_missing_price",
            fixture=broken_fixture,
        )
    assert_prior_remains_active(paths, published, previous_hashes)
    findings = json.loads(
        paths.data_path("snapshots/fixture_missing_price/quality_failed.json").read_bytes()
    )
    assert any(check["severity"] == "FAIL" for check in findings)
    assert not paths.data_path("snapshots/fixture_missing_price/manifest.json").exists()
    raw_manifest = json.loads(
        paths.data_path("snapshots/fixture_missing_price/raw_manifest.json").read_bytes()
    )
    ko_source = next(
        item
        for item in raw_manifest["sources"]
        if item["role"] == "yahoo_prices" and item["identity"] == "KO"
    )
    ko = pq.read_table(paths.workspace_root / ko_source["raw_file_path"]).to_pandas()
    missing_day = ko.loc[pd.to_datetime(ko["trading_date"]).dt.date.eq(date(2021, 1, 8))]
    assert missing_day.empty or missing_day["adj_close"].isna().all()
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute(
            "SELECT status,error_type FROM ops.job_runs WHERE dataset_version=?",
            ["fixture_missing_price"],
        ).fetchone() == ("FAILED", "DataQualityError")
        assert (
            connection.execute(
                """SELECT count(*) FROM ops.data_quality_results
                WHERE data_snapshot_id=? AND severity='FAIL'""",
                ["fixture_missing_price"],
            ).fetchone()[0]
            > 0
        )

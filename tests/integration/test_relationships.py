"""Offline acceptance of real monthly estimation and transactional analytics writes."""

import json
from datetime import date

import pandas as pd
import pyarrow.parquet as pq
import pytest

from structural_break.econometrics.fixtures import fixture_inputs
from structural_break.services import relationships
from structural_break.services.relationships import (
    RelationshipsRepository,
    build_relationships,
)
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file

TABLES = ("relationship_snapshots", "pair_state_daily", "divergence_crossings")


@pytest.fixture
def relationship_build(paths, config):
    return build_relationships(paths, config, fixture=True, relationship_version="artificial_first")


def _query(paths, sql, params=None):
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        return connection.execute(sql, params or []).fetchdf()


def _count(paths, table, version):
    return int(
        _query(
            paths,
            f"SELECT count(*) AS n FROM analytics.{table} WHERE relationship_version=?",
            [version],
        )["n"].iloc[0]
    )


def test_artificial_inputs_are_deterministic_explicit_and_not_real_history():
    first = fixture_inputs()
    second = fixture_inputs()
    for left, right in zip(first[:2], second[:2], strict=True):
        pd.testing.assert_frame_equal(left, right)
    assert first[2:] == second[2:]
    prices, pairs, start, end, identity = first
    assert start == date(2014, 1, 2)
    assert end == date(2018, 12, 31)
    assert len(identity) == 64
    assert prices.groupby("ticker").size().min() >= 900
    assert prices["adj_close"].gt(0).all()
    assert prices["synthetic"].all() and pairs["synthetic"].all()
    assert prices["source_provider"].eq("SYNTHETIC_ACCEPTANCE_FIXTURE").all()
    assert prices["data_snapshot_id"].str.startswith("synthetic_p2_").all()
    assert not prices.duplicated(["ticker", "trading_date"]).any()
    assert prices["data_available_at"].dt.tz is not None
    assert pairs["pair_id"].tolist() == ["KO__PEP", "HD__LOW", "WMT__TGT"]
    assert (pairs["leg_a"] + "__" + pairs["leg_b"]).equals(pairs["pair_id"])


def test_production_job_publishes_all_analytics_and_frozen_lineage(
    paths, config, relationship_build
):
    manifest = relationship_build
    assert manifest["synthetic"] is True
    assert manifest["relationship_version"] == "artificial_first"
    assert manifest["counts"]["relationship_snapshots"] > 0
    assert manifest["counts"]["pair_state_daily"] > 0
    assert manifest["counts"]["divergence_crossings"] > 0
    assert not paths.data_path("curated/market/prices_daily.parquet").exists()
    assert len(manifest["files"]) == 3
    for item in manifest["files"]:
        assert sha256_file(paths.workspace_root / item["path"]) == item["sha256"]
    for table in TABLES:
        assert _count(paths, table, "artificial_first") == manifest["counts"][table]
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM analytics.relationship_versions"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT relationship_version FROM ops.active_relationship_version WHERE singleton"
        ).fetchone() == ("artificial_first",)
        assert connection.execute("SELECT status FROM ops.job_runs").fetchall() == [("SUCCESS",)]
        assert connection.execute("SELECT kind,version FROM ops.artifact_registry").fetchall() == [
            ("relationships", "artificial_first")
        ]
    snapshots = _query(
        paths,
        """SELECT pair_id,pair_status,n_obs,diagnostics
        FROM analytics.relationship_snapshots WHERE relationship_version=?""",
        ["artificial_first"],
    )
    assert set(snapshots["pair_id"]) == {"KO__PEP", "HD__LOW", "WMT__TGT"}
    assert snapshots["n_obs"].max() == config.econometrics.formation_days
    ko = snapshots.loc[snapshots["pair_id"].eq("KO__PEP") & snapshots["n_obs"].eq(504)]
    independent = snapshots.loc[snapshots["pair_id"].eq("HD__LOW") & snapshots["n_obs"].eq(504)]
    stationary = snapshots.loc[snapshots["pair_id"].eq("WMT__TGT")]
    assert ko["pair_status"].eq("ACTIVE").mean() > 0.70
    # Overlapping windows from one independent realization can contain clustered
    # false positives. This fixture must usually fail, rather than pass every window.
    assert independent["pair_status"].ne("ACTIVE").mean() > 0.50
    assert stationary["pair_status"].ne("ACTIVE").all()
    assert all(json.loads(value) for value in snapshots["diagnostics"])
    for encoded in snapshots["diagnostics"]:
        diagnostics = json.loads(encoded)
        assert diagnostics["source_price_snapshot_ids"]
        assert diagnostics["source_price_hashes"]
        if diagnostics["window_end"] is not None:
            assert diagnostics["window_end"] <= diagnostics["estimation_date"]
            assert pd.Timestamp(diagnostics["formation_price_available_at_max"]) <= pd.Timestamp(
                diagnostics["estimation_timestamp"]
            )
    crossings = _query(paths, "SELECT * FROM analytics.divergence_crossings")
    assert crossings["z_score"].abs().ge(config.econometrics.entry_z).all()
    assert crossings["direction"].isin([-1, 1]).all()
    assert crossings["baseline1_eligible"].any()
    assert (~crossings["baseline1_eligible"]).any()
    assert not any("label" in field or "outcome" in field for field in crossings.columns)


def test_persisted_daily_history_always_joins_latest_effective_estimate(paths, relationship_build):
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute(
            """SELECT count(*) FROM analytics.relationship_snapshots
            WHERE effective_start<=estimation_date"""
        ).fetchone() == (0,)
        assert connection.execute(
            """SELECT count(*) FROM analytics.pair_state_daily state
            JOIN analytics.relationship_snapshots snapshot
              ON state.relationship_version=snapshot.relationship_version
             AND state.relationship_snapshot_id=snapshot.relationship_snapshot_id
            WHERE snapshot.effective_start>state.trading_date
               OR snapshot.estimation_date>=state.trading_date
               OR snapshot.effective_start<>(
                 SELECT max(other.effective_start) FROM analytics.relationship_snapshots other
                 WHERE other.relationship_version=state.relationship_version
                   AND other.pair_id=state.pair_id
                   AND other.effective_start<=state.trading_date)"""
        ).fetchone() == (0,)
        assert connection.execute(
            """SELECT count(*) FROM analytics.divergence_crossings crossing
            JOIN analytics.pair_state_daily state
              ON state.relationship_version=crossing.relationship_version
             AND state.pair_id=crossing.pair_id AND state.trading_date=crossing.trading_date
            WHERE crossing.relationship_snapshot_id<>state.relationship_snapshot_id
               OR crossing.event_timestamp<>state.data_available_at
               OR crossing.baseline1_eligible<>(state.pair_status='ACTIVE')"""
        ).fetchone() == (0,)


def test_same_frozen_inputs_reproduce_ids_and_parameters_without_duplicate_rows(
    paths, config, relationship_build
):
    first_manifest = RelationshipsRepository(paths).active_manifest()
    repeated = build_relationships(
        paths, config, fixture=True, relationship_version="artificial_first"
    )
    assert repeated == first_manifest
    second = build_relationships(
        paths, config, fixture=True, relationship_version="artificial_second"
    )
    assert second["counts"] == relationship_build["counts"]
    assert RelationshipsRepository(paths).active_manifest()["relationship_version"] == (
        "artificial_second"
    )
    selections = {
        "relationship_snapshots": (
            "relationship_snapshot_id,pair_id,estimation_date,effective_start,effective_end,"
            "data_snapshot_id,config_hash,pair_status,n_obs,alpha,beta,spread_mean,spread_std"
        ),
        "pair_state_daily": (
            "pair_id,trading_date,relationship_snapshot_id,alpha,beta,spread,z_score,abs_z,"
            "spread_velocity_1d,z_velocity_1d,pair_status,data_available_at,data_snapshot_id"
        ),
        "divergence_crossings": (
            "crossing_id,pair_id,trading_date,event_timestamp,relationship_snapshot_id,"
            "direction,z_score,baseline1_eligible,data_snapshot_id"
        ),
    }
    for table, columns in selections.items():
        frames = [
            _query(
                paths,
                f"SELECT {columns} FROM analytics.{table} "
                "WHERE relationship_version=? ORDER BY 1,2",
                [version],
            )
            for version in ("artificial_first", "artificial_second")
        ]
        pd.testing.assert_frame_equal(*frames, check_exact=True)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT count(*) FROM ops.job_runs").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM analytics.relationship_versions"
        ).fetchone() == (2,)


def test_computation_change_requires_new_publication_identity(
    paths, config, relationship_build, monkeypatch
):
    from structural_break.econometrics import engine

    original_computation = relationship_build["computation_identity"]
    cached_frames = {
        item["dataset"]: pq.read_table(paths.workspace_root / item["path"]).to_pandas()
        for item in relationship_build["files"]
    }
    computations = []

    def reuse_estimation(*args, **kwargs):
        computations.append(kwargs)
        outputs = []
        for name in TABLES:
            frame = cached_frames[name].copy(deep=True)
            frame["created_at_utc"] = kwargs["created_at"]
            outputs.append(frame)
        return tuple(outputs)

    # Estimation is separately exercised above; this regression isolates the
    # real manifest/registry/persistence identity rule using those frozen results.
    monkeypatch.setattr(engine, "build_relationship_history", reuse_estimation)
    monkeypatch.setattr(relationships, "computation_identity", lambda: original_computation)
    original_default = build_relationships(paths, config, fixture=True)
    repeated = build_relationships(paths, config, fixture=True)
    assert repeated == original_default
    assert len(computations) == 1
    assert original_default["computation_identity"] == original_computation
    changed_computation = {**original_computation, "regression_revision": "changed"}
    monkeypatch.setattr(relationships, "computation_identity", lambda: changed_computation)
    with pytest.raises(ValueError, match="different|computation"):
        build_relationships(
            paths,
            config,
            fixture=True,
            relationship_version=relationship_build["relationship_version"],
        )
    assert len(computations) == 1
    assert RelationshipsRepository(paths).active_manifest() == original_default
    changed_default = build_relationships(paths, config, fixture=True)
    assert changed_default["relationship_version"] != original_default["relationship_version"]
    assert changed_default["computation_identity"] == changed_computation
    assert changed_default["counts"] == relationship_build["counts"]
    assert len(computations) == 2
    assert RelationshipsRepository(paths).active_manifest() == changed_default
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM analytics.relationship_versions"
        ).fetchone() == (3,)
        assert connection.execute("SELECT status FROM ops.job_runs").fetchall() == [
            ("SUCCESS",),
            ("SUCCESS",),
            ("SUCCESS",),
        ]


def test_failed_publication_rolls_back_tables_registry_and_active_reader_version(
    paths, config, relationship_build, monkeypatch
):
    original_publish = relationships.publish_relationships

    def fail_after_real_publication(*args, **kwargs):
        original_publish(*args, **kwargs)
        raise RuntimeError("Injected failure after analytics and version writes")

    monkeypatch.setattr(relationships, "publish_relationships", fail_after_real_publication)
    with pytest.raises(RuntimeError, match="Injected failure"):
        build_relationships(paths, config, fixture=True, relationship_version="artificial_failed")
    assert RelationshipsRepository(paths).active_manifest()["relationship_version"] == (
        "artificial_first"
    )
    for table in TABLES:
        assert _count(paths, table, "artificial_first") == relationship_build["counts"][table]
        assert _count(paths, table, "artificial_failed") == 0
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM analytics.relationship_versions"
        ).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM ops.artifact_registry").fetchone() == (1,)
        assert connection.execute(
            "SELECT status,error_type FROM ops.job_runs WHERE status='FAILED'",
        ).fetchone() == ("FAILED", "RuntimeError")
    # An aborted publication must not leave its immutable destination unusable.
    monkeypatch.setattr(relationships, "publish_relationships", original_publish)
    recovered = build_relationships(
        paths, config, fixture=True, relationship_version="artificial_failed"
    )
    assert recovered["counts"] == relationship_build["counts"]
    assert RelationshipsRepository(paths).active_manifest()["relationship_version"] == (
        "artificial_failed"
    )


def test_historical_relationship_reader_is_local_and_rejects_unknown_pair(
    paths, relationship_build, monkeypatch
):
    def forbidden_build(*args, **kwargs):
        pytest.fail("Historical queries must not run a canonical batch job")

    monkeypatch.setattr(relationships, "build_relationships", forbidden_build)
    reader = RelationshipsRepository(paths)
    states = reader.pair_states("KO__PEP", date(2017, 1, 3), date(2017, 2, 28))
    assert len(states) > 0
    assert states["pair_id"].eq("KO__PEP").all()
    snapshot_frame = reader.snapshot_for_session("KO__PEP", date(2017, 1, 3))
    assert len(snapshot_frame) == 1
    snapshot = snapshot_frame.iloc[0]
    assert str(snapshot["estimation_date"])[:10] < "2017-01-03"
    assert states["relationship_snapshot_id"].iloc[0] == snapshot["relationship_snapshot_id"]
    eligible = reader.crossings("KO__PEP", eligible_only=True)
    assert eligible["baseline1_eligible"].all()
    assert set(eligible["crossing_id"]) <= set(reader.crossings("KO__PEP")["crossing_id"])
    with pytest.raises(ValueError, match="Unknown"):
        reader.pair_states("PEP__KO", date(2017, 1, 3), date(2017, 2, 28))
    with pytest.raises(ValueError):
        reader.pair_states("KO__PEP", date(2017, 2, 28), date(2017, 1, 3))


def test_publication_validator_rejects_crossings_with_mismatched_historical_state(
    paths, relationship_build
):
    frames = {
        item["dataset"]: pq.read_table(paths.workspace_root / item["path"]).to_pandas()
        for item in relationship_build["files"]
    }
    relationships.validate_relationships(frames)
    crossings = frames["divergence_crossings"]
    assert len(crossings) > 0
    first_index = crossings.index[0]
    active_index = crossings.loc[crossings["baseline1_eligible"]].index[0]
    for field, index, incorrect in (
        (
            "event_timestamp",
            first_index,
            crossings.loc[first_index, "event_timestamp"] + pd.Timedelta("1us"),
        ),
        (
            "relationship_snapshot_id",
            first_index,
            frames["relationship_snapshots"].iloc[0]["relationship_snapshot_id"],
        ),
        ("fresh_threshold_crossing", first_index, False),
        ("baseline1_eligible", active_index, False),
    ):
        corrupted = {name: frame.copy(deep=True) for name, frame in frames.items()}
        corrupted["divergence_crossings"].loc[index, field] = incorrect
        with pytest.raises(ValueError):
            relationships.validate_relationships(corrupted)


@pytest.mark.parametrize("target", ["manifest", "output"])
def test_frozen_relationship_hash_tampering_blocks_readers(paths, relationship_build, target):
    reader = RelationshipsRepository(paths)
    if target == "output":
        relative = relationship_build["files"][0]["path"]
    else:
        with DuckDBConnectionFactory(paths.database).connect() as connection:
            relative = connection.execute(
                "SELECT manifest_path FROM analytics.relationship_versions"
            ).fetchone()[0]
    path = paths.workspace_root / relative
    original_bytes = path.read_bytes()
    path.write_bytes(original_bytes + b"corrupt immutable artifact")
    try:
        with pytest.raises(ValueError, match="checksum|hash"):
            reader.active_manifest()
        with pytest.raises(ValueError, match="checksum|hash"):
            reader.pair_states("KO__PEP", date(2017, 1, 3), date(2017, 2, 28))
    finally:
        path.write_bytes(original_bytes)
    assert reader.active_manifest()["relationship_version"] == "artificial_first"

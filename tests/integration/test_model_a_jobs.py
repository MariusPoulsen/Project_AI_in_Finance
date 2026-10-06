"""The actual offline P2 -> event dataset -> thirty-trial Model A job path."""

import shutil
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from structural_break.config.loader import load_config
from structural_break.config.paths import ProjectPaths
from structural_break.ml.fixtures import fixture_inputs
from structural_break.services import model_a
from structural_break.services.model_a import (
    ModelARepository,
    build_events,
    merge_event_rows,
    train_model_a_job,
)
from structural_break.services.relationships import RelationshipsRepository
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "configs")
    paths = ProjectPaths.resolve(root, tmp_path_factory.mktemp("p3_jobs") / "workspace")
    events = build_events(paths, config, fixture=True, event_version="acceptance_events")
    model = train_model_a_job(paths, config, model_version="acceptance_model_a")
    return paths, config, events, model


@pytest.fixture
def copied(published, tmp_path):
    original, config, events, model = published
    destination = tmp_path / "workspace"
    shutil.copytree(original.workspace_root, destination)
    return ProjectPaths.resolve(original.project_root, destination), config, events, model


def query(paths, sql, parameters=None):
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        return connection.execute(sql, parameters or []).fetchdf()


def test_synthetic_fixture_reproducible_explicit_and_full_history():
    first, second = fixture_inputs(), fixture_inputs()
    for left, right in zip(first[:4], second[:4], strict=True):
        pd.testing.assert_frame_equal(left, right)
    assert first[4] == second[4]
    prices, pairs, securities, context, identity = first
    assert identity.startswith("synthetic_p3_")
    assert prices["synthetic"].all() and context["synthetic"].all()
    assert prices["source_provider"].eq("SYNTHETIC").all()
    assert prices["trading_date"].min() == date(2014, 1, 2)
    assert prices["trading_date"].max() == date(2025, 12, 31)
    assert len(pairs) == 3 and len(securities) == 6
    assert prices["data_snapshot_id"].eq(identity).all()
    assert context["data_snapshot_id"].eq(identity).all()


def test_actual_jobs_publish_integrity_counts_and_final_lock(copied):
    paths, config, events, model = copied
    repository = ModelARepository(paths)
    assert repository.dataset_manifest() == events
    assert repository.active_manifest() == model
    assert events["synthetic"] and model["synthetic"]
    for manifest in (events, model):
        for item in manifest["files"]:
            assert sha256_file(paths.workspace_root / item["path"]) == item["sha256"]
    for name, count in events["counts"].items():
        assert len(query(paths, f"SELECT event_id FROM analytics.{name}")) == count
    assert events["partition_counts"]["train"]["supervised_eligible"] > 50
    assert events["partition_counts"]["validation"]["supervised_eligible"] > 10
    assert events["partition_counts"]["final_test"]["positives"] is None
    assert model["model_manifest"]["final_test_locked"]
    assert repository.load_bundle().metadata["search_trials"] == config.ml.search_trials
    assert model["metrics"]["final_test"] == {"status": "LOCKED", "outcomes_inspected": False}
    frames = repository.dataset_frames()
    joined = merge_event_rows(frames)
    stored = repository.predictions()
    excluded = joined.loc[
        joined["model_ready"]
        & joined["partition"].isin(["train", "validation"])
        & ~joined["supervised_eligible"],
        "event_id",
    ]
    assert len(excluded) > 0
    assert (
        stored.loc[stored["event_id"].isin(excluded), "evaluation_role"]
        .eq("EXCLUDED_FROM_SUPERVISION")
        .all()
    )
    final = joined.loc[joined["partition"].eq("final_test")]
    assert len(final) > 0
    assert final["outcome_type"].eq("LOCKED").all()
    assert final["y_revert_success"].isna().all()
    assert not final["supervised_eligible"].any()
    assert final["resolution_date"].isna().all()
    for partition, boundary in (
        ("train", config.ml.train.end),
        ("validation", config.ml.validation.end),
    ):
        eligible = joined.loc[joined["partition"].eq(partition) & joined["supervised_eligible"]]
        assert pd.to_datetime(eligible["horizon_end_date"]).dt.date.le(boundary).all()
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT status FROM ops.job_runs").fetchall() == [
            ("SUCCESS",),
            ("SUCCESS",),
        ]
        assert connection.execute(
            "SELECT count(*) FROM analytics.relationship_versions"
        ).fetchone() == (1,)


def test_saved_bundle_reload_reproduces_probabilities_without_jobs(copied, monkeypatch):
    paths, _, _, model = copied

    def forbidden_job(*args, **kwargs):
        pytest.fail("Read-only historical browsing must not start a scientific batch")

    monkeypatch.setattr(model_a, "build_events", forbidden_job)
    monkeypatch.setattr(model_a, "train_model_a_job", forbidden_job)
    repository = ModelARepository(paths)
    stored = repository.predictions()
    assert len(stored) == model["counts"]["predictions"]
    ordered = stored.merge(repository.features(), on="event_id", validate="one_to_one")
    matrix = ordered[model["feature_schema"]["feature_columns"]]
    predictions = repository.load_bundle().predict(matrix)
    np.testing.assert_allclose(
        predictions["raw_probability"], stored["raw_probability"], rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(
        predictions["calibrated_probability"], stored["calibrated_probability"], rtol=0, atol=1e-12
    )
    local = repository.events("KO__PEP", date(2016, 1, 1), date(2023, 12, 31))
    assert len(local) > 0 and local["pair_id"].eq("KO__PEP").all()
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT count(*) FROM ops.job_runs").fetchone() == (2,)


def test_registered_event_and_model_jobs_are_idempotent(copied):
    paths, config, events, model = copied
    assert (
        build_events(paths, config, fixture=True, event_version=events["dataset_version"]) == events
    )
    assert train_model_a_job(paths, config, model_version=model["model_version"]) == model
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT count(*) FROM ops.job_runs").fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM analytics.event_dataset_versions"
        ).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM analytics.model_versions").fetchone() == (
            1,
        )


@pytest.mark.parametrize("kind", ["event", "model", "upstream_relationship"])
def test_readers_reject_tampered_artifacts_and_upstream_lineage(copied, kind):
    paths, _, events, model = copied
    if kind == "event":
        target = paths.workspace_root / events["files"][0]["path"]
    elif kind == "model":
        target = paths.workspace_root / next(
            item["path"] for item in model["files"] if item["dataset"] == "xgb_model"
        )
    else:
        upstream = RelationshipsRepository(paths).active_manifest()
        target = paths.workspace_root / upstream["files"][0]["path"]
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        ModelARepository(paths).active_manifest()


def test_sql_foreign_keys_reject_orphan_feature_and_prediction(copied):
    paths, _, events, model = copied
    with DuckDBConnectionFactory(paths.database).connect(read_only=False) as connection:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO analytics.event_features VALUES (?,?,?,?,?,?)",
                [
                    events["dataset_version"],
                    "orphan",
                    "quantitative-v1",
                    "2020-01-02T21:00:00Z",
                    True,
                    "{}",
                ],
            )
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO analytics.model_predictions VALUES (?,?,?,?,?,?,?,?)",
                [
                    model["model_version"],
                    events["dataset_version"],
                    "orphan",
                    "KO__PEP",
                    "2020-01-02T21:00:00Z",
                    0.5,
                    0.5,
                    "{}",
                ],
            )


@pytest.mark.parametrize(
    "malformation",
    [
        "cutoff",
        "source",
        "snapshot",
        "label",
        "supervised",
        "final_outcome",
    ],
)
def test_publication_validator_rejects_malformed_leakage_and_metadata(copied, malformation):
    paths, _, _, _ = copied
    frames = ModelARepository(paths).dataset_frames()
    if malformation == "cutoff":
        frames["event_features"].loc[0, "feature_cutoff_timestamp"] += pd.Timedelta(days=1)
    elif malformation == "source":
        frames["event_features"].loc[0, "data_snapshot_id"] = "other-source"
    elif malformation == "snapshot":
        frames["event_features"].loc[0, "relationship_snapshot_id"] = "other-snapshot"
    elif malformation == "label":
        index = frames["event_targets"].index[frames["event_targets"]["label_eligible"]][0]
        frames["event_targets"].loc[index, "label_eligible"] = False
    elif malformation == "supervised":
        index = frames["event_partitions"].index[frames["event_partitions"]["supervised_eligible"]][
            0
        ]
        frames["event_partitions"].loc[index, "supervised_eligible"] = False
    else:
        index = frames["divergence_events"].index[
            frames["divergence_events"]["partition"].eq("final_test")
        ][0]
        frames["event_targets"].loc[index, "resolution_date"] = date(2024, 1, 4)
    with pytest.raises(ValueError):
        model_a.validate_event_frames(frames)


def test_event_publication_failure_rolls_back_and_retries_same_identity(copied, monkeypatch):
    paths, config, events, model = copied
    original = model_a.publish_events

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected event publication failure")

    monkeypatch.setattr(model_a, "publish_events", fail_after_write)
    with pytest.raises(RuntimeError, match="Injected event"):
        build_events(paths, config, fixture=True, event_version="acceptance_failed_events")
    repository = ModelARepository(paths)
    assert repository.dataset_manifest() == events
    assert repository.active_manifest() == model
    assert query(paths, "SELECT count(*) n FROM analytics.event_dataset_versions")["n"].iloc[0] == 1
    assert (
        query(
            paths,
            "SELECT count(*) n FROM analytics.divergence_events WHERE dataset_version=?",
            ["acceptance_failed_events"],
        )["n"].iloc[0]
        == 0
    )
    assert query(paths, "SELECT status,error_type FROM ops.job_runs WHERE status='FAILED'").iloc[
        0
    ].tolist() == ["FAILED", "RuntimeError"]
    monkeypatch.setattr(model_a, "publish_events", original)
    recovered = build_events(paths, config, fixture=True, event_version="acceptance_failed_events")
    assert recovered["counts"] == events["counts"]
    assert repository.dataset_manifest() == recovered
    assert repository.active_manifest() == model
    assert repository.features()["dataset_version"].eq(model["dataset_version"]).all()
    original_frames = repository.dataset_frames(events["dataset_version"])
    recovered_frames = repository.dataset_frames(recovered["dataset_version"])
    assert original_frames["divergence_events"]["event_id"].equals(
        recovered_frames["divergence_events"]["event_id"]
    )
    pd.testing.assert_frame_equal(
        original_frames["event_targets"].drop(columns="dataset_version"),
        recovered_frames["event_targets"].drop(columns="dataset_version"),
    )
    archived = list((paths.artifacts / "events").glob("acceptance_failed_events.unregistered-*"))
    assert len(archived) == 1


def test_model_publication_failure_keeps_previous_model_and_failed_run(copied, monkeypatch):
    paths, config, events, model = copied
    original = model_a.publish_model

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected model publication failure")

    monkeypatch.setattr(model_a, "publish_model", fail_after_write)
    with pytest.raises(RuntimeError, match="Injected model"):
        train_model_a_job(paths, config, model_version="acceptance_failed_model")
    repository = ModelARepository(paths)
    assert repository.active_manifest() == model
    assert repository.dataset_manifest() == events
    assert query(paths, "SELECT count(*) n FROM analytics.model_versions")["n"].iloc[0] == 1
    assert (
        query(
            paths,
            "SELECT count(*) n FROM analytics.model_predictions WHERE model_version=?",
            ["acceptance_failed_model"],
        )["n"].iloc[0]
        == 0
    )
    assert query(paths, "SELECT status,error_type FROM ops.job_runs WHERE status='FAILED'").iloc[
        0
    ].tolist() == ["FAILED", "RuntimeError"]

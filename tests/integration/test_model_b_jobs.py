"""Actual cached extraction -> Model B -> paired comparison, with no network."""

import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from structural_break.config.loader import load_config
from structural_break.config.paths import ProjectPaths
from structural_break.services import model_b
from structural_break.services.model_a import ModelARepository, build_events, train_model_a_job
from structural_break.services.model_b import (
    ModelBRepository,
    merge_model_b_rows,
    train_model_b,
    verify_model_b,
)
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    from structural_break.services.intelligence import build_event_intelligence

    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "configs")
    config = config.model_copy(update={"ml": config.ml.model_copy(update={"search_trials": 2})})
    paths = ProjectPaths.resolve(root, tmp_path_factory.mktemp("p4_model_jobs") / "workspace")
    events = build_events(paths, config, fixture=True, event_version="p4_model_events")
    model_a = train_model_a_job(paths, config, model_version="p4_baseline_a")
    evidence = build_event_intelligence(
        paths,
        config,
        dataset_version=events["dataset_version"],
        event_feature_version="p4_model_evidence",
        fixture=True,
    )
    model = train_model_b(paths, config, model_version="p4_model_b")
    return paths, config, events, model_a, evidence, model


@pytest.fixture
def copied(published, tmp_path):
    original, *rest = published
    destination = tmp_path / "workspace"
    shutil.copytree(original.workspace_root, destination)
    return ProjectPaths.resolve(original.project_root, destination), *rest


def query(paths, sql, parameters=None):
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        return connection.execute(sql, parameters or []).fetchdf()


def test_model_b_publishes_unchanged_cohort_and_independent_model_a(copied):
    paths, config, events, model_a, evidence, model = copied
    from structural_break.services.intelligence import EvidenceRepository

    repository = ModelBRepository(paths)
    assert repository.active_manifest() == model
    assert ModelARepository(paths).active_manifest() == model_a
    assert ModelARepository(paths).dataset_manifest() == events
    assert EvidenceRepository(paths).manifest() == evidence
    assert model["model_a_version"] == model_a["model_version"]
    assert model["event_feature_version"] == evidence["event_feature_version"]
    assert set(repository.features()["event_id"]) == set(
        ModelARepository(paths).features()["event_id"]
    )
    assert set(repository.predictions()["event_id"]) == set(
        ModelARepository(paths).predictions()["event_id"]
    )
    assert (
        len(query(paths, "SELECT event_id FROM analytics.model_b_predictions"))
        == model["counts"]["predictions"]
    )
    assert repository.load_bundle().metadata["search_trials"] == 2
    for item in model["files"]:
        assert sha256_file(paths.workspace_root / item["path"]) == item["sha256"]
    comparison = repository.comparison()
    expected_count = events["partition_counts"]["validation"]["supervised_eligible"]
    assert comparison["validation_supervised_eligible"] == expected_count
    assert (
        comparison["paired_subsets"]["all_eligible_validation"]["B"]["raw"]["n"] == expected_count
    )
    assert comparison["paired_subsets"]["UNKNOWN"]["B"]["raw"]["n"] > 0
    assert (
        sum(
            comparison["paired_subsets"][name]["B"]["raw"]["n"]
            for name in ("UNKNOWN", "NONE", "supported_catalyst")
        )
        == expected_count
    )
    assert comparison["final_test"] == {"status": "LOCKED", "outcomes_inspected": False}
    final = repository.predictions().query("partition == 'final_test'")
    assert len(final) > 0
    assert final["evaluation_role"].eq("LOCKED_FEATURE_ONLY_INFERENCE").all()


def test_reloaded_model_b_reproduces_probabilities_and_raw_margin_shap(copied):
    paths, config, events, model_a, evidence, model = copied
    report = verify_model_b(paths)
    assert report["prediction_count"] == model["counts"]["predictions"]
    assert max(report["reload_max_errors"].values()) == 0
    assert report["shap_raw_margin_max_error"] < 2e-5
    assert report["paired_comparison_reproduced"]
    assert report["final_test_outcomes_inspected"] is False
    stored = ModelBRepository(paths).predictions()
    assert all(
        len(values) == len(model["feature_schema"]["feature_columns"])
        for values in stored["shap_values"]
    )
    assert stored["explanation_status"].eq("AVAILABLE_RAW_MARGIN").all()


def test_registered_rebuild_uses_cached_features_without_an_llm(copied, monkeypatch):
    paths, config, events, model_a, evidence, model = copied
    from structural_break.services import intelligence
    from structural_break.services.intelligence import EvidenceRepository

    def forbid_extraction(*args, **kwargs):
        pytest.fail("Model B rebuild must not call extraction or evidence jobs")

    monkeypatch.setattr(intelligence, "build_event_intelligence", forbid_extraction)

    count = len(query(paths, "SELECT run_id FROM ops.job_runs"))
    assert train_model_b(paths, config, model_version=model["model_version"]) == model
    assert len(query(paths, "SELECT run_id FROM ops.job_runs")) == count
    # Reading a trained model needs only the verified evidence generation, not providers.
    before = sha256_file(paths.database)
    frame = ModelBRepository(paths).features()
    assert len(frame) == evidence["counts"]["model_b_features"]
    assert EvidenceRepository(paths).manifest() == evidence
    assert sha256_file(paths.database) == before
    assert len(query(paths, "SELECT model_version FROM analytics.model_b_versions")) == 1


@pytest.mark.parametrize("kind", ["native_model", "comparison", "evidence", "model_a"])
def test_model_b_reader_rejects_tampered_model_and_parents(copied, kind):
    paths, config, events, model_a, evidence, model = copied
    if kind == "native_model":
        item = next(entry for entry in model["files"] if entry["dataset"] == "xgb_model")
    elif kind == "comparison":
        item = next(entry for entry in model["files"] if entry["dataset"] == "model_a_b_comparison")
    elif kind == "evidence":
        item = evidence["files"][0]
    else:
        item = next(entry for entry in model_a["files"] if entry["dataset"] == "xgb_model")
    path = paths.workspace_root / item["path"]
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        ModelBRepository(paths).active_manifest()


@pytest.mark.parametrize("malformation", ["drop", "duplicate", "quantitative", "cutoff"])
def test_model_b_rejects_evidence_selection_bias_and_quantitative_mutation(copied, malformation):
    paths, config, events, model_a, evidence, model = copied
    from structural_break.services.intelligence import EvidenceRepository

    frames = ModelARepository(paths).dataset_frames(events["dataset_version"])
    features = EvidenceRepository(paths).frames()["model_b_features"]
    if malformation == "drop":
        features = features.iloc[1:]
    elif malformation == "duplicate":
        features = pd.concat([features, features.iloc[:1]], ignore_index=True)
    elif malformation == "quantitative":
        features.loc[0, "abs_z"] += 0.1
    else:
        features["event_feature_cutoff_timestamp"] = features["event_timestamp"] + pd.Timedelta(
            days=1
        )
    with pytest.raises(ValueError):
        merge_model_b_rows(frames, features, model["feature_schema"])


def test_failed_model_b_publication_rolls_back_and_retry_preserves_parent_models(
    copied, monkeypatch
):
    paths, config, events, model_a, evidence, model = copied
    original = model_b.publish_model_b

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected Model B publication failure")

    monkeypatch.setattr(model_b, "publish_model_b", fail_after_write)
    with pytest.raises(RuntimeError, match="Injected Model B"):
        train_model_b(paths, config, model_version="failed_model_b")
    assert ModelBRepository(paths).active_manifest() == model
    assert ModelARepository(paths).active_manifest() == model_a
    assert len(query(paths, "SELECT model_version FROM analytics.model_b_versions")) == 1
    assert (
        len(
            query(
                paths,
                "SELECT event_id FROM analytics.model_b_predictions "
                "WHERE model_version='failed_model_b'",
            )
        )
        == 0
    )
    assert query(paths, "SELECT status,error_type FROM ops.job_runs WHERE status='FAILED'").iloc[
        0
    ].tolist() == ["FAILED", "RuntimeError"]
    monkeypatch.setattr(model_b, "publish_model_b", original)
    restored = train_model_b(paths, config, model_version="failed_model_b")
    assert ModelBRepository(paths).active_manifest() == restored
    assert ModelARepository(paths).active_manifest() == model_a
    assert (
        restored["comparison"]["validation_supervised_eligible"]
        == model["comparison"]["validation_supervised_eligible"]
    )
    assert len(list((paths.artifacts / "models").glob("failed_model_b.unregistered-*"))) == 1


def test_sql_rejects_orphan_model_b_prediction(copied):
    paths, config, events, model_a, evidence, model = copied
    with DuckDBConnectionFactory(paths.database).connect(read_only=False) as connection:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO analytics.model_b_predictions VALUES (?,?,?,?,?,?,?,?)",
                [
                    model["model_version"],
                    events["dataset_version"],
                    "orphan",
                    "KO__PEP",
                    "2020-01-02T21:00:00Z",
                    0.1,
                    0.1,
                    "{}",
                ],
            )


@pytest.mark.parametrize("attempted_variant", ["A", "B"])
def test_registered_model_namespace_collision_preserves_both_variants(copied, attempted_variant):
    paths, config, events, model_a, evidence, model = copied
    count = len(query(paths, "SELECT run_id FROM ops.job_runs"))
    with pytest.raises(ValueError, match="registered artifact"):
        if attempted_variant == "A":
            train_model_a_job(paths, config, model_version=model["model_version"])
        else:
            train_model_b(paths, config, model_version=model_a["model_version"])
    assert len(query(paths, "SELECT run_id FROM ops.job_runs")) == count
    assert ModelARepository(paths).active_manifest() == model_a
    assert ModelBRepository(paths).active_manifest() == model
    for manifest in (model_a, model):
        for item in manifest["files"]:
            assert sha256_file(paths.workspace_root / item["path"]) == item["sha256"]


def test_read_queries_use_model_bound_evidence_after_new_active_generation(copied):
    paths, config, events, model_a, evidence, model = copied
    from structural_break.services.intelligence import build_event_intelligence

    original = ModelBRepository(paths).features()
    newer = build_event_intelligence(
        paths,
        config,
        dataset_version=events["dataset_version"],
        event_feature_version="newer_p4_features",
        fixture=True,
    )
    assert newer["event_feature_version"] != evidence["event_feature_version"]
    bound = ModelBRepository(paths).features()
    pd.testing.assert_frame_equal(bound, original)
    assert ModelBRepository(paths).active_manifest() == model

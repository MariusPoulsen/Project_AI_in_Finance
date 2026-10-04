"""Model B shares Model A's chronology and compares every eligible event."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from structural_break.config.loader import load_config
from structural_break.ml.model import (
    ModelTrainingError,
    load_bundle,
    train_chronological_model,
)
from structural_break.services.model_b import compare_model_a_b, model_b_feature_schema


def inputs():
    generator = np.random.default_rng(3227)
    records = []
    for year in range(2016, 2026):
        for month in range(1, 7):
            success = month % 2
            unknown = month % 3 == 0
            records.append(
                {
                    "event_id": f"synthetic_b_{year}_{month}",
                    "event_timestamp": pd.Timestamp(year=year, month=month, day=5, tz="UTC"),
                    "horizon_end_date": pd.Timestamp(year=year, month=month, day=20),
                    "partition": "train"
                    if year < 2022
                    else "validation"
                    if year < 2024
                    else "final_test",
                    "supervised_eligible": year < 2024,
                    "y_revert_success": success if year < 2024 else None,
                    "signal": generator.normal(),
                    "event_type_UNKNOWN": int(unknown),
                    "event_type_NONE": int(not unknown and not success),
                    "evidence_available": int(not unknown),
                    "extraction_confidence": np.nan if unknown else 0.9,
                    "supported_event": int(success and not unknown),
                }
            )
    columns = [
        {"name": "signal", "family": "spread", "allow_missing": False},
        *[
            {"name": name, "family": "event", "binary": True, "allow_missing": False}
            for name in (
                "event_type_UNKNOWN",
                "event_type_NONE",
                "evidence_available",
                "supported_event",
            )
        ],
        {"name": "extraction_confidence", "family": "event", "allow_missing": True},
    ]
    schema = {
        "version": "synthetic-model-b-v1",
        "columns": columns,
        "feature_columns": [item["name"] for item in columns],
    }
    settings = load_config(Path(__file__).resolve().parents[2] / "configs").ml.model_copy(
        update={"search_trials": 2}
    )
    return pd.DataFrame(records), schema, settings


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    rows, schema, settings = inputs()
    root = tmp_path_factory.mktemp("model_b_math")
    result = train_chronological_model(
        rows,
        schema,
        settings,
        root / "bundle",
        model_version="synthetic_b",
        dataset_version="synthetic_b_events",
        tracking_directory=root / "mlflow",
        expected_feature_schema_version=schema["version"],
        model_variant="B",
    )
    return result, root / "bundle", rows, schema, settings


def test_model_b_schema_preserves_order_and_explicit_unknown_missingness():
    from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
    from structural_break.ml.features import feature_schema

    model_a = feature_schema("quantitative-v1")
    before = json.dumps(model_a, sort_keys=True)
    model_b = model_b_feature_schema(model_a)
    assert model_b["feature_columns"] == model_a["feature_columns"] + list(EVENT_FEATURE_NAMES)
    assert model_b["columns"][:36] == model_a["columns"]
    assert json.dumps(model_a, sort_keys=True) == before
    assert model_b == model_b_feature_schema(model_a)
    definitions = {item["name"]: item for item in model_b["columns"]}
    assert definitions["event_type_UNKNOWN"]["binary"]
    assert not definitions["event_type_NONE"]["allow_missing"]
    assert definitions["extraction_confidence"]["allow_missing"]
    assert model_b["version"] != model_a["version"]


def test_fitted_model_b_uses_same_splits_policy_and_no_final_targets(fitted):
    result, directory, rows, schema, settings = fitted
    assert result.bundle.metadata["n_training"] == 36
    assert result.bundle.metadata["n_calibration"] == 12
    assert result.bundle.policy["candidate_threshold"] == settings.candidate_threshold
    assert result.metrics["final_test"] == {"status": "LOCKED", "outcomes_inspected": False}
    assert len(result.predictions) == 48
    assert set(result.predictions["event_id"]) == set(
        rows.loc[rows["supervised_eligible"], "event_id"]
    )
    assert "B_full" in result.metrics["raw_validation_feature_ablations"]
    assert "A2_same_B_hyperparameters" in result.metrics["raw_validation_feature_ablations"]
    assert "Model B" in json.loads((directory / "model_card.json").read_text())["family"]
    assert result.bundle.schema == schema


def test_model_b_reload_and_unknown_rows_have_valid_shap(fitted):
    result, directory, rows, schema, settings = fitted
    matrix = rows.loc[rows["partition"].eq("validation"), schema["feature_columns"]]
    before = result.bundle.predict(matrix)
    after = load_bundle(directory).predict(matrix)
    np.testing.assert_array_equal(after["raw_probability"], before["raw_probability"])
    np.testing.assert_array_equal(after["calibrated_probability"], before["calibrated_probability"])
    assert matrix["event_type_UNKNOWN"].sum() == 4
    assert len(after) == len(matrix)
    np.testing.assert_allclose(
        np.asarray(after["shap_values"].tolist()).sum(axis=1) + after["shap_base_value"],
        after["raw_margin"],
        atol=2e-5,
    )


def test_model_b_comparison_preserves_unknown_none_and_supported_events(fitted):
    result, directory, rows, schema, settings = fitted
    comparison = compare_model_a_b(rows, result.predictions, result.predictions, threshold=0.65)
    assert comparison["validation_supervised_eligible"] == 12
    subsets = comparison["paired_subsets"]
    assert subsets["all_eligible_validation"]["A"]["raw"]["n"] == 12
    assert subsets["UNKNOWN"]["A"]["raw"]["n"] == 4
    assert subsets["NONE"]["A"]["raw"]["n"] == 4
    assert subsets["supported_catalyst"]["A"]["raw"]["n"] == 4
    assert comparison["raw_metric_role"] == "RAW_VALIDATION_HOLDOUT"
    assert comparison["calibrated_metric_role"] == "CALIBRATION_FIT_DESCRIPTIVE"
    assert comparison["B_minus_A"]["raw"]["brier"] == 0
    assert comparison["final_test"]["outcomes_inspected"] is False


def test_comparison_rejects_silently_dropped_unknown_event(fitted):
    result, directory, rows, schema, settings = fitted
    unknown = rows.loc[
        rows["partition"].eq("validation") & rows["event_type_UNKNOWN"].eq(1), "event_id"
    ].iloc[0]
    dropped = result.predictions.loc[result.predictions["event_id"].ne(unknown)]
    with pytest.raises(ValueError, match="every eligible validation"):
        compare_model_a_b(rows, result.predictions, dropped, threshold=0.65)


def test_comparison_one_class_does_not_invent_auc(fitted):
    result, directory, rows, schema, settings = fitted
    rows = rows.copy()
    rows.loc[rows["partition"].eq("validation"), "y_revert_success"] = 0
    comparison = compare_model_a_b(rows, result.predictions, result.predictions, threshold=0.65)
    assert comparison["validation_positives"] == 0
    assert comparison["validation_class_identifiable"] is False
    assert comparison["B_minus_A"]["raw"]["roc_auc"] is None
    assert comparison["paired_subsets"]["all_eligible_validation"]["B"]["raw"]["pr_auc"] is None


@pytest.mark.parametrize("failure", ["future_cutoff", "final_target", "schema"])
def test_model_b_leakage_and_schema_fail_before_fitting(tmp_path, failure):
    rows, schema, settings = inputs()
    if failure == "future_cutoff":
        rows["feature_cutoff_timestamp"] = rows["event_timestamp"] + pd.Timedelta(days=1)
        message = "Feature cutoff"
    elif failure == "final_target":
        rows.loc[rows["partition"].eq("final_test"), "y_revert_success"] = 1
        message = "Locked final-test outcomes"
    else:
        schema["version"] = "changed"
        message = "schema versions"
    with pytest.raises((ValueError, ModelTrainingError), match=message):
        train_chronological_model(
            rows,
            schema,
            settings,
            tmp_path,
            model_version="bad",
            dataset_version="bad",
            expected_feature_schema_version="synthetic-model-b-v1",
            model_variant="B",
        )
    assert not list(tmp_path.glob("*.json"))


def test_comparison_rejects_final_outcomes_even_when_evaluating_validation(fitted):
    result, directory, rows, schema, settings = fitted
    rows = rows.copy()
    rows.loc[rows["partition"].eq("final_test"), "y_revert_success"] = 0
    with pytest.raises(ValueError, match="Final-test outcomes"):
        compare_model_a_b(rows, result.predictions, result.predictions, threshold=0.65)


@pytest.mark.parametrize("directory_present", [True, False])
def test_archive_guard_protects_any_registered_kind_even_when_files_missing(
    tmp_path, directory_present
):
    from structural_break.common.logging import new_run_id
    from structural_break.config.paths import ProjectPaths
    from structural_break.services.model_a import _archive_unregistered
    from structural_break.storage.database import DuckDBConnectionFactory, migrate
    from structural_break.storage.files import write_bytes
    from structural_break.storage.registry import Registration, RunRegistry

    root = Path(__file__).resolve().parents[2]
    paths = ProjectPaths.resolve(root, tmp_path / "workspace")
    paths.create_directories()
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    destination = paths.artifacts / "models" / "reserved_marker"
    marker = write_bytes(destination / "marker.json", b"{}")
    run_id = new_run_id()
    registry = RunRegistry(factory, paths.workspace_root)
    registry.start(
        run_id, "synthetic-registry-test", load_config(root / "configs"), "test", "synthetic"
    )
    registry.finish(
        run_id,
        status="SUCCESS",
        artifacts=(Registration("unrelated-report", "synthetic", marker),),
    )
    if not directory_present:
        assert destination.resolve().is_relative_to(paths.workspace_root.resolve())
        marker.unlink()
        destination.rmdir()
    with pytest.raises(ValueError, match="registered artifact"):
        # Case aliases must remain protected when Windows has no existing
        # directory from which Path.resolve can recover its original case.
        requested = destination if directory_present else destination.with_name("RESERVED_MARKER")
        _archive_unregistered(paths, requested, new_run_id())
    assert destination.exists() is directory_present
    assert not list(destination.parent.glob("reserved_marker.unregistered-*"))
    if directory_present:
        assert marker.read_bytes() == b"{}"

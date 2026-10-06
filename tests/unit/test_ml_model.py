"""Actual fitted models, chronology, calibration, immutable reload and SHAP tests."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from structural_break.config.loader import load_config
from structural_break.ml.model import (
    ModelTrainingError,
    fit_sigmoid,
    forward_folds,
    load_bundle,
    predictive_metrics,
    select_threshold,
    train_model_a,
    validate_features,
)


def model_inputs():
    generator = np.random.default_rng(73919)
    records = []
    for year in range(2016, 2026):
        for month in range(1, 13):
            target = int(month % 2 == 0)
            records.append(
                {
                    "event_id": f"synthetic_{year}_{month:02d}",
                    "event_timestamp": pd.Timestamp(year=year, month=month, day=5, tz="UTC"),
                    "horizon_end_date": pd.Timestamp(year=year, month=month, day=20),
                    "partition": "train"
                    if year < 2022
                    else "validation"
                    if year < 2024
                    else "final_test",
                    "supervised_eligible": year < 2024,
                    "y_revert_success": target if year < 2024 else None,
                    "signal": (2 * target - 1) + generator.normal(0, 0.4),
                    "nullable": np.nan if month % 3 == 0 else generator.normal(),
                    "binary_flag": month % 2,
                    "pair_id": "SYN_A__SYN_B" if month % 2 else "SYN_C__SYN_D",
                    "sector": "synthetic",
                    "divergence_sign": -1 if month % 2 else 1,
                }
            )
    schema = {
        "version": "quantitative-v1",
        "feature_columns": ["signal", "nullable", "binary_flag"],
        "columns": [
            {"name": "signal", "allow_missing": False, "family": "spread"},
            {"name": "nullable", "allow_missing": True, "family": "relationship"},
            {"name": "binary_flag", "allow_missing": False, "binary": True, "family": "liquidity"},
        ],
    }
    settings = load_config(Path(__file__).resolve().parents[2] / "configs").ml.model_copy(
        update={"search_trials": 2, "feature_schema_version": schema["version"]}
    )
    return pd.DataFrame(records), schema, settings


@pytest.fixture(scope="module")
def fitted_model(tmp_path_factory):
    rows, schema, settings = model_inputs()
    directory = tmp_path_factory.mktemp("actual_model")
    result = train_model_a(
        rows,
        schema,
        settings,
        directory / "bundle",
        model_version="test_model_A",
        dataset_version="synthetic_model_test",
        tracking_directory=directory / "mlflow",
        label_policy={"version": "label_actual_scientific_hash", "horizon_sessions": 10},
    )
    return result, directory / "bundle", rows, schema, settings


def test_actual_model_and_logistic_training_have_metrics_without_final_results(fitted_model):
    result, directory, rows, schema, settings = fitted_model
    assert result.metrics["final_test"] == {"status": "LOCKED", "outcomes_inspected": False}
    assert result.bundle.metadata["n_training"] == 72
    assert result.bundle.metadata["n_calibration"] == 24
    assert result.bundle.policy["candidate_threshold"] == 0.65
    assert result.bundle.policy["status"] == "FROZEN_PREDECLARED_SMALL_SAMPLE"
    assert result.bundle.metadata["training_only_transformations"] is True
    assert result.bundle.metadata["label_policy_version"] == "label_actual_scientific_hash"
    assert result.predictions["label_policy_version"].eq("label_actual_scientific_hash").all()
    assert len(result.predictions) == 96
    assert set(result.metrics["partitions"]["validation"]) >= {
        "logistic",
        "xgboost_raw",
        "xgboost_calibrated",
    }
    assert result.metrics["partitions"]["validation"]["xgboost_raw"]["n"] == 24
    assert (
        "CALIBRATED_VALIDATION_FIT_DESCRIPTIVE"
        in result.metrics["partitions"]["validation"]["role"]
    )
    assert result.manifest["mlflow_run_id"]
    assert (directory / "label_policy.json").exists()
    assert len(json.loads((directory / "search_scores.json").read_text())) == 6


def test_actual_reload_reproduces_probability_and_raw_margin_tree_shap(fitted_model):
    result, directory, rows, schema, settings = fitted_model
    reloaded = load_bundle(directory)
    matrix = rows.loc[rows["partition"] == "validation", schema["feature_columns"]]
    before, after = result.bundle.predict(matrix), reloaded.predict(matrix)
    for column in [
        "raw_margin",
        "raw_probability",
        "calibrated_probability",
        "logistic_probability",
    ]:
        np.testing.assert_allclose(before[column], after[column], rtol=0, atol=1e-12)
        assert (
            after[column].between(0, 1).all()
            if column != "raw_margin"
            else after[column].notna().all()
        )
    contributions = np.asarray(after["shap_values"].tolist())
    assert contributions.shape == (24, 3)
    np.testing.assert_allclose(
        contributions.sum(axis=1) + after["shap_base_value"], after["raw_margin"], atol=2e-5
    )
    assert (after["explanation_status"] == "AVAILABLE_RAW_MARGIN").all()
    assert after["feature_schema_version"].eq(schema["version"]).all()
    assert after["model_version"].eq("test_model_A").all()


def test_logistic_preprocessing_uses_training_only_medians_and_scale(fitted_model):
    result, directory, rows, schema, settings = fitted_model
    pipeline = result.bundle.logistic.named_steps["preprocessor"].named_transformers_["continuous"]
    training = rows.loc[rows["partition"] == "train", ["signal", "nullable"]]
    imputed = training.fillna(training.median()).to_numpy()
    np.testing.assert_allclose(pipeline.named_steps["imputer"].statistics_, training.median())
    np.testing.assert_allclose(pipeline.named_steps["scaler"].mean_, imputed.mean(axis=0))
    assert result.bundle.logistic.named_steps["preprocessor"].transformers_[1][0] == "binary"
    assert set(result.bundle.metadata["training_event_ids"]).isdisjoint(
        result.bundle.metadata["calibration_event_ids"]
    )


def test_locked_outcomes_are_rejected_before_training(tmp_path):
    rows, schema, settings = model_inputs()
    rows.loc[rows["partition"] == "final_test", "y_revert_success"] = 1
    with pytest.raises(ModelTrainingError, match="Locked final-test outcomes"):
        train_model_a(rows, schema, settings, tmp_path, model_version="bad", dataset_version="bad")


def test_final_feature_rows_do_not_enter_fit_or_evaluation(fitted_model):
    result, directory, rows, schema, settings = fitted_model
    final_ids = set(rows.loc[rows["partition"] == "final_test", "event_id"])
    assert final_ids.isdisjoint(result.predictions["event_id"])
    assert final_ids.isdisjoint(result.bundle.metadata["training_event_ids"])
    assert final_ids.isdisjoint(result.bundle.metadata["calibration_event_ids"])
    assert (
        result.bundle.predict(
            rows.loc[rows["partition"] == "final_test", schema["feature_columns"]]
        ).shape[0]
        == 24
    )


def test_future_feature_cutoff_fails_before_any_fit(tmp_path):
    rows, schema, settings = model_inputs()
    rows["feature_cutoff_timestamp"] = rows["event_timestamp"] + pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="Feature cutoff"):
        train_model_a(rows, schema, settings, tmp_path, model_version="bad", dataset_version="bad")


def test_training_label_horizon_crossing_boundary_fails(tmp_path):
    rows, schema, settings = model_inputs()
    rows.loc[0, "horizon_end_date"] = pd.Timestamp("2022-01-03")
    with pytest.raises(ValueError, match="Training label crosses"):
        train_model_a(rows, schema, settings, tmp_path, model_version="bad", dataset_version="bad")


def test_forward_folds_purge_using_horizon_not_count_of_events():
    rows, schema, settings = model_inputs()
    training = rows.loc[rows["partition"] == "train"].copy()
    training.loc[0, "event_timestamp"] = pd.Timestamp("2018-12-21", tz="UTC")
    training.loc[0, "horizon_end_date"] = pd.Timestamp("2019-01-08")
    training.loc[1, "event_timestamp"] = pd.Timestamp("2019-12-23", tz="UTC")
    training.loc[1, "horizon_end_date"] = pd.Timestamp("2020-01-08")
    folds = forward_folds(training, settings)
    assert [fold["year"] for fold in folds] == [2019, 2020, 2021]
    assert 0 not in folds[0]["fit_index"]
    assert 1 not in folds[0]["evaluation_index"]
    assert 0 in folds[1]["fit_index"]
    assert 1 not in folds[1]["fit_index"]


@pytest.mark.parametrize(
    "labels,margins", [([0, 0, 0], [-2, 0, 2]), ([1, 1, 1], [-2, 0, 2]), ([0, 1], [0, 0])]
)
def test_unidentifiable_calibration_is_explicit_and_smoothed(labels, margins):
    calibrator = fit_sigmoid(margins, labels)
    assert calibrator.status == "CONSTANT_UNIDENTIFIABLE"
    assert calibrator.slope == 0
    expected = (sum(labels) + 1) / (len(labels) + 2)
    np.testing.assert_allclose(calibrator.predict([-100, 0, 100]), expected)


def test_monotone_validation_calibrator_never_reverses_ranking():
    calibrator = fit_sigmoid([-3, -2, -1, 1, 2, 3], [0, 0, 1, 0, 1, 1])
    assert calibrator.slope >= 0
    probabilities = calibrator.predict(np.linspace(-10, 10, 31))
    assert (np.diff(probabilities) >= 0).all()
    inverted = fit_sigmoid([-3, -2, -1, 1, 2, 3], [1, 1, 1, 0, 0, 0])
    assert inverted.slope == 0
    assert inverted.status == "CONSTANT_NONNEGATIVE_BOUNDARY"


@pytest.mark.parametrize(
    "columns",
    [
        ["signal", "binary_flag", "nullable"],
        ["signal", "nullable"],
        ["signal", "nullable", "binary_flag", "pair_id"],
    ],
)
def test_feature_schema_order_is_a_hard_contract(columns):
    rows, schema, settings = model_inputs()
    with pytest.raises(ValueError, match="names/order"):
        validate_features(rows[columns], schema)


def test_feature_schema_rejects_target_identity_infinity_and_required_missing():
    rows, schema, settings = model_inputs()
    matrix = rows[schema["feature_columns"]].copy()
    matrix.loc[0, "signal"] = np.inf
    with pytest.raises(ValueError, match="Infinite"):
        validate_features(matrix, schema)
    matrix.loc[0, "signal"] = np.nan
    with pytest.raises(ValueError, match="Required feature"):
        validate_features(matrix, schema)
    bad = {"version": "bad", "feature_columns": ["pair_id"], "columns": [{"name": "pair_id"}]}
    with pytest.raises(ValueError, match="Identifiers"):
        validate_features(rows[["pair_id"]], bad)


def test_threshold_is_predeclared_despite_apparent_validation_precision_gain():
    result = select_threshold([0, 0, 1, 1], [0.56, 0.62, 0.70, 0.90])
    assert result["candidate_threshold"] == 0.65
    assert result["status"] == "FROZEN_PREDECLARED_SMALL_SAMPLE"
    assert len(result["validation_sensitivity"]) == 5
    assert result["economic_threshold_validation"] == "DEFERRED_TO_PHASE6"


def test_metrics_include_coverage_probability_quality_and_defined_nulls():
    result = predictive_metrics([0, 1, 0, 1], [0.1, 0.2, 0.8, 0.9])
    assert result["n"] == 4
    assert result["selected"] == 2
    assert result["coverage"] == 0.5
    assert result["precision"] == 0.5
    assert sum(bin["n"] for bin in result["calibration_curve"]) == 4
    assert result["success_rate_wilson95_iid_reference"]
    one_class = predictive_metrics([0, 0], [0.1, 0.2])
    assert one_class["roc_auc"] is None
    assert one_class["pr_auc"] is None
    assert one_class["recall"] is None
    assert one_class["precision"] is None


def test_bundle_hash_tampering_is_rejected(tmp_path, fitted_model):
    result, directory, rows, schema, settings = fitted_model
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(directory, copy)
    path = copy / "platt_calibrator.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_bundle(copy)


def test_one_class_training_has_explicit_failure(tmp_path):
    rows, schema, settings = model_inputs()
    rows.loc[rows["partition"] == "train", "y_revert_success"] = 0
    with pytest.raises(ModelTrainingError, match="both observed target classes"):
        train_model_a(rows, schema, settings, tmp_path, model_version="bad", dataset_version="bad")


def test_retraining_same_frozen_input_reproduces_scores_and_hyperparameters(tmp_path, fitted_model):
    result, directory, rows, schema, settings = fitted_model
    replay = train_model_a(
        rows,
        schema,
        settings,
        tmp_path / "replay",
        model_version="test_model_A",
        dataset_version="synthetic_model_test",
        tracking_directory=tmp_path / "mlflow",
        label_policy={"version": "label_actual_scientific_hash", "horizon_sessions": 10},
    )
    assert (
        replay.bundle.metadata["selected_hyperparameters"]
        == result.bundle.metadata["selected_hyperparameters"]
    )
    assert replay.bundle.calibrator == result.bundle.calibrator
    for column in [
        "raw_margin",
        "raw_probability",
        "calibrated_probability",
        "logistic_probability",
    ]:
        np.testing.assert_allclose(
            replay.predictions[column], result.predictions[column], atol=1e-12, rtol=0
        )
    assert (tmp_path / "replay/xgb_model.json").read_bytes() == (
        directory / "xgb_model.json"
    ).read_bytes()


@pytest.mark.parametrize("invalid", [0.5, 2, -1, float("nan")])
def test_fractional_or_nonbinary_target_is_not_silently_cast(invalid):
    with pytest.raises(ValueError, match="binary"):
        predictive_metrics([0, invalid], [0.2, 0.7])
    with pytest.raises(ModelTrainingError, match="binary"):
        fit_sigmoid([0.0, 1.0], [0, invalid])


def test_both_final_training_classes_do_not_allow_arbitrary_unusable_fold_search(tmp_path):
    rows, schema, settings = model_inputs()
    training = rows["partition"] == "train"
    rows.loc[training, "y_revert_success"] = 0
    # The second class first appears in the final evaluation year. All three
    # earlier expanding fit periods therefore have only class zero.
    late = training & pd.to_datetime(rows["event_timestamp"]).dt.year.eq(2021)
    rows.loc[late, "y_revert_success"] = 1
    assert rows.loc[training, "y_revert_success"].nunique() == 2
    with pytest.raises(ModelTrainingError, match="No fold has both training classes"):
        train_model_a(
            rows,
            schema,
            settings,
            tmp_path / "forbidden_model",
            model_version="bad_unusable_folds",
            dataset_version="synthetic",
        )
    assert not (tmp_path / "forbidden_model/bundle_manifest.json").exists()

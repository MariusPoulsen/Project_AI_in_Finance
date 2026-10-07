"""Independent scientific checks of matched research-v2 development evaluation."""

from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest

from structural_break.research import evaluation
from structural_break.research.evaluation import evaluate_matched_models, paired_assessment
from structural_break.research.protocol import ResearchProtocol, load_protocol

QUANT = ("q1", "q2")
BLOCKS = {
    "sentiment": ("tone", "tone_unknown"),
    "gemma": ("event_unknown",),
    "both": ("tone", "tone_unknown", "event_unknown"),
}


def protocol() -> ResearchProtocol:
    values = load_protocol(Path("configs/research_v2.yaml")).model_dump()
    values.update(
        logistic_c=(0.1, 1.0),
        xgb_candidates=(
            {"max_depth": 1, "n_estimators": 5, "learning_rate": 0.1, "min_child_weight": 1},
            {"max_depth": 2, "n_estimators": 5, "learning_rate": 0.1, "min_child_weight": 1},
        ),
        bootstrap_replicates=100,
    )
    return ResearchProtocol.model_validate(values)


def registry() -> pd.DataFrame:
    rows = []
    for year in (2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023):
        for month in (2, 5, 8, 11):
            index = len(rows)
            day = date(year, month, 1)
            label = index % 2
            unknown = int(index % 3 == 0)
            pair = "KO__PEP" if index % 3 else "KO__WMT"
            rows.append(
                {
                    "event_id": f"event_{index:03d}",
                    "event_date": day,
                    "horizon_end_date": day + timedelta(days=28),
                    "supervised_eligible": True,
                    "y_revert_success": label,
                    "pair_id": pair,
                    "leg_a": "KO",
                    "leg_b": pair.split("__")[1],
                    "sector": "Consumer Staples",
                    "business_group": "beverages" if pair == "KO__PEP" else "retail",
                    "baseline1_eligible": index % 4 != 0,
                    "q1": float(label) + float(index % 3) * 0.4,
                    "q2": float(index % 7),
                    "tone": np.nan if unknown else 0.3 * label - 0.1,
                    "tone_unknown": unknown,
                    "event_unknown": int(index % 5 == 0),
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def fitted() -> Any:
    return evaluate_matched_models(registry(), QUANT, BLOCKS, protocol())


def test_matched_all_unknowns_retained_on_original_cohort(fitted: Any) -> None:
    rows = registry()
    predictions = fitted.predictions
    assert set(predictions["event_id"]) == set(rows["event_id"])
    assert predictions["event_id"].is_unique
    unknown_ids = set(rows.loc[rows["tone_unknown"].eq(1), "event_id"])
    assert unknown_ids <= set(predictions["event_id"])
    assert fitted.report["all_quantitative_events_retained"] is True
    assert fitted.report["final_test_read"] is False
    assert fitted.report["cohorts"]["fit"]["n"] == 16
    assert fitted.report["cohorts"]["calibration"]["n"] == 8
    assert fitted.report["cohorts"]["assessment"]["n"] == 8
    for family in ("logistic", "xgboost"):
        for variant in ("A", "B_sentiment", "B_gemma", "B_both"):
            record = fitted.report["models"][family][variant]
            assert record["raw_assessment"]["n"] == 8
            assert record["calibrated_assessment"]["n"] == 8
            assert record["calibrator"]["sample_count"] == 8
            scores = predictions[f"{family}_{variant}_calibrated"]
            assert np.isfinite(scores).all()
            assert scores.between(0, 1).all()
            if variant != "A":
                assert record["paired_assessment"]["resamples"] == 100


def test_raw_models_and_calibrators_replay_from_persisted_bytes(fitted: Any) -> None:
    rows = registry()
    predictions = fitted.predictions.set_index("event_id")
    for name, content in fitted.models.items():
        restored = joblib.load(io.BytesIO(content))
        values = restored.predict(rows)
        np.testing.assert_allclose(
            values,
            predictions.loc[rows["event_id"], f"{name}_calibrated"].to_numpy(),
            rtol=0,
            atol=1e-12,
        )
        assert restored.columns == (
            QUANT if name.endswith("_A") else (*QUANT, *BLOCKS[name.split("_B_")[1]])
        )


def test_all_fitting_transformations_and_calibration_use_separate_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = registry()
    estimator_fits: list[set[int]] = []
    calibrator_fits: list[set[int]] = []
    original_sigmoid = evaluation.fit_sigmoid

    def fitting_tracker(original_fit: Any) -> Any:
        def tracked_fit(model: Any, features: pd.DataFrame, labels: pd.Series[Any]) -> Any:
            estimator_fits.append(set(features.index))
            return original_fit(model, features, labels)

        return tracked_fit

    def calibrator(margins: Any, labels: pd.Series[Any]) -> Any:
        calibrator_fits.append(set(labels.index))
        return original_sigmoid(margins, labels)

    monkeypatch.setattr(evaluation.Pipeline, "fit", fitting_tracker(evaluation.Pipeline.fit))
    monkeypatch.setattr(
        evaluation.XGBClassifier, "fit", fitting_tracker(evaluation.XGBClassifier.fit)
    )
    monkeypatch.setattr(evaluation, "fit_sigmoid", calibrator)
    result = evaluate_matched_models(rows, QUANT, BLOCKS, protocol())
    assert estimator_fits and calibrator_fits
    fit_ids = set(rows.index[pd.to_datetime(rows["event_date"]).dt.year.le(2019)])
    cal_ids = set(rows.index[pd.to_datetime(rows["event_date"]).dt.year.isin([2020, 2021])])
    assessment_ids = set(rows.index[pd.to_datetime(rows["event_date"]).dt.year.ge(2022)])
    assert all(indices <= fit_ids for indices in estimator_fits)
    assert all(indices == cal_ids for indices in calibrator_fits)
    assert all(not (indices & assessment_ids) for indices in estimator_fits + calibrator_fits)
    assert result.report["cohorts"]["assessment"]["n"] == len(assessment_ids)


def test_full_horizon_is_purged_at_every_forward_tuning_year_end() -> None:
    rows = registry()
    tail = dict(rows.iloc[0])
    tail.update(
        event_id="late_2018_resolves_2019",
        event_date=date(2018, 12, 20),
        horizon_end_date=date(2019, 1, 25),
    )
    rows = pd.concat([rows, pd.DataFrame([tail])], ignore_index=True)
    result = evaluate_matched_models(rows, QUANT, BLOCKS, protocol())
    for family in result.report["models"].values():
        for variant in family.values():
            for candidate in variant["tuning"]:
                first, second = candidate["folds"]
                assert first["year"] == 2018
                assert first["assessment_n"] == 4
                assert first["purged_year_tail"] == 1
                assert second["year"] == 2019
                assert second["fit_n"] == 12  # Crossing event is not fit at Jan 1, 2019.


def test_calibration_tail_and_assessment_tail_are_purged_not_early_resolution_waived() -> None:
    rows = registry()
    extra = []
    for year in (2019, 2021, 2023):
        tail = dict(rows.iloc[0])
        tail.update(
            event_id=f"tail_{year}",
            event_date=date(year, 12, 20),
            horizon_end_date=date(year + 1, 1, 25),
            resolution_date=date(year, 12, 21),
        )
        extra.append(tail)
    rows = pd.concat([rows, pd.DataFrame(extra)], ignore_index=True)
    result = evaluate_matched_models(rows, QUANT, BLOCKS, protocol())
    assert not any(identity.startswith("tail_") for identity in result.predictions["event_id"])
    assert result.report["excluded_registry_rows"] == 3


@pytest.mark.parametrize(
    "leaked",
    [
        "event_id",
        "pair_id",
        "y_revert_success",
        "outcome_type",
        "resolution_date",
        "time_to_resolution",
        "max_adverse_z",
        "max_favourable_z",
        "censor_reason",
        "gross_pair_return",
        "net_pair_return",
    ],
)
def test_targets_identity_and_realised_outcomes_are_never_allowed_features(leaked: str) -> None:
    rows = registry()
    if leaked not in rows:
        rows[leaked] = 1
    with pytest.raises(ValueError, match="Outcome/identity"):
        evaluate_matched_models(rows, QUANT, {"both": (leaked,)}, protocol())


def test_duplicate_predictors_events_and_infinite_features_block() -> None:
    rows = registry()
    with pytest.raises(ValueError, match="duplicate field"):
        evaluate_matched_models(rows, QUANT, {"both": ("q1",)}, protocol())
    rows.loc[1, "event_id"] = rows.loc[0, "event_id"]
    with pytest.raises(ValueError, match="Duplicate observations"):
        evaluate_matched_models(rows, QUANT, BLOCKS, protocol())
    rows = registry()
    rows.loc[0, "q1"] = np.inf
    with pytest.raises(ValueError, match="infinite"):
        evaluate_matched_models(rows, QUANT, BLOCKS, protocol())


def test_eligible_nonbinary_label_and_final_event_are_blocking() -> None:
    rows = registry()
    rows.loc[0, "y_revert_success"] = 2
    with pytest.raises(ValueError, match="binary targets"):
        evaluate_matched_models(rows, QUANT, BLOCKS, protocol())
    rows = registry()
    rows.loc[0, "event_date"] = date(2024, 1, 1)
    rows.loc[0, "horizon_end_date"] = date(2024, 2, 1)
    with pytest.raises(ValueError, match="final-test"):
        evaluate_matched_models(rows, QUANT, BLOCKS, protocol())


def test_paired_assessment_reuses_complete_quarter_blocks_and_seed() -> None:
    rows = registry().iloc[-8:].copy()
    a = np.array([0.8, 0.8, 0.7, 0.4, 0.7, 0.7, 0.6, 0.6])
    b = np.array([0.4, 0.8, 0.3, 0.8, 0.4, 0.9, 0.3, 0.9])
    one = paired_assessment(rows, a, b, protocol())
    two = paired_assessment(rows, a, b, protocol())
    assert one == two
    assert one["observed_quarter_blocks"] == 8
    y = rows["y_revert_success"].to_numpy()
    expected = float(((b - y) ** 2 - (a - y) ** 2).mean())
    assert one["brier_delta_B_minus_A"] == pytest.approx(expected)
    assert one["point_estimate_improves"] == (expected < 0)
    assert sum(record["n"] for record in one["slices"]["year"].values()) == len(rows)


@pytest.mark.parametrize("bad", [np.nan, -0.1, 1.1])
def test_paired_assessment_rejects_invalid_values(bad: float) -> None:
    rows = registry().iloc[-8:].copy()
    probabilities = np.full(len(rows), 0.5)
    probabilities[0] = bad
    with pytest.raises(ValueError, match="Invalid paired|outside their contract"):
        paired_assessment(rows, probabilities, np.full(len(rows), 0.5), protocol())

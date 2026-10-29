"""Current monitoring uses scored-event identities and full missing-data denominators."""

import pandas as pd
import pytest

from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.services import current_monitor as monitor


def inputs():
    forecasts = pd.DataFrame(
        {
            "event_id": ["a", "b"],
            "year": [2018, 2018],
            "labelled": [True, False],
            "y": [1, None],
            "pair_id": ["A__B", "A__C"],
            "leg_a": ["A", "A"],
            "leg_b": ["B", "C"],
            "z_signed": [2.1, -2.2],
        }
    )
    registry = pd.DataFrame(
        {
            "event_id": ["a"],
            "half_life": [10.0],
            "sentiment_both_known": [1],
            "sec_a_metadata_coverage_unknown": [0],
            "sec_b_metadata_coverage_unknown": [0],
            **{feature: [0] for feature in EVENT_FEATURE_NAMES},
        }
    )
    return forecasts, registry


def test_current_cohort_and_coverage_keep_events_missing_from_the_old_input_export():
    forecasts, registry = inputs()
    frame = monitor.event_inputs(forecasts, registry, final_included=False)
    rows = monitor.cohorts(frame, final_included=False).set_index("Period")
    holdout = rows.loc["Holdout · 2018–2023"]
    assert holdout["Events"] == 2 and holdout["Labelled"] == 1
    assert holdout["Reversion rate"] == 1
    assert rows.loc["Final test · 2024–2025", "Status"] == "Results pending"
    assert pd.isna(rows.loc["Final test · 2024–2025", "Events"])
    coverage = monitor.coverage(frame).set_index("label")
    assert coverage.loc["FinBERT tone known for both legs", "share"] == 0.5
    assert coverage.loc["Leg A SEC metadata UNKNOWN", "share"] == 0.5
    assert set(coverage.n) == {2}
    assert not coverage.index.str.contains("Catalyst", case=False).any()


def test_catalyst_fields_and_old_probabilities_never_enter_feature_drift():
    forecasts, registry = inputs()
    registry["logistic_B_both_calibrated"] = 0.5
    frame = monitor.event_inputs(forecasts, registry, final_included=False)
    assert not set(monitor.drift_features(frame)) & set(EVENT_FEATURE_NAMES)
    assert "logistic_B_both_calibrated" not in frame
    with pytest.raises(ValueError, match="approved"):
        monitor.drift(frame, "affected_leg_A")
    profile = monitor.drift(frame, "half_life").iloc[0]
    assert profile["n"] == 2 and profile["missing_share"] == 0.5
    assert profile["p50"] == 10


def test_final_test_rows_require_the_current_export_to_include_them():
    forecasts, registry = inputs()
    forecasts.loc[0, "year"] = 2024
    with pytest.raises(ValueError, match="Final-test"):
        monitor.event_inputs(forecasts, registry, final_included=False)
    frame = monitor.event_inputs(forecasts, registry, final_included=True)
    rows = monitor.cohorts(frame, final_included=True).set_index("Period")
    assert rows.loc["Final test · 2024–2025", "Events"] == 1
    assert rows.loc["Final test · 2024–2025", "Status"] == "Exported"


def test_period_boundaries_describe_evaluation_not_frozen_fitting_partitions():
    assert monitor.period_of_year(2017) == "Selection · 2010–2017"
    assert monitor.period_of_year(2018) == "Holdout · 2018–2023"
    assert monitor.period_of_year(2024) == "Final test · 2024–2025"
    with pytest.raises(ValueError):
        monitor.period_of_year(2006)


def test_coverage_reports_current_development_stages_and_only_published_assessment():
    forecasts, registry = inputs()
    forecasts.loc[0, "year"] = 2010
    frame = monitor.event_inputs(forecasts, registry, final_included=False)
    rows = monitor.coverage(frame)
    table = monitor.coverage_table(rows).set_index("Indicator")
    assert table.columns.tolist() == ["Fit · 2010–2017 (n=1)", "Calibration · 2018–2023 (n=1)"]
    assert not table.index.str.contains("catalyst", case=False).any()
    assert set(table.index) == set(monitor.COVERAGE.values())
    assert table.loc["FinBERT tone known for both legs"].tolist() == [1, 0]
    assert table.loc["Leg A SEC metadata UNKNOWN"].tolist() == [0, 1]
    assert set(rows.year) == {2010, 2018}
    forecasts.loc[1, "year"] = 2024
    published = monitor.event_inputs(forecasts, registry, final_included=True)
    assert "Assessment · 2024–2025 (n=1)" in monitor.coverage_table(monitor.coverage(published))

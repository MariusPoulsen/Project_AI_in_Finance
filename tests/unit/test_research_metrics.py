"""Independent loss and weighting checks using synthetic research observations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import log_loss

from structural_break.ml.model import predictive_metrics
from structural_break.research.evaluation import (
    assessment_slices,
    paired_assessment,
    research_metrics,
)
from structural_break.research.protocol import load_protocol


def rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pair_id": ["P__Q"] * 3 + ["P__R"] + ["S__R"] * 2,
            "leg_a": ["P"] * 4 + ["S"] * 2,
            "leg_b": ["Q"] * 3 + ["R"] * 3,
            "y_revert_success": [0, 1, 0, 1, 1, 0],
            "event_date": pd.to_datetime(
                ["2022-01-05", "2022-04-05", "2022-07-05", "2022-10-05", "2023-01-05", "2023-04-05"]
            ),
            "sector": ["one"] * 6,
            "business_group": ["group_one"] * 4 + ["group_two"] * 2,
            "baseline1_eligible": [True, False, True, True, False, True],
        }
    )


def test_log_loss_uses_natural_logs_and_finite_float64_endpoint_clipping() -> None:
    observations = rows().iloc[:4].copy()
    observations["y_revert_success"] = [0, 1, 0, 1]
    probabilities = np.array([0.0, 1.0, 1.0, 0.0])
    metrics = research_metrics(observations, probabilities, 0.65)
    epsilon = np.finfo(np.float64).eps
    expected = -(np.log(epsilon) + np.log1p(-epsilon)) / 2
    assert metrics["log_loss"] == pytest.approx(expected)
    assert metrics["log_loss"] == pytest.approx(
        log_loss(observations.y_revert_success, probabilities, labels=[0, 1])
    )
    assert np.isfinite(metrics["log_loss"])
    np.testing.assert_array_equal(probabilities, [0.0, 1.0, 1.0, 0.0])


def test_pair_and_issuer_balancing_equal_independent_group_average_losses() -> None:
    observations = rows()
    probabilities = np.array([0.1, 0.4, 0.2, 0.8, 0.3, 0.7])
    y = observations.y_revert_success.to_numpy()
    losses = {
        "brier": (probabilities - y) ** 2,
        "log_loss": -(y * np.log(probabilities) + (1 - y) * np.log1p(-probabilities)),
    }
    metrics = research_metrics(observations, probabilities, 0.65)
    for name, values in losses.items():
        pair_averages = [values[group.index].mean() for _, group in observations.groupby("pair_id")]
        issuer_averages = [
            values[
                (observations.leg_a.eq(issuer) | observations.leg_b.eq(issuer)).to_numpy()
            ].mean()
            for issuer in ("P", "Q", "R", "S")
        ]
        assert metrics[f"pair_balanced_{name}"] == pytest.approx(np.mean(pair_averages))
        assert metrics[f"issuer_balanced_{name}"] == pytest.approx(np.mean(issuer_averages))
    shared = predictive_metrics(y, probabilities, 0.65)
    assert "log_loss" not in shared  # Original Phase 3/4 contract stays intact.
    assert {name: metrics[name] for name in shared} == shared


def test_empty_and_one_class_loss_metrics_are_explicit() -> None:
    observations = rows()
    metrics = research_metrics(observations.iloc[:0], np.array([]), 0.65)
    for name in ("log_loss", "pair_balanced_brier", "issuer_balanced_log_loss"):
        assert metrics[name] is None
    one_class = observations.iloc[:2].copy()
    one_class["y_revert_success"] = 1
    metrics = research_metrics(one_class, np.array([0.25, 0.75]), 0.65)
    assert metrics["roc_auc"] is None and metrics["pr_auc"] is None
    assert metrics["log_loss"] == pytest.approx(-(np.log(0.25) + np.log(0.75)) / 2)


def test_paired_weighted_log_losses_match_single_model_reports() -> None:
    from pathlib import Path

    observations = rows()
    protocol = load_protocol(Path("configs/research_v2.yaml"))
    a = np.array([0.1, 0.4, 0.2, 0.8, 0.3, 0.7])
    b = np.array([0.2, 0.5, 0.3, 0.7, 0.6, 0.4])
    comparison = paired_assessment(observations, a, b, protocol)
    metrics_a, metrics_b = (research_metrics(observations, values, 0.65) for values in (a, b))
    for balance in ("pair_balanced", "issuer_balanced"):
        for loss in ("brier", "log_loss"):
            name = f"{balance}_{loss}"
            assert comparison[name] == {"A": metrics_a[name], "B": metrics_b[name]}
    assert comparison["resamples"] == 2000


def test_descriptive_slices_preserve_active_coverage_and_empty_frozen_groups() -> None:
    from pathlib import Path

    observations = rows()
    probabilities = np.array([0.1, 0.4, 0.2, 0.8, 0.3, 0.7])
    protocol = load_protocol(Path("configs/research_v2.yaml"))
    slices = assessment_slices(
        observations,
        probabilities,
        protocol,
        business_groups=("group_one", "group_two", "empty_group"),
    )
    active = slices["ACTIVE"]["True"]
    assert active["n"] == 4 and active["positives"] == 1
    assert active["selected"] == 2 and active["coverage"] == 0.5
    expected = research_metrics(observations.loc[[0, 2, 3, 5]], probabilities[[0, 2, 3, 5]], 0.65)
    assert {key: active[key] for key in expected} == expected
    assert set(slices["business_group"]) == {"group_one", "group_two", "empty_group"}
    empty = slices["business_group"]["empty_group"]
    assert empty["n"] == empty["positives"] == empty["selected"] == 0
    assert empty["pairs"] == empty["issuers"] == 0
    assert empty["roc_auc"] is empty["pr_auc"] is empty["log_loss"] is None
    assert empty["calibration_curve"] == []
    for name in ("year", "sector", "ACTIVE", "business_group"):
        assert sum(group["n"] for group in slices[name].values()) == len(observations)


def test_one_class_and_single_observation_slices_keep_discrimination_undefined() -> None:
    from pathlib import Path

    observations = rows().iloc[[3]].copy()
    protocol = load_protocol(Path("configs/research_v2.yaml"))
    slices = assessment_slices(
        observations, np.array([0.8]), protocol, business_groups=("group_one", "group_two")
    )
    single = slices["business_group"]["group_one"]
    assert single["n"] == single["positives"] == 1
    assert single["roc_auc"] is single["pr_auc"] is None
    assert single["coverage"] == 1.0
    assert single["log_loss"] == pytest.approx(-np.log(0.8))
    assert slices["ACTIVE"]["False"]["n"] == 0
    assert slices["year"]["2023"]["n"] == 0

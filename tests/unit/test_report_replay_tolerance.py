"""Native report replay tolerates only last-digit float noise."""

import math

import numpy as np
import pytest

from structural_break.research.model_job import report_values_reproduce

STORED = {
    "events": 120,
    "positives": 31,
    "log_loss": 0.021827986026316196,
    "roc_auc": None,
    "slices": [{"group": "Integrated oil and gas", "brier": 0.000675682362619368}],
}


def replay(**changes):
    value = {**STORED, "slices": [dict(STORED["slices"][0])]}
    value.update(changes)
    return value


def test_last_digit_summation_noise_reproduces():
    noisy = replay(log_loss=0.021827986026316193)
    noisy["slices"][0]["brier"] = 0.0006756823626193678
    assert report_values_reproduce(noisy, STORED)


def test_numpy_scalars_compare_by_value():
    assert report_values_reproduce(
        replay(events=np.int64(120), log_loss=np.float64(0.021827986026316196)), STORED
    )


@pytest.mark.parametrize(
    "changed",
    [
        replay(log_loss=0.021827986026316196 * (1 + 1e-9)),
        replay(events=121),
        replay(roc_auc=0.5),
        {key: value for key, value in STORED.items() if key != "positives"},
        replay(slices=[]),
        replay(slices=[{"group": "Utilities", "brier": 0.000675682362619368}]),
    ],
)
def test_material_changes_do_not_reproduce(changed):
    assert not report_values_reproduce(changed, STORED)


def test_nan_matches_only_nan():
    assert report_values_reproduce({"x": math.nan}, {"x": math.nan})
    assert not report_values_reproduce({"x": math.nan}, {"x": 0.0})
    assert not report_values_reproduce({"x": 0.0}, {"x": math.nan})

"""Policy gates are ranked on matched events without inventing probability forecasts."""

import numpy as np
import pandas as pd
import pytest

from structural_break.app_ui.result_charts import metric_bars
from structural_break.services.forecast_baselines import metrics, validate_flags


def test_baselines_keep_the_common_population_and_leave_probability_losses_unavailable():
    forecasts = pd.DataFrame(
        {
            "event_id": list("abcdef"),
            "year": [2017] * 6,
            "labelled": [True] * 4 + [False, True],
            "y": [1, 0, 1, 0, 1, np.nan],
        }
    )
    flags = pd.DataFrame(
        {"event_id": list("abcdef"), "baseline1_eligible": [True, False, True, False, True, True]}
    )
    rows = metrics(forecasts, flags).set_index("model")
    assert rows.n.tolist() == [4, 4]
    assert rows.selected_n.tolist() == [4, 2]
    assert rows.loc["baseline0", "roc_auc"] == 0.5
    assert rows.loc["baseline0", "pr_auc"] == 0.5
    assert rows.loc["baseline1", "roc_auc"] == 1.0
    assert rows.loc["baseline1", "pr_auc"] == 1.0
    assert rows[["log_loss", "brier"]].isna().all().all()
    figure = metric_bars(rows.reset_index(), "roc_auc", "ROC AUC", rows.index.tolist())
    assert list(figure.data[0].x) == [0.5, 1.0]
    assert not metric_bars(rows.reset_index(), "log_loss", "Log loss", rows.index.tolist()).data
    assert metrics(forecasts, None).model.tolist() == ["baseline0"]


def test_missing_or_unknown_active_flags_cannot_be_treated_as_inactive():
    forecasts = pd.DataFrame({"event_id": ["a", "b"]})
    for flags in (
        pd.DataFrame({"event_id": ["a"], "baseline1_eligible": [True]}),
        pd.DataFrame({"event_id": ["a", "a"], "baseline1_eligible": [True, False]}),
        pd.DataFrame({"event_id": ["a", "b"], "baseline1_eligible": [True, None]}),
        pd.DataFrame({"event_id": ["a", "b"], "baseline1_eligible": ["True", "False"]}),
    ):
        with pytest.raises(ValueError, match="exact forecast events"):
            validate_flags(flags, forecasts)


def test_one_class_has_no_invented_auc():
    forecasts = pd.DataFrame({"event_id": ["a"], "year": [2023], "labelled": [True], "y": [0]})
    rows = metrics(forecasts, None)
    assert rows.roc_auc.isna().all() and rows.pr_auc.isna().all()

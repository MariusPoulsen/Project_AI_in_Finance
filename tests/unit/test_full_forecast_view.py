"""The agent comparison follows the chosen period and rejects unmatched cohorts."""

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

pytestmark = [
    pytest.mark.allow_hosts(["127.0.0.1", "::1"]),
    pytest.mark.usefixtures("preserve_main_module"),
]


def forecast_tab(rows, period):
    from structural_break.app_ui.full_forecast_view import render

    render(rows, period)


def test_selected_period_has_a_matched_agent_comparison_and_no_trading_metrics():
    rows = pd.DataFrame(
        [
            {
                "period": period,
                "model": model,
                "roc_auc": auc,
                "pr_auc": 0.2,
                "log_loss": 0.3,
                "brier": 0.1,
                "n": n,
                "base_rate": 0.1,
            }
            for period, auc, n in [("2010–2017", 0.7, 100), ("2018–2023", 0.6, 200)]
            for model in ["full_base", "full"]
        ]
    )
    rows.loc[rows.model.eq("full") & rows.period.eq("2018–2023"), "roc_auc"] = 0.58
    app = AppTest.from_function(forecast_tab, args=(rows, "2018–2023"), default_timeout=30).run()
    assert not app.exception and not app.error
    comparison = app.dataframe[0].value
    assert comparison.Metric.tolist() == ["ROC AUC ↑", "PR AUC ↑", "Log loss ↓", "Brier ↓"]
    assert comparison.iloc[0]["Forecast only"] == 0.6
    assert comparison.iloc[0]["Full model"] == 0.58
    assert comparison.iloc[0]["Change"] == pytest.approx(-0.02)
    assert len(app.table[0].value) == 6

    # An apparently favourable agent result cannot be shown on a different cohort.
    rows.loc[rows.model.eq("full"), "n"] = 199
    failed = AppTest.from_function(forecast_tab, args=(rows, "2018–2023"), default_timeout=30).run()
    assert not failed.exception and failed.error
    assert not failed.dataframe

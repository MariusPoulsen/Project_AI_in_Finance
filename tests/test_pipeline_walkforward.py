"""Walk-forward replication: rolling purged splits and per-candidate allocation."""

from datetime import date

import numpy as np
import pandas as pd

from structural_break.pipeline.walkforward import allocation, rolling_split


def test_rolling_split_trains_before_the_threshold_year_and_tests_the_next() -> None:
    frame = pd.DataFrame(
        {
            "event_date": [
                date(2008, 3, 1),
                date(2008, 12, 20),
                date(2009, 6, 1),
                date(2010, 2, 1),
            ],
            "horizon_end_date": [
                date(2008, 4, 1),
                date(2009, 1, 20),
                date(2009, 7, 1),
                date(2010, 3, 1),
            ],
            "supervised_eligible": [True, True, True, True],
            "y_revert_success": [1.0, 0.0, 1.0, 0.0],
        }
    )
    train, threshold, test = rolling_split(frame, 2010)
    assert list(train["event_date"]) == [date(2008, 3, 1)]
    assert list(threshold["event_date"]) == [date(2009, 6, 1)]
    assert list(test["event_date"]) == [date(2010, 2, 1)]


def test_allocation_keeps_unknown_executions_out_of_the_mean() -> None:
    selected = pd.Series([True, True, False])
    status = pd.Series(["COMPLETE", "UNPRICED", "COMPLETE"])
    net = pd.Series([0.01, None, 0.05])
    values = allocation(selected, status, net)
    assert values.iloc[0] == 0.01 and np.isnan(values.iloc[1]) and values.iloc[2] == 0.0

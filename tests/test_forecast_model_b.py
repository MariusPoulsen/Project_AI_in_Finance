from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from structural_break.forecast import model_b as pb


def _frame(years: range = range(2006, 2012), per_year: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for year in years:
        days = pd.to_datetime(f"{year}-01-02") + pd.to_timedelta(
            np.sort(rng.integers(0, 360, per_year)), unit="D"
        )
        for number, day in enumerate(days):
            signal = rng.normal()
            rows.append(
                {
                    "event_id": f"e{year}-{number}",
                    "event_date": day.date(),
                    "horizon_end_date": (day + pd.Timedelta(days=28)).date(),
                    "supervised_eligible": True,
                    "f1": signal,
                    "f2": rng.normal(),
                    pb.TARGET: float(rng.random() < 1 / (1 + np.exp(-(signal * 2 - 1)))),
                    "frozen|status": "COMPLETE",
                    "frozen|net": signal * 1e-3,
                }
            )
    return pd.DataFrame(rows)


def test_purged_kfold_removes_overlap_and_embargo() -> None:
    train = _frame(range(2006, 2010)).reset_index(drop=True)
    signal = pd.to_datetime(train["event_date"])
    end = pd.to_datetime(train["horizon_end_date"])
    folds = pb.purged_kfold(train, 4)
    assert len(folds) == 4
    for fit, valid in folds:
        start, stop = signal.iloc[valid].min(), end.iloc[valid].max()
        assert not set(fit) & set(valid)
        overlap = (signal.iloc[fit] <= stop) & (end.iloc[fit] >= start)
        assert not overlap.any()
        embargoed = (signal.iloc[fit] > stop) & (signal.iloc[fit] <= stop + pb.EMBARGO)
        assert not embargoed.any()


def test_rolling_split_matches_decision_45() -> None:
    frame = _frame()
    train, threshold_rows, test = pb.rolling_split(frame, 2010)
    assert pd.to_datetime(train["horizon_end_date"]).max() < pd.Timestamp(2009, 1, 1)
    assert set(pd.to_datetime(threshold_rows["event_date"]).dt.year) == {2009}
    assert set(pd.to_datetime(test["event_date"]).dt.year) == {2010}


def test_log_loss() -> None:
    assert pb.log_loss(np.array([1.0]), np.array([0.5])) == pytest.approx(np.log(2))


def test_selection_threshold_comes_from_prior_year() -> None:
    scored = pd.DataFrame(
        {
            "year": 2011,
            "role": ["threshold"] * 10 + ["test"] * 4,
            "score": [*np.linspace(0, 0.9, 10), 0.95, 0.5, 0.75, 0.8],
        }
    )
    chosen = pb.selections(scored)
    assert chosen.tolist() == [False] * 10 + [True, False, True, True]
    alloc = pb.allocation(
        pd.Series([True, True, False]),
        pd.Series(["COMPLETE", "NO_FILL", "COMPLETE"]),
        pd.Series([0.01, 0.02, 0.03]),
    )
    assert alloc.iloc[0] == 0.01 and np.isnan(alloc.iloc[1]) and alloc.iloc[2] == 0.0

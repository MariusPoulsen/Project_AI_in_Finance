from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from structural_break.experiments import p6_boosting as pb


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


def test_forward_folds_purge_label_windows_and_use_last_years() -> None:
    train, _, _ = pb.rolling_split(_frame(), 2011)
    train = train.reset_index(drop=True)
    folds = pb.forward_folds(train)
    signal_years = pd.to_datetime(train["event_date"]).dt.year
    assert [int(signal_years.iloc[valid].unique()[0]) for _, valid in folds] == [2007, 2008, 2009]
    for fit, valid in folds:
        start = pd.to_datetime(train["event_date"]).iloc[valid].min()
        assert pd.to_datetime(train["horizon_end_date"]).iloc[fit].max() < start


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


def test_scores_and_corrections() -> None:
    labels = np.array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0])
    scores = np.array([0.9, 0.8, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1, 0.1])
    assert pb.top_share_precision(labels, scores) == 0.5
    assert pb.log_loss(np.array([1.0]), np.array([0.5])) == pytest.approx(np.log(2))
    adjusted = pb.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == {"a": 0.03, "c": 0.06, "b": 0.06}
    result = pb.bootstrap(np.ones(24), np.repeat(["2010-01", "2010-02"], 12))
    assert result["estimate"] == 1.0 and result["p_one_sided"] == 0.0


@pytest.mark.parametrize("family", ["xgboost", "lightgbm", "catboost"])
def test_tune_runs_for_each_family(family: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pb, "MAX_TREES", 30)
    monkeypatch.setattr(pb, "PATIENCE", 5)
    train, _, _ = pb.rolling_split(_frame(), 2011)
    train = train.reset_index(drop=True)
    x, y = train[["f1", "f2"]], train[pb.TARGET].astype(int)
    result = pb.tune(family, "logloss", x, y, pb.forward_folds(train), trials=2)
    assert 1 <= result["trees"] <= 30
    assert len(result["trials"]) == 2
    assert result["inner_score"] > 0


def test_run_task_reference_and_tuned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pb, "MAX_TREES", 20)
    monkeypatch.setattr(pb, "PATIENCE", 5)
    frame = _frame()
    columns = {"A": ("f2",), "B": ("f1", "f2")}
    reference, meta = pb.run_task(frame, columns, pb.REFERENCE, "B", 2011)
    assert meta["trees"] == 400 and set(reference["role"]) == {"threshold", "test"}
    tuned, meta = pb.run_task(frame, columns, "V6_xgb_forward_precision", "B", 2011, trials=2)
    assert len(tuned) == len(reference) and meta["family"] == "xgboost"
    assert tuned["score"].between(0, 1).all()


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


def test_task_order_and_count() -> None:
    tasks = pb.all_tasks()
    assert len(tasks) == (1 + len(pb.TUNED)) * 2 * 14
    assert tasks[0][0] == "V4_catboost_forward" and tasks[-1][0] == pb.REFERENCE

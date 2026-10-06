"""Temporal engine checks use transparent fixed fits to isolate chronology."""

from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from structural_break.config.models import EconometricsConfig, ProjectConfig
from structural_break.data.market import session_schedule
from structural_break.econometrics import engine

DATA_ID = "synthetic-engine-v1"
CONFIG_HASH = "a" * 64
CREATED = datetime(2026, 10, 3, tzinfo=UTC)
BEGIN, END = date(2020, 1, 2), date(2020, 4, 30)


def _inputs(
    shocks: dict[date, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    schedule = session_schedule(BEGIN, END)
    shocks = shocks or {}
    records = []
    for ticker, side in (("KO", "y"), ("PEP", "x")):
        for row in schedule.to_dict("records"):
            day = row["trading_date"]
            records.append(
                {
                    "ticker": ticker,
                    "trading_date": day,
                    "adj_close": float(np.exp(4 + (shocks.get(day, 0) if side == "y" else 0))),
                    "data_available_at": row["data_available_at"],
                    "quality_flag": "OK",
                    "source_snapshot_id": f"price-{ticker}",
                    "sha256": ("b" if side == "y" else "c") * 64,
                    "data_snapshot_id": DATA_ID,
                }
            )
    pairs = pd.DataFrame([{"pair_id": "KO__PEP", "leg_a": "KO", "leg_b": "PEP"}])
    return pd.DataFrame(records), pairs


def _fit(
    window: pd.DataFrame,
    settings: EconometricsConfig,
    previous_beta: float | None = None,
) -> dict[str, Any]:
    estimable = len(window) >= settings.formation_days
    return {
        "estimable": estimable,
        "hard_data_failure": not estimable,
        "n_obs": len(window),
        "alpha": 0.0 if estimable else None,
        "beta": 1.0 if estimable else None,
        "spread_mean": 0.0 if estimable else None,
        "spread_std": 1.0 if estimable else None,
        "integration_flag": "I1_COMPATIBLE",
        "coint_pvalue": 0.01,
        "data_quality_reasons": [] if estimable else ["INSUFFICIENT_HISTORY"],
        "cointegration_alpha": settings.cointegration_alpha,
        "retire_after_invalid": settings.retire_after_invalid,
    }


@pytest.fixture
def settings(config: ProjectConfig) -> EconometricsConfig:
    # Short windows are for deterministic temporal unit checks; production uses504.
    return config.econometrics.model_copy(update={"formation_days": 20})


@pytest.fixture(autouse=True)
def transparent_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "estimate_window", _fit)


def _run(
    prices: pd.DataFrame,
    pairs: pd.DataFrame,
    settings: EconometricsConfig,
    *,
    end: date = END,
    created_at: datetime = CREATED,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return engine.build_relationship_history(
        prices,
        pairs,
        settings,
        data_snapshot_id=DATA_ID,
        config_hash=CONFIG_HASH,
        start=BEGIN,
        end=end,
        created_at=created_at,
    )


def test_month_end_snapshot_effective_next_actual_session(settings: EconometricsConfig) -> None:
    prices, pairs = _inputs()
    snapshots, daily, _ = _run(prices, pairs, settings)
    first = snapshots.iloc[0]
    assert first["estimation_date"] == date(2020, 1, 31)
    assert first["effective_start"] == date(2020, 2, 3)
    assert first["effective_start_at"] == pd.Timestamp("2020-02-03T14:30:00Z")
    assert first["estimation_timestamp"] == pd.Timestamp("2020-01-31T21:00:00Z")
    assert first["effective_end"] == date(2020, 3, 2)
    assert daily["trading_date"].min() == date(2020, 2, 3)
    joined = daily.merge(snapshots, on="relationship_snapshot_id", suffixes=("", "_fit"))
    assert joined["trading_date"].ge(joined["effective_start"]).all()
    assert joined["trading_date"].lt(joined["effective_end"]).all()
    assert joined["trading_date"].gt(joined["estimation_date"]).all()
    assert joined["window_end"].le(joined["estimation_date"]).all()


def test_partial_month_is_not_an_estimation_date(settings: EconometricsConfig) -> None:
    prices, pairs = _inputs()
    snapshots, _, _ = _run(prices, pairs, settings, end=date(2020, 3, 16))
    assert snapshots["estimation_date"].tolist() == [date(2020, 1, 31), date(2020, 2, 28)]


def test_daily_spread_scale_and_parameters_remain_frozen_for_signal_month(
    settings: EconometricsConfig,
) -> None:
    prices, pairs = _inputs({date(2020, 2, 3): 3, date(2020, 2, 20): -8})
    snapshots, daily, crossings = _run(prices, pairs, settings)
    february = daily.loc[daily["trading_date"].map(lambda day: day.month == 2)]
    assert february["relationship_snapshot_id"].nunique() == 1
    assert february["alpha"].eq(0).all() and february["beta"].eq(1).all()
    assert february["spread_mean"].eq(0).all() and february["spread_std"].eq(1).all()
    event = crossings.loc[crossings["event_date"].eq(date(2020, 2, 20))].iloc[0]
    assert event["z_score"] == pytest.approx(-8)
    assert event["source_price_snapshot_ids"] == ["price-KO", "price-PEP"]
    assert event["source_price_hashes"] == ["b" * 64, "c" * 64]
    assert event["config_hash"] == CONFIG_HASH
    assert snapshots["source_price_snapshot_ids"].map(lambda ids: len(ids) == 2).all()


def test_formation_uses_exactly504_valid_common_prices(
    config: ProjectConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule = session_schedule(date(2014, 1, 1), date(2016, 6, 30))
    prices, pairs = _inputs()
    prices = pd.concat(
        [
            schedule.assign(
                ticker=ticker,
                adj_close=float(np.exp(4)),
                quality_flag="OK",
                source_snapshot_id=f"price-{ticker}",
                sha256="b" * 64,
                data_snapshot_id=DATA_ID,
            )
            for ticker in ("KO", "PEP")
        ],
        ignore_index=True,
    )
    observed: list[pd.DataFrame] = []

    def capture(
        window: pd.DataFrame, settings: EconometricsConfig, previous_beta: Any = None
    ) -> Any:
        observed.append(window.copy())
        return _fit(window, settings, previous_beta)

    monkeypatch.setattr(engine, "estimate_window", capture)
    snapshots, daily, _ = engine.build_relationship_history(
        prices,
        pairs,
        config.econometrics,
        data_snapshot_id=DATA_ID,
        config_hash=CONFIG_HASH,
        start=date(2014, 1, 1),
        end=date(2016, 6, 30),
        created_at=CREATED,
    )
    adequate = snapshots.loc[snapshots["estimable"]]
    assert not adequate.empty and adequate["n_obs"].eq(504).all()
    assert snapshots.loc[~snapshots["estimable"], "n_obs"].lt(504).all()
    for window, snapshot in zip(observed, snapshots.to_dict("records"), strict=True):
        assert len(window) <= 504
        assert window["trading_date"].le(snapshot["estimation_date"]).all()
        assert window["y"].eq(4).all() and window["x"].eq(4).all()
    assert daily["trading_date"].min() > adequate["estimation_date"].min()


def test_source_permutation_and_creation_time_preserve_scientific_ids(
    settings: EconometricsConfig,
) -> None:
    prices, pairs = _inputs({date(2020, 2, 3): 3})
    baseline = _run(prices, pairs, settings)
    shuffled = _run(prices.sample(frac=1, random_state=14), pairs, settings)
    for left, right in zip(baseline, shuffled, strict=True):
        assert_frame_equal(left, right)
    recreated = _run(prices, pairs, settings, created_at=datetime(2027, 1, 1, tzinfo=UTC))
    assert baseline[0]["relationship_snapshot_id"].equals(recreated[0]["relationship_snapshot_id"])
    assert baseline[2]["crossing_id"].equals(recreated[2]["crossing_id"])


def test_future_price_changes_cannot_change_prior_outputs(settings: EconometricsConfig) -> None:
    prices, pairs = _inputs({date(2020, 2, 3): 3})
    cutoff = date(2020, 3, 16)
    baseline = _run(prices, pairs, settings)
    perturbed = prices.copy()
    perturbed.loc[perturbed["trading_date"].gt(cutoff), "adj_close"] *= 17
    altered = _run(perturbed, pairs, settings)
    assert_frame_equal(
        baseline[0].loc[baseline[0]["estimation_date"].le(cutoff)].reset_index(drop=True),
        altered[0].loc[altered[0]["estimation_date"].le(cutoff)].reset_index(drop=True),
    )
    for index, column in ((1, "trading_date"), (2, "event_date")):
        assert_frame_equal(
            baseline[index].loc[baseline[index][column].le(cutoff)].reset_index(drop=True),
            altered[index].loc[altered[index][column].le(cutoff)].reset_index(drop=True),
        )


def test_missing_session_has_no_daily_state_or_bridged_crossing(
    settings: EconometricsConfig,
) -> None:
    shocks = {
        date(2020, 2, 5): 3,
        date(2020, 2, 6): 3,
        date(2020, 2, 10): -3,
    }
    prices, pairs = _inputs(shocks)
    prices = prices.loc[~(prices["ticker"].eq("KO") & prices["trading_date"].eq(date(2020, 2, 4)))]
    _, daily, crossings = _run(prices, pairs, settings)
    assert date(2020, 2, 4) not in daily["trading_date"].tolist()
    after_gap = daily.loc[daily["trading_date"].eq(date(2020, 2, 5))].iloc[0]
    assert pd.isna(after_gap["previous_z_score"])
    assert pd.isna(after_gap["z_velocity_1d"])
    assert pd.isna(after_gap["days_since_zero_cross"])
    assert date(2020, 2, 5) not in crossings["event_date"].tolist()
    assert date(2020, 2, 10) in crossings["event_date"].tolist()
    assert crossings.loc[crossings["event_date"].eq(date(2020, 2, 10)), "direction"].iloc[0] == -1


def test_refit_recomputes_previous_score_and_velocity_using_same_new_fit(
    settings: EconometricsConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refit(window: pd.DataFrame, settings: EconometricsConfig, previous_beta: Any = None) -> Any:
        result = _fit(window, settings, previous_beta)
        result["alpha"] = -3.0 if window["trading_date"].max() >= date(2020, 2, 28) else 0.0
        return result

    monkeypatch.setattr(engine, "estimate_window", refit)
    prices, pairs = _inputs()
    _, daily, crossings = _run(prices, pairs, settings)
    new_fit_day = daily.loc[daily["trading_date"].eq(date(2020, 3, 2))].iloc[0]
    assert new_fit_day["z_score"] == 3
    assert new_fit_day["previous_z_score"] == 3
    assert new_fit_day["z_velocity_1d"] == 0
    assert crossings.empty


def test_latest_unusable_attempt_blocks_fallback_to_old_success(
    settings: EconometricsConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_month(
        window: pd.DataFrame, settings: EconometricsConfig, previous_beta: Any = None
    ) -> Any:
        result = _fit(window, settings, previous_beta)
        if window["trading_date"].max() == date(2020, 2, 28):
            result.update(
                estimable=False,
                alpha=None,
                beta=None,
                spread_mean=None,
                spread_std=None,
                data_quality_reasons=["DEGENERATE_SPREAD"],
            )
        return result

    monkeypatch.setattr(engine, "estimate_window", failed_month)
    prices, pairs = _inputs({date(2020, 3, 2): 3})
    snapshots, daily, crossings = _run(prices, pairs, settings)
    assert (
        snapshots.loc[snapshots["estimation_date"].eq(date(2020, 2, 28)), "pair_status"].iloc[0]
        == "WATCH"
    )
    assert not daily["trading_date"].map(lambda value: value.month == 3).any()
    assert not crossings["event_date"].map(lambda value: value.month == 3).any()
    assert daily["trading_date"].map(lambda value: value.month == 4).any()


def test_baseline0_keeps_estimable_failed_cointegration_crossings(
    settings: EconometricsConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid(
        window: pd.DataFrame, settings: EconometricsConfig, previous_beta: Any = None
    ) -> Any:
        result = _fit(window, settings, previous_beta)
        result["coint_pvalue"] = 0.9
        return result

    monkeypatch.setattr(engine, "estimate_window", invalid)
    prices, pairs = _inputs({date(2020, 2, 3): 3, date(2020, 3, 2): -3})
    snapshots, _, crossings = _run(prices, pairs, settings)
    assert snapshots["pair_status"].tolist()[:2] == ["WATCH", "RETIRED"]
    assert crossings["baseline0_eligible"].all()
    assert not crossings["baseline1_eligible"].any()


def test_manual_terminal_retirement_takes_effect_on_correct_day(
    settings: EconometricsConfig,
) -> None:
    prices, pairs = _inputs({date(2020, 2, 10): 3})
    pairs["active_to"] = date(2020, 2, 7)
    _, daily, crossings = _run(prices, pairs, settings)
    assert daily.loc[daily["trading_date"].eq(date(2020, 2, 7)), "pair_status"].iloc[0] == "ACTIVE"
    assert (
        daily.loc[daily["trading_date"].eq(date(2020, 2, 10)), "pair_status"].iloc[0] == "RETIRED"
    )
    assert crossings.loc[crossings["event_date"].eq(date(2020, 2, 10)), "baseline0_eligible"].iloc[
        0
    ]
    assert not crossings.loc[
        crossings["event_date"].eq(date(2020, 2, 10)), "baseline1_eligible"
    ].iloc[0]


def test_zero_touch_is_not_a_sign_reversal(settings: EconometricsConfig) -> None:
    prices, pairs = _inputs(
        {
            date(2020, 2, 3): 1,
            date(2020, 2, 5): 1,
            date(2020, 2, 7): -1,
        }
    )
    _, daily, _ = _run(prices, pairs, settings)
    same_side = daily.loc[daily["trading_date"].eq(date(2020, 2, 5))].iloc[0]
    other_side = daily.loc[daily["trading_date"].eq(date(2020, 2, 7))].iloc[0]
    assert same_side["zero_crossings_252d"] == 0
    assert pd.isna(same_side["days_since_zero_cross"])
    assert other_side["zero_crossings_252d"] == 1
    assert other_side["days_since_zero_cross"] == 0


def test_undated_manual_terminal_flag_cannot_retroactively_retire_history(
    settings: EconometricsConfig,
) -> None:
    prices, pairs = _inputs()
    pairs["manual_terminal"] = True
    with pytest.raises(ValueError, match="effective date"):
        _run(prices, pairs, settings)
    pairs["active_to"] = date(2020, 2, 7)
    _, daily, _ = _run(prices, pairs, settings)
    assert daily.loc[daily["trading_date"].eq(date(2020, 2, 7)), "pair_status"].iloc[0] == "ACTIVE"
    assert (
        daily.loc[daily["trading_date"].eq(date(2020, 2, 10)), "pair_status"].iloc[0] == "RETIRED"
    )


def test_missing_estimation_day_uses_prior_valid_common_observations(
    settings: EconometricsConfig,
) -> None:
    prices, pairs = _inputs()
    prices = prices.loc[~prices["trading_date"].eq(date(2020, 2, 28))]
    snapshots, daily, _ = _run(prices, pairs, settings)
    february = snapshots.loc[snapshots["estimation_date"].eq(date(2020, 2, 28))].iloc[0]
    assert february["window_end"] == date(2020, 2, 27)
    assert february["n_obs"] == 20
    assert pd.isna(
        daily.loc[daily["trading_date"].eq(date(2020, 3, 2)), "previous_z_score"].iloc[0]
    )


def test_zero_volume_warning_preserves_estimable_price_window(settings: EconometricsConfig) -> None:
    prices, pairs = _inputs()
    prices["quality_flag"] = "ZERO_VOLUME"
    snapshots, daily, _ = _run(prices, pairs, settings)
    assert snapshots["estimable"].all() and not daily.empty


@pytest.mark.parametrize("invalid", ["nonpositive", "nonfinite", "flagged"])
def test_invalid_price_is_excluded_without_fill(
    settings: EconometricsConfig,
    invalid: str,
) -> None:
    prices, pairs = _inputs({date(2020, 2, 5): 3})
    target = prices["ticker"].eq("KO") & prices["trading_date"].eq(date(2020, 2, 4))
    if invalid == "nonpositive":
        prices.loc[target, "adj_close"] = 0
    elif invalid == "nonfinite":
        prices.loc[target, "adj_close"] = np.inf
    else:
        prices.loc[target, "quality_flag"] = "OHLC_INCONSISTENT"
    _, daily, crossings = _run(prices, pairs, settings)
    assert date(2020, 2, 4) not in daily["trading_date"].tolist()
    assert date(2020, 2, 5) not in crossings["event_date"].tolist()


def test_unexpected_estimation_failure_preserves_pair_and_date(
    settings: EconometricsConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("numerical routine failed")

    monkeypatch.setattr(engine, "estimate_window", fail)
    prices, pairs = _inputs()
    with pytest.raises(engine.RelationshipEstimationError) as captured:
        _run(prices, pairs, settings)
    assert captured.value.pair_id == "KO__PEP"
    assert captured.value.estimation_date == date(2020, 1, 31)
    assert DATA_ID in str(captured.value) and CONFIG_HASH in str(captured.value)


@pytest.mark.parametrize("mutation", ["duplicate", "orientation", "lineage", "naive", "late"])
def test_bad_identity_calendar_or_availability_rejected(
    settings: EconometricsConfig,
    mutation: str,
) -> None:
    prices, pairs = _inputs()
    if mutation == "duplicate":
        prices = pd.concat([prices, prices.iloc[[0]]], ignore_index=True)
    elif mutation == "orientation":
        pairs["orientation"] = "leg_b_is_y"
    elif mutation == "lineage":
        prices.loc[0, "data_snapshot_id"] = "other-source"
    elif mutation == "naive":
        prices["data_available_at"] = pd.to_datetime(prices["data_available_at"]).dt.tz_localize(
            None
        )
    else:
        prices["data_available_at"] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError):
        _run(prices, pairs, settings)

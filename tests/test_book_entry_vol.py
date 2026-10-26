from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from structural_break.book import entry_vol as ev


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 400
    dates = pd.to_datetime("2009-01-02") + pd.to_timedelta(rng.integers(0, 720, n), unit="D")
    return pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "event_date": dates,
            "abnormal_return_A_1d": rng.normal(0, 0.02, n),
            "abnormal_return_B_1d": rng.normal(0, 0.02, n),
            "volume_z_A_20": rng.normal(size=n),
            "volume_z_B_20": rng.normal(size=n),
            "market_return_1d": rng.normal(0, 0.01, n),
            "sector_return_1d": rng.normal(0, 0.01, n),
            "adverse_z_velocity_1d": rng.random(n),
            "spread_vol_ratio_20_60": rng.uniform(0.5, 1.8, n),
            "vix_level": rng.uniform(10, 40, n),
            "spread_vol_20": rng.uniform(0.005, 0.05, n),
            "market_rv20": rng.uniform(0.05, 0.5, n),
            "frozen_status": "COMPLETE",
            "exit|status": "COMPLETE",
            "exit|net": rng.normal(0, 0.01, n),
        }
    )


def test_thresholds_use_only_the_prior_year() -> None:
    frame = _frame()
    values = pd.Series(np.where(pd.to_datetime(frame["event_date"]).dt.year == 2009, 1.0, 100.0))
    reference = ev.prior_year_quantile(frame, values, 0.5)
    year = pd.to_datetime(frame["event_date"]).dt.year
    assert reference[year == 2009].isna().all()
    assert (reference[year == 2010] == 1.0).all()


def test_filters_and_sizing_contrasts() -> None:
    frame = ev.derived(_frame())
    for name, rule in ev.SIZING.items():
        frame["weight_" + name] = ev.normalised(frame, rule(frame))
    data = ev.population(frame, None, (2010, 2010))
    assert len(data) > 50
    for name in ev.FILTERS:
        result = ev.contrast(data, "filter", name)
        skip = ev.FILTERS[name](data).fillna(False)
        expected = -(data["exit|net"] * skip).mean()
        assert result["estimate"] == pytest.approx(expected)
    for name in ev.SIZING:
        result = ev.contrast(data, "sizing", name)
        weights = data["weight_" + name]
        assert weights.between(0.0, 10.0).all()
        assert result["estimate"] == pytest.approx(((weights - 1) * data["exit|net"]).mean())


def test_one_sided_volume_rule_uses_the_mover() -> None:
    frame = pd.DataFrame(
        {
            "abnormal_return_A_1d": [0.05, 0.01],
            "abnormal_return_B_1d": [0.01, -0.06],
            "volume_z_A_20": [2.5, 2.5],
            "volume_z_B_20": [0.2, 0.2],
        }
    )
    a, b = frame["abnormal_return_A_1d"], frame["abnormal_return_B_1d"]
    mover_a = a.abs() >= b.abs()
    frame["mover_volume_z"] = np.where(mover_a, frame["volume_z_A_20"], frame["volume_z_B_20"])
    frame["other_volume_z"] = np.where(mover_a, frame["volume_z_B_20"], frame["volume_z_A_20"])
    assert ev.FILTERS["F1_one_sided_volume_shock"](frame).tolist() == [True, False]

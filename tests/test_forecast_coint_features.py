from __future__ import annotations

import numpy as np
import pandas as pd

from structural_break.econometrics import alternatives as alt
from structural_break.forecast import coint_features as pc


def _pair(n: int = 504, beta: float = 1.3, rho: float = 0.9, seed: int = 1) -> tuple:
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, 0.01, n)) + 4.0
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = rho * spread[t - 1] + rng.normal(0, 0.01)
    return 0.2 + beta * x + spread, x


def test_cointegrated_pair_is_recognised() -> None:
    y, x = _pair()
    stats = alt.window_statistics(y, x)
    assert abs(stats["ols_beta"] - 1.3) < 0.1
    assert stats["ci_johansen_trace_ratio"] > 1.0
    assert stats["ci_eg_max_pvalue"] < 0.05
    assert abs(stats["tls_beta"] - 1.3) < 0.15
    assert abs(stats["minadf_beta"] - 1.3) < 0.2
    assert stats["ci_minhl_halflife"] < 15
    assert stats["ci_hurst"] < 0.5
    assert stats["ci_kpss"] < 0.463


def test_random_walks_are_not_cointegrated() -> None:
    rng = np.random.default_rng(7)
    y = np.cumsum(rng.normal(0, 0.01, 504))
    x = np.cumsum(rng.normal(0, 0.01, 504))
    stats = alt.window_statistics(y + 3, x + 3)
    assert stats["ci_eg_max_pvalue"] > 0.05
    assert stats["ci_johansen_trace_ratio"] < 1.0


def test_adf_and_half_life_basics() -> None:
    rng = np.random.default_rng(3)
    noise = rng.normal(size=400)
    assert alt.adf_t(noise) < -10
    assert alt.half_life(1.02 ** np.arange(400.0)) == np.inf
    ar = np.zeros(400)
    for t in range(1, 400):
        ar[t] = 0.5 * ar[t - 1] + noise[t]
    assert 0.5 < alt.half_life(ar) < 2.0


def test_kalman_tracks_beta_without_lookahead() -> None:
    y, x = _pair(n=800, rho=0.5)
    betas, z = alt.kalman_path(y, x)
    assert abs(betas[-1] - 1.3) < 0.3
    altered = y.copy()
    altered[600:] += 0.5
    later_betas, later_z = alt.kalman_path(altered, x)
    np.testing.assert_allclose(betas[:600], later_betas[:600])
    np.testing.assert_allclose(z[:600], later_z[:600], equal_nan=True)
    assert np.isnan(z[: alt.KALMAN_Z_WINDOW]).all()


def test_pair_features_use_window_before_relationship_date() -> None:
    y, x = _pair(n=700)
    dates = pd.bdate_range("2010-01-01", periods=700).date
    history = pd.DataFrame({"trading_date": dates, "y": y, "x": x})
    available = pd.Timestamp(dates[600], tz="UTC") + pd.Timedelta(hours=13.5)
    alpha, beta = alt.ols_beta(y[96:600], x[96:600])
    events = pd.DataFrame(
        {
            "event_id": ["e1"],
            "event_date": [dates[610]],
            "entry_z": [-2.1],
            "alpha": [alpha],
            "beta": [beta],
            "relationship_available_at": [available],
        }
    )
    (row,) = pc.pair_features(history, events)
    assert abs(row["ols_beta_check"]) < 1e-12 and abs(row["ols_alpha_check"]) < 1e-12
    assert set(pc.FEATURES) <= set(row)
    assert -3.0 <= row["ci_beta_gap_minadf"] <= 3.0


def test_gate_contrast_withholds_to_zero() -> None:
    frame = pd.DataFrame(
        {
            "event_date": pd.to_datetime(["2007-01-05", "2007-02-05", "2007-03-05", "2007-03-06"]),
            "frozen|status": ["COMPLETE"] * 4,
            "frozen|net": [0.01, -0.02, 0.03, -0.01],
            "ci_kpss": [0.1, 0.9, 0.2, 0.8],
            pc.TARGET: [1.0, 0.0, 1.0, np.nan],
            "baseline1_eligible": [True, False, True, True],
        }
    )
    result = pc.gate_contrast(frame, "G3_kpss_stationary", (2006, 2015))
    assert np.isclose(result["estimate"], (0.02 + 0.01) / 4)
    assert result["kept_share"] == 0.5
    reference = pc.gate_contrast(frame, pc.REFERENCE_GATE, (2006, 2015))
    assert np.isclose(reference["estimate"], 0.02 / 4)

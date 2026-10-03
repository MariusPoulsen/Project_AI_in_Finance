"""Statistical validity, numerical failures and prescribed lifecycle rules."""

from typing import Any

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.stattools import coint

from structural_break.config.models import EconometricsConfig
from structural_break.econometrics import statistics
from structural_break.econometrics.statistics import (
    EconometricsEstimationError,
    assign_pair_status,
    estimate_half_life,
    estimate_window,
)
from structural_break.econometrics.statistics import test_integration_order as integration_order


@pytest.fixture
def settings() -> EconometricsConfig:
    return EconometricsConfig(
        version="test-econometrics-v1",
        formation_days=504,
        refit="monthly",
        cointegration_alpha=0.05,
        entry_z=2.0,
        success_z=0.5,
        adverse_z=3.0,
        horizon_days=10,
    )


def _window(seed: int = 42, independent: bool = False) -> pd.DataFrame:
    generator = np.random.default_rng(seed)
    x = 4.0 + np.cumsum(generator.normal(0.0004, 0.015, 504))
    if independent:
        y = 4.5 + np.cumsum(generator.normal(0.0001, 0.02, 504))
    else:
        noise = generator.normal(0, 0.008, 504)
        error = np.zeros(504)
        for index in range(1, 504):
            error[index] = 0.65 * error[index - 1] + noise[index]
        y = 0.3 + 1.25 * x + error
    frame = pd.DataFrame(
        {"trading_date": pd.bdate_range("2016-01-01", periods=504), "y": y, "x": x}
    )
    frame["dy"] = frame["y"].diff()
    frame["dx"] = frame["x"].diff()
    return frame


def test_cointegrated_synthetic_fixture_and_mackinnon_outputs(settings: EconometricsConfig) -> None:
    window = _window()
    result = estimate_window(window, settings)
    expected = coint(window.y, window.x, trend="c", method="aeg", autolag="aic")
    assert result["estimable"]
    assert result["coint_pvalue"] < 0.05
    assert result["coint_tstat"] == pytest.approx(expected[0])
    assert result["coint_pvalue"] == pytest.approx(expected[1])
    assert result["coint_crit_5pct"] == pytest.approx(expected[2][1])
    assert result["beta"] == pytest.approx(1.25, abs=0.05)
    assert result["cointegration_vector"] == [1.0, -result["beta"]]
    assert result["spread_mean"] == pytest.approx(0, abs=1e-12)
    residual = window.y - result["alpha"] - result["beta"] * window.x
    assert result["spread_std"] == pytest.approx(residual.std(ddof=1))
    assert result["n_obs"] == 504
    assert result["y_n_diff_obs"] == 503
    assert result["half_life_valid"]
    assert result["half_life_days"] > 0
    assert result["formation_z_range"] > 0
    assert result["zero_crossings_252d"] > 0


def test_independent_walks_usually_fail_cointegration(settings: EconometricsConfig) -> None:
    # Fixed multiple replications test statistical behaviour without relying on one lucky seed.
    rejected = [
        estimate_window(_window(seed, independent=True), settings)["coint_pvalue"] < 0.05
        for seed in range(100, 120)
    ]
    assert sum(rejected) < 6


def test_preferred_i1_and_stationary_i0_series(settings: EconometricsConfig) -> None:
    walk = integration_order(_window().x, settings)
    assert walk["integration_flag"] == "I1_COMPATIBLE"
    stationary = pd.Series(np.random.default_rng(18).normal(size=504))
    assert integration_order(stationary, settings)["integration_flag"] == "I0"


@pytest.mark.parametrize(
    ("adf_level", "kpss_level", "adf_diff", "expected"),
    [
        (0.5, 0.01, 0.001, "I1_COMPATIBLE"),
        (0.5, 0.01, 0.5, "NOT_I1"),
        (0.001, 0.1, 0.001, "I0"),
        (0.001, 0.01, 0.001, "AMBIGUOUS"),
        (0.5, 0.1, 0.001, "AMBIGUOUS"),
    ],
)
def test_integration_rules_and_difference_kpss_is_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    settings: EconometricsConfig,
    adf_level: float,
    kpss_level: float,
    adf_diff: float,
    expected: str,
) -> None:
    adf_values = iter((adf_level, adf_diff))
    kpss_values = iter((kpss_level, 0.01))  # Difference KPSS disagreement is not an extra gate.
    critical = {"1%": -3.5, "5%": -2.9, "10%": -2.6}
    monkeypatch.setattr(
        statistics,
        "adfuller",
        lambda *args, **kwargs: (-2.0, next(adf_values), 2, 500, critical, 0.0),
    )
    monkeypatch.setattr(
        statistics, "kpss", lambda *args, **kwargs: (0.5, next(kpss_values), 3, critical)
    )
    result = integration_order(_window().x, settings)
    assert result["integration_flag"] == expected
    assert "KPSS_DIFFERENCE_REJECTS_STATIONARITY" in result["warning_flags"]


def test_orientation_is_not_searched(settings: EconometricsConfig) -> None:
    original = _window()
    direct = estimate_window(original, settings)
    reversed_window = original.rename(columns={"y": "x", "x": "y", "dy": "dx", "dx": "dy"})
    reversed_result = estimate_window(reversed_window, settings)
    expected_beta = np.cov(original.x, original.y, ddof=1)[0, 1] / original.x.var(ddof=1)
    assert direct["beta"] == pytest.approx(expected_beta)
    assert reversed_result["beta"] != pytest.approx(direct["beta"])
    assert reversed_result["coint_tstat"] != direct["coint_tstat"]


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("short", "INCOMPLETE_FORMATION_WINDOW"),
        ("missing", "MISSING_FORMATION_COLUMNS"),
        ("duplicate_date", "INVALID_FORMATION_DATES"),
        ("reverse_dates", "INVALID_FORMATION_DATES"),
        ("nan", "INVALID_LOG_LEVELS"),
        ("infinity", "INVALID_LOG_LEVELS"),
        ("constant", "NEAR_CONSTANT_LOG_LEVEL"),
        ("near_constant", "NEAR_CONSTANT_LOG_LEVEL"),
        ("perfect", "DEGENERATE_SPREAD_SCALE"),
    ],
)
def test_unusable_windows_return_explicit_audit_rows(
    settings: EconometricsConfig,
    case: str,
    reason: str,
) -> None:
    window = _window()
    if case == "short":
        window = window.iloc[:-1]
    elif case == "missing":
        window = window.drop(columns="x")
    elif case == "duplicate_date":
        window.loc[1, "trading_date"] = window.loc[0, "trading_date"]
    elif case == "reverse_dates":
        window = window.iloc[::-1]
    elif case in ("nan", "infinity"):
        window.loc[4, "x"] = np.nan if case == "nan" else np.inf
    elif case == "constant":
        window["x"] = 4.0
    elif case == "near_constant":
        window["x"] = 4.0 + np.arange(504) * 1e-14
    elif case == "perfect":
        window["y"] = 0.3 + 1.25 * window.x
    result = estimate_window(window, settings)
    assert not result["estimable"]
    assert result["hard_data_failure"]
    assert reason in result["data_quality_reasons"]
    assert assign_pair_status(result)["pair_status"] == "WATCH"


def test_degenerate_integration_differences_are_not_forced(settings: EconometricsConfig) -> None:
    result = integration_order(pd.Series(np.arange(504, dtype=float)), settings)
    assert result["integration_flag"] == "NOT_I1"
    assert not result["diagnostics_valid"]
    assert result["adf_diff_p"] is None


@pytest.mark.parametrize(
    ("rho", "flag"), [(0.8, "VALID"), (-0.6, "OSCILLATORY"), (1.005, "NON_MEAN_REVERTING")]
)
def test_half_life_regimes(settings: EconometricsConfig, rho: float, flag: str) -> None:
    spread = pd.Series(rho ** np.arange(504))
    result = estimate_half_life(spread, settings)
    assert result["ar1_rho"] == pytest.approx(rho)
    assert result["error_correction_phi"] == pytest.approx(rho - 1)
    assert result["half_life_flag"] == flag
    if rho == 0.8:
        assert result["half_life_days"] == pytest.approx(-np.log(2) / np.log(rho))
        assert result["half_life_valid"]
    else:
        assert result["half_life_days"] is None
        assert not result["half_life_valid"]


def test_missing_returns_do_not_bridge_a_gap(settings: EconometricsConfig) -> None:
    window = _window()
    window.loc[len(window) - 5, ["dy", "dx"]] = np.nan
    result = estimate_window(window, settings, previous_beta=1.0)
    assert result["corr_20d"] is None
    assert result["corr_60d"] is None
    assert result["beta_drift_pct"] == pytest.approx(abs(result["beta"] - 1.0))
    assert "RETURN_CORRELATION_20D_UNAVAILABLE" in result["warning_flags"]


def test_near_collinearity_warning_keeps_infinity_out_of_json(settings: EconometricsConfig) -> None:
    window = _window()
    window["y"] = 0.3 + 1.25 * window.x + np.random.default_rng(8).normal(0, 1e-7, 504)
    result = estimate_window(window, settings)
    assert result["estimable"]
    assert result["coint_tstat"] is None
    assert result["coint_tstat_is_infinite"]
    assert "PERFECT_OR_NEAR_PERFECT_COLLINEARITY" in result["warning_flags"]
    assert result["coint_pvalue"] == 0


def test_unexpected_statistical_failure_is_raised(
    monkeypatch: pytest.MonkeyPatch,
    settings: EconometricsConfig,
) -> None:
    def failed_test(*args: Any, **kwargs: Any) -> None:
        raise ValueError("synthetic numerical failure")

    monkeypatch.setattr(statistics, "coint", failed_test)
    with pytest.raises(EconometricsEstimationError, match="ENGLE_GRANGER failed"):
        estimate_window(_window(), settings)


def _eligible() -> dict[str, Any]:
    return {
        "estimable": True,
        "hard_data_failure": False,
        "integration_flag": "I1_COMPATIBLE",
        "coint_pvalue": 0.01,
        "cointegration_alpha": 0.05,
        "retire_after_invalid": 2,
    }


def test_lifecycle_invalid_persistence_and_recovery() -> None:
    invalid = {**_eligible(), "coint_pvalue": 0.3}
    first = assign_pair_status(invalid)
    assert first["pair_status"] == "WATCH"
    assert first["consecutive_invalid_snapshots"] == 1
    second = assign_pair_status(invalid, prior_invalid=1, prior_age=5)
    assert second["pair_status"] == "RETIRED"
    assert second["relationship_age_months"] == 0
    recovered = assign_pair_status(_eligible(), prior_invalid=2)
    assert recovered["pair_status"] == "ACTIVE"
    assert recovered["consecutive_invalid_snapshots"] == 0
    assert recovered["relationship_age_months"] == 1
    assert assign_pair_status(_eligible(), prior_age=3)["relationship_age_months"] == 4


@pytest.mark.parametrize("integration", ["AMBIGUOUS", "I0", "NOT_I1"])
def test_non_i1_never_active(integration: str) -> None:
    result = assign_pair_status({**_eligible(), "integration_flag": integration})
    assert result["pair_status"] == "WATCH"


def test_half_life_and_soft_stability_do_not_add_activity_gates() -> None:
    result = {
        **_eligible(),
        "half_life_valid": False,
        "half_life_days": None,
        "half_life_flag": "NON_MEAN_REVERTING",
        "beta_drift_pct": 9.0,
        "spread_vol_ratio": 20.0,
        "warning_flags": ["SOFT_STABILITY_WARNING"],
    }
    assert assign_pair_status(result)["pair_status"] == "ACTIVE"


def test_exact_significance_boundary_is_invalid_and_manual_terminal_retires() -> None:
    assert assign_pair_status({**_eligible(), "coint_pvalue": 0.05})["pair_status"] == "WATCH"
    assert assign_pair_status({**_eligible(), "coint_pvalue": np.nan})["pair_status"] == "WATCH"
    terminal = assign_pair_status(_eligible(), manual_terminal=True)
    assert terminal["pair_status"] == "RETIRED"
    assert terminal["status_reason"] == ["MANUAL_TERMINAL"]


def test_zero_touches_are_not_double_counted() -> None:
    frame = pd.DataFrame({"session_index": np.arange(7)})
    assert statistics._crossing_metrics(
        frame, np.array([1.0, 0.0, 0.0, -1.0, -1.0, 0.0, 1.0]), []
    ) == (2, 0)
    assert statistics._crossing_metrics(frame.iloc[:3], np.array([1.0, 0.0, 1.0]), []) == (0, None)


def test_monthly_crossing_statistics_never_bridge_a_gap() -> None:
    frame = pd.DataFrame({"session_index": [0, 1, 2, 4, 5, 6, 7]})
    spread = np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0, 1.0])
    recorded: list[str] = []
    assert statistics._crossing_metrics(frame, spread, recorded) == (1, 0)
    assert "FORMATION_GAP_CROSSING_COVERAGE_INCOMPLETE" in recorded
    assert statistics._crossing_metrics(frame.iloc[:-1], spread[:-1], []) == (0, None)
    # The 252-session lookback uses actual calendar offsets rather than common-row offsets.
    frame = pd.DataFrame({"session_index": [0, 1, 400, 401]})
    assert statistics._crossing_metrics(frame, np.array([1.0, -1.0, -1.0, -1.0]), []) == (0, None)

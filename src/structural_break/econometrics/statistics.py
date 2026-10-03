"""Deterministic, fixed-orientation relationship statistics without storage or retrieval."""

import warnings
from collections.abc import Callable
from functools import partial
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from statsmodels.regression.linear_model import OLS
from statsmodels.tsa.stattools import adfuller, coint, kpss

from structural_break.config.models import EconometricsConfig

FloatArray = NDArray[np.float64]


class EconometricsEstimationError(RuntimeError):
    """An unexpected statistical failure; callers must fail and record the batch."""


def _statistic(label: str, operation: Callable[[], Any]) -> tuple[Any, list[str]]:
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            value = operation()
        recorded = [f"{label}:{item.category.__name__}:{item.message}" for item in captured]
        return value, recorded
    except Exception as exc:
        raise EconometricsEstimationError(f"{label} failed ({type(exc).__name__}): {exc}") from exc


def _degenerate(values: FloatArray, epsilon: float) -> bool:
    scale = max(1.0, float(np.max(np.abs(values))))
    return float(np.std(values, ddof=1)) <= epsilon * scale


def _blank_integration(reason: str, n_obs: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "integration_flag": "NOT_I1",
        "diagnostics_valid": False,
        "n_obs": n_obs,
        "n_diff_obs": max(0, n_obs - 1),
        "warning_flags": [reason],
    }
    for name in ("adf_level", "adf_diff", "kpss_level", "kpss_diff"):
        for field in ("stat", "p", "lags", "crit_1pct", "crit_5pct", "crit_10pct"):
            result[f"{name}_{field}"] = None
    result["adf_level_nobs"] = None
    result["adf_diff_nobs"] = None
    return result


def test_integration_order(series: pd.Series, settings: EconometricsConfig) -> dict[str, Any]:
    """ADF/KPSS on a log level and its first differences under one global specification.

    KPSS difference results are retained as diagnostics. The preferred I(1) rule
    uses the three tests in the specification: ADF level, KPSS level and ADF difference.
    """
    try:
        values = series.to_numpy(dtype=np.float64)
    except (TypeError, ValueError):
        return _blank_integration("INVALID_NUMERIC_SERIES", len(series))
    if len(values) < 8 or not np.isfinite(values).all():
        return _blank_integration("INSUFFICIENT_OR_INVALID_SERIES", len(values))
    if _degenerate(values, settings.numerical_epsilon):
        return _blank_integration("NEAR_CONSTANT_LEVEL", len(values))
    differences = np.diff(values)
    if _degenerate(differences, settings.numerical_epsilon):
        return _blank_integration("NEAR_CONSTANT_DIFFERENCE", len(values))

    result: dict[str, Any] = {
        "n_obs": len(values),
        "n_diff_obs": len(differences),
        "diagnostics_valid": True,
        "warning_flags": [],
    }
    for suffix, sample in (("level", values), ("diff", differences)):
        adf, adf_warnings = _statistic(
            f"ADF_{suffix}",
            partial(adfuller, sample, regression=settings.test_trend, autolag=settings.eg_autolag),
        )
        kpss_result, kpss_warnings = _statistic(
            f"KPSS_{suffix}",
            partial(kpss, sample, regression=settings.test_trend, nlags=settings.kpss_nlags),
        )
        if not np.isfinite([adf[0], adf[1], kpss_result[0], kpss_result[1]]).all():
            raise EconometricsEstimationError(f"Integration {suffix} test produced invalid outputs")
        result[f"adf_{suffix}_stat"] = float(adf[0])
        result[f"adf_{suffix}_p"] = float(adf[1])
        result[f"adf_{suffix}_lags"] = int(adf[2])
        result[f"adf_{suffix}_nobs"] = int(adf[3])
        result[f"kpss_{suffix}_stat"] = float(kpss_result[0])
        result[f"kpss_{suffix}_p"] = float(kpss_result[1])
        result[f"kpss_{suffix}_lags"] = int(kpss_result[2])
        for label, output, critical_index in (("adf", adf, 4), ("kpss", kpss_result, 3)):
            for critical in (1, 5, 10):
                result[f"{label}_{suffix}_crit_{critical}pct"] = float(
                    output[critical_index][f"{critical}%"]
                )
        result["warning_flags"].extend(adf_warnings + kpss_warnings)

    alpha = settings.diagnostic_alpha
    adf_level_stationary = result["adf_level_p"] < alpha
    kpss_level_stationary = result["kpss_level_p"] >= alpha
    adf_difference_stationary = result["adf_diff_p"] < alpha
    if not adf_level_stationary and not kpss_level_stationary:
        flag = "I1_COMPATIBLE" if adf_difference_stationary else "NOT_I1"
    elif adf_level_stationary and kpss_level_stationary:
        flag = "I0"
    else:
        flag = "AMBIGUOUS"
    result["integration_flag"] = flag
    if result["kpss_diff_p"] < alpha:
        result["warning_flags"].append("KPSS_DIFFERENCE_REJECTS_STATIONARITY")
    return result


def estimate_half_life(spread: pd.Series, settings: EconometricsConfig) -> dict[str, Any]:
    """Fit AR(1) with an intercept; invalid decay regimes have a null half-life."""
    empty: dict[str, Any] = {
        "ar1_rho": None,
        "error_correction_phi": None,
        "half_life_days": None,
        "half_life_valid": False,
        "half_life_flag": "INVALID_SPREAD",
        "warning_flags": [],
    }
    try:
        values = spread.to_numpy(dtype=np.float64)
    except (TypeError, ValueError):
        return empty
    if len(values) < 3 or not np.isfinite(values).all():
        return empty
    if _degenerate(values[:-1], settings.numerical_epsilon):
        return {**empty, "half_life_flag": "DEGENERATE_SPREAD"}
    fitted, recorded = _statistic(
        "AR1",
        lambda: OLS(values[1:], np.column_stack((np.ones(len(values) - 1), values[:-1]))).fit(),
    )
    rho = float(fitted.params[1])
    if not np.isfinite(rho):
        raise EconometricsEstimationError("AR1 produced a non-finite coefficient")
    valid = 0 < rho < 1
    flag = "VALID" if valid else "NON_MEAN_REVERTING" if rho >= 1 else "OSCILLATORY"
    return {
        "ar1_rho": rho,
        "error_correction_phi": rho - 1,
        "half_life_days": float(-np.log(2) / np.log(rho)) if valid else None,
        "half_life_valid": valid,
        "half_life_flag": flag,
        "warning_flags": recorded,
    }


def _crossing_metrics(
    window: pd.DataFrame, spread: FloatArray, warnings_out: list[str]
) -> tuple[int, int | None]:
    """Do not bridge a missing session when counting crossings or their recency."""
    session_indices = (
        window["session_index"].to_numpy(dtype=np.int64)
        if "session_index" in window
        else np.arange(len(window))
    )
    adjacent = np.ones(len(window), dtype=bool)
    adjacent[0] = False
    adjacent[1:] = np.diff(session_indices) == 1
    if "dy" in window and "dx" in window:
        adjacent &= np.isfinite(window[["dy", "dx"]].to_numpy(dtype=np.float64)).all(axis=1)
    if not adjacent[1:].all():
        warnings_out.append("FORMATION_GAP_CROSSING_COVERAGE_INCOMPLETE")
        if "session_index" not in window:
            warnings_out.append("SESSION_INDEX_UNAVAILABLE")
    indices: list[int] = []
    last_sign = 0
    last_gap = 0
    for index, value in enumerate(spread):
        if not adjacent[index]:
            last_sign = 0
            last_gap = index
        sign = int(np.sign(value))
        if sign:
            if last_sign and sign != last_sign:
                indices.append(index)
            last_sign = sign
    recent_start = session_indices[-1] - 251
    crossing_count = int(sum(session_indices[index] >= recent_start for index in indices))
    recency = (
        int(session_indices[-1] - session_indices[indices[-1]])
        if indices and indices[-1] > last_gap
        else None
    )
    return crossing_count, recency


def _correlation(window: pd.DataFrame, days: int, warnings_out: list[str]) -> float | None:
    if "dy" not in window or "dx" not in window or len(window) < days:
        warnings_out.append(f"RETURN_CORRELATION_{days}D_UNAVAILABLE")
        return None
    returns = window[["dy", "dx"]].tail(days).to_numpy(dtype=np.float64)
    if not np.isfinite(returns).all() or np.any(np.std(returns, axis=0) == 0):
        warnings_out.append(f"RETURN_CORRELATION_{days}D_UNAVAILABLE")
        return None
    return float(np.corrcoef(returns[:, 0], returns[:, 1])[0, 1])


def _empty_window(settings: EconometricsConfig, n_obs: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "estimable": False,
        "hard_data_failure": True,
        "data_quality_reasons": [],
        "warning_flags": [],
        "n_obs": n_obs,
        "formation_window_days": settings.formation_days,
        "integration_flag": "NOT_I1",
        "integration_warning": True,
        "half_life_valid": False,
        "half_life_flag": "UNAVAILABLE",
        "coint_tstat_is_infinite": False,
        "cointegration_vector": None,
        "cointegration_alpha": settings.cointegration_alpha,
        "retire_after_invalid": settings.retire_after_invalid,
        "diagnostic_alpha": settings.diagnostic_alpha,
        "trend_spec": settings.test_trend,
        "autolag_spec": settings.eg_autolag,
        "kpss_nlags": settings.kpss_nlags,
    }
    for field in (
        "alpha",
        "beta",
        "spread_mean",
        "spread_std",
        "ols_rsquared",
        "coint_tstat",
        "coint_pvalue",
        "coint_crit_1pct",
        "coint_crit_5pct",
        "coint_crit_10pct",
        "ar1_rho",
        "error_correction_phi",
        "half_life_days",
        "corr_20d",
        "corr_60d",
        "beta_drift_pct",
        "spread_vol_20d",
        "spread_vol_ratio",
        "zero_crossings_252d",
        "days_since_zero_cross",
        "formation_z_range",
    ):
        result[field] = None
    for leg in ("y", "x"):
        result.update(
            {
                f"{leg}_{key}": value
                for key, value in _blank_integration("UNAVAILABLE", n_obs).items()
                if key != "warning_flags"
            }
        )
    return result


def estimate_window(
    window: pd.DataFrame,
    settings: EconometricsConfig,
    previous_beta: float | None = None,
) -> dict[str, Any]:
    """Estimate one already aligned formation window with leg A fixed as dependent y.

    Known unusable inputs return a nonestimable audit row. An unexpected OLS/test
    exception is raised so a caller cannot silently skip a difficult relationship.
    """
    result = _empty_window(settings, len(window))
    if len(window) != settings.formation_days:
        result["data_quality_reasons"] = ["INCOMPLETE_FORMATION_WINDOW"]
        return result
    if len(window) < 8:
        result["data_quality_reasons"] = ["INSUFFICIENT_STATISTICAL_OBSERVATIONS"]
        return result
    if not {"trading_date", "y", "x"}.issubset(window):
        result["data_quality_reasons"] = ["MISSING_FORMATION_COLUMNS"]
        return result
    dates = pd.to_datetime(window["trading_date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        result["data_quality_reasons"] = ["INVALID_FORMATION_DATES"]
        return result
    try:
        y = window["y"].to_numpy(dtype=np.float64)
        x = window["x"].to_numpy(dtype=np.float64)
    except (TypeError, ValueError):
        result["data_quality_reasons"] = ["INVALID_LOG_LEVELS"]
        return result
    if not np.isfinite(y).all() or not np.isfinite(x).all():
        result["data_quality_reasons"] = ["INVALID_LOG_LEVELS"]
        return result
    if _degenerate(y, settings.numerical_epsilon) or _degenerate(x, settings.numerical_epsilon):
        result["data_quality_reasons"] = ["NEAR_CONSTANT_LOG_LEVEL"]
        return result
    if previous_beta is not None and not np.isfinite(previous_beta):
        raise ValueError("previous_beta must be finite or None")

    fitted, recorded = _statistic(
        "OLS", lambda: OLS(y, np.column_stack((np.ones(len(x)), x))).fit()
    )
    alpha, beta = (float(value) for value in fitted.params)
    spread = y - alpha - beta * x
    spread_mean = float(np.mean(spread))
    spread_std = float(np.std(spread, ddof=1))
    result.update(
        alpha=alpha,
        beta=beta,
        spread_mean=spread_mean,
        spread_std=spread_std,
        ols_rsquared=float(fitted.rsquared),
        warning_flags=recorded,
    )
    if not np.isfinite([alpha, beta, spread_mean, spread_std]).all():
        raise EconometricsEstimationError("OLS produced non-finite relationship parameters")
    if spread_std <= settings.numerical_epsilon:
        result["data_quality_reasons"] = ["DEGENERATE_SPREAD_SCALE"]
        result["warning_flags"].append("PERFECT_OR_NEAR_PERFECT_COLLINEARITY")
        return result

    flags = []
    for leg, sample in (("y", y), ("x", x)):
        diagnostic = test_integration_order(pd.Series(sample), settings)
        flags.append(diagnostic["integration_flag"])
        result.update(
            {f"{leg}_{key}": value for key, value in diagnostic.items() if key != "warning_flags"}
        )
        result["warning_flags"].extend(f"{leg}:{item}" for item in diagnostic["warning_flags"])
    if "NOT_I1" in flags:
        integration_flag = "NOT_I1"
    elif "I0" in flags:
        integration_flag = "I0"
    elif "AMBIGUOUS" in flags:
        integration_flag = "AMBIGUOUS"
    else:
        integration_flag = "I1_COMPATIBLE"
    cointegration, coint_warnings = _statistic(
        "ENGLE_GRANGER",
        lambda: coint(
            y,
            x,
            trend=settings.test_trend,
            method="aeg",
            autolag=settings.eg_autolag,
            return_results=False,
        ),
    )
    statistic, pvalue, critical = cointegration
    if np.isnan(statistic) or not np.isfinite(pvalue) or not np.isfinite(critical).all():
        raise EconometricsEstimationError("Engle-Granger produced invalid test outputs")
    result.update(
        estimable=True,
        hard_data_failure=False,
        integration_flag=integration_flag,
        integration_warning=integration_flag != "I1_COMPATIBLE",
        coint_tstat=float(statistic) if np.isfinite(statistic) else None,
        coint_tstat_is_infinite=bool(np.isinf(statistic)),
        coint_pvalue=float(pvalue),
        coint_crit_1pct=float(critical[0]),
        coint_crit_5pct=float(critical[1]),
        coint_crit_10pct=float(critical[2]),
        cointegration_vector=[1.0, -beta],
    )
    result["warning_flags"].extend(coint_warnings)
    if np.isinf(statistic):
        result["warning_flags"].append("PERFECT_OR_NEAR_PERFECT_COLLINEARITY")
    half_life = estimate_half_life(pd.Series(spread), settings)
    result["warning_flags"].extend(half_life.pop("warning_flags"))
    result.update(half_life)
    if not result["half_life_valid"]:
        result["warning_flags"].append(f"HALF_LIFE_{result['half_life_flag']}")
    crossing_count, crossing_recency = _crossing_metrics(window, spread, result["warning_flags"])
    vol_20d = float(np.std(spread[-20:], ddof=1)) if len(spread) >= 20 else None
    result.update(
        beta_drift_pct=(
            abs(beta - previous_beta) / max(abs(previous_beta), settings.numerical_epsilon)
            if previous_beta is not None
            else None
        ),
        spread_vol_20d=vol_20d,
        spread_vol_ratio=vol_20d / spread_std if vol_20d is not None else None,
        zero_crossings_252d=crossing_count,
        days_since_zero_cross=crossing_recency,
        formation_z_range=float((np.max(spread) - np.min(spread)) / spread_std),
    )
    result["corr_20d"] = _correlation(window, 20, result["warning_flags"])
    result["corr_60d"] = _correlation(window, 60, result["warning_flags"])
    return result


def assign_pair_status(
    result: dict[str, Any],
    prior_invalid: int = 0,
    prior_age: int = 0,
    manual_terminal: bool = False,
) -> dict[str, Any]:
    """Apply only prescribed validity gates; half-life and stability remain diagnostics."""
    if prior_invalid < 0 or prior_age < 0:
        raise ValueError("Lifecycle counts cannot be negative")
    reasons: list[str] = []
    if manual_terminal:
        reasons.append("MANUAL_TERMINAL")
    if not result.get("estimable", False):
        reasons.extend(result.get("data_quality_reasons", []) or ["NON_ESTIMABLE_WINDOW"])
    elif result.get("hard_data_failure", False):
        reasons.extend(result.get("data_quality_reasons", []) or ["HARD_DATA_FAILURE"])
    integration = result.get("integration_flag")
    if result.get("estimable", False) and integration != "I1_COMPATIBLE":
        reasons.append(
            "AMBIGUOUS_INTEGRATION" if integration == "AMBIGUOUS" else "NOT_I1_COMPATIBLE"
        )
    pvalue = result.get("coint_pvalue")
    threshold = float(result.get("cointegration_alpha", 0.05))
    if result.get("estimable", False):
        if pvalue is None or not np.isfinite(pvalue):
            reasons.append("COINTEGRATION_UNAVAILABLE")
        elif pvalue >= threshold:
            reasons.append("COINTEGRATION_NOT_REJECTED")
    invalid = bool(reasons)
    invalid_count = prior_invalid + 1 if invalid else 0
    retire_after = int(result.get("retire_after_invalid", 2))
    if manual_terminal or invalid_count >= retire_after:
        status = "RETIRED"
        if not manual_terminal:
            reasons.append("CONSECUTIVE_INVALID_SNAPSHOTS")
    elif invalid:
        status = "WATCH"
    else:
        status = "ACTIVE"
        reasons.append("VALID_RELATIONSHIP")
    return {
        "pair_status": status,
        "status_reason": list(dict.fromkeys(reasons)),
        "consecutive_invalid_snapshots": invalid_count,
        "relationship_age_months": 0 if invalid else prior_age + 1,
    }

"""Alternative cointegration tests and hedge ratios for one formation window (DECISIONS 67).

The production relationship uses Engle-Granger with an OLS hedge ratio of leg A
(y) on leg B (x). These diagnostics re-examine the same 504-session window:
Engle-Granger in the reverse direction, Johansen, total least squares, the
hedge ratios that minimise the ADF statistic or the half-life of the spread,
KPSS, Hurst and a variance ratio. ``kalman_path`` runs a time-varying hedge
ratio filter over a pair's history using only past prices. None of these
changes the event definition; they are research features and gates.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

BETA_GRID = np.tan(np.linspace(0.02, 1.55, 80))  # positive hedge ratios, 0.02 to ~48
KALMAN_DELTA = 1e-4
KALMAN_OBSERVATION_VARIANCE = 1e-3
KALMAN_Z_WINDOW = 60
HURST_LAGS = np.arange(2, 21)
VR_LAG = 20


def ols_beta(y: FloatArray, x: FloatArray) -> tuple[float, float]:
    design = np.column_stack((np.ones(len(x)), x))
    alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
    return float(alpha), float(beta)


def adf_t(series: FloatArray, lags: int = 1) -> float:
    """ADF t-statistic with a constant and a fixed lag order (fast, for optimisation)."""
    diff = np.diff(series)
    rows = len(diff) - lags
    if rows < 20:
        return math.nan
    target = diff[lags:]
    columns = [series[lags:-1], np.ones(rows)]
    columns += [diff[lags - i : len(diff) - i] for i in range(1, lags + 1)]
    design = np.column_stack(columns)
    coef, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ coef
    dof = rows - design.shape[1]
    sigma2 = float(residual @ residual) / dof
    inverse = np.linalg.pinv(design.T @ design)
    se = math.sqrt(sigma2 * inverse[0, 0])
    return float(coef[0] / se) if se > 0 else math.nan


def half_life(series: FloatArray) -> float:
    """AR(1) half-life in sessions; infinite when the spread does not mean-revert."""
    lagged, change = series[:-1], np.diff(series)
    design = np.column_stack((lagged, np.ones(len(lagged))))
    rho = float(np.linalg.lstsq(design, change, rcond=None)[0][0])
    if rho >= 0 or rho <= -1:
        return math.inf
    return float(-math.log(2) / math.log1p(rho))


def tls_beta(y: FloatArray, x: FloatArray) -> float:
    """Orthogonal (total least squares) slope of y on x: symmetric in the two legs."""
    matrix = np.cov(np.vstack((x, y)))
    values, vectors = np.linalg.eigh(matrix)
    vx, vy = vectors[:, int(np.argmax(values))]
    return float(vy / vx) if vx != 0 else math.nan


def _minimise(objective: Any) -> tuple[float, float]:
    values = np.array([objective(b) for b in BETA_GRID])
    finite = np.isfinite(values)
    if not finite.any():
        return math.nan, math.nan
    best = int(np.nanargmin(np.where(finite, values, np.inf)))
    low = BETA_GRID[max(best - 1, 0)]
    high = BETA_GRID[min(best + 1, len(BETA_GRID) - 1)]
    grid = np.linspace(low, high, 21)
    refined = np.array([objective(b) for b in grid])
    if np.isfinite(refined).any():
        index = int(np.nanargmin(np.where(np.isfinite(refined), refined, np.inf)))
        return float(grid[index]), float(refined[index])
    return float(BETA_GRID[best]), float(values[best])


def min_adf_beta(y: FloatArray, x: FloatArray) -> tuple[float, float]:
    """Hedge ratio whose spread has the most negative ADF t (data-snooped by design)."""
    return _minimise(lambda b: adf_t(y - b * x))


def min_half_life_beta(y: FloatArray, x: FloatArray) -> tuple[float, float]:
    return _minimise(lambda b: half_life(y - b * x))


def hurst(series: FloatArray) -> float:
    spreads = [np.std(series[lag:] - series[:-lag]) for lag in HURST_LAGS]
    if min(spreads) <= 0:
        return math.nan
    slope = np.polyfit(np.log(HURST_LAGS), np.log(spreads), 1)[0]
    return float(slope)


def variance_ratio(series: FloatArray, lag: int = VR_LAG) -> float:
    one = np.var(np.diff(series), ddof=1)
    many = np.var(series[lag:] - series[:-lag], ddof=1)
    return float(many / (lag * one)) if one > 0 else math.nan


def johansen(y: FloatArray, x: FloatArray) -> dict[str, float]:
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    result = coint_johansen(np.column_stack((y, x)), det_order=0, k_ar_diff=1)
    vector = result.evec[:, 0]
    beta = float(-vector[1] / vector[0]) if vector[0] != 0 else math.nan
    return {
        "trace_ratio": float(result.lr1[0] / result.cvt[0, 1]),
        "maxeig_ratio": float(result.lr2[0] / result.cvm[0, 1]),
        "beta": beta,
    }


def window_statistics(y: FloatArray, x: FloatArray) -> dict[str, float]:
    """Every formation-window diagnostic plus the alternative hedge ratios and spread moments."""
    from statsmodels.tsa.stattools import coint, kpss

    alpha, beta = ols_beta(y, x)
    spread = y - alpha - beta * x
    scale = max(abs(beta), 0.1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reverse_t, reverse_p, _ = coint(x, y, trend="c", autolag="aic")
        forward_p = float(coint(y, x, trend="c", autolag="aic")[1])
        kpss_stat = float(kpss(spread, regression="c", nlags="auto")[0])
    joh = johansen(y, x)
    tls = tls_beta(y, x)
    adf_beta, adf_value = min_adf_beta(y, x)
    hl_beta, hl_value = min_half_life_beta(y, x)
    result = {
        "ols_alpha": alpha,
        "ols_beta": beta,
        "ci_eg_reverse_tstat": float(reverse_t),
        "ci_eg_max_pvalue": max(forward_p, float(reverse_p)),
        "ci_johansen_trace_ratio": joh["trace_ratio"],
        "ci_johansen_maxeig_ratio": joh["maxeig_ratio"],
        "ci_beta_gap_johansen": (joh["beta"] - beta) / scale,
        "ci_beta_gap_tls": (tls - beta) / scale,
        "ci_tls_adf_t": adf_t(y - tls * x),
        "ci_minadf_t": adf_value,
        "ci_beta_gap_minadf": (adf_beta - beta) / scale,
        "ci_minhl_halflife": min(hl_value, 504.0),
        "ci_beta_gap_minhl": (hl_beta - beta) / scale,
        "ci_kpss": kpss_stat,
        "ci_hurst": hurst(spread),
        "ci_vr20": variance_ratio(spread),
    }
    for name, value in (
        ("johansen", joh["beta"]),
        ("tls", tls),
        ("minadf", adf_beta),
        ("minhl", hl_beta),
    ):
        alt = y - value * x if np.isfinite(value) else np.full_like(y, np.nan)
        result[f"{name}_beta"] = value
        result[f"{name}_mean"] = float(np.mean(alt))
        result[f"{name}_std"] = float(np.std(alt, ddof=1))
    return result


def kalman_path(y: FloatArray, x: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Filtered hedge ratio and standardised one-step error at each session (past data only).

    State (alpha, beta) follows a random walk with variance delta/(1-delta); the
    observation is y = alpha + beta * x + e with a fixed variance. The error at t
    uses the prediction from t-1 and is divided by the standard deviation of the
    previous ``KALMAN_Z_WINDOW`` errors.
    """
    n = len(y)
    betas = np.full(n, np.nan)
    errors = np.full(n, np.nan)
    a, b = 0.0, 0.0
    p11, p12, p22 = 1.0, 0.0, 1.0
    w = KALMAN_DELTA / (1 - KALMAN_DELTA)
    ve = KALMAN_OBSERVATION_VARIANCE
    for t in range(n):
        yt, xt = float(y[t]), float(x[t])
        if not (math.isfinite(yt) and math.isfinite(xt)):
            continue
        p11, p22 = p11 + w, p22 + w
        error = yt - (a + b * xt)
        q = p11 + 2 * xt * p12 + xt * xt * p22 + ve
        k1, k2 = (p11 + xt * p12) / q, (p12 + xt * p22) / q
        a, b = a + k1 * error, b + k2 * error
        n11 = p11 - k1 * (p11 + xt * p12)
        n12 = p12 - k1 * (p12 + xt * p22)
        n22 = p22 - k2 * (p12 + xt * p22)
        p11, p12, p22 = n11, n12, n22
        errors[t] = error
        betas[t] = b
    z = np.full(n, np.nan)
    for t in range(KALMAN_Z_WINDOW, n):
        past = errors[t - KALMAN_Z_WINDOW : t]
        past = past[np.isfinite(past)]
        if len(past) >= KALMAN_Z_WINDOW // 2 and np.isfinite(errors[t]):
            sd = float(np.std(past, ddof=1))
            z[t] = errors[t] / sd if sd > 0 else np.nan
    return betas, z

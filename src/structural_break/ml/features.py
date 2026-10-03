"""Quantitative features built from an event's frozen, past-only information set."""

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from structural_break.data.market import session_schedule

FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "spread": (
        "z_signed",
        "abs_z",
        "divergence_sign",
        "adverse_z_velocity_1d",
        "adverse_z_velocity_5d",
        "spread_vol_20",
        "spread_vol_ratio_20_60",
        "days_since_equilibrium",
        "equilibrium_crossings_60",
        "max_abs_z_20",
    ),
    "relationship": (
        "coint_tstat",
        "coint_pvalue",
        "coint_strength",
        "half_life",
        "beta_abs",
        "beta_drift_pct",
        "corr_20",
        "corr_60",
        "valid_months_last_6",
    ),
    "market": (
        "market_return_1d",
        "market_return_5d",
        "sector_return_1d",
        "sector_return_5d",
        "vix_level",
        "vix_change_5d",
        "market_rv20",
    ),
    "security": (
        "aligned_relative_return_5d",
        "aligned_relative_return_20d",
        "abnormal_return_A_1d",
        "abnormal_return_B_1d",
        "volume_z_A_20",
        "volume_z_B_20",
        "relative_realised_vol_20",
    ),
    "liquidity": ("log_min_adv20", "adv_ratio", "max_range_proxy20"),
}
FEATURE_COLUMNS = tuple(name for names in FEATURE_FAMILIES.values() for name in names)
OPTIONAL_FEATURES = frozenset({"half_life", "beta_drift_pct", "days_since_equilibrium"})
LOOKBACKS: dict[str, int | None] = {
    "z_signed": 1,
    "abs_z": 1,
    "divergence_sign": 1,
    "adverse_z_velocity_1d": 2,
    "adverse_z_velocity_5d": 6,
    "spread_vol_20": 21,
    "spread_vol_ratio_20_60": 61,
    "days_since_equilibrium": None,
    "equilibrium_crossings_60": 61,
    "max_abs_z_20": 20,
    "corr_20": 21,
    "corr_60": 61,
    "market_return_1d": 2,
    "market_return_5d": 6,
    "sector_return_1d": 2,
    "sector_return_5d": 6,
    "vix_level": 1,
    "vix_change_5d": 6,
    "market_rv20": 21,
    "aligned_relative_return_5d": 6,
    "aligned_relative_return_20d": 21,
    "abnormal_return_A_1d": 2,
    "abnormal_return_B_1d": 2,
    "volume_z_A_20": 20,
    "volume_z_B_20": 20,
    "relative_realised_vol_20": 21,
    "log_min_adv20": 20,
    "adv_ratio": 20,
    "max_range_proxy20": 20,
}
DEFINITIONS: dict[str, str] = {
    "z_signed": "Entry z under the current frozen monthly fit",
    "abs_z": "Absolute entry z",
    "divergence_sign": "Sign of the entry z",
    "adverse_z_velocity_1d": "Entry sign times one-session z change under entry parameters",
    "adverse_z_velocity_5d": "Entry sign times five-session z change divided by five",
    "spread_vol_20": "Sample standard deviation of 20 exact-session frozen spread changes",
    "spread_vol_ratio_20_60": "20-session divided by 60-session spread-change volatility",
    "days_since_equilibrium": (
        "Sessions since last |z|<=success band since formation start; null if never observed"
    ),
    "equilibrium_crossings_60": "Success-band entries during 60 exact-session transitions",
    "max_abs_z_20": "Maximum absolute frozen z in the last 20 sessions including entry",
    "coint_tstat": "Current frozen Engle-Granger statistic",
    "coint_pvalue": "Current frozen MacKinnon approximate p-value",
    "coint_strength": "-log10(max(MacKinnon p-value, 1e-6))",
    "half_life": "Unclipped frozen AR(1) half-life in sessions; null when undefined",
    "beta_abs": "Absolute current frozen beta",
    "beta_drift_pct": "Frozen absolute beta change divided by absolute previous beta plus epsilon",
    "corr_20": "Sample correlation of exact-session log returns over trailing 20 sessions",
    "corr_60": "Sample correlation of exact-session log returns over trailing 60 sessions",
    "valid_months_last_6": "Number of ACTIVE fits in the latest six effective monthly attempts",
    "market_return_1d": "SPY one-session log return",
    "market_return_5d": "SPY cumulative five-session log return",
    "sector_return_1d": "Mapped sector ETF one-session log return",
    "sector_return_5d": "Mapped sector ETF cumulative five-session log return",
    "vix_level": "VIX from the exact previous XNYS session",
    "vix_change_5d": "Previous-session VIX minus the corresponding value five sessions earlier",
    "market_rv20": "Annualised sample standard deviation of 20 SPY log returns",
    "aligned_relative_return_5d": "Entry sign times A minus B five-session log return",
    "aligned_relative_return_20d": "Entry sign times A minus B 20-session log return",
    "abnormal_return_A_1d": "Leg A log return minus mapped sector ETF log return",
    "abnormal_return_B_1d": "Leg B log return minus mapped sector ETF log return",
    "volume_z_A_20": "Leg A volume z-score using trailing 20-session mean/sample deviation",
    "volume_z_B_20": "Leg B volume z-score using trailing 20-session mean/sample deviation",
    "relative_realised_vol_20": "A minus B annualised 20-session return volatility",
    "log_min_adv20": "log1p of lower leg trailing 20-session mean close times volume",
    "adv_ratio": "Larger trailing mean dollar volume divided by smaller",
    "max_range_proxy20": "Larger leg trailing 20-session mean of (unadjusted high-low)/close",
}


def feature_schema(version: str) -> dict[str, Any]:
    """The exact feature order and permitted missingness shared with inference."""
    return {
        "version": version,
        "feature_columns": list(FEATURE_COLUMNS),
        "columns": [
            {
                "name": name,
                "dtype": "float64",
                "allow_missing": name in OPTIONAL_FEATURES,
                "family": family,
                "definition": DEFINITIONS[name],
                "lookback_sessions": LOOKBACKS.get(name),
                "lookback_rule": "formation start through event"
                if name == "days_since_equilibrium"
                else (
                    "latest six effective monthly fits"
                    if name == "valid_months_last_6"
                    else "past only"
                ),
                "availability_column": f"{family}_available_at",
                "source": "frozen monthly relationship"
                if family == "relationship"
                else "past-only daily observations",
            }
            for family, names in FEATURE_FAMILIES.items()
            for name in names
        ],
        "volatility_convention": "sample standard deviation (ddof=1), annualised sqrt(252)",
        "rolling_price_convention": "entry fit and formation moments; no refitting or gap filling",
        "reference_limitation": "static sector proxies, retrospective adjusted-close vintages",
    }


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if np.isfinite(number) else float("nan")


def _std(values: np.ndarray[Any, Any], n: int) -> float:
    tail = values[-n:]
    if len(tail) != n or not np.isfinite(tail).all():
        return float("nan")
    return float(np.std(tail, ddof=1))


def _sum(values: np.ndarray[Any, Any], n: int) -> float:
    tail = values[-n:]
    return float(np.sum(tail)) if len(tail) == n and np.isfinite(tail).all() else float("nan")


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if np.isfinite(denominator) and denominator > 0 else float("nan")


def _returns(values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    return np.diff(np.log(np.where(values > 0, values, np.nan)))


def _correlation(a: np.ndarray[Any, Any], b: np.ndarray[Any, Any], n: int) -> float:
    a, b = a[-n:], b[-n:]
    if len(a) != n or len(b) != n or not np.isfinite(a).all() or not np.isfinite(b).all():
        return float("nan")
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _available(frame: pd.DataFrame, field: str, cutoff: pd.Timestamp) -> pd.Timestamp:
    if frame.empty or field not in frame:
        return pd.Timestamp("NaT")
    observed = pd.to_datetime(frame[field], utc=True, errors="coerce")
    if field.startswith("vix_"):
        present = frame["vix_close"].notna()
    else:
        present = frame["adj_close"].notna() if "adj_close" in frame else frame.notna().any(axis=1)
    if (present & observed.isna()).any():
        raise ValueError(f"Missing source availability timestamp: {field}")
    if observed.gt(cutoff).any():
        raise ValueError(f"Feature source timestamp exceeds event cutoff: {field}")
    return observed.max()


@lru_cache(maxsize=256)
def _first_session_predecessor(first: date) -> date:
    """The VIX predecessor can legitimately predate the price bootstrap."""
    schedule = session_schedule(first - timedelta(days=10), first)
    if len(schedule) < 2 or schedule.iloc[-1]["trading_date"] != first:
        raise ValueError("Feature history must use actual XNYS session dates")
    predecessor: date = schedule.iloc[-2]["trading_date"]
    return predecessor


def build_quantitative_features(
    event: dict[str, Any],
    snapshot: dict[str, Any],
    snapshot_history: pd.DataFrame,
    leg_a: pd.DataFrame,
    leg_b: pd.DataFrame,
    context: pd.DataFrame,
    session_dates: list[date],
    *,
    success_z: float,
    schema_version: str,
) -> dict[str, Any]:
    """Freeze a row from reindexed historical observations ending exactly at t0.

    Future rows are discarded before any operation. Missing sessions remain NaN
    so cumulative returns/rolling windows cannot jump across an absent price.
    """
    day = event["event_date"]
    cutoff = pd.Timestamp(event["event_timestamp"])
    if cutoff.tzinfo is None:
        raise ValueError("Event timestamp must be timezone-aware")
    cutoff = cutoff.tz_convert("UTC")
    dates = [value for value in session_dates if value <= day]
    formation_start = snapshot.get("window_start")
    if formation_start is not None and not pd.isna(formation_start):
        dates = [value for value in dates if value >= pd.Timestamp(formation_start).date()]
    index = pd.Index(dates, name="trading_date")

    def history(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.loc[frame["trading_date"].le(day)].set_index("trading_date").reindex(index)
        if "quality_flag" in result:
            invalid = result["quality_flag"].notna() & ~result["quality_flag"].isin(
                ["OK", "ZERO_VOLUME", "WARNING_BENCHMARK"]
            )
            numeric = result.select_dtypes(include="number").columns
            result.loc[invalid, numeric] = np.nan
        return result

    a, b, market = history(leg_a), history(leg_b), history(context)
    if "vix_observation_date" not in market:
        raise ValueError("VIX features require the exact previous-session source date")
    previous_sessions = {
        current: previous
        for previous, current in zip(session_dates, session_dates[1:], strict=False)
    }
    if session_dates:
        previous_sessions[session_dates[0]] = _first_session_predecessor(session_dates[0])
    vix_present = market["vix_close"].notna()
    vix_dates = pd.to_datetime(market["vix_observation_date"]).dt.date
    expected_vix_dates = pd.Series(
        [previous_sessions.get(value) for value in market.index], index=market.index
    )
    if (vix_present & vix_dates.ne(expected_vix_dates)).any():
        raise ValueError("VIX source is not the exact previous XNYS session")
    available_a = _available(a, "data_available_at", cutoff)
    available_b = _available(b, "data_available_at", cutoff)
    available_market = _available(market, "data_available_at", cutoff)
    vix_available = _available(market, "vix_observed_at_utc", cutoff)
    estimate_at = pd.to_datetime(snapshot["estimation_timestamp"], utc=True)
    effective_at = pd.to_datetime(snapshot["effective_start_at"], utc=True)
    if estimate_at > cutoff or effective_at > cutoff:
        raise ValueError("Future relationship snapshot used for event features")
    out: dict[str, Any] = {name: float("nan") for name in FEATURE_COLUMNS}
    out.update(
        {
            "event_id": event["event_id"],
            "feature_schema_version": schema_version,
            "feature_cutoff_timestamp": cutoff,
            "spread_available_at": max(available_a, available_b),
            "relationship_available_at": max(estimate_at, effective_at),
            "market_available_at": max(available_market, vix_available),
            "security_available_at": max(available_a, available_b, available_market),
            "liquidity_available_at": max(available_a, available_b),
            "vix_source_available_at": vix_available,
            "data_snapshot_id": event["data_snapshot_id"],
            "relationship_snapshot_id": event["relationship_snapshot_id"],
            "relationship_version": event["relationship_version"],
        }
    )
    alpha, beta = float(event["alpha"]), float(event["beta"])
    mean, deviation = float(event["spread_mean"]), float(event["spread_std"])
    pa, pb = a["adj_close"].to_numpy(dtype=float), b["adj_close"].to_numpy(dtype=float)
    spread = (
        np.log(np.where(pa > 0, pa, np.nan)) - alpha - beta * np.log(np.where(pb > 0, pb, np.nan))
    )
    z = (spread - mean) / deviation
    sign = int(event["divergence_sign"])
    if len(z):
        out.update(z_signed=float(z[-1]), abs_z=float(abs(z[-1])), divergence_sign=float(sign))
    if len(z) >= 2:
        out["adverse_z_velocity_1d"] = sign * (z[-1] - z[-2])
    if len(z) >= 6:
        out["adverse_z_velocity_5d"] = sign * (z[-1] - z[-6]) / 5
    ds = np.diff(spread)
    out["spread_vol_20"] = _std(ds, 20)
    out["spread_vol_ratio_20_60"] = _ratio(_std(ds, 20), _std(ds, 60))
    equilibrium = np.isfinite(z) & (np.abs(z) <= success_z)
    hits = np.flatnonzero(equilibrium)
    if len(hits) and np.isfinite(z[hits[-1] :]).all():
        out["days_since_equilibrium"] = float(len(z) - 1 - hits[-1])
    if len(z) >= 61 and np.isfinite(z[-61:]).all():
        out["equilibrium_crossings_60"] = float(np.sum(~equilibrium[-61:-1] & equilibrium[-60:]))
    if len(z) >= 20 and np.isfinite(z[-20:]).all():
        out["max_abs_z_20"] = float(np.max(np.abs(z[-20:])))
    pvalue = _finite(snapshot.get("coint_pvalue"))
    out.update(
        {
            "coint_tstat": _finite(snapshot.get("coint_tstat")),
            "coint_pvalue": pvalue,
            "coint_strength": -np.log10(max(pvalue, 1e-6)) if np.isfinite(pvalue) else np.nan,
            "half_life": _finite(snapshot.get("half_life_days")),
            "beta_abs": abs(beta),
            "beta_drift_pct": _finite(snapshot.get("beta_drift_pct")),
        }
    )
    past_snapshots = snapshot_history.loc[
        pd.to_datetime(snapshot_history["effective_start_at"], utc=True).le(cutoff)
    ]
    if not past_snapshots.empty:
        out["valid_months_last_6"] = float(
            past_snapshots.sort_values("effective_start_at")
            .tail(6)["pair_status"]
            .eq("ACTIVE")
            .sum()
        )
    ra, rb = _returns(pa), _returns(pb)
    out["corr_20"] = _correlation(ra, rb, 20)
    out["corr_60"] = _correlation(ra, rb, 60)
    rm = _returns(market["spy_adj_close"].to_numpy(dtype=float))
    rs = _returns(market["sector_etf_adj_close"].to_numpy(dtype=float))
    vix = market["vix_close"].to_numpy(dtype=float)
    out.update(
        {
            "market_return_1d": _sum(rm, 1),
            "market_return_5d": _sum(rm, 5),
            "sector_return_1d": _sum(rs, 1),
            "sector_return_5d": _sum(rs, 5),
            "vix_level": vix[-1] if len(vix) else np.nan,
            "vix_change_5d": vix[-1] - vix[-6]
            if len(vix) >= 6 and np.isfinite(vix[-6:]).all()
            else np.nan,
            "market_rv20": _std(rm, 20) * np.sqrt(252),
            "aligned_relative_return_5d": sign * (_sum(ra, 5) - _sum(rb, 5)),
            "aligned_relative_return_20d": sign * (_sum(ra, 20) - _sum(rb, 20)),
            "abnormal_return_A_1d": _sum(ra, 1) - _sum(rs, 1),
            "abnormal_return_B_1d": _sum(rb, 1) - _sum(rs, 1),
            "relative_realised_vol_20": (_std(ra, 20) - _std(rb, 20)) * np.sqrt(252),
        }
    )
    adv: list[float] = []
    ranges: list[float] = []
    for frame, suffix in ((a, "A"), (b, "B")):
        volume = frame["volume"].to_numpy(dtype=float)[-20:]
        valid = len(volume) == 20 and np.isfinite(volume).all()
        out[f"volume_z_{suffix}_20"] = (
            _ratio(float(volume[-1] - volume.mean()), float(volume.std(ddof=1)))
            if valid
            else np.nan
        )
        dollars = (frame["close"] * frame["volume"]).to_numpy(dtype=float)[-20:]
        adv.append(
            float(dollars.mean()) if len(dollars) == 20 and np.isfinite(dollars).all() else np.nan
        )
        range_values = ((frame["high"] - frame["low"]) / frame["close"]).to_numpy(dtype=float)[-20:]
        ranges.append(
            float(range_values.mean())
            if len(range_values) == 20 and np.isfinite(range_values).all()
            else np.nan
        )
    if np.isfinite(adv).all() and min(adv) > 0:
        out["log_min_adv20"] = float(np.log1p(min(adv)))
        out["adv_ratio"] = max(adv) / min(adv)
    if np.isfinite(ranges).all():
        out["max_range_proxy20"] = max(ranges)
    for name in FEATURE_COLUMNS:
        out[name] = _finite(out[name])
    missing = [
        name
        for name in FEATURE_COLUMNS
        if name not in OPTIONAL_FEATURES and not np.isfinite(out[name])
    ]
    out["feature_complete"] = not missing
    out["feature_quality_flags"] = missing
    return out


def validate_feature_timestamps(features: pd.DataFrame) -> None:
    """Release blocker: every used feature family is measurable at its cutoff."""
    if features.empty:
        return
    cutoff = pd.to_datetime(features["feature_cutoff_timestamp"], utc=True)
    for name in FEATURE_FAMILIES:
        available = pd.to_datetime(features[f"{name}_available_at"], utc=True)
        required = features["feature_complete"].astype(bool)
        if (available.gt(cutoff) | (required & available.isna())).any():
            raise ValueError(f"Feature availability exceeds event cutoff: {name}")
    if features["event_id"].duplicated().any():
        raise ValueError("Duplicate event feature rows")

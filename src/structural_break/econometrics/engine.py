"""Chronological monthly relationships and frozen daily divergence state.

This module consumes a frozen market snapshot; it never retrieves or persists
data and never reads forward prices for labels. Crossings are raw P2 observations,
not the non-overlapping labelled events constructed in P3.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from structural_break.config.models import EconometricsConfig
from structural_break.data.market import session_schedule
from structural_break.econometrics.statistics import assign_pair_status, estimate_window

PRICE_COLUMNS = (
    "ticker",
    "trading_date",
    "adj_close",
    "data_available_at",
    "quality_flag",
    "source_snapshot_id",
    "sha256",
    "data_snapshot_id",
)
BASE_SNAPSHOT_COLUMNS = (
    "relationship_snapshot_id",
    "pair_id",
    "y_ticker",
    "x_ticker",
    "estimation_date",
    "estimation_timestamp",
    "effective_start",
    "effective_end",
    "effective_start_at",
    "effective_end_at",
    "effective_start_date",
    "effective_end_date",
    "window_start",
    "window_end",
    "n_obs",
    "formation_window_days",
    "estimable",
    "alpha",
    "beta",
    "spread_mean",
    "spread_std",
    "pair_status",
    "status_reason",
    "consecutive_invalid_snapshots",
    "relationship_age_months",
    "data_snapshot_id",
    "source_price_snapshot_ids",
    "source_price_hashes",
    "config_hash",
    "relationship_spec_version",
    "created_at_utc",
)
BASE_DAILY_COLUMNS = (
    "pair_id",
    "trading_date",
    "relationship_snapshot_id",
    "alpha",
    "beta",
    "spread_mean",
    "spread_std",
    "spread",
    "z_score",
    "abs_z",
    "previous_spread",
    "previous_z_score",
    "spread_velocity_1d",
    "z_velocity_1d",
    "days_since_zero_cross",
    "zero_crossings_252d",
    "zero_crossings_252d_complete",
    "spread_vol_20d",
    "spread_vol_20d_ratio",
    "pair_status",
    "status_reason",
    "econometric_eligible",
    "fresh_threshold_crossing",
    "data_available_at",
    "data_snapshot_id",
    "source_price_snapshot_ids",
    "source_price_hashes",
    "config_hash",
    "relationship_spec_version",
    "created_at_utc",
)
BASE_CROSSING_COLUMNS = (
    "crossing_id",
    "pair_id",
    "event_date",
    "trading_date",
    "event_timestamp",
    "relationship_snapshot_id",
    "direction",
    "z_entry",
    "z_score",
    "previous_z_score",
    "alpha",
    "beta",
    "spread_mean",
    "spread_std",
    "pair_status",
    "econometric_eligible",
    "baseline0_eligible",
    "baseline1_eligible",
    "data_snapshot_id",
    "source_price_snapshot_ids",
    "source_price_hashes",
    "config_hash",
    "relationship_spec_version",
    "created_at_utc",
)
SNAPSHOT_FEATURES = (
    "coint_tstat",
    "coint_pvalue",
    "half_life_days",
    "half_life_valid",
    "beta_drift_pct",
    "corr_20d",
    "corr_60d",
    "integration_flag",
    "integration_warning",
    "cusum_pvalue",
    "cusum_warning",
    "relationship_age_months",
    "ar1_rho",
    "error_correction_phi",
)


class RelationshipEstimationError(RuntimeError):
    """Unexpected estimation failure annotated with its reproducible context."""

    def __init__(self, pair_id: str, estimation_date: date, message: str) -> None:
        super().__init__(message)
        self.pair_id = pair_id
        self.estimation_date = estimation_date


def _identity(prefix: str, values: dict[str, Any]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return prefix + hashlib.sha256(encoded).hexdigest()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date()


def _terminal(pair: dict[str, Any], day: date) -> bool:
    terminal_date = _optional_date(pair.get("manual_terminal_date"))
    active_to = _optional_date(pair.get("active_to"))
    return (terminal_date is not None and day >= terminal_date) or (
        active_to is not None and day > active_to
    )


def _price_frame(
    prices: pd.DataFrame, schedule: pd.DataFrame, data_snapshot_id: str
) -> pd.DataFrame:
    missing = set(PRICE_COLUMNS) - set(prices.columns)
    if missing:
        raise ValueError(f"Relationship prices lack required columns: {sorted(missing)}")
    if prices.empty:
        raise ValueError("Relationship price history is empty")
    result = prices.copy()
    result["trading_date"] = pd.to_datetime(result["trading_date"], errors="raise").dt.date
    if result.duplicated(["ticker", "trading_date"]).any():
        raise ValueError("Relationship prices have duplicate ticker/session keys")
    if not result["data_snapshot_id"].eq(data_snapshot_id).all():
        raise ValueError("Relationship prices mix frozen data snapshot identities")
    if result[["source_snapshot_id", "sha256"]].isna().any(axis=None):
        raise ValueError("Relationship price source lineage is missing")
    if result["source_snapshot_id"].astype(str).str.len().eq(0).any():
        raise ValueError("Relationship price source identity is empty")
    if not result["sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("Relationship price source hash is invalid")
    timestamps = result["data_available_at"].map(pd.Timestamp)
    if timestamps.isna().any() or timestamps.map(lambda value: value.tzinfo is None).any():
        raise ValueError("Relationship price availability must include a timezone")
    result["data_available_at"] = pd.to_datetime(timestamps, utc=True)
    close_by_date = schedule.set_index("trading_date")["data_available_at"]
    expected = result["trading_date"].map(close_by_date)
    if expected.isna().any() or not result["data_available_at"].eq(expected).all():
        raise ValueError("Relationship prices disagree with the actual XNYS close")
    result["adj_close"] = pd.to_numeric(result["adj_close"], errors="raise").astype(float)
    allowed = result["quality_flag"].map(
        lambda value: isinstance(value, str) and set(value.split("|")) <= {"OK", "ZERO_VOLUME"}
    )
    result["valid"] = allowed & np.isfinite(result["adj_close"]) & result["adj_close"].gt(0)
    return result.sort_values(["ticker", "trading_date"]).reset_index(drop=True)


def _pair_history(
    prices: pd.DataFrame, pair: dict[str, Any], schedule: pd.DataFrame
) -> pd.DataFrame:
    history = schedule.copy()
    history["session_index"] = np.arange(len(history), dtype=int)
    for side, ticker in (("y", pair["leg_a"]), ("x", pair["leg_b"])):
        columns = [
            "trading_date",
            "adj_close",
            "valid",
            "quality_flag",
            "source_snapshot_id",
            "sha256",
        ]
        leg = prices.loc[prices["ticker"].eq(ticker), columns].rename(
            columns={column: f"{side}_{column}" for column in columns if column != "trading_date"}
        )
        if leg.empty:
            raise ValueError(f"No price history for fixed pair {pair['pair_id']} leg {ticker}")
        history = history.merge(leg, on="trading_date", how="left", validate="one_to_one")
        valid = history[f"{side}_valid"].eq(True)
        values = history[f"{side}_adj_close"].where(valid)
        history[side] = np.log(values)
    valid_pair = history[["y", "x"]].notna().all(axis=1)
    active_from = _optional_date(pair.get("active_from"))
    if active_from is not None:
        valid_pair &= history["trading_date"].ge(active_from)
    history.loc[~valid_pair, ["y", "x"]] = np.nan
    history["valid"] = valid_pair
    # The calendar grid makes a missing previous session propagate to a missing
    # return rather than creating a multi-session return called one-day.
    history["dy"] = history["y"].diff()
    history["dx"] = history["x"].diff()
    return history


def _lineage(window: pd.DataFrame) -> dict[str, Any]:
    ids: set[str] = set()
    hashes: set[str] = set()
    for side in ("y", "x"):
        ids.update(str(value) for value in window[f"{side}_source_snapshot_id"].dropna())
        hashes.update(str(value) for value in window[f"{side}_sha256"].dropna())
    return {"source_price_snapshot_ids": sorted(ids), "source_price_hashes": sorted(hashes)}


def _daily_rows(
    history: pd.DataFrame,
    snapshot: dict[str, Any],
    pair: dict[str, Any],
    settings: EconometricsConfig,
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lower = max(start, snapshot["effective_start_date"])
    upper = min(end, snapshot["effective_end_date"] - timedelta(days=1))
    if lower > upper or not snapshot["estimable"]:
        return [], []
    prefix = history.loc[history["trading_date"].le(upper)].copy()
    alpha, beta = float(snapshot["alpha"]), float(snapshot["beta"])
    mean, std = float(snapshot["spread_mean"]), float(snapshot["spread_std"])
    spread = (prefix["y"] - alpha - beta * prefix["x"]).to_numpy(dtype=float)
    z_scores = (spread - mean) / std
    valid = np.isfinite(spread)
    locations = np.arange(len(prefix))
    last_gap_at = np.maximum.accumulate(np.where(~valid, locations, -1))
    nonzero = valid & (spread != 0)
    last_nonzero_at = np.maximum.accumulate(np.where(nonzero, locations, -1))
    previous_nonzero_at = np.r_[-1, last_nonzero_at[:-1]]
    known_previous_sign = (previous_nonzero_at >= 0) & (previous_nonzero_at > last_gap_at)
    previous_sign = np.sign(spread[np.maximum(previous_nonzero_at, 0)])
    # Touching zero and returning to the same side is not a sign reversal.
    zero_cross = nonzero & known_previous_sign & (np.sign(spread) != previous_sign)
    rows: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    last_zero_at = np.maximum.accumulate(np.where(zero_cross, locations, -1))
    signals = prefix.loc[prefix["trading_date"].ge(lower) & prefix["valid"]]
    for index, values in zip(signals.index.tolist(), signals.to_dict("records"), strict=True):
        day = values["trading_date"]
        last_zero = int(last_zero_at[index])
        known_crossing = last_zero >= 0 and last_zero > last_gap_at[index]
        previous_valid = index > 0 and valid[index - 1]
        previous_spread = float(spread[index - 1]) if previous_valid else None
        previous_z = float(z_scores[index - 1]) if previous_valid else None
        current_spread, current_z = float(spread[index]), float(z_scores[index])
        fresh = previous_z is not None and abs(previous_z) < settings.entry_z <= abs(current_z)
        terminal = _terminal(pair, day)
        status = "RETIRED" if terminal else snapshot["pair_status"]
        eligible = status == "ACTIVE"
        vol_window = spread[max(0, index - 19) : index + 1]
        vol = (
            float(np.std(vol_window, ddof=1))
            if len(vol_window) == 20 and np.isfinite(vol_window).all()
            else None
        )
        trailing = slice(max(0, index - 251), index + 1)
        row: dict[str, Any] = {
            "pair_id": snapshot["pair_id"],
            "trading_date": day,
            "relationship_snapshot_id": snapshot["relationship_snapshot_id"],
            "alpha": alpha,
            "beta": beta,
            "spread_mean": mean,
            "spread_std": std,
            "spread": current_spread,
            "z_score": current_z,
            "abs_z": abs(current_z),
            "previous_spread": previous_spread,
            "previous_z_score": previous_z,
            "spread_velocity_1d": current_spread - previous_spread
            if previous_spread is not None
            else None,
            "z_velocity_1d": current_z - previous_z if previous_z is not None else None,
            "days_since_zero_cross": index - last_zero if known_crossing else None,
            "zero_crossings_252d": int(zero_cross[trailing].sum()),
            "zero_crossings_252d_complete": bool(valid[trailing].all() and index >= 251),
            "spread_vol_20d": vol,
            "spread_vol_20d_ratio": vol / std if vol is not None else None,
            "pair_status": status,
            "status_reason": ["MANUAL_TERMINAL"] if terminal else snapshot["status_reason"],
            "econometric_eligible": eligible,
            "fresh_threshold_crossing": fresh,
            "data_available_at": values["data_available_at"],
            "data_snapshot_id": snapshot["data_snapshot_id"],
            "config_hash": snapshot["config_hash"],
            "relationship_spec_version": snapshot["relationship_spec_version"],
            "created_at_utc": snapshot["created_at_utc"],
            "y_source_snapshot_id": values["y_source_snapshot_id"],
            "x_source_snapshot_id": values["x_source_snapshot_id"],
            "y_price_quality_flag": values["y_quality_flag"],
            "x_price_quality_flag": values["x_quality_flag"],
            "y_source_price_sha256": values["y_sha256"],
            "x_source_price_sha256": values["x_sha256"],
            "source_price_snapshot_ids": sorted(
                {str(values["y_source_snapshot_id"]), str(values["x_source_snapshot_id"])}
            ),
            "source_price_hashes": sorted({str(values["y_sha256"]), str(values["x_sha256"])}),
            **{field: snapshot.get(field) for field in SNAPSHOT_FEATURES},
        }
        rows.append(row)
        if fresh:
            key = {
                "pair_id": row["pair_id"],
                "event_date": day.isoformat(),
                "relationship_snapshot_id": row["relationship_snapshot_id"],
                "data_snapshot_id": row["data_snapshot_id"],
                "config_hash": row["config_hash"],
            }
            crossings.append(
                {
                    **row,
                    "crossing_id": _identity("cross_", key),
                    "event_date": day,
                    "event_timestamp": row["data_available_at"],
                    "direction": 1 if current_z > 0 else -1,
                    "z_entry": current_z,
                    "baseline0_eligible": True,
                    "baseline1_eligible": eligible,
                }
            )
    return rows, crossings


def _frame(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> pd.DataFrame:
    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def build_relationship_history(
    prices: pd.DataFrame,
    pairs: pd.DataFrame,
    settings: EconometricsConfig,
    *,
    data_snapshot_id: str,
    config_hash: str,
    start: date,
    end: date,
    created_at: datetime,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fit each actual month-end and apply it only from the next XNYS session.

    ``start`` bounds daily outputs; all supplied earlier prices remain warm-up.
    Monthly audit rows include rejected attempts so a new unusable relationship
    never falls back to an older successful fit. ``effective_end`` is exclusive
    and determined by the next scheduled refit, including beyond ``end``.
    """
    if start > end or not data_snapshot_id or not config_hash:
        raise ValueError("Invalid relationship range or reproducibility identities")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("Relationship creation time must include a timezone")
    if prices.empty or pairs.empty:
        raise ValueError("Relationship prices and fixed pair registry must be nonempty")
    required = {"pair_id", "leg_a", "leg_b"}
    if not required <= set(pairs.columns) or pairs["pair_id"].duplicated().any():
        raise ValueError("Fixed pair registry needs unique pair_id/leg_a/leg_b")
    source_dates = pd.to_datetime(prices["trading_date"], errors="raise").dt.date
    # Requesting an earlier chronological prefix must not inspect later prices,
    # even though the caller can supply the complete frozen source history.
    prices = prices.loc[source_dates.le(end)].copy()
    if prices.empty:
        raise ValueError("No relationship observations on or before the requested end")
    earliest = pd.to_datetime(prices["trading_date"], errors="raise").min().date()
    schedule = session_schedule(min(start, earliest), end + timedelta(days=45)).reset_index(
        drop=True
    )
    source = _price_frame(prices, schedule, data_snapshot_id)
    month = pd.to_datetime(schedule["trading_date"]).dt.to_period("M")
    refits = schedule.groupby(month, sort=True).tail(1)
    snapshots: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    for raw_pair in pairs.sort_values("pair_id").to_dict("records"):
        pair = {str(key): value for key, value in raw_pair.items()}
        manual = pair.get("manual_terminal") is True or pair.get("lifecycle_status") == "RETIRED"
        if manual and all(
            _optional_date(pair.get(field)) is None
            for field in ("active_to", "manual_terminal_date")
        ):
            raise ValueError("Manual terminal retirement requires a declared effective date")
        if pair["pair_id"] != f"{pair['leg_a']}__{pair['leg_b']}" or pair["leg_a"] == pair["leg_b"]:
            raise ValueError("Pair identity must preserve fixed leg_a-is-y orientation")
        if pair.get("orientation", "leg_a_is_y") != "leg_a_is_y":
            raise ValueError("Relationship orientation must be leg_a_is_y")
        history = _pair_history(source, pair, schedule)
        previous_beta: float | None = None
        invalid_count, age = 0, 0
        refit_rows = refits.assign(session_index=refits.index).to_dict("records")
        for position, refit in enumerate(refit_rows):
            estimation_day = pd.Timestamp(refit["trading_date"]).date()
            if estimation_day > end or estimation_day < earliest:
                continue
            effective_index = int(refit["session_index"]) + 1
            next_refit = refit_rows[position + 1]
            next_effective_index = int(next_refit["session_index"]) + 1
            window = (
                history.loc[history["trading_date"].le(estimation_day) & history["valid"]]
                .tail(settings.formation_days)
                .copy()
            )
            try:
                result = estimate_window(window, settings, previous_beta=previous_beta)
                lifecycle = assign_pair_status(
                    result,
                    prior_invalid=invalid_count,
                    prior_age=age,
                    manual_terminal=_terminal(pair, estimation_day),
                )
            except Exception as exc:
                raise RelationshipEstimationError(
                    pair["pair_id"],
                    estimation_day,
                    f"Estimation failed for pair={pair['pair_id']} date={estimation_day} "
                    f"data={data_snapshot_id} config={config_hash}: {exc}",
                ) from exc
            identity = {
                "pair_id": pair["pair_id"],
                "estimation_date": estimation_day.isoformat(),
                "data_snapshot_id": data_snapshot_id,
                "config_hash": config_hash,
            }
            snapshot = {
                **result,
                **lifecycle,
                **_lineage(window),
                "relationship_snapshot_id": _identity("rel_", identity),
                "pair_id": pair["pair_id"],
                "y_ticker": pair["leg_a"],
                "x_ticker": pair["leg_b"],
                "estimation_date": estimation_day,
                "estimation_timestamp": refit["data_available_at"],
                "effective_start": schedule.iloc[effective_index]["trading_date"],
                "effective_end": schedule.iloc[next_effective_index]["trading_date"],
                "effective_start_at": schedule.iloc[effective_index]["session_open"],
                "effective_end_at": schedule.iloc[next_effective_index]["session_open"],
                "effective_start_date": schedule.iloc[effective_index]["trading_date"],
                "effective_end_date": schedule.iloc[next_effective_index]["trading_date"],
                "window_start": window["trading_date"].min() if not window.empty else None,
                "window_end": window["trading_date"].max() if not window.empty else None,
                "formation_window_days": settings.formation_days,
                "source_price_quality_flags": sorted(
                    {
                        str(flag)
                        for side in ("y", "x")
                        for flag in window[f"{side}_quality_flag"]
                        if flag != "OK"
                    }
                ),
                "formation_price_available_at_max": window["data_available_at"].max()
                if not window.empty
                else None,
                "data_snapshot_id": data_snapshot_id,
                "config_hash": config_hash,
                "relationship_spec_version": settings.version,
                "created_at_utc": created_at.astimezone(UTC),
            }
            snapshots.append(snapshot)
            invalid_count = int(lifecycle["consecutive_invalid_snapshots"])
            age = int(lifecycle["relationship_age_months"])
            previous_beta = float(result["beta"]) if result["estimable"] else None
            day_rows, crossing_rows = _daily_rows(history, snapshot, pair, settings, start, end)
            daily.extend(day_rows)
            crossings.extend(crossing_rows)
    return (
        _frame(snapshots, BASE_SNAPSHOT_COLUMNS),
        _frame(daily, BASE_DAILY_COLUMNS),
        _frame(crossings, BASE_CROSSING_COLUMNS),
    )

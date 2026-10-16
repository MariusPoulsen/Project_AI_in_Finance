"""Target-blind inputs for the production execution-policy proposal.

Only data dated before the bound assessment window are read: relationship betas
on fresh crossings and episode events, trailing split-invariant dollar volume at
the signal close, and calibration-period calibrated scores. Supervised targets,
forward price paths and returns are never read or produced. The summaries inform
a DRAFT proposal; they do not freeze or select any policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from structural_break.backtest.historical import HistoricalSources

DIAGNOSTICS_VERSION = "p6-policy-diagnostics-v1"
BETA_CEILINGS = (2.0, 3.0, 5.0)
DOLLAR_VOLUME_FLOORS = (1e6, 5e6, 1e7, 2.5e7)
SCORE_THRESHOLDS = (0.2, 0.3, 0.4, 0.5, 0.65)
QUANTILES = (0.01, 0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)
ADV_SESSIONS = 20


def _quantiles(values: pd.Series) -> dict[str, float | None]:
    clean = values.dropna().to_numpy(dtype=float)
    return {
        f"p{round(q * 100):02d}": float(np.quantile(clean, q)) if clean.size else None
        for q in QUANTILES
    } | {
        "min": float(clean.min()) if clean.size else None,
        "max": float(clean.max()) if clean.size else None,
    }


def _window(frame: pd.DataFrame, column: str, start: date, end: date) -> pd.DataFrame:
    dates = pd.to_datetime(frame[column]).dt.date
    return frame.loc[dates.ge(start) & dates.le(end)]


def beta_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """Execution eligibility needs 0 < beta <= ceiling; nothing here reads outcomes."""
    beta = frame["beta"].astype(float)
    positive = beta.loc[beta.gt(0)]
    return {
        "n": len(frame),
        "nonpositive_beta_n": int(beta.le(0).sum()),
        "missing_beta_n": int(beta.isna().sum()),
        "positive_beta_quantiles": _quantiles(positive),
        "positive_beta_above_ceiling_n": {
            str(ceiling): int(positive.gt(ceiling).sum()) for ceiling in BETA_CEILINGS
        },
    }


def liquidity_summary(
    events: pd.DataFrame, universe: pd.DataFrame, prices: pd.DataFrame
) -> dict[str, Any]:
    """Minimum-leg trailing mean dollar volume over the 20 sessions ending at the signal.

    `dollar_volume` = split-adjusted close x split-adjusted volume, so it is
    split-invariant. A share-price floor is not computed: retrospective split
    adjustment through the capture date makes historical price levels unreliable.
    """
    frame = prices.sort_values(["ticker", "trading_date"], kind="mergesort")
    rolling = frame.groupby("ticker", sort=False)["dollar_volume"].rolling(
        ADV_SESSIONS, min_periods=ADV_SESSIONS
    )
    frame = frame.assign(adv=rolling.mean().reset_index(level=0, drop=True))
    lookup = {
        (str(ticker), pd.Timestamp(day).date()): value
        for ticker, day, value in frame[["ticker", "trading_date", "adv"]].itertuples(
            index=False, name=None
        )
    }
    legs = universe.set_index("pair_id")[["leg_a", "leg_b"]]
    minimum = []
    for pair_id, day in events[["pair_id", "event_date"]].itertuples(index=False, name=None):
        leg_a, leg_b = legs.loc[pair_id]
        signal = pd.Timestamp(day).date()
        values = (lookup.get((str(leg_a), signal)), lookup.get((str(leg_b), signal)))
        known = [float(value) for value in values if value is not None and np.isfinite(value)]
        minimum.append(min(known) if len(known) == 2 else np.nan)
    series = pd.Series(minimum, dtype=float)
    return {
        "n": len(series),
        "unknown_n": int(series.isna().sum()),
        "min_leg_adv20_usd_quantiles": _quantiles(series),
        "below_floor_n": {
            f"{floor:.0f}": int(series.lt(floor).sum()) for floor in DOLLAR_VOLUME_FLOORS
        },
        "price_floor": "NOT_COMPUTED_RETROSPECTIVE_SPLIT_ADJUSTMENT",
    }


def score_summary(predictions: pd.DataFrame, models: Sequence[str]) -> dict[str, Any]:
    """Calibration-period score scale for the threshold question; no labels."""
    result: dict[str, Any] = {}
    for name in models:
        column = predictions[f"{name}_calibrated"].astype(float)
        groups = {
            "all": column,
            "baseline1_eligible": column.loc[predictions["baseline1_eligible"].eq(True)],
        }
        result[name] = {
            group: {
                "n": len(values),
                "quantiles": _quantiles(values),
                "at_or_above_n": {
                    str(threshold): int(values.ge(threshold).sum())
                    for threshold in SCORE_THRESHOLDS
                },
            }
            for group, values in groups.items()
        }
    return result


def policy_diagnostics(sources: HistoricalSources) -> dict[str, Any]:
    """Summaries over fit and calibration dates only; assessment rows are never read."""
    binding = sources.binding
    protocol = sources.evaluation["protocol"]
    start = date.fromisoformat(protocol["fit_start"])
    end = binding.assessment_start - timedelta(days=1)
    calibration = (
        date.fromisoformat(protocol["calibration_start"]),
        date.fromisoformat(protocol["calibration_end"]),
    )
    if calibration[1] > end:
        raise ValueError("Calibration window must end before the assessment window")
    universe = sources.pair_universe()
    crossings = pd.concat(
        [
            sources.pair_frame(pair_id, "raw_crossings", ["event_date", "beta", "pair_status"])
            for pair_id in sorted(universe["pair_id"])
        ],
        ignore_index=True,
    )
    crossings = _window(crossings, "event_date", start, end)
    horizon = binding.horizon_sessions
    events = _window(
        sources.registry_frame(f"h{horizon}_events", ["event_id", "pair_id", "event_date", "beta"]),
        "event_date",
        start,
        end,
    )
    prices = sources.prices(
        start - timedelta(days=45), end, ("ticker", "trading_date", "dollar_volume")
    )
    models = ("logistic_A", "logistic_B_both", "xgboost_A", "xgboost_B_both")
    predictions = sources.predictions(
        [
            "event_id",
            "event_date",
            "research_partition",
            "baseline1_eligible",
            *(f"{name}_calibrated" for name in models),
        ]
    )
    predictions = _window(predictions, "event_date", *calibration)
    if not predictions["research_partition"].eq("calibration").all():
        raise ValueError("Calibration-window scores must come from the calibration partition")
    return {
        "schema_version": DIAGNOSTICS_VERSION,
        "acceptance": binding.acceptance,
        "evaluation_version": binding.evaluation.version,
        "horizon_sessions": horizon,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "calibration_window": [day.isoformat() for day in calibration],
        "raw_crossing_beta": {
            "all": beta_summary(crossings),
            "active": beta_summary(crossings.loc[crossings["pair_status"].eq("ACTIVE")]),
        },
        "episode_event_beta": beta_summary(events),
        "episode_event_liquidity": liquidity_summary(events, universe, prices),
        "calibration_scores": score_summary(predictions, models),
        "labels_read": False,
        "assessment_data_read": False,
        "returns_computed": False,
        "final_test_read": False,
    }

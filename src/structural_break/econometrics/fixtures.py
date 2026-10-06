"""Deterministic artificial price histories for offline relationship acceptance.

Ticker labels preserve three approved pair orientations, but every number here
is generated rather than downloaded. These inputs are never research observations.
They exercise the same 504-session estimator, monthly schedule and publication
path as the project data, without consulting a final-test or live source.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

import exchange_calendars as xcals
import numpy as np
import pandas as pd
from numpy.typing import NDArray

FIXTURE_START = date(2014, 1, 2)
FIXTURE_END = date(2018, 12, 31)
FIXTURE_SEED = 12091
FIXTURE_VERSION = "p2-artificial-v1"


def _ar1(rng: np.random.Generator, count: int, rho: float, scale: float) -> NDArray[np.float64]:
    innovations = rng.normal(0.0, scale, count)
    values = np.zeros(count, dtype=np.float64)
    for index in range(1, count):
        values[index] = rho * values[index - 1] + innovations[index]
    return values


def fixture_inputs() -> tuple[pd.DataFrame, pd.DataFrame, date, date, str]:
    """Return artificial P1-shaped prices, approved pair labels and input hash.

    KO/PEP share a random-walk trend with a stationary AR(1) equilibrium error.
    HD/LOW are independently generated random walks. WMT/TGT have stationary
    log levels and should fail the I(1) gate even when residuals are stationary.
    The 2014--2018 dates contain more than 900 actual XNYS sessions.
    """
    calendar = xcals.get_calendar("XNYS", start=FIXTURE_START, end=FIXTURE_END)
    schedule = calendar.schedule
    schedule = schedule.loc[
        (schedule.index >= pd.Timestamp(FIXTURE_START))
        & (schedule.index <= pd.Timestamp(FIXTURE_END))
    ]
    dates = schedule.index.date
    count = len(dates)
    rng = np.random.default_rng(FIXTURE_SEED)
    shared_trend = 3.8 + np.cumsum(rng.normal(0.00025, 0.010, count))
    equilibrium_error = _ar1(rng, count, rho=0.75, scale=0.004)
    log_prices = {
        "KO": 0.35 + 1.08 * shared_trend + equilibrium_error,
        "PEP": shared_trend,
        "HD": 4.3 + np.cumsum(rng.normal(0.00015, 0.009, count)),
        "LOW": 4.0 + np.cumsum(rng.normal(0.00020, 0.012, count)),
        "WMT": 4.1 + _ar1(rng, count, rho=0.60, scale=0.015),
        "TGT": 4.0 + _ar1(rng, count, rho=0.65, scale=0.016),
    }
    frames: list[pd.DataFrame] = []
    for ticker, levels in log_prices.items():
        closes = np.exp(levels)
        frames.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "security_id": f"US:{ticker}",
                    "trading_date": dates,
                    "open": closes * 0.999,
                    "high": closes * 1.002,
                    "low": closes * 0.998,
                    "close": closes,
                    "adj_close": closes,
                    "volume": np.full(count, 2_000_000, dtype=np.int64),
                    "dividends": 0.0,
                    "stock_splits": 0.0,
                    "quality_flag": "OK",
                    "session_open": pd.to_datetime(schedule["open"].to_numpy(), utc=True),
                    "data_available_at": pd.to_datetime(schedule["close"].to_numpy(), utc=True),
                }
            )
        )
    prices = pd.concat(frames, ignore_index=True).sort_values(
        ["ticker", "trading_date"], ignore_index=True
    )
    specification: dict[str, Any] = {
        "synthetic": True,
        "version": FIXTURE_VERSION,
        "seed": FIXTURE_SEED,
        "start": FIXTURE_START.isoformat(),
        "end": FIXTURE_END.isoformat(),
        "calendar": "XNYS",
        "pairs": ["KO__PEP", "HD__LOW", "WMT__TGT"],
        "description": "Artificial cointegrated, independent-walk and stationary-level prices",
    }
    specification_bytes = json.dumps(specification, sort_keys=True).encode()
    price_bytes = prices.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode()
    source_identity = hashlib.sha256(specification_bytes + b"\n" + price_bytes).hexdigest()
    data_snapshot_id = f"synthetic_p2_{source_identity[:16]}"
    prices["data_snapshot_id"] = data_snapshot_id
    prices["source_snapshot_id"] = prices["ticker"].map(
        lambda ticker: f"synthetic_{ticker}_{source_identity[:16]}"
    )
    prices["source_provider"] = "SYNTHETIC_ACCEPTANCE_FIXTURE"
    prices["source_url"] = f"synthetic-fixture://{FIXTURE_VERSION}"
    prices["raw_file_path"] = f"synthetic-fixture/{FIXTURE_VERSION}/generated-prices"
    prices["sha256"] = source_identity
    prices["retrieved_at_utc"] = datetime(2019, 1, 2, tzinfo=UTC)
    prices["library_version"] = np.__version__
    prices["synthetic"] = True
    pairs = pd.DataFrame(
        [
            {
                "pair_id": f"{leg_a}__{leg_b}",
                "leg_a": leg_a,
                "leg_b": leg_b,
                "y_ticker": leg_a,
                "x_ticker": leg_b,
                "leg_a_security_id": f"US:{leg_a}",
                "leg_b_security_id": f"US:{leg_b}",
                "orientation": "leg_a_is_y",
                "enabled": True,
                "manual_review_status": "APPROVED",
                "manual_terminal_reason": None,
                "pair_version": FIXTURE_VERSION,
                "data_snapshot_id": data_snapshot_id,
                "synthetic": True,
            }
            for leg_a, leg_b in (("KO", "PEP"), ("HD", "LOW"), ("WMT", "TGT"))
        ]
    )
    return prices, pairs, FIXTURE_START, FIXTURE_END, source_identity

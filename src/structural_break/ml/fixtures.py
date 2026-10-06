"""Deterministic synthetic P3 inputs for the actual econometric/ML job path."""

import hashlib
from datetime import date

import numpy as np
import pandas as pd

from structural_break.data.market import build_market_context, session_schedule


def fixture_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    """Generate transparent fictitious OHLCV/context, without target injection.

    Three fixed pairs combine independent common random walks and stationary
    residuals with different persistence. Outcomes follow the normal frozen
    relationship and target rules; no class labels are fabricated.
    """
    schedule = session_schedule(date(2014, 1, 1), date(2025, 12, 31))
    count = len(schedule)
    rng = np.random.default_rng(730031)
    logs: dict[str, np.ndarray] = {}
    pairs = []
    for number, (a, b, rho, beta) in enumerate(
        (
            ("KO", "PEP", 0.66, 0.9),
            ("HD", "LOW", 0.84, 1.1),
            ("TXN", "ADI", 0.94, 0.8),
        )
    ):
        common = 4.2 + np.cumsum(rng.normal(0.0001, 0.014, count))
        innovation = rng.normal(0, 0.012, count)
        residual = np.zeros(count)
        for offset in range(1, count):
            residual[offset] = rho * residual[offset - 1] + innovation[offset]
        logs[b] = common
        logs[a] = 0.5 + beta * common + residual
        pairs.append(
            {
                "pair_id": f"{a}__{b}",
                "leg_a": a,
                "leg_b": b,
                "peer_group": f"Synthetic peer group {number + 1}",
                "active_from": None,
                "active_to": None,
            }
        )
    logs["SPY"] = 5 + np.cumsum(rng.normal(0.0002, 0.008, count))
    logs["XLP"] = 4 + np.cumsum(rng.normal(0.0001, 0.007, count))
    records = []
    for ticker, values in sorted(logs.items()):
        close = np.exp(values)
        volumes = rng.integers(750_000, 5_500_000, count).astype(float)
        open_price = close * np.exp(rng.normal(0, 0.002, count))
        high = np.maximum(open_price, close) * 1.01
        low = np.minimum(open_price, close) * 0.99
        for number, row in enumerate(schedule.to_dict("records")):
            records.append(
                {
                    "ticker": ticker,
                    "trading_date": row["trading_date"],
                    "open": open_price[number],
                    "high": high[number],
                    "low": low[number],
                    "close": close[number],
                    "adj_close": close[number],
                    "volume": volumes[number],
                    "data_available_at": row["data_available_at"],
                    "quality_flag": "OK",
                    "source_provider": "SYNTHETIC",
                    "synthetic": True,
                    "source_snapshot_id": f"synthetic-p3-{ticker}",
                    "sha256": hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest(),
                    "daily_log_return": values[number] - values[number - 1] if number else np.nan,
                }
            )
    prices = pd.DataFrame(records)
    identity = hashlib.sha256(
        pd.util.hash_pandas_object(prices, index=False).to_numpy(dtype="uint64").tobytes()
    ).hexdigest()
    data_id = "synthetic_p3_" + identity[:24]
    prices["data_snapshot_id"] = data_id
    prices["dollar_volume"] = prices["close"] * prices["volume"]
    vix = schedule[["trading_date"]].copy()
    vix["vix_close"] = 20 + 3 * np.sin(np.arange(count) / 30) + rng.normal(0, 0.3, count)
    vix["vix_observed_at_utc"] = (
        pd.to_datetime(vix["trading_date"].astype(str) + " 16:16:00")
        .dt.tz_localize("America/New_York")
        .dt.tz_convert("UTC")
    )
    vix["quality_flag"] = "OK"
    vix["data_snapshot_id"] = data_id
    vix["source_snapshot_id"] = "synthetic-p3-vix"
    vix["sha256"] = hashlib.sha256(vix["vix_close"].to_numpy(dtype="<f8").tobytes()).hexdigest()
    combined_identity = hashlib.sha256((identity + str(vix.iloc[0]["sha256"])).encode()).hexdigest()
    data_id = "synthetic_p3_" + combined_identity[:24]
    prices["data_snapshot_id"] = data_id
    vix["data_snapshot_id"] = data_id
    context = build_market_context(prices, vix, ("XLP",))
    context["synthetic"] = True
    securities = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "sector_etf": "XLP",
                "sector": "SYNTHETIC",
                "active_from": None,
                "active_to": None,
                "data_snapshot_id": data_id,
            }
            for ticker in sorted(set(logs) - {"SPY", "XLP"})
        ]
    )
    return prices, pd.DataFrame(pairs), securities, context, data_id

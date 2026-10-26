"""Per-stock trading cost model (DECISIONS 95, amended in 95a).

Per leg and side, point-in-time at the signal date: a half spread tiered by
20-session dollar ADV (Decision 95a; the Abdi-Ranaldo estimate is kept as a
diagnostic column), plus square-root market impact Y * sigma * sqrt(Q / V),
plus a commission. Q is
the leg's notional for an assumed capital at 25 % of NAV per entry, split by
the frozen position's gross shares. The per-trade rate is the leg-gross-weighted
average of the two legs.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

IMPACT_Y = 0.7
COMMISSION_BPS = 0.5
CAP_BPS = 200.0
ENTRY_FRACTION = 0.25
SPREAD_WINDOW = 60
VOL_WINDOW = 20


def stock_inputs(prices: pd.DataFrame) -> pd.DataFrame:
    """Per ticker and session: half-spread (bps), 20-session volatility and dollar ADV."""
    px = prices.loc[prices["close"].gt(0) & prices["high"].ge(prices["low"])].copy()
    px["trading_date"] = pd.to_datetime(px["trading_date"])
    px = px.sort_values(["ticker", "trading_date"])
    c = np.log(px["close"])
    eta = (np.log(px["high"]) + np.log(px["low"])) / 2
    group = px["ticker"]
    # Product for the pair (t-1, t) uses c[t-1], eta[t-1], eta[t]: known at the close of t.
    product = (c.groupby(group).shift(1) - eta.groupby(group).shift(1)) * (
        c.groupby(group).shift(1) - eta
    )
    mean = product.groupby(group).transform(
        lambda s: s.rolling(SPREAD_WINDOW, min_periods=30).mean()
    )
    px["half_spread_bps"] = np.sqrt(np.maximum(4 * mean, 0.0)) / 2 * 1e4
    returns = np.log(px["adj_close"]).groupby(group).diff()
    px["vol20"] = returns.groupby(group).transform(
        lambda s: s.rolling(VOL_WINDOW, min_periods=15).std()
    )
    px["adv20"] = (
        (px["close"] * px["volume"])
        .groupby(group)
        .transform(lambda s: s.rolling(VOL_WINDOW, min_periods=15).mean())
    )
    return px.set_index(["ticker", "trading_date"])[["half_spread_bps", "vol20", "adv20"]]


def tier_half_spread_bps(adv: float) -> float:
    """Typical effective half spread of US large caps by dollar ADV (Decision 95a)."""
    if adv >= 200e6:
        return 1.0
    if adv >= 50e6:
        return 2.0
    if adv >= 20e6:
        return 4.0
    return 8.0


def lookup(inputs: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], tuple[float, float, float]]:
    values = inputs[["half_spread_bps", "vol20", "adv20"]].to_numpy(dtype=float)
    return {
        (str(t), pd.Timestamp(d)): (float(h), float(v), float(a))
        for (t, d), (h, v, a) in zip(inputs.index, values, strict=True)
    }


def trade_rate_bps(
    table: dict[tuple[str, pd.Timestamp], tuple[float, float, float]],
    request: Any,
    frozen: Any,
    capital: float,
    entry_fraction: float = ENTRY_FRACTION,
) -> float | None:
    """Per-side cost rate of one trade (bps of gross), or None when inputs are missing."""
    if frozen.entry is None or frozen.position is None:
        return None
    day = pd.Timestamp(request.sessions[0].session_date)
    gross_a = abs(frozen.position.units_a) * frozen.entry.price_a
    gross_b = abs(frozen.position.units_b) * frozen.entry.price_b
    total = gross_a + gross_b
    rate = 0.0
    for ticker, gross in ((request.leg_a, gross_a), (request.leg_b, gross_b)):
        values = table.get((str(ticker), day))
        if values is None:
            return None
        _, vol, adv = values
        if not (math.isfinite(vol) and math.isfinite(adv)) or adv <= 0:
            return None
        half = tier_half_spread_bps(adv)
        share = gross / total
        notional = entry_fraction * capital * share
        impact = IMPACT_Y * vol * math.sqrt(notional / adv) * 1e4
        rate += share * min(half + impact + COMMISSION_BPS, CAP_BPS)
    return rate

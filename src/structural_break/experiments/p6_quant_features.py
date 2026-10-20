"""Point-in-time research features for the quant program (DECISIONS 75).

Five blocks, each computed from information available at the signal close:

- ``peer``: cross-sectional context from every pair's daily z-score
  (Chen, Chen, Chen and Li 2019; Avellaneda and Lee 2010). Each stock's
  displacement is measured against all its other peers, which separates a
  stock-specific shock (the stock is out of line with everyone) from noise in
  one relationship; plus market-wide divergence breadth.
- ``state``: extra relationship diagnostics from the daily pair state
  (zero crossings over 252 days, AR(1) rho, error-correction speed, CUSUM).
- ``track``: each pair's and each stock's record of earlier events whose labels
  had resolved before the signal date, shrunk towards the running base rate.
- ``earnings``: days since each leg's last earnings 8-K (Item 2.02) and the
  estimated days to its next one (median of its last four gaps), and whether
  the next is due within the 20-session holding window.
- ``momentum``: each leg's 20- and 120-session log return and distance to its
  252-session high, aligned with the divergence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REGISTRY = "artifacts/research/research_registry_0bd415d2a5af1f4891dc1f0d"
STATE_COLUMNS = [
    "pair_id",
    "trading_date",
    "z_score",
    "fresh_threshold_crossing",
    "zero_crossings_252d",
    "days_since_zero_cross",
    "ar1_rho",
    "error_correction_phi",
    "cusum_pvalue",
    "relationship_age_months",
]
SHRINK = 10.0
_ITEM = re.compile(r"\b\d+\.\d+\b")

PEER = (
    "peer_a_aligned_z",
    "peer_b_aligned_z",
    "peer_max_aligned_z",
    "peer_gap_aligned_z",
    "peer_a_share_diverged",
    "peer_b_share_diverged",
    "peer_a_n_pairs",
    "peer_b_n_pairs",
    "market_share_diverged",
    "market_fresh_crossings",
)
STATE = (
    "state_zero_crossings_252d",
    "state_days_since_zero_cross",
    "state_ar1_rho",
    "state_error_correction_phi",
    "state_relationship_age_months",
)
TRACK = (
    "track_pair_n",
    "track_pair_rate",
    "track_pair_stop_rate",
    "track_pair_last_success",
    "track_pair_days_since_last",
    "track_stock_a_rate",
    "track_stock_b_rate",
    "track_base_rate",
)
EARNINGS = (
    "earn_a_days_since",
    "earn_b_days_since",
    "earn_a_days_to_next",
    "earn_b_days_to_next",
    "earn_either_in_horizon",
    "earn_mover_in_horizon",
)
MOMENTUM = (
    "mom_a_ret20_aligned",
    "mom_b_ret20_aligned",
    "mom_a_ret120_aligned",
    "mom_b_ret120_aligned",
    "mom_a_from_high",
    "mom_b_from_high",
)
BLOCKS = {
    "peer": PEER,
    "state": STATE,
    "track": TRACK,
    "earnings": EARNINGS,
    "momentum": MOMENTUM,
}


def load_state(workspace: Path) -> pd.DataFrame:
    folder = workspace / REGISTRY / "pairs"
    parts = [
        pd.read_parquet(path / "daily_pair_state.parquet", columns=STATE_COLUMNS)
        for path in sorted(folder.iterdir())
        if path.is_dir()
    ]
    state = pd.concat(parts, ignore_index=True)
    state["trading_date"] = pd.to_datetime(state["trading_date"])
    legs = state["pair_id"].str.split("__", expand=True)
    state["leg_a"], state["leg_b"] = legs[0], legs[1]
    return state


def peer_features(events: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    """Each leg's displacement against its other peers, aligned with the divergence."""
    z = state.loc[
        state["z_score"].notna(), ["pair_id", "trading_date", "leg_a", "leg_b", "z_score"]
    ]
    # Signed z per (stock, pair, day): positive means the stock is rich in that pair.
    long = pd.concat(
        [
            z.assign(stock=z["leg_a"], sz=z["z_score"]),
            z.assign(stock=z["leg_b"], sz=-z["z_score"]),
        ],
        ignore_index=True,
    )[["stock", "pair_id", "trading_date", "sz"]]
    long["rich"] = long["sz"].ge(2.0).astype(float)
    long["cheap"] = long["sz"].le(-2.0).astype(float)
    totals = long.groupby(["stock", "trading_date"]).agg(
        sum_sz=("sz", "sum"), n=("sz", "size"), rich=("rich", "sum"), cheap=("cheap", "sum")
    )
    day = state.groupby("trading_date").agg(
        diverged=("z_score", lambda s: float((s.abs() >= 2.0).mean())),
        fresh=("fresh_threshold_crossing", lambda s: float(s.fillna(False).astype(bool).sum())),
    )
    out = pd.DataFrame(index=events.index)
    date = pd.to_datetime(events["event_date"])
    sign = np.sign(events["entry_z"].astype(float).to_numpy())
    own = events["entry_z"].astype(float)
    for leg, own_sz, direction in (("a", own, sign), ("b", -own, -sign)):
        key = pd.MultiIndex.from_arrays([events[f"leg_{leg}"], date])
        row = totals.reindex(key)
        others = row["n"].to_numpy() - 1
        other_sum = row["sum_sz"].to_numpy() - own_sz.to_numpy()
        mean_other = np.where(others > 0, other_sum / np.maximum(others, 1), np.nan)
        # Same-direction divergences of this leg in its other pairs.
        same = np.where(direction > 0, row["rich"].to_numpy(), row["cheap"].to_numpy()) - 1
        out[f"peer_{leg}_aligned_z"] = direction * mean_other
        out[f"peer_{leg}_share_diverged"] = np.where(
            others > 0, same / np.maximum(others, 1), np.nan
        )
        out[f"peer_{leg}_n_pairs"] = row["n"].to_numpy()
    out["peer_max_aligned_z"] = out[["peer_a_aligned_z", "peer_b_aligned_z"]].max(axis=1)
    out["peer_gap_aligned_z"] = (out["peer_a_aligned_z"] - out["peer_b_aligned_z"]).abs()
    daily = day.reindex(date)
    out["market_share_diverged"] = daily["diverged"].to_numpy()
    out["market_fresh_crossings"] = daily["fresh"].to_numpy()
    return out


def state_features(events: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    keyed = state.set_index(["pair_id", "trading_date"])
    key = pd.MultiIndex.from_arrays([events["pair_id"], pd.to_datetime(events["event_date"])])
    row = keyed.reindex(key)
    out = pd.DataFrame(index=events.index)
    for column in STATE:
        out[column] = row[column.removeprefix("state_")].astype(float).to_numpy()
    return out


def track_features(events: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """Outcomes of earlier events resolved strictly before each event's signal date."""
    history = events[["event_id", "pair_id", "leg_a", "leg_b"]].merge(
        targets[["event_id", "y_revert_success", "outcome_type", "resolution_date"]], on="event_id"
    )
    history = history.loc[history["y_revert_success"].notna()].copy()
    history["resolved"] = pd.to_datetime(history["resolution_date"])
    history = history.sort_values("resolved")
    history["stopped"] = history["outcome_type"].eq("STOPPED").astype(float)
    dates = pd.to_datetime(events["event_date"])
    resolved = history["resolved"].to_numpy()
    success = history["y_revert_success"].to_numpy(float)
    cum_success = np.cumsum(success)
    position = np.searchsorted(resolved, dates.to_numpy(), side="left")
    base = np.where(
        position > 0, cum_success[np.maximum(position - 1, 0)] / np.maximum(position, 1), np.nan
    )
    out = pd.DataFrame(index=events.index)
    out["track_base_rate"] = base

    def grouped(
        keys: pd.Series, own_keys: pd.Series
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n = np.zeros(len(events))
        s = np.zeros(len(events))
        stop = np.zeros(len(events))
        last = np.full(len(events), np.nan)
        since = np.full(len(events), np.nan)
        frame = pd.DataFrame(
            {"key": own_keys.to_numpy(), "date": dates.to_numpy(), "row": np.arange(len(events))}
        )
        by_key = dict(tuple(history.groupby(keys)))
        for key, part in frame.groupby("key"):
            past = by_key.get(key)
            if past is None or past.empty:
                continue
            times = past["resolved"].to_numpy()
            ys = past["y_revert_success"].to_numpy(float)
            cs, cstop = np.cumsum(ys), np.cumsum(past["stopped"].to_numpy())
            idx = np.searchsorted(times, part["date"].to_numpy(), side="left")
            rows = part["row"].to_numpy()
            has = idx > 0
            n[rows] = idx
            s[rows[has]] = cs[idx[has] - 1]
            stop[rows[has]] = cstop[idx[has] - 1]
            last[rows[has]] = ys[idx[has] - 1]
            gap = part["date"].to_numpy()[has] - times[idx[has] - 1]
            since[rows[has]] = gap / np.timedelta64(1, "D")
        return n, s, stop, last, since

    prior = np.nan_to_num(base, nan=0.08)
    n, s, stop, last, since = grouped(history["pair_id"], events["pair_id"])
    out["track_pair_n"] = n
    out["track_pair_rate"] = (s + SHRINK * prior) / (n + SHRINK)
    out["track_pair_stop_rate"] = np.where(n > 0, stop / np.maximum(n, 1), np.nan)
    out["track_pair_last_success"] = last
    out["track_pair_days_since_last"] = since
    for leg in ("a", "b"):
        stock_keys = pd.concat([history["leg_a"], history["leg_b"]])
        doubled = pd.concat([history, history])
        doubled = doubled.assign(stock=stock_keys.to_numpy()).sort_values("resolved")
        stock_events = events[f"leg_{leg}"]
        rate = np.full(len(events), np.nan)
        frame = pd.DataFrame(
            {
                "key": stock_events.to_numpy(),
                "date": dates.to_numpy(),
                "row": np.arange(len(events)),
            }
        )
        for key, part in frame.groupby("key"):
            past = doubled.loc[doubled["stock"].eq(key)]
            if past.empty:
                rate[part["row"].to_numpy()] = prior[part["row"].to_numpy()]
                continue
            times = past["resolved"].to_numpy()
            cs = np.cumsum(past["y_revert_success"].to_numpy(float))
            idx = np.searchsorted(times, part["date"].to_numpy(), side="left")
            rows = part["row"].to_numpy()
            successes = np.where(idx > 0, cs[np.maximum(idx - 1, 0)], 0.0)
            rate[rows] = (successes + SHRINK * prior[rows]) / (idx + SHRINK)
        out[f"track_stock_{leg}_rate"] = rate
    return out


def earnings_features(
    events: pd.DataFrame, filings: pd.DataFrame, pairs: pd.DataFrame
) -> pd.DataFrame:
    """Earnings calendar per leg from Item 2.02 8-K acceptance times (upper-bound availability)."""
    rows = filings.loc[filings["form"].isin(["8-K", "8-K/A"])].copy()
    rows["earnings"] = rows["items"].astype(str).map(lambda v: "2.02" in _ITEM.findall(v))
    rows = rows.loc[rows["earnings"]]
    rows["accepted"] = pd.to_datetime(rows["acceptance_datetime_utc"], utc=True).dt.tz_localize(
        None
    )
    by_security = {
        k: g["accepted"].sort_values().to_numpy() for k, g in rows.groupby("security_id")
    }
    legs = events[["pair_id"]].merge(
        pairs[["pair_id", "leg_a_security_id", "leg_b_security_id"]], on="pair_id", how="left"
    )
    # The signal is at the close; anything accepted by 21:00 UTC that day is known.
    cutoff = pd.to_datetime(events["event_date"]).to_numpy() + np.timedelta64(21, "h")
    out = pd.DataFrame(index=events.index)
    for leg in ("a", "b"):
        since = np.full(len(events), np.nan)
        to_next = np.full(len(events), np.nan)
        for security, index in legs.groupby(f"leg_{leg}_security_id").groups.items():
            times = by_security.get(str(security))
            if times is None or not len(times):
                continue
            positions = np.asarray(list(index))
            when = cutoff[positions]
            idx = np.searchsorted(times, when, side="right")
            has = idx > 0
            last = times[np.maximum(idx - 1, 0)]
            since[positions[has]] = (when[has] - last[has]) / np.timedelta64(1, "D")
            for j, k in zip(positions[has], idx[has], strict=True):
                gaps = np.diff(times[max(0, k - 5) : k]) / np.timedelta64(1, "D")
                gaps = gaps[(gaps > 30) & (gaps < 200)]
                cadence = float(np.median(gaps)) if len(gaps) else 91.0
                to_next[j] = cadence - (cutoff[j] - times[k - 1]) / np.timedelta64(1, "D")
        out[f"earn_{leg}_days_since"] = since
        out[f"earn_{leg}_days_to_next"] = to_next
    window = 30.0  # about 20 sessions
    a_in = out["earn_a_days_to_next"].between(-5, window)
    b_in = out["earn_b_days_to_next"].between(-5, window)
    out["earn_either_in_horizon"] = (a_in | b_in).astype(float)
    mover_a = events["abnormal_return_A_1d"].abs() >= events["abnormal_return_B_1d"].abs()
    out["earn_mover_in_horizon"] = np.where(mover_a, a_in, b_in).astype(float)
    return out


def momentum_features(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    px = prices.loc[prices["adj_close"].gt(0), ["ticker", "trading_date", "adj_close"]].copy()
    px["trading_date"] = pd.to_datetime(px["trading_date"])
    px = px.sort_values(["ticker", "trading_date"])
    logp = np.log(px["adj_close"])
    grouped = logp.groupby(px["ticker"])
    px["ret20"] = logp - grouped.shift(20)
    px["ret120"] = logp - grouped.shift(120)
    px["from_high"] = logp - grouped.transform(lambda s: s.rolling(252, min_periods=120).max())
    keyed = px.set_index(["ticker", "trading_date"])
    date = pd.to_datetime(events["event_date"])
    sign = np.sign(events["entry_z"].astype(float).to_numpy())
    out = pd.DataFrame(index=events.index)
    for leg, direction in (("a", sign), ("b", -sign)):
        row = keyed.reindex(pd.MultiIndex.from_arrays([events[f"leg_{leg}"], date]))
        out[f"mom_{leg}_ret20_aligned"] = direction * row["ret20"].to_numpy()
        out[f"mom_{leg}_ret120_aligned"] = direction * row["ret120"].to_numpy()
        out[f"mom_{leg}_from_high"] = row["from_high"].to_numpy()
    return out


def build_all(
    events: pd.DataFrame,
    workspace: Path,
    filings: pd.DataFrame,
    pairs: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    state = load_state(workspace)
    targets = pd.read_parquet(workspace / REGISTRY / "h20_targets.parquet")
    parts: list[Any] = [
        peer_features(events, state),
        state_features(events, state),
        track_features(events, targets),
        earnings_features(events, filings, pairs),
        momentum_features(events, prices),
    ]
    return pd.concat([events[["event_id"]], *parts], axis=1)


# --------------------------------------------------------------------------- #
# Stage A2 block (DECISIONS 81)
# --------------------------------------------------------------------------- #

EXTRA = (
    "extra_sector_share_diverged",
    "extra_a_disp_change5",
    "extra_b_disp_change5",
    "extra_a_vol60",
    "extra_b_vol60",
    "extra_vol_ratio",
)


def extra_features(events: pd.DataFrame, state: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Sector divergence breadth, 5-session change in each leg's displacement, leg volatility."""
    out = pd.DataFrame(index=events.index)
    date = pd.to_datetime(events["event_date"])
    sector_of = events.drop_duplicates("pair_id").set_index("pair_id")["sector"]
    z = state.loc[
        state["z_score"].notna(), ["pair_id", "trading_date", "leg_a", "leg_b", "z_score"]
    ]
    z = z.assign(sector=z["pair_id"].map(sector_of))
    breadth = (
        z.assign(div=z["z_score"].abs().ge(2.0).astype(float))
        .groupby(["sector", "trading_date"])["div"]
        .mean()
    )
    out["extra_sector_share_diverged"] = breadth.reindex(
        pd.MultiIndex.from_arrays([events["sector"], date])
    ).to_numpy()
    long = pd.concat(
        [
            z.assign(stock=z["leg_a"], sz=z["z_score"]),
            z.assign(stock=z["leg_b"], sz=-z["z_score"]),
        ],
        ignore_index=True,
    )
    disp = long.groupby(["stock", "trading_date"])["sz"].mean().rename("disp").reset_index()
    disp = disp.sort_values(["stock", "trading_date"])
    disp["change5"] = disp["disp"] - disp.groupby("stock")["disp"].shift(5)
    keyed = disp.set_index(["stock", "trading_date"])["change5"]
    sign = np.sign(events["entry_z"].astype(float).to_numpy())
    for leg, direction in (("a", sign), ("b", -sign)):
        values = keyed.reindex(pd.MultiIndex.from_arrays([events[f"leg_{leg}"], date])).to_numpy()
        out[f"extra_{leg}_disp_change5"] = direction * values
    px = prices.loc[prices["adj_close"].gt(0), ["ticker", "trading_date", "adj_close"]].copy()
    px["trading_date"] = pd.to_datetime(px["trading_date"])
    px = px.sort_values(["ticker", "trading_date"])
    returns = np.log(px["adj_close"]).groupby(px["ticker"]).diff()
    px["vol60"] = returns.groupby(px["ticker"]).transform(
        lambda s: s.rolling(60, min_periods=40).std()
    )
    vol = px.set_index(["ticker", "trading_date"])["vol60"]
    for leg in ("a", "b"):
        out[f"extra_{leg}_vol60"] = vol.reindex(
            pd.MultiIndex.from_arrays([events[f"leg_{leg}"], date])
        ).to_numpy()
    out["extra_vol_ratio"] = out["extra_a_vol60"] / out["extra_b_vol60"]
    return out


BLOCKS["extra"] = EXTRA


# --------------------------------------------------------------------------- #
# Stage L block (DECISIONS 94): overnight versus intraday decomposition
# --------------------------------------------------------------------------- #

INTRADAY = (
    "intra_a_overnight",
    "intra_b_overnight",
    "intra_a_intraday",
    "intra_b_intraday",
    "intra_mover_gap_share",
    "intra_a_range_rel",
    "intra_b_range_rel",
    "intra_a_close_location",
    "intra_b_close_location",
)


def intraday_features(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Signal-day overnight gap and intraday move per leg (split-adjusted), aligned."""
    px = prices.loc[prices["close"].gt(0) & prices["adj_close"].gt(0)].copy()
    px["trading_date"] = pd.to_datetime(px["trading_date"])
    px = px.sort_values(["ticker", "trading_date"])
    factor = px["adj_close"] / px["close"]
    open_adj, high_adj, low_adj = px["open"] * factor, px["high"] * factor, px["low"] * factor
    previous = px.groupby("ticker")["adj_close"].shift(1)
    px["overnight"] = np.log(open_adj / previous)
    px["intraday"] = np.log(px["adj_close"] / open_adj)
    span = (high_adj - low_adj) / px["adj_close"]
    px["range_rel"] = span / span.groupby(px["ticker"]).transform(
        lambda s: s.shift(1).rolling(20, min_periods=10).mean()
    )
    px["close_location"] = ((px["adj_close"] - low_adj) / (high_adj - low_adj)).where(
        high_adj > low_adj
    )
    keyed = px.set_index(["ticker", "trading_date"])
    date = pd.to_datetime(events["event_date"])
    sign = np.sign(events["entry_z"].astype(float).to_numpy())
    out = pd.DataFrame(index=events.index)
    for leg, direction in (("a", sign), ("b", -sign)):
        row = keyed.reindex(pd.MultiIndex.from_arrays([events[f"leg_{leg}"], date]))
        out[f"intra_{leg}_overnight"] = direction * row["overnight"].to_numpy()
        out[f"intra_{leg}_intraday"] = direction * row["intraday"].to_numpy()
        out[f"intra_{leg}_range_rel"] = row["range_rel"].to_numpy()
        # Aligned close location: 1 = rich leg closed at its high, cheap leg at its low.
        location = row["close_location"].to_numpy()
        out[f"intra_{leg}_close_location"] = np.where(direction > 0, location, 1 - location)
    mover_a = events["abnormal_return_A_1d"].abs() >= events["abnormal_return_B_1d"].abs()
    gap = np.where(mover_a, out["intra_a_overnight"], out["intra_b_overnight"])
    move = np.where(mover_a, out["intra_a_intraday"], out["intra_b_intraday"])
    total = np.abs(gap) + np.abs(move)
    out["intra_mover_gap_share"] = np.where(
        total > 0, np.abs(gap) / np.where(total > 0, total, 1), np.nan
    )
    return out


BLOCKS["intraday"] = INTRADAY

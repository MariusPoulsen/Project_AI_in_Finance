"""Residual-reversal sleeve and a netted stock-level book (DECISIONS 101-103).

Signals follow Avellaneda & Lee (2010): each stock's daily return is
regressed over 60 sessions on factors (its sector ETF, or 15 PCA
eigenportfolios), the cumulative residual is fitted as an AR(1), and the
s-score measures how far it sits from its equilibrium. Raw weights are made
neutral to sectors and market beta by projection, which nets the factor
hedges into stock positions.

``run_book`` is a daily open-to-open engine for a book of stock dollar
holdings. It takes a residual sleeve (target weights decided at each close)
and a pairs sleeve (legs with entry and exit sessions that drift with
prices), sums the two sleeves' trades per stock and charges per-stock costs
on the net trade (or per sleeve, to measure the netting saving).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from structural_break.experiments import p6_quant_costs as qc

WINDOW = 60
PCA_WINDOW = 252
FACTORS = 15
KAPPA_MIN = 252 / 30
OPEN_BAND = 1.25
CLOSE_LONG = -0.50
CLOSE_SHORT = 0.75
CLIP = 3.0
TRADE_BAND = 0.0015
BORROW = 0.01
CASH_HAIRCUT = 0.0025
SECTOR_ETF = {
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Industrials": "XLI",
    "Health Care": "XLV",
    "Information Technology": "XLK",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Communication Services": "SPY",
}


@dataclass
class Panels:
    dates: pd.DatetimeIndex
    tickers: list[str]
    returns: np.ndarray  # close-to-close, dates x tickers
    open_returns: np.ndarray  # open d to open d+1, indexed at d
    etf: dict[str, np.ndarray]  # close-to-close factor returns
    vol20: np.ndarray
    adv20: np.ndarray
    sectors: list[str]


def load_panels(prices: pd.DataFrame, sectors: dict[str, str]) -> Panels:
    px = prices.copy()
    px["trading_date"] = pd.to_datetime(px["trading_date"])
    wide = {
        c: px.pivot(index="trading_date", columns="ticker", values=c).sort_index()
        for c in ("open", "close", "adj_close")
    }
    factor = wide["adj_close"] / wide["close"]
    adj_open = wide["open"] * factor
    close_ret = wide["adj_close"].pct_change(fill_method=None)
    open_ret = adj_open.shift(-1) / adj_open - 1
    tickers = sorted(t for t in sectors if t in close_ret.columns)
    inputs = qc.stock_inputs(prices)
    vol = inputs["vol20"].unstack(0).reindex(index=close_ret.index, columns=tickers)
    adv = inputs["adv20"].unstack(0).reindex(index=close_ret.index, columns=tickers)
    etf = {e: close_ret[e].to_numpy(float) for e in set(SECTOR_ETF.values())}
    return Panels(
        dates=pd.DatetimeIndex(close_ret.index),
        tickers=tickers,
        returns=close_ret[tickers].to_numpy(float),
        open_returns=open_ret[tickers].to_numpy(float),
        etf=etf,
        vol20=vol.to_numpy(float),
        adv20=adv.to_numpy(float),
        sectors=[sectors[t] for t in tickers],
    )


def ou_scores(residuals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """s-score and kappa per column of a (window x stocks) residual matrix."""
    x = np.cumsum(residuals, axis=0)
    a0, a1 = x[:-1], x[1:]
    m0, m1 = a0.mean(axis=0), a1.mean(axis=0)
    cov = ((a0 - m0) * (a1 - m1)).sum(axis=0)
    var = ((a0 - m0) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        b = cov / var
        a = m1 - b * m0
        zeta = a1 - (a + b * a0)
        kappa = np.where((b > 0) & (b < 1), -np.log(b) * 252, np.nan)
        m = a / (1 - b)
        sigma_eq = np.sqrt(zeta.var(axis=0) / (1 - b**2))
        ok = np.isfinite(kappa) & np.isfinite(m) & (sigma_eq > 0)
        centred = m - np.nanmean(np.where(ok, m, np.nan))
        # (X_T - m) / sigma_eq; X_T is zero for OLS residuals, giving Avellaneda-Lee's -m / sigma_eq.
        s = np.where(ok, (x[-1] - centred) / sigma_eq, np.nan)
    return s, kappa


def _ols_residuals(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Residuals of y (window x n) on a shared design x (window x k) with intercept."""
    design = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return y - design @ coef


def signals(panels: Panels, model: str, start: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """s-scores, kappa and 60-session SPY beta at every close from ``start``."""
    n_days, n = panels.returns.shape
    s_all = np.full((n_days, n), np.nan)
    k_all = np.full((n_days, n), np.nan)
    beta_all = np.full((n_days, n), np.nan)
    spy = panels.etf["SPY"]
    sector_etf = [SECTOR_ETF[s] for s in panels.sectors]
    for t in range(start, n_days):
        hist = panels.returns[t - PCA_WINDOW + 1 : t + 1]
        eligible = np.isfinite(hist).all(axis=0) & (panels.adv20[t] > 0)
        cols = np.flatnonzero(eligible)
        if len(cols) < 2 * FACTORS:
            continue
        window = hist[-WINDOW:, cols]
        mkt = spy[t - WINDOW + 1 : t + 1]
        if not np.isfinite(mkt).all():
            continue
        mc = mkt - mkt.mean()
        beta_all[t, cols] = (mc @ (window - window.mean(axis=0))) / (mc @ mc)
        if model == "etf":
            resid = np.empty_like(window)
            for e in set(sector_etf[c] for c in cols):
                group = [i for i, c in enumerate(cols) if sector_etf[c] == e]
                f = panels.etf[e][t - WINDOW + 1 : t + 1]
                if not np.isfinite(f).all():
                    f = mkt
                resid[:, group] = _ols_residuals(window[:, group], f[:, None])
        elif model == "pca":
            z = (hist[:, cols] - hist[:, cols].mean(axis=0)) / hist[:, cols].std(axis=0)
            corr = z.T @ z / len(z)
            _, vectors = np.linalg.eigh(corr)
            q = vectors[:, -FACTORS:] / hist[:, cols].std(axis=0)[:, None]
            factors = window @ q
            resid = _ols_residuals(window, factors)
        else:
            raise ValueError(model)
        s, kappa = ou_scores(resid)
        s_all[t, cols] = s
        k_all[t, cols] = kappa
    return s_all, k_all, beta_all


def neutralise(raw: np.ndarray, sectors: Sequence[str], beta: np.ndarray) -> np.ndarray:
    """Project sector dummies and market beta out of raw weights, over stocks with a beta."""
    out = np.zeros_like(raw)
    idx = np.flatnonzero(np.isfinite(beta))
    if len(idx) == 0 or not np.any(raw[idx]):
        return out
    names = sorted(set(sectors[i] for i in idx))
    dummies = np.array([[sectors[i] == s for s in names] for i in idx], dtype=float)
    basis = np.column_stack([dummies, beta[idx]])
    coef, *_ = np.linalg.lstsq(basis, raw[idx], rcond=None)
    out[idx] = raw[idx] - basis @ coef
    return out


def targets(
    panels: Panels,
    s: np.ndarray,
    kappa: np.ndarray,
    beta: np.ndarray,
    rule: str,
    gross: float = 1.0,
) -> np.ndarray:
    """Target weights (fraction of NAV) decided at each close."""
    n_days, n = s.shape
    out = np.zeros((n_days, n))
    state = np.zeros(n)
    for t in range(n_days):
        st, ok = s[t], np.isfinite(s[t])
        if not ok.any():
            state[:] = 0
            continue
        fast = ok & (kappa[t] > KAPPA_MIN)
        if rule == "bands":
            state[~ok] = 0
            state[(state > 0) & ok & (st > CLOSE_LONG)] = 0
            state[(state < 0) & ok & (st < CLOSE_SHORT)] = 0
            flat = state == 0
            state[flat & fast & (st < -OPEN_BAND)] = 1
            state[flat & fast & (st > OPEN_BAND)] = -1
            raw = state.copy()
        elif rule == "continuous":
            raw = np.where(fast, -np.clip(np.nan_to_num(st), -CLIP, CLIP), 0.0)
        else:
            raise ValueError(rule)
        w = neutralise(raw, panels.sectors, np.where(ok, beta[t], np.nan))
        total = np.abs(w).sum()
        if total > 0:
            out[t] = w / total * gross
    return out


@dataclass
class Leg:
    ticker: str
    entry: pd.Timestamp  # held from this session's open (its close when timing="close")
    exit: pd.Timestamp  # closed at this session's open (its close when timing="close")
    fraction: float  # signed dollar weight as a fraction of NAV at entry


def _cost(trade: float, vol: float, adv: float, capital: float, extra_bps: float = 0.0) -> float:
    """Cost in NAV units of trading ``trade`` (NAV units) of one stock."""
    if trade == 0:
        return 0.0
    if not (math.isfinite(vol) and math.isfinite(adv)) or adv <= 0:
        return abs(trade) * qc.CAP_BPS / 1e4
    half = qc.tier_half_spread_bps(adv)
    impact = qc.IMPACT_Y * vol * math.sqrt(abs(trade) * capital / adv) * 1e4
    return abs(trade) * (min(half + impact + qc.COMMISSION_BPS, qc.CAP_BPS) + extra_bps) / 1e4


def run_book(
    panels: Panels,
    resid_targets: np.ndarray | None,
    legs: Sequence[Leg],
    start: pd.Timestamp,
    end: pd.Timestamp,
    capital: float = 1e7,
    net: bool = True,
    band: float = TRADE_BAND,
    rf: pd.Series | None = None,
    speed: float = 1.0,
    every: int = 1,
    vol_target: float | None = None,
    vol_window: int = 60,
    scale_clip: tuple[float, float] = (0.5, 2.0),
    timing: str = "open",
    extra_bps: float = 0.0,
) -> pd.DataFrame:
    """Daily open-to-open book; returns one row per session with NAV and diagnostics.

    ``resid_targets[t]`` is decided at close t and traded at the open of t+1.
    ``rf`` (annual, decimal) adds interest on NAV at the previous close's rate.
    Turnover controls for the residual sleeve: ``speed`` trades that fraction
    of each gap beyond the band (Garleanu-Pedersen partial trading), and
    ``every`` trades only on every n-th session of the run (exits to a zero
    target are always traded in full).
    ``vol_target`` (annual) scales new pair entries and residual targets by
    vol_target / realised book volatility over the last ``vol_window``
    sessions, clipped to ``scale_clip``; open pair legs are not resized.
    ``timing="close"`` trades at the signal session's close instead of the
    next open: targets[t] trade at close t and holdings earn close-to-close
    returns. ``extra_bps`` adds a flat cost per side (a stress test).
    """
    index = {d: i for i, d in enumerate(panels.dates)}
    n = len(panels.tickers)
    col = {t: i for i, t in enumerate(panels.tickers)}
    entries: dict[int, list[Leg]] = {}
    exits: dict[int, list[int]] = {}
    for k, leg in enumerate(legs):
        if leg.ticker not in col or leg.entry not in index or leg.exit not in index:
            continue
        entries.setdefault(index[leg.entry], []).append(leg)
        exits.setdefault(index[leg.exit], []).append(k)
    leg_value: dict[int, float] = {}
    leg_key = {id(leg): k for k, leg in enumerate(legs)}
    resid = np.zeros(n)
    nav = 1.0
    rows = []
    days = [i for i, d in enumerate(panels.dates) if start <= d <= end]
    rates = rf.reindex(panels.dates).ffill().to_numpy(float) if rf is not None else None
    at_close = timing == "close"
    history: list[float] = []
    for step, t in enumerate(days):
        scale = 1.0
        if vol_target is not None and len(history) >= 20:
            realised = float(np.std(history[-vol_window:])) * math.sqrt(252)
            if realised > 0:
                scale = min(max(vol_target / realised, scale_clip[0]), scale_clip[1])
        d_pairs = np.zeros(n)
        for k in exits.get(t, ()):
            if k in leg_value:
                d_pairs[col[legs[k].ticker]] -= leg_value.pop(k)
        for leg in entries.get(t, ()):
            k = leg_key[id(leg)]
            value = leg.fraction * scale * nav
            leg_value[k] = value
            d_pairs[col[leg.ticker]] += value
        d_resid = np.zeros(n)
        signal_day = t if at_close else t - 1
        if resid_targets is not None and signal_day >= 0:
            want = resid_targets[signal_day] * scale * nav
            gap = want - resid
            close = (want == 0) & (resid != 0)
            if step % every == 0:
                move = (np.abs(gap) > band * nav) & ~close
                d_resid[move] = speed * gap[move]
            d_resid[close] = gap[close]
            resid = resid + d_resid
        vol, adv = panels.vol20[signal_day], panels.adv20[signal_day]
        cost = 0.0
        for i in np.flatnonzero((d_pairs != 0) | (d_resid != 0)):
            if net:
                cost += _cost(d_pairs[i] + d_resid[i], vol[i], adv[i], capital * nav, extra_bps)
            else:
                cost += _cost(d_pairs[i], vol[i], adv[i], capital * nav, extra_bps)
                cost += _cost(d_resid[i], vol[i], adv[i], capital * nav, extra_bps)
        traded = float(np.abs(d_pairs + d_resid).sum())
        pairs_hold = np.zeros(n)
        for k, value in leg_value.items():
            pairs_hold[col[legs[k].ticker]] += value
        hold = pairs_hold + resid
        if at_close:
            r = np.nan_to_num(panels.returns[t + 1]) if t + 1 < len(panels.dates) else np.zeros(n)
        else:
            r = np.nan_to_num(panels.open_returns[t])
        borrow = -hold[hold < 0].sum() * BORROW / 252
        pnl = float(hold @ r)
        interest = 0.0
        if rates is not None and signal_day >= 0 and math.isfinite(rates[signal_day]):
            interest = nav * max(rates[signal_day] - CASH_HAIRCUT, 0.0) / 252
        before = nav
        nav = nav + pnl - cost - borrow + interest
        history.append(nav / before - 1)
        resid = resid * (1 + r)
        for k in leg_value:
            leg_value[k] *= 1 + r[col[legs[k].ticker]]
        rows.append(
            {
                "session_date": panels.dates[t],
                "nav": nav,
                "daily_return": nav / before - 1,
                "interest": interest / before,
                "cost": cost / before,
                "turnover": traded / before,
                "gross": float(np.abs(hold).sum()) / before,
                "net_exposure": float(hold.sum()) / before,
                "names": int((np.abs(hold) > 1e-9).sum()),
                "scale": scale,
            }
        )
    return pd.DataFrame(rows)


def stats(book: pd.DataFrame, first: int, last: int, cash: bool = False) -> dict[str, float]:
    """Sharpe (excess of cash), CAGR and drawdown for calendar years first..last."""
    years = pd.to_datetime(book["session_date"]).dt.year
    part = book.loc[years.between(first, last)]
    excess = part["daily_return"] - part["interest"]
    r = part["daily_return"] if cash else excess
    nav = (1 + r).cumprod()
    return {
        "sharpe": float(excess.mean() / excess.std() * math.sqrt(252)),
        "cagr": float(nav.iloc[-1] ** (252 / len(r)) - 1),
        "maxdd": float((nav / nav.cummax() - 1).min()),
        "vol": float(r.std() * math.sqrt(252)),
        "turnover": float(part["turnover"].mean() * 252),
        "cost": float(part["cost"].mean() * 252),
        "gross": float(part["gross"].mean()),
        "names": float(part["names"].mean()),
    }


def tbill(path: Path) -> pd.Series:
    """13-week T-bill yield (annual, decimal) by date, from the Yahoo ^IRX download."""
    frame = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
    return frame["irx"].astype(float) / 100

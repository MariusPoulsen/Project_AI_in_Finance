"""Pre-registered 2010-2023 portfolio evaluation of the candidate designs (DECISIONS 73).

Each design runs as one continuous fixed-share portfolio from 2010 to the end
of development (2023-12-29) under the frozen Decision 36 portfolio policy:
start NAV 1, 25 % of NAV per entry, gross capped at 100 % of NAV, one position
per pair, frozen headline costs and borrow. ``research_portfolio`` is a copy of
``backtest.portfolio.simulate_portfolio`` with two additions only: trade
results are supplied (so the E3 news exit can be used) and each entry's target
can be scaled by a weight (VIX sizing). With frozen results and unit weights it
reproduces the frozen portfolio exactly, which ``verify`` checks.

Designs:
P0 Baseline 0, every divergence, frozen exit (the original strategy);
P1 R0 top-20 % selections (Decision 45 XGBoost Model B), frozen exit;
P2 P1 with the E3 news exit (primary candidate);
P3 P2 with VIX-proportional sizing (secondary candidate);
P4 P2 skipping R1 events (fresh earnings or negative news on the mover).
The 2024-2025 final test is not read.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from structural_break.backtest.contracts import (
    ExecutionConfig,
    PairTradeResult,
    canonical_sessions,
)
from structural_break.backtest.portfolio import (
    DEVELOPMENT_END,
    PortfolioPolicy,
    PortfolioProposal,
)

PLAN_VERSION = "p6-portfolio-designs-v1"
TARGETS = {"frozen_25pct": 0.25, "sensitivity_10pct": 0.10}
PERIODS = {"2010-2015": (2010, 2015), "2016-2021": (2016, 2021), "2022-2023": (2022, 2023)}
TRADING_DAYS = 252
TOLERANCE = 1e-10


# --------------------------------------------------------------------------- #
# E3 news-exit trade results
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Research copy of the frozen portfolio (supplied results, weighted targets)
# --------------------------------------------------------------------------- #


def research_portfolio(
    proposals: Sequence[PortfolioProposal],
    results: dict[str, PairTradeResult],
    weights: dict[str, float],
    policy: PortfolioPolicy,
    config: ExecutionConfig,
    target: float,
    rates: dict[str, float] | None = None,
    sector_cap: float | None = None,
) -> dict[str, Any]:
    """``simulate_portfolio`` accounting with supplied results and per-entry weights.

    Differences from the frozen function: ``results`` replaces the internal
    simulator call; each eligible entry wants ``target * NAV * weight`` and,
    when the wanted total exceeds the available gross capacity, every entry is
    scaled by the same factor (with unit weights this is the frozen equal clip).
    Marks are returned as plain rows. Decision 96 adds two optional controls:
    ``rates`` gives a per-event cost rate (bps per side) in place of the flat
    entry and exit rates, and ``sector_cap`` limits each sector's gross
    exposure to that fraction of NAV at entry.
    """
    assert config.entry_cost_bps is not None and config.exit_cost_bps is not None
    assert config.annual_borrow_rate is not None
    ordered = sorted(proposals, key=lambda p: (p.request.signal_at, p.request.event_id))
    starts = [p.request.sessions[0].session_date for p in ordered]
    ends = [p.request.sessions[-1].session_date for p in ordered]
    last_declared_day = max(ends)
    sessions = list(canonical_sessions(min(starts), last_declared_day))
    pending: dict[date, list[PortfolioProposal]] = {}
    status: dict[str, str] = {}
    held: dict[str, dict[str, Any]] = {}
    allocations: dict[str, float] = {}
    cash = policy.initial_nav
    unknown_at: datetime | None = None
    rows: list[dict[str, Any]] = []
    previous_close = policy.initial_nav
    peak = policy.initial_nav
    entry_rate = config.entry_cost_bps / 10000.0
    for proposal in ordered:
        event = proposal.request
        if not proposal.selected:
            status[event.event_id] = "NOT_SELECTED"
        elif len(event.sessions) < 2:
            status[event.event_id] = "NOT_ENTERED"
        else:
            pending.setdefault(event.sessions[1].session_date, []).append(proposal)
    bars = {p.request.event_id: {b.session_date: b for b in p.request.prices} for p in ordered}

    def fail(position: dict[str, Any], at: datetime) -> None:
        nonlocal unknown_at
        position["unresolved"] = True
        if unknown_at is None:
            unknown_at = at

    def quote(position: dict[str, Any], day: date, phase: str) -> tuple[float, float] | None:
        bar = bars[position["event_id"]].get(day)
        if bar is None:
            return None
        a = bar.open_a if phase == "OPEN" else bar.close_a
        b = bar.open_b if phase == "OPEN" else bar.close_b
        return None if a is None or b is None else (a, b)

    def values(day: date, phase: str, at: datetime) -> tuple[float, float]:
        gross = net = 0.0
        for position in held.values():
            if position["unresolved"]:
                continue
            termination = position["proposal"].request.lifecycle_termination
            if termination is not None and day >= termination:
                fail(position, at)
                continue
            prices = quote(position, day, phase)
            if prices is None:
                fail(position, at)
                continue
            for units, price in ((position["a"], prices[0]), (position["b"], prices[1])):
                gross += abs(units) * price
                net += units * price
        return gross, net

    index = 0
    while index < len(sessions):
        day, opening, closing = sessions[index]
        index += 1
        borrow = 0.0
        for position in held.values():
            if day > position["entry_day"] and not position["unresolved"]:
                charge = (
                    position["entry_short"]
                    * config.annual_borrow_rate
                    / config.annual_trading_sessions
                )
                position["borrow"] += charge
                borrow += charge
        cash -= borrow
        values(day, "OPEN", opening)
        for pair_id, position in tuple(held.items()):
            result = position["result"]
            if position["unresolved"] or result.exit is None or result.exit.session_date != day:
                continue
            exit_a, exit_b = result.exit.price_a, result.exit.price_b
            exit_bps = (rates or {}).get(position["event_id"], config.exit_cost_bps)
            fee = (abs(position["a"]) * exit_a + abs(position["b"]) * exit_b) * exit_bps / 10000.0
            cash += position["a"] * exit_a + position["b"] * exit_b - fee
            position["trading"] += fee
            pnl = position["a"] * (exit_a - result.entry.price_a) + position["b"] * (
                exit_b - result.entry.price_b
            )
            expected = position["allocation"] * float(result.net_return)
            if not math.isclose(
                pnl - position["trading"] - position["borrow"],
                expected,
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                raise ValueError("Portfolio costs/units do not reconcile with the trade result")
            status[position["event_id"]] = "COMPLETE"
            del held[pair_id]
        gross, net = values(day, "OPEN", opening)
        nav = cash + net if unknown_at is None else None
        eligible: list[PortfolioProposal] = []
        occupied = set(held)
        for proposal in sorted(pending.get(day, ()), key=lambda p: p.request.event_id):
            event = proposal.request
            result = results[event.event_id]
            if result.entry is None:
                status[event.event_id] = "NOT_ENTERED"
            elif event.pair_id in occupied:
                status[event.event_id] = "PAIR_ALREADY_OPEN"
            elif nav is None or nav <= 0:
                status[event.event_id] = "NAV_UNKNOWN_OR_NONPOSITIVE"
            else:
                occupied.add(event.pair_id)
                eligible.append(proposal)
        if eligible:
            assert nav is not None
            capacity = max(
                0.0,
                (policy.gross_entry_cap * nav - gross)
                / (1.0 + policy.gross_entry_cap * entry_rate),
            )
            wanted = {
                p.request.event_id: target * nav * weights.get(p.request.event_id, 1.0)
                for p in eligible
            }
            total = sum(wanted.values())
            scale = min(1.0, capacity / total) if total > 0 else 0.0
            for proposal in eligible:
                event_id = proposal.request.event_id
                allocation = wanted[event_id] * scale
                if allocation <= 1e-15:
                    status[event_id] = "CAPACITY_REJECTED"
                    continue
                result = results[event_id]
                assert result.entry is not None and result.position is not None
                position = {
                    "event_id": event_id,
                    "proposal": proposal,
                    "result": result,
                    "allocation": allocation,
                    "a": allocation * result.position.units_a,
                    "b": allocation * result.position.units_b,
                    "entry_day": result.entry.session_date,
                    "entry_short": allocation * result.position.short_entry_notional,
                    "borrow": 0.0,
                    "trading": allocation
                    * (rates or {}).get(event_id, config.entry_cost_bps)
                    / 10000.0,
                    "unresolved": False,
                }
                cash -= position["a"] * result.entry.price_a + position["b"] * result.entry.price_b
                cash -= allocation * (rates or {}).get(event_id, config.entry_cost_bps) / 10000.0
                held[proposal.request.pair_id] = position
                status[event_id] = "ENTERED"
                allocations[event_id] = allocation / nav
        gross, net = values(day, "CLOSE", closing)
        for position in held.values():
            if position["unresolved"]:
                continue
            observed = {mark.session_date for mark in position["result"].marks}
            if day >= position["entry_day"] and day not in observed:
                fail(position, closing)
        mark_nav = cash + net if unknown_at is None else None
        row: dict[str, Any] = {"session_date": day, "nav": mark_nav, "open_positions": len(held)}
        if mark_nav is not None:
            peak = max(peak, mark_nav)
            row["drawdown"] = mark_nav / peak - 1.0
            row["daily_return"] = mark_nav / previous_close - 1.0 if previous_close > 0 else None
            row["gross_fraction"] = gross / mark_nav if mark_nav > 0 else None
            previous_close = mark_nav
        rows.append(row)
        if day == last_declared_day and held and unknown_at is None:
            following = canonical_sessions(day, day + timedelta(days=14))
            if len(following) >= 2 and following[1][0] <= DEVELOPMENT_END:
                sessions.append(following[1])
            else:
                for position in held.values():
                    fail(position, closing)
    return {"marks": pd.DataFrame(rows), "status": status, "allocations": allocations}


# --------------------------------------------------------------------------- #
# Data assembly
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def metrics(marks: pd.DataFrame) -> dict[str, Any]:
    known = marks.loc[marks["nav"].notna()].copy()
    known["year"] = pd.to_datetime(known["session_date"]).dt.year
    returns = known["daily_return"].astype(float)

    def block(part: pd.DataFrame) -> dict[str, Any]:
        r = part["daily_return"].astype(float)
        growth = float(np.prod(1 + r.to_numpy(dtype=float)))
        years = len(r) / TRADING_DAYS
        nav = (1 + r).cumprod()
        drawdown = float((nav / nav.cummax() - 1).min()) if len(nav) else math.nan
        vol = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
        cagr = growth ** (1 / years) - 1 if years > 0 else math.nan
        return {
            "total_return": growth - 1,
            "cagr": cagr,
            "volatility": vol,
            "sharpe": float(r.mean() / r.std(ddof=1) * math.sqrt(TRADING_DAYS))
            if r.std(ddof=1) > 0
            else math.nan,
            "max_drawdown": drawdown,
            "calmar": cagr / abs(drawdown) if drawdown < 0 else math.nan,
            "mean_gross_fraction": float(part["gross_fraction"].astype(float).mean()),
            "mean_open_positions": float(part["open_positions"].mean()),
            "sessions": int(len(r)),
        }

    result: dict[str, Any] = {"full": block(known), "periods": {}, "years": {}}
    for label, (low, high) in PERIODS.items():
        result["periods"][label] = block(known.loc[known["year"].between(low, high)])
    for year, part in known.groupby("year"):
        growth = np.prod(1 + part["daily_return"].to_numpy(dtype=float))
        result["years"][int(str(year))] = float(growth) - 1.0
    result["final_known_nav"] = float(known["nav"].iloc[-1])
    result["last_known_session"] = str(known["session_date"].iloc[-1])
    result["nav_unknown"] = bool(marks["nav"].isna().any())
    _ = returns
    return result

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

import argparse
import json
import math
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.backtest.contracts import (
    ExecutionConfig,
    PairTradeResult,
    canonical_sessions,
)
from structural_break.backtest.historical import build_historical_events
from structural_break.backtest.portfolio import (
    DEVELOPMENT_END,
    PortfolioPolicy,
    PortfolioProposal,
    simulate_portfolio,
)
from structural_break.backtest.production_policy import load_analysis_policies, load_headline
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.experiments import p6_boosting as pb
from structural_break.experiments import p6_entry_vol as ev
from structural_break.experiments import p6_sec_explore as ex
from structural_break.experiments.p6_halflife_exit import simulate_long
from structural_break.experiments.p6_improvement import _chunks, _sources, _spec
from structural_break.experiments.p6_sec_explore2 import EMPTY, _times, headline_index

PLAN_VERSION = "p6-portfolio-designs-v1"
START, END = date(2010, 1, 1), date(2023, 12, 31)
DESIGNS: dict[str, dict[str, Any]] = {
    "P0_baseline0_frozen": {"population": "all", "exit": "frozen"},
    "P1_model_frozen": {"population": "model", "exit": "frozen"},
    "P2_model_news_exit": {"population": "model", "exit": "e3"},
    "P3_model_news_exit_vix": {"population": "model", "exit": "e3", "vix": True},
    "P4_model_news_exit_r1": {"population": "model", "exit": "e3", "r1": True},
}
TARGETS = {"frozen_25pct": 0.25, "sensitivity_10pct": 0.10}
PERIODS = {"2010-2015": (2010, 2015), "2016-2021": (2016, 2021), "2022-2023": (2022, 2023)}
TRADING_DAYS = 252
TOLERANCE = 1e-10


# --------------------------------------------------------------------------- #
# E3 news-exit trade results
# --------------------------------------------------------------------------- #


def news_exit_result(
    request: Any, frozen: PairTradeResult, moments: Sequence[datetime], config: ExecutionConfig
) -> PairTradeResult:
    """The frozen result with its exit moved to the open after qualifying news (DECISIONS 60).

    The research exit loop (verified against the frozen simulator) decides
    whether and when the news exit fires; the entry, units and costs are the
    frozen ones, so the portfolio ledger reconciles exactly.
    """
    out = simulate_long(request, request.sessions, request.prices, config, 20, moments)
    if out["reason"] != "NEWS_EXIT":
        if (
            frozen.status == "COMPLETE"
            and abs(float(out["net"]) - float(frozen.net_return or 0)) > TOLERANCE
        ):
            raise ValueError(f"Exit copy differs from the frozen result for {request.event_id}")
        return frozen
    index = int(out["holding"])
    trigger, exit_session = request.sessions[index], request.sessions[index + 1]
    bar = next(b for b in request.prices if b.session_date == exit_session.session_date)
    exit_execution = frozen.entry.model_copy(  # type: ignore[union-attr]
        update={
            "session_date": exit_session.session_date,
            "at": exit_session.open_at,
            "price_a": bar.open_a,
            "price_b": bar.open_b,
        }
    )
    marks = tuple(m for m in frozen.marks if m.session_date <= trigger.session_date)
    return frozen.model_copy(
        update={
            "exit": exit_execution,
            "net_return": float(out["net"]),
            "reason": "NEWS_EXIT",
            "holding_sessions": index,
            "marks": marks,
            "trigger": None,
        }
    )


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


def load_inputs(args: argparse.Namespace) -> dict[str, Any]:
    features = [
        args.outputs / "p6_sec_features/timing_features.parquet",
        args.outputs / "news_v1/news_features.parquet",
        args.outputs / "news_v1/tone_features.parquet",
    ]
    frame, _ = ex.load(args.workspace_root, features, args.simulation)
    frame = ev.derived(frame)
    frame["vix_weight"] = ev.normalised(frame, ev.SIZING["Z3v_vix_proportional"](frame))
    r1 = ex.FILTERS["R1_fresh_news_filter"][1](frame).fillna(False).astype(bool)
    scores = pd.read_parquet(args.outputs / "p6_boosting2/scores.parquet")
    scores = scores.loc[scores["variant"].eq("R0_xgb_fixed")].copy()
    scores["selected"] = pb.selections(scores)
    chosen = set(scores.loc[scores["role"].eq("test") & scores["selected"], "event_id"])
    return {
        "frame": frame.set_index("event_id"),
        "model": chosen,
        "r1": set(frame.loc[r1, "event_id"]),
    }


def build_trades(args: argparse.Namespace, inputs: dict[str, Any]) -> dict[str, Any]:
    """Requests plus frozen and E3 results for every 2010-2023 Baseline 0 event."""
    sources = _sources(args.workspace_root)
    headline = load_headline(args.configs)
    frame = inputs["frame"]
    pairs = pd.read_parquet(
        args.workspace_root / "universe/source_v1/pair_universe.parquet"
    ).set_index("pair_id")
    index = headline_index(pd.read_parquet(args.outputs / "headline_v1/headline_tone.parquet"))
    sectors = sources.security_sectors()
    requests: dict[str, Any] = {}
    frozen: dict[str, PairTradeResult] = {}
    e3: dict[str, PairTradeResult] = {}
    for start, end in _chunks(START, END):
        events, _, _ = build_historical_events(sources, _spec(sources, start, end))
        print(f"{pb._now()} {len(events)} events {start}..{end}", flush=True)
        for event in events:
            request = event.request
            event_id = event.state.event_id
            if event_id not in frame.index:
                continue
            requests[event_id] = request
            result = simulate_pair_trade(request, headline)
            frozen[event_id] = result
            if event_id in inputs["model"]:
                pair = pairs.loc[request.pair_id]
                long_leg = "leg_b_security_id" if request.signal_z > 0 else "leg_a_security_id"
                short_leg = (
                    "leg_a_security_id" if long_leg == "leg_b_security_id" else "leg_b_security_id"
                )
                long_rows = index.get(str(pair[long_leg]), EMPTY)
                short_rows = index.get(str(pair[short_leg]), EMPTY)
                moments = _times(long_rows, request.signal_at, long_rows["net"].le(-0.1)) + _times(
                    short_rows, request.signal_at, short_rows["net"].ge(0.1)
                )
                e3[event_id] = news_exit_result(request, result, moments, headline)
        del events
    return {"requests": requests, "frozen": frozen, "e3": e3, "sectors": sectors}


def check_against_research(trades: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Frozen and E3 nets must equal the stored Decision 59-62 simulations."""
    stored = pd.concat(
        pd.read_parquet(args.outputs / f"p6_sec_explore2/exits_{n}.parquet")
        for n in ("explore", "confirm", "replicate")
    ).set_index("event_id")
    worst_frozen = worst_e3 = 0.0
    for event_id, result in trades["e3"].items():
        row = stored.loc[event_id]
        if result.net_return is not None:
            worst_e3 = max(
                worst_e3, abs(result.net_return - float(row["E3_adverse_tone_either_leg|net"]))
            )
        base = trades["frozen"][event_id]
        if base.net_return is not None:
            worst_frozen = max(worst_frozen, abs(base.net_return - float(row["frozen_net"])))
    if worst_e3 > 1e-9 or worst_frozen > 1e-9:
        raise ValueError(
            f"Trade results differ from stored simulations: {worst_frozen}, {worst_e3}"
        )
    return {"max_abs_frozen_difference": worst_frozen, "max_abs_e3_difference": worst_e3}


def proposals_for(trades: dict[str, Any], event_ids: Sequence[str]) -> list[PortfolioProposal]:
    sectors = trades["sectors"]
    return [
        PortfolioProposal(
            request=trades["requests"][e],
            decision_id=f"p6-portfolio:{e}",
            decision_at=trades["requests"][e].signal_at,
            sector_a=sectors.get(trades["requests"][e].leg_a, "UNKNOWN"),
            sector_b=sectors.get(trades["requests"][e].leg_b, "UNKNOWN"),
        )
        for e in event_ids
    ]


def verify(
    trades: dict[str, Any], args: argparse.Namespace, inputs: dict[str, Any]
) -> dict[str, Any]:
    """Unit weights and frozen results must reproduce ``simulate_portfolio``.

    Checked on the 2016-2017 model trades.
    """
    analysis = load_analysis_policies(args.configs)
    headline = load_headline(args.configs)
    chosen = [
        e
        for e, r in trades["requests"].items()
        if e in inputs["model"] and r.sessions[0].session_date.year in (2016, 2017)
    ]
    proposals = proposals_for(trades, chosen)
    frozen = simulate_portfolio(tuple(proposals), analysis.portfolio, headline)
    copy = research_portfolio(proposals, trades["frozen"], {}, analysis.portfolio, headline, 0.25)
    frozen_close = [m.nav for m in frozen.marks if m.phase == "CLOSE"]
    copy_close = copy["marks"]["nav"].tolist()
    if len(frozen_close) != len(copy_close):
        raise ValueError("Research portfolio has a different session path")
    difference = max(
        abs(a - b)
        for a, b in zip(frozen_close, copy_close, strict=True)
        if a is not None and b is not None
    )
    if difference > 1e-9:
        raise ValueError(f"Research portfolio differs from the frozen portfolio by {difference}")
    return {
        "proposals": len(proposals),
        "sessions": len(copy_close),
        "max_abs_nav_difference": difference,
    }


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


def run(args: argparse.Namespace) -> dict[str, Any]:
    inputs = load_inputs(args)
    trades = build_trades(args, inputs)
    checks = {
        "stored": check_against_research(trades, args),
        "portfolio": verify(trades, args, inputs),
    }
    print(json.dumps(checks), flush=True)
    analysis = load_analysis_policies(args.configs)
    headline = load_headline(args.configs)
    frame = inputs["frame"]
    args.output.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "decision": "DECISIONS 73",
        "checks": checks,
        "designs": {},
    }
    for design, spec in DESIGNS.items():
        if spec["population"] == "all":
            chosen = list(trades["requests"])
        else:
            chosen = [e for e in trades["requests"] if e in inputs["model"]]
        if spec.get("r1"):
            chosen = [e for e in chosen if e not in inputs["r1"]]
        results = trades["e3"] if spec["exit"] == "e3" else trades["frozen"]
        weights = (
            {e: float(np.nan_to_num(frame.at[e, "vix_weight"], nan=1.0)) for e in chosen}
            if spec.get("vix")
            else {}
        )
        proposals = proposals_for(trades, chosen)
        for label, target in TARGETS.items():
            out = research_portfolio(
                proposals, results, weights, analysis.portfolio, headline, target
            )
            stats = metrics(out["marks"])
            counts = pd.Series(out["status"]).value_counts().to_dict()
            stats["trade_status"] = {str(k): int(v) for k, v in counts.items()}
            stats["proposals"] = len(proposals)
            summary["designs"].setdefault(design, {})[label] = stats
            out["marks"].to_parquet(args.output / f"nav_{design}_{label}.parquet", index=False)
            f = stats["full"]
            print(
                f"{design:24s} {label:18s} CAGR {f['cagr']:+.2%} vol {f['volatility']:.2%}"
                f" Sharpe {f['sharpe']:+.2f} maxDD {f['max_drawdown']:.1%}"
                f" entered {counts.get('COMPLETE', 0)}",
                flush=True,
            )
    summary["run_date"] = date.today().isoformat()
    (args.output / "portfolios.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"
    )
    return summary


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--configs", type=Path, default=Path("configs"))
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_portfolio"))
    args = parser.parse_args(arguments)
    run(args)
    sys.stdout.flush()


if __name__ == "__main__":
    main()

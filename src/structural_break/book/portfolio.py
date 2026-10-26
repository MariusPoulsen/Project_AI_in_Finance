"""Quant programme Stage C: portfolio evaluation of the programme's design (DECISIONS 80).

Runs the verified research portfolio (``policy_portfolio.research_portfolio``,
Decision 73) for 2010-2023 on cached requests from ``trades``. Any
exit variant of ``trades.exit_loop`` is turned into a trade result
by moving the frozen result's exit, so the portfolio ledger reconciles
exactly against the variant's net return.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.backtest.contracts import ExecutionConfig, PairTradeRequest, PairTradeResult
from structural_break.backtest.portfolio import PortfolioProposal
from structural_break.backtest.production_policy import load_analysis_policies, load_headline
from structural_break.book import policy_portfolio as pp
from structural_break.book import trades as qt

PLAN_VERSION = "p6-quant-portfolio-v1"


def variant_result(
    request: PairTradeRequest,
    frozen: PairTradeResult,
    moments: Sequence[Any],
    config: ExecutionConfig,
    band: float,
    stop: float,
    timeout: int,
    news: bool,
    cost_bps: float | None = None,
    soft: tuple[int, float] | None = None,
) -> PairTradeResult:
    if frozen.entry is None or frozen.position is None:
        return frozen
    status, net, holding, reason = qt.exit_loop(
        request, frozen, config, band, stop, timeout, moments if news else (), cost_bps, soft
    )
    if status != "COMPLETE" or net is None or holding is None:
        return frozen.model_copy(update={"status": "UNPRICED", "net_return": None, "exit": None})
    if (
        frozen.status == "COMPLETE"
        and frozen.holding_sessions == holding
        and math.isclose(float(frozen.net_return or 0), net, abs_tol=1e-12)
    ):
        return frozen
    trigger, exit_session = request.sessions[holding], request.sessions[holding + 1]
    bar = next(b for b in request.prices if b.session_date == exit_session.session_date)
    assert frozen.entry is not None
    exit_execution = frozen.entry.model_copy(
        update={
            "session_date": exit_session.session_date,
            "at": exit_session.open_at,
            "price_a": bar.open_a,
            "price_b": bar.open_b,
        }
    )
    marks = tuple(m for m in frozen.marks if m.session_date <= trigger.session_date)
    if len(marks) < holding:
        # The frozen trade stopped earlier than this exit; its marks end there. Rebuild
        # the missing marks from the request's closes (same snapshot and units).
        marks = _marks(request, frozen, holding)
    return frozen.model_copy(
        update={
            "status": "COMPLETE",
            "exit": exit_execution,
            "net_return": net,
            "reason": reason,
            "holding_sessions": holding,
            "marks": marks,
            "trigger": None,
        }
    )


def _marks(request: PairTradeRequest, frozen: PairTradeResult, holding: int) -> tuple[Any, ...]:
    assert frozen.entry is not None and frozen.position is not None
    template = frozen.marks[0] if frozen.marks else None
    bars = {b.session_date: b for b in request.prices}
    marks = []
    for session in request.sessions[1 : holding + 1]:
        bar = bars[session.session_date]
        assert bar.close_a is not None and bar.close_b is not None
        a, b = bar.close_a, bar.close_b
        position, entry = frozen.position, frozen.entry
        values: dict[str, Any] = {
            "session_date": session.session_date,
            "at": session.close_at,
            "price_a": a,
            "price_b": b,
            "z": request.snapshot.z(a, b),
            "gross_return": position.units_a * (a - entry.price_a)
            + position.units_b * (b - entry.price_b),
            "gross_exposure": abs(position.units_a) * a + abs(position.units_b) * b,
        }
        if template is not None:
            marks.append(template.model_copy(update=values))
        else:
            from structural_break.backtest.contracts import TradeMark

            marks.append(TradeMark(**values))
    return tuple(marks)


def run_design(
    cache: dict[str, Any],
    selected: Sequence[str],
    exit_settings: tuple[float, float, int, bool],
    configs: Path,
    target: float,
    sectors: dict[str, str],
    cost_table: dict[Any, Any] | None = None,
    capital: float = 1e7,
    sector_cap: float | None = None,
    fractions: dict[str, float] | None = None,
    policy_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``cost_table`` (Decision 96) prices each trade with per-stock costs at ``capital``.

    ``fractions`` (Decision 99) gives each trade its own NAV fraction; the
    portfolio then wants ``fraction`` per entry and costs use that size.
    ``policy_override`` (Decision 111) replaces portfolio-policy fields, such as
    ``gross_entry_cap``, for a research run.
    """
    from structural_break.book import costs as qc

    headline = load_headline(configs)
    policy = load_analysis_policies(configs).portfolio
    if policy_override:
        policy = policy.model_copy(update=policy_override)
    results: dict[str, PairTradeResult] = {}
    proposals: list[PortfolioProposal] = []
    rates: dict[str, float] = {}
    for event_id in selected:
        request, frozen, moments = cache[event_id]
        rate = None
        if cost_table is not None:
            size = target if fractions is None else fractions.get(event_id, target)
            rate = qc.trade_rate_bps(cost_table, request, frozen, capital, size)
            if rate is None:
                continue
            rates[event_id] = rate
        # Decision 112: the time stop may be a per-event mapping, and a fifth setting a soft stop.
        band, stop, timeout, news = exit_settings[:4]
        soft = exit_settings[4] if len(exit_settings) > 4 else None
        if isinstance(timeout, dict):
            timeout = timeout[event_id]
        results[event_id] = variant_result(request, frozen, moments, headline, band, stop, timeout, news, rate, soft)
        proposals.append(
            PortfolioProposal(
                request=request,
                decision_id=f"p6-quant:{event_id}",
                decision_at=request.signal_at,
                sector_a=sectors.get(request.leg_a, "UNKNOWN"),
                sector_b=sectors.get(request.leg_b, "UNKNOWN"),
            )
        )
    weights = (
        {e: fractions.get(e, target) / target for e in results} if fractions is not None else {}
    )
    out = pp.research_portfolio(
        proposals, results, weights, policy, headline, target, rates or None, sector_cap
    )
    stats = pp.metrics(out["marks"])
    stats["trade_status"] = {
        str(k): int(v) for k, v in pd.Series(out["status"]).value_counts().items()
    }
    stats["proposals"] = len(proposals)
    return {
        "stats": stats,
        "marks": out["marks"],
        "status": out["status"],
        "allocations": out["allocations"],
        "results": results,
    }


def load_cache(path: Path) -> dict[str, Any]:
    with open(path, "rb") as handle:
        cache: dict[str, Any] = pickle.load(handle)  # our own cache from trades.build
    return cache


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--designs", type=Path, required=True, help="JSON {name: {scores, exit}}")
    parser.add_argument("--configs", type=Path, default=Path("configs"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_quant/portfolio"))
    args = parser.parse_args(arguments)
    from structural_break.pipeline.sources import _sources

    sectors = _sources(args.workspace_root).security_sectors()
    cache = load_cache(Path("outputs/p6_quant/requests.pkl"))
    designs = json.loads(args.designs.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"plan_version": PLAN_VERSION, "run_date": date.today().isoformat()}
    for name, spec in designs.items():
        scores = pd.read_parquet(spec["scores"])
        chosen = scores.loc[scores[spec.get("share", "top20")] & scores["year"].between(2010, 2023)]
        selected = [e for e in chosen["event_id"] if e in cache]
        settings = tuple(spec["exit"])
        for label, target in pp.TARGETS.items():
            out = run_design(cache, selected, settings, args.configs, target, sectors)
            summary.setdefault(name, {})[label] = out["stats"]
            out["marks"].to_parquet(args.output / f"nav_{name}_{label}.parquet", index=False)
            f = out["stats"]["full"]
            periods = out["stats"]["periods"]
            print(
                f"{name:30s} {label:18s} CAGR {f['cagr']:+.2%} vol {f['volatility']:.2%}"
                f" Sharpe {f['sharpe']:+.2f} maxDD {f['max_drawdown']:.1%}"
                f" | 10-15 {periods['2010-2015']['sharpe']:+.2f}"
                f" 16-21 {periods['2016-2021']['sharpe']:+.2f}"
                f" 22-23 {periods['2022-2023']['sharpe']:+.2f}",
                flush=True,
            )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()

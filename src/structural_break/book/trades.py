"""Quant programme Stage B: exit-rule grid on the frozen entries (DECISIONS 76).

Every 2006-2023 Baseline 0 event is entered exactly as the frozen Decision 36
policy enters it. Only the exit changes: the convergence band (take profit),
the adverse stop, the time stop and the E3 news exit. ``exit_loop`` is the
verified research exit loop of ``long_exit.simulate_long`` with those
four settings as arguments; with the frozen settings it reproduces the frozen
simulator, which ``build`` checks on every event. Results are written per
event and per variant, so selections from any model can be priced later.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import pickle
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.backtest.contracts import ExecutionConfig, PairTradeRequest, PairTradeResult
from structural_break.backtest.historical import build_historical_events
from structural_break.backtest.production_policy import load_headline
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.book.long_exit import simulate_long
from structural_break.forecast import model_b as pb
from structural_break.pipeline.news_exit import EMPTY, _times, headline_index
from structural_break.pipeline.sources import _chunks, _sources, _spec

PLAN_VERSION = "p6-quant-exits-v1"
BANDS = (0.5, 0.75, 1.0)
STOPS = (3.0, 3.5, 99.0)
TIMEOUTS = (20, 10)
NEWS = (False, True)
FROZEN = (0.5, 3.0, 20, False)


def variant_name(band: float, stop: float, timeout: int, news: bool) -> str:
    stop_label = "none" if stop >= 99 else f"{stop:g}"
    return f"b{band:g}_s{stop_label}_t{timeout}_{'news' if news else 'nonews'}"


VARIANTS = [variant_name(*v) for v in itertools.product(BANDS, STOPS, TIMEOUTS, NEWS)]


def exit_loop(
    request: PairTradeRequest,
    frozen: PairTradeResult,
    config: ExecutionConfig,
    band: float,
    stop: float,
    timeout: int,
    news: Sequence[datetime],
    cost_bps: float | None = None,
    soft: tuple[int, float] | None = None,
) -> tuple[str, float | None, int | None, str]:
    """Frozen entry, parameterised exit; returns (status, net, holding, reason).

    ``cost_bps`` (Decision 95) replaces the flat entry and exit cost rates with
    one per-trade rate per side; ``None`` keeps the frozen rates.
    ``soft`` (Decision 112) is a conditional time stop ``(session, ratio)``: at that
    session the trade exits if |z| is still above ``ratio`` x |signal z| (little
    progress); otherwise it runs on to ``timeout``.
    """
    if frozen.entry is None or frozen.position is None:
        return frozen.status, None, None, frozen.reason
    assert config.entry_cost_bps is not None and config.exit_cost_bps is not None
    assert config.annual_borrow_rate is not None
    entry, position = frozen.entry, frozen.position
    bars = {bar.session_date: bar for bar in request.prices}
    sessions = request.sessions
    side = 1.0 if request.signal_z > 0 else -1.0
    termination = request.lifecycle_termination
    for index, session in enumerate(sessions[1 : timeout + 1], start=1):
        if termination is not None and termination <= session.session_date:
            return "UNPRICED", None, None, "LIFECYCLE_TERMINATION"
        bar = bars.get(session.session_date)
        if bar is None or bar.close_a is None or bar.close_b is None:
            return "UNPRICED", None, None, "MISSING_MONITORING_CLOSE"
        z = request.snapshot.z(bar.close_a, bar.close_b)
        if abs(z) <= band:
            reason = "CONVERGENCE"
        elif side * z >= stop:
            reason = "ADVERSE_STOP"
        elif any(request.signal_at < moment <= session.close_at for moment in news):
            reason = "NEWS_EXIT"
        elif index == timeout:
            reason = "TIMEOUT"
        elif soft is not None and index == soft[0] and abs(z) > soft[1] * abs(request.signal_z):
            reason = "NO_PROGRESS_TIMEOUT"
        else:
            continue
        if index + 1 >= len(sessions):
            return "UNPRICED", None, None, "INCOMPLETE_SESSION_PATH"
        exit_session = sessions[index + 1]
        if termination is not None and termination <= exit_session.session_date:
            return "UNPRICED", None, None, "LIFECYCLE_TERMINATION"
        last = bars.get(exit_session.session_date)
        if last is None or last.open_a is None or last.open_b is None:
            return "UNPRICED", None, None, "MISSING_EXIT_OPEN"
        gross = position.units_a * (last.open_a - entry.price_a) + position.units_b * (
            last.open_b - entry.price_b
        )
        exposure = abs(position.units_a) * last.open_a + abs(position.units_b) * last.open_b
        entry_rate = config.entry_cost_bps if cost_bps is None else cost_bps
        exit_rate = config.exit_cost_bps if cost_bps is None else cost_bps
        trading = entry_rate / 10000.0 + exit_rate / 10000.0 * exposure
        borrow = (
            config.annual_borrow_rate
            * position.short_entry_notional
            * index
            / config.annual_trading_sessions
        )
        return "COMPLETE", gross - trading - borrow, index, reason
    return "UNPRICED", None, None, "INCOMPLETE_SESSION_PATH"


def build(workspace: Path, configs: Path, outputs: Path, output: Path) -> Path:
    """Price every event under every exit variant; cache requests for later stages."""
    sources = _sources(workspace)
    headline = load_headline(configs)
    frame, _ = pb.load_data(workspace, outputs / "walkforward/simulation_frozen_exit.parquet")
    wanted = set(frame["event_id"])
    pairs = pd.read_parquet(workspace / "universe/source_v1/pair_universe.parquet").set_index(
        "pair_id"
    )
    index = headline_index(pd.read_parquet(outputs / "headline_tone/headline_tone.parquet"))
    rows: list[dict[str, Any]] = []
    cache: dict[str, Any] = {}
    for start, end in _chunks(pd.Timestamp(2006, 1, 1).date(), periods.data_end()):
        events, _, _ = build_historical_events(sources, _spec(sources, start, end))
        print(f"{pb._now()} pricing {len(events)} events {start}..{end}", flush=True)
        for event in events:
            event_id = event.state.event_id
            if event_id not in wanted:
                continue
            request = event.request
            frozen = simulate_pair_trade(request, headline)
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
            check = simulate_long(request, request.sessions, request.prices, headline, 20, moments)
            row: dict[str, Any] = {
                "event_id": event_id,
                "frozen_status": frozen.status,
                "frozen_net": frozen.net_return,
            }
            for band, stop, timeout, news in itertools.product(BANDS, STOPS, TIMEOUTS, NEWS):
                status, net, holding, reason = exit_loop(
                    request, frozen, headline, band, stop, timeout, moments if news else ()
                )
                name = variant_name(band, stop, timeout, news)
                row[f"{name}|status"], row[f"{name}|net"] = status, net
                row[f"{name}|hold"], row[f"{name}|reason"] = holding, reason
            frozen_name = variant_name(*FROZEN)
            if frozen.status == "COMPLETE" and not math.isclose(
                float(row[f"{frozen_name}|net"]), float(frozen.net_return or 0), abs_tol=1e-12
            ):
                raise ValueError(f"Exit loop differs from the frozen simulator on {event_id}")
            e3 = variant_name(0.5, 3.0, 20, True)
            if check["status"] == "COMPLETE" and not math.isclose(
                float(row[f"{e3}|net"]), float(check["net"]), abs_tol=1e-12
            ):
                raise ValueError(f"Exit loop differs from the E3 research loop on {event_id}")
            rows.append(row)
            cache[event_id] = (request, frozen, moments)
        del events
    output.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows)
    path = output / "exit_grid.parquet"
    table.to_parquet(path, index=False)
    with open(output / "requests.pkl", "wb") as handle:
        pickle.dump(cache, handle, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"{pb._now()} wrote {len(table)} events x {len(VARIANTS)} exit variants", flush=True)
    return path


SELECT, HOLDOUT = (2010, 2017), (2018, 2023)


def r0_selections(outputs: Path, share: float = 0.20) -> pd.DataFrame:
    """The Decision 45 R0 top-share test selections (event_id, year, selected)."""
    scores = pd.read_parquet(outputs / "model_b/scores.parquet")
    scores = scores.loc[scores["variant"].eq("R0_xgb_fixed")].copy()
    chosen = pd.Series(False, index=scores.index)
    for _, group in scores.groupby("year"):
        cut = float(np.quantile(group.loc[group["role"].eq("threshold"), "score"], 1 - share))
        test = group["role"].eq("test")
        chosen.loc[group.index[test]] = group.loc[test, "score"].to_numpy() >= cut
    scores["selected"] = chosen
    return scores.loc[scores["role"].eq("test"), ["event_id", "year", "selected"]]


def exit_table(
    grid: pd.DataFrame, selections: pd.DataFrame, years: tuple[int, int]
) -> pd.DataFrame:
    """Per variant: per-candidate mean, monthly Sharpe and per-trade mean on priced events."""
    data = selections.merge(grid, on="event_id", how="inner")
    data = data.loc[data["year"].between(*years)]
    priced = np.ones(len(data), dtype=bool)
    for name in VARIANTS:
        priced &= data[f"{name}|status"].eq("COMPLETE").to_numpy()
    data = data.loc[priced]
    months = data["month"]
    rows = []
    for name in VARIANTS:
        net = data[f"{name}|net"].astype(float)
        alloc = net.where(data["selected"], 0.0)
        monthly = alloc.groupby(months).mean()
        sd = float(monthly.std(ddof=1))
        chosen = net[data["selected"]]
        rows.append(
            {
                "variant": name,
                "per_candidate_bps": float(alloc.mean() * 1e4),
                "monthly_sharpe": float(monthly.mean() / sd * math.sqrt(12))
                if sd > 0
                else math.nan,
                "per_trade_bps": float(chosen.mean() * 1e4),
                "hit_rate": float((chosen > 0).mean()),
                "mean_hold": float(data.loc[data["selected"], f"{name}|hold"].astype(float).mean()),
                "trades": int(data["selected"].sum()),
            }
        )
    return pd.DataFrame(rows).set_index("variant")


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "explore-exits"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--configs", type=Path, default=Path("configs"))
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument("--output", type=Path, default=Path("outputs/book"))
    args = parser.parse_args(arguments)
    if args.command == "build":
        build(args.workspace_root, args.configs, args.outputs, args.output)
        return
    grid = pd.read_parquet(args.output / "exit_grid.parquet")
    frame, _ = pb.load_data(
        args.workspace_root,
        args.outputs / "walkforward/simulation_frozen_exit.parquet",
    )
    months = frame.set_index("event_id")["event_date"].map(lambda d: str(d)[:7])
    selections = r0_selections(args.outputs)
    selections["month"] = selections["event_id"].map(months)
    table = exit_table(grid, selections, SELECT).sort_values("monthly_sharpe", ascending=False)
    e3 = variant_name(0.5, 3.0, 20, True)
    best = str(table.index[0])
    per_candidate = table["per_candidate_bps"].astype(float)
    if per_candidate[best] < per_candidate[e3]:
        best = e3
    table.to_csv(args.output / "exit_exploration.csv")
    choice = {"exit": best, "years": list(SELECT), "plan_version": PLAN_VERSION}
    (args.output / "exit_choice.json").write_text(json.dumps(choice, indent=2) + chr(10))
    print(table.round(3).to_string())
    print(json.dumps(choice))


if __name__ == "__main__":
    main()

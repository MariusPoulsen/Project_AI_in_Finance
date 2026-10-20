"""Quant programme Stage B: exit-rule grid on the frozen entries (DECISIONS 76).

Every 2010-2023 Baseline 0 event is entered exactly as the frozen Decision 36
policy enters it. Only the exit changes: the convergence band (take profit),
the adverse stop, the time stop and the E3 news exit. ``exit_loop`` is the
verified research exit loop of ``p6_halflife_exit.simulate_long`` with those
four settings as arguments; with the frozen settings it reproduces the frozen
simulator, which ``build`` checks on every event. Results are written per
event and per variant, so selections from any model can be priced later.
"""

from __future__ import annotations

import argparse
import itertools
import math
import pickle
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.backtest.contracts import ExecutionConfig, PairTradeRequest, PairTradeResult
from structural_break.backtest.historical import build_historical_events
from structural_break.backtest.production_policy import load_headline
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.experiments import p6_boosting as pb
from structural_break.experiments.p6_halflife_exit import simulate_long
from structural_break.experiments.p6_improvement import _chunks, _sources, _spec
from structural_break.experiments.p6_sec_explore2 import EMPTY, _times, headline_index

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
) -> tuple[str, float | None, int | None, str]:
    """Frozen entry, parameterised exit; returns (status, net, holding, reason)."""
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
        trading = config.entry_cost_bps / 10000.0 + config.exit_cost_bps / 10000.0 * exposure
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
    frame, _ = pb.load_data(
        workspace, outputs / "p6_improvement/walkforward/simulation_frozen_exit.parquet"
    )
    wanted = set(frame["event_id"])
    pairs = pd.read_parquet(workspace / "universe/source_v1/pair_universe.parquet").set_index(
        "pair_id"
    )
    index = headline_index(pd.read_parquet(outputs / "headline_v1/headline_tone.parquet"))
    rows: list[dict[str, Any]] = []
    cache: dict[str, Any] = {}
    for start, end in _chunks(pd.Timestamp(2010, 1, 1).date(), pd.Timestamp(2023, 12, 31).date()):
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


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build",))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--configs", type=Path, default=Path("configs"))
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_quant"))
    args = parser.parse_args(arguments)
    build(args.workspace_root, args.configs, args.outputs, args.output)


if __name__ == "__main__":
    main()

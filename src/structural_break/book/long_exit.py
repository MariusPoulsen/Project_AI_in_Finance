"""Pre-registered half-life timeout test (DECISIONS 52; exploratory).

The frozen Decision 36 policy times every trade out after 20 sessions, but the
median pair's formation-window half-life is about 30 sessions: closing a gap
from |z| = 2 to the 0.5 exit band (a 75 % reduction) takes about two
half-lives. This experiment keeps the frozen entry, convergence band, adverse
stop, costs and borrow, and changes only the timeout to

    timeout = clip(ceil(2 * half_life), 1, 120) sessions,

using each event's point-in-time half-life (20 sessions when it is unknown).

The frozen simulator and its contracts are not modified; its source hash binds
the accepted backtests and its contract caps holding at 30 sessions. A research
copy continues the identical exit loop on a longer price path from the same
price capture, after the frozen simulator's own entry. Before any result is
written, the copy must reproduce the frozen simulator exactly at 20 sessions
for every event. Sessions are never built after the development end
(2023-12-31), so the locked final-test years are never read; a trade still
open then is UNPRICED.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.backtest import historical
from structural_break.backtest.contracts import (
    ExecutionConfig,
    MarketSession,
    PairPrices,
    PairTradeRequest,
)
from structural_break.backtest.historical import (
    HistoricalSources,
    PriceBook,
    build_historical_events,
)
from structural_break.backtest.production_policy import load_headline
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.pipeline.sources import (
    _chunks,
    _sources,
    _spec,
    load_frame,
    paired_block_bootstrap,
)
from structural_break.pipeline.walkforward import (
    DECISION_YEARS,
    MINIMUM_POSITIVE_YEARS,
    REFERENCE_YEARS,
)
from structural_break.storage.files import write_bytes

PLAN_VERSION = "p6-halflife-exit-v1"
MULTIPLE = 2.0
MIN_TIMEOUT, MAX_TIMEOUT, DEFAULT_TIMEOUT = 1, 120, 20
TOLERANCE = 1e-12


def timeout_for(half_life: float | None) -> int:
    """Two half-lives, bounded to 1-120 sessions; 20 when the half-life is unknown."""
    if half_life is None or not math.isfinite(half_life) or half_life <= 0:
        return DEFAULT_TIMEOUT
    return int(min(max(math.ceil(MULTIPLE * half_life), MIN_TIMEOUT), MAX_TIMEOUT))


def long_sessions(signal: date, timeout: int, development_end: date) -> tuple[MarketSession, ...]:
    """The frozen session builder, asked for a longer path (never past development end)."""
    return historical._sessions(signal, timeout, development_end)


def simulate_long(
    request: PairTradeRequest,
    sessions: Sequence[MarketSession],
    path_prices: Sequence[PairPrices],
    config: ExecutionConfig,
    timeout: int,
    news_exit: Sequence[datetime] = (),
) -> dict[str, Any]:
    """Frozen entry, then the frozen exit loop with ``timeout`` on a longer path.

    ``news_exit`` (DECISIONS 59) lists availability times of qualifying news; a
    trade still open at a session close after such news became available exits
    at the next open, like any other close-based trigger. Empty by default.
    """
    frozen = simulate_pair_trade(request, config)
    if frozen.status == "NOT_ENTERED" or frozen.entry is None or frozen.position is None:
        return {"status": frozen.status, "reason": frozen.reason, "net": None, "holding": None}
    assert config.entry_cost_bps is not None and config.exit_cost_bps is not None
    assert config.annual_borrow_rate is not None
    entry, position = frozen.entry, frozen.position
    bars = {bar.session_date: bar for bar in path_prices}
    side = 1.0 if request.signal_z > 0 else -1.0
    termination = request.lifecycle_termination

    def unpriced(reason: str) -> dict[str, Any]:
        return {"status": "UNPRICED", "reason": reason, "net": None, "holding": None}

    def pnl(a: float, b: float) -> float:
        return position.units_a * (a - entry.price_a) + position.units_b * (b - entry.price_b)

    for index, session in enumerate(sessions[1 : timeout + 1], start=1):
        if termination is not None and termination <= session.session_date:
            return unpriced("LIFECYCLE_TERMINATION")
        bar = bars.get(session.session_date)
        if bar is None or bar.close_a is None or bar.close_b is None:
            return unpriced("MISSING_MONITORING_CLOSE")
        z = request.snapshot.z(bar.close_a, bar.close_b)
        if abs(z) <= config.convergence_band:
            reason = "CONVERGENCE"
        elif side * z >= config.adverse_boundary:
            reason = "ADVERSE_STOP"
        elif any(request.signal_at < moment <= session.close_at for moment in news_exit):
            reason = "NEWS_EXIT"
        elif index == timeout:
            reason = "TIMEOUT"
        else:
            continue
        if index + 1 >= len(sessions):
            return unpriced("INCOMPLETE_SESSION_PATH")
        exit_session = sessions[index + 1]
        if termination is not None and termination <= exit_session.session_date:
            return unpriced("LIFECYCLE_TERMINATION")
        last = bars.get(exit_session.session_date)
        if last is None or last.open_a is None or last.open_b is None:
            return unpriced("MISSING_EXIT_OPEN")
        gross_return = pnl(last.open_a, last.open_b)
        exposure = abs(position.units_a) * last.open_a + abs(position.units_b) * last.open_b
        trading = config.entry_cost_bps / 10000.0 + config.exit_cost_bps / 10000.0 * exposure
        borrow = (
            config.annual_borrow_rate
            * position.short_entry_notional
            * index
            / config.annual_trading_sessions
        )
        return {
            "status": "COMPLETE",
            "reason": reason,
            "net": gross_return - trading - borrow,
            "holding": index,
        }
    return unpriced("INCOMPLETE_SESSION_PATH")


def simulate(
    sources: HistoricalSources,
    configs: Path,
    half_lives: dict[str, float | None],
    *,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Frozen 20-session result, the research copy at 20 and the half-life timeout."""
    say = progress or (lambda message: None)
    headline = load_headline(configs)
    development_end = sources.binding.development_end
    rows: list[dict[str, Any]] = []
    for start, end in _chunks(date(2006, 1, 1), date(2023, 12, 31)):
        spec = _spec(sources, start, end)
        events, _, _ = build_historical_events(sources, spec)
        prices = PriceBook.build(
            sources.prices(spec.window_start - timedelta(days=45), development_end), spec
        )
        say(f"simulating {len(events)} events {start}..{end}")
        for event in events:
            request = event.request
            event_id = event.state.event_id
            timeout = timeout_for(half_lives.get(event_id))
            signal = request.sessions[0].session_date
            path = long_sessions(signal, max(timeout, DEFAULT_TIMEOUT), development_end)
            frozen = simulate_pair_trade(request, headline)
            bars = prices.pair_bars(request.leg_a, request.leg_b, path)
            copy = simulate_long(request, path, bars, headline, DEFAULT_TIMEOUT)
            longer = simulate_long(request, path, bars, headline, timeout)
            rows.append(
                {
                    "event_id": event_id,
                    "event_date": signal,
                    "half_life": half_lives.get(event_id),
                    "timeout": timeout,
                    "frozen_status": frozen.status,
                    "frozen_net": frozen.net_return,
                    "frozen_holding": frozen.holding_sessions,
                    "copy_status": copy["status"],
                    "copy_net": copy["net"],
                    "hl_status": longer["status"],
                    "hl_reason": longer["reason"],
                    "hl_net": longer["net"],
                    "hl_holding": longer["holding"],
                }
            )
        del events, prices
    frame = pd.DataFrame(rows)
    if frame.empty or frame["event_id"].duplicated().any():
        raise ValueError("Simulated events must be nonempty and unique")
    return frame


def verify_copy(frame: pd.DataFrame) -> dict[str, int]:
    """The research copy must equal the frozen simulator at 20 sessions, event by event."""
    status = frame["copy_status"].ne(frame["frozen_status"])
    both = frame["frozen_net"].notna() & frame["copy_net"].notna()
    net = (frame.loc[both, "frozen_net"] - frame.loc[both, "copy_net"]).abs().gt(TOLERANCE)
    one_sided = frame["frozen_net"].notna() != frame["copy_net"].notna()
    result = {
        "events": int(len(frame)),
        "status_mismatches": int(status.sum()),
        "net_mismatches": int(net.sum()),
        "one_sided_net": int(one_sided.sum()),
    }
    if result["status_mismatches"] or result["net_mismatches"] or result["one_sided_net"]:
        raise ValueError(f"Research simulator copy differs from the frozen simulator: {result}")
    return result


def _contrast(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    """Paired per-trade and per-day contrasts where both rules priced the trade."""
    priced = mask & frame["frozen_status"].eq("COMPLETE") & frame["hl_status"].eq("COMPLETE")
    rows = frame.loc[priced]
    year = pd.to_datetime(rows["event_date"]).dt.year
    months = pd.to_datetime(rows["event_date"]).dt.strftime("%Y-%m").to_numpy()
    pooled = paired_block_bootstrap(
        rows["frozen_net"].to_numpy(dtype=float), rows["hl_net"].to_numpy(dtype=float), months
    )
    per_year = {
        str(y): float((group["hl_net"] - group["frozen_net"]).mean() * 1e4)
        for y, group in rows.groupby(year)
    }

    def per_20_days(net: str, holding: str) -> float | None:
        days = rows[holding].astype(float).sum()
        return float(rows[net].sum() / days * 20 * 1e4) if days else None

    return {
        "trades_priced_by_both": int(len(rows)),
        "unpriced_by_half_life_rule": int((mask & frame["hl_status"].eq("UNPRICED")).sum()),
        "frozen_mean_net_bps": float(rows["frozen_net"].mean() * 1e4) if len(rows) else None,
        "half_life_mean_net_bps": float(rows["hl_net"].mean() * 1e4) if len(rows) else None,
        "difference_bps": pooled["estimate"] * 1e4 if pooled["estimate"] is not None else None,
        "difference_interval_95_bps": [v * 1e4 for v in pooled["interval_95"]]
        if pooled["interval_95"]
        else None,
        "months": pooled["blocks_n"],
        "per_year_difference_bps": per_year,
        "frozen_net_per_20_days_bps": per_20_days("frozen_net", "frozen_holding"),
        "half_life_net_per_20_days_bps": per_20_days("hl_net", "hl_holding"),
        "frozen_mean_holding": float(rows["frozen_holding"].mean()) if len(rows) else None,
        "half_life_mean_holding": float(rows["hl_holding"].mean()) if len(rows) else None,
        "half_life_exit_reasons": rows["hl_reason"].value_counts().to_dict(),
    }


def evaluate(frame: pd.DataFrame, eligible: pd.Series) -> dict[str, Any]:
    year = pd.to_datetime(frame["event_date"]).dt.year
    decision = year.isin(DECISION_YEARS)
    reference = year.isin(REFERENCE_YEARS)
    baseline1 = frame["event_id"].map(eligible).fillna(False).astype(bool)
    result: dict[str, Any] = {"plan_version": PLAN_VERSION, "copy_check": verify_copy(frame)}
    for name, population in (
        ("baseline0", pd.Series(True, index=frame.index)),
        ("baseline1", baseline1),
    ):
        block = _contrast(frame, population & decision)
        years = block["per_year_difference_bps"]
        better = sum(years.get(str(y), -math.inf) > 0 for y in DECISION_YEARS)
        interval = block["difference_interval_95_bps"]
        per_day_ok = (
            block["half_life_net_per_20_days_bps"] is not None
            and block["frozen_net_per_20_days_bps"] is not None
            and block["half_life_net_per_20_days_bps"] >= block["frozen_net_per_20_days_bps"]
        )
        block |= {
            "years_better": better,
            "passes_per_trade": bool(
                interval is not None and interval[0] > 0 and better >= MINIMUM_POSITIVE_YEARS
            ),
            "per_day_not_worse": bool(per_day_ok),
            "reference_2022_2023": _contrast(frame, population & reference),
        }
        block["passes"] = block["passes_per_trade"] and block["per_day_not_worse"]
        result[name] = block
    result["verdict"] = result["baseline0"]["passes"]
    return result


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--configs-dir", type=Path, default=Path("configs"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    say = lambda message: print(message, file=sys.stderr, flush=True)  # noqa: E731
    sources = _sources(args.workspace_root)
    frame_inputs, _ = load_frame(args.workspace_root, sources.binding.evaluation.version)
    half_lives = {
        str(k): (None if pd.isna(v) else float(v))
        for k, v in zip(frame_inputs["event_id"], frame_inputs["half_life"], strict=True)
    }
    eligible = frame_inputs.set_index("event_id")["baseline1_eligible"].eq(True)
    cache = args.output_dir / "simulation.parquet"
    if cache.exists():
        frame = pd.read_parquet(cache)
    else:
        frame = simulate(sources, args.configs_dir, half_lives, progress=say)
        verify_copy(frame)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cache, index=False)
    result = evaluate(frame, eligible)
    result["inputs"] = {
        "run_date": date.today().isoformat(),
        "multiple": MULTIPLE,
        "bounds": [MIN_TIMEOUT, MAX_TIMEOUT],
        "default_timeout": DEFAULT_TIMEOUT,
        "timeout_distribution": frame["timeout"].describe().round(1).to_dict(),
        "np_version": np.__version__,
    }
    body = (json.dumps(result, indent=2, sort_keys=True, default=str) + "\n").encode()
    write_bytes(args.output_dir / "halflife_exit.json", body)
    print(
        json.dumps(
            {"verdict": result["verdict"], "output": str(args.output_dir / "halflife_exit.json")}
        )
    )


if __name__ == "__main__":
    main()

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

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from structural_break.backtest.contracts import (
    ExecutionConfig,
    MarketSession,
    PairPrices,
    PairTradeRequest,
)
from structural_break.backtest.simulator import simulate_pair_trade

PLAN_VERSION = "p6-halflife-exit-v1"
MIN_TIMEOUT, MAX_TIMEOUT, DEFAULT_TIMEOUT = 1, 120, 20
TOLERANCE = 1e-12


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

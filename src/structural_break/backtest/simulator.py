"""One frozen-unit, next-open execution/cost engine for every later ladder rung.

This module does not choose candidate events, fit models, fetch data or aggregate
portfolio returns. It deliberately preserves a record for every failed execution.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from structural_break.backtest.contracts import (
    Execution,
    ExecutionConfig,
    ExitTrigger,
    PairPrices,
    PairTradeRequest,
    PairTradeResult,
    Position,
    Reason,
    Status,
    TradeMark,
)


def canonical_bytes(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: BaseModel) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def simulator_source_sha256() -> str:
    """Bind both numerical rules and validation rules, portable across CRLF/LF."""
    digest = hashlib.sha256()
    for name in ("contracts.py", "simulator.py"):
        source = (Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n")
        digest.update(name.encode("ascii") + b"\0" + source + b"\0")
    return digest.hexdigest()


def fixture_config(*, horizon_sessions: int = 20) -> ExecutionConfig:
    """Explicit scenario, not a validation-frozen economic policy."""
    return ExecutionConfig.model_validate(
        {
            "version": "phase6-execution-fixture-v1",
            "mode": "FIXTURE",
            "status": "DRAFT",
            "horizon_sessions": horizon_sessions,
            "positive_beta_limit": 10.0,
            "entry_cost_bps": 5.0,
            "exit_cost_bps": 5.0,
            "annual_borrow_rate": 0.03,
        }
    )


def simulate_pair_trade(event: PairTradeRequest, config: ExecutionConfig) -> PairTradeResult:
    """Run the supplied path once; no filling or convenient later execution.

    Horizon sessions are counted from the signal, not from a refit or entry gap.
    Borrow counts the exact number of session boundaries from entry open to exit
    open. Exit trading cost uses actual gross exit turnover of the frozen units.
    """
    if config.mode == "FIXTURE" and event.data_kind != "SYNTHETIC_FIXTURE":
        raise ValueError("Fixture economic assumptions cannot be applied to captured market data")
    marks: list[TradeMark] = []
    entry: Execution | None = None
    position: Position | None = None
    trigger: ExitTrigger | None = None
    gap: float | None = None
    base: dict[str, Any] = {
        "event_id": event.event_id,
        "pair_id": event.pair_id,
        "simulator_source_sha256": simulator_source_sha256(),
        "request_sha256": sha256(event),
        "execution_config_sha256": sha256(config),
        "execution_config_version": config.version,
        "snapshot_id": event.snapshot.snapshot_id,
        "price_lineage": event.price_lineage,
        "data_kind": event.data_kind,
        "signal_z": event.signal_z,
        "limitations": (
            *(("SYNTHETIC_ENGINEERING_ONLY",) if event.data_kind == "SYNTHETIC_FIXTURE" else ()),
            "ADJUSTMENT_BASIS_DECLARED_NOT_INDEPENDENTLY_VERIFIED",
            "OBSERVED_CLOSES_AND_EXIT_ONLY_NO_INTRADAY_EXTREMES",
            "NO_PORTFOLIO_OR_LADDER_SELECTION",
        ),
    }

    def result(status: Status, reason: Reason, **economics: Any) -> PairTradeResult:
        returns = [0.0, *(mark.gross_return for mark in marks)] if entry else []
        if "gross_return" in economics:
            returns.append(economics["gross_return"])
        return PairTradeResult(
            **base,
            status=status,
            reason=reason,
            entry=entry,
            position=position,
            trigger=trigger,
            entry_gap_z=gap,
            marks=tuple(marks),
            mae=min(returns) if returns and status == "COMPLETE" else None,
            mfe=max(returns) if returns and status == "COMPLETE" else None,
            partial_mae=min(returns) if returns and status == "UNPRICED" else None,
            partial_mfe=max(returns) if returns and status == "UNPRICED" else None,
            **economics,
        )

    if config.mode == "DEVELOPMENT" and config.status != "FROZEN":
        return result("NOT_ENTERED", "POLICY_NOT_FROZEN")
    if any(
        value is None
        for value in (
            config.positive_beta_limit,
            config.entry_cost_bps,
            config.exit_cost_bps,
            config.annual_borrow_rate,
        )
    ):
        return result("NOT_ENTERED", "POLICY_PARAMETERS_MISSING")
    assert config.positive_beta_limit is not None
    assert config.entry_cost_bps is not None
    assert config.exit_cost_bps is not None
    assert config.annual_borrow_rate is not None
    if not 0 < event.snapshot.beta <= config.positive_beta_limit:
        return result("NOT_ENTERED", "INVALID_ECONOMIC_BETA")
    if abs(event.signal_z) < config.entry_threshold:
        return result("NOT_ENTERED", "SIGNAL_NOT_DIVERGED")
    prices = {bar.session_date: bar for bar in event.prices}
    signal = prices.get(event.sessions[0].session_date)
    if signal is None or signal.close_a is None or signal.close_b is None:
        return result("NOT_ENTERED", "MISSING_SIGNAL_CLOSE")
    if len(event.sessions) < 2:
        return result("NOT_ENTERED", "INCOMPLETE_SESSION_PATH")
    entry_session = event.sessions[1]
    if event.lifecycle_termination is not None:
        if event.lifecycle_termination <= entry_session.session_date:
            return result("NOT_ENTERED", "LIFECYCLE_TERMINATION")
    first = prices.get(entry_session.session_date)
    if first is None or first.open_a is None or first.open_b is None:
        return result("NOT_ENTERED", "MISSING_ENTRY_OPEN")
    side = 1.0 if event.signal_z > 0 else -1.0
    weight_a = -side / (1.0 + event.snapshot.beta)
    weight_b = side * event.snapshot.beta / (1.0 + event.snapshot.beta)
    entry = Execution(
        session_date=entry_session.session_date,
        at=entry_session.open_at,
        price_a=first.open_a,
        price_b=first.open_b,
    )
    position = Position(
        direction="SHORT_A_LONG_B" if side > 0 else "LONG_A_SHORT_B",
        weight_a=weight_a,
        weight_b=weight_b,
        units_a=weight_a / first.open_a,
        units_b=weight_b / first.open_b,
        short_entry_notional=abs(weight_a if weight_a < 0 else weight_b),
    )
    gap = event.snapshot.z(first.open_a, first.open_b) - event.signal_z

    def pnl(a: float, b: float) -> float:
        assert entry is not None and position is not None
        return position.units_a * (a - entry.price_a) + position.units_b * (b - entry.price_b)

    def gross(a: float, b: float) -> float:
        assert position is not None
        return abs(position.units_a) * a + abs(position.units_b) * b

    for index, session in enumerate(event.sessions[1 : config.horizon_sessions + 1], start=1):
        if event.lifecycle_termination is not None:
            if event.lifecycle_termination <= session.session_date:
                return result("UNPRICED", "LIFECYCLE_TERMINATION")
        bar: PairPrices | None = prices.get(session.session_date)
        if bar is None or bar.close_a is None or bar.close_b is None:
            return result("UNPRICED", "MISSING_MONITORING_CLOSE")
        z = event.snapshot.z(bar.close_a, bar.close_b)
        marks.append(
            TradeMark(
                session_date=session.session_date,
                at=session.close_at,
                price_a=bar.close_a,
                price_b=bar.close_b,
                z=z,
                gross_return=pnl(bar.close_a, bar.close_b),
                gross_exposure=gross(bar.close_a, bar.close_b),
            )
        )
        if abs(z) <= config.convergence_band:
            trigger = ExitTrigger(
                reason="CONVERGENCE", session_date=session.session_date, at=session.close_at, z=z
            )
        elif side * z >= config.adverse_boundary:
            trigger = ExitTrigger(
                reason="ADVERSE_STOP", session_date=session.session_date, at=session.close_at, z=z
            )
        elif index == config.horizon_sessions:
            trigger = ExitTrigger(
                reason="TIMEOUT", session_date=session.session_date, at=session.close_at, z=z
            )
        if trigger is None:
            continue
        if index + 1 >= len(event.sessions):
            return result("UNPRICED", "INCOMPLETE_SESSION_PATH")
        exit_session = event.sessions[index + 1]
        if event.lifecycle_termination is not None:
            if event.lifecycle_termination <= exit_session.session_date:
                return result("UNPRICED", "LIFECYCLE_TERMINATION")
        last = prices.get(exit_session.session_date)
        if last is None or last.open_a is None or last.open_b is None:
            return result("UNPRICED", "MISSING_EXIT_OPEN")
        exit_execution = Execution(
            session_date=exit_session.session_date,
            at=exit_session.open_at,
            price_a=last.open_a,
            price_b=last.open_b,
        )
        gross_return = pnl(last.open_a, last.open_b)
        holding_sessions = index  # exit index minus entry index: (index + 1) - 1
        trading_cost = config.entry_cost_bps / 10000.0 + config.exit_cost_bps / 10000.0 * gross(
            last.open_a, last.open_b
        )
        borrow_cost = (
            config.annual_borrow_rate
            * position.short_entry_notional
            * holding_sessions
            / config.annual_trading_sessions
        )
        return result(
            "COMPLETE",
            trigger.reason,
            exit=exit_execution,
            holding_sessions=holding_sessions,
            gross_return=gross_return,
            trading_cost=trading_cost,
            borrow_cost=borrow_cost,
            net_return=gross_return - trading_cost - borrow_cost,
        )
    return result("UNPRICED", "INCOMPLETE_SESSION_PATH")

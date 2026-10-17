"""Secondary fixture portfolio with chronological fixed-share accounting.

Proposals contain decisions and price paths, never supervised outcomes. Every
proposal is simulated by the shared pair engine, including doomed trades. Its
stored future result does not determine allocation: entry, close and exit facts
are consumed at their exact timestamps. The first missing held quote makes
aggregate NAV permanently unknown; convenient later prices cannot repair it.
"""

import hashlib
from datetime import date, datetime, timedelta
from math import isclose
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, model_validator

from structural_break.backtest.contracts import (
    SHA256,
    BoundedNumber,
    ExecutionConfig,
    FrozenModel,
    Identifier,
    PairTradeRequest,
    PairTradeResult,
    canonical_sessions,
    development_date,
    utc,
)
from structural_break.backtest.simulator import sha256, simulate_pair_trade


class PortfolioProposal(FrozenModel):
    """An outcome-free stored decision; declined proposals retain their row."""

    request: PairTradeRequest
    decision_id: Identifier
    decision_at: datetime
    selected: bool = True
    sector_a: Identifier = "UNKNOWN"
    sector_b: Identifier = "UNKNOWN"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if utc(self.decision_at) != utc(self.request.signal_at):
            raise ValueError("Portfolio selection must be recorded at the signal cutoff")
        return self


FROZEN_PORTFOLIO_VERSION = "phase6-portfolio-20261016"
DEVELOPMENT_END = date(2023, 12, 31)


class PortfolioPolicy(FrozenModel):
    schema_version: Literal["pair-portfolio-policy-v1"] = "pair-portfolio-policy-v1"
    version: Identifier
    # Decision 36 froze the fixture allocation rules for accepted historical use.
    mode: Literal["FIXTURE", "DEVELOPMENT"] = "FIXTURE"
    initial_nav: Annotated[float, Field(gt=0, le=1e12)] = 1.0
    target_entry_fraction: Annotated[float, Field(gt=0, le=1)] = 0.25
    gross_entry_cap: Annotated[float, Field(gt=0, le=1)] = 1.0
    allocation: Literal["EQUAL_SIMULTANEOUS_CLIPPED_FIXED_SHARES"] = (
        "EQUAL_SIMULTANEOUS_CLIPPED_FIXED_SHARES"
    )
    idle_cash_yield: Annotated[float, Field(ge=0, le=0)] = 0.0
    unknown_nav_policy: Literal["PERMANENT_UNKNOWN_BLOCK_NEW_ENTRIES"] = (
        "PERMANENT_UNKNOWN_BLOCK_NEW_ENTRIES"
    )

    @model_validator(mode="after")
    def frozen_identity(self) -> Self:
        if (self.mode == "DEVELOPMENT") != (self.version == FROZEN_PORTFOLIO_VERSION):
            raise ValueError("Only the Decision 36 portfolio identity is a development policy")
        return self


class PortfolioTrade(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    proposal_sha256: SHA256
    shared_result_sha256: SHA256
    status: Literal["NOT_SELECTED", "NOT_ENTERED", "CAPACITY_REJECTED", "COMPLETE", "UNPRICED"]
    reason: Identifier
    allocation: Annotated[float, Field(ge=0, le=1e20)] = 0.0
    entry_at: datetime | None = None
    exit_at: datetime | None = None
    units_a: BoundedNumber | None = None
    units_b: BoundedNumber | None = None
    gross_pnl: BoundedNumber | None = None
    trading_cost: Annotated[float, Field(ge=0, le=1e20)] | None = None
    borrow_cost: Annotated[float, Field(ge=0, le=1e20)] | None = None
    net_pnl: BoundedNumber | None = None


class PortfolioMark(FrozenModel):
    session_date: date
    at: datetime
    phase: Literal["OPEN", "CLOSE"]
    nav: BoundedNumber | None
    cash_balance: BoundedNumber
    gross_exposure: Annotated[float, Field(ge=0, le=1e20)] | None
    net_exposure: BoundedNumber | None
    gross_fraction: Annotated[float, Field(ge=0, le=1e20)] | None
    entry_cap_breached_by_drift: bool | None
    open_positions: Annotated[int, Field(ge=0)]
    unresolved_positions: Annotated[int, Field(ge=0)]
    ticker_gross: dict[str, float] | None
    sector_gross: dict[str, float] | None
    turnover: Annotated[float, Field(ge=0, le=1e20)]
    turnover_fraction: Annotated[float, Field(ge=0, le=1e20)] | None
    trading_cost_charged: Annotated[float, Field(ge=0, le=1e20)]
    borrow_cost_charged: Annotated[float, Field(ge=0, le=1e20)]
    daily_return: BoundedNumber | None
    drawdown: BoundedNumber | None
    nav_unknown_since: datetime | None
    unknown_reasons: tuple[str, ...]


class PortfolioResult(FrozenModel):
    schema_version: Literal["pair-portfolio-result-v1"] = "pair-portfolio-result-v1"
    mode: Literal["SYNTHETIC_FIXTURE", "DEVELOPMENT_CAPTURE"] = "SYNTHETIC_FIXTURE"
    policy_sha256: SHA256
    execution_config_sha256: SHA256
    source_sha256: SHA256
    proposal_sha256: tuple[SHA256, ...]
    trades: tuple[PortfolioTrade, ...]
    marks: tuple[PortfolioMark, ...]
    initial_nav: float
    final_nav: float | None
    total_return: float | None
    maximum_drawdown: float | None
    known_trading_cost: float
    known_borrow_cost: float
    known_turnover: float
    unknown_nav_since: datetime | None
    scientific_acceptance: Literal[False] = False
    final_test_unlocked: Literal[False] = False
    limitations: tuple[str, ...] = (
        "SYNTHETIC_ENGINEERING_ONLY",
        "ENTRY_GROSS_CAP_ONLY_PASSIVE_FIXED_SHARE_DRIFT_DISCLOSED",
        "ZERO_IDLE_CASH_YIELD_NO_FINANCING_OR_INTRADAY_MARGIN_MODEL",
        "NO_PORTFOLIO_SHARPE_FROM_EVENT_RETURN_AVERAGES",
        "MISSING_HELD_QUOTES_PERMANENTLY_INVALIDATE_NAV",
        "NO_PRODUCTION_ALLOCATION_OR_EXECUTION_ASSUMPTION_FREEZE",
    )


def portfolio_source_sha256() -> str:
    """Bind portfolio and shared execution/validation rules across CRLF/LF."""
    digest = hashlib.sha256()
    for name in ("contracts.py", "simulator.py", "portfolio.py"):
        source = (Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n")
        digest.update(name.encode("ascii") + b"\0" + source + b"\0")
    return digest.hexdigest()


class _Held:
    def __init__(
        self, proposal: PortfolioProposal, result: PairTradeResult, allocation: float
    ) -> None:
        assert result.entry is not None and result.position is not None
        self.proposal = proposal
        self.result = result
        self.allocation = allocation
        self.a = allocation * result.position.units_a
        self.b = allocation * result.position.units_b
        self.entry_at = result.entry.at
        self.entry_day = result.entry.session_date
        self.entry_short = allocation * result.position.short_entry_notional
        self.borrow = 0.0
        self.trading = 0.0
        self.unresolved = False
        self.failure_reason: str | None = None


def simulate_portfolio(
    proposals: tuple[PortfolioProposal, ...],
    policy: PortfolioPolicy,
    execution_config: ExecutionConfig,
) -> PortfolioResult:
    """Batch simultaneous entries after exits, retaining every requested event.

    Allocation is target fraction of post-exit NAV per eligible proposal, clipped
    equally to available gross capacity. Reserve entry fees algebraically so
    gross/NAV after entry fees does not exceed the entry cap. Open borrow accrual
    precedes exits and charges precisely one interval for each overnight held
    position. No entry, monitoring or execution price is forward filled.
    """
    if not proposals:
        raise ValueError("Portfolio requires a nonempty explicit proposal inventory")
    source_identity = portfolio_source_sha256()
    if len({p.request.event_id for p in proposals}) != len(proposals):
        raise ValueError("Portfolio proposal event identities must be unique")
    quote_inventory: dict[tuple[str, date, str], float] = {}
    sectors: dict[str, str] = {}
    for proposal in proposals:
        event = proposal.request
        for ticker, sector in (
            (event.leg_a, proposal.sector_a),
            (event.leg_b, proposal.sector_b),
        ):
            if ticker in sectors and sectors[ticker] != sector:
                raise ValueError("Portfolio ticker sector identities must be consistent")
            sectors[ticker] = sector
        for bar in event.prices:
            for ticker, phase, price in (
                (event.leg_a, "OPEN", bar.open_a),
                (event.leg_b, "OPEN", bar.open_b),
                (event.leg_a, "CLOSE", bar.close_a),
                (event.leg_b, "CLOSE", bar.close_b),
            ):
                if price is None:
                    continue
                key = ticker, bar.session_date, phase
                if key in quote_inventory and not isclose(
                    quote_inventory[key], price, rel_tol=1e-12, abs_tol=1e-12
                ):
                    raise ValueError("Simultaneous ticker quotes must reconcile across pairs")
                quote_inventory[key] = price
    data_kinds = {proposal.request.data_kind for proposal in proposals}
    if policy.mode == "FIXTURE" and (
        data_kinds != {"SYNTHETIC_FIXTURE"}
        or (execution_config.mode, execution_config.status) != ("FIXTURE", "DRAFT")
    ):
        raise ValueError("Fixture portfolio accounting accepts synthetic fixtures only")
    if policy.mode == "DEVELOPMENT" and (
        data_kinds != {"DEVELOPMENT_CAPTURE"}
        or (execution_config.mode, execution_config.status) != ("DEVELOPMENT", "FROZEN")
    ):
        raise ValueError("Historical portfolio accounting needs captured data and frozen policy")
    if any(
        value is None
        for value in (
            execution_config.entry_cost_bps,
            execution_config.exit_cost_bps,
            execution_config.annual_borrow_rate,
            execution_config.positive_beta_limit,
        )
    ):
        raise ValueError("Portfolio fixture requires explicit shared execution parameters")
    assert execution_config.entry_cost_bps is not None
    assert execution_config.exit_cost_bps is not None
    assert execution_config.annual_borrow_rate is not None
    ordered = tuple(sorted(proposals, key=lambda p: (utc(p.request.signal_at), p.request.event_id)))
    # COMPLETE is never an eligibility condition. Entries with later unknown
    # monitoring/exit prices remain in the chronological allocation inventory.
    results = {
        p.request.event_id: simulate_pair_trade(p.request, execution_config) for p in ordered
    }
    starts = [p.request.sessions[0].session_date for p in ordered]
    ends = [p.request.sessions[-1].session_date for p in ordered]
    last_declared_day = max(ends)
    sessions = list(canonical_sessions(min(starts), last_declared_day))
    pending: dict[date, list[PortfolioProposal]] = {}
    trade_rows: dict[str, PortfolioTrade] = {}
    held: dict[str, _Held] = {}
    cash = policy.initial_nav
    unknown_at: datetime | None = None
    unknown_reasons: set[str] = set()
    marks: list[PortfolioMark] = []
    previous_close = policy.initial_nav
    peak = policy.initial_nav
    drawdowns: list[float] = []
    total_trading = total_borrow = total_turnover = 0.0
    truncated = False

    def base_trade(proposal: PortfolioProposal) -> dict[str, Any]:
        event = proposal.request
        return {
            "event_id": event.event_id,
            "pair_id": event.pair_id,
            "proposal_sha256": sha256(proposal),
            "shared_result_sha256": sha256(results[event.event_id]),
        }

    for proposal in ordered:
        event = proposal.request
        result = results[event.event_id]
        if not proposal.selected:
            trade_rows[event.event_id] = PortfolioTrade(
                **base_trade(proposal), status="NOT_SELECTED", reason="STORED_SELECTION_WITHHELD"
            )
        elif len(event.sessions) < 2:
            trade_rows[event.event_id] = PortfolioTrade(
                **base_trade(proposal), status="NOT_ENTERED", reason=result.reason
            )
        else:
            pending.setdefault(event.sessions[1].session_date, []).append(proposal)

    def fail(position: _Held, at: datetime, reason: str) -> None:
        nonlocal unknown_at
        position.unresolved = True
        if position.failure_reason is None:
            position.failure_reason = reason
        if unknown_at is None:
            unknown_at = at
        unknown_reasons.add(f"{position.proposal.request.event_id}:{reason}")

    def quote(position: _Held, day: date, phase: str) -> tuple[float, float] | None:
        bar = next((b for b in position.proposal.request.prices if b.session_date == day), None)
        if bar is None:
            return None
        a = bar.open_a if phase == "OPEN" else bar.close_a
        b = bar.open_b if phase == "OPEN" else bar.close_b
        return None if a is None or b is None else (a, b)

    def values(
        day: date, phase: str, at: datetime
    ) -> tuple[float, float, dict[str, float], dict[str, float]]:
        gross = net = 0.0
        ticker: dict[str, float] = {}
        sector: dict[str, float] = {}
        for position in held.values():
            if position.unresolved:
                continue
            event = position.proposal.request
            if event.lifecycle_termination is not None and day >= event.lifecycle_termination:
                fail(position, at, "LIFECYCLE_TERMINATION")
                continue
            prices = quote(position, day, phase)
            if prices is None:
                fail(position, at, f"MISSING_HELD_{phase}_PRICE")
                continue
            for name, industry, units, price in (
                (event.leg_a, position.proposal.sector_a, position.a, prices[0]),
                (event.leg_b, position.proposal.sector_b, position.b, prices[1]),
            ):
                exposure = abs(units) * price
                gross += exposure
                net += units * price
                ticker[name] = ticker.get(name, 0.0) + exposure
                sector[industry] = sector.get(industry, 0.0) + exposure
        return gross, net, dict(sorted(ticker.items())), dict(sorted(sector.items()))

    for day, opening, closing in sessions:
        turnover = trading = borrow = 0.0
        for position in held.values():
            if day > position.entry_day and not position.unresolved:
                charge = (
                    position.entry_short
                    * execution_config.annual_borrow_rate
                    / execution_config.annual_trading_sessions
                )
                position.borrow += charge
                borrow += charge
        cash -= borrow
        total_borrow += borrow
        values(day, "OPEN", opening)
        # A previously observed close trigger exits before fresh allocations.
        for pair_id, position in tuple(held.items()):
            result = position.result
            if position.unresolved or result.exit is None or result.exit.session_date != day:
                continue
            exit_a, exit_b = result.exit.price_a, result.exit.price_b
            exit_turnover = abs(position.a) * exit_a + abs(position.b) * exit_b
            fee = exit_turnover * execution_config.exit_cost_bps / 10000.0
            cash += position.a * exit_a + position.b * exit_b - fee
            turnover += exit_turnover
            trading += fee
            position.trading += fee
            assert result.entry is not None
            pnl = position.a * (exit_a - result.entry.price_a) + position.b * (
                exit_b - result.entry.price_b
            )
            # Independent ledger must reconcile exactly with the unit event engine.
            assert result.net_return is not None
            if not isclose(
                pnl - position.trading - position.borrow,
                position.allocation * result.net_return,
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "Portfolio costs/units do not reconcile with shared pair execution"
                )
            trade_rows[position.proposal.request.event_id] = PortfolioTrade(
                **base_trade(position.proposal),
                status="COMPLETE",
                reason=result.reason,
                allocation=position.allocation,
                entry_at=position.entry_at,
                exit_at=result.exit.at,
                units_a=position.a,
                units_b=position.b,
                gross_pnl=pnl,
                trading_cost=position.trading,
                borrow_cost=position.borrow,
                net_pnl=pnl - position.trading - position.borrow,
            )
            del held[pair_id]
        gross, net, _, _ = values(day, "OPEN", opening)
        nav = cash + net if unknown_at is None else None
        eligible: list[PortfolioProposal] = []
        # One pair slot per open; simultaneous duplicates use lexical event ID.
        occupied = set(held)
        for proposal in sorted(pending.get(day, ()), key=lambda p: p.request.event_id):
            event = proposal.request
            result = results[event.event_id]
            reason: str | None = None
            if result.entry is None:
                reason = result.reason
            elif event.pair_id in occupied:
                reason = "PAIR_ALREADY_OPEN"
            elif nav is None:
                reason = "PORTFOLIO_NAV_UNKNOWN"
            elif nav <= 0:
                reason = "NONPOSITIVE_PORTFOLIO_NAV"
            if reason is not None:
                trade_rows[event.event_id] = PortfolioTrade(
                    **base_trade(proposal), status="NOT_ENTERED", reason=reason
                )
            else:
                occupied.add(event.pair_id)
                eligible.append(proposal)
        if eligible:
            assert nav is not None and nav > 0
            entry_rate = execution_config.entry_cost_bps / 10000.0
            capacity = max(
                0.0,
                (policy.gross_entry_cap * nav - gross)
                / (1.0 + policy.gross_entry_cap * entry_rate),
            )
            allocation = min(policy.target_entry_fraction * nav, capacity / len(eligible))
            for proposal in eligible:
                if allocation <= 1e-15:
                    trade_rows[proposal.request.event_id] = PortfolioTrade(
                        **base_trade(proposal),
                        status="CAPACITY_REJECTED",
                        reason="NO_GROSS_CAPACITY",
                    )
                    continue
                result = results[proposal.request.event_id]
                assert result.entry is not None
                position = _Held(proposal, result, allocation)
                fee = allocation * entry_rate
                position.trading += fee
                cash -= position.a * result.entry.price_a + position.b * result.entry.price_b + fee
                turnover += allocation
                trading += fee
                held[proposal.request.pair_id] = position
        total_trading += trading
        total_turnover += turnover

        for phase, at in (("OPEN", opening), ("CLOSE", closing)):
            gross, net, ticker_values, sector_values = values(day, phase, at)
            # A complete portfolio mark requires the pair engine's required
            # monitoring prefix, not merely an available convenient quote.
            if phase == "CLOSE":
                for position in held.values():
                    event = position.proposal.request
                    result = position.result
                    if position.unresolved:
                        continue
                    observed = {mark.session_date for mark in result.marks}
                    if day >= position.entry_day and day not in observed:
                        fail(position, at, result.reason)
            mark_nav = cash + net if unknown_at is None else None
            daily_return: float | None = None
            drawdown: float | None = None
            if mark_nav is not None:
                peak = max(peak, mark_nav)
                drawdown = mark_nav / peak - 1.0
                drawdowns.append(drawdown)
                if phase == "CLOSE":
                    daily_return = mark_nav / previous_close - 1.0 if previous_close > 0 else None
                    previous_close = mark_nav
            ratio = gross / mark_nav if mark_nav is not None and mark_nav > 0 else None
            marks.append(
                PortfolioMark(
                    session_date=day,
                    at=at,
                    phase=cast(Literal["OPEN", "CLOSE"], phase),
                    nav=mark_nav,
                    cash_balance=cash,
                    gross_exposure=gross if unknown_at is None else None,
                    net_exposure=net if unknown_at is None else None,
                    gross_fraction=ratio,
                    entry_cap_breached_by_drift=(
                        ratio > policy.gross_entry_cap + 1e-10 if ratio is not None else None
                    ),
                    open_positions=len(held),
                    unresolved_positions=sum(p.unresolved for p in held.values()),
                    ticker_gross=ticker_values if unknown_at is None else None,
                    sector_gross=sector_values if unknown_at is None else None,
                    turnover=turnover if phase == "OPEN" else 0.0,
                    turnover_fraction=(
                        turnover / nav if phase == "OPEN" and nav is not None and nav > 0 else None
                    ),
                    trading_cost_charged=trading if phase == "OPEN" else 0.0,
                    borrow_cost_charged=borrow if phase == "OPEN" else 0.0,
                    daily_return=daily_return,
                    drawdown=drawdown,
                    nav_unknown_since=unknown_at,
                    unknown_reasons=tuple(sorted(unknown_reasons)),
                )
            )
        # Only an actually allocated, still-valued position needs a subsequent
        # missing-mark boundary. A doomed rejected proposal never extends the
        # evaluation timeline using its future outcome.
        if day == last_declared_day and held and unknown_at is None:
            following = canonical_sessions(day, day + timedelta(days=14))
            if len(following) < 2:
                raise ValueError("Incomplete position has no bounded next development session")
            if policy.mode == "DEVELOPMENT" and following[1][0] > DEVELOPMENT_END:
                # Accepted history ends before the locked final test: positions still
                # open stay unresolved and no terminal NAV is claimed or constructed.
                for position in held.values():
                    fail(position, closing, "DEVELOPMENT_END_TRUNCATION")
                truncated = True
                continue
            development_date(following[1][0])
            sessions.append(following[1])
    for position in held.values():
        trade_rows[position.proposal.request.event_id] = PortfolioTrade(
            **base_trade(position.proposal),
            status="UNPRICED",
            reason=position.failure_reason or position.result.reason,
            allocation=position.allocation,
            entry_at=position.entry_at,
            units_a=position.a,
            units_b=position.b,
        )
    final = None if truncated else marks[-1].nav
    if portfolio_source_sha256() != source_identity:
        raise ValueError("Portfolio computational source changed during calculation")
    development = policy.mode == "DEVELOPMENT"
    return PortfolioResult(
        mode="DEVELOPMENT_CAPTURE" if development else "SYNTHETIC_FIXTURE",
        limitations=(
            "POST_HOC_DEVELOPMENT_ASSESSMENT_NOT_FINAL_TEST"
            if development
            else "SYNTHETIC_ENGINEERING_ONLY",
            "ENTRY_GROSS_CAP_ONLY_PASSIVE_FIXED_SHARE_DRIFT_DISCLOSED",
            "ZERO_IDLE_CASH_YIELD_NO_FINANCING_OR_INTRADAY_MARGIN_MODEL",
            "NO_PORTFOLIO_SHARPE_FROM_EVENT_RETURN_AVERAGES",
            "MISSING_HELD_QUOTES_PERMANENTLY_INVALIDATE_NAV",
            "DECISION_35_FROZEN_ALLOCATION_AND_EXECUTION"
            if development
            else "NO_PRODUCTION_ALLOCATION_OR_EXECUTION_ASSUMPTION_FREEZE",
        ),
        policy_sha256=sha256(policy),
        execution_config_sha256=sha256(execution_config),
        source_sha256=source_identity,
        proposal_sha256=tuple(sha256(p) for p in ordered),
        trades=tuple(trade_rows[p.request.event_id] for p in ordered),
        marks=tuple(marks),
        initial_nav=policy.initial_nav,
        final_nav=final,
        total_return=final / policy.initial_nav - 1.0 if final is not None else None,
        maximum_drawdown=min(drawdowns) if unknown_at is None else None,
        known_trading_cost=total_trading,
        known_borrow_cost=total_borrow,
        known_turnover=total_turnover,
        unknown_nav_since=unknown_at,
    )

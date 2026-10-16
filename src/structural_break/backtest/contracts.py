"""Strict development-only inputs for the common event execution engine.

The future price path is execution/outcome data, never an agent/model predictor.
Declared sessions are checked against the local XNYS calendar, including holidays,
early closes and daylight saving. Missing observations remain explicit nulls.
"""

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from math import isclose, log
from typing import Annotated, Literal, Self, TypeAlias, cast

import exchange_calendars as xcals
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Ticker = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9.-]{0,19}$")]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Price = Annotated[float, Field(ge=1e-8, le=1e12)]
BoundedNumber = Annotated[float, Field(ge=-1e20, le=1e20)]
Status: TypeAlias = Literal["COMPLETE", "NOT_ENTERED", "UNPRICED"]
Reason: TypeAlias = Literal[
    "CONVERGENCE",
    "ADVERSE_STOP",
    "TIMEOUT",
    "POLICY_NOT_FROZEN",
    "POLICY_PARAMETERS_MISSING",
    "INVALID_ECONOMIC_BETA",
    "ILLIQUID_LEG",
    "MISSING_LEG_LIQUIDITY",
    "SIGNAL_NOT_DIVERGED",
    "MISSING_SIGNAL_CLOSE",
    "MISSING_ENTRY_OPEN",
    "MISSING_MONITORING_CLOSE",
    "MISSING_EXIT_OPEN",
    "INCOMPLETE_SESSION_PATH",
    "LIFECYCLE_TERMINATION",
]
Direction: TypeAlias = Literal["SHORT_A_LONG_B", "LONG_A_SHORT_B"]
ExitReason: TypeAlias = Literal["CONVERGENCE", "ADVERSE_STOP", "TIMEOUT"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Execution timestamps must be timezone-aware")
    return value.astimezone(UTC)


def development_date(value: date) -> None:
    if not date(2004, 1, 1) <= value <= date(2023, 12, 31):
        raise ValueError("Execution inputs are development-only; 2024+ remains locked")


@lru_cache(maxsize=1)
def _development_calendar() -> pd.DataFrame:
    # One calendar avoids rebuilding the exchange schedule per historical event.
    # Padding covers next-open admissibility near both development boundaries.
    calendar = xcals.get_calendar("XNYS", start="2003-12-01", end="2024-01-15")
    return cast(pd.DataFrame, calendar.schedule)


@lru_cache(maxsize=128)
def canonical_sessions(start: date, end: date) -> tuple[tuple[date, datetime, datetime], ...]:
    """Local deterministic exchange calendar; no market downloads."""
    if start > end or start < date(2003, 12, 1) or end > date(2024, 1, 15):
        raise ValueError("Requested session range lies outside the bounded development calendar")
    schedule = _development_calendar().loc[pd.Timestamp(start) : pd.Timestamp(end)]
    return tuple(
        (
            cast(pd.Timestamp, day).date(),
            cast(pd.Timestamp, opening).to_pydatetime(),
            cast(pd.Timestamp, closing).to_pydatetime(),
        )
        for day, opening, closing in schedule[["open", "close"]].itertuples(name=None)
    )


class MarketSession(FrozenModel):
    session_date: date
    open_at: datetime
    close_at: datetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        development_date(self.session_date)
        if utc(self.open_at) >= utc(self.close_at):
            raise ValueError("Market open must precede close")
        return self


class RelationshipSnapshot(FrozenModel):
    snapshot_id: Identifier
    available_at: datetime
    formation_end: date
    alpha: Annotated[float, Field(ge=-1e6, le=1e6)]
    beta: Annotated[float, Field(ge=-100, le=100)]
    spread_mean: Annotated[float, Field(ge=-1e6, le=1e6)]
    spread_std: Annotated[float, Field(gt=1e-12, le=1e6)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        utc(self.available_at)
        development_date(self.formation_end)
        return self

    def z(self, a: float, b: float) -> float:
        return (log(a) - self.alpha - self.beta * log(b) - self.spread_mean) / self.spread_std


class PairPrices(FrozenModel):
    session_date: date
    open_a: Price | None = None
    open_b: Price | None = None
    close_a: Price | None = None
    close_b: Price | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        development_date(self.session_date)
        return self


class PriceLineage(FrozenModel):
    source_snapshot_id: Identifier
    source_sha256: SHA256
    price_basis: Literal["ADJUSTED_OPEN_CLOSE"]
    adjustment_policy: Identifier


class PairTradeRequest(FrozenModel):
    schema_version: Literal["pair-trade-request-v1"] = "pair-trade-request-v1"
    data_kind: Literal["SYNTHETIC_FIXTURE", "DEVELOPMENT_CAPTURE"]
    event_id: Identifier
    pair_id: Identifier
    leg_a: Ticker
    leg_b: Ticker
    signal_at: datetime
    signal_z: Annotated[float, Field(ge=-1000, le=1000)]
    snapshot: RelationshipSnapshot
    price_lineage: PriceLineage
    sessions: Annotated[tuple[MarketSession, ...], Field(min_length=1, max_length=64)]
    prices: Annotated[tuple[PairPrices, ...], Field(max_length=64)]
    lifecycle_termination: date | None = None
    # Mean dollar volume over the exact 20 XNYS sessions ending at the signal
    # close (admissible at the signal); None means unknown, never zero.
    signal_adv20_usd_a: Annotated[float, Field(ge=0, le=1e15)] | None = None
    signal_adv20_usd_b: Annotated[float, Field(ge=0, le=1e15)] | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.leg_a == self.leg_b or self.pair_id != f"{self.leg_a}__{self.leg_b}":
            raise ValueError("Pair identity must preserve two distinct oriented legs")
        signal = utc(self.signal_at)
        dates = tuple(session.session_date for session in self.sessions)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("Declared sessions must be unique and ordered")
        expected = canonical_sessions(dates[0], dates[-1])
        actual = tuple(
            (session.session_date, utc(session.open_at), utc(session.close_at))
            for session in self.sessions
        )
        if actual != expected:
            raise ValueError("Declared sessions must exactly match every XNYS session")
        if signal != utc(self.sessions[0].close_at):
            raise ValueError("Signal cutoff must be the first declared XNYS session close")
        if utc(self.snapshot.available_at) > signal or self.snapshot.formation_end > dates[0]:
            raise ValueError("Relationship snapshot must be available by the signal cutoff")
        formation = canonical_sessions(
            self.snapshot.formation_end, self.snapshot.formation_end + timedelta(days=14)
        )
        if not formation or formation[0][0] != self.snapshot.formation_end:
            raise ValueError("Formation endpoint must be an actual XNYS session")
        if utc(formation[0][2]) > utc(self.snapshot.available_at):
            raise ValueError("Formation endpoint must close before snapshot availability")
        if len(formation) < 2 or utc(self.snapshot.available_at) < utc(formation[1][1]):
            raise ValueError("Relationship snapshot becomes usable at the next XNYS open")
        price_dates = tuple(row.session_date for row in self.prices)
        if price_dates != tuple(sorted(set(price_dates))):
            raise ValueError("Price rows must be unique and ordered")
        if not set(price_dates).issubset(dates):
            raise ValueError("Price observations must belong to declared sessions")
        if self.lifecycle_termination is not None:
            development_date(self.lifecycle_termination)
        signal_row = next((row for row in self.prices if row.session_date == dates[0]), None)
        if signal_row and signal_row.close_a is not None and signal_row.close_b is not None:
            observed = self.snapshot.z(signal_row.close_a, signal_row.close_b)
            if not isclose(self.signal_z, observed, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("Signal z must reconcile with frozen log-price parameters")
        return self


class ExecutionConfig(FrozenModel):
    schema_version: Literal["pair-execution-policy-v1", "pair-execution-policy-v2"] = (
        "pair-execution-policy-v1"
    )
    version: Identifier
    mode: Literal["FIXTURE", "DEVELOPMENT"]
    status: Literal["DRAFT", "FROZEN"]
    horizon_sessions: Literal[10, 20, 30] = 20
    entry_threshold: Annotated[float, Field(ge=2.0, le=2.0)] = 2.0
    convergence_band: Annotated[float, Field(ge=0.5, le=0.5)] = 0.5
    adverse_boundary: Annotated[float, Field(ge=3.0, le=3.0)] = 3.0
    positive_beta_limit: Annotated[float, Field(gt=0, le=100)] | None = None
    entry_cost_bps: Annotated[float, Field(ge=0, le=100)] | None = None
    exit_cost_bps: Annotated[float, Field(ge=0, le=100)] | None = None
    annual_borrow_rate: Annotated[float, Field(ge=0, le=1)] | None = None
    annual_trading_sessions: Literal[252] = 252
    # v2 adds a shared minimum-leg liquidity gate; 0 explicitly disables it.
    min_leg_adv20_usd: Annotated[float, Field(ge=0, le=1e12)] | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.mode == "FIXTURE" and self.status != "DRAFT":
            raise ValueError("Synthetic fixture assumptions cannot freeze a production policy")
        if self.schema_version == "pair-execution-policy-v1" and self.min_leg_adv20_usd is not None:
            raise ValueError("The liquidity floor requires execution policy schema v2")
        return self


class Execution(FrozenModel):
    session_date: date
    at: datetime
    price_a: Price
    price_b: Price

    @model_validator(mode="after")
    def coherent(self) -> Self:
        development_date(self.session_date)
        expected = canonical_sessions(self.session_date, self.session_date)
        if not expected or utc(self.at) != utc(expected[0][1]):
            raise ValueError("Executions must use the exact declared XNYS open")
        return self


class Position(FrozenModel):
    direction: Direction
    weight_a: BoundedNumber
    weight_b: BoundedNumber
    units_a: BoundedNumber
    units_b: BoundedNumber
    short_entry_notional: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        side = 1.0 if self.direction == "SHORT_A_LONG_B" else -1.0
        if not side * self.weight_a < 0 < side * self.weight_b:
            raise ValueError("Weights must preserve the declared long/short direction")
        if not side * self.units_a < 0 < side * self.units_b:
            raise ValueError("Frozen units must preserve the declared long/short direction")
        if not isclose(abs(self.weight_a) + abs(self.weight_b), 1.0, abs_tol=1e-12):
            raise ValueError("Entry gross notional must equal one")
        short = abs(self.weight_a if self.weight_a < 0 else self.weight_b)
        if not isclose(self.short_entry_notional, short, abs_tol=1e-12):
            raise ValueError("Borrow notional must equal the entry short leg notional")
        return self


class TradeMark(FrozenModel):
    session_date: date
    at: datetime
    price_a: Price
    price_b: Price
    z: BoundedNumber
    gross_return: BoundedNumber
    gross_exposure: Annotated[float, Field(gt=0, le=1e20)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        development_date(self.session_date)
        expected = canonical_sessions(self.session_date, self.session_date)
        if not expected or utc(self.at) != utc(expected[0][2]):
            raise ValueError("Monitoring marks must use the exact XNYS close")
        return self


class ExitTrigger(FrozenModel):
    reason: ExitReason
    session_date: date
    at: datetime
    z: BoundedNumber

    @model_validator(mode="after")
    def coherent(self) -> Self:
        development_date(self.session_date)
        expected = canonical_sessions(self.session_date, self.session_date)
        if not expected or utc(self.at) != utc(expected[0][2]):
            raise ValueError("Exit triggers must use the exact XNYS close")
        return self


class PairTradeResult(FrozenModel):
    schema_version: Literal["pair-trade-result-v1"] = "pair-trade-result-v1"
    simulator_version: Literal["pair-simulator-v1"] = "pair-simulator-v1"
    simulator_source_sha256: SHA256
    event_id: Identifier
    pair_id: Identifier
    request_sha256: SHA256
    execution_config_sha256: SHA256
    execution_config_version: Identifier
    snapshot_id: Identifier
    price_lineage: PriceLineage
    data_kind: Literal["SYNTHETIC_FIXTURE", "DEVELOPMENT_CAPTURE"]
    status: Status
    reason: Reason
    signal_z: BoundedNumber
    entry: Execution | None = None
    position: Position | None = None
    trigger: ExitTrigger | None = None
    exit: Execution | None = None
    holding_sessions: Annotated[int, Field(ge=1, le=30)] | None = None
    gross_return: BoundedNumber | None = None
    net_return: BoundedNumber | None = None
    trading_cost: Annotated[float, Field(ge=0, le=1e20)] | None = None
    borrow_cost: Annotated[float, Field(ge=0, le=1)] | None = None
    mae: BoundedNumber | None = None
    mfe: BoundedNumber | None = None
    partial_mae: BoundedNumber | None = None
    partial_mfe: BoundedNumber | None = None
    entry_gap_z: BoundedNumber | None = None
    marks: Annotated[tuple[TradeMark, ...], Field(max_length=30)] = ()
    limitations: tuple[
        Literal[
            "SYNTHETIC_ENGINEERING_ONLY",
            "ADJUSTMENT_BASIS_DECLARED_NOT_INDEPENDENTLY_VERIFIED",
            "OBSERVED_CLOSES_AND_EXIT_ONLY_NO_INTRADAY_EXTREMES",
            "NO_PORTFOLIO_OR_LADDER_SELECTION",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        economics = (
            self.holding_sessions,
            self.gross_return,
            self.net_return,
            self.trading_cost,
            self.borrow_cost,
        )
        if self.status == "COMPLETE":
            if self.partial_mae is not None or self.partial_mfe is not None:
                raise ValueError("Complete trades must use complete sampled-path excursions")
            if any(value is None for value in (self.entry, self.position, self.trigger, self.exit)):
                raise ValueError("Complete trades require both executions and a close trigger")
            if any(value is None for value in economics):
                raise ValueError("Complete trades require reconciled economics")
            if self.reason not in ("CONVERGENCE", "ADVERSE_STOP", "TIMEOUT"):
                raise ValueError("Complete trades require an execution exit reason")
            assert self.entry is not None and self.position is not None
            assert self.exit is not None and self.trigger is not None
            assert self.gross_return is not None and self.net_return is not None
            assert self.trading_cost is not None and self.borrow_cost is not None
            if self.reason != self.trigger.reason:
                raise ValueError("Terminal reason must match the actual close trigger")
            exit_sessions = canonical_sessions(self.trigger.session_date, self.exit.session_date)
            if len(exit_sessions) != 2 or utc(self.entry.at) > utc(self.trigger.at):
                raise ValueError(
                    "Exit must be the exact next session after an observed close trigger"
                )
            holding = canonical_sessions(self.entry.session_date, self.exit.session_date)
            if self.holding_sessions != len(holding) - 1:
                raise ValueError("Borrow holding period must reconcile to open-to-open sessions")
            gross = self.position.units_a * (self.exit.price_a - self.entry.price_a)
            gross += self.position.units_b * (self.exit.price_b - self.entry.price_b)
            if not isclose(self.gross_return, gross, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Terminal P&L must reconcile to frozen share units")
            if not isclose(
                self.net_return,
                gross - self.trading_cost - self.borrow_cost,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("Net return must reconcile to gross P&L and explicit costs")
        else:
            if any(value is not None for value in economics) or self.exit is not None:
                raise ValueError("Unpriced/non-entered trades must not fabricate terminal returns")
            if self.mae is not None or self.mfe is not None:
                raise ValueError("Unpriced/non-entered trades cannot claim full-path excursions")
            if self.reason in ("CONVERGENCE", "ADVERSE_STOP", "TIMEOUT"):
                raise ValueError("Incomplete trades require an explicit failure reason")
            if self.status == "NOT_ENTERED":
                if (
                    any(
                        value is not None
                        for value in (
                            self.entry,
                            self.position,
                            self.trigger,
                            self.mae,
                            self.mfe,
                            self.entry_gap_z,
                            self.partial_mae,
                            self.partial_mfe,
                        )
                    )
                    or self.marks
                ):
                    raise ValueError("Non-entered events cannot have positions or price marks")
            elif self.entry is None or self.position is None:
                raise ValueError("Unpriced trades must preserve the actual opened position")
        if self.entry is not None:
            assert self.position is not None
            if not isclose(
                self.position.weight_a,
                self.position.units_a * self.entry.price_a,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("Leg A units must reconcile to entry weight and price")
            if not isclose(
                self.position.weight_b,
                self.position.units_b * self.entry.price_b,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("Leg B units must reconcile to entry weight and price")
            returns = [0.0]
            for mark in self.marks:
                if utc(mark.at) <= utc(self.entry.at):
                    raise ValueError("Monitoring marks must follow the actual entry")
                gross = self.position.units_a * (mark.price_a - self.entry.price_a)
                gross += self.position.units_b * (mark.price_b - self.entry.price_b)
                exposure = abs(self.position.units_a) * mark.price_a
                exposure += abs(self.position.units_b) * mark.price_b
                if not isclose(mark.gross_return, gross, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("Close P&L must reconcile to frozen share units")
                if not isclose(mark.gross_exposure, exposure, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("Close exposure must reconcile to frozen share units")
                returns.append(mark.gross_return)
            if self.marks:
                monitored = canonical_sessions(self.entry.session_date, self.marks[-1].session_date)
                if tuple(mark.session_date for mark in self.marks) != tuple(
                    row[0] for row in monitored
                ):
                    raise ValueError("Monitoring must preserve every required close without gaps")
            if self.trigger is not None:
                if not self.marks or self.trigger.at != self.marks[-1].at:
                    raise ValueError("Exit trigger must match the last observed close")
                if self.trigger.z != self.marks[-1].z:
                    raise ValueError("Exit trigger must preserve the observed close z")
            if self.gross_return is not None:
                returns.append(self.gross_return)
            observed_mae = self.mae if self.status == "COMPLETE" else self.partial_mae
            observed_mfe = self.mfe if self.status == "COMPLETE" else self.partial_mfe
            if observed_mae is None or observed_mfe is None:
                raise ValueError("Opened positions must disclose observed partial excursions")
            if not isclose(observed_mae, min(returns), abs_tol=1e-12):
                raise ValueError("MAE must include entry, observed closes and any priced exit")
            if not isclose(observed_mfe, max(returns), abs_tol=1e-12):
                raise ValueError("MFE must include entry, observed closes and any priced exit")
        return self

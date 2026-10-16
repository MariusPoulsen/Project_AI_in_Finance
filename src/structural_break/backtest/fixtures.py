"""Synthetic price path with an independently hand-calculable 10% gross return."""

from datetime import date
from math import exp, log

from structural_break.backtest.contracts import (
    MarketSession,
    PairPrices,
    PairTradeRequest,
    PriceLineage,
    RelationshipSnapshot,
    canonical_sessions,
)


def synthetic_trade_request() -> PairTradeRequest:
    sessions = tuple(
        MarketSession(session_date=day, open_at=opening, close_at=closing)
        for day, opening, closing in canonical_sessions(date(2023, 1, 3), date(2023, 1, 5))
    )
    snapshot = RelationshipSnapshot(
        snapshot_id="synthetic-relationship-v1",
        available_at=sessions[0].open_at,
        formation_end=date(2022, 12, 30),
        alpha=log(200.0) - 2.0 * log(100.0) - 0.24,
        beta=2.0,
        spread_mean=0.0,
        spread_std=0.1,
    )
    # At entry: short 1/3 of gross in A at 210, long 2/3 in B at 100.
    # At exit: A=189 (-10%) and B=110 (+10%): gross P&L = +10%.
    # The intervening close is within the band; its quote is not the exit fill.
    converged_a = exp(snapshot.alpha + 2.0 * log(100.0) + 0.04)
    return PairTradeRequest(
        data_kind="SYNTHETIC_FIXTURE",
        event_id="synthetic-convergence-event-v1",
        pair_id="AAA__BBB",
        leg_a="AAA",
        leg_b="BBB",
        signal_at=sessions[0].close_at,
        signal_z=2.4,
        snapshot=snapshot,
        price_lineage=PriceLineage(
            source_snapshot_id="synthetic-prices-v1",
            source_sha256="0" * 64,
            price_basis="ADJUSTED_OPEN_CLOSE",
            adjustment_policy="synthetic-no-corporate-actions-v1",
        ),
        sessions=sessions,
        prices=(
            PairPrices(session_date=sessions[0].session_date, close_a=200.0, close_b=100.0),
            PairPrices(
                session_date=sessions[1].session_date,
                open_a=210.0,
                open_b=100.0,
                close_a=converged_a,
                close_b=100.0,
            ),
            PairPrices(session_date=sessions[2].session_date, open_a=189.0, open_b=110.0),
        ),
    )

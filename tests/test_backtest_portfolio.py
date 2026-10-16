"""Hand-ledger tests for chronological portfolio capital and missingness."""

from datetime import date, timedelta
from math import exp, log
from typing import Any

import pytest
from pydantic import ValidationError

from structural_break.backtest.contracts import (
    MarketSession,
    PairPrices,
    PairTradeRequest,
    RelationshipSnapshot,
    canonical_sessions,
)
from structural_break.backtest.portfolio import (
    PortfolioPolicy,
    PortfolioProposal,
    simulate_portfolio,
)
from structural_break.backtest.portfolio_fixtures import fixture_portfolio
from structural_break.backtest.simulator import simulate_pair_trade


def update_request(proposal: PortfolioProposal, **changes: Any) -> PortfolioProposal:
    request = PairTradeRequest.model_validate({**proposal.request.model_dump(), **changes})
    return PortfolioProposal.model_validate(
        {**proposal.model_dump(), "request": request, "decision_at": request.signal_at}
    )


def update_bars(proposal: PortfolioProposal, index: int, **changes: Any) -> PortfolioProposal:
    bars = list(proposal.request.prices)
    bars[index] = PairPrices.model_validate({**bars[index].model_dump(), **changes})
    return update_request(proposal, prices=tuple(bars))


def shift(proposal: PortfolioProposal, *, day: date, event_id: str) -> PortfolioProposal:
    sessions = tuple(
        MarketSession(session_date=d, open_at=o, close_at=c)
        for d, o, c in canonical_sessions(day, day + timedelta(days=5))[:3]
    )
    bars = tuple(
        PairPrices.model_validate({**bar.model_dump(), "session_date": session.session_date})
        for bar, session in zip(proposal.request.prices, sessions, strict=True)
    )
    return update_request(
        proposal, event_id=event_id, signal_at=sessions[0].close_at, sessions=sessions, prices=bars
    )


def longer(proposal: PortfolioProposal) -> PortfolioProposal:
    """Enter Jan4, observe unchanged z, converge Jan5, exit Jan6."""
    sessions = tuple(
        MarketSession(session_date=d, open_at=o, close_at=c)
        for d, o, c in canonical_sessions(date(2023, 1, 3), date(2023, 1, 6))
    )
    source = proposal.request
    bars = (
        source.prices[0],
        PairPrices(
            session_date=date(2023, 1, 4),
            open_a=210.0,
            open_b=100.0,
            close_a=200.0,
            close_b=100.0,
        ),
        PairPrices(
            session_date=date(2023, 1, 5),
            open_a=205.0,
            open_b=100.0,
            close_a=source.prices[1].close_a,
            close_b=100.0,
        ),
        PairPrices(
            session_date=date(2023, 1, 6),
            open_a=189.0,
            open_b=110.0,
            close_a=189.0,
            close_b=110.0,
        ),
    )
    return update_request(proposal, sessions=sessions, prices=bars)


def test_two_simultaneous_trades_reconcile_hand_cash_units_costs_and_nav() -> None:
    proposals, policy, config = fixture_portfolio()
    result = simulate_portfolio(proposals, policy, config)
    # Each gross allocation .25: short A=1/12 at210, long B=1/6 at100.
    expected_gross = 0.05
    entry_cost = 0.5 * 0.0005
    exit_cost = 0.5 * (0.9 / 3.0 + 2.0 * 1.1 / 3.0) * 0.0005
    borrow = 0.5 / 3.0 * 0.03 / 252.0
    assert result.final_nav == pytest.approx(1.0 + expected_gross - entry_cost - exit_cost - borrow)
    assert result.total_return == pytest.approx(0.0494718253968254)
    assert result.known_trading_cost == pytest.approx(entry_cost + exit_cost)
    assert result.known_borrow_cost == pytest.approx(borrow)
    assert result.known_turnover == pytest.approx(0.5 + 0.5 * (0.9 / 3 + 2 * 1.1 / 3))
    entry = result.marks[2]
    assert entry.nav == pytest.approx(0.99975)
    assert entry.cash_balance == pytest.approx(1.0 - 0.5 / 3.0 - entry_cost)
    assert entry.gross_exposure == pytest.approx(0.5)
    assert entry.net_exposure == pytest.approx(0.5 / 3)
    assert entry.ticker_gross == pytest.approx(
        {"AAA": 1 / 12, "BBB": 1 / 6, "CCC": 1 / 12, "DDD": 1 / 6}
    )
    assert entry.sector_gross == pytest.approx({"TECHNOLOGY": 0.5})
    assert [trade.allocation for trade in result.trades] == [0.25, 0.25]
    assert all(trade.status == "COMPLETE" for trade in result.trades)
    for proposal, trade in zip(proposals, result.trades, strict=True):
        # Trade rows are chronological then event ID, not caller positional order.
        shared = simulate_pair_trade(proposal.request, config)
        assert trade.net_pnl == pytest.approx(0.25 * shared.net_return)  # type: ignore[operator]
        assert trade.units_a == pytest.approx(-0.25 / 3.0 / 210.0)
        assert trade.units_b == pytest.approx(0.5 / 3.0 / 100.0)


def test_input_order_does_not_change_simultaneous_allocation_or_bytes() -> None:
    proposals, policy, config = fixture_portfolio()
    assert simulate_portfolio(proposals, policy, config) == simulate_portfolio(
        tuple(reversed(proposals)), policy, config
    )


def test_entry_cap_reserves_costs_and_clips_batch_equally() -> None:
    proposals, policy, config = fixture_portfolio()
    policy = PortfolioPolicy.model_validate({**policy.model_dump(), "target_entry_fraction": 1.0})
    result = simulate_portfolio(proposals, policy, config)
    allocation = 1.0 / (1.0 + 0.0005) / 2.0
    assert [t.allocation for t in result.trades] == pytest.approx([allocation, allocation])
    mark = result.marks[2]
    assert mark.gross_fraction == pytest.approx(1.0)
    assert mark.nav == pytest.approx(1.0 - 2 * allocation * 0.0005)
    assert mark.entry_cap_breached_by_drift is False


def test_custom_initial_nav_scales_units_pnl_and_preserves_return() -> None:
    proposals, policy, config = fixture_portfolio()
    scaled = PortfolioPolicy.model_validate({**policy.model_dump(), "initial_nav": 1000.0})
    base = simulate_portfolio(proposals, policy, config)
    result = simulate_portfolio(proposals, scaled, config)
    assert result.final_nav == pytest.approx(1000.0 * base.final_nav)  # type: ignore[operator]
    assert result.total_return == pytest.approx(base.total_return)
    assert result.known_turnover == pytest.approx(1000 * base.known_turnover)


def test_close_returns_compound_nav_and_event_average_is_not_portfolio_return() -> None:
    proposals, policy, config = fixture_portfolio()
    result = simulate_portfolio(proposals, policy, config)
    closes = [mark for mark in result.marks if mark.phase == "CLOSE"]
    compound = 1.0
    for mark in closes:
        assert mark.daily_return is not None
        compound *= 1.0 + mark.daily_return
    assert compound == pytest.approx(result.final_nav)
    assert result.total_return != pytest.approx(
        simulate_pair_trade(proposals[0].request, config).net_return
    )
    assert "sharpe" not in result.model_dump()


def test_unknown_future_trade_is_allocated_before_failure_without_survivor_selection() -> None:
    proposals, policy, config = fixture_portfolio()
    bad = update_bars(proposals[0], 1, close_a=None)
    result = simulate_portfolio((bad, proposals[1]), policy, config)
    rows = {row.event_id: row for row in result.trades}
    assert rows[bad.request.event_id].allocation == 0.25
    assert rows[bad.request.event_id].status == "UNPRICED"
    assert rows[proposals[1].request.event_id].allocation == 0.25
    assert rows[proposals[1].request.event_id].status == "COMPLETE"
    assert result.marks[2].nav == pytest.approx(0.99975)
    assert result.marks[3].nav is None
    assert result.final_nav is None
    assert result.total_return is None
    assert result.maximum_drawdown is None
    assert result.unknown_nav_since == bad.request.sessions[1].close_at
    assert all(mark.nav is None for mark in result.marks[3:])
    assert all(mark.daily_return is None for mark in result.marks[3:])


def test_missing_exit_open_never_delays_fill_and_keeps_unresolved_position() -> None:
    proposals, policy, config = fixture_portfolio()
    bad = update_bars(proposals[0], 2, open_a=None)
    result = simulate_portfolio((bad,), policy, config)
    assert result.marks[3].nav is not None
    assert result.marks[4].nav is None
    assert result.unknown_nav_since == bad.request.sessions[2].open_at
    assert result.trades[0].status == "UNPRICED"
    assert result.trades[0].exit_at is None
    assert result.marks[-1].open_positions == 1
    assert result.marks[-1].unresolved_positions == 1
    assert result.known_turnover == 0.25


def test_missing_intermediate_held_open_invalidates_nav_even_when_pair_result_complete() -> None:
    proposals, policy, config = fixture_portfolio()
    event = update_bars(longer(proposals[0]), 2, open_a=None)
    assert simulate_pair_trade(event.request, config).status == "COMPLETE"
    result = simulate_portfolio((event,), policy, config)
    assert result.unknown_nav_since == event.request.sessions[2].open_at
    assert result.trades[0].status == "UNPRICED"
    assert result.trades[0].gross_pnl is None
    assert result.final_nav is None


def test_truncated_held_path_becomes_unknown_at_exact_next_xnys_open() -> None:
    proposals, policy, config = fixture_portfolio()
    event = longer(proposals[0])
    event = update_request(
        event, sessions=event.request.sessions[:2], prices=event.request.prices[:2]
    )
    result = simulate_portfolio((event,), policy, config)
    assert result.marks[-2].session_date == date(2023, 1, 5)
    assert result.unknown_nav_since == result.marks[-2].at
    assert result.marks[3].nav is not None
    assert result.final_nav is None
    assert result.trades[0].allocation == 0.25


def test_unknown_nav_blocks_later_entries_without_retroactively_removing_earlier_trade() -> None:
    proposals, policy, config = fixture_portfolio()
    bad = update_bars(proposals[0], 1, close_a=None)
    later = shift(proposals[1], day=date(2023, 1, 4), event_id="later-entry")
    result = simulate_portfolio((bad, later), policy, config)
    rows = {row.event_id: row for row in result.trades}
    assert rows[bad.request.event_id].allocation == 0.25
    assert rows["later-entry"].allocation == 0.0
    assert rows["later-entry"].reason == "PORTFOLIO_NAV_UNKNOWN"


def test_pair_slot_conflict_uses_lexical_event_id_not_input_order() -> None:
    proposals, policy, config = fixture_portfolio()
    a = update_request(proposals[0], event_id="a-first")
    b = update_request(proposals[0], event_id="b-second")
    result = simulate_portfolio((b, a), policy, config)
    assert result.trades[0].event_id == "a-first"
    assert result.trades[0].status == "COMPLETE"
    assert result.trades[1].reason == "PAIR_ALREADY_OPEN"
    assert result.trades[1].allocation == 0.0


def test_failed_entry_does_not_reserve_pair_slot_or_consume_capacity() -> None:
    proposals, policy, config = fixture_portfolio()
    a = update_bars(update_request(proposals[0], event_id="a-first"), 1, open_a=None)
    b = update_request(proposals[0], event_id="b-second")
    result = simulate_portfolio((a, b), policy, config)
    assert result.trades[0].reason == "MISSING_ENTRY_OPEN"
    assert result.trades[0].allocation == 0.0
    assert result.trades[1].status == "COMPLETE"
    assert result.trades[1].allocation == 0.25
    assert result.final_nav is not None


def test_existing_pair_rejects_new_signal_at_later_open() -> None:
    proposals, policy, config = fixture_portfolio()
    first = longer(proposals[0])
    bars = first.request.prices[1:]
    sessions = first.request.sessions[1:]
    second = update_request(
        first,
        event_id="same-pair-later",
        signal_at=sessions[0].close_at,
        sessions=sessions,
        prices=bars,
    )
    result = simulate_portfolio((first, second), policy, config)
    rows = {row.event_id: row for row in result.trades}
    assert rows[second.request.event_id].reason == "PAIR_ALREADY_OPEN"
    assert rows[first.request.event_id].status == "COMPLETE"


def test_exits_release_pair_and_capital_before_same_open_new_entry() -> None:
    proposals, policy, config = fixture_portfolio()
    first = proposals[0]
    base = first.request
    assert base.prices[1].close_a is not None
    second_sessions = tuple(
        MarketSession(session_date=d, open_at=o, close_at=c)
        for d, o, c in canonical_sessions(date(2023, 1, 4), date(2023, 1, 6))
    )
    snapshot = RelationshipSnapshot.model_validate(
        {
            **base.snapshot.model_dump(),
            "snapshot_id": "next-relationship-v1",
            "alpha": log(base.prices[1].close_a) - 2 * log(100.0) - 0.24,
        }
    )
    close_a = exp(snapshot.alpha + 2 * log(110.0) + 0.04)
    first = update_bars(first, 2, close_a=close_a)
    second = update_request(
        first,
        event_id="next-same-pair",
        signal_at=second_sessions[0].close_at,
        snapshot=snapshot,
        sessions=second_sessions,
        prices=(
            first.request.prices[1],
            first.request.prices[2],
            PairPrices(
                session_date=date(2023, 1, 6),
                open_a=170.1,
                open_b=121.0,
                close_a=170.1,
                close_b=121.0,
            ),
        ),
    )
    result = simulate_portfolio((first, second), policy, config)
    rows = {row.event_id: row for row in result.trades}
    first_net = simulate_pair_trade(first.request, config).net_return
    assert first_net is not None
    second_net = simulate_pair_trade(second.request, config).net_return
    assert second_net is not None
    after_first = 1.0 + 0.25 * first_net
    assert rows[second.request.event_id].allocation == pytest.approx(0.25 * after_first)
    assert result.final_nav == pytest.approx(after_first * (1.0 + 0.25 * second_net))
    assert rows[first.request.event_id].exit_at == rows[second.request.event_id].entry_at


def test_borrow_accrues_once_per_actual_open_interval_without_entry_double_charge() -> None:
    proposals, policy, config = fixture_portfolio()
    event = longer(proposals[0])
    result = simulate_portfolio((event,), policy, config)
    charges = [m.borrow_cost_charged for m in result.marks if m.phase == "OPEN"]
    one_interval = 0.25 / 3 * 0.03 / 252
    assert charges == pytest.approx([0.0, 0.0, one_interval, one_interval])
    assert result.known_borrow_cost == pytest.approx(2 * one_interval)
    assert result.trades[0].borrow_cost == pytest.approx(2 * one_interval)


def test_passive_price_drift_breach_is_disclosed_without_daily_reweighting() -> None:
    proposals, policy, config = fixture_portfolio()
    policy = PortfolioPolicy.model_validate({**policy.model_dump(), "target_entry_fraction": 1.0})
    event = update_bars(proposals[0], 1, close_a=420.0, close_b=200.0)
    result = simulate_portfolio((event,), policy, config)
    entry, close = result.marks[2:4]
    assert entry.gross_fraction == pytest.approx(1.0)
    assert close.entry_cap_breached_by_drift is True
    assert close.gross_exposure == pytest.approx(2 * entry.gross_exposure)  # type: ignore[operator]
    assert close.turnover == 0.0
    assert result.trades[0].units_a == pytest.approx(-result.trades[0].allocation / 3 / 210)


def test_idle_sessions_cash_yield_and_withheld_inventory_remain_explicit() -> None:
    proposals, policy, config = fixture_portfolio()
    withheld = PortfolioProposal.model_validate({**proposals[0].model_dump(), "selected": False})
    later = shift(proposals[1], day=date(2023, 1, 9), event_id="later-selected")
    result = simulate_portfolio((withheld, later), policy, config)
    idle = [m for m in result.marks if m.session_date < date(2023, 1, 10)]
    assert all(m.nav == 1.0 and m.gross_exposure == 0.0 for m in idle)
    assert {m.session_date for m in idle} == {
        date(2023, 1, 3),
        date(2023, 1, 4),
        date(2023, 1, 5),
        date(2023, 1, 6),
        date(2023, 1, 9),
    }
    assert result.trades[0].status == "NOT_SELECTED"
    assert result.trades[0].allocation == 0.0


@pytest.mark.parametrize(
    "change",
    [
        {"gross_entry_cap": 1.01},
        {"gross_entry_cap": 0.0},
        {"target_entry_fraction": 0.0},
        {"idle_cash_yield": 0.01},
        {"mode": "DEVELOPMENT"},
    ],
)
def test_invalid_or_unfrozen_production_portfolio_policy_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PortfolioPolicy.model_validate({"version": "bad-policy", **change})


def test_duplicate_event_id_rejected_before_accounting() -> None:
    proposals, policy, config = fixture_portfolio()
    with pytest.raises(ValueError, match="unique"):
        simulate_portfolio((proposals[0], proposals[0]), policy, config)


def test_conflicting_shared_ticker_quotes_rejected() -> None:
    proposals, policy, config = fixture_portfolio()
    second = update_request(proposals[1], pair_id="AAA__DDD", leg_a="AAA")
    second = update_bars(second, 1, open_a=211.0)
    with pytest.raises(ValueError, match="quotes"):
        simulate_portfolio((proposals[0], second), policy, config)


def test_shared_ticker_and_sector_exposure_sum_abs_leg_values() -> None:
    proposals, policy, config = fixture_portfolio()
    second = update_request(proposals[1], pair_id="AAA__DDD", leg_a="AAA")
    result = simulate_portfolio((proposals[0], second), policy, config)
    mark = result.marks[2]
    assert mark.ticker_gross == pytest.approx({"AAA": 1 / 6, "BBB": 1 / 6, "DDD": 1 / 6})
    assert mark.sector_gross == pytest.approx({"TECHNOLOGY": 0.5})


def test_inconsistent_ticker_sector_rejected() -> None:
    proposals, policy, config = fixture_portfolio()
    second = update_request(proposals[1], pair_id="AAA__DDD", leg_a="AAA")
    second = PortfolioProposal.model_validate({**second.model_dump(), "sector_a": "ENERGY"})
    with pytest.raises(ValueError, match="sector"):
        simulate_portfolio((proposals[0], second), policy, config)


def test_real_price_capture_and_late_decision_rejected() -> None:
    proposals, policy, config = fixture_portfolio()
    captured = update_request(proposals[0], data_kind="DEVELOPMENT_CAPTURE")
    with pytest.raises(ValueError, match="synthetic fixtures only"):
        simulate_portfolio((captured, *proposals[1:]), policy, config)
    with pytest.raises(ValidationError, match="signal cutoff"):
        PortfolioProposal.model_validate(
            {
                **proposals[0].model_dump(),
                "decision_at": proposals[0].decision_at + timedelta(seconds=1),
            }
        )


def test_final_test_dates_and_truncated_position_crossing_2024_remain_locked() -> None:
    proposals, policy, config = fixture_portfolio()
    with pytest.raises(ValidationError, match="locked"):
        shift(proposals[0], day=date(2024, 1, 2), event_id="locked")
    # A development signal whose incomplete position needs a 2024 mark is locked.
    sessions = tuple(
        MarketSession(session_date=d, open_at=o, close_at=c)
        for d, o, c in canonical_sessions(date(2023, 12, 28), date(2023, 12, 29))
    )
    bars = tuple(
        PairPrices.model_validate({**bar.model_dump(), "session_date": session.session_date})
        for bar, session in zip(proposals[0].request.prices[:2], sessions, strict=True)
    )
    event = update_request(
        proposals[0],
        event_id="boundary",
        signal_at=sessions[0].close_at,
        sessions=sessions,
        prices=bars,
    )
    event = update_bars(event, 1, close_a=200.0, close_b=100.0)
    with pytest.raises(ValueError, match="locked"):
        simulate_portfolio((event,), policy, config)


def test_source_change_during_accounting_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    proposals, policy, config = fixture_portfolio()
    identities = iter(("0" * 64, "1" * 64))
    monkeypatch.setattr(
        "structural_break.backtest.portfolio.portfolio_source_sha256", lambda: next(identities)
    )
    with pytest.raises(ValueError, match="source changed"):
        simulate_portfolio(proposals, policy, config)


def test_outputs_disclose_fixture_status_and_do_not_unlock_final_test() -> None:
    proposals, policy, config = fixture_portfolio()
    result = simulate_portfolio(proposals, policy, config)
    assert result.scientific_acceptance is False
    assert result.final_test_unlocked is False
    assert len(result.source_sha256) == 64
    assert len(result.proposal_sha256) == len(proposals)
    assert "ENTRY_GROSS_CAP_ONLY_PASSIVE_FIXED_SHARE_DRIFT_DISCLOSED" in result.limitations


def test_zero_proposals_rejected_and_missing_execution_parameters_rejected() -> None:
    proposals, policy, config = fixture_portfolio()
    with pytest.raises(ValueError, match="nonempty"):
        simulate_portfolio((), policy, config)
    config = type(config).model_validate({**config.model_dump(), "entry_cost_bps": None})
    with pytest.raises(ValueError, match="explicit"):
        simulate_portfolio(proposals, policy, config)


def test_losing_exit_and_drawdown_reconcile_sampled_nav_peak() -> None:
    proposals, policy, config = fixture_portfolio()
    event = update_bars(proposals[0], 2, open_a=231.0, open_b=90.0)
    result = simulate_portfolio((event,), policy, config)
    expected = 1.0 - 0.025 - 0.25 * (0.0005 + 0.0005 * (1.1 / 3 + 2 * 0.9 / 3))
    expected -= 0.25 / 3 * 0.03 / 252
    assert result.final_nav == pytest.approx(expected)
    navs = [m.nav for m in result.marks]
    assert all(nav is not None for nav in navs)
    peak = 1.0
    sampled = []
    for nav in navs:
        assert nav is not None
        peak = max(peak, nav)
        sampled.append(nav / peak - 1)
    assert result.maximum_drawdown == pytest.approx(min(sampled))
    assert result.maximum_drawdown < 0  # type: ignore[operator]


def test_mid_position_lifecycle_termination_keeps_unknown_settlement() -> None:
    proposals, policy, config = fixture_portfolio()
    event = update_request(longer(proposals[0]), lifecycle_termination=date(2023, 1, 5))
    result = simulate_portfolio((event,), policy, config)
    assert result.trades[0].allocation == 0.25
    assert result.trades[0].status == "UNPRICED"
    assert result.trades[0].reason == "LIFECYCLE_TERMINATION"
    assert result.unknown_nav_since == event.request.sessions[2].open_at
    assert result.final_nav is None


def test_nonpositive_nav_rejects_later_entries_without_hiding_short_loss() -> None:
    proposals, policy, config = fixture_portfolio()
    first = update_bars(proposals[0], 2, open_a=4000.0, open_b=1.0)
    later = shift(proposals[1], day=date(2023, 1, 4), event_id="later-after-loss")
    result = simulate_portfolio((first, later), policy, config)
    rows = {row.event_id: row for row in result.trades}
    assert rows[first.request.event_id].status == "COMPLETE"
    assert rows[later.request.event_id].reason == "NONPOSITIVE_PORTFOLIO_NAV"
    assert result.final_nav is not None and result.final_nav < 0
    assert result.total_return is not None and result.total_return < -1


def test_existing_passive_cap_breach_blocks_fresh_capital_without_rebalancing() -> None:
    proposals, policy, config = fixture_portfolio()
    policy = PortfolioPolicy.model_validate({**policy.model_dump(), "target_entry_fraction": 1.0})
    first = update_bars(longer(proposals[0]), 1, close_a=420.0, close_b=200.0)
    first = update_bars(first, 2, open_a=420.0, open_b=200.0)
    later = shift(proposals[1], day=date(2023, 1, 4), event_id="later-no-capacity")
    result = simulate_portfolio((first, later), policy, config)
    rows = {row.event_id: row for row in result.trades}
    assert rows[first.request.event_id].allocation == pytest.approx(1.0 / 1.0005)
    assert rows[later.request.event_id].status == "CAPACITY_REJECTED"
    assert rows[later.request.event_id].reason == "NO_GROSS_CAPACITY"
    mark = next(m for m in result.marks if m.session_date == date(2023, 1, 5) and m.phase == "OPEN")
    assert mark.entry_cap_breached_by_drift is True
    assert mark.turnover == 0.0


def test_withheld_incomplete_boundary_proposal_does_not_force_final_test_timeline() -> None:
    proposals, policy, config = fixture_portfolio()
    sessions = tuple(
        MarketSession(session_date=d, open_at=o, close_at=c)
        for d, o, c in canonical_sessions(date(2023, 12, 28), date(2023, 12, 29))
    )
    bars = tuple(
        PairPrices.model_validate({**bar.model_dump(), "session_date": session.session_date})
        for bar, session in zip(proposals[0].request.prices[:2], sessions, strict=True)
    )
    event = update_request(
        proposals[0],
        signal_at=sessions[0].close_at,
        sessions=sessions,
        prices=bars,
    )
    event = PortfolioProposal.model_validate({**event.model_dump(), "selected": False})
    result = simulate_portfolio((event,), policy, config)
    assert result.trades[0].status == "NOT_SELECTED"
    assert result.final_nav == 1.0
    assert result.marks[-1].session_date == date(2023, 12, 29)

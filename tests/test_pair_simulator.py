"""Hand-derived economics and adversarial execution paths, with blocked sockets."""

import json
from datetime import UTC, date, datetime, timedelta
from math import exp, log
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from structural_break.backtest.cli import main
from structural_break.backtest.contracts import (
    ExecutionConfig,
    MarketSession,
    PairPrices,
    PairTradeRequest,
    PairTradeResult,
    canonical_sessions,
)
from structural_break.backtest.fixtures import synthetic_trade_request
from structural_break.backtest.simulator import (
    canonical_bytes,
    fixture_config,
    sha256,
    simulate_pair_trade,
)


def changed(event: PairTradeRequest, **updates: Any) -> PairTradeRequest:
    payload = event.model_dump(mode="json")
    payload.update(updates)
    return PairTradeRequest.model_validate_json(json.dumps(payload))


def policy(**updates: Any) -> ExecutionConfig:
    payload = fixture_config().model_dump(mode="json")
    payload.update(updates)
    return ExecutionConfig.model_validate_json(json.dumps(payload))


def path(zs: list[float], *, beta: float = 2.0, signal_z: float = 2.4) -> PairTradeRequest:
    fixture = synthetic_trade_request()
    sessions = tuple(
        MarketSession(session_date=day, open_at=opening, close_at=closing)
        for day, opening, closing in canonical_sessions(date(2023, 1, 3), date(2023, 3, 15))[
            : len(zs) + 2
        ]
    )
    snapshot = fixture.snapshot.model_dump(mode="json")
    snapshot.update(alpha=log(200.0) - beta * log(100.0) - signal_z * 0.1, beta=beta)
    rows = [PairPrices(session_date=sessions[0].session_date, close_a=200.0, close_b=100.0)]
    for index, z in enumerate(zs, start=1):
        close_a = exp(snapshot["alpha"] + beta * log(100.0) + 0.1 * z)
        rows.append(
            PairPrices(
                session_date=sessions[index].session_date,
                open_a=210.0,
                open_b=100.0,
                close_a=close_a,
                close_b=100.0,
            )
        )
    rows.append(
        PairPrices(
            session_date=sessions[-1].session_date,
            open_a=189.0 if signal_z > 0 else 231.0,
            open_b=110.0 if signal_z > 0 else 90.0,
        )
    )
    return changed(
        fixture,
        signal_z=signal_z,
        snapshot=snapshot,
        sessions=[session.model_dump(mode="json") for session in sessions],
        prices=[row.model_dump(mode="json") for row in rows],
    )


def edited_bar(event: PairTradeRequest, index: int, **updates: Any) -> PairTradeRequest:
    rows = event.model_dump(mode="json")["prices"]
    rows[index].update(updates)
    return changed(event, prices=rows)


def test_hand_calculated_frozen_units_exit_turnover_and_one_session_borrow() -> None:
    event = synthetic_trade_request()
    result = simulate_pair_trade(event, fixture_config())
    assert result.status == "COMPLETE" and result.reason == "CONVERGENCE"
    assert result.entry is not None and result.exit is not None and result.position is not None
    assert result.position.direction == "SHORT_A_LONG_B"
    assert result.position.weight_a == pytest.approx(-1 / 3)
    assert result.position.weight_b == pytest.approx(2 / 3)
    assert result.position.units_a == pytest.approx(-1 / 630)
    assert result.position.units_b == pytest.approx(1 / 150)
    assert result.entry.price_a == 210.0 and result.exit.price_a == 189.0
    assert result.gross_return == pytest.approx(0.1)
    # Entry turnover=1; exit turnover=189/630+110/150=31/30.
    expected_trading = 0.0005 * (1 + 31 / 30)
    expected_borrow = 0.03 * (1 / 3) / 252
    assert result.trading_cost == pytest.approx(expected_trading)
    assert result.borrow_cost == pytest.approx(expected_borrow)
    assert result.net_return == pytest.approx(0.1 - expected_trading - expected_borrow)
    assert result.holding_sessions == 1
    assert result.entry.at == event.sessions[1].open_at
    assert result.exit.at == event.sessions[2].open_at
    assert result.trigger is not None and result.trigger.at == event.sessions[1].close_at
    assert result.mae == 0.0 and result.mfe == pytest.approx(0.1)
    assert result.request_sha256 == sha256(event)
    assert result.execution_config_sha256 == sha256(fixture_config())
    assert result.snapshot_id == event.snapshot.snapshot_id
    assert "SYNTHETIC_ENGINEERING_ONLY" in result.limitations


def test_negative_signal_reverses_the_two_legs_not_the_hedge_ratio() -> None:
    result = simulate_pair_trade(path([-0.4], signal_z=-2.4), fixture_config())
    assert result.position is not None
    assert result.position.direction == "LONG_A_SHORT_B"
    assert result.position.weight_a == pytest.approx(1 / 3)
    assert result.position.weight_b == pytest.approx(-2 / 3)
    assert result.gross_return == pytest.approx(0.1)
    assert result.borrow_cost == pytest.approx(0.03 * (2 / 3) / 252)


def test_units_are_frozen_even_after_large_intermediate_price_moves() -> None:
    event = path([2.4, 2.4, 0.4])
    event = edited_bar(event, 1, open_a=100.0, close_a=50.0, close_b=50.0)
    event = edited_bar(event, 2, close_a=200.0, close_b=100.0)
    event = edited_bar(event, 4, open_a=100.0, open_b=100.0)
    result = simulate_pair_trade(
        event, policy(entry_cost_bps=0.0, exit_cost_bps=0.0, annual_borrow_rate=0.0)
    )
    assert result.status == "COMPLETE"
    # Each leg exits at exactly its entry price: frozen-unit P&L must be zero,
    # despite the very different intermediate prices and drifting exposures.
    assert result.gross_return == pytest.approx(0.0)
    assert result.net_return == pytest.approx(0.0)
    assert result.marks[0].gross_return == pytest.approx(-1 / 6)
    assert result.marks[1].gross_return == pytest.approx(-1 / 3)
    assert result.mae == pytest.approx(-1 / 3)
    assert result.position is not None and result.position.units_a == pytest.approx(-1 / 300)


@pytest.mark.parametrize("horizon", [10, 20, 30])
def test_timeout_uses_predeclared_signal_horizon_and_next_open(horizon: int) -> None:
    event = path([2.4] * horizon)
    result = simulate_pair_trade(event, fixture_config(horizon_sessions=horizon))
    assert result.reason == "TIMEOUT" and result.status == "COMPLETE"
    assert result.trigger is not None and result.exit is not None
    assert result.trigger.session_date == event.sessions[horizon].session_date
    assert result.exit.session_date == event.sessions[horizon + 1].session_date
    assert result.holding_sessions == horizon
    assert result.borrow_cost == pytest.approx(0.03 / 3 * horizon / 252)


def test_a_jump_across_equilibrium_is_neither_convergence_nor_same_side_stop() -> None:
    result = simulate_pair_trade(path([-3.5] * 20), fixture_config())
    assert result.reason == "TIMEOUT"
    assert len(result.marks) == 20


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_adverse_stop_is_same_side_and_executes_after_close(sign: float) -> None:
    event = path([sign * 3.5], signal_z=sign * 2.4)
    result = simulate_pair_trade(event, fixture_config())
    assert result.reason == "ADVERSE_STOP" and result.status == "COMPLETE"
    assert result.trigger is not None and result.trigger.at == event.sessions[1].close_at
    assert result.exit is not None and result.exit.at == event.sessions[2].open_at


def test_final_horizon_convergence_precedes_the_timeout() -> None:
    result = simulate_pair_trade(path([2.4] * 19 + [0.4]), fixture_config())
    assert result.reason == "CONVERGENCE" and result.holding_sessions == 20


def test_convergence_and_stop_include_exact_computed_boundaries() -> None:
    event = synthetic_trade_request()
    snapshot = event.snapshot.model_dump(mode="json")
    snapshot.update(alpha=0.0, beta=1.0, spread_mean=0.0, spread_std=log(4.0))
    rows = event.model_dump(mode="json")["prices"]
    rows[0].update(close_a=16.0, close_b=1.0)
    rows[1].update(open_a=16.0, open_b=1.0, close_a=2.0, close_b=1.0)
    event = changed(event, signal_z=2.0, snapshot=snapshot, prices=rows)
    assert simulate_pair_trade(event, fixture_config()).reason == "CONVERGENCE"
    event = edited_bar(event, 1, close_a=64.0)
    assert simulate_pair_trade(event, fixture_config()).reason == "ADVERSE_STOP"


def test_exit_gap_can_turn_a_converged_label_path_into_an_economic_loss() -> None:
    event = edited_bar(synthetic_trade_request(), 2, open_a=300.0, open_b=90.0)
    result = simulate_pair_trade(event, fixture_config())
    assert result.reason == "CONVERGENCE"
    assert result.gross_return == pytest.approx((-1 / 3) * (300 / 210 - 1) + (2 / 3) * -0.1)
    assert result.net_return is not None and result.net_return < 0
    assert result.mae == pytest.approx(result.gross_return)


def test_open_gap_is_recorded_but_not_used_as_a_close_based_exit_trigger() -> None:
    event = path([2.4, 0.4])
    converged_a = exp(event.snapshot.alpha + event.snapshot.beta * log(100.0))
    event = edited_bar(event, 1, open_a=converged_a)
    result = simulate_pair_trade(event, fixture_config())
    assert result.entry_gap_z == pytest.approx(-2.4)
    assert result.holding_sessions == 2
    assert (
        result.trigger is not None and result.trigger.session_date == event.sessions[2].session_date
    )


@pytest.mark.parametrize(
    ("index", "field", "status", "reason"),
    [
        (0, "close_a", "NOT_ENTERED", "MISSING_SIGNAL_CLOSE"),
        (0, "close_b", "NOT_ENTERED", "MISSING_SIGNAL_CLOSE"),
        (1, "open_a", "NOT_ENTERED", "MISSING_ENTRY_OPEN"),
        (1, "open_b", "NOT_ENTERED", "MISSING_ENTRY_OPEN"),
        (1, "close_a", "UNPRICED", "MISSING_MONITORING_CLOSE"),
        (1, "close_b", "UNPRICED", "MISSING_MONITORING_CLOSE"),
        (2, "open_a", "UNPRICED", "MISSING_EXIT_OPEN"),
        (2, "open_b", "UNPRICED", "MISSING_EXIT_OPEN"),
    ],
)
def test_missing_required_observation_keeps_the_denominator_without_fake_returns(
    index: int, field: str, status: str, reason: str
) -> None:
    event = edited_bar(synthetic_trade_request(), index, **{field: None})
    result = simulate_pair_trade(event, fixture_config())
    assert result.status == status and result.reason == reason
    assert result.gross_return is None and result.net_return is None
    assert result.borrow_cost is None and result.trading_cost is None
    assert result.exit is None
    assert (result.entry is not None) == (status == "UNPRICED")


def test_missing_next_open_does_not_select_a_later_convenient_fill() -> None:
    event = path([0.4, 2.4])
    event = edited_bar(event, 2, open_a=None)
    result = simulate_pair_trade(event, fixture_config())
    assert result.reason == "MISSING_EXIT_OPEN"
    assert (
        result.trigger is not None and result.trigger.session_date == event.sessions[1].session_date
    )
    assert result.exit is None and result.gross_return is None


def test_absent_price_row_has_same_explicit_failure_as_null_observations() -> None:
    event = synthetic_trade_request()
    rows = event.model_dump(mode="json")["prices"]
    result = simulate_pair_trade(changed(event, prices=[rows[0], rows[2]]), fixture_config())
    assert result.reason == "MISSING_ENTRY_OPEN" and result.status == "NOT_ENTERED"


def test_truncated_path_preserves_opened_position_and_partial_marks() -> None:
    event = path([2.4, 2.4])
    event = changed(
        event,
        sessions=event.model_dump(mode="json")["sessions"][:-1],
        prices=event.model_dump(mode="json")["prices"][:-1],
    )
    result = simulate_pair_trade(event, fixture_config())
    assert result.status == "UNPRICED" and result.reason == "INCOMPLETE_SESSION_PATH"
    assert len(result.marks) == 2 and result.partial_mae is not None
    assert result.mae is None and result.mfe is None
    assert result.net_return is None and result.holding_sessions is None


def test_truncated_trigger_path_is_unpriced_not_a_close_fill() -> None:
    event = synthetic_trade_request()
    event = changed(
        event,
        sessions=event.model_dump(mode="json")["sessions"][:-1],
        prices=event.model_dump(mode="json")["prices"][:-1],
    )
    result = simulate_pair_trade(event, fixture_config())
    assert result.reason == "INCOMPLETE_SESSION_PATH" and result.trigger is not None
    assert result.exit is None


def test_lifecycle_termination_never_fabricates_a_delisting_settlement() -> None:
    event = synthetic_trade_request()
    early = changed(event, lifecycle_termination=str(event.sessions[1].session_date))
    assert simulate_pair_trade(early, fixture_config()).status == "NOT_ENTERED"
    overnight = changed(event, lifecycle_termination=str(event.sessions[2].session_date))
    result = simulate_pair_trade(overnight, fixture_config())
    assert result.status == "UNPRICED" and result.reason == "LIFECYCLE_TERMINATION"
    assert result.trigger is not None and result.gross_return is None


@pytest.mark.parametrize("beta", [-2.0, 0.0, 10.01])
def test_positive_beta_economic_gate_is_explicit(beta: float) -> None:
    result = simulate_pair_trade(path([0.4], beta=beta), fixture_config())
    assert result.status == "NOT_ENTERED" and result.reason == "INVALID_ECONOMIC_BETA"


def test_inside_entry_band_does_not_create_a_trade() -> None:
    result = simulate_pair_trade(path([0.4], signal_z=1.9), fixture_config())
    assert result.reason == "SIGNAL_NOT_DIVERGED"


def test_development_draft_policy_fails_closed_without_applying_fixture_defaults() -> None:
    config = policy(
        mode="DEVELOPMENT",
        positive_beta_limit=None,
        entry_cost_bps=None,
        exit_cost_bps=None,
        annual_borrow_rate=None,
    )
    result = simulate_pair_trade(synthetic_trade_request(), config)
    assert result.status == "NOT_ENTERED" and result.reason == "POLICY_NOT_FROZEN"
    assert result.gross_return is None


def test_fixture_mode_cannot_be_reused_on_captured_market_data() -> None:
    event = changed(synthetic_trade_request(), data_kind="DEVELOPMENT_CAPTURE")
    with pytest.raises(ValueError, match="Fixture economic assumptions"):
        simulate_pair_trade(event, fixture_config())


def test_fixture_mode_cannot_claim_a_frozen_production_policy() -> None:
    with pytest.raises(ValidationError, match="cannot freeze"):
        policy(status="FROZEN")


def test_missing_scenario_cost_parameter_is_an_explicit_non_entry() -> None:
    result = simulate_pair_trade(synthetic_trade_request(), policy(annual_borrow_rate=None))
    assert result.reason == "POLICY_PARAMETERS_MISSING"


@pytest.mark.parametrize("horizon", [1, 15, 31])
def test_only_predeclared_horizons_are_accepted(horizon: int) -> None:
    with pytest.raises(ValidationError):
        fixture_config(horizon_sessions=horizon)


@pytest.mark.parametrize("field", ["signal_at", "available_at", "open_at"])
def test_naive_timestamps_are_rejected(field: str) -> None:
    event = synthetic_trade_request()
    payload = event.model_dump(mode="json")
    if field == "signal_at":
        payload[field] = "2023-01-03T21:00:00"
    elif field == "available_at":
        payload["snapshot"][field] = "2023-01-03T14:30:00"
    else:
        payload["sessions"][0][field] = "2023-01-03T14:30:00"
    with pytest.raises(ValidationError, match="timezone-aware"):
        PairTradeRequest.model_validate_json(json.dumps(payload))


def test_future_snapshot_and_future_formation_are_rejected() -> None:
    event = synthetic_trade_request()
    snapshot = event.snapshot.model_dump(mode="json")
    snapshot["available_at"] = (event.signal_at + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="available by"):
        changed(event, snapshot=snapshot)
    snapshot["available_at"] = event.signal_at.isoformat()
    snapshot["formation_end"] = "2023-01-04"
    with pytest.raises(ValidationError, match="available by"):
        changed(event, snapshot=snapshot)


def test_signal_cutoff_must_be_actual_close_and_z_must_reconcile() -> None:
    event = synthetic_trade_request()
    with pytest.raises(ValidationError, match="signal cutoff|Signal cutoff"):
        changed(event, signal_at=(event.signal_at + timedelta(minutes=1)).isoformat())
    with pytest.raises(ValidationError, match="reconcile"):
        changed(event, signal_z=4.0)


def test_timezone_representation_can_differ_when_the_instant_is_identical() -> None:
    event = synthetic_trade_request()
    event = changed(event, signal_at="2023-01-03T16:00:00-05:00")
    assert simulate_pair_trade(event, fixture_config()).status == "COMPLETE"


def test_xnys_early_close_holidays_and_daylight_saving_are_canonical() -> None:
    early = canonical_sessions(date(2023, 11, 22), date(2023, 11, 27))
    assert [row[0] for row in early] == [date(2023, 11, 22), date(2023, 11, 24), date(2023, 11, 27)]
    assert early[1][2] == datetime(2023, 11, 24, 18, 0, tzinfo=UTC)
    dst = canonical_sessions(date(2023, 3, 10), date(2023, 3, 13))
    assert dst[0][1].hour == 14 and dst[1][1].hour == 13


def test_skipping_a_declared_trading_session_is_rejected() -> None:
    event = path([2.4, 0.4])
    payload = event.model_dump(mode="json")
    with pytest.raises(ValidationError, match="every XNYS session"):
        changed(
            event,
            sessions=[payload["sessions"][0], *payload["sessions"][2:]],
            prices=[payload["prices"][0], *payload["prices"][2:]],
        )


def test_wrong_calendar_open_and_duplicate_prices_are_rejected() -> None:
    event = synthetic_trade_request()
    payload = event.model_dump(mode="json")
    payload["sessions"][1]["open_at"] = "2023-01-04T15:30:00Z"
    with pytest.raises(ValidationError, match="XNYS"):
        changed(event, sessions=payload["sessions"])
    with pytest.raises(ValidationError, match="unique and ordered"):
        changed(event, prices=[*payload["prices"], payload["prices"][-1]])


@pytest.mark.parametrize("year", [2003, 2024, 2025, 2026])
def test_locked_or_outside_development_price_dates_are_rejected(year: int) -> None:
    with pytest.raises(ValidationError, match="development-only"):
        PairPrices(session_date=date(year, 1, 3), close_a=100.0, close_b=100.0)


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan"), 1e-20])
def test_nonpositive_nonfinite_or_numerically_unusable_prices_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        PairPrices(session_date=date(2023, 1, 3), open_a=value)


def test_unknown_fields_and_nonfinite_snapshot_numbers_are_rejected() -> None:
    event = synthetic_trade_request()
    with pytest.raises(ValidationError, match="Extra inputs"):
        changed(event, label_success=True)
    payload = event.snapshot.model_dump(mode="json")
    payload["alpha"] = float("nan")
    with pytest.raises(ValidationError):
        changed(event, snapshot=payload)


def test_inputs_and_results_are_deeply_immutable_and_json_roundtrip() -> None:
    event = synthetic_trade_request()
    result = simulate_pair_trade(event, fixture_config())
    assert PairTradeRequest.model_validate_json(canonical_bytes(event)) == event
    assert PairTradeResult.model_validate_json(canonical_bytes(result)) == result
    with pytest.raises(ValidationError):
        event.snapshot.beta = 3.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.marks[0].z = 0.0  # type: ignore[misc]


def test_unpriced_result_cannot_be_serialized_with_a_fabricated_zero_return() -> None:
    result = simulate_pair_trade(
        edited_bar(synthetic_trade_request(), 2, open_a=None), fixture_config()
    )
    payload = result.model_dump(mode="json")
    payload["net_return"] = 0.0
    with pytest.raises(ValidationError, match="fabricate terminal returns"):
        PairTradeResult.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "net_return", 0.5),
        (None, "gross_return", 0.5),
        (None, "holding_sessions", 2),
        (None, "mae", -1.0),
        ("position", "units_a", -0.01),
        ("position", "weight_b", 0.5),
        ("entry", "at", "2023-01-04T21:00:00Z"),
        ("exit", "at", "2023-01-05T21:00:00Z"),
        ("trigger", "at", "2023-01-04T14:30:00Z"),
    ],
)
def test_result_rows_reject_tampered_economics_units_or_execution_times(
    section: str | None, field: str, value: Any
) -> None:
    result = simulate_pair_trade(synthetic_trade_request(), fixture_config())
    payload = result.model_dump(mode="json")
    target = payload if section is None else payload[section]
    target[field] = value
    with pytest.raises(ValidationError):
        PairTradeResult.model_validate_json(json.dumps(payload))


def test_snapshot_cannot_be_available_before_its_formation_close() -> None:
    event = synthetic_trade_request()
    snapshot = event.snapshot.model_dump(mode="json")
    snapshot["available_at"] = "2022-12-30T14:30:00Z"
    with pytest.raises(ValidationError, match="Formation endpoint"):
        changed(event, snapshot=snapshot)


def test_same_close_monthly_fit_is_not_yet_effective_for_that_signal() -> None:
    event = synthetic_trade_request()
    snapshot = event.snapshot.model_dump(mode="json")
    snapshot.update(formation_end="2023-01-03", available_at=event.signal_at.isoformat())
    with pytest.raises(ValidationError, match="next XNYS open"):
        changed(event, snapshot=snapshot)


def test_holiday_snapshot_cannot_become_effective_before_the_exact_next_open() -> None:
    event = synthetic_trade_request()  # Dec30 formation; Jan2 closed; Jan3 next open.
    snapshot = event.snapshot.model_dump(mode="json")
    snapshot["available_at"] = "2023-01-02T14:30:00Z"
    with pytest.raises(ValidationError, match="next XNYS open"):
        changed(event, snapshot=snapshot)
    snapshot["available_at"] = "2023-01-03T14:29:59Z"
    with pytest.raises(ValidationError, match="next XNYS open"):
        changed(event, snapshot=snapshot)
    snapshot["available_at"] = "2023-01-03T14:30:00Z"
    assert changed(event, snapshot=snapshot).snapshot.available_at == event.sessions[0].open_at


def test_snapshot_effectiveness_uses_daylight_saving_adjusted_next_open() -> None:
    event = synthetic_trade_request()
    schedule = canonical_sessions(date(2023, 3, 13), date(2023, 3, 15))
    payload = event.model_dump(mode="json")
    payload["sessions"] = [
        MarketSession(session_date=day, open_at=opening, close_at=closing).model_dump(mode="json")
        for day, opening, closing in schedule
    ]
    payload["signal_at"] = schedule[0][2].isoformat()
    payload["snapshot"].update(formation_end="2023-03-10", available_at="2023-03-13T13:29:59Z")
    for row, session in zip(payload["prices"], payload["sessions"], strict=True):
        row["session_date"] = session["session_date"]
    with pytest.raises(ValidationError, match="next XNYS open"):
        PairTradeRequest.model_validate_json(json.dumps(payload))
    payload["snapshot"]["available_at"] = "2023-03-13T13:30:00Z"
    request = PairTradeRequest.model_validate_json(json.dumps(payload))
    assert simulate_pair_trade(request, fixture_config()).status == "COMPLETE"


def test_repository_production_policy_is_the_frozen_decision_35_headline() -> None:
    config_path = Path(__file__).parents[1] / "configs/phase6_execution.json"
    config = ExecutionConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    assert (config.schema_version, config.mode, config.status) == (
        "pair-execution-policy-v2",
        "DEVELOPMENT",
        "FROZEN",
    )
    assert (config.entry_cost_bps, config.exit_cost_bps, config.annual_borrow_rate) == (
        5.0,
        5.0,
        0.01,
    )
    assert (config.positive_beta_limit, config.min_leg_adv20_usd) == (3.0, 5_000_000.0)
    assert config.horizon_sessions == 20
    # A request without signal-time leg liquidity is explicitly not entered.
    result = simulate_pair_trade(synthetic_trade_request(), config)
    assert (result.status, result.reason) == ("NOT_ENTERED", "MISSING_LEG_LIQUIDITY")


def test_liquidity_floor_requires_schema_v2_and_complete_leg_liquidity() -> None:
    with pytest.raises(ValidationError, match="schema v2"):
        policy(min_leg_adv20_usd=1e6)
    v2 = {"schema_version": "pair-execution-policy-v2"}
    missing = simulate_pair_trade(synthetic_trade_request(), policy(**v2))
    assert missing.reason == "POLICY_PARAMETERS_MISSING"
    floor = policy(**v2, min_leg_adv20_usd=5e6)
    unknown = changed(synthetic_trade_request(), signal_adv20_usd_a=9e6)
    assert simulate_pair_trade(unknown, floor).reason == "MISSING_LEG_LIQUIDITY"
    thin = changed(unknown, signal_adv20_usd_b=4e6)
    assert simulate_pair_trade(thin, floor).reason == "ILLIQUID_LEG"
    liquid = changed(unknown, signal_adv20_usd_b=6e6)
    entered = simulate_pair_trade(liquid, floor)
    assert entered.status == "COMPLETE"
    disabled = simulate_pair_trade(thin, policy(**v2, min_leg_adv20_usd=0.0))
    assert disabled.status == "COMPLETE"
    assert entered.net_return == disabled.net_return


def test_cost_scenarios_change_only_economics_not_prices_units_or_exit() -> None:
    event = synthetic_trade_request()
    baseline = simulate_pair_trade(event, fixture_config())
    stressed = simulate_pair_trade(
        event, policy(entry_cost_bps=20.0, exit_cost_bps=20.0, annual_borrow_rate=0.1)
    )
    assert baseline.position == stressed.position and baseline.exit == stressed.exit
    assert baseline.gross_return == stressed.gross_return
    assert stressed.net_return is not None and baseline.net_return is not None
    assert stressed.net_return < baseline.net_return
    assert baseline.execution_config_sha256 != stressed.execution_config_sha256


def test_cli_fixture_persists_identical_immutable_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["structural-break-backtest", "--fixture", "--output-dir", str(tmp_path)]
    )
    main()
    first = json.loads(capsys.readouterr().out)
    main()
    second = json.loads(capsys.readouterr().out)
    assert first == second
    result_path = Path(first["result"])
    assert result_path.exists()
    assert (result_path.parent / "input.json").exists()
    assert (result_path.parent / "config.json").exists()
    stored = PairTradeResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    assert stored.gross_return == pytest.approx(0.1)
    assert first["data_kind"] == "SYNTHETIC_FIXTURE"


def test_cli_supplied_draft_configuration_produces_an_explicit_non_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    request_path, config_path = tmp_path / "input.json", tmp_path / "policy.json"
    request_path.write_bytes(canonical_bytes(synthetic_trade_request()))
    config_path.write_bytes(canonical_bytes(policy(mode="DEVELOPMENT")))
    monkeypatch.setattr(
        "sys.argv",
        [
            "structural-break-backtest",
            "--input",
            str(request_path),
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["reason"] == "POLICY_NOT_FROZEN"

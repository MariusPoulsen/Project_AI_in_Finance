"""Capability isolation, availability denominators and adversarial typed joins."""

import json
from collections import Counter
from math import exp, log
from typing import Any

import pytest
from pydantic import ValidationError

import structural_break.backtest.ladder as ladder
from structural_break.backtest.contracts import ExecutionConfig, PairTradeRequest, PairTradeResult
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    LadderEvent,
    LadderPolicy,
    LadderRow,
    Rung,
    RungSelection,
)
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.simulator import canonical_bytes, sha256, simulate_pair_trade


def changed_event(event: LadderEvent, payload: dict[str, Any]) -> LadderEvent:
    value = event.model_dump(mode="json")
    for key, updates in payload.items():
        value[key].update(updates)
    return LadderEvent.model_validate_json(json.dumps(value))


def changed_policy(policy: LadderPolicy, **updates: Any) -> LadderPolicy:
    value = policy.model_dump(mode="json")
    value.update(updates)
    return LadderPolicy.model_validate_json(json.dumps(value))


def selection(row: LadderRow, rung: Rung) -> RungSelection:
    return next(value for value in row.selections if value.rung == rung)


def with_z(event: LadderEvent, *, previous_z: float, signal_z: float) -> LadderEvent:
    value = event.model_dump(mode="json")
    snapshot = event.request.snapshot
    previous = value["state"]["previous"]
    previous["z"] = previous_z
    previous["close_a"] = exp(
        snapshot.alpha
        + snapshot.beta * log(previous["close_b"])
        + snapshot.spread_mean
        + snapshot.spread_std * previous_z
    )
    value["request"]["signal_z"] = signal_z
    current = value["request"]["prices"][0]
    current["close_a"] = exp(
        snapshot.alpha
        + snapshot.beta * log(current["close_b"])
        + snapshot.spread_mean
        + snapshot.spread_std * signal_z
    )
    return LadderEvent.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("candidate", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "SELECTED")),
        ("a-only", ("SELECTED", "SELECTED", "SELECTED", "WITHHELD", "WITHHELD")),
        ("b-only", ("SELECTED", "SELECTED", "WITHHELD", "SELECTED", "SELECTED")),
        ("watch", ("SELECTED", "WITHHELD", "WITHHELD", "WITHHELD", "WITHHELD")),
        ("missing-a", ("SELECTED", "SELECTED", "UNAVAILABLE", "SELECTED", "SELECTED")),
        ("missing-b", ("SELECTED", "SELECTED", "SELECTED", "UNAVAILABLE", "UNAVAILABLE")),
        ("unscheduled", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "UNAVAILABLE")),
        ("review", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "WITHHELD")),
        ("abstain", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "WITHHELD")),
        ("unpriced", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "SELECTED")),
        ("not-fresh", ("WITHHELD", "WITHHELD", "WITHHELD", "WITHHELD", "WITHHELD")),
        (
            "no-previous",
            ("UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"),
        ),
        ("no-trade", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "WITHHELD")),
        ("missing-controller", ("SELECTED", "SELECTED", "SELECTED", "SELECTED", "UNAVAILABLE")),
    ],
)
def test_fourteen_case_inventory_preserves_every_capability_disposition(
    name: str, expected: tuple[str, ...]
) -> None:
    events, policy, config, _ = fixture_ladder()
    rows = ladder.evaluate_ladder(events, policy, config)
    assert len(rows) == len(events) == 14
    row = next(value for value in rows if value.event_id == f"synthetic-ladder-{name}-v1")
    assert tuple(value.rung for value in row.selections) == RUNG_ORDER
    assert tuple(value.disposition for value in row.selections) == expected
    event = next(value for value in events if value.state.event_id == row.event_id)
    assert row.state_sha256 == sha256(event.state)
    assert row.request_sha256 == sha256(event.request)


def test_one_shared_execution_per_raw_fresh_event_including_rejected_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, policy, config, _ = fixture_ladder()
    calls: list[str] = []

    def recording(request: PairTradeRequest, execution: ExecutionConfig) -> PairTradeResult:
        calls.append(request.event_id)
        assert execution is config
        return simulate_pair_trade(request, execution)

    monkeypatch.setattr(ladder, "simulate_pair_trade", recording)
    rows = ladder.evaluate_ladder(events, policy, config)
    expected = {row.event_id for row in rows if row.raw_fresh is True}
    assert Counter(calls) == Counter(dict.fromkeys(expected, 1))
    assert len(calls) == 12
    assert "synthetic-ladder-watch-v1" in calls
    assert "synthetic-ladder-no-trade-v1" in calls
    for row in rows:
        if row.raw_fresh is True:
            event = next(value for value in events if value.state.event_id == row.event_id)
            assert row.execution == simulate_pair_trade(event.request, config)
        else:
            assert row.execution is None


def test_pure_selection_replay_never_calls_simulator(monkeypatch: pytest.MonkeyPatch) -> None:
    events, policy, _, _ = fixture_ladder()

    def forbidden(*args: Any, **kwargs: Any) -> PairTradeResult:
        raise AssertionError("Selection cannot read execution outcomes")

    monkeypatch.setattr(ladder, "simulate_pair_trade", forbidden)
    fresh, selections = ladder.select_ladder_event(events[0], policy)
    assert fresh is True and all(value.selected for value in selections)


@pytest.mark.parametrize("unavailable", ["entry", "exit", "monitoring"])
def test_failed_forward_execution_cannot_rewrite_selection(unavailable: str) -> None:
    events, policy, config, _ = fixture_ladder()
    value = events[0].model_dump(mode="json")
    index, column = {"entry": (1, "open_a"), "exit": (2, "open_a"), "monitoring": (1, "close_b")}[
        unavailable
    ]
    value["request"]["prices"][index][column] = None
    event = LadderEvent.model_validate_json(json.dumps(value))
    original = ladder.evaluate_ladder((events[0],), policy, config)[0]
    failed = ladder.evaluate_ladder((event,), policy, config)[0]
    assert failed.selections == original.selections
    assert failed.execution is not None
    assert failed.execution.status == ("NOT_ENTERED" if unavailable == "entry" else "UNPRICED")
    assert failed.execution.net_return is None
    assert failed.execution.gross_return is None


def test_forward_prices_and_costs_change_economics_but_not_probability_selection() -> None:
    events, policy, config, _ = fixture_ladder()
    value = events[0].model_dump(mode="json")
    value["request"]["prices"][-1].update(open_a=300.0, open_b=80.0)
    event = LadderEvent.model_validate_json(json.dumps(value))
    expensive = config.model_dump(mode="json")
    expensive.update(entry_cost_bps=20.0, exit_cost_bps=20.0, annual_borrow_rate=0.1)
    high_cost = ExecutionConfig.model_validate_json(json.dumps(expensive))
    original = ladder.evaluate_ladder((events[0],), policy, config)[0]
    changed = ladder.evaluate_ladder((event,), policy, high_cost)[0]
    assert changed.selections == original.selections
    assert changed.execution is not None and original.execution is not None
    assert changed.execution.net_return != original.execution.net_return


def test_b_and_full_do_not_require_a_probability_or_a_acceptance() -> None:
    events, policy, config, _ = fixture_ladder()
    rows = ladder.evaluate_ladder(events, policy, config)
    for name, a_status in (("b-only", "WITHHELD"), ("missing-a", "UNAVAILABLE")):
        row = next(value for value in rows if value.event_id == f"synthetic-ladder-{name}-v1")
        assert selection(row, "MODEL_A").disposition == a_status
        assert selection(row, "MODEL_B").selected
        assert selection(row, "FULL_SYSTEM").selected


def test_probability_threshold_is_shared_and_inclusive() -> None:
    events, policy, config, _ = fixture_ladder()
    value = events[0].model_dump(mode="json")
    value["state"]["model_a"]["probability"] = policy.candidate_threshold
    value["state"]["model_b"]["probability"] = policy.candidate_threshold
    value["state"]["controller"]["decision"]["model_b_probability"] = policy.candidate_threshold
    event = LadderEvent.model_validate_json(json.dumps(value))
    row = ladder.evaluate_ladder((event,), policy, config)[0]
    assert selection(row, "MODEL_A").selected and selection(row, "MODEL_B").selected


@pytest.mark.parametrize(
    ("previous_z", "signal_z", "fresh"),
    [
        (1.999, 2.0, True),
        (2.0, 2.4, False),
        (2.4, 2.4, False),
        (-2.4, 2.4, False),
        (1.5, 1.999, False),
        (-1.5, -2.4, True),
        (1.5, -2.4, True),
    ],
)
def test_crossing_requires_observed_prior_inside_band_and_current_divergence(
    previous_z: float, signal_z: float, fresh: bool
) -> None:
    events, policy, config, _ = fixture_ladder()
    event = with_z(events[0], previous_z=previous_z, signal_z=signal_z)
    row = ladder.evaluate_ladder((event,), policy, config)[0]
    assert row.raw_fresh is fresh
    assert selection(row, "BASELINE_0").selected is fresh
    assert (row.execution is not None) is fresh


def test_new_snapshot_may_become_usable_after_the_previous_price_close() -> None:
    events, policy, config, _ = fixture_ladder()
    event = events[0]
    assert event.state.previous is not None
    assert event.request.snapshot.available_at.date() > event.state.previous.session_date
    assert ladder.evaluate_ladder((event,), policy, config)[0].raw_fresh is True


@pytest.mark.parametrize("pair_status", ["WATCH", "RETIRED", "UNKNOWN"])
def test_historical_relationship_gate_preserves_raw_counterfactual(pair_status: str) -> None:
    events, policy, config, _ = fixture_ladder()
    event = changed_event(events[0], {"state": {"pair_status": pair_status}})
    row = ladder.evaluate_ladder((event,), policy, config)[0]
    assert selection(row, "BASELINE_0").selected
    expected = "UNAVAILABLE" if pair_status == "UNKNOWN" else "WITHHELD"
    assert all(value.disposition == expected for value in row.selections[1:])
    assert row.execution is not None and row.execution.status == "COMPLETE"


def test_current_price_unavailability_cannot_use_an_unverified_declared_z() -> None:
    events, policy, config, _ = fixture_ladder()
    value = events[0].model_dump(mode="json")
    value["request"]["prices"][0]["close_a"] = None
    event = LadderEvent.model_validate_json(json.dumps(value))
    row = ladder.evaluate_ladder((event,), policy, config)[0]
    assert row.raw_fresh is None and row.execution is None
    assert all(value.disposition == "UNAVAILABLE" for value in row.selections)
    assert selection(row, "BASELINE_0").reason_codes == ("UNKNOWN_SIGNAL_CLOSE",)


@pytest.mark.parametrize("field,value", [("session_date", "2022-12-29"), ("snapshot_id", "other")])
def test_previous_observation_requires_exact_prior_xnys_session_and_current_snapshot(
    field: str, value: str
) -> None:
    events, _, _, _ = fixture_ladder()
    payload = events[0].model_dump(mode="json")
    payload["state"]["previous"][field] = value
    with pytest.raises(ValidationError):
        LadderEvent.model_validate_json(json.dumps(payload))


def test_previous_z_cannot_disagree_with_original_prices() -> None:
    events, _, _, _ = fixture_ladder()
    payload = events[0].model_dump(mode="json")
    payload["state"]["previous"]["z"] = 0.0
    with pytest.raises(ValidationError, match="Previous z must reconcile"):
        LadderEvent.model_validate_json(json.dumps(payload))


def test_unscheduled_abstention_is_unavailable_and_exact_receipt_is_preserved() -> None:
    events, policy, config, _ = fixture_ladder()
    event = next(value for value in events if "unscheduled" in value.state.event_id)
    before = canonical_bytes(event.state)
    row = ladder.evaluate_ladder((event,), policy, config)[0]
    assert selection(row, "FULL_SYSTEM").reason_codes == ("AGENT_UNSCHEDULED",)
    assert selection(row, "FULL_SYSTEM").disposition == "UNAVAILABLE"
    assert canonical_bytes(event.state) == before
    assert event.state.controller is not None
    assert event.state.controller.decision.status == "ABSTAIN"
    assert event.state.controller.decision.reason_codes == ("INVESTIGATION_NOT_SCHEDULED",)
    assert row.state_sha256 == sha256(event.state)


@pytest.mark.parametrize("name", ["review", "no-trade", "abstain"])
def test_investigated_non_candidates_are_withheld_not_missing(name: str) -> None:
    events, policy, config, _ = fixture_ladder()
    event = next(value for value in events if value.state.event_id == f"synthetic-ladder-{name}-v1")
    row = ladder.evaluate_ladder((event,), policy, config)[0]
    assert selection(row, "MODEL_B").selected
    assert selection(row, "FULL_SYSTEM").available
    assert selection(row, "FULL_SYSTEM").disposition == "WITHHELD"


@pytest.mark.parametrize("status", ["DRAFT", "FROZEN"])
def test_all_production_ladder_statuses_remain_blocked(status: str) -> None:
    events, policy, config, _ = fixture_ladder()
    with pytest.raises(ValueError, match="synthetic fixture"):
        ladder.evaluate_ladder(events, changed_policy(policy, status=status), config)


@pytest.mark.parametrize("status", ["DRAFT", "FROZEN"])
def test_development_execution_policy_cannot_enter_fixture_ladder(status: str) -> None:
    events, policy, config, _ = fixture_ladder()
    payload = config.model_dump(mode="json")
    payload.update(mode="DEVELOPMENT", status=status)
    execution = ExecutionConfig.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="synthetic fixture"):
        ladder.evaluate_ladder(events, policy, execution)


def test_capture_inventory_is_rejected_before_any_counterfactual_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, policy, config, _ = fixture_ladder()
    captured = changed_event(events[-1], {"request": {"data_kind": "DEVELOPMENT_CAPTURE"}})
    calls: list[str] = []

    def forbidden(request: PairTradeRequest, execution: ExecutionConfig) -> PairTradeResult:
        calls.append(request.event_id)
        raise AssertionError("Bad inventory must fail before executing early valid rows")

    monkeypatch.setattr(ladder, "simulate_pair_trade", forbidden)
    with pytest.raises(ValueError, match="Captured market"):
        ladder.evaluate_ladder((*events[:-1], captured), policy, config)
    assert not calls


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_a_bundle_id", "other"),
        ("model_a_calibrator_id", "other"),
        ("model_b_bundle_id", "other"),
        ("model_b_calibrator_id", "other"),
        ("model_b_variant", "B-tone"),
        ("model_family", "xgboost"),
    ],
)
def test_declared_named_model_identities_cannot_silently_change(field: str, value: str) -> None:
    events, policy, config, _ = fixture_ladder()
    with pytest.raises(ValueError, match="Stored prediction"):
        ladder.evaluate_ladder(events, changed_policy(policy, **{field: value}), config)


def test_unmatched_horizon_threshold_or_controller_policy_refuses_execution() -> None:
    events, policy, config, _ = fixture_ladder()
    with pytest.raises(ValueError, match="horizon"):
        ladder.evaluate_ladder(events, changed_policy(policy, horizon_sessions=10), config)
    with pytest.raises(ValueError, match="threshold"):
        ladder.evaluate_ladder(events, changed_policy(policy, candidate_threshold=None), config)
    with pytest.raises(ValueError, match="Stored controller policy"):
        ladder.evaluate_ladder(
            events, changed_policy(policy, controller_policy_version="other"), config
        )


def test_duplicate_inventory_does_not_double_count_one_event() -> None:
    events, policy, config, _ = fixture_ladder()
    with pytest.raises(ValueError, match="unique event"):
        ladder.evaluate_ladder((*events, events[0]), policy, config)


def test_evaluation_labels_are_separate_and_cannot_enter_selection_schema() -> None:
    events, _, _, labels = fixture_ladder()
    assert len(labels) == len(events)
    assert labels[0].complete_window_end > events[0].request.sessions[-1].session_date
    payload = events[0].model_dump(mode="json")
    payload["state"]["label_success"] = labels[0].label_success
    with pytest.raises(ValidationError, match="Extra inputs"):
        LadderEvent.model_validate_json(json.dumps(payload))


def test_fixture_labels_can_disagree_with_economic_return_without_affecting_selection() -> None:
    events, policy, config, labels = fixture_ladder()
    row = ladder.evaluate_ladder((events[2],), policy, config)[0]
    assert labels[2].label_success == 0
    assert row.execution is not None and row.execution.net_return is not None
    assert row.execution.net_return > 0
    assert selection(row, "MODEL_B").selected and selection(row, "FULL_SYSTEM").selected


def test_empty_inventory_retains_an_explicit_empty_result() -> None:
    _, policy, config, _ = fixture_ladder()
    assert ladder.evaluate_ladder((), policy, config) == ()

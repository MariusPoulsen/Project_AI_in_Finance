"""Coverage, clock and paired-block checks on deliberately invented prices."""

import hashlib
import json
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from structural_break.backtest.contracts import canonical_sessions
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import LadderEvent
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.robustness import (
    PointInTimeContext,
    RobustnessPolicy,
    build_robustness_report,
    fixture_contexts,
)
from structural_break.backtest.uncertainty import EconomicBootstrapPolicy, paired_month_bootstrap


def changed_context(context: PointInTimeContext, **updates: Any) -> PointInTimeContext:
    payload = context.model_dump(mode="json")
    payload.update(updates)
    return PointInTimeContext.model_validate_json(json.dumps(payload))


def move_event(event: LadderEvent, day: date, *, loss: bool = False) -> LadderEvent:
    """Shift all synthetic clocks together, preserving the same admissible fit."""
    payload = event.model_dump(mode="json")
    sessions = canonical_sessions(day, day + timedelta(days=14))[:3]
    payload["request"]["sessions"] = [
        {
            "session_date": d.isoformat(),
            "open_at": opening.isoformat(),
            "close_at": close.isoformat(),
        }
        for d, opening, close in sessions
    ]
    cutoff = sessions[0][2].isoformat()
    payload["request"]["signal_at"] = payload["state"]["signal_at"] = cutoff
    for prices, session in zip(payload["request"]["prices"], sessions, strict=True):
        prices["session_date"] = session[0].isoformat()
    if loss:
        payload["request"]["prices"][-1].update(open_a=231.0, open_b=90.0)
    previous = canonical_sessions(day - timedelta(days=14), day)[-2][0]
    payload["state"]["previous"]["session_date"] = previous.isoformat()
    for role in ("model_a", "model_b", "controller"):
        if payload["state"][role] is not None:
            payload["state"][role]["information_cutoff"] = cutoff
    return LadderEvent.model_validate_json(json.dumps(payload))


def bootstrap(*, replicates: int = 100) -> dict[str, Any]:
    events, policy, execution, _ = fixture_ladder()
    return paired_month_bootstrap(
        events,
        evaluate_ladder(events, policy, execution),
        policy,
        bootstrap_policy=EconomicBootstrapPolicy(replicates=replicates),
    )


def test_every_slice_retains_the_inventory_including_missing_context() -> None:
    events, policy, execution, labels = fixture_ladder()
    result = build_robustness_report(
        events,
        evaluate_ladder(events, policy, execution),
        policy,
        labels=labels,
        contexts=fixture_contexts(events),
    )
    assert result["population_n"] == 14
    assert result["context_supplied_n"] == 3
    assert result["context_missing_n"] == 11
    for slices in result["slices"].values():
        assert sum(group["population_n"] for group in slices.values()) == 14
        assert all(group["tiny_population"] for group in slices.values())
    assert result["slices"]["vix_stress"]["UNKNOWN"]["population_n"] == 11
    assert result["slices"]["event_type"]["UNKNOWN"]["population_n"] == 12
    assert result["slices"]["materiality"]["HIGH"]["population_n"] == 1
    assert result["genuine_economic_acceptance_passed"] is False
    assert result["final_test_read"] is False


def test_tiny_and_empty_groups_do_not_invent_zero_returns() -> None:
    events, policy, execution, _ = fixture_ladder()
    event = next(event for event in events if "unpriced" in event.state.event_id)
    result = build_robustness_report((event,), evaluate_ladder((event,), policy, execution), policy)
    economics = result["slices"]["pair"][event.state.pair_id]["natural_rungs"]["MODEL_B"][
        "selected_economics"
    ]
    assert economics["priced_n"] == 0
    assert economics["unknown_return_n"] == 1
    assert economics["mean_net_return"] is None
    excluded = result["leave_one_out"]["pair"][event.state.pair_id]
    assert excluded["population_n"] == 0
    assert excluded["natural_rungs"]["MODEL_B"]["selected_economics"]["mean_net_return"] is None


def test_single_class_predictive_slice_keeps_undefined_auc_and_label_counts() -> None:
    events, policy, execution, labels = fixture_ladder()
    result = build_robustness_report(
        events[:1],
        evaluate_ladder(events[:1], policy, execution),
        policy,
        labels=labels[:1],
    )
    metrics = result["slices"]["year"]["2023"]["predictive"]["natural_model_a"]
    assert metrics["score_and_label_n"] == 1
    assert metrics["metrics"]["roc_auc"] is None
    assert metrics["label_coverage"]["label_successes"] == 1


def test_context_does_not_change_selection_and_labels_stay_separate() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    without = build_robustness_report(events, rows, policy)
    with_context = build_robustness_report(events, rows, policy, contexts=fixture_contexts(events))
    with_labels = build_robustness_report(events, rows, policy, labels=labels)
    for rung in without["baseline"]["natural_rungs"]:
        assert (
            without["baseline"]["natural_rungs"][rung]["selected_n"]
            == with_context["baseline"]["natural_rungs"][rung]["selected_n"]
        )
        assert (
            without["baseline"]["natural_rungs"][rung]["selected_economics"]
            == with_labels["baseline"]["natural_rungs"][rung]["selected_economics"]
        )


@pytest.mark.parametrize(
    "field", ["information_cutoff", "evidence_available_at", "volatility_observed_at"]
)
def test_future_context_clock_is_rejected(field: str) -> None:
    events, _, _, _ = fixture_ladder()
    context = fixture_contexts(events)[0]
    with pytest.raises(ValidationError):
        changed_context(
            context, **{field: (context.information_cutoff + timedelta(days=1)).isoformat()}
        )


def test_same_session_vix_and_stale_vix_are_rejected() -> None:
    events, _, _, _ = fixture_ladder()
    context = fixture_contexts(events)[0]
    for clock in (context.information_cutoff, context.information_cutoff - timedelta(days=10)):
        with pytest.raises(ValidationError, match="preceding"):
            changed_context(context, vix_observed_at=clock.isoformat())


@pytest.mark.parametrize(
    "updates",
    [
        {"vix_observed_at": None},
        {"vix_previous_close": None},
        {"volatility_observed_at": None},
        {"trailing_annualized_volatility": None},
        {"event_type": "REALIZED_WIN"},
        {"materiality": "SUCCESS"},
        {"label_success": 1},
        {"vix_previous_close": float("nan")},
    ],
)
def test_incomplete_or_outcome_context_is_rejected(updates: dict[str, Any]) -> None:
    events, _, _, _ = fixture_ladder()
    with pytest.raises(ValidationError):
        changed_context(fixture_contexts(events)[0], **updates)


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", "foreign-event"),
        ("pair_id", "CCC__DDD"),
        ("context_policy_version", "different-policy"),
    ],
)
def test_context_inventory_identity_is_exact(field: str, value: str) -> None:
    events, policy, execution, _ = fixture_ladder()
    context = changed_context(fixture_contexts(events)[0], **{field: value})
    with pytest.raises(ValueError, match="Context"):
        build_robustness_report(
            events, evaluate_ladder(events, policy, execution), policy, contexts=(context,)
        )


def test_duplicate_context_inventory_is_rejected() -> None:
    events, policy, execution, _ = fixture_ladder()
    context = fixture_contexts(events)[0]
    with pytest.raises(ValueError, match="duplicate"):
        build_robustness_report(
            events, evaluate_ladder(events, policy, execution), policy, contexts=(context, context)
        )


def test_boundaries_are_predeclared_and_include_exact_boundary_in_higher_bucket() -> None:
    events, policy, execution, _ = fixture_ladder()
    contexts = fixture_contexts(events)
    contexts = (
        changed_context(contexts[0], vix_previous_close=20.0, trailing_annualized_volatility=0.2),
        changed_context(contexts[1], vix_previous_close=30.0, trailing_annualized_volatility=0.4),
    )
    result = build_robustness_report(
        events, evaluate_ladder(events, policy, execution), policy, contexts=contexts
    )
    assert result["slices"]["vix_stress"]["ELEVATED"]["population_n"] == 1
    assert result["slices"]["vix_stress"]["HIGH"]["population_n"] == 1
    with pytest.raises(ValidationError, match="increasing"):
        RobustnessPolicy(vix_elevated=30.0, vix_high=20.0)


def test_pair_contribution_is_completed_unit_return_and_counts_unpriced() -> None:
    events, policy, execution, _ = fixture_ladder()
    result = build_robustness_report(events, evaluate_ladder(events, policy, execution), policy)
    contribution = result["pair_concentration"]["FULL_SYSTEM"]
    assert contribution["selected_n"] == 4
    assert contribution["priced_n"] == 3
    assert contribution["unknown_return_n"] == 1
    assert contribution["selected_count_hhi"] == 1.0
    pair = contribution["pairs"]["AAA__BBB"]
    mean = result["baseline"]["natural_rungs"]["FULL_SYSTEM"]["selected_economics"][
        "mean_net_return"
    ]
    assert pair["sum_completed_unit_net_returns"] == pytest.approx(3 * mean)
    assert contribution["not_portfolio_pnl"] is True


def test_leave_one_pair_and_sector_out_retain_the_other_groups() -> None:
    events, policy, execution, _ = fixture_ladder()
    payload = events[2].model_dump(mode="json")
    payload["request"].update(pair_id="CCC__BBB", leg_a="CCC")
    payload["state"].update(pair_id="CCC__BBB", sector="OTHER_SYNTHETIC")
    payload["state"]["controller"]["pair_id"] = "CCC__BBB"
    second = LadderEvent.model_validate_json(json.dumps(payload))
    chosen = (events[0], events[1], second)
    result = build_robustness_report(chosen, evaluate_ladder(chosen, policy, execution), policy)
    assert result["leave_one_out"]["pair"]["AAA__BBB"]["population_n"] == 1
    assert result["leave_one_out"]["sector"]["OTHER_SYNTHETIC"]["population_n"] == 2
    assert result["pair_concentration"]["BASELINE_0"]["selected_count_hhi"] == pytest.approx(5 / 9)
    assert result["slices"]["pair"]["CCC__BBB"]["natural_rungs"]["MODEL_A"]["selected_n"] == 0
    assert result["slices"]["pair"]["CCC__BBB"]["natural_rungs"]["MODEL_B"]["selected_n"] == 1


def test_negative_divergence_uses_signal_sign_and_keeps_same_snapshot_for_previous() -> None:
    from math import exp, log

    events, policy, execution, _ = fixture_ladder()
    payload = events[0].model_dump(mode="json")
    alpha = payload["request"]["snapshot"]["alpha"] + 0.48
    payload["request"]["snapshot"]["alpha"] = alpha
    payload["request"]["signal_z"] = -2.4
    payload["state"]["previous"]["close_a"] = exp(alpha + 2 * log(100.0) + 0.15)
    negative = LadderEvent.model_validate_json(json.dumps(payload))
    result = build_robustness_report(
        (negative,), evaluate_ladder((negative,), policy, execution), policy
    )
    assert result["slices"]["divergence_sign"]["NEGATIVE"]["population_n"] == 1
    assert result["slices"]["divergence_sign"]["NEGATIVE"]["raw_fresh_n"] == 1


def test_bootstrap_default_policy_is_fixed_and_one_month_interval_is_suppressed() -> None:
    result = bootstrap()
    assert EconomicBootstrapPolicy().replicates == 2000
    assert result["raw_candidate_population_n"] == 12
    assert result["all_input_population_n"] == 14
    assert result["excluded_nonfresh_n"] == result["excluded_unknown_freshness_n"] == 1
    assert result["calendar_months"] == ["2023-01"]
    for comparison in result["comparisons"].values():
        for estimand in (
            "natural_selected_complete",
            "common_known_allocation_per_raw_candidate",
            "common_priced_both_selected_intersection",
        ):
            interval = comparison[estimand]["bootstrap"]
            assert interval["percentile_interval_95"] is None
            assert (
                interval["interval_unavailable_reason"] == "INSUFFICIENT_POPULATED_CALENDAR_MONTHS"
            )


def test_unpriced_and_unscheduled_are_unknown_allocations_not_zero() -> None:
    result = bootstrap()
    observed = result["observed_status_counts"]["FULL_SYSTEM"]
    assert observed["SELECTED_COMPLETE"] == 3
    assert observed["SELECTED_UNPRICED"] == 1
    assert observed["UNAVAILABLE"] == 3  # Missing B, unscheduled, missing controller.
    comparison = result["comparisons"]["MODEL_B__FULL_SYSTEM"]
    common = comparison["common_known_allocation_per_raw_candidate"]
    assert common["paired_unknown_n"] == 4
    assert common["paired_known_n"] == 8
    natural = comparison["natural_selected_complete"]
    assert natural["right_priced_n"] == 3
    assert natural["right_sum"] / 3 == pytest.approx(
        natural["right_sum"] / natural["right_priced_n"]
    )
    for statuses in result["draw_status_counts"]:
        assert all(sum(counts.values()) == 12 for counts in statuses.values())


def test_months_share_multiplicity_and_empty_draws_remain_undefined() -> None:
    events, policy, execution, _ = fixture_ladder()
    chosen = (events[1], move_event(events[2], date(2023, 3, 1), loss=True))
    rows = evaluate_ladder(chosen, policy, execution)
    declared = EconomicBootstrapPolicy(replicates=100, minimum_populated_months_for_interval=2)
    result = paired_month_bootstrap(chosen, rows, policy, bootstrap_policy=declared)
    assert result["calendar_months"] == ["2023-01", "2023-02", "2023-03"]
    assert result["observed_block_population_n"] == [1, 0, 1]
    assert result["empty_calendar_month_blocks_n"] == 1
    sampled = np.random.default_rng(declared.seed).integers(0, 3, (100, 3))
    assert (
        result["sampled_month_indices_sha256"]
        == hashlib.sha256(sampled.astype("<i8").tobytes()).hexdigest()
    )
    comparison = result["comparisons"]["MODEL_A__MODEL_B"]
    for indices, population, statuses, draw in zip(
        sampled,
        result["draw_population_n"],
        result["draw_status_counts"],
        comparison["draws"],
        strict=True,
    ):
        january, march = int((indices == 0).sum()), int((indices == 2).sum())
        assert population == january + march
        assert statuses["MODEL_A"]["SELECTED_COMPLETE"] == january
        assert statuses["MODEL_B"]["SELECTED_COMPLETE"] == march
        assert draw["allocation_paired_known_n"] == population
        left = rows[0].execution.net_return if rows[0].execution else None
        right = rows[1].execution.net_return if rows[1].execution else None
        assert left is not None and right is not None
        expected = (march * right - january * left) / population if population else None
        assert (
            draw["allocation_right_minus_left_mean"] == pytest.approx(expected)
            if expected is not None
            else draw["allocation_right_minus_left_mean"] is None
        )
    natural = comparison["natural_selected_complete"]["bootstrap"]
    allocation = comparison["common_known_allocation_per_raw_candidate"]["bootstrap"]
    assert natural["undefined_draws_n"] > allocation["undefined_draws_n"] > 0
    assert allocation["percentile_interval_95"] is not None


def test_bootstrap_is_order_invariant_and_seed_changes_only_resamples() -> None:
    events, policy, execution, _ = fixture_ladder()
    chosen = (events[1], move_event(events[2], date(2023, 3, 1), loss=True))
    rows = evaluate_ladder(chosen, policy, execution)
    declared = EconomicBootstrapPolicy(replicates=100)
    result = paired_month_bootstrap(chosen, rows, policy, bootstrap_policy=declared)
    reordered = paired_month_bootstrap(
        tuple(reversed(chosen)), tuple(reversed(rows)), policy, bootstrap_policy=declared
    )
    assert result == reordered
    reseeded = paired_month_bootstrap(
        chosen, rows, policy, bootstrap_policy=EconomicBootstrapPolicy(replicates=100, seed=42)
    )
    assert reseeded["sampled_month_indices_sha256"] != result["sampled_month_indices_sha256"]
    for name, comparison in result["comparisons"].items():
        for estimand in (
            "natural_selected_complete",
            "common_known_allocation_per_raw_candidate",
            "common_priced_both_selected_intersection",
        ):
            observed = {
                key: value for key, value in comparison[estimand].items() if key != "bootstrap"
            }
            changed = {
                key: value
                for key, value in reseeded["comparisons"][name][estimand].items()
                if key != "bootstrap"
            }
            assert observed == changed


def test_no_fresh_events_produces_undefined_draws_without_favorable_zeros() -> None:
    events, policy, execution, _ = fixture_ladder()
    chosen = tuple(
        event
        for event in events
        if "not-fresh" in event.state.event_id or "no-previous" in event.state.event_id
    )
    result = paired_month_bootstrap(
        chosen,
        evaluate_ladder(chosen, policy, execution),
        policy,
        bootstrap_policy=EconomicBootstrapPolicy(replicates=100),
    )
    assert result["raw_candidate_population_n"] == 0
    assert result["calendar_months"] == []
    assert result["draw_population_n"] == [0] * 100
    common = result["comparisons"]["MODEL_A__MODEL_B"]["common_known_allocation_per_raw_candidate"]
    assert common["right_minus_left_mean"] is None
    assert common["bootstrap"]["undefined_draws_n"] == 100


def test_interval_requires_month_support_for_its_own_estimand() -> None:
    events, policy, execution, _ = fixture_ladder()
    chosen: list[LadderEvent] = []
    for month in range(1, 13):
        day = canonical_sessions(date(2023, month, 1), date(2023, month, 15))[0][0]
        event = move_event(events[0] if month == 1 else events[1], day)
        payload = event.model_dump(mode="json")
        identity = f"synthetic-support-month-{month}"
        payload["request"]["event_id"] = payload["state"]["event_id"] = identity
        payload["state"]["controller"]["event_id"] = identity
        chosen.append(LadderEvent.model_validate_json(json.dumps(payload)))
    result = paired_month_bootstrap(
        chosen,
        evaluate_ladder(chosen, policy, execution),
        policy,
        bootstrap_policy=EconomicBootstrapPolicy(replicates=100),
    )
    assert result["populated_calendar_month_blocks_n"] == 12
    comparison = result["comparisons"]["MODEL_A__MODEL_B"]
    natural = comparison["natural_selected_complete"]
    assert natural["left_completed_calendar_month_blocks_n"] == 12
    assert natural["right_completed_calendar_month_blocks_n"] == 1
    assert natural["bootstrap"]["percentile_interval_95"] is None
    allocation = comparison["common_known_allocation_per_raw_candidate"]
    assert allocation["bootstrap"]["contributing_calendar_month_blocks_n"] == 12
    assert allocation["bootstrap"]["percentile_interval_95"] is not None
    assert (
        comparison["common_priced_both_selected_intersection"]["bootstrap"][
            "percentile_interval_95"
        ]
        is None
    )


def test_selected_intersection_is_not_the_common_data_or_allocation_population() -> None:
    result = bootstrap()
    comparison = result["comparisons"]["MODEL_A__MODEL_B"]
    intersection = comparison["common_priced_both_selected_intersection"]
    allocation = comparison["common_known_allocation_per_raw_candidate"]
    assert intersection["paired_selected_priced_n"] == 6
    assert allocation["paired_known_n"] == 9
    assert intersection["right_minus_left_mean"] == 0.0
    assert intersection["not_a_selection_improvement_estimand"] is True


def test_locked_metadata_and_captured_economic_inputs_fail_closed() -> None:
    events, policy, execution, _ = fixture_ladder()
    context = fixture_contexts(events)[0]
    with pytest.raises(ValidationError, match="locked"):
        changed_context(context, information_cutoff="2024-01-03T21:00:00+00:00")
    payload = events[0].model_dump(mode="json")
    payload["request"]["data_kind"] = "DEVELOPMENT_CAPTURE"
    captured = LadderEvent.model_validate_json(json.dumps(payload))
    rows = evaluate_ladder(events[:1], policy, execution)
    with pytest.raises(ValueError, match="Genuine"):
        paired_month_bootstrap((captured,), rows, policy)


@pytest.mark.parametrize(
    "updates",
    [
        {"status": "FROZEN"},
        {"replicates": 99},
        {"seed": -1},
        {"minimum_populated_months_for_interval": 1},
        {"known_nonselection": "ALL_ZERO"},
    ],
)
def test_economic_policy_cannot_silently_change_guardrails(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EconomicBootstrapPolicy.model_validate(updates)

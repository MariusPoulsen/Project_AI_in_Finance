"""Coverage and counterfactual metrics without live sources or model fitting."""

import json
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from structural_break.backtest.contracts import canonical_sessions
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import (
    EvaluationLabel,
    LadderEvent,
    LadderPolicy,
    LadderRow,
)
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.reporting import build_comparison_report
from structural_break.ml.model import predictive_metrics


def report(*, labels: bool = True) -> dict[str, Any]:
    events, policy, execution, targets = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    return build_comparison_report(events, rows, policy, labels=targets if labels else ())


def changed_event(event: LadderEvent, **updates: Any) -> LadderEvent:
    payload = event.model_dump(mode="json")
    payload.update(updates)
    return LadderEvent.model_validate_json(json.dumps(payload))


def changed_label(label: EvaluationLabel, **updates: Any) -> EvaluationLabel:
    payload = label.model_dump(mode="json")
    payload.update(updates)
    return EvaluationLabel.model_validate_json(json.dumps(payload))


def test_all_natural_rows_are_retained_and_rungs_branch_independently() -> None:
    result = report()
    assert result["population_n"] == 14
    assert result["raw_fresh_n"] == 12
    assert result["raw_not_fresh_n"] == 1
    assert result["raw_fresh_unknown_n"] == 1
    natural = result["natural_rungs"]
    assert [row["population_n"] for row in natural.values()] == [14] * 5
    assert [row["selected_n"] for row in natural.values()] == [12, 11, 9, 9, 4]
    comparison = result["adjacent_comparisons"]["MODEL_A__MODEL_B"]
    assert comparison["left_only_selected_n"] == comparison["right_only_selected_n"] == 1
    assert comparison["both_selected_n"] == 7
    assert comparison["left_on_common"]["selected_n"] == 8
    assert comparison["right_on_common"]["selected_n"] == 8
    assert comparison["common_data_population_n"] == 11
    assert comparison["common_data_population_n"] > comparison["both_selected_n"]


def test_predictive_population_is_fresh_and_preserves_inactive_and_unknown_text() -> None:
    events, policy, execution, targets = fixture_ladder()
    watch_index = next(i for i, event in enumerate(events) if event.state.pair_status == "WATCH")
    payload = events[watch_index].model_dump(mode="json")
    payload["state"]["source_coverage"] = "UNKNOWN"
    events = (
        *events[:watch_index],
        changed_event(events[watch_index], **payload),
        *events[watch_index + 1 :],
    )
    result = build_comparison_report(
        events, evaluate_ladder(events, policy, execution), policy, labels=targets
    )
    predictive = result["predictive"]
    assert predictive["all_input_population_n"] == 14
    assert predictive["forecast_population_n"] == 12
    assert predictive["excluded_not_fresh_n"] == predictive["excluded_unknown_freshness_n"] == 1
    assert predictive["natural_model_a"]["score_and_label_n"] == 11
    assert predictive["natural_model_b"]["score_and_label_n"] == 11
    assert predictive["common_score_population_n"] == 10
    assert result["source_coverage_counts"]["UNKNOWN"] == 1
    fresh = [
        event
        for event in events
        if event.state.previous is not None and abs(event.state.previous.z) < 2
    ]
    target_map = {target.event_id: target.label_success for target in targets}
    common = [event for event in fresh if event.state.model_a and event.state.model_b]
    expected = predictive_metrics(
        [target_map[event.state.event_id] for event in common],
        [event.state.model_a.probability for event in common if event.state.model_a],
        policy.candidate_threshold,
    )
    actual = predictive["common_model_a"]["metrics"]
    for key in ("n", "positives", "roc_auc", "pr_auc", "brier", "calibration_curve"):
        assert actual[key] == expected[key]
    assert "success_rate_wilson95_iid_reference" not in actual


def test_completed_economics_exclude_unpriced_events_without_zero_imputation() -> None:
    result = report()
    selected = result["natural_rungs"]["FULL_SYSTEM"]["selected_economics"]
    assert selected["population_n"] == 4
    assert selected["priced_n"] == 3
    assert selected["unknown_return_n"] == 1
    assert selected["status_counts"] == {
        "COMPLETE": 3,
        "UNPRICED": 1,
        "NOT_ENTERED": 0,
        "NOT_SIMULATED": 0,
    }
    expected = 0.1 - 0.0005 * (1 + 31 / 30) - 0.03 / 3 / 252
    assert selected["mean_net_return"] == pytest.approx(expected)
    assert selected["mean_net_return"] != pytest.approx(expected * 3 / 4)
    assert selected["mean_mfe"] == pytest.approx(0.1)
    assert selected["mean_mae"] == 0.0


def test_not_entered_counterfactual_is_separate_from_zero_return() -> None:
    events, policy, execution, targets = fixture_ladder()
    payload = events[0].request.model_dump(mode="json")
    payload["prices"][1]["open_a"] = None
    events = (changed_event(events[0], request=payload), *events[1:])
    rows = evaluate_ladder(events, policy, execution)
    result = build_comparison_report(events, rows, policy, labels=targets)
    economics = result["natural_rungs"]["BASELINE_0"]["selected_economics"]
    assert economics["status_counts"]["NOT_ENTERED"] == 1
    assert economics["status_counts"]["UNPRICED"] == 1
    assert economics["priced_n"] == 10
    assert economics["net_zero_n"] == 0


def test_supervised_success_is_not_inferred_from_realized_profit() -> None:
    events, policy, execution, targets = fixture_ladder()
    payload = events[0].request.model_dump(mode="json")
    payload["prices"][-1].update(open_a=231.0, open_b=90.0)
    event = changed_event(events[0], request=payload)
    rows = evaluate_ladder((event,), policy, execution)
    result = build_comparison_report((event,), rows, policy, labels=(targets[0],))
    full = result["natural_rungs"]["FULL_SYSTEM"]
    assert full["selected_labels"]["label_successes"] == 1
    assert full["selected_economics"]["net_negative_n"] == 1
    assert full["selected_economics"]["net_positive_n"] == 0


def test_missing_labels_remain_explicit_and_undefined_metrics_are_null() -> None:
    result = report(labels=False)
    assert result["label_coverage"]["population_n"] == 14
    assert result["label_coverage"]["unknown_label_n"] == 14
    assert result["label_coverage"]["label_success_rate"] is None
    assert result["label_coverage"]["missing_label_reasons"] == {"LABEL_NOT_SUPPLIED": 14}
    assert result["predictive"]["common_model_a"]["metrics"]["brier"] is None
    assert result["agent_controller"]["failed_opportunity_withholding_rate"] is None
    assert result["agent_controller"]["explicit_false_veto_rate"] is None
    assert result["natural_rungs"]["FULL_SYSTEM"]["selected_economics"]["priced_n"] == 3


def test_empty_population_is_json_safe_with_explicit_undefined_rates() -> None:
    _, policy, _, _ = fixture_ladder()
    result = build_comparison_report((), (), policy)
    assert result["population_n"] == 0
    assert result["label_coverage"]["label_success_rate"] is None
    assert result["agent_controller"]["candidate_retention_rate"] is None
    assert result["natural_rungs"]["MODEL_A"]["selected_economics"]["mean_net_return"] is None
    json.dumps(result, allow_nan=False)


def test_scheduled_b_denominator_includes_failed_missing_and_abstaining_agents() -> None:
    result = report()
    agents = result["agent_controller"]
    assert agents["all_model_b_candidates_n"] == 9
    assert agents["scheduled_model_b_candidates_n"] == 8
    assert agents["unscheduled_model_b_candidates_n"] == 1
    assert agents["scheduled_status_counts"] == {
        "CANDIDATE": 4,
        "REVIEW": 1,
        "NO TRADE": 1,
        "ABSTAIN": 1,
        "MISSING": 1,
    }
    assert agents["candidate_retention_rate"] == 0.5
    assert agents["abstention_rate"] == agents["missing_investigation_rate"] == 1 / 8
    matched = result["adjacent_comparisons"]["MODEL_B__FULL_SYSTEM"]
    assert matched["common_data_population_n"] == 8
    assert matched["left_on_common"]["selected_n"] == 8
    assert matched["right_on_common"]["selected_n"] == 4
    assert matched["right_on_common"]["unavailable_n"] == 1


def test_explicit_veto_metrics_are_separate_from_review_abstain_and_missing() -> None:
    agents = report()["agent_controller"]
    assert agents["scheduled_model_b_label_failures_n"] == 3
    assert agents["scheduled_model_b_label_successes_n"] == 5
    assert agents["withheld_label_failures_n"] == 2
    assert agents["withheld_label_successes_n"] == 2
    assert agents["failed_opportunity_withholding_rate"] == 2 / 3
    assert agents["successful_opportunity_withholding_rate"] == 2 / 5
    assert agents["explicit_veto_label_failures_n"] == 0
    assert agents["explicit_veto_label_successes_n"] == 1
    assert agents["explicit_false_veto_rate"] == 1 / 5
    assert agents["explicit_veto_rate"] == 1 / 8


def test_missing_label_keeps_its_scheduled_denominator_and_label_gap() -> None:
    events, policy, execution, targets = fixture_ladder()
    result = build_comparison_report(
        events, evaluate_ladder(events, policy, execution), policy, labels=targets[:-1]
    )
    agents = result["agent_controller"]
    assert agents["scheduled_model_b_candidates_n"] == 8
    assert agents["scheduled_label_coverage"]["unknown_label_n"] == 1
    assert agents["scheduled_model_b_label_failures_n"] == 2
    assert agents["failed_opportunity_withholding_rate"] == 1 / 2


def test_known_earlier_rejection_does_not_invent_higher_layer_data_coverage() -> None:
    events, policy, execution, targets = fixture_ladder()
    watch = next(event for event in events if event.state.pair_status == "WATCH")
    state = watch.state.model_dump(mode="json")
    state.update(model_a=None, model_b=None, controller=None)
    event = changed_event(watch, state=state)
    rows = evaluate_ladder((event,), policy, execution)
    result = build_comparison_report((event,), rows, policy, labels=())
    natural = result["natural_rungs"]["MODEL_A"]
    assert natural["decision_data_available_n"] == 1
    assert natural["required_input_data_available_n"] == 0
    assert result["adjacent_comparisons"]["MODEL_A__MODEL_B"]["common_data_population_n"] == 0


def test_single_class_predictive_discrimination_is_undefined() -> None:
    events, policy, execution, targets = fixture_ladder()
    rows = evaluate_ladder(events[:1], policy, execution)
    result = build_comparison_report(events[:1], rows, policy, labels=targets[:1])
    metrics = result["predictive"]["common_model_a"]["metrics"]
    assert metrics["roc_auc"] is None and metrics["pr_auc"] is None
    assert metrics["brier"] == pytest.approx(0.04)


def test_unknown_pair_status_keeps_forecast_row_but_excludes_economic_common_data() -> None:
    events, policy, execution, targets = fixture_ladder()
    state = events[0].state.model_dump(mode="json")
    state["pair_status"] = "UNKNOWN"
    event = changed_event(events[0], state=state)
    rows = evaluate_ladder((event,), policy, execution)
    result = build_comparison_report((event,), rows, policy, labels=targets[:1])
    assert result["population_n"] == 1
    assert result["predictive"]["common_model_a"]["score_and_label_n"] == 1
    assert result["predictive"]["common_model_b"]["score_and_label_n"] == 1
    assert result["natural_rungs"]["MODEL_B"]["unavailable_n"] == 1
    assert result["adjacent_comparisons"]["MODEL_A__MODEL_B"]["common_data_population_n"] == 0


@pytest.mark.parametrize("kind", ["events", "rows", "labels"])
def test_duplicate_identities_are_rejected(kind: str) -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    if kind == "events":
        events = (*events, events[0])
    elif kind == "rows":
        rows = (*rows, rows[0])
    else:
        labels = (*labels, labels[0])
    with pytest.raises(ValueError, match="Duplicate"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_missing_row_cannot_silently_reduce_reported_population() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    with pytest.raises(ValueError, match="exactly one"):
        build_comparison_report(events, rows[:-1], policy, labels=labels)


@pytest.mark.parametrize("field,value", [("pair_id", "WRONG__PAIR"), ("state_sha256", "f" * 64)])
def test_mismatched_row_inventory_rejected(field: str, value: str) -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    # Deliberately bypass the frozen row validator to exercise report trust boundaries.
    rows = (rows[0].model_copy(update={field: value}), *rows[1:])
    with pytest.raises(ValueError, match="exact event/request/state"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_forged_selection_under_identical_input_hashes_rejected() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    payload = rows[0].model_dump(mode="json")
    payload["selections"][2].update(
        disposition="WITHHELD", reason_codes=["MODEL_A_BELOW_THRESHOLD"]
    )
    rows = (LadderRow.model_validate_json(json.dumps(payload)), *rows[1:])
    with pytest.raises(ValueError, match="deterministic frozen policy"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_changed_threshold_cannot_relabel_existing_selections() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    payload = policy.model_dump(mode="json")
    payload["candidate_threshold"] = 0.9
    changed = LadderPolicy.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="deterministic frozen policy"):
        build_comparison_report(events, rows, changed, labels=labels)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pair_id", "WRONG__PAIR"),
        ("label_policy_version", "wrong-target-policy"),
        ("event_id", "unknown-event"),
    ],
)
def test_mismatched_label_join_rejected(field: str, value: str) -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    labels = (changed_label(labels[0], **{field: value}), *labels[1:])
    with pytest.raises(ValueError, match="outside|exact event/horizon/policy"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_mixed_label_manifest_identity_rejected() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    labels = (changed_label(labels[0], label_manifest_sha256="f" * 64), *labels[1:])
    with pytest.raises(ValueError, match="one immutable label inventory"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_valid_alternative_label_horizon_cannot_join_primary_comparison() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    end = canonical_sessions(date(2023, 1, 3), date(2023, 3, 15))[10][0]
    label = changed_label(labels[0], horizon_sessions=10, complete_window_end=end.isoformat())
    with pytest.raises(ValueError, match="exact event/horizon/policy"):
        build_comparison_report(events, rows, policy, labels=(label, *labels[1:]))


def test_2023_signal_does_not_authorize_a_label_window_crossing_final_lock() -> None:
    _, _, _, labels = fixture_ladder()
    with pytest.raises(ValidationError, match="development-only"):
        changed_label(labels[0], signal_at="2023-12-29T21:00:00Z", complete_window_end="2024-01-30")


@pytest.mark.parametrize("status", ["DRAFT", "FROZEN"])
def test_real_or_unfrozen_reporting_policy_is_blocked(status: str) -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    payload = policy.model_dump(mode="json")
    payload["status"] = status
    blocked = LadderPolicy.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="requires a complete FIXTURE policy"):
        build_comparison_report(events, rows, blocked, labels=labels)


def test_development_price_capture_cannot_be_treated_as_an_accepted_fixture_adapter() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    payload = events[0].request.model_dump(mode="json")
    payload["data_kind"] = "DEVELOPMENT_CAPTURE"
    events = (changed_event(events[0], request=payload), *events[1:])
    with pytest.raises(ValueError, match="declared data kind"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_mixed_execution_costs_rejected() -> None:
    events, policy, execution, labels = fixture_ladder()
    rows = evaluate_ladder(events, policy, execution)
    assert rows[0].execution is not None
    altered = rows[0].execution.model_copy(update={"execution_config_sha256": "f" * 64})
    rows = (rows[0].model_copy(update={"execution": altered}), *rows[1:])
    with pytest.raises(ValueError, match="one shared execution/cost identity"):
        build_comparison_report(events, rows, policy, labels=labels)


def test_report_is_deterministic_json_safe_and_has_no_inference_claim() -> None:
    first = report()
    assert first == report()
    json.dumps(first, allow_nan=False)
    assert first["final_test_read"] is False
    assert first["genuine_economic_acceptance_passed"] is False
    assert first["agent_controller"]["semantic_quality_measured"] is False
    assert "portfolio" not in first and "bootstrap" not in first

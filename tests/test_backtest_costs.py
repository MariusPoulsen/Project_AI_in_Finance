"""The full declared cost grid changes economics, never capability selection."""

import json

import pytest
from pydantic import ValidationError

from structural_break.backtest.contracts import ExecutionConfig
from structural_break.backtest.costs import (
    CostGridPolicy,
    cost_sensitivity_report,
    scenario_configs,
)
from structural_break.backtest.ladder_fixtures import fixture_ladder


def test_full_grid_preserves_denominators_and_selection_and_gross_returns() -> None:
    events, policy, execution, labels = fixture_ladder()
    report = cost_sensitivity_report(events, policy, execution, CostGridPolicy(), labels=labels)
    assert report["scenario_n"] == 12
    expected = [(bps, borrow) for bps in (2.5, 5.0, 10.0, 20.0) for borrow in (0.0, 0.03, 0.1)]
    actual = []
    gross = []
    for scenario in report["scenarios"]:
        config = scenario["execution_config"]
        actual.append((config["entry_cost_bps"], config["annual_borrow_rate"]))
        assert config["entry_cost_bps"] == config["exit_cost_bps"]
        assert len(scenario["event_rows"]) == 14
        full = scenario["natural_rungs"]["FULL_SYSTEM"]
        assert full["selected_n"] == 4
        assert full["selected_economics"]["priced_n"] == 3
        assert full["selected_economics"]["unknown_return_n"] == 1
        assert scenario["agent_controller"]["scheduled_model_b_candidates_n"] == 8
        gross.append(scenario["event_rows"][0]["execution"]["gross_return"])
    assert actual == expected
    assert len(set(gross)) == 1
    assert report["scientific_acceptance"] is False
    assert report["production_costs_frozen"] is False


def test_zero_costs_equal_gross_and_each_cost_increase_reduces_net() -> None:
    events, policy, execution, labels = fixture_ladder()
    grid = CostGridPolicy(turnover_bps=(0.0, 5.0, 20.0), annual_borrow_rates=(0.0, 0.1))
    report = cost_sensitivity_report(events, policy, execution, grid, labels=labels)
    trades = [scenario["event_rows"][0]["execution"] for scenario in report["scenarios"]]
    assert trades[0]["net_return"] == trades[0]["gross_return"]
    assert trades[0]["trading_cost"] == trades[0]["borrow_cost"] == 0.0
    assert trades[0]["net_return"] > trades[1]["net_return"]
    assert trades[0]["net_return"] > trades[2]["net_return"] > trades[4]["net_return"]
    assert trades[1]["net_return"] > trades[3]["net_return"] > trades[5]["net_return"]
    assert trades[4]["net_return"] > trades[5]["net_return"]


def test_missing_labels_do_not_prevent_economic_sensitivity() -> None:
    events, policy, execution, _labels = fixture_ladder()
    grid = CostGridPolicy(turnover_bps=(5.0,), annual_borrow_rates=(0.03,))
    report = cost_sensitivity_report(events, policy, execution, grid)
    model_b = report["scenarios"][0]["natural_rungs"]["MODEL_B"]
    assert model_b["selected_labels"]["labelled_n"] == 0
    assert model_b["selected_labels"]["unknown_label_n"] == 9
    assert model_b["selected_economics"]["priced_n"] == 8


@pytest.mark.parametrize(
    "updates",
    [
        {"turnover_bps": []},
        {"turnover_bps": [5.0, 2.5]},
        {"turnover_bps": [5.0, 5.0]},
        {"annual_borrow_rates": [0.03, 0.03]},
        {"turnover_bps": [-1.0]},
        {"turnover_bps": [101.0]},
        {"annual_borrow_rates": [2.0]},
    ],
)
def test_grid_refuses_ambiguous_or_invalid_scenarios(updates: dict[str, list[float]]) -> None:
    payload = CostGridPolicy().model_dump(mode="json")
    payload.update(updates)
    with pytest.raises(ValidationError):
        CostGridPolicy.model_validate_json(json.dumps(payload))


def test_production_config_cannot_be_used_as_fixture_sensitivity() -> None:
    _events, _policy, execution, _labels = fixture_ladder()
    payload = execution.model_dump(mode="json")
    payload.update(mode="DEVELOPMENT", status="FROZEN")
    with pytest.raises(ValueError, match="fixture execution only"):
        scenario_configs(ExecutionConfig.model_validate_json(json.dumps(payload)), CostGridPolicy())

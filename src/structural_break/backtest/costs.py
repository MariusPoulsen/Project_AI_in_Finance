"""Predeclared fixture cost grid with unchanged, outcome-free selection."""

import json
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from structural_break.backtest.contracts import ExecutionConfig, FrozenModel, Identifier
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import EvaluationLabel, LadderEvent, LadderPolicy
from structural_break.backtest.reporting import build_comparison_report
from structural_break.backtest.simulator import sha256

BasisPoints = Annotated[float, Field(ge=0, le=100)]
BorrowRate = Annotated[float, Field(ge=0, le=1)]


class CostGridPolicy(FrozenModel):
    version: Identifier = "phase6-cost-grid-fixture-v1"
    status: Literal["FIXTURE"] = "FIXTURE"
    turnover_bps: Annotated[tuple[BasisPoints, ...], Field(min_length=1, max_length=10)] = (
        2.5,
        5.0,
        10.0,
        20.0,
    )
    annual_borrow_rates: Annotated[tuple[BorrowRate, ...], Field(min_length=1, max_length=10)] = (
        0.0,
        0.03,
        0.1,
    )

    @model_validator(mode="after")
    def declared_unique_grid(self) -> Self:
        if tuple(sorted(set(self.turnover_bps))) != self.turnover_bps:
            raise ValueError("Cost grid turnover values must be unique and increasing")
        if tuple(sorted(set(self.annual_borrow_rates))) != self.annual_borrow_rates:
            raise ValueError("Cost grid borrow values must be unique and increasing")
        return self


def scenario_configs(
    execution: ExecutionConfig, grid: CostGridPolicy
) -> tuple[ExecutionConfig, ...]:
    """Only cost fields differ; horizons, entry and exit rules stay fixed."""
    if execution.mode != "FIXTURE" or execution.status != "DRAFT":
        raise ValueError("Cost sensitivity currently supports fixture execution only")
    result = []
    for index, (bps, borrow) in enumerate(
        (bps, borrow) for bps in grid.turnover_bps for borrow in grid.annual_borrow_rates
    ):
        payload = execution.model_dump(mode="json")
        payload.update(
            version=f"{grid.version}-scenario-{index:02d}",
            entry_cost_bps=bps,
            exit_cost_bps=bps,
            annual_borrow_rate=borrow,
        )
        result.append(ExecutionConfig.model_validate_json(json.dumps(payload)))
    return tuple(result)


def cost_sensitivity_report(
    events: Sequence[LadderEvent],
    policy: LadderPolicy,
    execution: ExecutionConfig,
    grid: CostGridPolicy,
    *,
    labels: Sequence[EvaluationLabel] = (),
) -> dict[str, Any]:
    """Every predeclared scenario is reported; no winner is promoted or refitted."""
    base_rows = evaluate_ladder(events, policy, execution)
    selections = tuple((row.event_id, row.raw_fresh, row.selections) for row in base_rows)
    scenarios = []
    for config in scenario_configs(execution, grid):
        rows = evaluate_ladder(events, policy, config)
        if selections != tuple((row.event_id, row.raw_fresh, row.selections) for row in rows):
            raise ValueError("A cost scenario cannot change strategy selection")
        report = build_comparison_report(events, rows, policy, labels=labels)
        scenarios.append(
            {
                "execution_config": config.model_dump(mode="json"),
                "execution_config_sha256": sha256(config),
                "event_rows": [row.model_dump(mode="json") for row in rows],
                "natural_rungs": report["natural_rungs"],
                "adjacent_comparisons": report["adjacent_comparisons"],
                "agent_controller": report["agent_controller"],
            }
        )
    return {
        "schema_version": "phase6-cost-sensitivity-v1",
        "mode": "SYNTHETIC_FIXTURE",
        "grid_policy_sha256": sha256(grid),
        "base_execution_config_sha256": sha256(execution),
        "selection_policy_sha256": sha256(policy),
        "population_n": len(events),
        "scenario_n": len(scenarios),
        "scenarios": scenarios,
        "selection_invariant_across_scenarios": True,
        "production_costs_frozen": False,
        "scientific_acceptance": False,
        "limitations": [
            "Scenario rates are predeclared assumptions, not measured execution costs",
            "No scenario is selected from its result or substituted for the primary research run",
            "Unknown execution returns retain their counts in every scenario",
        ],
    }

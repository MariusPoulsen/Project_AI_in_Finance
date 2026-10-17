"""Separate fixture economic calendar-month block sensitivity.

This never changes canonical v2 paired-quarter predictive uncertainty. All
strategies share sampled calendar months, including every pair in each month.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

import numpy as np
from pydantic import Field, model_validator

from structural_break.backtest.contracts import FrozenModel, Identifier, utc
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    LadderEvent,
    LadderPolicy,
    LadderRow,
)
from structural_break.backtest.reporting import build_comparison_report
from structural_break.backtest.simulator import sha256

if TYPE_CHECKING:
    from structural_break.backtest.historical_contracts import HistoricalSpec

STATUS_COLUMNS = (
    "SELECTED_COMPLETE",
    "SELECTED_UNPRICED",
    "SELECTED_NOT_ENTERED",
    "WITHHELD",
    "UNAVAILABLE",
    "NOT_RUN",
)


FROZEN_BOOTSTRAP_VERSION = "phase6-month-bootstrap-20261016"


class EconomicBootstrapPolicy(FrozenModel):
    version: Identifier = "phase6-fixture-month-bootstrap-v1"
    # Decision 36 froze these fixture parameters for accepted historical use.
    status: Literal["FIXTURE", "FROZEN"] = "FIXTURE"
    replicates: Annotated[int, Field(ge=100, le=10000)] = 2000
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = 5557
    minimum_populated_months_for_interval: Annotated[int, Field(ge=2, le=240)] = 12
    interval_level: Annotated[float, Field(ge=0.95, le=0.95)] = 0.95
    block_rule: Literal["SIGNAL_CALENDAR_MONTH_COMPLETE_RANGE"] = (
        "SIGNAL_CALENDAR_MONTH_COMPLETE_RANGE"
    )
    known_nonselection: Literal["WITHHELD_ZERO_ALLOCATION"] = "WITHHELD_ZERO_ALLOCATION"
    unknown_selection_execution: Literal["UNKNOWN_NO_ZERO_IMPUTATION"] = (
        "UNKNOWN_NO_ZERO_IMPUTATION"
    )

    @model_validator(mode="after")
    def frozen_identity(self) -> Self:
        if (self.status == "FROZEN") != (self.version == FROZEN_BOOTSTRAP_VERSION):
            raise ValueError("Only the Decision 36 bootstrap identity is frozen")
        return self


def _months(rows: Sequence[LadderRow]) -> list[str]:
    observed = sorted({utc(row.signal_at).strftime("%Y-%m") for row in rows})
    if not observed:
        return []
    year, month = (int(part) for part in observed[0].split("-"))
    result: list[str] = []
    while f"{year:04d}-{month:02d}" <= observed[-1]:
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def _complete_return(row: LadderRow) -> float | None:
    if row.execution is None or row.execution.status != "COMPLETE":
        return None
    value = row.execution.net_return
    if value is None:
        raise ValueError("COMPLETE execution requires a net return")
    return value


def _allocation(row: LadderRow, index: int) -> float | None:
    selection = row.selections[index]
    if selection.disposition == "WITHHELD":
        return 0.0
    if selection.selected:
        return _complete_return(row)
    return None


def _mean(total: float, count: float) -> float | None:
    return total / count if count else None


def _difference(left_sum: float, left_n: float, right_sum: float, right_n: float) -> float | None:
    left, right = _mean(left_sum, left_n), _mean(right_sum, right_n)
    return right - left if left is not None and right is not None else None


def _interval(
    values: Sequence[float | None], populated_months: int, policy: EconomicBootstrapPolicy
) -> dict[str, Any]:
    valid = [value for value in values if value is not None]
    reason = (
        "INSUFFICIENT_POPULATED_CALENDAR_MONTHS"
        if populated_months < policy.minimum_populated_months_for_interval
        else "NO_DEFINED_RESAMPLES"
        if not valid
        else None
    )
    return {
        "defined_draws_n": len(valid),
        "undefined_draws_n": len(values) - len(valid),
        "contributing_calendar_month_blocks_n": populated_months,
        "percentile_interval_95": [float(value) for value in np.quantile(valid, [0.025, 0.975])]
        if reason is None
        else None,
        "interval_unavailable_reason": reason,
        "interval_is_fixture_sensitivity_not_inference": True,
    }


def paired_month_bootstrap(
    events: Sequence[LadderEvent],
    rows: Sequence[LadderRow],
    policy: LadderPolicy,
    *,
    bootstrap_policy: EconomicBootstrapPolicy | None = None,
    historical_spec: HistoricalSpec | None = None,
) -> dict[str, Any]:
    """Predeclare three distinct paired economic return estimands on fresh events.

    Natural selected means use each strategy's COMPLETE selected rows. Allocation
    means pair only rows where both strategies' allocations are known: WITHHELD
    allocates zero; selected unpriced/not-entered and UNAVAILABLE stay unknown.
    The separately reported both-selected COMPLETE intersection has the same
    common simulator return on each side, and cannot demonstrate selection gain.
    """
    declared = bootstrap_policy or EconomicBootstrapPolicy()
    if (historical_spec is None) != (declared.status == "FIXTURE"):
        raise ValueError("Fixture bootstrap policies are synthetic; historical use needs FROZEN")
    build_comparison_report(events, rows, policy, historical_spec=historical_spec)
    fresh = sorted((row for row in rows if row.raw_fresh is True), key=lambda row: row.event_id)
    months = _months(fresh)
    month_index = {month: index for index, month in enumerate(months)}
    block_population = np.zeros(len(months), dtype=np.int64)
    block_status = np.zeros((len(months), len(RUNG_ORDER), len(STATUS_COLUMNS)), dtype=np.int64)
    block_natural_sum = np.zeros((len(months), len(RUNG_ORDER)))
    # Paired known allocation and common selected COMPLETE intersection:
    # [allocation left sum, right sum, paired n, shared selected sum, shared n].
    block_pairs = np.zeros((len(months), len(RUNG_ORDER) - 1, 5))
    for row in fresh:
        index = month_index[utc(row.signal_at).strftime("%Y-%m")]
        block_population[index] += 1
        complete_return = _complete_return(row)
        allocations = [_allocation(row, rung_index) for rung_index in range(len(RUNG_ORDER))]
        for rung_index, selection in enumerate(row.selections):
            status = (
                f"SELECTED_{row.execution.status}"
                if selection.selected and row.execution
                else selection.disposition
            )
            block_status[index, rung_index, STATUS_COLUMNS.index(status)] += 1
            if selection.selected and complete_return is not None:
                block_natural_sum[index, rung_index] += complete_return
        for comparison in range(len(RUNG_ORDER) - 1):
            allocation_left, allocation_right = allocations[comparison : comparison + 2]
            if allocation_left is not None and allocation_right is not None:
                block_pairs[index, comparison, :3] += [allocation_left, allocation_right, 1]
            if (
                row.selections[comparison].selected
                and row.selections[comparison + 1].selected
                and complete_return is not None
            ):
                block_pairs[index, comparison, 3:] += [complete_return, 1]
    populated = int((block_population > 0).sum())
    rng = np.random.default_rng(declared.seed)
    sampled = (
        rng.integers(0, len(months), (declared.replicates, len(months)))
        if months
        else np.empty((declared.replicates, 0), dtype=np.int64)
    )
    observed_status = block_status.sum(axis=0)
    observed_natural = block_natural_sum.sum(axis=0)
    observed_pairs = block_pairs.sum(axis=0)
    comparisons: dict[str, Any] = {}
    for index, (left, right) in enumerate(zip(RUNG_ORDER[:-1], RUNG_ORDER[1:], strict=True)):
        paired = observed_pairs[index]
        comparisons[f"{left}__{right}"] = {
            "left": left,
            "right": right,
            "raw_candidate_population_n": len(fresh),
            "natural_selected_complete": {
                "left_sum": float(observed_natural[index]),
                "right_sum": float(observed_natural[index + 1]),
                "left_priced_n": int(observed_status[index, 0]),
                "right_priced_n": int(observed_status[index + 1, 0]),
                "left_completed_calendar_month_blocks_n": int(
                    (block_status[:, index, 0] > 0).sum()
                ),
                "right_completed_calendar_month_blocks_n": int(
                    (block_status[:, index + 1, 0] > 0).sum()
                ),
                "right_minus_left_mean": _difference(
                    float(observed_natural[index]),
                    float(observed_status[index, 0]),
                    float(observed_natural[index + 1]),
                    float(observed_status[index + 1, 0]),
                ),
            },
            "common_known_allocation_per_raw_candidate": {
                "paired_known_n": int(paired[2]),
                "paired_unknown_n": len(fresh) - int(paired[2]),
                "left_sum": float(paired[0]),
                "right_sum": float(paired[1]),
                "paired_known_calendar_month_blocks_n": int((block_pairs[:, index, 2] > 0).sum()),
                "right_minus_left_mean": _difference(
                    float(paired[0]), float(paired[2]), float(paired[1]), float(paired[2])
                ),
            },
            "common_priced_both_selected_intersection": {
                "paired_selected_priced_n": int(paired[4]),
                "shared_sum": float(paired[3]),
                "paired_selected_priced_calendar_month_blocks_n": int(
                    (block_pairs[:, index, 4] > 0).sum()
                ),
                "left_mean": _mean(float(paired[3]), float(paired[4])),
                "right_mean": _mean(float(paired[3]), float(paired[4])),
                "right_minus_left_mean": 0.0 if paired[4] else None,
                "not_a_selection_improvement_estimand": True,
            },
            "draws": [],
        }
    draw_populations: list[int] = []
    draw_statuses: list[dict[str, dict[str, int]]] = []
    for chosen in sampled:
        population = int(block_population[chosen].sum())
        statuses = block_status[chosen].sum(axis=0)
        natural = block_natural_sum[chosen].sum(axis=0)
        paired_values = block_pairs[chosen].sum(axis=0)
        draw_populations.append(population)
        draw_statuses.append(
            {
                rung: {
                    name: int(statuses[index, number]) for number, name in enumerate(STATUS_COLUMNS)
                }
                for index, rung in enumerate(RUNG_ORDER)
            }
        )
        for index, (left, right) in enumerate(zip(RUNG_ORDER[:-1], RUNG_ORDER[1:], strict=True)):
            paired = paired_values[index]
            comparisons[f"{left}__{right}"]["draws"].append(
                {
                    "natural_left_sum": float(natural[index]),
                    "natural_right_sum": float(natural[index + 1]),
                    "natural_left_priced_n": int(statuses[index, 0]),
                    "natural_right_priced_n": int(statuses[index + 1, 0]),
                    "natural_right_minus_left_mean": _difference(
                        float(natural[index]),
                        float(statuses[index, 0]),
                        float(natural[index + 1]),
                        float(statuses[index + 1, 0]),
                    ),
                    "allocation_left_sum": float(paired[0]),
                    "allocation_right_sum": float(paired[1]),
                    "allocation_paired_known_n": int(paired[2]),
                    "allocation_paired_unknown_n": population - int(paired[2]),
                    "allocation_right_minus_left_mean": _difference(
                        float(paired[0]), float(paired[2]), float(paired[1]), float(paired[2])
                    ),
                    "both_selected_priced_n": int(paired[4]),
                    "both_selected_shared_sum": float(paired[3]),
                    "both_selected_right_minus_left_mean": 0.0 if paired[4] else None,
                }
            )
    for comparison in comparisons.values():
        natural = comparison["natural_selected_complete"]
        supported_months = {
            "natural_selected_complete": min(
                natural["left_completed_calendar_month_blocks_n"],
                natural["right_completed_calendar_month_blocks_n"],
            ),
            "common_known_allocation_per_raw_candidate": comparison[
                "common_known_allocation_per_raw_candidate"
            ]["paired_known_calendar_month_blocks_n"],
            "common_priced_both_selected_intersection": comparison[
                "common_priced_both_selected_intersection"
            ]["paired_selected_priced_calendar_month_blocks_n"],
        }
        for name, field in (
            ("natural_selected_complete", "natural_right_minus_left_mean"),
            ("common_known_allocation_per_raw_candidate", "allocation_right_minus_left_mean"),
            ("common_priced_both_selected_intersection", "both_selected_right_minus_left_mean"),
        ):
            comparison[name]["bootstrap"] = _interval(
                [draw[field] for draw in comparison["draws"]], supported_months[name], declared
            )
    if policy.full_system == "NOT_RUN":
        # No accepted controller generation: the B/Full comparison is not run, never zero.
        comparisons["MODEL_B__FULL_SYSTEM"] = {
            "left": "MODEL_B",
            "right": "FULL_SYSTEM",
            "status": "NOT_RUN",
            "reason": "CONTROLLER_GENERATION_NOT_ACCEPTED",
        }
    return {
        "schema_version": "phase6-fixture-economic-month-bootstrap-v1",
        "data_kind": "SYNTHETIC_FIXTURE" if historical_spec is None else "DEVELOPMENT_CAPTURE",
        "post_hoc_development": historical_spec is not None,
        "genuine_economic_acceptance_passed": False,
        "final_test_read": False,
        "policy_sha256": sha256(declared),
        "policy": declared.model_dump(mode="json"),
        "all_input_population_n": len(rows),
        "raw_candidate_population_n": len(fresh),
        "excluded_nonfresh_n": sum(row.raw_fresh is False for row in rows),
        "excluded_unknown_freshness_n": sum(row.raw_fresh is None for row in rows),
        "calendar_months": months,
        "calendar_month_blocks_n": len(months),
        "populated_calendar_month_blocks_n": populated,
        "empty_calendar_month_blocks_n": len(months) - populated,
        "observed_block_population_n": [int(value) for value in block_population],
        "sampled_month_indices_sha256": hashlib.sha256(sampled.astype("<i8").tobytes()).hexdigest(),
        "draw_population_n": draw_populations,
        "draw_status_counts": draw_statuses,
        "observed_status_counts": {
            rung: {
                name: int(observed_status[index, number])
                for number, name in enumerate(STATUS_COLUMNS)
            }
            for index, rung in enumerate(RUNG_ORDER)
        },
        "comparisons": comparisons,
        "limitations": [
            "Fixture month-block sensitivity preserves canonical v2 predictive quarter blocks",
            "All pairs within a sampled month retain identical multiplicity across strategies",
            "Months between first/last raw candidate are included; empty draws remain undefined",
            "WITHHELD allocates zero; UNAVAILABLE and selected unknown execution never become zero",
            "Natural selected means, known allocations and selected intersections are distinct",
            "Unit event allocation return is not a portfolio NAV or leverage-adjusted performance",
            "Intervals require the predeclared contributing-month minimum for their own estimand",
            "Percentile intervals use defined draws only; undefined draws stay separately counted",
            "Temporal blocks do not establish independence; overlapping windows and issuers remain",
        ],
    }

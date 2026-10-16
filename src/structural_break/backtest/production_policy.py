"""The frozen Phase 6 production execution policy and its predeclared sensitivities.

Decision 35 froze one headline `pair-execution-policy-v2` configuration and a
compact sensitivity declaration. Expansion is deterministic, so every reported
variant has a stable identity, and no variant can be added, dropped or chosen
after returns are observed without changing this file's identity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from structural_break.backtest.contracts import ExecutionConfig, FrozenModel, Identifier
from structural_break.backtest.historical_contracts import (
    HEADLINE_TRADING_THRESHOLD,
    SENSITIVITY_TRADING_THRESHOLDS,
)

HEADLINE_CONFIG = "phase6_execution.json"
SENSITIVITY_CONFIG = "phase6_execution_sensitivities.json"
Number = Annotated[float, Field(ge=0, le=1e12)]
# The canonical v2 matched reporting threshold stays a reported trading sensitivity.
V2_REPORTING_THRESHOLD = 0.65


class ExecutionSensitivities(FrozenModel):
    schema_version: Literal["pair-execution-sensitivities-v1"] = "pair-execution-sensitivities-v1"
    version: Identifier
    status: Literal["FROZEN"]
    headline_version: Identifier
    cost_bps_per_side: Annotated[tuple[Number, ...], Field(min_length=1, max_length=8)]
    annual_borrow_rates: Annotated[tuple[Number, ...], Field(min_length=1, max_length=8)]
    positive_beta_limits: Annotated[tuple[Number, ...], Field(max_length=8)]
    min_leg_adv20_usd: Annotated[tuple[Number, ...], Field(max_length=8)]
    horizon_sessions: tuple[Literal[10, 20, 30], ...]
    headline_trading_threshold: Annotated[float, Field(gt=0, lt=1)]
    sensitivity_trading_thresholds: Annotated[tuple[float, ...], Field(max_length=8)]

    @model_validator(mode="after")
    def unique_values(self) -> Self:
        for values in (
            self.cost_bps_per_side,
            self.annual_borrow_rates,
            self.positive_beta_limits,
            self.min_leg_adv20_usd,
            self.horizon_sessions,
            self.sensitivity_trading_thresholds,
        ):
            if len(set(values)) != len(values):
                raise ValueError("Sensitivity values must be unique within each dimension")
        return self


def _reject_constant(value: str) -> object:
    raise ValueError(f"Nonfinite policy constant: {value}")


def _strict(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    json.loads(raw, parse_constant=_reject_constant)
    return raw


def load_headline(configs: Path) -> ExecutionConfig:
    config = ExecutionConfig.model_validate_json(_strict(configs / HEADLINE_CONFIG))
    if (
        config.schema_version != "pair-execution-policy-v2"
        or config.mode != "DEVELOPMENT"
        or config.status != "FROZEN"
        or config.min_leg_adv20_usd is None
    ):
        raise ValueError("The production execution policy must be the frozen v2 headline")
    return config


def load_sensitivities(configs: Path) -> ExecutionSensitivities:
    return ExecutionSensitivities.model_validate_json(_strict(configs / SENSITIVITY_CONFIG))


def expand_policies(
    headline: ExecutionConfig, sensitivities: ExecutionSensitivities
) -> tuple[ExecutionConfig, ...]:
    """Headline first, then the cost x borrow grid and one-at-a-time sensitivities."""
    if sensitivities.headline_version != headline.version:
        raise ValueError("Sensitivities must bind the frozen headline version")
    if (
        headline.entry_cost_bps != headline.exit_cost_bps
        or headline.entry_cost_bps not in sensitivities.cost_bps_per_side
        or headline.annual_borrow_rate not in sensitivities.annual_borrow_rates
    ):
        raise ValueError("The cost/borrow grid must contain the headline scenario")
    for values, current in (
        (sensitivities.positive_beta_limits, headline.positive_beta_limit),
        (sensitivities.min_leg_adv20_usd, headline.min_leg_adv20_usd),
        (sensitivities.horizon_sessions, headline.horizon_sessions),
    ):
        if current in values:
            raise ValueError("One-at-a-time sensitivities must differ from the headline")
    if sensitivities.headline_trading_threshold != HEADLINE_TRADING_THRESHOLD or set(
        sensitivities.sensitivity_trading_thresholds
    ) != {*SENSITIVITY_TRADING_THRESHOLDS, V2_REPORTING_THRESHOLD}:
        raise ValueError("Trading thresholds differ from the Decision 35 declaration")
    base = headline.model_dump(mode="json")

    def variant(name: str, **updates: object) -> ExecutionConfig:
        return ExecutionConfig.model_validate_json(
            json.dumps({**base, **updates, "version": f"{headline.version}:{name}"})
        )

    policies = [headline]
    for cost in sensitivities.cost_bps_per_side:
        for borrow in sensitivities.annual_borrow_rates:
            if (cost, borrow) != (headline.entry_cost_bps, headline.annual_borrow_rate):
                policies.append(
                    variant(
                        f"cost={cost:g}bps,borrow={borrow:g}",
                        entry_cost_bps=cost,
                        exit_cost_bps=cost,
                        annual_borrow_rate=borrow,
                    )
                )
    policies += [
        variant(f"beta<={limit:g}", positive_beta_limit=limit)
        for limit in sensitivities.positive_beta_limits
    ]
    policies += [
        variant(f"adv>={floor:g}", min_leg_adv20_usd=floor)
        for floor in sensitivities.min_leg_adv20_usd
    ]
    policies += [
        variant(f"horizon={horizon}", horizon_sessions=horizon)
        for horizon in sensitivities.horizon_sessions
    ]
    if len({policy.version for policy in policies}) != len(policies):
        raise ValueError("Every expanded execution policy needs a unique version")
    return tuple(policies)

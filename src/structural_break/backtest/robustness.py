"""Predeclared descriptive fixture slices, preserving unknown input coverage.

These helpers do not accept genuine historical generations or open final-test
outcomes. Context is an outcome-free declaration, not source acceptance proof.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from structural_break.backtest.contracts import (
    SHA256,
    FrozenModel,
    Identifier,
    canonical_sessions,
    development_date,
    utc,
)
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    EvaluationLabel,
    LadderEvent,
    LadderPolicy,
    LadderRow,
)
from structural_break.backtest.reporting import build_comparison_report
from structural_break.backtest.simulator import sha256

if TYPE_CHECKING:
    from structural_break.backtest.historical_contracts import HistoricalSpec


class PointInTimeContext(FrozenModel):
    """Optional observable metadata bound to one event and its exact cutoff."""

    event_id: Identifier
    pair_id: Identifier
    information_cutoff: datetime
    source_manifest_sha256: SHA256
    context_policy_version: Identifier
    evidence_available_at: datetime
    vix_previous_close: Annotated[float, Field(ge=0, le=1000)] | None = None
    vix_observed_at: datetime | None = None
    trailing_annualized_volatility: Annotated[float, Field(ge=0, le=100)] | None = None
    volatility_observed_at: datetime | None = None
    event_type: Literal[
        "EARNINGS",
        "GUIDANCE",
        "M&A",
        "REGULATORY",
        "LITIGATION",
        "MANAGEMENT",
        "PRODUCT_OTHER",
        "NONE",
        "UNKNOWN",
    ] = "UNKNOWN"
    materiality: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def admissible_clocks(self) -> Self:
        cutoff = utc(self.information_cutoff)
        development_date(cutoff.date())
        sessions = canonical_sessions(cutoff.date() - timedelta(days=14), cutoff.date())
        if not sessions or utc(sessions[-1][2]) != cutoff:
            raise ValueError("Context cutoff must be the exact development XNYS close")
        if utc(self.evidence_available_at) > cutoff:
            raise ValueError("Context evidence must be admissible by the event close")
        if (self.vix_previous_close is None) != (self.vix_observed_at is None):
            raise ValueError("Previous-session VIX requires its observation clock")
        if self.vix_observed_at is not None and utc(self.vix_observed_at).date() != sessions[-2][0]:
            raise ValueError("VIX must identify the immediately preceding XNYS session")
        if self.vix_observed_at is not None and utc(self.vix_observed_at) > cutoff:
            raise ValueError("VIX observation cannot follow the event cutoff")
        if (self.trailing_annualized_volatility is None) != (self.volatility_observed_at is None):
            raise ValueError("Trailing volatility requires its observation clock")
        if self.volatility_observed_at is not None and utc(self.volatility_observed_at) > cutoff:
            raise ValueError("Trailing volatility cannot include observations after the cutoff")
        return self


class RobustnessPolicy(FrozenModel):
    version: Identifier = "phase6-fixture-robustness-v1"
    status: Literal["FIXTURE", "DRAFT", "FROZEN"] = "FIXTURE"
    context_policy_version: Identifier = "phase6-fixture-context-v1"
    tiny_population_threshold: Annotated[int, Field(ge=2, le=10000)] = 20
    vix_elevated: Annotated[float, Field(ge=0, le=1000)] = 20.0
    vix_high: Annotated[float, Field(ge=0, le=1000)] = 30.0
    volatility_elevated: Annotated[float, Field(ge=0, le=100)] = 0.2
    volatility_high: Annotated[float, Field(ge=0, le=100)] = 0.4

    @model_validator(mode="after")
    def increasing_boundaries(self) -> Self:
        if self.vix_elevated >= self.vix_high or self.volatility_elevated >= self.volatility_high:
            raise ValueError("Stress bucket boundaries must be strictly increasing")
        if (self.status == "FIXTURE") != (self.version == "phase6-fixture-robustness-v1"):
            raise ValueError("Production slice policies need their own declared version")
        return self


def _bucket(value: float | None, elevated: float, high: float) -> str:
    if value is None:
        return "UNKNOWN"
    return "HIGH" if value >= high else "ELEVATED" if value >= elevated else "LOW"


def _context_inventory(
    events: Sequence[LadderEvent], contexts: Sequence[PointInTimeContext], policy: RobustnessPolicy
) -> dict[str, PointInTimeContext]:
    event_map = {event.state.event_id: event for event in events}
    context_map = {context.event_id: context for context in contexts}
    if len(context_map) != len(contexts) or not context_map.keys() <= event_map.keys():
        raise ValueError("Context inventory contains duplicate or foreign events")
    for context in contexts:
        event = event_map[context.event_id]
        if (
            context.pair_id != event.state.pair_id
            or utc(context.information_cutoff) != utc(event.state.signal_at)
            or context.context_policy_version != policy.context_policy_version
        ):
            raise ValueError("Context event/pair/cutoff/policy binding mismatch")
    return context_map


def _slice_values(
    event: LadderEvent, context: PointInTimeContext | None, policy: RobustnessPolicy
) -> dict[str, str]:
    z = event.request.signal_z
    return {
        "year": str(utc(event.state.signal_at).year),
        "pair": event.state.pair_id,
        "sector": event.state.sector,
        "divergence_sign": "POSITIVE" if z > 0 else "NEGATIVE" if z < 0 else "ZERO",
        "source_coverage": event.state.source_coverage,
        "vix_stress": _bucket(
            context.vix_previous_close if context else None, policy.vix_elevated, policy.vix_high
        ),
        "volatility_stress": _bucket(
            context.trailing_annualized_volatility if context else None,
            policy.volatility_elevated,
            policy.volatility_high,
        ),
        "event_type": context.event_type if context else "UNKNOWN",
        "materiality": context.materiality if context else "UNKNOWN",
    }


def _summary(report: dict[str, Any], policy: RobustnessPolicy) -> dict[str, Any]:
    """Reuse validated reporting estimands; small samples keep values but flag limits."""
    return {
        "population_n": report["population_n"],
        "tiny_population": report["population_n"] < policy.tiny_population_threshold,
        "raw_fresh_n": report["raw_fresh_n"],
        "raw_not_fresh_n": report["raw_not_fresh_n"],
        "raw_fresh_unknown_n": report["raw_fresh_unknown_n"],
        "label_coverage": report["label_coverage"],
        "natural_rungs": report["natural_rungs"],
        "predictive": report["predictive"],
        "agent_controller": report["agent_controller"],
        "interpretation": "Descriptive slice; undefined metrics stay null; no subgroup selection",
    }


def _concentration(rows: Sequence[LadderRow]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    pairs = sorted({row.pair_id for row in rows})
    for index, rung in enumerate(RUNG_ORDER):
        selected = [row for row in rows if row.selections[index].selected]
        priced = [
            row
            for row in selected
            if row.execution is not None and row.execution.status == "COMPLETE"
        ]

        def net(row: LadderRow) -> float:
            assert row.execution is not None and row.execution.net_return is not None
            return row.execution.net_return

        total_absolute = sum(abs(net(row)) for row in priced)
        contributions: dict[str, Any] = {}
        for pair in pairs:
            group = [row for row in selected if row.pair_id == pair]
            complete = [row for row in priced if row.pair_id == pair]
            values = [net(row) for row in complete]
            contributions[pair] = {
                "selected_n": len(group),
                "priced_n": len(complete),
                "unknown_return_n": len(group) - len(complete),
                "selected_count_share": len(group) / len(selected) if selected else None,
                "sum_completed_unit_net_returns": sum(values) if values else None,
                "sum_absolute_completed_unit_net_returns": sum(abs(value) for value in values)
                if values
                else None,
                "absolute_unit_return_share": sum(abs(value) for value in values) / total_absolute
                if total_absolute
                else None,
            }
        result[rung] = {
            "selected_n": len(selected),
            "priced_n": len(priced),
            "unknown_return_n": len(selected) - len(priced),
            "pairs": contributions,
            "selected_count_hhi": sum(
                (entry["selected_count_share"] or 0) ** 2 for entry in contributions.values()
            )
            if selected
            else None,
            "absolute_unit_return_hhi": sum(
                (entry["absolute_unit_return_share"] or 0) ** 2 for entry in contributions.values()
            )
            if total_absolute
            else None,
            "not_portfolio_pnl": True,
            "units": "Event return per unit entry gross notional; no capital allocation",
        }
    return result


def build_robustness_report(
    events: Sequence[LadderEvent],
    rows: Sequence[LadderRow],
    policy: LadderPolicy,
    *,
    labels: Sequence[EvaluationLabel] = (),
    contexts: Sequence[PointInTimeContext] = (),
    slice_policy: RobustnessPolicy | None = None,
    historical_spec: HistoricalSpec | None = None,
) -> dict[str, Any]:
    """Fixed slices and leave-one-group-out diagnostics; retain all unknowns."""
    declared = slice_policy or RobustnessPolicy()
    if historical_spec is None and declared.status != "FIXTURE":
        raise ValueError("Synthetic robustness uses the fixture slice policy")
    if historical_spec is not None and declared.status != "FROZEN":
        raise ValueError("Historical robustness requires a frozen slice policy")
    baseline = build_comparison_report(
        events, rows, policy, labels=labels, historical_spec=historical_spec
    )
    context_map = _context_inventory(events, contexts, declared)
    row_map = {row.event_id: row for row in rows}
    label_map = {label.event_id: label for label in labels}
    groups: dict[str, dict[str, list[LadderEvent]]] = {}
    for event in events:
        for dimension, value in _slice_values(
            event, context_map.get(event.state.event_id), declared
        ).items():
            groups.setdefault(dimension, {}).setdefault(value, []).append(event)

    def summarize(subset: Sequence[LadderEvent]) -> dict[str, Any]:
        event_ids = [event.state.event_id for event in subset]
        report = build_comparison_report(
            subset,
            [row_map[event_id] for event_id in event_ids],
            policy,
            labels=[label_map[event_id] for event_id in event_ids if event_id in label_map],
            historical_spec=historical_spec,
        )
        return _summary(report, declared)

    slices = {
        dimension: {value: summarize(subset) for value, subset in sorted(values.items())}
        for dimension, values in groups.items()
    }
    leave_one_out: dict[str, Any] = {}
    for dimension in ("pair", "sector"):
        leave_one_out[dimension] = {}
        for value, excluded in sorted(groups.get(dimension, {}).items()):
            excluded_ids = {event.state.event_id for event in excluded}
            leave_one_out[dimension][value] = summarize(
                [event for event in events if event.state.event_id not in excluded_ids]
            )
    return {
        "schema_version": "phase6-fixture-robustness-report-v1",
        "data_kind": "SYNTHETIC_FIXTURE" if historical_spec is None else "DEVELOPMENT_CAPTURE",
        "post_hoc_development": historical_spec is not None,
        "descriptive_only": True,
        "genuine_economic_acceptance_passed": False,
        "final_test_read": False,
        "policy_sha256": sha256(declared),
        "policy": declared.model_dump(mode="json"),
        "population_n": len(events),
        "context_supplied_n": len(contexts),
        "context_missing_n": len(events) - len(contexts),
        "context_identity_sha256": [
            sha256(context) for context in sorted(contexts, key=lambda x: x.event_id)
        ],
        "baseline": _summary(baseline, declared),
        "slices": slices,
        "pair_concentration": _concentration(rows),
        "leave_one_out": leave_one_out,
        "limitations": [
            "Buckets and tiny-sample threshold are fixture scenarios; production remains DRAFT",
            "Context source declarations require independent acceptance before genuine assessment",
            "UNKNOWN metadata remains a separate slice; missing evidence is not neutral",
            "All slices are reported; no favorable subgroup or leave-one-out result is selected",
            "Unit event-return contributions are not portfolio P&L or deployed capital shares",
        ],
    }


def fixture_contexts(events: Sequence[LadderEvent]) -> tuple[PointInTimeContext, ...]:
    """Three invented context cases; omitted events deliberately remain UNKNOWN."""
    scenarios = (
        (15.0, 0.1, "EARNINGS", "LOW"),
        (25.0, 0.25, "M&A", "HIGH"),
        (35.0, 0.6, "UNKNOWN", "UNKNOWN"),
    )
    result: list[PointInTimeContext] = []
    for event, (vix, volatility, category, materiality) in zip(events[:3], scenarios, strict=False):
        cutoff = utc(event.state.signal_at)
        previous = canonical_sessions(cutoff.date() - timedelta(days=14), cutoff.date())[-2]
        result.append(
            PointInTimeContext.model_validate(
                {
                    "event_id": event.state.event_id,
                    "pair_id": event.state.pair_id,
                    "information_cutoff": cutoff,
                    "evidence_available_at": cutoff,
                    "source_manifest_sha256": hashlib.sha256(b"synthetic-context-v1").hexdigest(),
                    "context_policy_version": RobustnessPolicy().context_policy_version,
                    "vix_previous_close": vix,
                    "vix_observed_at": previous[2],
                    "trailing_annualized_volatility": volatility,
                    "volatility_observed_at": cutoff,
                    "event_type": category,
                    "materiality": materiality,
                }
            )
        )
    return tuple(result)

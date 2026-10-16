"""Descriptive fixture comparisons with explicit missing-data denominators.

Outcome labels enter only this evaluation module, after immutable ladder selection.
The report is not the canonical v2 forecast assessment or a portfolio backtest.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from structural_break.backtest.contracts import PairTradeResult, utc
from structural_break.backtest.ladder import select_ladder_event
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    EvaluationLabel,
    LadderEvent,
    LadderPolicy,
    LadderRow,
    Rung,
    RungSelection,
)
from structural_break.backtest.simulator import sha256
from structural_break.ml.model import predictive_metrics

if TYPE_CHECKING:
    from structural_break.backtest.historical_contracts import HistoricalSpec

REPORT_VERSION = "phase6-descriptive-ladder-report-v1"


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _counts(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _label_summary(event_ids: Sequence[str], labels: dict[str, EvaluationLabel]) -> dict[str, Any]:
    observed = [labels[event_id].label_success for event_id in event_ids if event_id in labels]
    positives = sum(value == 1 for value in observed)
    missing = ["LABEL_NOT_SUPPLIED" for event_id in event_ids if event_id not in labels]
    return {
        "population_n": len(event_ids),
        "labelled_n": len(observed),
        "unknown_label_n": len(missing),
        "label_successes": positives,
        "label_failures": len(observed) - positives,
        "label_success_rate": _rate(positives, len(observed)),
        "missing_label_reasons": _counts([str(reason) for reason in missing]),
    }


def _economics(results: Sequence[PairTradeResult | None]) -> dict[str, Any]:
    """Only fully priced events enter completed-return and excursion statistics."""
    status_counts = {"COMPLETE": 0, "UNPRICED": 0, "NOT_ENTERED": 0, "NOT_SIMULATED": 0}
    complete: list[PairTradeResult] = []
    for result in results:
        status_counts[result.status if result is not None else "NOT_SIMULATED"] += 1
        if result is not None and result.status == "COMPLETE":
            complete.append(result)
    values = np.array([result.net_return for result in complete], dtype=float)
    observed = len(complete)
    return {
        "population_n": len(results),
        "status_counts": status_counts,
        "priced_n": observed,
        "unknown_return_n": len(results) - observed,
        "reason_counts": _counts([result.reason for result in results if result is not None]),
        "net_positive_n": int((values > 0).sum()),
        "net_zero_n": int((values == 0).sum()),
        "net_negative_n": int((values < 0).sum()),
        "net_positive_rate": _rate(int((values > 0).sum()), observed),
        "mean_net_return": float(values.mean()) if observed else None,
        "median_net_return": float(np.median(values)) if observed else None,
        "min_net_return": float(values.min()) if observed else None,
        "max_net_return": float(values.max()) if observed else None,
        "net_return_quantiles": {
            "p05": float(np.quantile(values, 0.05)) if observed else None,
            "p25": float(np.quantile(values, 0.25)) if observed else None,
            "p75": float(np.quantile(values, 0.75)) if observed else None,
            "p95": float(np.quantile(values, 0.95)) if observed else None,
        },
        "mean_gross_return": _complete_mean(complete, "gross_return"),
        "mean_trading_cost": _complete_mean(complete, "trading_cost"),
        "mean_borrow_cost": _complete_mean(complete, "borrow_cost"),
        "mean_mae": _complete_mean(complete, "mae"),
        "mean_mfe": _complete_mean(complete, "mfe"),
        "mean_holding_sessions": _complete_mean(complete, "holding_sessions"),
        "return_policy": "COMPLETE_ONLY; missing returns are not zero imputed",
        "path_policy": "Completed observed-close/exit excursions only; partial marks excluded",
    }


def _complete_mean(complete: Sequence[PairTradeResult], field: str) -> float | None:
    if not complete:
        return None
    values = [getattr(result, field) for result in complete]
    if any(value is None for value in values):
        raise ValueError("Complete economic results must contain completed path metrics")
    return float(np.mean(values))


def _predictive(
    event_ids: Sequence[str],
    scores: dict[str, float | None],
    labels: dict[str, EvaluationLabel],
    threshold: float,
) -> dict[str, Any]:
    matched = [
        event_id for event_id in event_ids if scores[event_id] is not None and event_id in labels
    ]
    values = [scores[event_id] for event_id in matched]
    targets = [labels[event_id].label_success for event_id in matched]
    metrics = predictive_metrics(targets, values, threshold)
    # Canonical metrics remain unchanged. This descriptive fixture report neither
    # introduces iid intervals nor replaces v2's paired quarter-block assessment.
    for key in (
        "success_rate_wilson95_iid_reference",
        "precision_wilson95_iid_reference",
        "uncertainty_note",
    ):
        metrics.pop(key, None)
    return {
        "population_n": len(event_ids),
        "score_available_n": sum(scores[event_id] is not None for event_id in event_ids),
        "missing_score_n": sum(scores[event_id] is None for event_id in event_ids),
        "score_and_label_n": len(matched),
        "excluded_from_metrics_n": len(event_ids) - len(matched),
        "label_coverage": _label_summary(event_ids, labels),
        "candidate_threshold": threshold,
        "metrics": metrics,
    }


def _selection(row: LadderRow, rung: Rung) -> RungSelection:
    return row.selections[RUNG_ORDER.index(rung)]


def _required_data(event: LadderEvent, row: LadderRow, rung: Rung) -> bool:
    """Known rejection at an earlier gate is not complete higher-layer data."""
    if row.raw_fresh is None:
        return False
    if rung == "BASELINE_0":
        return True
    if event.state.pair_status == "UNKNOWN":
        return False
    if rung == "BASELINE_1":
        return True
    if rung == "MODEL_A":
        return event.state.model_a is not None
    if event.state.model_b is None:
        return False
    if rung == "MODEL_B":
        return True
    return event.state.agent_scheduled and event.state.controller is not None


def _rung_report(
    events: dict[str, LadderEvent],
    rows: Sequence[LadderRow],
    rung: Rung,
    labels: dict[str, EvaluationLabel],
) -> dict[str, Any]:
    selected = [row for row in rows if _selection(row, rung).selected]
    rejected = [row for row in rows if not _selection(row, rung).selected]
    available = sum(_selection(row, rung).available for row in rows)
    return {
        "population_n": len(rows),
        "decision_data_available_n": available,
        "required_input_data_available_n": sum(
            _required_data(events[row.event_id], row, rung) for row in rows
        ),
        "unavailable_n": len(rows) - available,
        "selected_n": len(selected),
        "withheld_n": sum(_selection(row, rung).disposition == "WITHHELD" for row in rows),
        "selection_rate_all_rows": _rate(len(selected), len(rows)),
        "selection_rate_available_rows": _rate(len(selected), available),
        "reason_counts": _counts(
            [reason for row in rows for reason in _selection(row, rung).reason_codes]
        ),
        "selected_labels": _label_summary([row.event_id for row in selected], labels),
        "selected_economics": _economics([row.execution for row in selected]),
        "not_selected_labels": _label_summary([row.event_id for row in rejected], labels),
        "not_selected_counterfactual_economics": _economics([row.execution for row in rejected]),
    }


def _validate_report_inputs(
    events: Sequence[LadderEvent],
    rows: Sequence[LadderRow],
    policy: LadderPolicy,
    labels: Sequence[EvaluationLabel],
    historical_spec: HistoricalSpec | None = None,
) -> tuple[dict[str, LadderEvent], dict[str, LadderRow], dict[str, EvaluationLabel]]:
    selector: Callable[[LadderEvent], tuple[bool | None, tuple[RungSelection, ...]]]
    if historical_spec is None:
        if policy.status != "FIXTURE" or policy.candidate_threshold is None:
            raise ValueError(
                "Descriptive ladder reporting currently requires a complete FIXTURE policy"
            )
        data_kind = "SYNTHETIC_FIXTURE"

        def selector(event: LadderEvent) -> tuple[bool | None, tuple[RungSelection, ...]]:
            return select_ladder_event(event, policy)
    else:
        from structural_break.backtest.historical import select_historical_event

        if (
            historical_spec.ladder != policy
            or policy.status != "FROZEN"
            or historical_spec.binding.acceptance != "ACCEPTED"
        ):
            raise ValueError("Historical reporting requires the accepted frozen ladder policy")
        data_kind = "DEVELOPMENT_CAPTURE"
        spec = historical_spec

        def selector(event: LadderEvent) -> tuple[bool | None, tuple[RungSelection, ...]]:
            return select_historical_event(event, spec)

    event_map = {event.state.event_id: event for event in events}
    row_map = {row.event_id: row for row in rows}
    label_map = {label.event_id: label for label in labels}
    if len(event_map) != len(events) or len(row_map) != len(rows) or len(label_map) != len(labels):
        raise ValueError("Duplicate event, ladder row or evaluation label identity")
    if event_map.keys() != row_map.keys():
        raise ValueError("Reporting requires exactly one complete ladder row for every input event")
    if not label_map.keys() <= event_map.keys():
        raise ValueError("Evaluation labels contain events outside the declared population")
    execution_identities: set[str] = set()
    for event_id, event in event_map.items():
        if event.request.data_kind != data_kind:
            raise ValueError("Reporting inputs must all share the declared data kind")
        row = row_map[event_id]
        if (
            row.pair_id != event.state.pair_id
            or utc(row.signal_at) != utc(event.state.signal_at)
            or row.state_sha256 != sha256(event.state)
            or row.request_sha256 != sha256(event.request)
        ):
            raise ValueError("Reporting row does not bind the exact event/request/state identity")
        expected_fresh, expected_selections = selector(event)
        if row.raw_fresh != expected_fresh or row.selections != expected_selections:
            raise ValueError("Reporting selections differ from the deterministic frozen policy")
        if row.execution is not None:
            execution_identities.add(row.execution.execution_config_sha256)
            if (
                row.execution.data_kind != data_kind
                or row.execution.snapshot_id != event.request.snapshot.snapshot_id
                or row.execution.price_lineage != event.request.price_lineage
                or row.execution.signal_z != event.request.signal_z
            ):
                raise ValueError("Shared execution differs from its frozen signal/source identity")
        for prediction, role, bundle, calibrator in (
            (
                event.state.model_a,
                "A",
                policy.model_a_bundle_id,
                policy.model_a_calibrator_id,
            ),
            (
                event.state.model_b,
                policy.model_b_variant,
                policy.model_b_bundle_id,
                policy.model_b_calibrator_id,
            ),
        ):
            if prediction is not None and (
                prediction.model_role != role
                or prediction.model_bundle_id != bundle
                or prediction.calibrator_id != calibrator
                or prediction.model_family != policy.model_family
                or prediction.horizon_sessions != policy.horizon_sessions
            ):
                raise ValueError("Stored prediction does not match the declared comparison policy")
        if (
            event.state.controller is not None
            and event.state.controller.decision.policy_version != policy.controller_policy_version
        ):
            raise ValueError("Stored controller policy differs from the declared comparison")
        if event_id in label_map:
            label = label_map[event_id]
            if (
                label.pair_id != event.state.pair_id
                or utc(label.signal_at) != utc(event.state.signal_at)
                or label.horizon_sessions != policy.horizon_sessions
                or label.label_policy_version != policy.label_policy_version
            ):
                raise ValueError("Evaluation label does not match the exact event/horizon/policy")
    if len(execution_identities) > 1:
        raise ValueError("Ladder reporting requires one shared execution/cost identity")
    if len({label.label_manifest_sha256 for label in labels}) > 1:
        raise ValueError("Evaluation labels must bind one immutable label inventory")
    return event_map, row_map, label_map


def _not_run(population_n: int) -> dict[str, Any]:
    """A rung without an accepted controller generation has no metrics, not zeros."""
    return {
        "status": "NOT_RUN",
        "reason": "CONTROLLER_GENERATION_NOT_ACCEPTED",
        "population_n": population_n,
        "metrics": None,
    }


def _agent_report(
    events: dict[str, LadderEvent], rows: Sequence[LadderRow], labels: dict[str, EvaluationLabel]
) -> dict[str, Any]:
    candidates = [row for row in rows if _selection(row, "MODEL_B").selected]
    scheduled = [row for row in candidates if events[row.event_id].state.agent_scheduled]
    counts = {"CANDIDATE": 0, "REVIEW": 0, "NO TRADE": 0, "ABSTAIN": 0, "MISSING": 0}
    groups: dict[str, list[LadderRow]] = {name: [] for name in counts}
    for row in scheduled:
        controller = events[row.event_id].state.controller
        status = controller.decision.status if controller is not None else "MISSING"
        counts[status] += 1
        groups[status].append(row)
    withheld = [row for row in scheduled if not _selection(row, "FULL_SYSTEM").selected]
    labelled = [row for row in scheduled if row.event_id in labels]
    failures = [row for row in labelled if labels[row.event_id].label_success == 0]
    successes = [row for row in labelled if labels[row.event_id].label_success == 1]
    withheld_ids = {row.event_id for row in withheld}
    veto_ids = {row.event_id for row in groups["NO TRADE"]}
    withheld_failures = sum(row.event_id in withheld_ids for row in failures)
    withheld_successes = sum(row.event_id in withheld_ids for row in successes)
    explicit_veto_failures = sum(row.event_id in veto_ids for row in failures)
    explicit_veto_successes = sum(row.event_id in veto_ids for row in successes)
    reasons = [
        reason
        for row in scheduled
        if (controller := events[row.event_id].state.controller) is not None
        for reason in controller.decision.reason_codes
    ]
    return {
        "all_model_b_candidates_n": len(candidates),
        "scheduled_model_b_candidates_n": len(scheduled),
        "unscheduled_model_b_candidates_n": len(candidates) - len(scheduled),
        "investigation_output_n": len(scheduled) - counts["MISSING"],
        "scheduled_status_counts": counts,
        "scheduled_withheld_n": len(withheld),
        "candidate_retention_rate": _rate(counts["CANDIDATE"], len(scheduled)),
        "explicit_veto_rate": _rate(counts["NO TRADE"], len(scheduled)),
        "review_rate": _rate(counts["REVIEW"], len(scheduled)),
        "abstention_rate": _rate(counts["ABSTAIN"], len(scheduled)),
        "missing_investigation_rate": _rate(counts["MISSING"], len(scheduled)),
        "scheduled_label_coverage": _label_summary([row.event_id for row in scheduled], labels),
        "scheduled_model_b_label_failures_n": len(failures),
        "scheduled_model_b_label_successes_n": len(successes),
        "withheld_label_failures_n": withheld_failures,
        "withheld_label_successes_n": withheld_successes,
        "failed_opportunity_withholding_rate": _rate(withheld_failures, len(failures)),
        "successful_opportunity_withholding_rate": _rate(withheld_successes, len(successes)),
        "explicit_veto_label_failures_n": explicit_veto_failures,
        "explicit_veto_label_successes_n": explicit_veto_successes,
        "explicit_failure_veto_rate": _rate(explicit_veto_failures, len(failures)),
        "explicit_false_veto_rate": _rate(explicit_veto_successes, len(successes)),
        "scheduled_model_b_economics": _economics([row.execution for row in scheduled]),
        "scheduled_full_selected_economics": _economics(
            [row.execution for row in scheduled if _selection(row, "FULL_SYSTEM").selected]
        ),
        "scheduled_withheld_counterfactual_economics": _economics(
            [row.execution for row in withheld]
        ),
        "status_label_coverage": {
            status: _label_summary([row.event_id for row in group], labels)
            for status, group in groups.items()
        },
        "reason_code_counts": _counts(reasons),
        "denominator_policy": (
            "All scheduled Model B candidates, including missing/failed/ABSTAIN investigations; "
            "unscheduled candidates are separately counted"
        ),
        "veto_policy": "Only explicit NO TRADE is a veto; other withheld statuses are separate",
        "semantic_quality_measured": False,
        "fixture_controller_statuses_establish_agent_usefulness": False,
    }


def build_comparison_report(
    events: Sequence[LadderEvent],
    rows: Sequence[LadderRow],
    policy: LadderPolicy,
    *,
    labels: Sequence[EvaluationLabel] = (),
    historical_spec: HistoricalSpec | None = None,
) -> dict[str, Any]:
    """Keep the full population and independent selections in descriptive comparisons.

    With `historical_spec`, rows must be accepted-generation captured events under
    the frozen ladder; results are post-hoc development assessment, not final test.
    """
    event_map, row_map, label_map = _validate_report_inputs(
        events, rows, policy, labels, historical_spec
    )
    aligned = [row_map[event.state.event_id] for event in events]
    event_ids = [event.state.event_id for event in events]
    forecast_ids = [row.event_id for row in aligned if row.raw_fresh is True]
    scores_a = {
        event.state.event_id: event.state.model_a.probability if event.state.model_a else None
        for event in events
    }
    scores_b = {
        event.state.event_id: event.state.model_b.probability if event.state.model_b else None
        for event in events
    }
    assert policy.candidate_threshold is not None
    predictive_common = [
        event_id
        for event_id in forecast_ids
        if scores_a[event_id] is not None and scores_b[event_id] is not None
    ]
    comparisons: dict[str, Any] = {}
    full_run = policy.full_system == "RUN"
    for left, right in zip(RUNG_ORDER[:-1], RUNG_ORDER[1:], strict=True):
        if (left, right) == ("MODEL_B", "FULL_SYSTEM") and not full_run:
            comparisons[f"{left}__{right}"] = {
                "left": left,
                "right": right,
                **_not_run(len(aligned)),
            }
            continue
        if (left, right) == ("MODEL_B", "FULL_SYSTEM"):
            common = [
                row
                for row in aligned
                if _selection(row, left).selected and event_map[row.event_id].state.agent_scheduled
            ]
            population_policy = "All scheduled Model B candidates; missing investigations retained"
        else:
            common = [
                row
                for row in aligned
                if _required_data(event_map[row.event_id], row, left)
                and _required_data(event_map[row.event_id], row, right)
            ]
            population_policy = "Both rungs have required inputs, independent of selection/gates"
        comparisons[f"{left}__{right}"] = {
            "left": left,
            "right": right,
            "natural_population_n": len(aligned),
            "common_data_population_n": len(common),
            "excluded_from_common_n": len(aligned) - len(common),
            "population_policy": population_policy,
            "both_selected_n": sum(
                _selection(row, left).selected and _selection(row, right).selected for row in common
            ),
            "left_only_selected_n": sum(
                _selection(row, left).selected and not _selection(row, right).selected
                for row in common
            ),
            "right_only_selected_n": sum(
                not _selection(row, left).selected and _selection(row, right).selected
                for row in common
            ),
            "left_on_common": _rung_report(event_map, common, left, label_map),
            "right_on_common": _rung_report(event_map, common, right, label_map),
            "selection_policy": "Each rung selects independently on the common data population",
        }
    return {
        "schema_version": REPORT_VERSION,
        "data_kind": "SYNTHETIC_FIXTURE" if historical_spec is None else "DEVELOPMENT_CAPTURE",
        "post_hoc_development": historical_spec is not None,
        "descriptive_only": True,
        "final_test_read": False,
        "genuine_economic_acceptance_passed": False,
        "policy_sha256": sha256(policy),
        "policy_version": policy.version,
        "population_id": policy.population_id,
        "population_n": len(aligned),
        "all_input_rows_retained": True,
        "raw_fresh_n": sum(row.raw_fresh is True for row in aligned),
        "raw_not_fresh_n": sum(row.raw_fresh is False for row in aligned),
        "raw_fresh_unknown_n": sum(row.raw_fresh is None for row in aligned),
        "label_policy_version": policy.label_policy_version,
        "label_manifest_sha256": next(
            iter({label.label_manifest_sha256 for label in labels}), None
        ),
        "label_coverage": _label_summary(event_ids, label_map),
        "source_coverage_counts": _counts([event.state.source_coverage for event in events]),
        "natural_rungs": {
            rung: (
                _rung_report(event_map, aligned, rung, label_map)
                if full_run or rung != "FULL_SYSTEM"
                else _not_run(len(aligned))
            )
            for rung in RUNG_ORDER
        },
        "adjacent_comparisons": comparisons,
        "predictive": {
            "all_input_population_n": len(aligned),
            "forecast_population_n": len(forecast_ids),
            "excluded_not_fresh_n": sum(row.raw_fresh is False for row in aligned),
            "excluded_unknown_freshness_n": sum(row.raw_fresh is None for row in aligned),
            "natural_model_a": _predictive(
                forecast_ids, scores_a, label_map, policy.candidate_threshold
            ),
            "natural_model_b": _predictive(
                forecast_ids, scores_b, label_map, policy.candidate_threshold
            ),
            "common_score_population_n": len(predictive_common),
            "common_model_a": _predictive(
                predictive_common, scores_a, label_map, policy.candidate_threshold
            ),
            "common_model_b": _predictive(
                predictive_common, scores_b, label_map, policy.candidate_threshold
            ),
            "comparison_population_policy": (
                "Estimable fresh divergences with both scores, irrespective of ACTIVE/selection; "
                "only separately supplied labels enter supervised metrics"
            ),
        },
        "agent_controller": (
            _agent_report(event_map, aligned, label_map) if full_run else _not_run(len(aligned))
        ),
        "limitations": [
            (
                "Synthetic engineering outputs do not establish predictive or economic benefit"
                if historical_spec is None
                else "Post-hoc 2022-2023 development assessment under Decision 36; not final test"
            ),
            "Supervised mean-reversion success and positive net trade return are separate outcomes",
            "Economic statistics require COMPLETE; missing returns remain explicit",
            "No portfolio, Sharpe, significance or uncertainty/bootstrap results are produced",
            "Canonical v2 predictive reports and paired quarter-block uncertainty remain unchanged",
        ],
    }

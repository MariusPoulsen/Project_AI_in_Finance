"""Fourteen deliberately synthetic capability/coverage cases for the ladder.

Scores, decisions and labels are invented contract fixtures. They establish no
calibration, agent quality or profitability; evaluation labels stay separate
from all selection inputs and need not agree with the first-day trade return.
"""

import hashlib
import json
from datetime import date
from math import exp, log
from typing import Any

from structural_break.agents.contracts import ControllerDecision, ReasonCode, Risk
from structural_break.backtest.contracts import (
    ExecutionConfig,
    PairTradeRequest,
    canonical_sessions,
)
from structural_break.backtest.fixtures import synthetic_trade_request
from structural_break.backtest.ladder_contracts import (
    EvaluationLabel,
    LadderEvent,
    LadderPolicy,
    LadderState,
    PreviousClose,
    StoredController,
    StoredPrediction,
)
from structural_break.backtest.simulator import fixture_config


def _digest(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _prediction(
    request: PairTradeRequest, policy: LadderPolicy, role: str, probability: float
) -> StoredPrediction:
    return StoredPrediction.model_validate(
        {
            "model_role": "A" if role == "A" else policy.model_b_variant,
            "model_family": policy.model_family,
            "horizon_sessions": policy.horizon_sessions,
            "model_bundle_id": (
                policy.model_a_bundle_id if role == "A" else policy.model_b_bundle_id
            ),
            "calibrator_id": (
                policy.model_a_calibrator_id if role == "A" else policy.model_b_calibrator_id
            ),
            "information_cutoff": request.signal_at,
            "probability": probability,
        }
    )


def _event(
    name: str,
    policy: LadderPolicy,
    *,
    a: float | None = 0.8,
    b: float | None = 0.8,
    pair_status: str = "ACTIVE",
    previous_z: float | None = 1.5,
    scheduled: bool = True,
    controller_status: str | None = "CANDIDATE",
    unpriced: bool = False,
) -> LadderEvent:
    base = synthetic_trade_request()
    payload: dict[str, Any] = base.model_dump(mode="json")
    payload["event_id"] = f"synthetic-ladder-{name}-v1"
    if unpriced:
        payload["prices"][-1]["open_a"] = None
    request = PairTradeRequest.model_validate_json(json.dumps(payload))
    previous = None
    if previous_z is not None:
        prior = canonical_sessions(date(2022, 12, 20), request.sessions[0].session_date)[-2]
        close_b = 100.0
        close_a = exp(
            request.snapshot.alpha
            + request.snapshot.beta * log(close_b)
            + request.snapshot.spread_mean
            + request.snapshot.spread_std * previous_z
        )
        previous = PreviousClose(
            session_date=prior[0],
            close_a=close_a,
            close_b=close_b,
            z=previous_z,
            snapshot_id=request.snapshot.snapshot_id,
        )
    model_a = None if a is None else _prediction(request, policy, "A", a)
    model_b = None if b is None else _prediction(request, policy, "B", b)
    schedule_id = _digest("synthetic-target-blind-agent-schedule-v1")
    controller = None
    if controller_status is not None and model_b is not None:
        reason: ReasonCode
        risk: Risk
        if controller_status == "CANDIDATE":
            reason, risk = "ALL_GATES_PASSED", "LOW"
        elif controller_status == "REVIEW":
            reason, risk = "MEDIUM_BREAK_RISK", "MEDIUM"
        elif controller_status == "NO TRADE":
            reason, risk = "HIGH_BREAK_RISK", "HIGH"
        else:
            reason = "AGENT_FAILURE" if scheduled else "INVESTIGATION_NOT_SCHEDULED"
            risk = "UNKNOWN"
        decision = ControllerDecision.model_validate(
            {
                "status": controller_status,
                "reason_codes": (reason,),
                "policy_version": policy.controller_policy_version,
                "model_b_probability": model_b.probability,
                "break_risk": risk,
            }
        )
        controller = StoredController(
            investigation_id=_digest(f"synthetic-investigation:{name}"),
            input_sha256=_digest(f"synthetic-agent-input:{name}"),
            event_id=request.event_id,
            pair_id=request.pair_id,
            information_cutoff=request.signal_at,
            snapshot_id=request.snapshot.snapshot_id,
            model_b_bundle_id=model_b.model_bundle_id,
            schedule_id=schedule_id,
            decision=decision,
        )
    state = LadderState.model_validate(
        {
            "event_id": request.event_id,
            "pair_id": request.pair_id,
            "signal_at": request.signal_at,
            "snapshot_id": request.snapshot.snapshot_id,
            "previous": previous,
            "pair_status": pair_status,
            "model_a": model_a,
            "model_b": model_b,
            "agent_scheduled": scheduled,
            "full_schedule_id": schedule_id if scheduled or controller is not None else None,
            "controller": controller,
            "sector": "SYNTHETIC",
            "source_coverage": "COMPLETE",
        }
    )
    return LadderEvent(state=state, request=request)


def fixture_ladder() -> tuple[
    tuple[LadderEvent, ...], LadderPolicy, ExecutionConfig, tuple[EvaluationLabel, ...]
]:
    """Inputs and separate invented labels for deterministic engineering checks."""
    policy = LadderPolicy(
        version="phase6-ladder-fixture-v1",
        population_id="synthetic-ladder-cases-v1",
        status="FIXTURE",
        candidate_threshold=0.65,
        model_a_bundle_id="synthetic-logistic-A-h20-v1",
        model_a_calibrator_id="synthetic-A-platt-v1",
        model_b_bundle_id="synthetic-logistic-B-both-h20-v1",
        model_b_calibrator_id="synthetic-B-both-platt-v1",
        controller_policy_version="phase5-fixture-v1",
        label_policy_version="synthetic-target-v1",
    )
    events = (
        _event("candidate", policy),
        _event("a-only", policy, b=0.4, controller_status="NO TRADE"),
        _event("b-only", policy, a=0.4),
        _event("watch", policy, pair_status="WATCH", controller_status="REVIEW"),
        _event("missing-a", policy, a=None),
        _event("missing-b", policy, b=None, scheduled=False, controller_status=None),
        _event("unscheduled", policy, scheduled=False, controller_status="ABSTAIN"),
        _event("review", policy, controller_status="REVIEW"),
        _event("abstain", policy, controller_status="ABSTAIN"),
        _event("unpriced", policy, unpriced=True),
        _event("not-fresh", policy, previous_z=2.2),
        _event("no-previous", policy, previous_z=None),
        _event("no-trade", policy, controller_status="NO TRADE"),
        _event("missing-controller", policy, controller_status=None),
    )
    label_values = (1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0)
    complete_end = canonical_sessions(date(2023, 1, 3), date(2023, 3, 15))[20][0]
    labels = tuple(
        EvaluationLabel.model_validate(
            {
                "event_id": event.state.event_id,
                "pair_id": event.state.pair_id,
                "signal_at": event.state.signal_at,
                "horizon_sessions": policy.horizon_sessions,
                "label_policy_version": policy.label_policy_version,
                "label_manifest_sha256": _digest("synthetic-ladder-labels-v1"),
                "complete_window_end": complete_end,
                "label_success": label,
            }
        )
        for event, label in zip(events, label_values, strict=True)
    )
    return events, policy, fixture_config(), labels

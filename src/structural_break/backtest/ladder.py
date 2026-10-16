"""Outcome-free five-rung selection over one shared counterfactual simulator.

The A/B models branch independently from historical ACTIVE eligibility. No
selection rule reads forward price bars, execution returns or evaluation labels.
Only synthetic inputs are supported until genuine capture adapters are accepted.
"""

import hashlib
from collections.abc import Sequence
from pathlib import Path

from structural_break.backtest.contracts import ExecutionConfig
from structural_break.backtest.ladder_contracts import (
    LadderEvent,
    LadderPolicy,
    LadderRow,
    Rung,
    RungSelection,
    SelectionReason,
    StoredPrediction,
)
from structural_break.backtest.simulator import sha256, simulate_pair_trade


def ladder_source_sha256() -> str:
    """Bind validation, selection and execution rules without platform line endings."""
    digest = hashlib.sha256()
    for name in ("contracts.py", "simulator.py", "ladder_contracts.py", "ladder.py"):
        source = (Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n")
        digest.update(name.encode("ascii") + b"\0" + source + b"\0")
    return digest.hexdigest()


def _selection(
    rung: Rung,
    disposition: str,
    *reasons: SelectionReason,
) -> RungSelection:
    return RungSelection.model_validate(
        {"rung": rung, "disposition": disposition, "reason_codes": reasons}
    )


def _base_gate(rung: Rung, parent: RungSelection) -> RungSelection:
    """Retain the underlying unavailable/withheld reason through later layers."""
    reason: SelectionReason = (
        "BASE_RULE_UNAVAILABLE" if not parent.available else "BASE_RULE_WITHHELD"
    )
    inherited = tuple(
        code
        for code in parent.reason_codes
        if code not in ("BASE_RULE_UNAVAILABLE", "BASE_RULE_WITHHELD")
    )
    return _selection(rung, parent.disposition, reason, *inherited)


def _check_prediction(
    prediction: StoredPrediction | None, policy: LadderPolicy, *, role: str
) -> None:
    if prediction is None:
        return
    expected = (
        ("A", policy.model_a_bundle_id, policy.model_a_calibrator_id)
        if role == "A"
        else (policy.model_b_variant, policy.model_b_bundle_id, policy.model_b_calibrator_id)
    )
    actual = (prediction.model_role, prediction.model_bundle_id, prediction.calibrator_id)
    if (
        actual != expected
        or prediction.model_family != policy.model_family
        or prediction.horizon_sessions != policy.horizon_sessions
    ):
        raise ValueError("Stored prediction does not match the declared ladder model policy")


def _raw_selection(event: LadderEvent, threshold: float) -> tuple[bool | None, RungSelection]:
    previous = event.state.previous
    if previous is None:
        return None, _selection("BASELINE_0", "UNAVAILABLE", "UNKNOWN_PREVIOUS_CLOSE")
    current = next(
        (
            row
            for row in event.request.prices
            if row.session_date == event.request.sessions[0].session_date
        ),
        None,
    )
    if current is None or current.close_a is None or current.close_b is None:
        return None, _selection("BASELINE_0", "UNAVAILABLE", "UNKNOWN_SIGNAL_CLOSE")
    fresh = abs(previous.z) < threshold <= abs(event.request.signal_z)
    return fresh, _selection(
        "BASELINE_0",
        "SELECTED" if fresh else "WITHHELD",
        "FRESH_CROSSING" if fresh else "NOT_FRESH",
    )


def _model_selection(
    rung: Rung, parent: RungSelection, prediction: StoredPrediction | None, threshold: float
) -> RungSelection:
    if not parent.selected:
        return _base_gate(rung, parent)
    if prediction is None:
        missing: SelectionReason = "MISSING_MODEL_A" if rung == "MODEL_A" else "MISSING_MODEL_B"
        return _selection(rung, "UNAVAILABLE", missing)
    passes = prediction.probability >= threshold
    reason: SelectionReason
    if rung == "MODEL_A":
        reason = "MODEL_A_SELECTED" if passes else "MODEL_A_BELOW_THRESHOLD"
    else:
        reason = "MODEL_B_SELECTED" if passes else "MODEL_B_BELOW_THRESHOLD"
    return _selection(rung, "SELECTED" if passes else "WITHHELD", reason)


def _check_policy(policy: LadderPolicy) -> None:
    if policy.status != "FIXTURE":
        raise ValueError("Ladder execution currently supports synthetic fixture policies only")
    if policy.candidate_threshold is None:
        raise ValueError("The matched Model A/B threshold must be explicitly declared")


def _check_event(event: LadderEvent, policy: LadderPolicy) -> None:
    if event.request.data_kind != "SYNTHETIC_FIXTURE":
        raise ValueError("Captured market inputs cannot use the synthetic ladder adapter")
    _check_prediction(event.state.model_a, policy, role="A")
    _check_prediction(event.state.model_b, policy, role="B")
    if (
        event.state.controller is not None
        and event.state.controller.decision.policy_version != policy.controller_policy_version
    ):
        raise ValueError("Stored controller policy must match the declared ladder policy")


def _select_validated_event(
    event: LadderEvent, policy: LadderPolicy
) -> tuple[bool | None, tuple[RungSelection, ...]]:
    assert policy.candidate_threshold is not None
    # The crossing threshold is a frozen rule, matching ExecutionConfig's exact 2.0.
    raw_fresh, baseline_0 = _raw_selection(event, 2.0)
    if not baseline_0.selected:
        baseline_1 = _base_gate("BASELINE_1", baseline_0)
    elif event.state.pair_status == "UNKNOWN":
        baseline_1 = _selection("BASELINE_1", "UNAVAILABLE", "PAIR_STATUS_UNKNOWN")
    elif event.state.pair_status != "ACTIVE":
        baseline_1 = _selection("BASELINE_1", "WITHHELD", "PAIR_NOT_ACTIVE")
    else:
        baseline_1 = _selection("BASELINE_1", "SELECTED", "PAIR_ACTIVE")
    model_a = _model_selection(
        "MODEL_A", baseline_1, event.state.model_a, policy.candidate_threshold
    )
    model_b = _model_selection(
        "MODEL_B", baseline_1, event.state.model_b, policy.candidate_threshold
    )
    if policy.full_system == "NOT_RUN":
        full = _selection("FULL_SYSTEM", "NOT_RUN", "CONTROLLER_GENERATION_NOT_ACCEPTED")
    elif not model_b.selected:
        full = _base_gate("FULL_SYSTEM", model_b)
    elif not event.state.agent_scheduled:
        full = _selection("FULL_SYSTEM", "UNAVAILABLE", "AGENT_UNSCHEDULED")
    elif event.state.controller is None:
        full = _selection("FULL_SYSTEM", "UNAVAILABLE", "MISSING_CONTROLLER")
    else:
        status = event.state.controller.decision.status
        reasons: dict[str, SelectionReason] = {
            "CANDIDATE": "CONTROLLER_CANDIDATE",
            "REVIEW": "CONTROLLER_REVIEW",
            "NO TRADE": "CONTROLLER_NO_TRADE",
            "ABSTAIN": "CONTROLLER_ABSTAIN",
        }
        full = _selection(
            "FULL_SYSTEM", "SELECTED" if status == "CANDIDATE" else "WITHHELD", reasons[status]
        )
    return raw_fresh, (baseline_0, baseline_1, model_a, model_b, full)


def select_ladder_event(
    event: LadderEvent, policy: LadderPolicy
) -> tuple[bool | None, tuple[RungSelection, ...]]:
    """Replay selection with no simulator, forward path inspection or label access."""
    _check_policy(policy)
    _check_event(event, policy)
    return _select_validated_event(event, policy)


def evaluate_ladder(
    events: Sequence[LadderEvent], policy: LadderPolicy, execution_config: ExecutionConfig
) -> tuple[LadderRow, ...]:
    """Preserve every row and run every fresh event exactly once, even if rejected.

    Forward bars are passed only to the simulator after selection. A failed fill
    does not retrospectively change model/controller selection or erase its row.
    """
    _check_policy(policy)
    if execution_config.mode != "FIXTURE" or execution_config.status != "DRAFT":
        raise ValueError("Ladder execution currently supports synthetic fixture policies only")
    if execution_config.horizon_sessions != policy.horizon_sessions:
        raise ValueError("Ladder and shared execution horizon must match")
    if len({event.state.event_id for event in events}) != len(events):
        raise ValueError("Every ladder input must have a unique event identity")
    # Validate the whole inventory before executing any price path.
    for event in events:
        _check_event(event, policy)
    rows: list[LadderRow] = []
    for event in events:
        raw_fresh, selections = _select_validated_event(event, policy)
        execution = simulate_pair_trade(event.request, execution_config) if raw_fresh else None
        rows.append(
            LadderRow(
                event_id=event.state.event_id,
                pair_id=event.state.pair_id,
                signal_at=event.state.signal_at,
                state_sha256=sha256(event.state),
                request_sha256=sha256(event.request),
                raw_fresh=raw_fresh,
                selections=selections,
                execution=execution,
            )
        )
    return tuple(rows)

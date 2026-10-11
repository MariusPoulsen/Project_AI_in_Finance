"""Deterministic Phase 5 gates; language models cannot authorize candidates."""

from structural_break.agents.contracts import (
    AgentInput,
    ReasonCode,
    Risk,
    ValidationReport,
    validate_citations,
)
from structural_break.agents.contracts import (
    AgentPolicy as AgentPolicy,
)
from structural_break.agents.contracts import (
    ControllerDecision as ControllerDecision,
)


def _result(
    event: AgentInput,
    policy: AgentPolicy,
    status: str,
    codes: tuple[ReasonCode, ...],
    risk: Risk = "UNKNOWN",
) -> ControllerDecision:
    return ControllerDecision.model_validate(
        {
            "status": status,
            "reason_codes": codes,
            "policy_version": policy.policy_version,
            "model_b_probability": event.quant.model_b_probability,
            "break_risk": risk,
        }
    )


def failure_decision(
    event: AgentInput, policy: AgentPolicy, code: ReasonCode = "AGENT_FAILURE"
) -> ControllerDecision:
    """Fail closed with a redacted, fixed reason; never persist exception text."""

    return _result(event, policy, "ABSTAIN", (code,))


def preflight(event: AgentInput, policy: AgentPolicy) -> ControllerDecision | None:
    """Skip LLM calls where an automatic candidate is already impossible.

    The returned record remains in the scheduling/decision denominator. A None
    result means the event can proceed to investigation, not that it is accepted.
    FIXTURE policies are allowed here for unit tests; the runner must reject them
    for a live provider.
    """

    if policy.status == "DRAFT":
        return failure_decision(event, policy, "POLICY_NOT_FROZEN")
    if policy.no_trade_probability is None or policy.candidate_probability is None:
        return failure_decision(event, policy, "POLICY_THRESHOLDS_MISSING")
    if not event.gates.market_data_ok:
        return failure_decision(event, policy, "MISSING_MARKET_DATA")
    if not event.gates.model_inputs_ok or event.quant.model_b_probability is None:
        return failure_decision(event, policy, "MISSING_MODEL_INPUT")
    if not event.gates.source_timestamps_ok:
        return failure_decision(event, policy, "UNRELIABLE_SOURCE_TIMESTAMP")
    if event.gates.source_coverage == "UNKNOWN":
        return failure_decision(event, policy, "UNKNOWN_SOURCE_COVERAGE")
    if event.pair_status == "UNKNOWN":
        return failure_decision(event, policy, "PAIR_NOT_ACTIVE")
    if event.pair_status == "RETIRED":
        return _result(event, policy, "NO TRADE", ("PAIR_RETIRED",))
    if not event.gates.liquidity_ok:
        return _result(event, policy, "NO TRADE", ("HARD_LIQUIDITY_FAILURE",))
    if not event.gates.implementation_ok:
        return _result(event, policy, "NO TRADE", ("HARD_IMPLEMENTATION_FAILURE",))
    probability = event.quant.model_b_probability
    if probability < policy.no_trade_probability:
        return _result(event, policy, "NO TRADE", ("LOW_MODEL_PROBABILITY",))
    if event.pair_status != "ACTIVE":
        return _result(event, policy, "REVIEW", ("PAIR_NOT_ACTIVE",))
    if probability < policy.candidate_probability:
        return _result(event, policy, "REVIEW", ("INTERMEDIATE_MODEL_PROBABILITY",))
    warnings: list[ReasonCode] = []
    if event.gates.source_coverage == "PARTIAL":
        warnings.append("PARTIAL_SOURCE_COVERAGE")
    if event.gates.market_stressed:
        warnings.append("MARKET_STRESS")
    if event.gates.soft_warning:
        warnings.append("SOFT_WARNING")
    if warnings:
        return _result(event, policy, "REVIEW", tuple(warnings))
    return None


def decide(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> ControllerDecision:
    """Apply policy to the immutable input and independently validated risk."""

    deterministic = preflight(event, policy)
    if deterministic is not None and deterministic.status != "REVIEW":
        return deterministic
    if validate_citations(event, (validation,)):
        return failure_decision(event, policy, "MECHANICAL_VALIDATION_FAILED")
    if (
        validation.validation_status == "FAIL"
        or validation.abstain_recommended
        or validation.invalid_claim_count > 0
    ):
        return failure_decision(event, policy, "VALIDATION_FAILED")
    if validation.source_completeness == "UNKNOWN":
        return failure_decision(event, policy, "UNKNOWN_SOURCE_COVERAGE")
    if validation.break_risk == "UNKNOWN":
        return failure_decision(event, policy, "UNKNOWN_BREAK_RISK")
    if validation.break_risk == "HIGH":
        return _result(event, policy, "NO TRADE", ("HIGH_BREAK_RISK",), "HIGH")
    if validation.high_materiality_one_sided_catalyst:
        return _result(
            event, policy, "NO TRADE", ("HIGH_ONE_SIDED_CATALYST",), validation.break_risk
        )
    warnings: list[ReasonCode] = []
    if any(
        catalyst.affected_leg in {"A", "B"}
        and catalyst.materiality == "HIGH"
        and catalyst.relationship_relevance == "DIRECT"
        for catalyst in event.catalysts
    ):
        # Mechanical grounding of extraction is not semantic confirmation. Until
        # the first slice supports explicit rejection adjudication, an existing
        # high one-sided signal cannot silently become a LOW-risk candidate.
        warnings.append("UNRESOLVED_CATALYST_RISK")
    if validation.break_risk == "MEDIUM":
        warnings.append("MEDIUM_BREAK_RISK")
    if validation.contradiction_flag:
        warnings.append("CONFLICTING_EVIDENCE")
    if validation.source_completeness == "PARTIAL":
        warnings.append("PARTIAL_SOURCE_COVERAGE")
    if validation.validation_status == "PASS_WITH_WARNINGS":
        warnings.append("SOFT_WARNING")
    if warnings:
        return _result(event, policy, "REVIEW", tuple(warnings), validation.break_risk)
    if deterministic is not None:
        return _result(event, policy, "REVIEW", deterministic.reason_codes, validation.break_risk)
    return _result(event, policy, "CANDIDATE", ("ALL_GATES_PASSED",), "LOW")

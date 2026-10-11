"""Adversarial source admission and deterministic controller precedence checks."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from structural_break.agents.contracts import (
    AdvocateReport,
    AgentInput,
    AgentPolicy,
    Citation,
    Claim,
    DataGates,
    Lineage,
    QuantReference,
    QuantState,
    SourceChunk,
    ToneState,
    ValidationReport,
    validate_citations,
)
from structural_break.decision.agent_policy import decide, failure_decision, preflight


@pytest.fixture
def event() -> AgentInput:
    text = "The company maintained its previously disclosed annual guidance."
    cutoff = datetime(2022, 3, 15, 20, tzinfo=UTC)
    return AgentInput(
        event_id="event-fixture-1",
        pair_id="AAA__BBB",
        event_timestamp=cutoff,
        leg_a_security_id="security-A",
        leg_b_security_id="security-B",
        pair_status="ACTIVE",
        quant=QuantState(
            model_b_probability=0.75,
            z_score=2.1,
            half_life_sessions=12.0,
            beta_drift=0.05,
            cointegration_pvalue=0.02,
        ),
        gates=DataGates(
            market_data_ok=True,
            model_inputs_ok=True,
            source_timestamps_ok=True,
            source_coverage="COMPLETE",
            liquidity_ok=True,
            implementation_ok=True,
        ),
        lineage=Lineage(
            registry_id="registry-fixture",
            model_bundle_id="B-fixture",
            model_version="B-both-logistic-v2",
            calibrator_version="calibrator-fixture",
            relationship_version="relationship-fixture",
            evidence_policy_version="sec-evidence-v1",
            source_manifest_sha256="a" * 64,
        ),
        evidence=(
            SourceChunk(
                chunk_id="chunk-A",
                leg="A",
                security_id="security-A",
                filing_id="filing-A",
                document_sha256="b" * 64,
                start_offset=10,
                end_offset=10 + len(text),
                source_timestamp=cutoff - timedelta(hours=2),
                text=text,
            ),
        ),
    )


@pytest.fixture
def policy() -> AgentPolicy:
    return AgentPolicy(
        policy_version="fixture-controller-v1",
        status="FIXTURE",
        no_trade_probability=0.45,
        candidate_probability=0.65,
    )


@pytest.fixture
def validation() -> ValidationReport:
    return ValidationReport(
        validation_status="PASS",
        source_completeness="COMPLETE",
        contradiction_flag=False,
        invalid_claim_count=0,
        break_risk="LOW",
        abstain_recommended=False,
        claims=(
            Claim(
                claim_id="validation-guidance",
                text="The selected filing maintains guidance.",
                kind="FACT",
                citations=(
                    Citation(chunk_id="chunk-A", leg="A", quote="maintained its previously"),
                ),
            ),
        ),
    )


def changed_event(event: AgentInput, **changes: Any) -> AgentInput:
    data = event.model_dump(mode="json")
    data.update(changes)
    return AgentInput.model_validate_json(json.dumps(data))


def changed_validation(validation: ValidationReport, **changes: Any) -> ValidationReport:
    data = validation.model_dump(mode="json")
    data.update(changes)
    return ValidationReport.model_validate_json(json.dumps(data))


def test_nested_inputs_cannot_mutate(event: AgentInput) -> None:
    with pytest.raises(ValidationError):
        event.quant.model_b_probability = 0.99  # type: ignore[misc]
    with pytest.raises(ValidationError):
        event.evidence[0].text = "replacement"  # type: ignore[misc]
    assert isinstance(event.evidence, tuple)
    assert AgentInput.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize("field", ["target", "success", "future_return", "outcome"])
def test_inputs_reject_outcomes(event: AgentInput, field: str) -> None:
    with pytest.raises(ValidationError):
        changed_event(event, **{field: 1})


@pytest.mark.parametrize("year", [2024, 2025, 2026])
def test_final_test_stays_locked(event: AgentInput, year: int) -> None:
    with pytest.raises(ValidationError, match="locked final-test"):
        changed_event(event, event_timestamp=f"{year}-03-15T20:00:00Z")


@pytest.mark.parametrize(
    "change",
    [
        {"source_timestamp": "2022-03-15T21:00:00Z"},
        {"source_timestamp": "2022-03-15T18:00:00"},
        {"security_id": "security-B"},
        {"end_offset": 999},
    ],
)
def test_sources_reject_bad_time_issuer_and_offsets(
    event: AgentInput, change: dict[str, Any]
) -> None:
    source = event.evidence[0].model_dump(mode="json")
    source.update(change)
    with pytest.raises(ValidationError):
        changed_event(event, evidence=[source])


def test_duplicate_sources_rejected(event: AgentInput) -> None:
    with pytest.raises(ValidationError, match="unique"):
        changed_event(event, evidence=[event.evidence[0].model_dump(mode="json")] * 2)


def test_none_catalyst_needs_complete_coverage(event: AgentInput) -> None:
    gates = event.gates.model_dump(mode="json")
    gates["source_coverage"] = "UNKNOWN"
    with pytest.raises(ValidationError, match="NONE is inadmissible"):
        changed_event(
            event,
            gates=gates,
            catalysts=[
                {
                    "event_type": "NONE",
                    "affected_leg": "NONE",
                    "direction": "UNKNOWN",
                    "materiality": "UNKNOWN",
                    "relationship_relevance": "NONE",
                    "citations": [],
                }
            ],
        )


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), -0.1, 1.1, True, "0.75"])
def test_model_probability_is_finite_strict_probability(probability: Any) -> None:
    with pytest.raises(ValidationError):
        QuantState(model_b_probability=probability)


def test_all_gates_are_required_for_candidate(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    assert preflight(event, policy) is None
    decision = decide(event, policy, validation)
    assert decision.status == "CANDIDATE"
    assert decision.reason_codes == ("ALL_GATES_PASSED",)
    assert decide(event, policy, validation) == decision


def test_draft_policy_and_missing_thresholds_fail_before_calls(event: AgentInput) -> None:
    for policy, code in (
        (AgentPolicy(policy_version="draft", status="DRAFT"), "POLICY_NOT_FROZEN"),
        (AgentPolicy(policy_version="unconfigured", status="FROZEN"), "POLICY_THRESHOLDS_MISSING"),
    ):
        result = preflight(event, policy)
        assert result is not None and result.status == "ABSTAIN"
        assert result.reason_codes == (code,)


@pytest.mark.parametrize(
    ("gate", "value", "status", "code"),
    [
        ("market_data_ok", False, "ABSTAIN", "MISSING_MARKET_DATA"),
        ("model_inputs_ok", False, "ABSTAIN", "MISSING_MODEL_INPUT"),
        ("source_timestamps_ok", False, "ABSTAIN", "UNRELIABLE_SOURCE_TIMESTAMP"),
        ("source_coverage", "UNKNOWN", "ABSTAIN", "UNKNOWN_SOURCE_COVERAGE"),
        ("liquidity_ok", False, "NO TRADE", "HARD_LIQUIDITY_FAILURE"),
        ("implementation_ok", False, "NO TRADE", "HARD_IMPLEMENTATION_FAILURE"),
        ("market_stressed", True, "REVIEW", "MARKET_STRESS"),
        ("source_coverage", "PARTIAL", "REVIEW", "PARTIAL_SOURCE_COVERAGE"),
        ("soft_warning", True, "REVIEW", "SOFT_WARNING"),
    ],
)
def test_preflight_gate_statuses(
    event: AgentInput, policy: AgentPolicy, gate: str, value: Any, status: str, code: str
) -> None:
    gates = event.gates.model_dump(mode="json")
    gates[gate] = value
    result = preflight(changed_event(event, gates=gates), policy)
    assert result is not None and result.status == status and result.reason_codes == (code,)


@pytest.mark.parametrize(
    ("pair_status", "expected"),
    [
        ("WATCH", "REVIEW"),
        ("RETIRED", "NO TRADE"),
        ("UNKNOWN", "ABSTAIN"),
    ],
)
def test_only_historically_active_pairs_can_be_candidates(
    event: AgentInput,
    policy: AgentPolicy,
    validation: ValidationReport,
    pair_status: str,
    expected: str,
) -> None:
    assert (
        decide(changed_event(event, pair_status=pair_status), policy, validation).status == expected
    )


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (0.449, "NO TRADE"),
        (0.45, "REVIEW"),
        (0.649, "REVIEW"),
        (0.65, "CANDIDATE"),
    ],
)
def test_probability_threshold_boundaries(
    event: AgentInput,
    policy: AgentPolicy,
    validation: ValidationReport,
    probability: float,
    expected: str,
) -> None:
    quant = event.quant.model_dump(mode="json")
    quant["model_b_probability"] = probability
    assert decide(changed_event(event, quant=quant), policy, validation).status == expected


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        ("LOW", "CANDIDATE"),
        ("MEDIUM", "REVIEW"),
        ("HIGH", "NO TRADE"),
        ("UNKNOWN", "ABSTAIN"),
    ],
)
def test_categorical_risk_gates(
    event: AgentInput,
    policy: AgentPolicy,
    validation: ValidationReport,
    risk: str,
    expected: str,
) -> None:
    assert decide(event, policy, changed_validation(validation, break_risk=risk)).status == expected


def test_source_failure_has_precedence_over_high_risk(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    gates = event.gates.model_dump(mode="json")
    gates["source_coverage"] = "UNKNOWN"
    assert (
        decide(
            changed_event(event, gates=gates),
            policy,
            changed_validation(validation, break_risk="HIGH"),
        ).status
        == "ABSTAIN"
    )


def test_optional_review_investigation_can_find_hard_veto(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    watch = changed_event(event, pair_status="WATCH")
    assert preflight(watch, policy).status == "REVIEW"  # type: ignore[union-attr]
    assert (
        decide(watch, policy, changed_validation(validation, break_risk="HIGH")).status
        == "NO TRADE"
    )


def test_high_one_sided_catalyst_cannot_be_diluted(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    result = decide(
        event, policy, changed_validation(validation, high_materiality_one_sided_catalyst=True)
    )
    assert result.status == "NO TRADE" and result.reason_codes == ("HIGH_ONE_SIDED_CATALYST",)


def test_conflicts_and_partial_semantic_coverage_require_review(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    result = decide(
        event,
        policy,
        changed_validation(
            validation,
            validation_status="PASS_WITH_WARNINGS",
            contradiction_flag=True,
            source_completeness="PARTIAL",
        ),
    )
    assert result.status == "REVIEW"
    assert "CONFLICTING_EVIDENCE" in result.reason_codes
    assert "PARTIAL_SOURCE_COVERAGE" in result.reason_codes


def test_validation_failure_never_becomes_candidate(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    invalid = changed_validation(validation, validation_status="FAIL", invalid_claim_count=1)
    assert decide(event, policy, invalid).status == "ABSTAIN"
    assert failure_decision(event, policy).reason_codes == ("AGENT_FAILURE",)


def test_grounding_checks_exact_sources_and_numeric_values(
    event: AgentInput, validation: ValidationReport
) -> None:
    assert validate_citations(event, (validation,)) == ()
    claims = (
        Claim(
            claim_id="invented",
            text="Invented chunk.",
            kind="FACT",
            citations=(Citation(chunk_id="nonexistent", leg="A", quote="maintained guidance"),),
        ),
        Claim(
            claim_id="wrong-leg",
            text="Wrong issuer.",
            kind="FACT",
            citations=(Citation(chunk_id="chunk-A", leg="B", quote="maintained its previously"),),
        ),
        Claim(
            claim_id="changed-quote",
            text="Altered quote.",
            kind="FACT",
            citations=(Citation(chunk_id="chunk-A", leg="A", quote="raised annual guidance"),),
        ),
        Claim(
            claim_id="changed-score",
            text="Altered score.",
            kind="INFERENCE",
            quant_refs=(QuantReference(field="model_b_probability", value=0.9),),
        ),
    )
    report = AdvocateReport(
        role="MEAN_REVERSION",
        stage="OPENING",
        thesis="A fixture case.",
        claims=claims,
        evidence_strength="LOW",
    )
    assert [issue.code for issue in validate_citations(event, (report,))] == [
        "UNKNOWN_CHUNK",
        "SOURCE_LEG_MISMATCH",
        "QUOTE_NOT_FOUND",
        "QUANT_VALUE_MISMATCH",
    ]


def test_unsupported_and_unauthorized_outputs_rejected() -> None:
    with pytest.raises(ValidationError, match="grounding"):
        Claim(claim_id="unsupported", text="Trade now.", kind="INFERENCE")
    with pytest.raises(ValidationError):
        AdvocateReport.model_validate_json(
            json.dumps(
                {
                    "role": "MEAN_REVERSION",
                    "stage": "OPENING",
                    "thesis": "A fixture case.",
                    "evidence_strength": "LOW",
                    "final_status": "CANDIDATE",
                }
            )
        )
    with pytest.raises(ValidationError, match="grounded validation"):
        ValidationReport(
            validation_status="PASS",
            source_completeness="COMPLETE",
            contradiction_flag=False,
            invalid_claim_count=0,
            break_risk="LOW",
            abstain_recommended=False,
        )


@pytest.fixture
def tone() -> ToneState:
    return ToneState(
        leg="A",
        security_id="security-A",
        status="PARTIAL",
        source_coverage="COMPLETE",
        model_name="ProsusAI/finbert",
        model_revision="4556d13015211d73dccd3fdd39d39232506f3e43",
        preprocessing_version="sec-sentence-quality-wordpiece-v2",
        weights_sha256="e15a7b5738df7f17553399b6d94c6e2ff69c89245d066e8e5d183f5803a554e3",
        positive=0.4,
        negative=0.1,
        neutral=0.5,
        net=0.3,
        token_coverage=0.6,
        raw_token_count=100,
        eligible_token_count=70,
        excluded_token_count=30,
        scored_token_count=60,
        budget_omitted_token_count=10,
        unknown_chunk_count=0,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"raw_token_count": 70},
        {"eligible_token_count": 60},
        {"token_coverage": 1.0},
        {"net": 0.9},
        {"negative": 0.4},
        {"positive": None},
        {"weights_sha256": "0" * 64},
        {"preprocessing_version": "legacy-v1"},
        {"model_revision": "0" * 40},
    ],
)
def test_tone_preserves_pinned_assets_and_full_denominators(
    tone: ToneState, changes: dict[str, Any]
) -> None:
    data = tone.model_dump(mode="json")
    data.update(changes)
    with pytest.raises(ValidationError):
        ToneState.model_validate_json(json.dumps(data))


def test_unknown_tone_stays_null_and_never_becomes_neutral(tone: ToneState) -> None:
    data = tone.model_dump(mode="json")
    data.update(
        status="UNKNOWN",
        positive=None,
        negative=None,
        neutral=None,
        net=None,
        token_coverage=0.0,
        scored_token_count=0,
        budget_omitted_token_count=70,
    )
    unknown = ToneState.model_validate_json(json.dumps(data))
    assert unknown.positive is None and unknown.neutral is None
    data["neutral"] = 1.0
    with pytest.raises(ValidationError, match="UNKNOWN tone"):
        ToneState.model_validate_json(json.dumps(data))


def test_tone_binds_issuer_and_grounded_numeric_references(
    event: AgentInput, tone: ToneState
) -> None:
    event_with_tone = changed_event(event, tones=[tone.model_dump(mode="json")])
    report = AdvocateReport(
        role="STRUCTURAL_BREAK",
        stage="OPENING",
        thesis="Tone is supporting context only.",
        evidence_strength="LOW",
        claims=(
            Claim(
                claim_id="tone-context",
                text="Pinned classifier reports positive tone 0.4.",
                kind="INFERENCE",
                quant_refs=(QuantReference(field="tone_a_positive", value=0.4),),
            ),
        ),
    )
    assert validate_citations(event_with_tone, (report,)) == ()
    assert validate_citations(event, (report,))[0].code == "QUANT_VALUE_MISMATCH"
    data = tone.model_dump(mode="json")
    data["security_id"] = "security-B"
    with pytest.raises(ValidationError, match="pair leg"):
        changed_event(event, tones=[data])
    with pytest.raises(ValidationError, match="one record per leg"):
        changed_event(event, tones=[tone.model_dump(mode="json")] * 2)


def test_bounded_evidence_does_not_silently_truncate(event: AgentInput) -> None:
    source = event.evidence[0].model_dump(mode="json")
    rows = [dict(source, chunk_id=f"source-{index}") for index in range(9)]
    with pytest.raises(ValidationError, match="eight-chunks-per-leg"):
        changed_event(event, evidence=rows)
    source.update(text="a" * 5000, start_offset=0, end_offset=5000)
    rows = [dict(source, chunk_id=f"source-{index}") for index in range(7)]
    with pytest.raises(ValidationError, match="32000-character"):
        changed_event(event, evidence=rows)


def test_missing_model_probability_abstains(event: AgentInput, policy: AgentPolicy) -> None:
    data = event.quant.model_dump(mode="json")
    data["model_b_probability"] = None
    result = preflight(changed_event(event, quant=data), policy)
    assert result is not None and result.reason_codes == ("MISSING_MODEL_INPUT",)


def test_unconfirmed_high_extraction_red_flag_cannot_become_low_risk_candidate(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    flagged = changed_event(
        event,
        catalysts=[
            {
                "event_type": "GUIDANCE",
                "affected_leg": "A",
                "direction": "NEGATIVE",
                "materiality": "HIGH",
                "relationship_relevance": "DIRECT",
                "citations": [
                    {
                        "chunk_id": "chunk-A",
                        "leg": "A",
                        "quote": "maintained its previously",
                    }
                ],
            }
        ],
    )
    assert preflight(flagged, policy) is None
    unresolved = decide(flagged, policy, validation)
    assert unresolved.status == "REVIEW"
    assert unresolved.reason_codes == ("UNRESOLVED_CATALYST_RISK",)
    confirmed = changed_validation(validation, high_materiality_one_sided_catalyst=True)
    assert decide(flagged, policy, confirmed).status == "NO TRADE"
    high_risk = changed_validation(validation, break_risk="HIGH")
    assert decide(flagged, policy, high_risk).reason_codes == ("HIGH_BREAK_RISK",)


def test_controller_rechecks_validator_grounding_when_called_directly(
    event: AgentInput, policy: AgentPolicy, validation: ValidationReport
) -> None:
    bad = changed_validation(
        validation,
        claims=[
            {
                "claim_id": "invented-validation-support",
                "text": "A purported risk justification.",
                "kind": "FACT",
                "citations": [
                    {
                        "chunk_id": "invented-chunk",
                        "leg": "A",
                        "quote": "maintained its previously",
                    }
                ],
            }
        ],
    )
    result = decide(event, policy, bad)
    assert result.status == "ABSTAIN"
    assert result.reason_codes == ("MECHANICAL_VALIDATION_FAILED",)

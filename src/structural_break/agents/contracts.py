"""Immutable, bounded development inputs and grounded Phase 5 agent reports.

These contracts deliberately have no target/outcome or final-status field in any
LLM-facing object. Citation existence/quotation checks are mechanical checks;
claim meaning still needs the separate semantic validator and human quality audit.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from math import isclose
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(min_length=1, max_length=1200)]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Probability = Annotated[float, Field(ge=0, le=1)]
Risk: TypeAlias = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
RiskCategory: TypeAlias = Risk
Coverage: TypeAlias = Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
AdvocateRole: TypeAlias = Literal["MEAN_REVERSION", "STRUCTURAL_BREAK"]
QuantField: TypeAlias = Literal[
    "model_b_probability",
    "z_score",
    "half_life_sessions",
    "beta_drift",
    "cointegration_pvalue",
    "tone_a_positive",
    "tone_a_negative",
    "tone_a_neutral",
    "tone_a_net",
    "tone_a_token_coverage",
    "tone_b_positive",
    "tone_b_negative",
    "tone_b_neutral",
    "tone_b_net",
    "tone_b_token_coverage",
]
ReasonCode: TypeAlias = Literal[
    "POLICY_NOT_FROZEN",
    "POLICY_THRESHOLDS_MISSING",
    "MISSING_MARKET_DATA",
    "MISSING_MODEL_INPUT",
    "UNRELIABLE_SOURCE_TIMESTAMP",
    "UNKNOWN_SOURCE_COVERAGE",
    "PAIR_RETIRED",
    "PAIR_NOT_ACTIVE",
    "HARD_LIQUIDITY_FAILURE",
    "HARD_IMPLEMENTATION_FAILURE",
    "UNKNOWN_LIQUIDITY_ELIGIBILITY",
    "UNKNOWN_IMPLEMENTATION_ELIGIBILITY",
    "LOW_MODEL_PROBABILITY",
    "INTERMEDIATE_MODEL_PROBABILITY",
    "VALIDATION_FAILED",
    "AGENT_FAILURE",
    "INVESTIGATION_NOT_SCHEDULED",
    "INVESTIGATION_BUDGET_EXHAUSTED",
    "MECHANICAL_VALIDATION_FAILED",
    "UNKNOWN_BREAK_RISK",
    "HIGH_BREAK_RISK",
    "HIGH_ONE_SIDED_CATALYST",
    "UNRESOLVED_CATALYST_RISK",
    "MEDIUM_BREAK_RISK",
    "CONFLICTING_EVIDENCE",
    "PARTIAL_SOURCE_COVERAGE",
    "MARKET_STRESS",
    "SOFT_WARNING",
    "ALL_GATES_PASSED",
]


class FrozenModel(BaseModel):
    """Strict JSON validation plus tuple collections prevent mutation below root."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class QuantState(FrozenModel):
    model_b_probability: Probability | None
    z_score: float | None = None
    half_life_sessions: Annotated[float, Field(gt=0)] | None = None
    beta_drift: Annotated[float, Field(ge=0)] | None = None
    cointegration_pvalue: Probability | None = None


class DataGates(FrozenModel):
    market_data_ok: bool
    model_inputs_ok: bool
    source_timestamps_ok: bool
    source_coverage: Coverage
    liquidity_ok: bool | None
    implementation_ok: bool | None
    market_stressed: bool = False
    soft_warning: bool = False


class SourceChunk(FrozenModel):
    chunk_id: Identifier
    leg: Literal["A", "B"]
    security_id: Identifier
    filing_id: Identifier
    document_sha256: SHA256
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(gt=0)]
    source_timestamp: datetime
    text: Annotated[str, Field(min_length=1, max_length=8000)]

    @model_validator(mode="after")
    def exact_span_and_clock(self) -> Self:
        if self.source_timestamp.utcoffset() is None:
            raise ValueError("Source timestamp must have an explicit timezone")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("Source offsets must bind the exact stored text span")
        return self


class Lineage(FrozenModel):
    registry_id: Identifier
    model_bundle_id: Identifier
    model_version: Identifier
    calibrator_version: Identifier
    relationship_version: Identifier
    evidence_policy_version: Identifier
    source_manifest_sha256: SHA256


class Citation(FrozenModel):
    chunk_id: Identifier
    leg: Literal["A", "B"]
    quote: Annotated[str, Field(min_length=8, max_length=1600)]


class CatalystState(FrozenModel):
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
    ]
    affected_leg: Literal["A", "B", "BOTH", "NONE", "UNKNOWN"]
    direction: Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"]
    materiality: Risk
    relationship_relevance: Literal["DIRECT", "INDIRECT", "NONE", "UNKNOWN"]
    citations: tuple[Citation, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def supported_categories(self) -> Self:
        if self.event_type == "UNKNOWN":
            if self.citations or any(
                value != "UNKNOWN"
                for value in (
                    self.affected_leg,
                    self.direction,
                    self.materiality,
                    self.relationship_relevance,
                )
            ):
                raise ValueError("UNKNOWN catalysts cannot invent properties or citations")
        elif self.event_type == "NONE":
            if (
                self.citations
                or self.affected_leg != "NONE"
                or self.relationship_relevance != "NONE"
                or self.direction != "UNKNOWN"
                or self.materiality != "UNKNOWN"
            ):
                raise ValueError("NONE requires a supported absence extraction")
        elif self.affected_leg in {"NONE", "UNKNOWN"} or not self.citations:
            raise ValueError("A catalyst requires an affected leg and source citations")
        else:
            expected_legs = {"A", "B"} if self.affected_leg == "BOTH" else {self.affected_leg}
            if {citation.leg for citation in self.citations} != expected_legs:
                raise ValueError("Catalyst citations must cover exactly the claimed affected legs")
        return self


class ToneState(FrozenModel):
    """Provided pinned FinBERT scores, with full raw/excluded/unscored denominators."""

    leg: Literal["A", "B"]
    security_id: Identifier
    status: Literal["SUCCESS", "PARTIAL", "UNKNOWN"]
    source_coverage: Coverage
    model_name: Literal["ProsusAI/finbert"]
    model_revision: Literal["4556d13015211d73dccd3fdd39d39232506f3e43"]
    preprocessing_version: Literal["sec-sentence-quality-wordpiece-v2"]
    weights_sha256: Literal["e15a7b5738df7f17553399b6d94c6e2ff69c89245d066e8e5d183f5803a554e3"]
    positive: Probability | None
    negative: Probability | None
    neutral: Probability | None
    net: Annotated[float, Field(ge=-1, le=1)] | None
    token_coverage: Probability
    raw_token_count: Annotated[int, Field(ge=0)]
    eligible_token_count: Annotated[int, Field(ge=0)]
    excluded_token_count: Annotated[int, Field(ge=0)]
    scored_token_count: Annotated[int, Field(ge=0)]
    budget_omitted_token_count: Annotated[int, Field(ge=0)]
    unknown_chunk_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def coherent_coverage(self) -> Self:
        if self.raw_token_count != self.eligible_token_count + self.excluded_token_count:
            raise ValueError("FinBERT raw denominator must retain eligible and excluded tokens")
        if self.eligible_token_count != self.scored_token_count + self.budget_omitted_token_count:
            raise ValueError("FinBERT eligible denominator must retain unscored budget omissions")
        expected = self.scored_token_count / self.raw_token_count if self.raw_token_count else 0.0
        if not isclose(self.token_coverage, expected, abs_tol=1e-12):
            raise ValueError("FinBERT coverage differs from its full raw denominator")
        probabilities = (self.positive, self.negative, self.neutral)
        if self.status == "UNKNOWN":
            if any(score is not None for score in (*probabilities, self.net)):
                raise ValueError("UNKNOWN tone must not become neutral or a scored estimate")
            if self.scored_token_count:
                raise ValueError("UNKNOWN tone cannot have scored tokens")
        else:
            if any(score is None for score in probabilities) or self.net is None:
                raise ValueError("Known tone requires the full class probability vector")
            if not self.scored_token_count:
                raise ValueError("Known tone requires scored tokens")
            assert self.positive is not None and self.negative is not None
            assert self.neutral is not None
            if not isclose(self.positive + self.negative + self.neutral, 1.0, abs_tol=1e-6):
                raise ValueError("FinBERT class probabilities must sum to one")
            if not isclose(self.net, self.positive - self.negative, abs_tol=1e-12):
                raise ValueError("FinBERT net must preserve supplied positive-minus-negative score")
        return self


class AgentInput(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    event_timestamp: datetime
    leg_a_security_id: Identifier
    leg_b_security_id: Identifier
    pair_status: Literal["ACTIVE", "WATCH", "RETIRED", "UNKNOWN"]
    quant: QuantState
    gates: DataGates
    lineage: Lineage
    evidence: tuple[SourceChunk, ...] = Field(default=(), max_length=16)
    catalysts: tuple[CatalystState, ...] = Field(default=(), max_length=16)
    tones: tuple[ToneState, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def admissible_development_sources(self) -> Self:
        if self.event_timestamp.utcoffset() is None:
            raise ValueError("Event timestamp must have an explicit timezone")
        if self.event_timestamp.astimezone(UTC).year >= 2024:
            raise ValueError("Phase 5 development inputs cannot open the locked final-test period")
        if self.leg_a_security_id == self.leg_b_security_id:
            raise ValueError("Pair securities must be distinct")
        if len({source.chunk_id for source in self.evidence}) != len(self.evidence):
            raise ValueError("Source chunk identifiers must be unique")
        if sum(len(source.text) for source in self.evidence) > 32000:
            raise ValueError("Evidence exceeds the frozen 32000-character pack bound")
        if any(sum(source.leg == leg for source in self.evidence) > 8 for leg in ("A", "B")):
            raise ValueError("Evidence exceeds the frozen eight-chunks-per-leg bound")
        for source in self.evidence:
            security = self.leg_a_security_id if source.leg == "A" else self.leg_b_security_id
            if source.security_id != security:
                raise ValueError("Source security does not match its pair leg")
            if source.source_timestamp > self.event_timestamp:
                raise ValueError("Source was unavailable at the event cutoff")
        for catalyst in self.catalysts:
            if catalyst.event_type == "NONE" and self.gates.source_coverage != "COMPLETE":
                raise ValueError("NONE is inadmissible when selected-source coverage is incomplete")
            for citation in catalyst.citations:
                if _citation_issue(self, citation) is not None:
                    raise ValueError("Stored catalyst has an invalid source citation")
        if len({tone.leg for tone in self.tones}) != len(self.tones):
            raise ValueError("FinBERT tone must have at most one record per leg")
        for tone in self.tones:
            security = self.leg_a_security_id if tone.leg == "A" else self.leg_b_security_id
            if tone.security_id != security:
                raise ValueError("FinBERT security does not match its pair leg")
        return self


class QuantReference(FrozenModel):
    field: QuantField
    value: float


class Claim(FrozenModel):
    claim_id: Identifier
    text: ShortText
    kind: Literal["FACT", "INFERENCE"]
    citations: tuple[Citation, ...] = Field(default=(), max_length=8)
    quant_refs: tuple[QuantReference, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def grounded(self) -> Self:
        if not self.citations and not self.quant_refs:
            raise ValueError("Facts and inferences require source or quantitative grounding")
        if len({ref.field for ref in self.quant_refs}) != len(self.quant_refs):
            raise ValueError("Quantitative references must have distinct fields")
        return self


class AdvocateReport(FrozenModel):
    role: AdvocateRole
    stage: Literal["OPENING", "REBUTTAL"]
    thesis: ShortText
    claims: tuple[Claim, ...] = Field(default=(), max_length=12)
    counterevidence: tuple[Claim, ...] = Field(default=(), max_length=8)
    uncertainties: tuple[ShortText, ...] = Field(default=(), max_length=8)
    evidence_strength: Risk


class SynthesisReport(FrozenModel):
    summary: ShortText
    proposed_break_risk: Risk
    claims: tuple[Claim, ...] = Field(default=(), max_length=12)
    unresolved_conflicts: tuple[ShortText, ...] = Field(default=(), max_length=8)
    uncertainties: tuple[ShortText, ...] = Field(default=(), max_length=8)


class ValidationReport(FrozenModel):
    validation_status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    source_completeness: Coverage
    contradiction_flag: bool
    invalid_claim_count: Annotated[int, Field(ge=0, le=1000)]
    break_risk: Risk
    abstain_recommended: bool
    high_materiality_one_sided_catalyst: bool = False
    reason_codes: tuple[ReasonCode, ...] = Field(default=(), max_length=16)
    claims: tuple[Claim, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def grounded_risk_assessment(self) -> Self:
        if self.validation_status != "FAIL" and self.break_risk != "UNKNOWN" and not self.claims:
            raise ValueError("Known semantic risk assessments require grounded validation claims")
        if self.validation_status == "PASS" and (
            self.invalid_claim_count
            or self.abstain_recommended
            or self.source_completeness != "COMPLETE"
            or self.contradiction_flag
        ):
            raise ValueError("PASS cannot hide failures or source/contradiction warnings")
        return self


class AgentPolicy(FrozenModel):
    policy_version: Identifier
    status: Literal["DRAFT", "FROZEN", "FIXTURE"]
    no_trade_probability: Probability | None = None
    candidate_probability: Probability | None = None

    @model_validator(mode="after")
    def ordered_thresholds(self) -> Self:
        low, high = self.no_trade_probability, self.candidate_probability
        if low is not None and high is not None and low >= high:
            raise ValueError("The review interval must be nonempty")
        return self


class ControllerDecision(FrozenModel):
    status: Literal["CANDIDATE", "REVIEW", "NO TRADE", "ABSTAIN"]
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=16)
    policy_version: Identifier
    model_b_probability: Probability | None
    break_risk: Risk


class MechanicalIssue(FrozenModel):
    claim_id: Identifier
    code: Literal[
        "UNKNOWN_CHUNK",
        "SOURCE_LEG_MISMATCH",
        "QUOTE_NOT_FOUND",
        "FUTURE_SOURCE",
        "UNKNOWN_QUANT_FIELD",
        "QUANT_VALUE_MISMATCH",
        "DUPLICATE_CLAIM_ID",
    ]


def _citation_issue(event: AgentInput, citation: Citation) -> str | None:
    source = next((row for row in event.evidence if row.chunk_id == citation.chunk_id), None)
    if source is None:
        return "UNKNOWN_CHUNK"
    if source.leg != citation.leg:
        return "SOURCE_LEG_MISMATCH"
    if source.source_timestamp > event.event_timestamp:
        return "FUTURE_SOURCE"
    if citation.quote not in source.text:
        return "QUOTE_NOT_FOUND"
    return None


Report: TypeAlias = AdvocateReport | SynthesisReport | ValidationReport


def validate_citations(event: AgentInput, reports: Iterable[Report]) -> tuple[MechanicalIssue, ...]:
    """Reject unverifiable quotations and changed numeric inputs, without judging meaning."""

    issues: list[MechanicalIssue] = []
    for report in reports:
        claims = report.claims
        if isinstance(report, AdvocateReport):
            claims += report.counterevidence
        seen: set[str] = set()
        for claim in claims:
            if claim.claim_id in seen:
                issues.append(MechanicalIssue(claim_id=claim.claim_id, code="DUPLICATE_CLAIM_ID"))
            seen.add(claim.claim_id)
            for citation in claim.citations:
                reason = _citation_issue(event, citation)
                if reason is not None:
                    issues.append(
                        MechanicalIssue.model_validate(
                            {
                                "claim_id": claim.claim_id,
                                "code": reason,
                            }
                        )
                    )
            for reference in claim.quant_refs:
                if reference.field.startswith("tone_"):
                    _, leg, field = reference.field.split("_", maxsplit=2)
                    tone = next((row for row in event.tones if row.leg.lower() == leg), None)
                    expected = getattr(tone, field) if tone is not None else None
                else:
                    expected = getattr(event.quant, reference.field)
                if expected is None or reference.value != expected:
                    issues.append(
                        MechanicalIssue(
                            claim_id=claim.claim_id,
                            code="QUANT_VALUE_MISMATCH",
                        )
                    )
    return tuple(issues)

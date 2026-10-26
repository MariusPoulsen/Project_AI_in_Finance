import hashlib
import json
from datetime import UTC, datetime

import pytest

from structural_break.agents import debate as dv
from structural_break.agents.contracts import (
    AgentInput,
    DataGates,
    Lineage,
    QuantState,
    SourceChunk,
)
from structural_break.intelligence import catalysts as cv

TEXT_A = "Company A entered into a merger agreement with an unrelated buyer. The board approved the deal."
TEXT_B = "Company B declared its regular quarterly dividend. No other matters were reported."


def _chunk(leg: str, text: str) -> SourceChunk:
    return SourceChunk(
        chunk_id=f"chunk_{leg}",
        leg=leg,  # type: ignore[arg-type]
        security_id=f"US:{leg}X",
        filing_id=f"0000-{leg}",
        document_sha256=hashlib.sha256(text.encode()).hexdigest(),
        start_offset=0,
        end_offset=len(text),
        source_timestamp=datetime(2015, 3, 2, 14, tzinfo=UTC),
        text=text,
    )


def _case(coverage: str = "COMPLETE") -> dv.Case:
    event = AgentInput(
        event_id="evt_1",
        pair_id="pair_1",
        event_timestamp=datetime(2015, 3, 3, 21, tzinfo=UTC),
        leg_a_security_id="US:AX",
        leg_b_security_id="US:BX",
        pair_status="ACTIVE",
        quant=QuantState(model_b_probability=0.2, z_score=2.3, half_life_sessions=12.0),
        gates=DataGates(
            market_data_ok=True,
            model_inputs_ok=True,
            source_timestamps_ok=True,
            source_coverage=coverage,  # type: ignore[arg-type]
            liquidity_ok=True,
            implementation_ok=True,
        ),
        lineage=Lineage(
            registry_id="r",
            model_bundle_id="m",
            model_version="v",
            calibrator_version="c",
            relationship_version="rel",
            evidence_policy_version="e",
            source_manifest_sha256="0" * 64,
        ),
        evidence=(_chunk("A", TEXT_A), _chunk("B", TEXT_B)),
    )
    context = {
        "sub_industry": "widgets",
        "rationale": "same customers",
        "legs": {
            leg: {"abnormal_return": "+1.0 %", "news": "8-K filed", "tone": "+0.10"} for leg in "AB"
        },
        "chunks": {"chunk_A": "8-K Item 1.01", "chunk_B": "8-K Item 8.01"},
    }
    return dv.Case(event, context)


def _claim(cites=("A1.1",), quant=()) -> dict:
    return {"text": "The merger is one-sided.", "kind": "FACT", "cites": list(cites), "quant": list(quant)}


def _answer(role: str, risk: str) -> dict:
    if role in dv.OPENINGS + dv.REBUTTALS:
        return {
            "thesis": "One-sided merger news.",
            "claims": [_claim(), _claim(cites=(), quant=("z_score",))],
            "counterevidence": [_claim(cites=("B1.1",))],
            "uncertainties": [],
            "evidence_strength": "MEDIUM",
        }
    if role == "synthesis":
        return {"summary": "A merger on A only.", "proposed_break_risk": risk, "claims": [_claim()]}
    return {
        "validation_status": "PASS",
        "source_completeness": "COMPLETE",
        "contradiction_flag": False,
        "invalid_claim_count": 0,
        "break_risk": risk,
        "abstain_recommended": False,
        "high_materiality_one_sided_catalyst": risk == "HIGH",
        "claims": [_claim()],
    }


class Script:
    """Fake HTTP transport answering by role; ``overrides[role]`` is a list of texts."""

    def __init__(self, risk: str = "LOW", overrides: dict | None = None) -> None:
        self.risk, self.overrides, self.calls = risk, overrides or {}, []

    def __call__(self, url, payload, headers, timeout):
        prompt = payload["contents"][0]["parts"][0]["text"]
        role = prompt.splitlines()[0].split("| ")[1]
        self.calls.append((url.split("/")[-1].split(":")[0], role))
        queued = self.overrides.get(role)
        if queued:
            item = queued.pop(0)
            if isinstance(item, int):
                return item, None
            text = item
        else:
            text = json.dumps(_answer(role, self.risk))
        body = {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": len(prompt) // 4, "candidatesTokenCount": 50},
        }
        return 200, body


def _clients(script: Script, journal=None) -> dict:
    guard = dv.Guard(journal, {}, transport=script, sleep=lambda s: None)
    big = dict.fromkeys((dv.ADVOCATE_MODEL, dv.SYNTHESIS_MODEL, dv.VALIDATION_MODEL), 10**9)
    clients = dv.make_clients(lambda: "test-key", guard, token_budgets=big)
    for client in clients.values():
        client.sleep = lambda s: None
    return clients


def test_mask_text_hides_names_and_tickers() -> None:
    companies = {"A": ("Union Pacific Corporation", "UNP"), "B": ("CSX CORP", "CSX")}
    text = "Union Pacific Corp (NYSE: UNP) and CSX said UNP results beat. Union Pacific grew."
    masked = dv.mask_text(text, companies)
    assert "Union" not in masked and "UNP" not in masked and "CSX" not in masked
    assert masked.count("Company A") == 4 and "Company B" in masked


def test_resolve_maps_sentence_ids_to_exact_quotes_and_rejects_bad_refs() -> None:
    case = _case()
    report = dv.resolve("structural_break_opening", _answer("structural_break_opening", "HIGH"), case)
    assert report.claims[0].citations[0].quote == "Company A entered into a merger agreement with an unrelated buyer."
    assert report.claims[1].quant_refs[0].value == 2.3
    bad = _answer("structural_break_opening", "HIGH") | {"claims": [_claim(cites=("A9.9",))]}
    with pytest.raises(ValueError, match="Unknown sentence ID"):
        dv.resolve("structural_break_opening", bad, case)
    with pytest.raises(ValueError):  # a claim needs a citation or a quantitative field
        dv.resolve("structural_break_opening", bad | {"claims": [_claim(cites=())]}, case)


def test_analyst_context_is_labelled_zero_and_citable() -> None:
    base = _case()
    text = "Company A's 1-day abnormal return at the signal was -6.9 %.\nCompany A's recent 8-K news was M&A."
    context = SourceChunk(
        chunk_id="context:evt_1:A",
        leg="A",
        security_id="US:AX",
        filing_id=dv.CONTEXT_FILING,
        document_sha256=hashlib.sha256(text.encode()).hexdigest(),
        start_offset=0,
        end_offset=len(text),
        source_timestamp=base.event.event_timestamp,
        text=text,
    )
    case = dv.Case(base.event.model_copy(update={"evidence": (context, *base.event.evidence)}), base.context)
    prompt = dv.build_prompt("mean_reversion_opening", case, {})
    assert "[A0] Company A | analyst context" in prompt and "(A1.1) Company A entered" in prompt
    report = dv.resolve("structural_break_opening", _answer("structural_break_opening", "LOW") | {"claims": [_claim(cites=("A0.1",))]}, case)
    assert report.claims[0].citations[0].quote.endswith("-6.9 %.")


def test_prompt_shows_numbered_sentences_and_no_outcomes() -> None:
    prompt = dv.build_prompt("mean_reversion_opening", _case(), {})
    assert "(A1.1) Company A entered into a merger agreement" in prompt
    assert "revert_success" not in prompt
    with pytest.raises(ValueError):
        dv.build_prompt("synthesis", _case(), {})  # missing predecessors


def test_processing_order_is_deterministic() -> None:
    assert cv.processing_order("evt_1") == cv.processing_order("evt_1")

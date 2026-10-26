import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from structural_break.agents import debate as dv
from structural_break.agents.budgets import BudgetPolicy, DurableAttemptJournal, ModelCap
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


@pytest.mark.parametrize(("risk", "status"), [("LOW", "CANDIDATE"), ("HIGH", "NO TRADE"), ("MEDIUM", "REVIEW")])
def test_full_debate_reaches_the_controller(tmp_path: Path, risk: str, status: str) -> None:
    script = Script(risk)
    case = _case()
    result = dv.run_debate(case, _clients(script), tmp_path)
    assert result["decision"]["status"] == status
    assert [model for model, _ in script.calls].count(dv.ADVOCATE_MODEL) == 4
    assert (dv.SYNTHESIS_MODEL, "synthesis") in script.calls
    assert (dv.VALIDATION_MODEL, "validation") in script.calls
    assert dv.verify_result(result, case).status == status
    # Rerunning replays the role cache without any provider call.
    again = dv.run_debate(case, _clients(Script("HIGH")), tmp_path)
    assert again["decision"] == result["decision"]


def test_one_correction_then_valid(tmp_path: Path) -> None:
    script = Script("LOW", {"validation": ['{"break_risk": "LOW"}']})
    result = dv.run_debate(_case(), _clients(script), tmp_path)
    validation = result["stages"][-1]
    assert validation["status"] == "VALID" and len(validation["rejected"]) == 1
    assert result["decision"]["status"] == "CANDIDATE"


def test_failed_role_abstains_and_skips_downstream(tmp_path: Path) -> None:
    bad = "not json"
    script = Script("LOW", {"mean_reversion_opening": [bad] * (dv.CORRECTIONS + 1)})
    result = dv.run_debate(_case(), _clients(script), tmp_path)
    assert result["decision"]["status"] == "ABSTAIN"
    assert result["decision"]["reason_codes"] == ["AGENT_FAILURE"]
    assert result["stages"][2]["status"] == "SKIPPED"
    assert all(role in dv.OPENINGS for _, role in script.calls)


def test_daily_quota_pauses_instead_of_failing(tmp_path: Path) -> None:
    class Daily(Script):
        def __call__(self, url, payload, headers, timeout):
            if dv.SYNTHESIS_MODEL in url:
                body = {"error": {"details": [{"violations": [{"quotaId": "RequestsPerDay-FreeTier"}]}]}}
                return 429, body
            return super().__call__(url, payload, headers, timeout)

    with pytest.raises(dv.PauseRequired):
        dv.run_debate(_case(), _clients(Daily()), tmp_path)
    # Openings and rebuttals were cached, so the resumed event does not resend them.
    script = Script("LOW")
    dv.run_debate(_case(), _clients(script), tmp_path)
    assert [role for _, role in script.calls] == ["synthesis", "validation"]


def test_unknown_coverage_never_calls_a_model(tmp_path: Path) -> None:
    script = Script()
    result = dv.run_debate(_case("UNKNOWN"), _clients(script), tmp_path)
    assert result["decision"]["status"] == "ABSTAIN" and not script.calls


def test_guard_charges_the_durable_journal_before_each_attempt(tmp_path: Path) -> None:
    policy = BudgetPolicy(
        allocation_id="test",
        global_cap=100,
        model_caps=tuple(
            ModelCap(model=m, total=100, daily=100)
            for m in (dv.ADVOCATE_MODEL, dv.SYNTHESIS_MODEL, dv.VALIDATION_MODEL)
        ),
    )
    with DurableAttemptJournal(tmp_path / "journal", policy) as journal:
        script = Script("LOW", {"structural_break_opening": [500]})
        dv.run_debate(_case(), _clients(script, journal), tmp_path / "roles")
        counts = journal.counts["by_model"]
    # Six roles plus one server-error retry, every attempt charged.
    assert sum(counts.values()) == 7 and counts[dv.ADVOCATE_MODEL] == 5


def test_daily_cap_in_journal_pauses(tmp_path: Path) -> None:
    policy = BudgetPolicy(
        allocation_id="test",
        global_cap=100,
        model_caps=(
            ModelCap(model=dv.ADVOCATE_MODEL, total=100, daily=100),
            ModelCap(model=dv.SYNTHESIS_MODEL, total=100, daily=0),
            ModelCap(model=dv.VALIDATION_MODEL, total=100, daily=100),
        ),
    )
    with DurableAttemptJournal(tmp_path / "journal", policy) as journal:
        with pytest.raises(dv.PauseRequired):
            dv.run_debate(_case(), _clients(Script(), journal), tmp_path / "roles")


def test_batch_runner_writes_results_and_resumes(tmp_path: Path) -> None:
    import pandas as pd

    from structural_break.agents import debate_runner as pa

    case = _case()
    dv.cv_write(tmp_path / "cases" / "evt_1.json", case.to_json())
    pd.DataFrame(
        [{"event_id": "evt_1", "year": 2015, "status": "DEBATE"}, {"event_id": "evt_2", "year": 2015, "status": "NO_RECENT_NEWS"}]
    ).to_parquet(tmp_path / "inventory.parquet")
    counts = pa.run(tmp_path, clients=_clients(Script("HIGH")), say=lambda m: None, passes=0)
    assert counts == {"NO TRADE": 1}
    assert pa.load_result(tmp_path, "evt_1")["decision"]["status"] == "NO TRADE"
    assert pa.run(tmp_path, clients=_clients(Script()), say=lambda m: None, passes=0) == {}
    table = pa.decisions(tmp_path)
    assert dict(zip(table.event_id, table.status)) == {"evt_1": "NO TRADE", "evt_2": "NOT_DEBATED"}


def test_policy_is_frozen_and_admits_selected_candidates() -> None:
    assert dv.POLICY.status == "FROZEN"
    assert cv.processing_order("evt_1") == cv.processing_order("evt_1")

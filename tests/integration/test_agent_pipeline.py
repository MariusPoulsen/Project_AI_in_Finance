"""Offline graph barriers, authorization, failure containment and immutable replay."""

import json
import threading
from pathlib import Path

import pytest

from structural_break.agents.contracts import AgentInput, AgentPolicy
from structural_break.agents.pipeline import ROLES, canonical_json, digest, run_investigation
from structural_break.agents.providers import ScriptedProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/phase5"


def fixtures():
    event = AgentInput.model_validate_json((FIXTURES / "input.json").read_text())
    policy = AgentPolicy.model_validate_json((FIXTURES / "policy.json").read_text())
    responses = json.loads((FIXTURES / "responses.json").read_text())
    return event, policy, responses


def changed(model, **changes):
    payload = model.model_dump(mode="json")
    payload.update(changes)
    return type(model).model_validate_json(json.dumps(payload))


def test_parallel_openings_and_bounded_one_round_order(tmp_path):
    event, policy, responses = fixtures()
    before = event.model_dump_json()
    barrier = threading.Barrier(2)
    prompts = {}

    class CaptureProvider(ScriptedProvider):
        def generate(self, role, prompt, output_schema):
            prompts[role] = prompt
            if role.endswith("opening"):
                barrier.wait(timeout=10)
            return super().generate(role, prompt, output_schema)

    provider = CaptureProvider(responses)
    result = run_investigation(event, policy, provider, tmp_path)
    assert result.decision.status == "CANDIDATE"
    assert provider.calls == 6
    assert len(result.stages) == 6
    assert tuple(stage.role for stage in result.stages) == ROLES
    assert event.model_dump_json() == before
    for role in ROLES[:2]:
        assert "structural_break_opening-source" not in prompts[role]
        assert "mean_reversion_opening-source" not in prompts[role]
    for role in ROLES[2:4]:
        assert "mean_reversion_opening-source" in prompts[role]
        assert "structural_break_opening-source" in prompts[role]
        assert "structural_break_rebuttal-source" not in prompts[role]
        assert "mean_reversion_rebuttal-source" not in prompts[role]
    assert "mean_reversion_rebuttal-source" in prompts["synthesis"]
    assert "structural_break_rebuttal-source" in prompts["synthesis"]
    assert "synthesis-source" in prompts["validation"]


def test_terminal_and_role_cache_replay_without_calls(tmp_path):
    event, policy, responses = fixtures()
    first = run_investigation(event, policy, ScriptedProvider(responses), tmp_path)
    replay_provider = ScriptedProvider(responses)
    replay = run_investigation(event, policy, replay_provider, tmp_path)
    assert replay == first
    assert replay_provider.calls == 0
    resumed_provider = ScriptedProvider(responses)
    resumed = run_investigation(
        event, policy, resumed_provider, tmp_path, attempt_id="deliberate-2"
    )
    assert resumed.decision == first.decision
    assert resumed.run_id != first.run_id
    assert resumed_provider.calls == 0
    assert len(list((tmp_path / "runs").glob("*/result.json"))) == 2


@pytest.mark.parametrize("kind", ["invented_quote", "changed_number", "final_status", "wrong_role"])
def test_invalid_opening_abstains_and_skips_later_calls(tmp_path, kind):
    event, policy, responses = fixtures()
    report = responses["mean_reversion_opening"]
    if kind == "invented_quote":
        report["claims"][1]["citations"][0]["quote"] = "A fabricated quote never in the source"
    elif kind == "changed_number":
        report["claims"][0]["quant_refs"][0]["value"] = 0.99
    elif kind == "final_status":
        report["final_status"] = "CANDIDATE"
    else:
        report["role"] = "STRUCTURAL_BREAK"
    provider = ScriptedProvider(responses)
    result = run_investigation(event, policy, provider, tmp_path)
    assert result.decision.status == "ABSTAIN"
    assert provider.calls == 2
    assert all(stage.status == "SKIPPED" for stage in result.stages[2:])
    assert len(list((tmp_path / "runs").glob("*/result.json"))) == 1
    retry = ScriptedProvider(responses)
    assert run_investigation(event, policy, retry, tmp_path) == result
    assert retry.calls == 0
    explicit_retry = ScriptedProvider(responses)
    assert (
        run_investigation(
            event, policy, explicit_retry, tmp_path, attempt_id="deliberate-retry"
        ).decision.status
        == "ABSTAIN"
    )
    assert explicit_retry.calls == 1  # The valid opposing opening is preserved.


def test_semantic_validator_can_reject_mechanically_valid_quote(tmp_path):
    event, policy, responses = fixtures()
    responses["validation"].update(
        validation_status="FAIL",
        invalid_claim_count=1,
        abstain_recommended=True,
        break_risk="UNKNOWN",
    )
    result = run_investigation(event, policy, ScriptedProvider(responses), tmp_path)
    assert all(stage.status == "VALID" for stage in result.stages)
    assert result.decision.status == "ABSTAIN"
    assert result.decision.reason_codes == ("VALIDATION_FAILED",)


@pytest.mark.parametrize(
    "risk,expected", [("HIGH", "NO TRADE"), ("MEDIUM", "REVIEW"), ("UNKNOWN", "ABSTAIN")]
)
def test_validated_risk_controls_status(tmp_path, risk, expected):
    event, policy, responses = fixtures()
    responses["validation"]["break_risk"] = risk
    result = run_investigation(event, policy, ScriptedProvider(responses), tmp_path)
    assert result.decision.status == expected
    assert result.decision.model_b_probability == 0.78


@pytest.mark.parametrize(
    "gate,expected",
    [
        ("draft", "ABSTAIN"),
        ("watch", "REVIEW"),
        ("low_score", "NO TRADE"),
        ("partial", "REVIEW"),
        ("unknown", "ABSTAIN"),
        ("liquidity", "NO TRADE"),
    ],
)
def test_ineligible_rows_recorded_without_llm_cost(tmp_path, gate, expected):
    event, policy, responses = fixtures()
    if gate == "draft":
        policy = changed(policy, status="DRAFT")
    elif gate == "watch":
        event = changed(event, pair_status="WATCH")
    elif gate == "low_score":
        event = changed(
            event, quant=changed(event.quant, model_b_probability=0.1).model_dump(mode="json")
        )
    else:
        gates = event.gates.model_dump(mode="json")
        if gate == "liquidity":
            gates["liquidity_ok"] = False
        else:
            gates["source_coverage"] = "PARTIAL" if gate == "partial" else "UNKNOWN"
        # An absence extraction cannot assert complete coverage for these inputs.
        event = changed(event, gates=gates, catalysts=[])
    provider = ScriptedProvider(responses)
    result = run_investigation(event, policy, provider, tmp_path)
    assert result.decision.status == expected
    assert result.provider_calls == provider.calls == 0
    assert not result.stages
    assert len(list((tmp_path / "runs").glob("*/result.json"))) == 1


def test_shared_provider_budget_cannot_be_bypassed_by_parallel_roles(tmp_path):
    event, policy, responses = fixtures()
    provider = ScriptedProvider(responses, max_calls=1)
    result = run_investigation(event, policy, provider, tmp_path)
    assert provider.calls == 1
    assert result.decision.status == "ABSTAIN"
    assert all(stage.status == "SKIPPED" for stage in result.stages[2:])


def test_fixture_policy_rejected_for_live_adapter(tmp_path):
    event, policy, responses = fixtures()

    class PretendLive(ScriptedProvider):
        mode = "live"

    provider = PretendLive(responses)
    with pytest.raises(ValueError, match="Fixture thresholds"):
        run_investigation(event, policy, provider, tmp_path)
    assert provider.calls == 0


def test_terminal_checksum_and_controller_reproduction_are_checked(tmp_path):
    event, policy, responses = fixtures()
    result = run_investigation(event, policy, ScriptedProvider(responses), tmp_path)
    path = tmp_path / "runs" / result.run_id / "result.json"
    saved = path.read_bytes()
    envelope = json.loads(saved)
    envelope["payload"]["decision"]["status"] = "NO TRADE"
    path.write_text(canonical_json(envelope))
    provider = ScriptedProvider(responses)
    with pytest.raises(ValueError, match="checksum"):
        run_investigation(event, policy, provider, tmp_path)
    envelope["sha256"] = digest(envelope["payload"])
    path.write_text(canonical_json(envelope))
    with pytest.raises(ValueError, match="not reproducible"):
        run_investigation(event, policy, provider, tmp_path)
    assert provider.calls == 0


def test_changed_frozen_input_has_separate_cache_identity(tmp_path):
    event, policy, responses = fixtures()
    first = run_investigation(event, policy, ScriptedProvider(responses), tmp_path)
    modified = changed(
        event, lineage=changed(event.lineage, model_version="fixture-b-v2").model_dump(mode="json")
    )
    provider = ScriptedProvider(responses)
    second = run_investigation(modified, policy, provider, tmp_path)
    assert first.run_id != second.run_id
    assert provider.calls == 6

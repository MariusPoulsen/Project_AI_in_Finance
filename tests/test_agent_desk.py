import json
from pathlib import Path

import pytest

from structural_break.agents import debate as dv
from structural_break.agents import desk as dk
from structural_break.agents.budgets import BudgetPolicy, DurableAttemptJournal, ModelCap
from tests.test_agent_debate import Script, _answer, _case, _claim, _clients


def _analyst(persistence: int = 2, explains: int = 2, relation: int = 1) -> dict:
    return {
        "mover": "A",
        "explains_move": explains,
        "persistence": persistence,
        "relationship_change": relation,
        "claims": [_claim()],
        "uncertainties": [],
    }


class Desk(Script):
    """Answers desk roles; v2 debate roles fall back to the v2 script."""

    def __init__(self, analyst: dict, facilitator: dict | None = None, verdict: str = "SUPPORTED", overrides=None):
        super().__init__("MEDIUM", overrides)
        self.analyst, self.facilitator, self.verdict = analyst, facilitator or analyst, verdict

    def __call__(self, url, payload, headers, timeout):
        prompt = payload["contents"][0]["parts"][0]["text"]
        role = prompt.splitlines()[0].split("| ")[1]
        answers = {
            "pair_analyst": self.analyst,
            "facilitator": self.facilitator,
            "position_monitor": {"adverse": 4, "persistence": 5, "claims": [_claim()], "uncertainties": ["Unclear impact."]},
            "risk_judge": {"verdict": self.verdict, "reason": "The cited merger sentence supports it."},
        }
        if role in answers and not self.overrides.get(role):
            self.calls.append((url.split("/")[-1].split(":")[0], role))
            body = {
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answers[role])}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            }
            return 200, body
        return super().__call__(url, payload, headers, timeout)


def test_uncontested_event_needs_one_call(tmp_path: Path) -> None:
    script = Desk(_analyst(persistence=1))
    result = dk.run_entry(_case(), _clients(script), tmp_path, debate=True, judge=True)
    assert result["status"] == "SCORED" and not result["debated"]
    assert [role for _, role in script.calls] == ["pair_analyst"]
    assert result["scores"]["persistence"] == 1


def test_contested_event_is_debated_and_judged(tmp_path: Path) -> None:
    script = Desk(_analyst(persistence=3), facilitator=_analyst(persistence=5))
    result = dk.run_entry(_case(), _clients(script), tmp_path, debate=True, judge=True)
    roles = [role for _, role in script.calls]
    assert roles[0] == "pair_analyst" and roles[-1] == "risk_judge" and "facilitator" in roles
    assert sum(r.endswith("opening") or r.endswith("rebuttal") for r in roles) == 4
    assert result["debated"] and result["scores"]["persistence"] == 5
    assert (dk.JUDGE_MODEL, "risk_judge") in script.calls


def test_rejected_judgement_abstains(tmp_path: Path) -> None:
    script = Desk(_analyst(persistence=5), verdict="NOT_SUPPORTED")
    result = dk.run_entry(_case(), _clients(script), tmp_path, debate=False, judge=True)
    assert result["status"] == "ABSTAIN" and result["scores"] is None
    assert result["analyst_scores"]["persistence"] == 5


def test_invalid_scores_are_corrected_or_abstain(tmp_path: Path) -> None:
    bad = json.dumps(_analyst() | {"persistence": 9})
    script = Desk(_analyst(), overrides={"pair_analyst": [bad] * (dv.CORRECTIONS + 1)})
    result = dk.run_entry(_case(), _clients(script), tmp_path, debate=False, judge=False)
    assert result["status"] == "ABSTAIN"
    script = Desk(_analyst(), overrides={"pair_analyst": [bad]})
    assert dk.run_entry(_case(), _clients(script), tmp_path / "b", debate=False, judge=False)["status"] == "SCORED"


def test_monitor_scores_a_check(tmp_path: Path) -> None:
    result = dk.run_monitor(_case(), _clients(Desk(_analyst())), tmp_path)
    assert result["status"] == "SCORED" and result["scores"]["adverse"] == 4


def test_prompts_carry_anchors_and_no_outcomes() -> None:
    prompt = dk.analyst_prompt(_case())
    assert "persistence: will the relative move persist" in prompt and "revert_success" not in prompt
    assert "(A1.1)" in prompt
    with pytest.raises(ValueError):
        dk.resolve_analyst(_analyst() | {"claims": [_claim(cites=("Z9.9",))]}, _case())
    assert _answer  # shared fixtures stay importable


def _desk_policy(daily_judge: int = 100) -> BudgetPolicy:
    models = {dk.ANALYST_MODEL, dv.ADVOCATE_MODEL, dk.MONITOR_MODEL}
    caps = [ModelCap(model=m, total=100, daily=100) for m in sorted(models - {dk.JUDGE_MODEL})]
    caps.append(ModelCap(model=dk.JUDGE_MODEL, total=100, daily=daily_judge))
    return BudgetPolicy(allocation_id="test", global_cap=100, model_caps=tuple(caps))


def test_guard_charges_the_durable_journal_before_each_attempt(tmp_path: Path) -> None:
    with DurableAttemptJournal(tmp_path / "journal", _desk_policy()) as journal:
        script = Desk(_analyst(persistence=3), facilitator=_analyst(persistence=5),
                      overrides={"structural_break_opening": [500]})
        dk.run_entry(_case(), _clients(script, journal), tmp_path / "roles", debate=True, judge=True)
        counts = journal.counts["by_model"]
    # Analyst, four advocate turns plus one server-error retry, facilitator and judge.
    assert sum(counts.values()) == 8 and counts[dk.JUDGE_MODEL] == 1


def test_daily_cap_in_journal_pauses(tmp_path: Path) -> None:
    with DurableAttemptJournal(tmp_path / "journal", _desk_policy(daily_judge=0)) as journal:
        script = Desk(_analyst(persistence=5))
        with pytest.raises(dv.PauseRequired):
            dk.run_entry(_case(), _clients(script, journal), tmp_path / "roles", debate=False, judge=True)


def test_daily_quota_pauses_and_resumes_from_cached_roles(tmp_path: Path) -> None:
    class Daily(Desk):
        def __call__(self, url, payload, headers, timeout):
            if dk.JUDGE_MODEL in url:
                body = {"error": {"details": [{"violations": [{"quotaId": "RequestsPerDay-FreeTier"}]}]}}
                return 429, body
            return super().__call__(url, payload, headers, timeout)

    with pytest.raises(dv.PauseRequired):
        dk.run_entry(_case(), _clients(Daily(_analyst(persistence=5))), tmp_path, debate=False, judge=True)
    script = Desk(_analyst(persistence=5))
    dk.run_entry(_case(), _clients(script), tmp_path, debate=False, judge=True)
    assert [role for _, role in script.calls] == ["risk_judge"]

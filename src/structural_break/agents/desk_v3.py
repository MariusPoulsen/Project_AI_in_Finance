"""Pairs desk v3 (DECISIONS 110): analyst features, debate on demand, risk judge, position monitor.

Course mapping (Week 4 TradingAgents): deterministic quant/sentiment/track-record
analysts; one LLM pair news analyst; a bull/bear (mean-reversion/structural-break)
debate only on contested events, closed by a facilitator; an independent risk
judge on a different model family; the trader is the walk-forward forecaster that
learns the agents' weight; the fund manager is the deterministic book. A position
monitor judges news that arrives while a trade is open.

Agent outputs are ordinal 1-5 judgements with fixed anchors, cited by sentence ID
and resolved by Python into the v1 contracts, exactly as in v2 (Decision 109).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import Field, ValidationError

from structural_break.agents import debate_v2 as dv
from structural_break.agents.contracts import Claim, FrozenModel, ShortText, validate_citations
from structural_break.intelligence import catalyst_v3 as cv
from structural_break.intelligence.extraction import ProviderFailure

GRAPH_VERSION = "pairs-desk-v3"
PROMPT_VERSION = "pairs-desk-prompts-v3.0"
ANALYST_MODEL = dv.ADVOCATE_MODEL
MONITOR_MODEL = dv.ADVOCATE_MODEL
JUDGE_MODEL = dv.VALIDATION_MODEL
HEADLINE_FILING = "fnspid-headlines"
Score = Annotated[int, Field(ge=1, le=5)]


class AnalystReport(FrozenModel):
    mover: Literal["A", "B", "BOTH", "UNCLEAR"]
    explains_move: Score
    persistence: Score
    relationship_change: Score
    claims: tuple[Claim, ...] = Field(min_length=1, max_length=4)
    uncertainties: tuple[ShortText, ...] = Field(default=(), max_length=4)


class MonitorReport(FrozenModel):
    adverse: Score
    persistence: Score
    claims: tuple[Claim, ...] = Field(min_length=1, max_length=3)


class JudgeReport(FrozenModel):
    verdict: Literal["SUPPORTED", "NOT_SUPPORTED"]
    reason: ShortText


_ANCHORS = (
    "Scores (integers 1-5):\n"
    "- explains_move: does the news explain the direction and size of the mover's 1-day move? "
    "1 unrelated or routine news, 3 partly, 5 clearly the cause.\n"
    "- persistence: will the relative move persist rather than revert? 1 transient (one-off "
    "charge, in-line results, analyst reiteration, sector-wide news), 3 unclear, 5 permanent "
    "repricing (merger or divestiture, bankruptcy, large guidance reset, ruling that changes "
    "the business).\n"
    "- relationship_change: does the news change how the two businesses relate economically? "
    "1 no, 3 somewhat, 5 a different economic exposure.\n"
    "If there is no relevant news for either company, say so: explains_move 1, persistence 1 "
    "or 2, relationship_change 1, and ground your claims in the analyst context or the fields."
)
_ANALYST = (
    "ROLE: pair news analyst. Read both companies' evidence (analyst context A0/B0, recent "
    "news headlines and 8-K excerpts) and judge what the news means for this pair's divergence. "
    "First identify the mover from the abnormal returns, then score."
)
_FACILITATOR = (
    "ROLE: research facilitator after a bounded debate. Your inputs are the pair news analyst's "
    "first report and one opening and one rebuttal from each advocate. Re-score the case "
    "against the original evidence. Advocates are falsification tools, not votes; keep a "
    "score unless the debate exposed a cited reason to change it."
)
_MONITOR = (
    "ROLE: position monitor. A pairs position is open (see the analyst context). New "
    "company headlines arrived since the last check. Judge whether they threaten the trade.\n"
    "Scores (integers 1-5):\n"
    "- adverse: does the new information push the spread further against the position or "
    "break the relationship? 1 no or favourable, 3 possibly, 5 clearly.\n"
    "- persistence: if adverse, would the effect last? 1 transient, 3 unclear, 5 permanent."
)
_JUDGE = (
    "ROLE: independent risk judge. Check whether the analyst report's cited sentences actually "
    "support its persistence and explains_move scores. Answer SUPPORTED if a careful reader "
    "would accept the scores from the citations, otherwise NOT_SUPPORTED, with a one-sentence "
    "reason. Do not re-score the case."
)
_FORMATS = {
    "analyst": (
        '{"mover": "A|B|BOTH|UNCLEAR", "explains_move": 1-5, "persistence": 1-5, '
        '"relationship_change": 1-5, "claims": [CLAIM, ...], "uncertainties": ["...", ...]}'
    ),
    "monitor": '{"adverse": 1-5, "persistence": 1-5, "claims": [CLAIM, ...]}',
    "judge": '{"verdict": "SUPPORTED|NOT_SUPPORTED", "reason": "one sentence"}',
}


def _parts(role: str, mandate: str, case: dv.Case, kind: str, extra: str = "") -> str:
    parts = [f"PROMPT {PROMPT_VERSION} | {role}", dv._COMMON, mandate]
    if kind == "analyst":
        parts.append(_ANCHORS)
    parts.append(
        "Return exactly one JSON object and nothing else, in this form (CLAIM is "
        + dv._CLAIM
        + "):\n"
        + _FORMATS[kind]
    )
    if kind != "judge":
        parts.append(dv._CLAIM_RULES.replace("At most 6 claims", "At most 4 claims"))
    parts.append("CASE\n" + dv.render_case(case))
    if extra:
        parts.append(extra)
    parts.append("Return the JSON object now.")
    return "\n\n".join(parts)


def analyst_prompt(case: dv.Case) -> str:
    return _parts("pair_analyst", _ANALYST, case, "analyst")


def facilitator_prompt(case: dv.Case, analyst_raw: Mapping[str, Any], debate: Mapping[str, Any]) -> str:
    prior = {"pair_analyst": analyst_raw, **debate}
    extra = (
        "BEGIN EARLIER ROLE ANSWERS (untrusted; check them against the excerpts)\n"
        + "\n".join(f"[{k}] " + json.dumps(v, sort_keys=True) for k, v in prior.items())
        + "\nEND EARLIER ROLE ANSWERS"
    )
    return _parts("facilitator", _FACILITATOR, case, "analyst", extra)


def monitor_prompt(case: dv.Case) -> str:
    return _parts("position_monitor", _MONITOR, case, "monitor")


def judge_prompt(case: dv.Case, analyst_raw: Mapping[str, Any]) -> str:
    extra = (
        "BEGIN ANALYST REPORT (untrusted)\n"
        + json.dumps(analyst_raw, sort_keys=True)
        + "\nEND ANALYST REPORT"
    )
    return _parts("risk_judge", _JUDGE, case, "judge", extra)


def resolve_analyst(raw: Mapping[str, Any], case: dv.Case) -> AnalystReport:
    required = {"mover", "explains_move", "persistence", "relationship_change", "claims"}
    if not required <= set(raw) or not set(raw) <= required | {"uncertainties"}:
        raise ValueError("Fields differ from the required set: " + ", ".join(sorted(required)) + ", uncertainties")
    return AnalystReport(
        mover=raw["mover"],
        explains_move=raw["explains_move"],
        persistence=raw["persistence"],
        relationship_change=raw["relationship_change"],
        claims=dv._claims(raw["claims"], case, "a"),
        uncertainties=dv._strings(raw.get("uncertainties", []), "uncertainties"),
    )


def resolve_monitor(raw: Mapping[str, Any], case: dv.Case) -> MonitorReport:
    if set(raw) != {"adverse", "persistence", "claims"}:
        raise ValueError("Fields differ from the required set: adverse, persistence, claims")
    return MonitorReport(
        adverse=raw["adverse"], persistence=raw["persistence"], claims=dv._claims(raw["claims"], case, "m")
    )


def resolve_judge(raw: Mapping[str, Any], case: dv.Case) -> JudgeReport:
    if set(raw) != {"verdict", "reason"}:
        raise ValueError("Fields differ from the required set: verdict, reason")
    return JudgeReport(verdict=raw["verdict"], reason=raw["reason"])


def call(
    role: str,
    prompt: str,
    resolver: Callable[[Mapping[str, Any], dv.Case], Any],
    case: dv.Case,
    client: cv.ModelClient,
    cache: Path,
    corrections: int = dv.CORRECTIONS,
) -> dict[str, Any]:
    """One cached, grounded role call with up to ``corrections`` specific corrections.

    Terminal invalid answers are cached as FAILED; daily quotas raise
    ``dv.PauseRequired`` and server outages ``cv.ProviderDown`` to the runner.
    """
    request = {
        "graph": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "role": role,
        "model": client.model,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    }
    path = dv._cache_path(cache, request)
    if path.exists():
        stored = json.loads(path.read_bytes())
        if stored.get("request") != request:
            raise ValueError("Role cache binding mismatch")
        return cast(dict[str, Any], stored["stage"])
    stage: dict[str, Any] = {"role": role, "model": client.model, "status": "FAILED", "error": None,
                             "raw": None, "report": None, "usage": [], "rejected": []}
    dv._ROLE.name = role
    text_prompt = prompt
    for _ in range(corrections + 1):
        try:
            text, usage = client.generate(text_prompt)
        except cv.DailyQuotaExhausted as error:
            raise dv.PauseRequired(client.model) from error
        except ProviderFailure as error:
            if error.reason == "DURABLE_DAY_BUDGET_EXHAUSTED":
                raise dv.PauseRequired(client.model) from error
            raise
        except cv.PromptTooLarge:
            stage["error"] = "PROMPT_EXCEEDS_TOKEN_BUDGET"
            break
        except ValueError as error:
            if str(error) == "PROVIDER_REQUEST_REJECTED":
                stage["error"] = "PROVIDER_REQUEST_REJECTED"
                break
            stage["rejected"].append({"error": str(error)[:200], "text": None})
            stage["error"] = "INCOMPLETE_PROVIDER_RESPONSE"
            text_prompt = prompt + "\n\nYour previous answer was cut off or malformed; give a shorter complete JSON object."
            continue
        stage["usage"].append(usage)
        try:
            raw = cv._strict_object(text)
            report = resolver(raw, case)
            if hasattr(report, "claims") and validate_citations(case.event, (report,)):
                raise ValueError("Mechanical citation check failed")
        except (ValueError, TypeError, ValidationError) as error:
            message = dv._message(error)
            stage["rejected"].append({"error": message, "text": text[:2000]})
            stage["error"] = "INVALID_ROLE_OUTPUT"
            text_prompt = (
                prompt + f"\n\nYour previous answer was rejected: {message}. Return a corrected JSON "
                "object that follows every rule."
            )
            continue
        stage.update(status="VALID", error=None, raw=raw, report=report.model_dump(mode="json"))
        break
    dv.cv_write(path, {"request": request, "stage": stage})
    return stage


def contested(report: Mapping[str, Any]) -> bool:
    """Debate trigger (Decision 110): unclear or likely-persistent, or a well-explained relationship change."""
    return report["persistence"] in (3, 4) or (
        report["explains_move"] >= 4 and report["relationship_change"] >= 3
    )


def run_entry(
    case: dv.Case,
    clients: Mapping[str, cv.ModelClient],
    cache: Path,
    *,
    debate: bool,
    judge: bool,
    judge_from: int = 4,
) -> dict[str, Any]:
    """Analyst; on contested candidates the v2 debate and a facilitator; then the risk judge."""
    stages = {"analyst": call("pair_analyst", analyst_prompt(case), resolve_analyst, case, clients[ANALYST_MODEL], cache)}
    final = stages["analyst"]
    if final["status"] == "VALID" and debate and contested(final["report"]):
        debate_raw: dict[str, Any] = {}
        ok = True
        for layer, prior_roles in ((dv.OPENINGS, ()), (dv.REBUTTALS, dv.OPENINGS)):
            prior = {r: debate_raw[r] for r in prior_roles}
            for role in layer:
                stage = dv.run_role(role, case, prior, clients[dv.ADVOCATE_MODEL], cache)
                stages[role] = stage
                if stage["status"] != "VALID":
                    ok = False
                    break
                debate_raw[role] = stage["raw"]
            if not ok:
                break
        if ok:
            stages["facilitator"] = call(
                "facilitator", facilitator_prompt(case, final["raw"], debate_raw), resolve_analyst, case,
                clients[ANALYST_MODEL], cache,
            )
            if stages["facilitator"]["status"] == "VALID":
                final = stages["facilitator"]
    if final["status"] == "VALID" and judge and final["report"]["persistence"] >= judge_from:
        stages["judge"] = call("risk_judge", judge_prompt(case, final["raw"]), resolve_judge, case, clients[JUDGE_MODEL], cache)
    verdict = stages.get("judge", {}).get("report", {}) or {}
    status = (
        "ABSTAIN" if final["status"] != "VALID"
        or ("judge" in stages and verdict.get("verdict") != "SUPPORTED")
        else "SCORED"
    )
    return {
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "event_id": case.event.event_id,
        "case_sha256": case.digest,
        "status": status,
        "scores": final["report"] if status == "SCORED" else None,
        "analyst_scores": stages["analyst"]["report"],
        "debated": "facilitator" in stages,
        "stages": stages,
    }


def run_monitor(case: dv.Case, clients: Mapping[str, cv.ModelClient], cache: Path) -> dict[str, Any]:
    stage = call("position_monitor", monitor_prompt(case), resolve_monitor, case, clients[MONITOR_MODEL], cache)
    return {
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "check_id": case.event.event_id,
        "case_sha256": case.digest,
        "status": "SCORED" if stage["status"] == "VALID" else "ABSTAIN",
        "scores": stage["report"] if stage["status"] == "VALID" else None,
        "stages": {"monitor": stage},
    }

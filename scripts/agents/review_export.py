"""Decision 113: blind 50-case human review of the pairs desk (Decision 28 quality gate).

30 entry cases (design candidates; 10 debated, 20 not) and 20 monitor checks (10 the monitor
rated adverse >= 4, 10 others), fixed seed 5558. Reviewers see the masked evidence and the
agents' cited claims; no model probability is shown beyond the case's own fields, and no
outcome, label or return. Writes docs/agent_review/review_cases.md and review_answers.csv.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.agents import debate as dv

OUT = Path("outputs/agent_desk")
DOCS = Path("docs/agent_review")
DOCS.mkdir(parents=True, exist_ok=True)
SEED = 5558
inv = pd.read_parquet(OUT / "entry_inventory.parquet").set_index("event_id")
entry_rows: list[dict[str, Any]] = []
for path in (OUT / "entry_results").glob("*.json"):
    r = json.loads(path.read_bytes())
    if (
        r.get("prompt_version", "").endswith("v3.1")
        and r["status"] == "SCORED"
        and bool(inv.loc[r["event_id"], "candidate"])
    ):
        entry_rows.append({"event_id": r["event_id"], "debated": r["debated"]})
entries = pd.DataFrame(entry_rows)
picked = pd.concat(
    [
        entries[entries.debated].sample(10, random_state=SEED),
        entries[~entries.debated].sample(20, random_state=SEED),
    ]
)
mon_inv = pd.read_parquet(OUT / "monitor_inventory.parquet").set_index("file")
check_rows: list[dict[str, Any]] = []
for path in (OUT / "monitor_results").glob("*.json"):
    r = json.loads(path.read_bytes())
    if (
        r.get("prompt_version", "").endswith("v3.3")
        and r["status"] == "SCORED"
        and path.stem in mon_inv.index
    ):
        check_rows.append({"file": path.stem, "adverse": r["scores"]["adverse"]})
checks = pd.DataFrame(check_rows)
mpicked = pd.concat(
    [
        checks[checks.adverse >= 4].sample(10, random_state=SEED),
        checks[checks.adverse < 4].sample(10, random_state=SEED),
    ]
)
cases = [("E", e) for e in picked.event_id] + [("M", f) for f in mpicked.file]
order = pd.Series(range(len(cases))).sample(frac=1, random_state=SEED).tolist()  # mix types


def claims_block(raw: dict[str, Any], case: dv.Case) -> list[str]:
    refs = case.sentences
    lines = []
    for number, claim in enumerate(raw.get("claims", []), start=1):
        cited = "; ".join(f"({c}) {refs[c][2][:220]}" for c in claim.get("cites", []) if c in refs)
        quant = ", ".join(claim.get("quant", []))
        lines.append(f"  {number}. [{claim.get('kind')}] {claim.get('text')}")
        if cited:
            lines.append(f"     cites: {cited}")
        if quant:
            lines.append(f"     fields: {quant}")
    return lines


md = [
    "# Agent review: 50 blind cases (Decision 113)",
    "",
    "For each case, read the evidence first, then the agent's claims.",
    "- In `review_answers.csv`, mark every claim **Y** (the cited text supports it), **P** "
    "(partly) or **N** (not supported).",
    "- Give **your own** scores from 1 to 5 using the anchors below, without looking at the "
    "agent's scores (they are not shown).",
    "- Company names are masked as Company A/B. No outcomes are shown.",
    "",
    "**Entry anchors:** explains_move: 1 = unrelated or routine news, 5 = clearly the cause of "
    "the move. "
    "persistence: 1 = transient, 3 = unclear, 5 = permanent repricing (merger, bankruptcy, "
    "large guidance reset, ruling). "
    "relationship_change: 1 = no change, 5 = a different economic exposure.",
    "",
    "**Monitor anchors:** adverse: 1 = no threat or favourable, 5 = clearly pushes the spread "
    "against the position or breaks the relationship. "
    "persistence: 1 = transient, 5 = permanent.",
    "",
]
answers = []
for position, index in enumerate(order, start=1):
    kind, key = cases[index]
    rid = f"R{position:02d}"
    if kind == "E":
        case = dv.Case.from_json(json.loads((OUT / "entry_cases" / f"{key}.json").read_bytes()))
        result = json.loads((OUT / "entry_results" / f"{key}.json").read_bytes())
        stage = (
            result["stages"]["facilitator"]
            if result["debated"]
            and result["stages"].get("facilitator", {}).get("status") == "VALID"
            else result["stages"]["analyst"]
        )
        title = "Entry case: pair news analyst" + (" (after a debate)" if result["debated"] else "")
        own = "explains_move, persistence, relationship_change"
    else:
        case = dv.Case.from_json(json.loads((OUT / "monitor_cases" / f"{key}.json").read_bytes()))
        result = json.loads((OUT / "monitor_results" / f"{key}.json").read_bytes())
        stage = result["stages"]["monitor"]
        title = "Monitor check: position monitor"
        own = "adverse, persistence"
    raw = stage["raw"]
    md += [
        f"## {rid}. {title}",
        "",
        "```",
        dv.render_case(case),
        "```",
        "",
        "**Agent's claims:**",
        *claims_block(raw, case),
        "",
    ]
    if raw.get("uncertainties"):
        md += ["**Agent's uncertainties:** " + " | ".join(raw["uncertainties"]), ""]
    for number, _ in enumerate(raw.get("claims", []), start=1):
        answers.append(
            {
                "review_id": rid,
                "type": kind,
                "item": f"claim {number}",
                "answer (Y/P/N)": "",
                "notes": "",
            }
        )
    answers.append(
        {
            "review_id": rid,
            "type": kind,
            "item": f"your scores: {own}",
            "answer (Y/P/N)": "",
            "notes": "",
        }
    )
    answers.append(
        {
            "review_id": rid,
            "type": kind,
            "item": "overall: is the agent's reasoning sound? (Y/P/N)",
            "answer (Y/P/N)": "",
            "notes": "",
        }
    )
(DOCS / "review_cases.md").write_text("\n".join(md), encoding="utf-8")
pd.DataFrame(answers).to_csv(DOCS / "review_answers.csv", index=False)
key = pd.DataFrame(
    [
        {"review_id": f"R{p:02d}", "type": cases[i][0], "source": cases[i][1]}
        for p, i in enumerate(order, start=1)
    ]
)
key.to_csv(
    OUT / "review_key.csv", index=False
)  # kept out of docs so reviewers stay blind to agent scores
print(f"wrote {len(cases)} cases, {len(answers)} answer rows")

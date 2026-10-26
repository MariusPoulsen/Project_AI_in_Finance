# Agent desk

The agent desk is the project's multi-agent layer. It follows the course's TradingAgents
structure (analyst team, bull/bear debate, risk check, fund manager) on top of the
quantitative book, and adds a position monitor that watches open trades. It was
pre-registered in Decision 110 and evaluated in Decision 110d.

**What it contributes to the adopted book:** only the **monitor exit**. Agent scores at
entry did not improve the reversion forecast or the book, so they are reported but not
used (Decision 110d).

## Roles

| Course role | Desk role | Who | When |
|---|---|---|---|
| Technical analyst | Quant state: z-score, half-life, beta drift, model probability | Python | always |
| Sentiment analyst | FinBERT tone of each company's 8-K excerpts and headlines | Python (pinned FinBERT) | always |
| News analyst | **Pair news analyst**: reads both companies' fresh news and scores the divergence | Gemma 4 26B | one call per event with news |
| Bull and bear researchers | Mean-reversion and structural-break **advocates**, one exchange (four turns) | Gemma 4 26B | contested events only |
| Research manager | **Facilitator**: revises the analyst's scores after the debate | Gemma 4 26B | contested events only |
| Risk team | **Risk judge**: checks that the cited sentences support the scores | Gemini 3.5 Flash-Lite (a different model family) | design candidates |
| Fund manager | The deterministic book (selection, sizing, exits, risk) | Python | always |
| — | **Position monitor**: judges news that arrives during an open trade | Gemma 4 26B | headlines toned against the position |

An event is **contested** when the analyst's persistence is 3 or 4, or when
explains-move is at least 4 and relationship-change at least 3.

## Reports

All scores are ordinal 1–5 with written anchors; claims cite sentence IDs that are resolved
locally against the masked evidence (company names appear as "Company A/B").

- **Analyst and facilitator:** mover (A, B, both or unclear), explains_move, persistence,
  relationship_change, up to four cited claims and the uncertainties.
- **Monitor:** adverse (does the news push the spread against the position or break the
  relationship?) and persistence, up to four cited claims and the uncertainties. The prompt
  states the live z-score and the trade's time stop, and that there is no z-score stop-loss.
- **Risk judge:** SUPPORTED or NOT_SUPPORTED with a reason; NOT_SUPPORTED makes the event
  ABSTAIN, so it falls back to the no-agent forecast.

Invalid answers get up to two specific corrections, then ABSTAIN. ABSTAIN is a failure state
and is reported separately from any judgement.

## Monitor exit (part of the book)

A trade is closed at the close of the first monitor check with **adverse ≥ 5 and
persistence ≥ 5** (Decision 110d), in addition to the take profit, the half-life time stop and
the 8-K news exit. A **FinBERT triage** decides which checks reach the model: a check is sent
only when a new headline is toned against the position (net tone ≤ −0.2 on the long leg or
≥ +0.2 on the short leg; Decision 112c). This cut the monitor checks from 21,333 to 7,937.

## Results (2010–2023, Decision 110d)

| | Result |
|---|---|
| Entry run | 6,485 events scored, 31 abstained |
| Monitor run | 7,933 checks scored, 4 abstained |
| Goal 1 (forecast) | Agent features do not improve the forecast on any base; slightly worse on the bagged B+rule+ou base |
| Goal 2 (book) | R0 selection with the monitor exit: Sharpe 0.813 (2010–2017), 0.595 (2018–2023), 0.713 (2010–2023) |
| Full model as selector | About 0.39, below the R0 book |

The 50-case blind human review sheet is in [agent_review/](agent_review/review_cases.md).

## Models, limits and guardrails

- Free API tier only. Durable per-model call caps (entry: 9,000 a day, 36,000 in total;
  monitor: 13,000 a day, 30,000 in total), a reservation before every HTTP call, and a pause
  until the provider's daily reset.
- Gemini Flash (non-Lite) models are reserved and unused.
- Temperature 0, seed 42, minimal thinking.
- Names masked; no outcomes in prompts; nothing from 2024 or later before the final-test
  unlock.
- Prompt identities are stored with every result: `pairs-desk-prompts-v3.1` (entry) and
  `pairs-desk-monitor-v3.3` (monitor). They are content identifiers of the cached results and
  are not renamed.

## Code and commands

| Module | Contents |
|---|---|
| `structural_break.agents.debate` | Shared case format, masking, sentence-ID citations, rate guard, clients, advocate turns |
| `structural_break.agents.desk` | Report contracts, prompts, entry flow and monitor check |
| `structural_break.agents.desk_runner` | Case building, the resumable run, status and evaluation |
| `structural_break.book.selection` | The book's candidate selection that the desk works on |

```shell
python -m structural_break.agents.desk_runner build-entry
python -m structural_break.agents.desk_runner build-monitor
python scripts/agents/monitor_triage.py
python -m structural_break.agents.desk_runner run --kind entry --env-file PATH/TO/.env
python -m structural_break.agents.desk_runner run --kind monitor --env-file PATH/TO/.env
python -m structural_break.agents.desk_runner status
python -m structural_break.agents.desk_runner evaluate            # add --holdout once
python scripts/agents/review_export.py                            # blind review sheet
python scripts/agents/ingest_fnspid.py                            # FNSPID headlines
```

Outputs go to `outputs/agent_desk/`. The earlier debate-only layer (Decision 109) and the
original agent pipeline are described in [archive/DEBATE_LAYER.md](archive/DEBATE_LAYER.md)
and [archive/AGENT_PIPELINE_RUNBOOK.md](archive/AGENT_PIPELINE_RUNBOOK.md).

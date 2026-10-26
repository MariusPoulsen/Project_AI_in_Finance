# Multi-agent layer v2 (Decision 109)

Branch `p6/agent-layer`, stacked on `p6/quant-research`. This is the Phase 5
plan (Decision 28, `specs/04_MULTI_AGENT_PIPELINE.md`) completed on the
candidates of the current best book. It is aimed at both project goals:
- **Goal 1:** does the agents' validated break risk improve the reversion
  forecast?
- **Goal 2:** does vetoing or down-sizing risky candidates raise the book's
  Sharpe ratio?

## What runs

For each candidate trade of the Decision 100 design with fresh 8-K news
(715 of 3,291 events, 2010–2023):

| Step | Role | Model (free tier) | Sees |
|---|---|---|---|
| 1 | Mean-reversion opening | `gemma-4-26b-a4b-it` | case only |
| 1 | Structural-break opening | `gemma-4-26b-a4b-it` | case only (in parallel, independent) |
| 2 | Mean-reversion rebuttal | `gemma-4-26b-a4b-it` | case + both openings |
| 2 | Structural-break rebuttal | `gemma-4-26b-a4b-it` | case + both openings |
| 3 | Synthesis | `gemini-3.1-flash-lite` | case + openings + rebuttals |
| 4 | Risk / validation | `gemini-3.5-flash-lite` | everything above |
| 5 | Controller | Python (`decision/agent_policy.decide`) | validated state |

**The case.** Everything except the source excerpts is masked to
"Company A/B":
- the five fixed quantitative fields: model probability, spread z-score,
  half-life, beta drift and cointegration p-value;
- each company's 1-day abnormal return, Gemma news label (Decision 50) and
  FinBERT tone (Decision 51);
- the pair's sub-industry and economic rationale;
- the dated SEC excerpts, split into numbered sentences (`A1.3`).

**Claims.** The agents cite sentence IDs and field names. Python replaces
them with the exact sentence and stored value. The unchanged v1 contracts
then check every report. A claim cannot cite a sentence that does not
exist, or a value the case does not hold.

**Controller.** The controller maps the validated break risk to a status:

| Validated outcome | Status |
|---|---|
| LOW risk, every check passed | CANDIDATE |
| MEDIUM risk, a contradiction or a warning | REVIEW |
| HIGH risk, or a HIGH-materiality one-sided catalyst | NO TRADE |
| Any failed role or check | ABSTAIN |

No LLM decides a trade.

## Guardrails

- **Free tier only, durable caps.** Every HTTP attempt, retries included,
  is charged to a durable journal (`outputs/p6_agents/journal`) before it
  is sent:

  | Model | Per Pacific day | Total |
  |---|---|---|
  | Gemma | 9,000 | 6,000 |
  | Each Flash-Lite | 450 | 1,600 |

  Gemma is paced at 14,500 input tokens a minute (limit 16,000). Flash-Lite
  sends at most one request every 5 seconds.
- **Quota pauses.** A daily 429 from Google, or a durable cap reached,
  pauses until midnight Pacific. Finished roles are cached, so a paused
  event resumes without resending them.
- **No fallback, no stronger model.** `gemini-3.5-flash` and the other
  Flash models are not used.
- **No outcomes.** Labels and returns never enter a prompt; the prompt
  builder rejects outcome-named fields, and agent inputs cannot hold events
  from 2024 or later.
- **Key handling.** The key is read from the v2 `.env` into the process
  only and is never printed or stored.
- **Fixed run order.** Events run in a fixed order set by a hash of the
  event ID, so any partial run is a target-blind sample.

## Commands

```powershell
.venv\Scripts\python.exe -m structural_break.experiments.p6_agents build      # case files + inventory (no LLM)
.venv\Scripts\python.exe -m structural_break.experiments.p6_agents run --env-file <v2 .env> [--limit 20]
.venv\Scripts\python.exe -m structural_break.experiments.p6_agents status
.venv\Scripts\python.exe -m structural_break.experiments.p6_agents evaluate [--holdout]   # after the run
.venv\Scripts\python.exe -m structural_break.experiments.p6_agents review-export          # 50-event blind sheet
```

`run` is resumable: rerun the same command after any stop.

## Limits to report

- **Possible memory leakage:** masking cannot stop a model that recognises
  a company from the facts in its filing and remembers later events.
- **Thin evidence:** the news packs hold at most two chunks per filing. Some
  companies only have an Item heading.
- **Grounding is not correctness:** exact provenance is guaranteed, but
  whether a cited sentence supports its claim is judged only by the
  validator. Human review (`review-export`, 50 events) remains required
  before claiming the agents are semantically accurate.

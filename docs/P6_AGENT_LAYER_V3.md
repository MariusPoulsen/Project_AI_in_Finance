# Multi-agent layer v3: design proposal ("pairs desk")

Status: **proposal, 2026-10-22.** Nothing here is run yet. It becomes a
pre-registration (Decision 110) only after the v2 run (Decision 109) has
finished and the owner has approved it.

v3 keeps the course's Week 4 TradingAgents structure:
- an analyst team;
- a bull/bear researcher debate;
- a trader;
- a risk team;
- a fund manager.

Three lessons from v2 change it:
1. **Agents produce features, not vetoes.** Their outputs feed the forecaster
   and walk-forward training learns their weight; no hand-coded rule such as
   "catalyst flag → NO TRADE".
2. **A debate only where it can matter.** One analyst call per event; the
   bull/bear debate runs only on contested events.
3. **Agents also watch open trades,** where the project's news evidence
   actually paid off (Decision 62).

## Why change v2

| v2 finding | Consequence | v3 response |
|---|---|---|
| Validator risk is MEDIUM on 18 of 19 pilot events | Almost no resolution, so little room to improve AUC or Brier | Ordinal 1–5 scores with explicit anchors; their weights learned walk-forward |
| The catalyst flag vetoes about 40 % of events by a fixed rule | Untested mapping from LLM label to action | Agent outputs become forecaster features; the data sets the action |
| Six calls per event, about 11 % abstain, 2+ days for 715 events | Expensive and fragile | One analyst call per event; debate on about 25 % |
| Only 715 of 3,291 candidates, and none outside the candidate set | Too few events to learn from | Analyst on every top-40 % event with news (about 2,000–2,500), so there is training data |
| News features failed at entry (Decision 54); the news exit worked (Decision 62) | Value sits after entry | New position monitor for news during open trades |

## The desk

| Course role | v3 role | Who | Calls |
|---|---|---|---|
| Technical analyst | **Quant analyst:** spread z-score, half-life, beta drift, cointegration, model probability | Python (deterministic) | 0 |
| Sentiment analyst | **Sentiment analyst:** FinBERT tone of each company's 8-K excerpts | Python (pinned FinBERT, already scored) | 0 |
| News analyst | **Pair news analyst:** reads both companies' fresh 8-K excerpts, writes the structured report below | Gemma, 1 call | 1 per event with news |
| Historian / memory (TradingAgents reflection) | **Track-record analyst:** this pair's earlier divergences whose 20-session outcome had closed before the signal | Python (point-in-time) | 0 |
| Bull vs bear researchers | **Mean-reversion vs structural-break advocates,** one exchange (the v2 graph) | Gemma, 4 calls | contested events only |
| Research manager | **Facilitator:** revises the analyst's scores after the debate | Gemma, 1 call | contested events only |
| Trader | **Forecaster:** R0 score plus agent features in a walk-forward logistic model; gives calibrated P(revert) | Python (learned) | 0 |
| Risk team | **Risk judge:** checks that the cited reasons support any score that would change the action | Flash-Lite 3.5 (a different model family, so independent) | about 10–20 % of events |
| Fund manager | **Book:** the existing deterministic portfolio, with size and veto thresholds chosen on 2010–2017 | Python | 0 |
| (new) | **Position monitor:** a new 8-K on either company during an open trade → HOLD / EXIT score | Gemma, 1 call | per news arrival in an open trade |

## The pair news analyst's report (one call)

Same masking, sentence-ID citations and v1-style grounding checks as v2. The
fields are ordinal with anchors, so the answer is a graded judgement rather
than a pseudo-probability:
- `mover`: A, B, BOTH or UNCLEAR. Which company's move made the divergence,
  checked against the cited abnormal returns.
- `explains_move`: 1–5. Does the news explain the direction and size of that
  move? (1 = unrelated or routine, 5 = clearly the cause.)
- `persistence`: 1–5. Will the move persist? (1 = transient, such as a
  one-off charge or in-line results; 3 = unclear; 5 = permanent repricing,
  such as M&A, bankruptcy, a business-mix change or a large guidance reset.)
- `relationship_change`: 1–5. Does the news change how the two businesses
  relate? (1 = no, 5 = a different economic exposure.)
- `materiality` and `event_type`: as in Decision 50.
- `claims`: up to four cited claims supporting the three scores.

**Features for the forecaster:**
- the three scores;
- `persistence × explains_move`;
- a "no fresh news" indicator. Events without news get the deterministic
  value; they are not missing data.

## Debate on demand

The v2 graph runs only when the analyst's report is contested:
- `persistence` is 3 or 4;
- or `explains_move` is 4 or more with `relationship_change` 3 or more.

Expected share: about 25 %. The facilitator issues revised scores in the same
schema. Both versions are stored, so the evaluation can measure what the
debate adds.

## Risk judge

The Flash-Lite judge runs only when the final scores would move an event
across the book's chosen veto or size threshold, at most about 20 % of
events. It checks whether the cited sentences support the scores.
- **Pass:** the scores stand.
- **Fail:** the event falls back to the no-agent forecast, the v3 form of
  ABSTAIN.

This keeps Flash-Lite use within its daily quota while preserving an
independent check where it matters.

## Position monitor (exits)

For each open trade, at every 8-K accepted on either company before the
planned exit, one call produces:
- `persistence` 1–5 of the new news, and whether it moves against the
  position;
- a cited reason.

The monitor exit rule, "exit at the next close if persistence ≥ T on the
adverse leg", is chosen on 2010–2017 against the existing adverse-tone news
exit (Decision 62). Exits are where the project has already found value.

## Statuses, simplified

- **NO TRADE:** a judged, cited reason not to trade. In v3 it arises only
  when the forecaster's P(revert) falls below the book's threshold after
  agent features.
- **ABSTAIN:** no defensible judgement, for example a failed analyst call or
  a failed risk check. The event is traded on the no-agent forecast and the
  abstention rate is reported. This keeps failure separate from judgement,
  as in v2.
- **REVIEW / CANDIDATE:** kept only for the demo app. The backtest uses
  trade, skip or size.

## Evaluation plan (to pre-register after the v2 run)

Same events, same walk-forward protocol, labels read once:

| Variant | Agents | Purpose |
|---|---|---|
| A | none | current book (Decision 108) |
| B | pair news analyst features | does one LLM call add information? |
| C | B + debate on demand | does the multi-agent debate add anything over one analyst? |
| D | v2 full debate (Decision 109) | the planned architecture, for reference |
| E | A + position monitor exits | agents after entry |

- **Goal 1:** AUC, log loss and Brier, walk-forward, on top-40 % events with
  news. Pass rule: Decision 47's month-block bootstrap.
- **Goal 2:** 2010–2017 Sharpe picks the variant (owner rule, Decision 105);
  2018–2023 is opened once.
- **Human check:** the 50-event blind review sheet also scores the analyst
  report.

## Guardrails (unchanged unless stated)

- **Kept from v2:**
  - free tier only, with durable per-model caps and quota pauses;
  - names masked;
  - no outcomes in prompts, and nothing from 2024 or later;
  - sentence-ID citations, resolved locally;
  - pre-registration before any run.
- **New, a leakage canary:** before the run, 50 masked cases ask the model
  to name the companies. If it names either company in more than 20 % of
  cases, the masking is strengthened before the run, and the rate is
  reported as a limitation.
- **New, a track-record cutoff:** the track-record analyst uses only
  outcomes whose 20-session window closed before the signal.

## Budget estimate (free tier)

| Stage | Calls | Model | Time at measured pacing |
|---|---|---|---|
| Leakage canary | 50 | Gemma | minutes |
| Pair news analyst | about 2,000–2,500 | Gemma | about 8–10 hours |
| Debate on demand | about 600 × 5 | Gemma | about 10–12 hours |
| Risk judge | about 300–500 | Flash-Lite 3.5 | 1–2 days of quota |
| Position monitor | about 800–1,200 | Gemma | about 4 hours |

That is roughly 2–3 days in total, mostly Gemma. It reuses the v2 case
builder, resolver, client and journal.

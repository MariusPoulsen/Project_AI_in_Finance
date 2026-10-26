# Plan and status

The project compares a quantitative reversion forecaster with SEC- and agent-augmented
versions (Goal 1) and builds the best pairs-trading book on top of them (Goal 2). Everything
up to 2023 is built and evaluated; the 2024–2025 final test stays locked until the owner
writes an unlock record. The earlier phase-by-phase plan and status pages are archived in
[archive/PHASE_PLAN.md](archive/PHASE_PLAN.md) and
[archive/PHASE_STATUS.md](archive/PHASE_STATUS.md).

## Components

| Component | Status | Where | Decisions |
|---|---|---|---|
| Data and universe: 250 frozen issuers, 736 business-peer pairs, prices, SEC filings | Done | `data/team` (accepted research snapshot) | 34 |
| Relationship engine and divergence events | Done | `econometrics`, `pairs`, `research` | 34 |
| Research study: Model A versus SEC-augmented Model B, thirty verified models | Done; B's improvement not established on 2022–2023 | `research`, `ml` | 34 |
| Plan-ladder backtests (Baseline 0, Baseline 1, Model A, Model B) on development years | Done; freeze `2266d696…` | `backtest`, [BACKTEST_RUNBOOK.md](BACKTEST_RUNBOOK.md) | 35–42 |
| Forecasters (Goal 1): pre-registered bagged B+rule+ou, best observed B+rule+ou+track | Done | `forecast`, [FORECASTING_AND_BOOK.md](FORECASTING_AND_BOOK.md) | 75–94, 114 |
| Trading book (Goal 2): selection, close execution, exits, residual sleeve, risk | Done; adopted design | `book` | 95–112, 110d |
| Agent desk: pair news analyst, debate, risk judge, position monitor | Done; only the monitor exit is used | `agents`, [AGENT_DESK.md](AGENT_DESK.md) | 109–110d, 112c–d |
| Input pipeline and reproduction checks | Done | `pipeline`, `scripts/verify_book.py` | 115 |
| Overall overfitting audit (PBO, deflated Sharpe) | Done | `scripts/overfitting_audit.py` | 113 |
| Blind human review of 50 agent cases | **Open:** the group fills in the answers | [agent_review/](agent_review/review_cases.md) | 113 |
| 2024–2025 company-news source | Done: TickerTick, adopted with a reported limitation (× 4.8 denser than FNSPID) | [NEWS_2024_2025.md](NEWS_2024_2025.md) | 116–116d |
| Final-test readiness: period switch, news adapters, report script, research-layer final-test mode (rehearsed) | Done; only the plan-ladder rerun on 2024–2025 is still to build | [FINAL_TEST_RUNBOOK.md](FINAL_TEST_RUNBOOK.md) | 117, 118 |
| Research freeze manifest | **Draft** `4c410439…`: owner review | [FREEZE_MANIFEST.md](FREEZE_MANIFEST.md) | 113, 115 |
| Final test 2024–2025 | **Locked** until the owner's unlock record | — | 42 |
| Research app (eight pages, including the adopted book) | Done (work stream 2, plus the adopted-book page); deployed from the `deploy` branch | `app/research_app.py`, [app/README.md](../app/README.md) | — |

## Open items

- [ ] Group: complete `docs/agent_review/review_answers.csv` (claim support Y/P/N, own scores).
- [ ] Plan-ladder rerun on 2024–2025 (step 8 of the [final-test runbook](FINAL_TEST_RUNBOOK.md)); optional, the
      adopted book is the primary Goal 2 result.
- [ ] Refit the bagged forecasters without Model B's 28 inert catalyst columns, as new
      labelled variants.
- [ ] Plan ladder's Full System rung under the frozen Decision 36 policy: needs the controller
      adapter (Decision 40); otherwise it is reported as not run.
- [ ] Owner review of the freeze manifest, then an owner-written unlock record citing its
      SHA-256.

## Final test, after the unlock

1. Capture 2024–2025 prices for the same 250 issuers, 8-K filings through the existing SEC
   pipeline, and company headlines from the chosen news source.
2. Build the 2024–2025 events and every book input with the frozen code
   (`python -m structural_break.pipeline.build_inputs plan` lists the order).
3. Refit the forecasters walk-forward exactly as in selection; no parameter is retuned.
4. Report Goal 1 (AUC, log loss, Brier) and Goal 2 (the adopted book, the same book without
   the monitor exit, and the plan ladder), once.
5. Any change after viewing a 2024–2025 result is a new, separately labelled experiment.

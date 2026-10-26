# Final-test runbook (2024–2025)

The final test runs once, after the owner's unlock record, on the frozen code and design.
Status per step: **Ready** (code exists and is tested), **Build** (still to be written, with
an estimate), **Owner** or **Group** (a person's action).

## Principles

- **Separate checkout.** The final test runs in a fresh checkout of the frozen commit with its
  own `data/team` (the final-test workspace) and `outputs/`. Every path is relative, so the
  development results cannot be overwritten.
- **One switch.** `structural_break.periods.data_end()` returns 2023-12-31 until the decision
  log holds an owner unlock record that cites the freeze manifest's SHA-256, and 2025-12-31
  afterwards. Builders, forecasters, the book and the agent contracts read their end date
  from it; the news adapters refuse later windows while locked (Decisions 116, 117).
- **No retuning.** Every parameter is the frozen one; forecasters are refitted walk-forward
  exactly as in selection. Any change after a 2024–2025 result is seen is a new, separately
  labelled experiment.

## Steps

| # | Step | Status | Command or note |
|---|---|---|---|
| 0a | Group completes the blind review of 50 agent cases | **Group** | `docs/agent_review/review_answers.csv` |
| 0b | Owner reviews the freeze manifest | **Owner** | [FREEZE_MANIFEST.md](FREEZE_MANIFEST.md) |
| 0c | Owner writes the unlock record (template below) | **Owner** | in `docs/DECISIONS.md` |
| 1 | Research layer in final-test mode: capture 2024–2025 prices and SEC filings for the 250 issuers, extend relationship snapshots, build 2024–2025 events, labels and Model A/B inputs | **Build** (about 2–3 days of work plus compute; a rehearsal on 2022–2023 first) | the research protocol is hard-locked below 2024 by design (`final_test_locked: true`); it needs an unlock-gated final-test protocol and a pre-registered rule for joining the new price capture to the frozen 2004–2023 prices |
| 2 | Book inputs on the final-test workspace | **Ready** once step 1 exists | `python -m structural_break.pipeline.build_inputs plan` (walk-forward frame, SEC timing, 8-K news and tone, headline tone, news-exit results, features, OU, R1, costs, residual targets) |
| 3 | Forecasters refitted walk-forward through 2025 | **Ready** | `python -m structural_break.forecast.model_b_scores`; `python -m structural_break.forecast.harness run --specs B+rule+ou B+rule+ou+track --schemes recent:bag5` |
| 4 | Company headlines for open trades | **Ready** (adapter); source chosen in Decision 116 | `intelligence.news_sources`; capture only the legs and dates of the book's open trades (a few thousand queries, hours) |
| 5 | Monitor cases, FinBERT triage and the Gemma monitor run | **Ready** | the desk reads FNSPID up to 2023 and `data/external/news_final/headlines.parquet` for the unlocked years; `desk_runner build-monitor`, `scripts/agents/monitor_triage.py`, `desk_runner run --kind monitor` (about 1,100 calls, within the free tier) |
| 6 | Adopted book, the same book without the monitor exit, and the plan ladder | **Build** (small: a final-test report over the 2024–2025 span; about half a day) | the book code runs to `data_end()` already |
| 7 | Goal 1 and Goal 2 report, opened once | **Build** (small, with step 6) | AUC, log loss, Brier; Sharpe, CAGR, drawdown, turnover, costs |

## Unlock record template

```markdown
## 1NN. Owner final-test unlock record

I, the owner, have reviewed the research freeze manifest and unlock the 2024–2025 final test
for this manifest only: SHA-256 `<64-character hash from docs/FREEZE_MANIFEST.md>`.
```

The heading must contain "unlock record" and the body the exact SHA-256; `periods.unlock_record()`
checks both. A record that cites another manifest does not unlock anything.

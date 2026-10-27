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
| 1 | Research layer in final-test mode: spliced 2024–2025 prices, SEC metadata, registry, intelligence for new events, final-test evaluation and binding (Decision 118) | **Ready** (rehearsed: registry, splice and intelligence reproduce the frozen data) | `scripts/final_test_data.py market --archive …`, `sec`, `registry --workers 4`, `intelligence --archive …`, `evaluation`, `check` (about 8 hours, mostly the registry) |
| 2 | Book inputs on the final-test workspace | **Ready** | `python -m structural_break.pipeline.build_inputs plan` (walk-forward frame, SEC timing, 8-K news and tone, headline tone, news-exit results, features, OU, R1, costs, residual targets) |
| 3 | Forecasters refitted walk-forward through 2025 | **Ready** | `python -m structural_break.forecast.model_b_scores`; `python -m structural_break.forecast.harness run --specs B+rule+ou B+rule+ou+track --schemes recent:bag5` |
| 4 | Company headlines 2024–2025 | **Ready** | TickerTick (Decision 116d): the 2025-05-26 bulk file, then the live API from 26 May 2025; see [NEWS_2024_2025.md](NEWS_2024_2025.md) |
| 5 | Monitor cases, FinBERT triage and the Gemma monitor run | **Ready** | the desk reads FNSPID up to 2023 and `data/external/news_final/headlines.parquet` for the unlocked years; `desk_runner build-monitor`, `scripts/agents/monitor_triage.py`, `desk_runner run --kind monitor` (about 1,100 calls, within the free tier) |
| 6 | Adopted book and the same book without the monitor exit | **Ready** (rehearsed on 2022–2023) | `python scripts/final_test_report.py` (refuses while locked; `--rehearsal` runs 2022–2023) |
| 7 | Goal 1 and Goal 2 report, opened once | **Ready** (same script) | AUC, PR-AUC, log loss, Brier; Sharpe, CAGR with and without cash, drawdown, turnover, costs |
| 8 | Plan ladder (Baseline 0, Baseline 1, Model A, Model B) under the frozen Decision 36 policy | **Build** with step 1 | `structural-break-backtest` on the final-test workspace, after `final-test-gate` |

## Setting up the final-test checkout

```powershell
git worktree add ..inal_test <frozen commit>          # the commit pinned by the freeze manifest
robocopy data	eam ..inal_test\data	eam /E          # the frozen workspace
robocopy <archive>\sec_metadata\source_v3 ..inal_test\data	eam\sec_metadata\source_v3 /E
cd ..inal_test                                          # every later command runs here
```

`outputs/` starts empty in that checkout, so the development results cannot be overwritten.

## Unlock record template

```markdown
## 1NN. Owner final-test unlock record

I, the owner, have reviewed the research freeze manifest and unlock the 2024–2025 final test
for this manifest only: SHA-256 `<64-character hash from docs/FREEZE_MANIFEST.md>`.
```

The heading must contain "unlock record" and the body the exact SHA-256; `periods.unlock_record()`
checks both. A record that cites another manifest does not unlock anything.

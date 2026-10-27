# Research freeze manifest (DRAFT)

**Status: draft, waiting for the owner's review.** The final test (2024–2025) stays locked.

| | |
|---|---|
| Manifest | [freeze/research_freeze_manifest.json](freeze/research_freeze_manifest.json) |
| SHA-256 of the manifest file | `4c4104399b6fb4b38b3585e22446d6258e5d7b369ddd9f31bdf98a6bd355def7` |
| Code commit it pins | `3339ff8882c444541a74781d09bcb509f28b6331` on `p6/agent-layer` (clean tree) |
| Files pinned by SHA-256 | 128: every module of `pipeline`, `forecast`, `book`, `agents`, `decision`, `intelligence` and `backtest`, the scripts, the configs, and the book's data inputs |
| Built by | `python scripts/freeze_manifest.py` (Decisions 113 and 115) |

## What it fixes

- **The adopted design (Decision 110d):** R0 selection with the R1, mean-crossing and cost
  filters; close execution; 7.5 % per entry; take profit at |z| ≤ 1.0, no z-score stop, the
  half-life time stop, the 8-K news exit and the agent monitor exit; the residual sleeve; the
  4 % volatility target and the 200 % gross cap; cash interest.
- **The agent desk identities:** prompt versions, models, settings and the FinBERT triage.
- **The final-test protocol:** what is captured after the unlock, how the forecasters are
  refitted (walk-forward, no retuning), and what is reported for Goal 1 and Goal 2.

## Before the final test

1. The owner reviews this manifest (and may ask for changes; any change produces a new
   manifest and a new SHA-256).
2. The owner writes an unlock record in `docs/DECISIONS.md` that cites the SHA-256 above.
3. Only then are 2024–2025 prices, filings and headlines captured and the final test run.

Known limitation to report with the final result: the overall overfitting audit (Decision
113) finds a deflated Sharpe ratio of 0.86 and a PBO of 0.54 for the adopted book.

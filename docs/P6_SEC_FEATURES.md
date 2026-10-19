# SEC timing features and recent-news catalysts

Exploratory work pre-registered in [DECISIONS 47](DECISIONS.md),
[DECISIONS 50](DECISIONS.md) and [DECISIONS 51](DECISIONS.md); results in
DECISIONS 48, 53, 54, 56, 58, 60, 62 and 64. Each block is added to
v2's Model B and tested against B with the Decision 45 walk-forward (fit before
year Y−1, threshold on Y−1, score Y; 2010–2021 decide, 2022–2023 reference).
Nothing here changes the accepted v2 snapshot, its models or the frozen
Phase 6 policies.

## Results so far

| Block | Verdict | Primary measure (logistic, Brier vs B) |
|---|---|---|
| Filing timing (10 metadata features) | **Fails**, not adopted | +0.000036, 95 % [−0.000072, +0.000170], better in 5 of 12 years |
| Full-coverage v2 catalysts (Decision 47) | Not run: design replaced (Decision 50) | — |
| Recent-news catalysts per company (13 features) | **Fails**, not adopted (Decision 54) | +0.000010, 95 % [−0.000075, +0.000092], better in 7 of 12 years |
| FinBERT tone of the same recent news (7 features) | **Fails**, not adopted (Decision 54) | +0.000078, 95 % [−0.000005, +0.000168], better in 6 of 12 years |
| Fresh-news entry filters (Decisions 55–58) | Replicate in direction, miss the corrected threshold | earnings filter +3.8 bps, negative-tone filter +2.2 bps per candidate (Holm p ≈ 0.08) |
| **Adverse-tone news exit E3 (Decisions 59–62)** | **Passes confirmation; candidate policy** | +6.1 bps per trade, 95 % [+1.4, +11.3], Holm p = 0.012, 6 of 6 years (2016–2021); 2022–2023 +2.2 bps, p = 0.24 |
| Graded sizing / sharper entry news (Decision 60) | Fails (Holm p = 0.084) | Z1 +1.6 bps, H2 +1.0 bps |
| News exit + entry filter (Decisions 63–64, post-hoc) | Chosen combination just misses (p = 0.070); all 12 positive | +2.4 bps over E3 alone, +7.6 bps vs frozen (2016–2023) |
| News exit on model trades (Decision 64, post-hoc) | Positive for all four models | XGBoost B +8.3 → +12.0 bps per trade (2010–2023) |

## How the recent-news extractor works

1. **Window.** For every h20 model event and each company in the pair, find
   the 8-Ks that became public in the three NYSE sessions before the
   divergence signal (conservative SEC availability times). Keep the latest
   two. About 35 % of events have such news on at least one company.
2. **Evidence.** From each filing take the first chunk of the 8-K that states
   an Item (for example "Item 2.02 Results of Operations") and the headline
   chunk of its press release (EX-99), parsed from the stored SEC archive.
3. **Extraction.** Gemma (`gemma-4-26b-a4b-it`, free tier) labels each
   company's news: event type, direction, materiality. It cites numbered
   sentences that are replaced by the exact source text, and answers that
   break the rules (for example a category with no matching term in the cited
   sentences) are retried with a specific correction or stay UNKNOWN.
   Identical company/filing sets share one call: 9,209 calls in total.
4. **Features.** Thirteen per event: material, negative, positive, earnings
   and other corporate news for each company; one-sided material news; and
   whether the company whose stock moved more had material news, and whether
   that news matches the direction of its move.
5. **Tone (Decision 51).** The same packs are also scored locally with v2's
   pinned FinBERT: each company's net and negative tone, the contrast, and the
   moving company's tone and whether it agrees with the move. v2's own
   FinBERT features stay in Model B unchanged.

Why not the v2 catalyst pack: 82 % of its text came from quarterly reports
filed about two months before the divergence, mostly financial tables, and it
labelled the pair as a whole (DECISIONS 50).

## Running the extraction

From the repository root on the machine that holds the v2 workspace:

```powershell
powershell -File scripts\catalyst_start.ps1      # start or resume both jobs and the watcher
powershell -File scripts\catalyst_progress.ps1   # progress of both jobs and the evaluation
```

The start script runs three detached processes: the Gemma news job, the
FinBERT tone job (with the v2 environment, which has `torch`) and a watcher
that builds the features and runs the evaluation below once both jobs have
finished, logging to `outputs/news_v1/evaluate.log`.

Packs and records live in `outputs/news_v1/`. The job can be stopped and
restarted at any time; finished packs are skipped. Per-minute quota limits
are waited out, a spent daily quota pauses the job until midnight Pacific
time, and packs that fail on server errors get three automatic retry passes
before the job stops. The PC must stay awake.

The progress report splits UNKNOWN into `UNKNOWN_ABSTAINED` (a valid model
answer), `UNKNOWN_REJECTED` (answers failed validation) and
`UNKNOWN_SERVER_OR_OTHER`.

## Evaluating once the extraction has finished

```powershell
.venv\Scripts\python.exe -m structural_break.experiments.news_coverage features --workspace-root data\team --output outputs\news_v1
.venv\Scripts\python.exe -m structural_break.experiments.p6_sec_features evaluate --workspace-root data\team `
  --features outputs\news_v1\news_features.parquet `
  --features outputs\news_v1\tone_features.parquet `
  --features outputs\p6_sec_features\timing_features.parquet `
  --simulation outputs\p6_improvement\walkforward\simulation_frozen_exit.parquet `
  --output outputs\p6_sec_features\news_walk_forward.json
```

The verdicts for `B_news` (Decision 50) and `B_news_tone` (Decision 51)
follow the Decision 47 pass rule; `B_news_text` and `B_news_timing` are
reported.

## Related trading test: half-life timeout (Decisions 52–53)

Replacing the frozen 20-session timeout with two half-lives (1–120 sessions)
**fails**: over 2010–2021 it changes net return per trade by −8.8 bps, 95 %
[−20.6, +3.0], better in 4 of 12 years. Half of the longer-held trades ended
at the adverse stop. Module: `structural_break.experiments.p6_halflife_exit`.

# SEC timing features and recent-news catalysts

Exploratory work pre-registered in [DECISIONS 47](DECISIONS.md) and
[DECISIONS 50](DECISIONS.md); results in DECISIONS 48. Each block is added to
v2's Model B and tested against B with the Decision 45 walk-forward (fit before
year Y−1, threshold on Y−1, score Y; 2010–2021 decide, 2022–2023 reference).
Nothing here changes the accepted v2 snapshot, its models or the frozen
Phase 6 policies.

## Results so far

| Block | Verdict | Primary measure (logistic, Brier vs B) |
|---|---|---|
| Filing timing (10 metadata features) | **Fails**, not adopted | +0.000036, 95 % [−0.000072, +0.000170], better in 5 of 12 years |
| Full-coverage v2 catalysts (Decision 47) | Not run: design replaced (Decision 50) | — |
| Recent-news catalysts per company (13 features) | Pending: extraction running | — |

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

Why not the v2 catalyst pack: 82 % of its text came from quarterly reports
filed about two months before the divergence, mostly financial tables, and it
labelled the pair as a whole (DECISIONS 50).

## Running the extraction

From the repository root on the machine that holds the v2 workspace:

```powershell
powershell -File scripts\catalyst_start.ps1      # start or resume (detached)
powershell -File scripts\catalyst_progress.ps1   # progress, rate, ETA, last log lines
```

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
  --features outputs\p6_sec_features\timing_features.parquet `
  --simulation outputs\p6_improvement\walkforward\simulation_frozen_exit.parquet `
  --output outputs\p6_sec_features\news_walk_forward.json
```

The verdict for `B_news` follows the Decision 47 pass rule.

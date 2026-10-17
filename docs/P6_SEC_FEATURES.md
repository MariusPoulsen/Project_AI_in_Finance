# SEC timing features and full-coverage catalysts

Exploratory work pre-registered in [DECISIONS 47](DECISIONS.md); results in
DECISIONS 48. Both blocks are tested against v2's Model B with the Decision 45
walk-forward (fit before year Y−1, threshold on Y−1, score Y; 2010–2021
decide, 2022–2023 reference only).

## Results so far

| Block | Verdict | Primary measure (logistic, Brier vs B) |
|---|---|---|
| Filing timing (10 metadata features) | **Fails**, not adopted | +0.000036, 95 % [−0.000072, +0.000170], better in 5 of 12 years |
| Full-coverage Gemma catalysts | Pending: extraction running | — |

## Why the v2 catalyst pilot produced only 15 catalysts

- The free tier allows 16,000 input tokens per minute per Gemma model. v2
  sent about 6,500-token prompts every 8 seconds, hit the limit within a
  minute, and its provider then refused every later call.
- Gemma rarely copies quotations or 64-character chunk IDs exactly, so about
  a third of the answers that did arrive failed citation validation.
- HTTP 500 errors were treated as final; `gemma-4-31b-it` returns them for
  almost every prompt of our size.

`catalyst_v3` keeps the v2 evidence packs, response schema, validation and
feature block, but has the model cite numbered sentences (`A1.3`) that are
resolved locally to exact source text, sends a compact prompt, paces tokens,
waits out quota limits and retries server errors. Version 3.1
([DECISIONS 49](DECISIONS.md)) also states the category-term rule, offers NONE
only when coverage is complete, gives each retry a specific correction, runs
three requests at a time and retries Google's frequent random HTTP 500s
quickly. On a 58-pack check about 90 % of packs end with a valid answer (a
catalyst, NONE, or the model's own UNKNOWN); most of the rest cite table
boilerplate as an event and are correctly rejected.

## Running the catalyst extraction

From the repository root on the machine that holds the v2 workspace:

```powershell
powershell -File scripts\catalyst_start.ps1      # start or resume (detached)
powershell -File scripts\catalyst_progress.ps1   # progress, rate, ETA, last log lines
```

The progress report splits UNKNOWN into `UNKNOWN_ABSTAINED` (a valid model
answer), `UNKNOWN_REJECTED` (answers failed validation) and
`UNKNOWN_SERVER_OR_OTHER`.

The job reads the v2 event checkpoints read-only and writes one record per
distinct evidence pack under `outputs/catalyst_v3/cache/`. It can be stopped
at any time (end the `python.exe` running `catalyst_coverage run`) and
restarted; finished packs are skipped and transient failures are retried.
When the daily quota is spent it pauses until midnight Pacific time. The PC
must stay awake: sleep pauses the job, and it resumes on its own when the PC
wakes.

`--retry-invalid` (passed to `catalyst_coverage run`) reattempts packs whose
answers failed validation. Raw progress as JSON:
`python -m structural_break.experiments.catalyst_coverage status --output outputs\catalyst_v3 --json`.

## Evaluating the catalysts once the h20 packs are done

```powershell
$ckpt = "<v2 workspace>\data\research_v2\intelligence\development_clockgap_v2\events"
$inputs = "data\team\artifacts\research\research_evaluation_16a431c4fea73ffd35f56062\model_inputs.parquet"
.venv\Scripts\python.exe -m structural_break.experiments.catalyst_coverage features --checkpoints $ckpt --model-inputs $inputs --output outputs\catalyst_v3
.venv\Scripts\python.exe -m structural_break.experiments.p6_sec_features evaluate --workspace-root data\team `
  --features outputs\p6_sec_features\timing_features.parquet `
  --features outputs\catalyst_v3\full_catalyst_features.parquet `
  --simulation outputs\p6_improvement\walkforward\simulation_frozen_exit.parquet `
  --output outputs\p6_sec_features\catalyst_walk_forward.json
```

This scores `B_full_catalyst` and `B_full_catalyst_timing` against B under
the same pass rule. Packs still UNKNOWN stay UNKNOWN in the features.

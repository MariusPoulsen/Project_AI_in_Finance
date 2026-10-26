> **Historical snapshot at `a02aadf`.** Current rules/status are in [the active documentation](../README.md). Original receipt identities and past statements below are retained.

# Research v2 development protocol

Base design freeze: 2026-10-06, before constructing the added observations.
The user delegated research design and implementation, with the goal of improving
Model B over Model A. This permits a separate experiment, not modification of
the completed 28-pair Phase 4 artifact or opening the 2024–2025 final test.
Subsequent development amendments below are separately disclosed; they are not
represented as decisions made before the initial quantitative label freeze.

## Population and target

Use the frozen business-peer roster of 250 domestic issuers in 40 groups and
736 fixed candidate pairs. Preserve the original 28 orientations; order
added pairs by frozen security identifier. The public-data roster is explicitly
conditioned on surviving issuers and current business classification. It is not
a historically complete investable universe. Missing prices/identity continuity
are reported exclusions, never repaired or selected using outcome labels.

Capture 2004–2023 Yahoo history, with 504 common-session monthly formation.
Forecast all deduplicated fresh |z|≥2 estimable divergences. Preserve actual
ACTIVE flags and report the ACTIVE subset separately; forecasting an ineligible
relationship does not make it a tradable opportunity. This deliberately changes
the prediction population and is not a replacement headline trading ladder.
Its ACTIVE slice retains the broad registry's episode construction; it is not
a separately rebuilt ACTIVE-only trading registry.

ACTIVE retains the original pointwise 5% diagnostic rule. The roster and broad
forecasting population are not screened on these p-values. No familywise error
control is claimed across 736 pairs; the ACTIVE slice remains exploratory.

The primary target is an observed close within |z|≤0.5 before the same-side
adverse boundary of 3 or 20 sessions. Coefficients remain entry-frozen, episodes
remain nonoverlapping and need a reset, and the full horizon controls embargo.
Predeclared 10- and 30-session sensitivity registries use their own horizon,
deduplication and embargo. Do not select the best horizon as a headline result.

## Evaluation

Forward tuning years are 2018 and 2019, with fitting histories from 2006 and
full-window purging before each fold. Fit final classifiers through 2019;
calibrate on 2020–2021; assess on 2022–2023. All boundary windows are purged by
the full horizon even if convergence happens earlier. The already observed
original 28-pair assessment results are development information, not a newly
untouched test. No source capture or outcome construction after 2023 is needed.

Primary estimators are strongly regularized logistic A and B, selecting among
C=0.01,0.1,1 by mean forward Brier loss. Small, identical-budget XGBoost grids
are secondary. Models A/B share quantitative columns, every observation,
target, tuning dates, preprocessing rules and calibration policy. B adds source
features. Ablations B-metadata, B-tone, B-catalyst and B-both are all reported; B-both is
predeclared primary, not chosen after assessment. Fit imputers/scalers inside
each fitting period only. A fitted prevalence baseline is also reported.

Report raw and calibrated Brier, log loss, ROC/PR AUC, pair/issuer-balanced
losses, yearly/industry/ACTIVE slices and unchanged 0.65 selection coverage.
Quantify the paired B−A loss difference using 2,000 seeded calendar-quarter
block resamples with all issuer-connected events kept in each selected block.
Only eight assessment blocks exist: disclose the limited uncertainty estimate.
Report the number of positive outcomes and distinct issuers/periods. One-class
metrics stay undefined. A point estimate below zero is suggestive; a stronger
improvement claim needs its paired interval below zero, coherent secondary
metrics and adequate coverage. Economic profitability awaits the shared P6
execution simulator; forecast improvement alone is not trading profitability.

The research-only reporting completion supplies these promised losses and
slices for all ten bundles per horizon. Natural-log loss uses float64 machine
epsilon clipping internally; stored probabilities and tuning Brier losses stay
unchanged. Pair-balanced loss averages each observed pair's mean loss equally;
issuer-balanced loss averages each observed issuer's mean loss equally, counting
both legs. These are assessment sensitivities, not training reweighting.
Raw and calibrated descriptive reports retain every frozen business group,
assessment year and ACTIVE level, including zero-row counts; sector reports use
observed assessment sectors. Each slice has its own event/positive/pair/issuer
denominators, discrimination, calibration and unchanged 0.65 coverage. Empty
and one-class ROC/AP remain null. Paired Brier delta slices cover observed groups.
Native verification reconstructs these reports; no subgroup chooses a model.

## Affordable text features

The `sec-item-recency-v1` metadata block records each leg's admissible recent
8-K counts, earnings Item 2.02 and management Item 5.02 indicators, filing/periodic
recency, asymmetry and explicit metadata-coverage UNKNOWNs. It needs no LLM
calls. Unknown source coverage must not be encoded as confirmed absence.

SEC acceptance time, issuer continuity and exact source provenance determine
admissibility. Local FinBERT produces positive/negative/neutral financial tone,
not catalysts or reversion probabilities. Token-window coverage is explicit;
unknown is not neutral. Freeze ProsusAI/finbert revision
4556d13015211d73dccd3fdd39d39232506f3e43. The initial preprocessing was
`exact-sentence-nonoverlap-wordpiece-v1`; the FIT-input amendment below is
separately versioned and does not rewrite that pre-label freeze.
Its weights were published in 2020; retrospective use on earlier text is a
disclosed modern-extractor limitation, not historical model availability.

### FIT-input preprocessing amendment

After quantitative cohorts and their counts had been constructed, but before
any research model assessment or Model B fit, authorize
`sec-sentence-quality-wordpiece-v2` for a new immutable evidence batch.
The decision inspects only 19 source events in the FIT period, dated
2006-01-03/04. It reads no outcome labels, model scores, calibration/assessment
text or final-test data. The tokenizer-only diagnostic made no network or
neural-inference calls. Its proof is
`.acceptance/finbert_preprocessing_input_audit.json`, SHA-256
`294c01de161c47ad16e06ad07ac89ae7fbf1f24ddf7c775b18b4ec97fc617855`.

| Input diagnostic | Legacy v1 | Exact-line quality v2 |
| --- | --- | --- |
| Raw windows under each policy's segmentation | 8,720 | 8,292 |
| Windows retained by the bounded scoring plan | 4,189 | 1,259 |
| Median window WordPieces | 4 | 14 |
| Retained tokens / unchanged full-source tokens | 26,109 / 39,879 | 20,957 / 39,879 |
| Raw-token retention | 65.5% | 52.6% |
| UNKNOWN issuer legs | 2 / 38 | 2 / 38 |

Raw-window denominators differ: legacy splits newlines plus punctuation;
quality-v2 uses physical lines. Both have the same 39,879 raw tokens. Production
quality-v2 excludes 7,033 windows/18,922 tokens with no budget omissions in this
sample and one empty chunk. All nineteen genuine legacy tone records replay
exactly. The production receipt is
`.acceptance/finbert_quality_v2_plan_acceptance.json`, SHA-256
`ca0113d09e9c1d12a1d61b6286ad44fd58626516bfbd89e7cc1b2fe8f0d3f407`.

A trimmed physical line qualifies with at least two alphabetic words of two or
more characters and terminal `.`, `!` or `?` (optional closing quote/bracket),
or at least six such words and alphabetic/(alphabetic+numeric) word ratio at
least two thirds. There is no line joining or within-line punctuation splitting;
score the first 64 eligible windows per chunk in source order. The guard keeps
short prose such as `Sales fell.` without concatenating table rows. Exact source offsets and
the full raw-token denominator remain attached to the inference inventory.
Rejected, truncated and budget-unscored tokens remain explicit coverage gaps;
a leg with no eligible text remains UNKNOWN. The guard is lexical, not a
semantic narrative classifier: signature captions and other weak prose can
remain. The narrow earliest-FIT sample is not representative corpus validation.
Fewer windows do not prove lower padded attention cost, inference time or better
predictions. FinBERT weights and the deterministic SEC source selector do not
change.

Preserve the legacy domain default, its proofs and exact caches. The research
CLI defaults to `sec-sentence-quality-wordpiece-v2`; legacy reproduction uses
`--sentiment-preprocessing exact-sentence-nonoverlap-wordpiece-v1`. The distinct
`development_quality_v2` replacement launched at 2026-10-07 05:17:15 UTC only
after freezing code at committed `2dd54bcb`. Guarded startup froze its own
inputs/schedule at 05:19:55 UTC before event processing. After an operational
SEC-cache failure, resume 1 launched at 08:58:15 UTC with these exact inputs and
was deliberately stopped at 09:40:28 UTC during preserved-checkpoint replay.
Keep the original partial batch immutable and reuse verified source/Gemma caches; new sentiment policy identities create new
tone caches. Quantitative pairs, labels, dates, estimator grids, the 0.65
threshold and the 500-event catalyst schedule remain unchanged. Full features,
Model B fitting and assessment still await completion.

The amended builder also aggregates compact feature rows instead of retaining
all full packs in memory. The same FIT diagnostic estimates 1.37 GB of pack-only
retention across 37,421 events under independent JSON-reloaded strings, excluding
other process overhead. This is an extrapolation, not measured live RSS.
Memory changes must reproduce the same immutable event/source inventories,
feature values and ordering; they do not authorize evidence or cohort changes.

The combined amendment passed 100 focused sentiment/intelligence/CLI tests,
whole Ruff/format checks for 133 files, strict mypy for 66 source files and four
final native-model integration tests in 83.74 seconds. Genuine quality-v2 CPU
inference on ADBE/ADSK at the first FIT event, 2006-01-03T21:00Z, passed in
31.766 seconds with exact cache replay, all five pinned asset hashes verified,
388 existing legacy cache files unchanged and no network/LLM/outcome access.
Its proof is `.acceptance/finbert_quality_real_sec_smoke.json`, SHA-256
`582866c4f633775a41532b3b0a20914dbe1f13975848d27908034bf0a2059c1c`.
This is a single-source engineering gate, not a representative NLP study or a
speed comparison with the different V/MA legacy smoke. The amended commit and
batch inputs were frozen at `2dd54bcb` and both hosted runs passed. The quality
generation is now deliberately stopped and preserved; the new parsing amendment
and batch transition below still require their own gates. Full source/tone generation and model assessment
remain separate, incomplete gates.

## Source-only parsing amendment

The post-cohort operational amendment in DECISIONS section 22 precedes every
actual A/B assessment. A frozen-source, API/inference/outcome-free profile of
three completed FIT 2006 events exactly replayed packs and stored tone features:
8.052 seconds cold versus 1.310 hot for their pack rebuilds, with parsing about
82% of cold cumulative work. The concurrent host and unflushed OS cache prevent
a full-job speedup or ETA claim. It does not change evidence, text policy,
cohorts, labels, grids or the fixed catalyst schedule.

The implemented cache holds 128 parsed inventories in RAM with private
operation-local spill. Each builder/verifier begins empty and independently reconstructs
verified raw sources once per distinct inventory; verification must not trust a
builder-produced parser cache. All raw/SGML/cutoff checks remain in place.
Ninety-five focused checks and eighteen exact pack reconstructions passed in
the forced-one-frame source-only benchmark: baseline parsing 22 calls, new
builder eleven, and a fresh verifier-style operation its own eleven. This is
not the full verifier/job or a measured production speedup. The amended cache also passed four native model/evidence integration tests in
128.76 seconds, whole Ruff/142-file format checks and default mypy for 77 source, script and app
files. These are engineering/synthetic integration checks, not actual study
fits. The final amended source still requires its own exact-head hosted CI.
A new source/input
freeze and exact-head CI are pending. The controlled
old-prefix stop preserves all 1,494 quality checkpoints. Planned immutable batch
`development_primary_v2` requires a byte-inventory/copy receipt and full raw-
source reconstruction before adopting that prefix. Transition, launch, actual
fits and primary/main promotion remain pending; final outcomes stay locked.

Before actual Model B fits, research v2 prepares
`sec-json-clock-envelope-v3` for SEC JSON availability. Among 250 matched
successful cached captures with hash-verified source headers, 186 JSON timestamps
matched SGML acceptance times; 49 JSON `Z` values were themselves four hours
later and 15 five hours later. This is source timestamp lag, not an error caused
only by parsing naive timestamps. No premature case occurred in that sample.
This is a 250-capture diagnostic, not a full audit of the 89,657 filing rows or
proof that every other acceptance timestamp is correct.

For absent or zero JSON offsets, including `Z`, consider both UTC and New York
wall-clock interpretations, plus the inverse UTC-to-New-York-wall-clock
candidate for the observed source lag. Preserve their lower and upper bounds
and admit evidence only at the upper bound; v3 leaves the conservative v2 upper
bound unchanged and widens its lower bound. Explicit nonzero offsets retain
their exact stated interpretation. Missing acceptance times stay UNKNOWN; filing
dates never recover them. If a relevant filing's availability interval crosses
the signal cutoff or the 30-, 180- or 400-calendar-day selection boundary, the
issuer's affected evidence coverage stays UNKNOWN, so uncertainty cannot prove
absence. These conservative bounds can postpone otherwise admissible evidence.

Rebuild SEC metadata in a new immutable `sec_metadata/source_v3` using only the
hash-verified response bytes and sidecars of `source_v1`, with network access
blocked. The new manifest binds the availability policy and implementation; a
separate replay receipt binds the exact parent manifest, complete raw inventory,
frozen code and derived manifest. Recompute normalized metadata and features;
do not relabel or overwrite old source, evidence or original Phase 4 artifacts.
See [the replay policy](SEC_METADATA_RECAPTURE_HISTORY.md) for execution and provenance.
The completed source-v2 metadata replay is preserved: its narrower interval
excluded those 64 earlier SGML headers below its lower bound. Its successful
hash/source replay does not establish SGML admissibility. Actual fitting remains
subject to the corrected source/inference checks and completion of its feature
batch, rather than relying on source-v2 metadata alone.
The v3 metadata replay completed under frozen code `100e1e48`, with identical
raw sources and filing population. Metadata reconstruction confirms its upper
bound is unchanged for every filing. The separate canonical replay passed for
250 cached accession inventories, with all sampled SGML headers inside the v3
envelope and unchanged original response/retrieval identities, without HTTP.
The genuine pinned CPU FinBERT smoke on V/MA SEC text at 2016-01-08 also passed:
six chunks, 210 windows and exact cache replay. These engineering checks do not
constitute a full 89,657-header audit or complete historical NLP study.
Legacy batch `development_v3_100e1e4` is confirmed STOPPED and incomplete as
of 2026-10-07 05:10 UTC. Its session/process are absent; the log ends at 1,494
completed checkpoints at 03:33 UTC without traceback or terminal manifest.
The cause is unknown, not recorded as an intentional stop or confirmed FAILED
publication. Preserve those partial records. New batch `development_quality_v2`
first launched at 2026-10-07 05:17:15 UTC from frozen `2dd54bcb`; its input SHA-256 is
`cf19099ac57ee7f5ba6ab3e37daa6d46dda49a7f4dc63893d6a06d1063f78fea`.
That first quality attempt exited 1 at 1,494 checkpoints because three valid
cached response/sidecar pairs lacked a completion manifest. A preserving repair
completed that one unregistered SEC inventory, with one missing exhibit fetched;
the frozen registry/policies/input manifest, original responses and retrieval
timestamps were unchanged.
Resume 1 launched at 08:58:15 UTC under the exact frozen code/inputs. Root
deliberately stopped its worker at 09:40:28 UTC after 1,209 preserved-prefix
replays, before any new acquisition/inference branch. All 1,494 old checkpoint
bytes remain preserved; the new operation-local parsing transition is pending. This does not explain the
earlier legacy stop. It retains the full 37,421-event union and separate
500-event catalyst schedule. Full features and all actual matched A/B fits
remain pending, with no predictive gain established. Operational receipts are
listed in [the runbook](INTELLIGENCE_RECOVERY_HISTORY.md#sec-text-inference-and-fitting).

Use free Gemma for a smaller bounded catalyst pack with exact JSON schema,
issuer/leg/timestamp checks, category-cue and exact-quote grounding, strict local
validation, bounded retries and quota-stop. Processing order is chronological,
without labels or model scores. Invalid, unavailable or budget-unprocessed rows
stay UNKNOWN on the matched cohort. Cache exact chunk/model/config identities.
Use all four predeclared ablations to distinguish text signal from retrieval
coverage. FinBERT ranking must not silently replace the deterministic source
selection or omit low-tone chunks from the inference inventory. Flash remains
configured for future adversarial reasoning agents. No paid API is enabled.

The `year-business-group-balanced-gemma-pilot-v1` catalyst schedule uses the
separate `--catalyst-max-events` limit, default 500. Hash the full allowlisted
event identities/timestamps and frozen business-group mappings before selection;
never read targets or scores. Cover each available UTC year from 2006–2023, then
each still-unrepresented available business group. Fill remaining slots by the
lowest selected year, group and year/group-cell counts, using fixed SHA-256
tie-breaks. Within each cell, rank identities/timestamps by fixed SHA-256; process
selected IDs in timestamp/pair/ID order. Reserve the configured retry allowance
for every selected event, including cache hits, and cap the selected count by
the provider's bounded call budget (at most 1,000 calls per invocation).

The manifest binds `catalyst_schedule.json`, its hash, exact selected IDs,
year/group margins, missing years/groups and call upper bound. Report scheduled
and actually processed coverage separately. Metadata and FinBERT source
processing can cover the full quantitative registry; unscheduled catalysts stay
UNKNOWN on the matched cohort, even if shared caches contain earlier successful
extractions. The evidence-v2 schema retains the complete bounded source pack
and a separately frozen catalyst pack; unselected catalyst packs are empty.
The pilot's representative-NLP-study flag remains
false. Report each ablation; 500 scheduled events do not imply complete Gemma
coverage or establish Model B improvement. The broader `--max-events` option
still limits text-source acquisition and creates a partial text batch.

Checkpoints and successful caches avoid ordinary repeat calls. The provider's
counter is not a durable cumulative budget across restarts or separate batches:
an interrupted attempt may be repeated if its checkpoint was not saved.

The official [FinBERT card](https://huggingface.co/ProsusAI/finbert) documents
financial-tone classification. Google's [pricing](https://ai.google.dev/gemini-api/docs/pricing)
lists free Gemma service; [quotas](https://ai.google.dev/gemini-api/docs/rate-limits)
are project-specific and actual capacity is not guaranteed.

## Reproducibility and limits

Write immutable source/protocol/roster/code manifests before constructing labels.
New research versions live in a separate workspace and database. Registered
generations are hash-verified; resume cached work rather than recapture silently.
CI uses deterministic fixtures and no real API or model-weight download.
Hosted CI for frozen `100e1e48` passed the complete Windows/Linux regression
jobs and Linux Colab bootstrap in
[run 37451417275](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37451417275).
The reporting, quality-v2 preprocessing and compact-union changes passed their
focused/local gates above and froze at `2dd54bcb`. Both new committed hosted
runs passed. They do not rewrite the stopped legacy batch's frozen source or
partial records.

Hosted CI for frozen `2dd54bcb` passed all Windows/Linux foundation jobs
and the Linux Colab/NLP bootstrap in
[PR run 37575503287](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37575503287)
and [branch run 37575496575](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37575496575).
The full structured result is `.acceptance/research_2dd54bc_hosted_ci.json`,
SHA-256 `4311287edfcd2aa8fc1f095ffae2b099ec549f9ee5207c1f74d9d26f8b2c111e`.
These checks cover the quality, reporting and compact-union amendments; they do
not establish complete historical feature coverage or predictive improvement.

Run the same package commands in local Python 3.11 and the Colab bootstrap.
Report negative or inconclusive comparisons without selecting favorable
companies, throwing away UNKNOWN observations, or inspecting the final test.

# Research v2 development protocol

Frozen design date: 2026-10-06, before constructing the added observations.
The user delegated research design and implementation, with the goal of improving
Model B over Model A. This permits a separate experiment, not modification of
the completed 28-pair Phase 4 artifact or opening the 2024–2025 final test.

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

## Affordable text features

The `sec-item-recency-v1` metadata block records each leg's admissible recent
8-K counts, earnings Item 2.02 and management Item 5.02 indicators, filing/periodic
recency, asymmetry and explicit metadata-coverage UNKNOWNs. It needs no LLM
calls. Unknown source coverage must not be encoded as confirmed absence.

SEC acceptance time, issuer continuity and exact source provenance determine
admissibility. Local FinBERT produces positive/negative/neutral financial tone,
not catalysts or reversion probabilities. Token-window coverage is explicit;
unknown is not neutral. Freeze ProsusAI/finbert revision
4556d13015211d73dccd3fdd39d39232506f3e43 and preprocessing before labels.
Its weights were published in 2020; retrospective use on earlier text is a
disclosed modern-extractor limitation, not historical model availability.

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
their exact
stated interpretation. Missing acceptance times stay UNKNOWN; filing
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
See [the replay policy](SEC_METADATA_RECAPTURE.md) for execution and provenance.
The completed source-v2 metadata replay is preserved: its narrower interval
excluded those 64 earlier SGML headers below its lower bound. Its successful
hash/source replay does not establish SGML admissibility. Actual fitting remains
blocked until the new envelope and canonical document replay pass fresh checks.

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
Run the same package commands in local Python 3.11 and the Colab bootstrap.
Report negative or inconclusive comparisons without selecting favorable
companies, throwing away UNKNOWN observations, or inspecting the final test.

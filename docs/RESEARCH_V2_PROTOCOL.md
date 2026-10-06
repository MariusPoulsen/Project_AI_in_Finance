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

Use free Gemma for a smaller bounded catalyst pack with exact JSON schema,
issuer/leg/timestamp checks, category-cue and exact-quote grounding, strict local
validation, bounded retries and quota-stop. Processing order is chronological,
without labels or model scores. Invalid, unavailable or budget-unprocessed rows
stay UNKNOWN on the matched cohort. Cache exact chunk/model/config identities.
Use all four predeclared ablations to distinguish text signal from retrieval
coverage. FinBERT ranking must not silently replace the deterministic source
selection or omit low-tone chunks from the inference inventory. Flash remains
configured for future adversarial reasoning agents. No paid API is enabled.

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

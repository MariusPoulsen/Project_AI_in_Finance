# Canonical project decisions

Research v2 is the authorized primary development workflow. The base scientific
freeze is dated 2026-10-06; later amendments retain their original timing and
provenance. This document states current rules. Past implementation records are
in [the decision history](archive/DECISIONS_HISTORY.md); archived rollout status
is not current status. See [STATUS.md](STATUS.md) for delivery gates.

## 1. Authority and precedence

Apply explicit user instructions, then this document, then the most specific
[component specification](specs/README.md). Use the software architecture
specification for integration and the project overview for broad product scope.
Resolve material conflicts before crossing the affected gate. The
[frozen v2 protocol](RESEARCH_V2_PROTOCOL.md) supplies the complete research rules.
Archived decisions govern reproduction of their original generations; they do
not replace the active v2 protocol. PDFs in `docs/archive/pdfs/` are source archives.

## 2. Product boundary

Build an AI-assisted statistical-arbitrage research and decision-support system
for US-listed equity pairs: divergence detection, calibrated reversion forecasts,
point-in-time SEC evidence, and eventually source-grounded adversarial agents,
a deterministic controller and a shared historical simulator. Controller statuses
are `CANDIDATE`, `REVIEW`, `NO TRADE` and `ABSTAIN`. No live order execution or
claim of deployable alpha is authorized.

## 3. Canonical repository/runtime architecture

Use Python 3.11, `uv`, the committed lockfile, a modular Python monolith and
DuckDB/Parquet. Streamlit calls typed services directly; domain logic belongs in
`src/structural_break/`. Canonical analytical writes are explicit batch jobs.
Ordinary app browsing is read-only. No HTTP service boundary is needed.

## 4. Canonical physical storage layout

V2 uses the separate `data/research_v2` workspace. Relative to that workspace:

```text
universe/source_v1/                 frozen issuers, pairs and classifications
market/source_v1/                   frozen development market capture
sec_metadata/source_v3/              corrected SEC clock envelope and provenance
intelligence/{batch}/               inputs, schedule, event checkpoints, features
cache/data/raw/sec/filings/          exact SEC response bodies and sidecars
artifacts/research/{version}/        registered quantitative/model generations
data/analytics/structural_break.duckdb
```

Pinned FinBERT assets live at project `data/cache/huggingface`. The original
workspace and its [storage contracts](archive/DECISIONS_HISTORY.md#4-canonical-physical-storage-layout)
remain available for explicit reference reproduction. Use exact generation
identities, never directory modification time. Immutable source/curated files,
DuckDB registrations and auxiliary artifacts retain checksums and lineage.
Generated workspaces, model weights, acceptance logs and credentials are ignored
by Git. `SB_WORKSPACE_ROOT` selects another workspace; an explicit CLI path wins.

## 5. Fixed working pair universe

The expanded v2 roster is frozen at 250 surviving domestic issuers, 40 business
groups and 736 candidate pairs. Retain the original 28 orientations below:
first leg is dependent `y`, second is `x`. Added pairs use frozen security identity
order. Do not test both orientations or select membership using outcomes.
Current business classifications and survivor conditioning are disclosed limits.

| # | leg_a | leg_b | Economic peer group |
|---:|---|---|---|
| 1 | KO | PEP | Beverages |
| 2 | HD | LOW | Home improvement retail |
| 3 | WMT | TGT | Large-format retail |
| 4 | MCD | YUM | Quick-service restaurants |
| 5 | ORLY | AZO | Auto-parts retail |
| 6 | TJX | ROST | Off-price apparel retail |
| 7 | XOM | CVX | Integrated oil & gas |
| 8 | COP | EOG | US exploration & production |
| 9 | V | MA | Card/payment networks |
| 10 | JPM | BAC | Large US banks |
| 11 | GS | MS | Investment banking / capital markets |
| 12 | SPGI | MCO | Ratings / financial information |
| 13 | ICE | CME | Exchanges / market infrastructure |
| 14 | CB | TRV | Property & casualty insurance |
| 15 | MET | PRU | Life insurance / retirement |
| 16 | PFE | MRK | Large-cap pharmaceuticals |
| 17 | BMY | ABBV | Large-cap biopharma |
| 18 | TMO | DHR | Life-science tools |
| 19 | ABT | BDX | Medical devices / supplies |
| 20 | UPS | FDX | Parcel logistics |
| 21 | CAT | DE | Heavy machinery |
| 22 | LMT | NOC | Defense primes |
| 23 | CSX | NSC | US freight railroads |
| 24 | DAL | UAL | US network airlines |
| 25 | TXN | ADI | Analog semiconductors |
| 26 | LRCX | KLAC | Semiconductor equipment |
| 27 | GM | F | US auto manufacturers |
| 28 | DUK | SO | Regulated electric utilities |

`pair_id` preserves orientation, for example `KO__PEP`. Pair membership does not
assert cointegration. Preserve the security approval provenance in
`configs/securities.yaml` and the original universe for reference reproduction.

## 6. Core time/data scope

Use daily end-of-day development prices from 2004 through 2023. A 504-common-session
formation warm-up permits eligible fitting events from 2006. Fit through 2019,
tune on forward 2018/2019 folds, calibrate on 2020–2021 and assess on 2022–2023.
Purge complete target windows at every partition/fold boundary. Keep the original
2014-source/2016–2021-fitting contracts when reproducing the reference study.
2024–2025 outcomes remain locked.

The user's equity-close information set uses the exact previous XNYS session's
VIX observation. Never include same-day VIX or carry an older observation across
a missing prior session. Preserve its source date and conservative 16:16
America/New_York observation proxy; historical CSV publication times remain unknown.
Static sector proxies and retrospective Yahoo adjustments are disclosed source
limits, not vintage classifications or adjustment feeds. Optional GDELT remains
current/demo enrichment with unknown publication time and no headline historical use.

## 7. Econometric relationship engine

Use monthly two-variable Engle–Granger estimation on log adjusted closes and
504 common sessions, with entry coefficients frozen for each episode. Daily
state uses the latest admissible snapshot. Retain the pointwise 5% diagnostic and
`ACTIVE`, `WATCH`, `RETIRED` lifecycle. Fresh divergence is |z|≥2; success is
|z|≤0.5 before the same-side adverse boundary of 3. The primary horizon is 20
sessions, with predeclared 10/30 sensitivities and full-window embargo.

The prediction population is deduplicated estimable fresh crossings, including
UNKNOWN evidence. Report ACTIVE separately as exploratory; do not silently
rebuild an ACTIVE-only cohort or interpret ineligible relationships as trades.
No familywise-controlled screening across 736 pairs is claimed.

Monthly estimation uses the latest 504 valid common observations on/before actual
XNYS month-end, recording the true formation endpoint without filling. ADF uses
a constant/AIC; KPSS a constant/automatic lags. I(1) compatibility requires level
ADF non-rejection, level KPSS rejection and first-difference ADF rejection at 5%;
first-difference KPSS remains a cross-check. Differences omit missing-session
transitions, and half-life AR(1) uses exact one-session pairs. Level tests retain
common-observation order; available-observation difference lags remain a disclosed
limitation. Do not add unspecified liquidity/stability or positive-beta gates.

The first invalid monthly attempt is WATCH and two consecutive invalid attempts
are RETIRED; statistical retirement can recover. Manual/lifecycle retirement needs
a declared date. Record every attempt. An unusable newest fit yields no daily
state in its next interval; never silently carry an older fit forward. Parameters
become effective at the next XNYS open. At refits, compare previous/current closes
under the same newly effective parameters; divergence, sign and velocity checks
never bridge missing sessions. A zero touch alone is not two sign crossings.

Events freeze entry alpha, beta, spread mean and standard deviation for their
entire target path. Later statistical WATCH/RETIRED does not censor a path;
declared lifecycle termination or unusable required prices does. Convergence needs
an observed close in the success band; jumping across equilibrium is insufficient.
Maintain one open episode per pair, then require an inside-entry-band reset before
a fresh outward crossing. Predictors use the current frozen fit and exact trailing
sessions without filling. Required undefined predictors make an event ineligible;
declared optional undefined predictors remain explicit NaNs.

## 8. Supervised ML definitions

A uses point-in-time quantitative features only. B adds the predeclared SEC
metadata, local FinBERT tone and guarded Gemma catalyst blocks. Compare identical
observations, targets, quantitative columns, chronology, tuning budgets, fitted
transformations and calibration policies. Raw text is not a classifier feature.

Calibrated logistic B-both versus A at 20 sessions is primary. Preserve logistic
C=0.01,0.1,1 selection by mean forward Brier loss, the identical-budget XGBoost
comparisons, all metadata/tone/catalyst/both ablations and 10/30 sensitivities:
ten bundles per horizon, thirty overall. Fit preprocessing within each fitting
period and calibrate independently. Retain the 0.65 reporting threshold and fitted
prevalence baseline. Report all comparisons; assessment never selects a winner.

Calibration retains the smoothed monotone Platt objective with nonnegative slope;
one-class/constant-score fits explicitly store a constant mapping. A numerical
SLSQP retry may solve the same objective after L-BFGS-B failure, but must be finite,
feasible, at least as good as the constant baseline and independently stationary
under per-observation unit-variance KKT checks. Solver failure never substitutes
an empirical prior for an identifiable two-class fit. Tree SHAP explains raw
XGBoost margins, not calibrated probability contributions or causal effects.

## 9. Historical event-evidence policy

SEC EDGAR is the canonical historical text source. Use exact issuer continuity,
raw source provenance, official SGML clocks and the conservative
`sec-json-clock-envelope-v3` admission bound. Missing/ambiguous coverage stays
UNKNOWN; filing dates cannot replace acceptance timestamps. Recent 8-K and latest
admissible 10-Q/10-K selection remain deterministic under the frozen evidence
policy. Optional contemporary news is not headline historical evidence. Historical
agents never browse the contemporary web. See [the source replay policy](SEC_METADATA_RECAPTURE.md).

The full evidence policy selects recent 8-K/8-K/A over 30 calendar days and the
latest admissible periodic 10-Q/10-K within 180 days, with a 400-day extension and
admissible amendments. Filter issuer/type/availability before lexical ranking.
Keep the frozen eight-chunk-per-leg and 32,000-character source-pack bounds;
the smaller catalyst pack is separately bounded. PDF-only exhibits remain
unsupported and a bounded pack is not exhaustive issuer knowledge.

## 10. Shared extraction and agent evidence

Admissible SEC text supplies structured catalyst extraction. B receives its compact
tabular representation; later agents receive the same underlying source chunks
and extraction plus B's quantitative state. LLMs do not overwrite stored
quantitative values or directly set controller status.

`NONE` needs complete bounded selected-source coverage and a valid absence
extraction; it means no supported catalyst in that evidence set, not proof that
the issuer had no event. Missing, rejected, unavailable or budget-unprocessed
processing is `UNKNOWN`. Self-reported extraction confidence is uncalibrated
certainty, not measured semantic correctness or reversion probability. Direction,
materiality and relevance still require independent human semantic evaluation.

## 11. Provider and text-model decisions

Keep provider/model configuration explicit and credentials in ignored environment
files or deployment secrets. V2 uses free Gemma `gemma-4-26b-a4b-it` with schema,
issuer, timestamp, category-cue and exact-quote grounding, bounded pacing/retries,
quota-stop and no paid API. Flash is reserved for later reasoning agents. Tests
use deterministic mocks and blocked sockets, with no credentials or weights.

Pin ProsusAI/finbert revision `4556d13015211d73dccd3fdd39d39232506f3e43`
and asset hashes. Tone is not a catalyst or reversion probability. Use the
separately versioned `sec-sentence-quality-wordpiece-v2` exact-line guard, first
64 eligible windows per chunk, full raw-token denominators and explicit excluded,
truncated and unscored coverage. Preserve the legacy domain default and caches.
Modern text models on earlier filings are a disclosed retrospective assumption.

## 12. Evaluation and future simulation

Report raw/calibrated Brier and log loss, discrimination, calibration, threshold
coverage, event/positive/pair/issuer denominators, balanced losses and descriptive
subgroups. Pair B−A losses using 2,000 seeded calendar-quarter block resamples;
only eight assessment blocks exist. Keep undefined one-class metrics null and
report negative or inconclusive results. Forecast gains do not prove profitability.

The future simulation ladder remains Baseline 0 → Baseline 1 → A → B → Full System,
with one execution/cost engine and capability-specific filtering. The broader v2
forecasting population does not rewrite this trading ladder. Economic, predictive
and agent-control claims remain separate.

Baseline 1 admits ACTIVE relationships; A/B add their frozen calibrated probability
thresholds. The Full System accepts only `CANDIDATE` for simulation. All rungs
share execution/cost assumptions apart from the capability-specific filter.

## 13. Final-test governance

Only explicit user authorization unlocks headline 2024–2025 outcome/performance
metrics after freezing universe/orientation, labels, features, estimators,
calibration, thresholds, evidence, prompts, controller, execution/cost assumptions
and code/data/config identities. Development acceptance, cleanup and main promotion
are not final-test authorization. Never retune after observing final results.

## 14. Deliverable ownership

Coding agents implement and verify the system and technical run documentation.
The user owns the academic report and presentation/video. Do not draft those
without an explicit request.

## 15–19. Original reference implementation

Original environment, ingestion, econometric, event/Model A and SEC/Model B
implementation decisions remain in the [decision history](archive/DECISIONS_HISTORY.md).
Use [reference runbooks](archive/README.md#original-experiment) and their recorded
source/config versions. Do not overwrite or reinterpret their immutable artifacts.

## 20. Delegated research v2 redesign

The user delegated redesign on 2026-10-06 to improve B over matched A. The
base protocol froze before constructing added labels. The exact-line FinBERT
amendment was decided after quantitative cohorts/counts existed but before
model assessment, using only nineteen earliest FIT source inputs and no outcomes,
scores or calibration/assessment/final-test text. Keep that timing disclosure and
its narrow-sample limitations. Full scientific terms and amendment diagnostics
remain in [the protocol](RESEARCH_V2_PROTOCOL.md); past receipts and rollout
chronology are archived. No predictive gain is established by engineering checks.

The 500-event `year-business-group-balanced-gemma-pilot-v1` schedule is target blind
and separate from full metadata/FinBERT processing. Unscheduled catalysts stay
UNKNOWN. Preserve selected IDs, year/group coverage and the 1,000-call upper bound
per invocation, including retry allowance. Restarts do not reconstruct a durable
counter of unsaved failed calls. A partial `--max-events` run is not the full study.

## 21. Promote completed research v2 as the primary version

The user authorized making completed v2 the default on GitHub `main`. Complete
the full feature generation, all three predeclared model evaluations, fresh native
replay of thirty bundles and required source/CI/app gates first. Publish readiness
with `structural-break promote-primary --pipeline-receipt PATH --ci-gate CI_PATH`
bound to genuine completed six-stage evidence and exact hosted-CI bytes. Publish
immutable `manifest.json`, `verification_receipt.json` and `hosted_ci_gate.json`;
the read-only app admits only checked publications. Publication does not merge
GitHub automatically, prove B superiority or unlock final outcomes.

Retain original Git history, source/config contracts and artifacts for reference
reproduction; its app remains `app/reference_streamlit_app.py`.

## 22. Source-only parsing amendment before model assessment

This engineering amendment preceded actual expanded A/B assessment. Preserve
all source, evidence, feature, cohort, label and schedule values. Use at most 128
parsed inventories in RAM plus private operation-local spill. Every independent
verifier starts empty and reconstructs each distinct verified raw inventory itself;
it must not trust a builder-generated parser cache. All raw-hash/SGML/cutoff and
coverage checks remain mandatory. Benchmarks establish narrow replay behavior,
not a measured whole-job speedup; their receipts remain in the decision history.

## 23. Detached, audited intelligence recovery

On 2026-10-10 the user authorized a detached feature build without ongoing chat
polling. Preserve registry `research_registry_0bd415d2a5af1f4891dc1f0d`, all
37,421 events, SEC `source_v3`, quality-v2 FinBERT, pinned assets, the frozen
500-event catalyst schedule, A/B definitions and the final-test lock.

Preserve the stopped `development_primary_v2` attempt and its 2,290 checkpoints.
Its baseline receipt SHA is
`b5c29ff2b0a9580fa2ab3c0a6ff7c5ed635c3ba2fb7f72bc3a19265ef1c26bbb`.
The parser repair collapses only verified exact primary/EX-99 logical-document
aliases, retaining original chunk IDs and every raw response/sidecar. Conflicting
issuer/time/URL/body/role/path claims still fail; no evidence budget changes.

Use distinct immutable batch `development_detached_v2`. Its explicit audit binds
the baseline, all checkpoint bytes, inputs differing only by builder code hash,
event identities, schedule, source/SGML clocks and validated stored extraction/tone
features. Copy bytes unchanged. Recheck the externally bound audit SHA, source/
parent files at startup and each checkpoint on load. Only that audited prefix may
skip repeated HTML/stored-tone replay. The audited builder writes a complete
manifest with independent verification explicitly pending and defers duplicate
final raw replay. Model fitting, native verification and publication still perform
unchanged fresh raw replay of every event; this audit is resumability evidence only.

Launch through `scripts/start_research_intelligence.ps1`, with file-backed logs,
atomic progress, a service-parent worker and durable exit status. Use
`scripts/check_research_intelligence.ps1` for manual status. The launcher does not
fit models, publish, retry failed jobs, unlock the final test or merge `main`.
Keep the live checkout frozen until its worker exits. Parallel repository cleanup
is prepared in an isolated checkout and is integrated only after the active job.

## 24. Bounded source prefetch and interrupted-connection recovery

On 2026-10-10 the user clarified that parallelism should accelerate the full
37,421-event feature computation. The preceding detached attempt exited 1 at
4,727 completed checkpoints with `RemoteDisconnected`; the exact failing request
was not recorded. Preserve its original bytes, logs and terminal receipts. Its
baseline is `.acceptance/detached_v2_failed_attempt_20261010T051843Z_6a54dac86d30/receipt.json`,
SHA-256 `0a23c5445e4c35353117087b870920406c85fdbb432c17cfa1c8ed94d524242c`.

The engineering design overlaps the next chronological event's SEC acquisition
and parsing with the current event's extraction and local tone scoring. Permit
only one outstanding source future, with one producer owning its HTTP pacing and
operation-local parser cache. The coordinator alone performs Gemma/FinBERT calls,
tone/extraction-cache writes, checkpoint publication, progress and canonical final
assembly. Share one CPU model; do not multiply model processes or provider budgets.
Inference batch size, window selection, pinned assets, evidence policy, population,
source-v3 clock envelope, catalyst schedule, A/B definitions and final lock stay fixed.
The opt-in `--source-prefetch 1` is operational and recorded in the launch plan.

Disconnected/incomplete public-source transfers use the existing bounded HTTP
attempt/backoff policy. Discard partial bodies; permanent HTTP errors and rejected
redirects remain hard failures. This adds no Gemma retries or model fallbacks.
Prepare and test changes in isolation, audit all retained checkpoints against the
frozen stopped-attempt baseline, and use new immutable batch `development_prefetch_v2`.
The audit permits only the engineering builder-code hash difference in scientific
inputs. Independent verification remains fresh raw replay. Do not claim a measured
whole-job speedup from synthetic concurrency tests or a cache-only replay benchmark.

## 25. Explicitly empty official acceptance clocks

On 2026-10-10 the source-prefetch attempt exited 1 after 6,835 checkpoints.
The user authorized continuation. Source-only diagnosis identified NOC accession
`0000950134-09-000321`, whose official submission has one top-level
`<ACCEPTANCE-DATETIME>` field containing only whitespace. Its raw response SHA-256
is `1ef7c17b421958602c140526c8d35183d10d619df40e6f02ec9fdd75c53718c4`.
This amendment follows quantitative cohort construction and counts, but precedes
expanded Model B fitting and A/B assessment. Diagnosis reads cached source and
event identities, without outcomes, model scores or final-test data.

Treat only a unique, genuinely empty top-level official acceptance field as
unavailable source text. Retain the selected accession, all response bytes and
sidecars, selected-filing denominators and every event. Exclude that accession's
primary/exhibit text before parsing, extraction or tone inference; mark its
affected leg's coverage gap explicitly. Other admissible sources can supply partial
evidence. Incomplete coverage cannot establish `NONE` or confirmed one-sided
absence. Never infer acceptance from filing/header/document dates, backfill an
older filing or neutral tone, drop an event, or relax the source-v3 clock envelope.
Frozen metadata-only features continue using the unchanged source-v3 JSON bounds.

Nonempty malformed values, duplicate acceptance markers and contradictory valid
clocks remain hard failures. The existing absent-marker policy is unchanged and
does not assert an exact verified SGML clock. Builder, checkpoint audit and fresh
independent replay apply the same empty-clock exclusion. The audit must reject a
saved checkpoint that uses excluded text or fails to disclose its coverage gap;
it cannot bless a changed feature value merely because old bytes were preserved.

Preserve the failed `development_prefetch_v2` source, logs and 6,835 checkpoints.
Freeze and test the repair, bind a new failed-attempt baseline and audit all retained
checkpoints before the distinct immutable `development_clockgap_v2` generation.
The registry, 37,421-event population, SEC source-v3 bytes, evidence budgets,
quality-v2 FinBERT, pinned assets, 500-event schedule, matched A/B definitions and
2024–2025 outcome lock remain fixed. Main promotion and independent raw/native
verification remain pending.

## 26. Two complete independent source reconstructions for matched horizons

On 2026-10-14, before expanded assessment results were available, the user
explicitly approved [the shared-source verification amendment](VERIFICATION_EFFICIENCY_PROPOSAL.md).
This supersedes section 23's requirement to repeat the identical complete text
reconstruction at every model fitting, native verification and publication step.

Run one genuinely complete, fresh 37,421-event raw-source reconstruction before
fitting, and a second independent complete reconstruction after all models finish
and before publication. Both must start with an empty private parser cache and
reproduce every evidence pack, stored text feature, source-clock/cutoff claim,
source inventory, coverage denominator and target-blind schedule. Neither can
trust builder parsing outputs or mint a receipt from sampling/checksums alone.

Bind the actual source commands, exits/logs, immutable proof bytes, registry,
features, complete checkpoint/raw inventories, verifier code/runtime and proof
purpose. Recheck every bound file checksum before each fitting/native stage.
Reject changed inputs, stale runtime/code, partial populations, substituted
receipts or use of a fitting proof as the final independent reconstruction.
Preserve all thirty fits and native/report/calibration/paired checks at the same
1e-12 prediction tolerance. Publication requires both genuine source passes,
all six actual model stages, current hosted CI and the real read-only app gate.

The dataset, source-v3 bytes, quality-v2 policy, provider schedule/budget, A/B
definitions, cohort matching, chronology, tuning, calibration, uncertainty and
final-test lock remain unchanged. Preserve the old run and all prior artifacts.
Prepare and test changes in isolation; replace the old frozen run only after
the new source passes its engineering and Linux/Windows/Colab CI gates.

Twelve complete reconstructions become two: ten expensive reconstructions are
removed, not ten scientific checks. This is an 83% reduction in reconstruction
count, not a claimed 83% whole-job runtime improvement. Hashing/fitting and
independent publication still require actual acceptance before main promotion.

### Four-core source verification execution

On 2026-10-15 the user explicitly authorized restarting the verification run and
using all four physical CPU cores to meet a 2026-10-16 midday deadline. This is an
execution change, with both complete source passes and all scientific gates intact.
An optional four-process verifier partitions events by the frozen business group,
balances target-free event counts, and restores the original canonical event order
before the unchanged complete source-inventory and feature-frame comparisons.
Each process starts its own empty private parser cache, retains at most sixteen
hot frames and uses one native-library thread. No builder cache is shared or used
as independent evidence. Only the coordinator can complete the full-population
comparison and source proof; a worker result or a benchmark sample cannot mint it.
Worker count is bound in proof bytes, runtime/command/launch receipts and progress.
The serial path remains reproducible. Changed verifier code needs its own source
freeze and genuine complete Linux/Windows/Colab CI before production cutover.

## 27. Colab support retired; parallel CI

On 2026-10-15, before the v2 assessment was published, the user retired Google
Colab as a supported platform: no group member uses it. `scripts/colab_bootstrap.py`,
`docs/COLAB.md` and the `colab-bootstrap` CI job are removed. Supported platforms
are local Windows and Linux with Python 3.11 and `uv`. Full release validation is
now `foundation` and `acceptance` on Linux and Windows plus the `nlp-runtime`
CPU PyTorch/Transformers install check; earlier references to Linux/Windows/Colab
CI gates are read as this set. Release evidence recorded with the earlier
`colab-bootstrap` job stays valid for its revisions. Archived documents keep
their historical Colab references.

CI runs pytest with one process per runner CPU and moves the synthetic CLI
acceptance checks into a parallel job. Test content, fixtures and blocked network
sockets are unchanged; this is an execution change with no scientific effect.
Package source under `src/` is untouched, so the computational identity of the
running v2 generation is unaffected.

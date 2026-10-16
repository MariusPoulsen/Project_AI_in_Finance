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

## 28. Phase 5 bounded adversarial investigation

On 2026-10-11 the user explicitly authorized updating the multi-agent pipeline
and Phase 5 plan to the Week 4-inspired design and beginning implementation.
This amendment follows v2 quantitative cohort construction and precedes the
genuine Phase 5 agent evaluation. It does not retrospectively change the v2
scientific freeze or assume expanded Model B improvement.

Reuse accepted quantitative state, calibrated Model B, admissible SEC evidence,
structured catalysts and FinBERT tone as the analyst inputs. The advocates address
mean reversion versus persistent pair-relative repricing, rather than a stock's
bullish versus bearish direction. Produce independent opening cases in parallel,
then exactly one rebuttal per advocate after both openings. Each rebuttal can see
both openings and the original inputs, but not the other rebuttal. A distinct
synthesis/facilitator produces a cited research interpretation and proposed
LOW/MEDIUM/HIGH/UNKNOWN break risk. A separate semantic Risk/Validation stage
checks that interpretation before deterministic Python applies the controller.
There is no LLM-authorized trade, open-ended debate, contemporary historical
browsing or new external information set.

Use explicitly configured free Gemma for both opening/rebuttal roles and
Flash-Lite for separate synthesis and semantic-validation roles. This is four
Gemma and two Flash-Lite calls per complete uncached event before retries, not
one Flash-Lite call. Pin actual model, prompt, graph, schema and inference-setting
identities in each run/cache. Changing the model or number of rounds requires a
new version; do not silently fall back. Respect pacing, timeouts and shared
attempt budgets including retries; paid API use and hidden SDK retries remain
disabled. The Phase 5 adapter is distinct from v2's catalyst-only Gemma contract.
The first provider's counters are invocation-local; they do not reconstruct
unsaved failed requests across process restarts or reset actual project quotas.
Preserve failed receipts and disclose that limitation when scheduling a pilot.

Python mechanically checks schemas, cited chunk/issuer identity, exact quotes,
timestamps and quantitative references. Semantic validation separately checks
claim support, fact versus inference, contradictions, coverage and break risk.
Valid quotation is insufficient evidence that its interpretation is true. LLM
validation cannot override failed mechanical checks or modify stored numerical
state. Failed or insufficient required evidence yields UNKNOWN/ABSTAIN; explicit
high-risk or deterministic ineligibility may yield NO TRADE. Controller statuses
remain exactly CANDIDATE, REVIEW, NO TRADE and ABSTAIN with fixed reason codes.
Unvalidated fixture thresholds are not frozen research policy.

A source-grounded stored HIGH-materiality catalyst affecting A or B with DIRECT
relationship relevance cannot be silently downgraded to CANDIDATE by an
otherwise LOW-risk validator output. Unless semantic validation confirms HIGH
break risk or the high-materiality one-sided veto, retain REVIEW with fixed
reason `UNRESOLVED_CATALYST_RISK`. The unconfirmed extraction is not itself an
automatic NO TRADE rule; confirmed risk and deterministic hard gates govern
vetoes. This preserves an unresolved warning without equating exact quotation
with semantic confirmation.

Full-System automatic candidates require ACTIVE at the historical event timestamp,
the frozen Model B candidate threshold and hard data/risk/liquidity gates.
Preflight may skip expensive reasoning when deterministic gates already make
CANDIDATE impossible, but persist the status, eligibility and skip reason for
every event. Count eligible events after accepted B fitting. Declare any optional
REVIEW/audit population separately. If quotas require a subset, freeze a
target-blind investigation schedule and retain matched B/Full-System denominators
before evaluating those agent outputs. Do not impose the v2 extraction schedule's
500-event cap on agents or claim a subset result for the whole cohort.

Keep the broad 37,421-event matched A/B forecasting population, UNKNOWN rows,
SEC source-v3 bytes, quality-v2 FinBERT, frozen 500-event catalyst schedule, model
definitions and final-test lock unchanged. Prepare implementation on the isolated
`phase5/agents-controller-foundation` branch. Do not synchronize it into the live
v2 checkout until full feature/model/replay/CI/publication acceptance; worker exit
alone is insufficient. This amendment does not start P6/P7 or authorize
2024–2025 outcome/performance access.

Mocks establish contracts, orchestration, reproducibility and fail-safe controller
behavior only. Phase 5 completion additionally requires accepted-generation
integration, a genuine provider pilot and fixed human source-support/category/
materiality/relevance evaluation on at least 50 historical events, aiming for 100.
Any development outcome stratification belongs only to evaluation selection;
agent prompts and production scheduling never receive realized outcomes. Record
unsupported interpretations, failures, UNKNOWNs and abstentions honestly. No
agent usefulness or Full-System benefit is established by the fixture slice.

## 29. Phase 5 durable batches and blind source review

On 2026-10-11 the user authorized continuing the independent Phase 5 batch
infrastructure while the detached v2 feature build runs. This engineering slice
adds a target-blind frozen schedule, immutable per-event checkpoints, complete
scheduled/skipped/budget-failed denominators, a prepared mock-input inventory and
a source-only human annotation workflow. It does not change the v2 population,
500-event catalyst schedule, model definitions or final-test lock.

Durable attempt accounting supersedes the invocation-only limitation described
for the first adapter in section 28 when the provider is attached to the journal.
Reserve each transport attempt before sending it, including retries. Reservations
are never refunded after a timeout or interrupted process because its actual
provider outcome may be unknown. Bind immutable total/per-model/per-provider-day
limits to the same allocation across restarts. Ledger integrity and exclusive
leases fail closed; an abandoned lease requires explicit stopped-owner attestation,
the exact token and a preserved recovery receipt. This journal does not measure
other applications' use of the same provider project or reset provider quotas.

Persist the schedule before inference. If capped, rank historically eligible
events only by a declared seed and event/pair/time identity, never by outcomes or
favourable agent results. All input rows retain a deterministic disposition.
Intentional pauses do not publish a complete manifest. Resume verifies completed
input/checkpoint/provider/code/policy identities and replays the deterministic
controller without rerunning the graph or transport. Changed scientific inputs,
implementation or explicit retry identity create a distinct batch, preserving
previous failed records and shared allocation accounting.

The prepared-input CLI currently accepts mock manifests only. Files are bounded,
content addressed and checksum checked lazily; this is not an independently
verified adapter to accepted native Model B and registered historical SEC assets.
Source review selects a frozen event-identity sample and omits probabilities,
suggested catalyst labels and outcomes. Human annotations bind the exact inventory
and source bytes, preserve incomplete acquisition and cite the claimed affected
legs. Format/provenance checks do not measure semantic accuracy. Genuine source
review, advocate/synthesis interpretation evaluation and at least 50 historical
annotations (aiming for 100) remain completion gates.

## 30. Phase 6 fixed-share development simulator

On 2026-10-11 the user authorized parallel Phase 5 batch infrastructure and the
Phase 6 shared event-level simulator while the frozen v2 feature job continues.
Prepare this simulator on isolated `phase6/shared-simulator`; do not synchronize
new computational source into the running v2 checkout or claim that fixture
success completes v2 or Phase 6. This amendment precedes any genuine Phase 6
economic assessment. The primary forecast comparison remains calibrated
logistic B-both versus matched A, with fit 2006-2019, calibration 2020-2021 and
assessment 2022-2023, the complete-window embargo, all predeclared ablations and
10/30-session sensitivities. Final 2024-2025 outcomes/performance stay locked.

The event engine uses the frozen signal-close alpha, beta, spread mean and
standard deviation, entering at the exact next XNYS open. Snapshot availability
means first usability and cannot precede the next XNYS open after its formation
endpoint; a same-close newly formed fit cannot drive that signal. The primary timeout
is the close of the twentieth session after the signal; preserve separately
versioned 10/30-session sensitivities. Monitor each close from the entry session.
An observed |z| <= 0.5 triggers convergence; signal-sign times z >= 3 triggers
the same-side adverse stop. An opposite-side jump outside the success band is
neither convergence nor that adverse stop. Every close trigger, including
timeout, exits at the exact following XNYS open. Never substitute a later
convenient open, interpolate a required price or reuse new relationship fits.

Positive beta is an economic execution gate only; it does not alter the broad
v2 A/B cohort. Size entry gross notional with signed beta weights, then freeze
share units using entry prices. No daily constant-weight rebalancing is allowed.
Gross return is fixed-share exit-minus-entry P&L divided by entry gross notional.
Entry cost applies to actual gross entry turnover; exit cost applies to actual
gross exit turnover, which can differ as prices move. The synthetic scenario
uses 5 bps on each turnover and 3% annual borrow on entry short notional times
actual open-to-open XNYS session intervals / 252. These are disclosed fixture
parameters, not measured execution prices or frozen production assumptions.

The production `configs/phase6_execution.json` remains DEVELOPMENT/DRAFT with
costs, annual borrow and positive-beta ceiling unresolved. Execution refuses
real captured inputs until a production policy is explicitly frozen. The
fixture's beta ceiling is a test scenario, not a forecast population restriction.
A later immutable economic experiment must freeze the real cost/sensitivity,
borrow, price-adjustment, liquidity/eligibility and execution assumptions before
economic assessment. Keep `configs/backtest.yaml` and original reference
artifacts unchanged.

Synthetic prices declare one compatible open/close basis. A future Yahoo
adapter must use adjusted open = raw open * (adjusted close / raw close) and
the matching adjusted close from the same capture; retrospective adjustments
are a disclosed historical limitation rather than a vintage feed. This slice
does not ingest market data or settle actual corporate actions. A declared
lifecycle termination produces explicit unknown execution until its economic
settlement policy is implemented; statistical WATCH/RETIRED alone does not
terminate a frozen path.

Retain a row and reason for NOT_ENTERED and UNPRICED results. Missing entry/exit
opens, missing monitored prices, truncation and unresolved lifecycle settlement
cannot produce fabricated zero return. Completed MAE/MFE sample entry zero,
observed monitored closes and executed exit open; they do not claim intraday
extrema. A partially observed path is not a completed event outcome. Existing
supervised labels and economic returns remain distinct. For UNPRICED paths,
final MAE/MFE remain null; separately named partial excursion fields describe
the observed prefix and are excluded from completed-event statistics.

The first acceptance boundary is synthetic event-level execution only. Raw
signal generation, all five capability filters, actual stored v2/controller
integration, common-subset economic evaluation, portfolio allocation and human
agent metrics remain pending. Preserve the v2 paired calendar-quarter forecast
bootstrap; the older calendar-month economic-bootstrap proposal is separate
and must be specified/frozen before economic assessment. Do not silently
redefine forecast uncertainty through the new simulator.

## 31. Phase 6 fixture ladder and coverage reporting

On 2026-10-11 the user authorized the next Phase 6 engineering slice while
the detached v2 feature build continues. Extend the isolated shared-simulator
branch with frozen capability selection, event-level reporting and immutable
verification using synthetic inputs only. This does not open genuine historical
assessment, change the v2 research protocol or synchronize computational code
into its running checkout.

Baseline 0 requires an estimable fresh divergence under the admissible current
relationship snapshot: evaluate the prior and signal-close spread with those
same current parameters, rather than comparing z-scores from two different
rolling fits. Baseline 1 adds historical ACTIVE status at signal time. A and B
each independently add their own frozen calibrated probability at the same
declared threshold to Baseline 1. B is not required to pass A. The Full System
adds a stored CANDIDATE controller decision to the B-accepted set; REVIEW,
NO TRADE and ABSTAIN are withheld. Execution eligibility, including positive
beta and available next-open prices, stays a separate shared-engine gate.

Persist every input event and every variant's selection/disposition. Simulate
each fresh raw event once under the common execution policy, preserving
rejected-event counterfactuals and explicit unavailable/unpriced reasons. A
counterfactual is the outcome of this same frozen simulator, not a prediction
or an agent label.
Retain rows lacking A/B predictions, agent results, labels or prices. Selection
must not read supervised targets; join target identities and development-only
labels through a separate reporting input. Convergence and positive net return
cannot substitute for the supervised success label.

Adjacent-rung comparisons disclose natural populations, common required-data
availability and the intersection of actual selected events separately. The
common-data population is not the selected intersection. A/B economic selection
tables do not replace the broad matched v2 forecasting analysis. Fixture
forecast metrics use estimable fresh events regardless of ACTIVE status and
report exclusions for nonfresh or unknown crossings separately. Every reported
return uses COMPLETE, priced trades only and names its selected, missing,
NOT_ENTERED and UNPRICED denominators. Label rates use only available bound
labels, with unavailable labels counted separately; zero eligible observations
produce an explicit undefined rate rather than a favorable zero.

Full-System coverage distinguishes the frozen scheduled B-candidate population
from successful investigations. Scheduled missing/failed results remain in that
denominator as unavailable/ABSTAIN; do not redefine the scheduled cohort around
completed favorable cases. Report unscheduled events separately. Distinguish
NO TRADE vetoes from REVIEW deferrals, ABSTAIN/unavailable investigations and
unscheduled rows. False-veto and failed-opportunity rejection describe NO TRADE
on labeled scheduled B candidates; a separate all-withheld measure may describe
REVIEW and ABSTAIN too, without calling them confirmed agent vetoes.

The synthetic ladder freezes its fixture threshold, model/decision identities,
event inventory, execution scenario and code identities in an immutable
manifest. Reverification reconstructs selection and reports from bound inputs
and reruns the same simulator; it cannot repair or overwrite mismatched bytes.
Reject implementation/runtime drift during computation or verification before
publishing or attesting the result.
Report assembly also rechecks the deterministic selector against its input
policy without executing the price path again.
Fixture economics and mock controller outputs establish engineering behavior
only. Production policy remains DRAFT. Accepted historical generation adapters,
genuine controller/source and human-quality integration, portfolio accounting,
economic bootstrap and production assumption freeze remain completion gates.
The final 2024-2025 outcome/performance lock remains intact.

## 32. Historical bridges and economic analysis before v2 completion

On 2026-10-11 the user authorized the remaining independent Phase 5/6 work:
historical artifact adapters, genuine blind source-review preparation, robustness
and cost analysis, economic uncertainty engineering and secondary portfolio
accounting. Implement on the isolated Phase 5 and stacked Phase 6 branches. Keep
the running v2 source, registry, population, feature policies, catalyst schedule,
model comparison and final-test lock unchanged. These choices follow previously
observed original development results and precede genuine v2 economic assessment;
they must not be described as decisions made before all development observations.

Source-only human review may use an explicit registered H20 registry and verified
SEC source-v3 without a fitted Model B. Freeze a seeded event-identity sample of
50–100 events before reading its captures. Snapshot only the selected stored raw
receipts/documents, preserve unavailable captures and replay each packet from
that frozen copy. Omit targets, model probabilities and suggested catalyst labels.
Bind source manifests, registry/universe identities and the source recipe. Citation
offsets address the stored cleaned chunk, not original HTML characters. Human
annotations and their semantic evaluation remain human work; format/provenance
validation cannot certify accuracy.

Scored historical agent inputs additionally require the explicit registered
primary publication and its accepted native/source/hosted-CI evidence. Replay
the exact primary logistic B-both/H20 model and selected calibrated/raw prediction,
SEC pack, pinned quality-v2 tone and stored extraction. A declared manifest or
acceptance flag cannot substitute for publication. Admit only 2022–2023 assessment
scores; fit/calibration scores from the final fitted bundle are not vintage
out-of-sample agent inputs. Preserve unavailable lifecycle, liquidity or
implementation eligibility instead of inventing approval. Nullable eligibility
produces ABSTAIN with explicit UNKNOWN reason codes; known hard failures still
produce NO TRADE. Genuine
provider pilots, the historically eligible schedule and Full-System claims remain
pending; exporting a source review does not complete them.

The independent Phase 6 analysis bundle is synthetic engineering. Report all
predeclared turnover scenarios (2.5/5/10/20 bps per entry/exit turnover) crossed
with annual borrow scenarios (0/3/10 percent), using the same event inventory,
selection and shared execution engine. Never select a winning scenario or change
model acceptance using its return. Actual production costs and borrow remain DRAFT.
Robustness slices cover year, pair, sector, divergence sign, source coverage,
previous-session VIX/trailing-volatility stress and event type/materiality. Missing
context is UNKNOWN; bind its event/cutoff and report small populations, pair
concentration and leave-one-pair/sector-out diagnostics without selecting a
favorable subset.

The separate fixture economic bootstrap uses 2,000 seeded paired calendar-month
draws (seed 5557), drawing identical complete-range month indices for every
strategy and retaining all pairs in a block. Distinguish natural selected
COMPLETE-only event mean differences, common known allocation-per-raw-candidate
differences and the both-selected COMPLETE intersection. Explicit WITHHELD means
zero allocation under that estimand; UNAVAILABLE or selected unknown execution
does not become a zero return. Retain status/denominator and undefined-draw counts.
Suppress intervals below 12 contributing populated months for each estimand,
including support on both sides of natural mean comparisons. These fixture
intervals establish no inference. The canonical v2 paired-quarter predictive
bootstrap remains unchanged; the production economic freeze is still pending.

The fixture secondary portfolio starts at NAV 1 and targets 25 percent of current
NAV gross per accepted entry, clips simultaneous entries equally to available
gross capacity, reserves entry fees and processes previously triggered exits before
new allocations. Freeze entry shares, allow one position per pair and report shared
ticker/sector concentration. The gross limit of one is an entry admission cap;
passive price drift can breach it and must be disclosed. There is no automatic
deleveraging, financing/margin or idle-cash-yield model. Chronological open/close
marks supply NAV, exposure, turnover, costs, borrow, drawdown and close-to-close
returns. Future COMPLETE status cannot select surviving entries. Missing held
quotes or unresolved settlement invalidate subsequent NAV and block new allocation;
do not average event returns into portfolio Sharpe. Actual portfolio policy and
historical price acceptance remain pending.

Persist the complete analysis inputs, contexts, policies, rows, scenarios and reports
immutably with code/runtime identities; independently rebuild outputs on verification
and reject source/runtime drift. These artifacts and mock controller results cannot
self-attest scientific acceptance, model improvement or agent quality. No change
authorizes 2024–2025 outcomes or merging unfinished v2 into main.

## 33. Native report replay tolerance and the v2 completion rerun

Recorded 2026-10-16, before any accepted v2 publication. No assessment result
was used to choose any change below.

The shared-source completion attempt (`v2_completion_four_core_20261014T2355Z_76d9db8`,
revision `76d9db8`) completed source pass 1 and the h20 fit and verification.
It then stopped on 2026-10-15 in the h10 in-fit native self-check. Every h10
model reproduced its stored probabilities within 1e-12, but a few recomputed
subgroup report metrics differed from the stored report in the last binary
digits (for example log loss `…193` vs `…196`). The check used exact float
equality, so the result depended on BLAS threading and reduction order.

On 2026-10-16 the user authorized a resumed attempt
(`v2_resume_b_20261016T0100_76d9db8`) that reused the verified pass-1 proof and
h20 stages and ran native replays without the one-thread cap. h10 then passed,
but h30's standalone verification failed the same way in the opposite thread
mode. Read-only replays showed h20 passing in both modes, h10 only without the
cap and h30 only with it. A publication replay of all thirty models in one
process could therefore not pass under any setting. The resumed attempt's
records and amendment note remain in its directory; no generation from either
attempt is accepted.

The user then authorized a code fix and a complete rerun. `verify_research_models`
now compares recomputed report floats within a 1e-12 relative tolerance; keys,
lengths, counts, labels and nulls stay exact. The 1e-12 probability tolerance and
the exact calibrator check are unchanged. With the fixed comparator, all thirty
models registered by the earlier attempts pass the full replay in both thread
modes. Because package source changed, the rerun
(`v2_rerun_a_20261016_4764c65`, revision `4764c65`) starts again from source
pass 1 and creates new generations, both complete source passes and full hosted
CI. Fitting code, data, event population, protocol, model definitions, tuning,
calibration and the 2024–2025 final-test lock are unchanged.

The full-validation CI gate for the rerun is the section 27 job set
(`foundation` and `acceptance` on Linux and Windows, plus `nlp-runtime`). A
provisional, clearly unaccepted export of the earlier registered generations
was prepared for group members to start exploratory work; it is replaced by the
official snapshot once the rerun is accepted.

## 34. Accepted research v2 publication

Recorded 2026-10-17. The rerun `v2_rerun_a_20261016_4764c65` (revision `4764c65`,
computational source `73c4539b…`, full hosted CI run 38822935350) completed both
complete source passes, all six fit/verification stages for the thirty models and
`promote-primary`, which performed the fresh source and native replay and
published primary `research_primary_5c01ab3d29c74e3e9154d9e3` with evaluations
`research_evaluation_16a431c4fea73ffd35f56062` (h20, primary),
`research_evaluation_219b30fcf452cd5e1609ec3c` (h10) and
`research_evaluation_bc319e752527bdd7f10ff0c2` (h30). The final-test lock is unchanged.

The supervisor's last gate, the read-only real-app check, stopped because importing
Streamlit calls `platform.system()`, which on Windows with Python 3.11 runs
`cmd /c ver`; the checker's audit hook denies every subprocess as a forbidden
provider call. The app performed no download, fit, provider call or write. With
the user's approval the unchanged checker was run again in a fresh process after
caching `platform.uname()` before the guard was installed. It passed: both pages
rendered without exceptions, displayed metrics and denominators matched the
accepted reports, external sockets were blocked and the database and publication
files were unchanged (receipt
`real_app_acceptance_receipt_prewarmed_platform.json`, SHA-256 `40ae1db3…`, in the
run directory). The supervisor's own receipts record the stop and are not
rewritten; this section is the acceptance record for the app gate. Future checker
versions should cache the platform lookup before installing the guard.

## 34. Phase 6 historical adapters and selection inventory

Recorded 2026-10-16. The owner approved the P6 adapter design questions
(`docs/proposals/P6_HISTORICAL_PLAN.md`, Q1–Q7) before any historical economic
number was computed. These choices follow earlier development observations,
including the already observed 2022–2023 assessment forecasts. They must not be
described as decisions made before all development observations.

- **Trading inventory.** Every rung of the historical ladder uses the horizon's
  non-overlapping episode events (the v2 one-open-episode/reset rule). Raw
  fresh crossings in the window that this registry omits are kept as separate
  `NOT_IN_HORIZON_EVENT_REGISTRY` records, not as trading rows. A and B can
  only score episode events, so this keeps one change per rung.
- **Window.** The headline development ladder covers the 2022–2023 assessment
  window for all five rungs. Stored fit- and calibration-period scores are
  in-sample for the model or the calibrator and are not admitted. Economic
  numbers from this window are post-hoc development results, never final-test
  results. A separately labelled Baseline 0/1 history for 2006–2021 remains
  optional.
- **Selection policy.** The headline uses calibrated logistic A and logistic
  B-both at the bound horizon, with the matched v2 threshold read from the
  bound protocol (0.65). The adapter refuses any other threshold. XGBoost, the
  B ablations and the 10/30-session horizons are labelled sensitivities, and
  every variant is reported.
- **Bindings.** An ACCEPTED binding is derived only through `load_primary` and
  the registered evaluation manifest. An explicit path-and-checksum binding to
  an unpublished pack is `UNACCEPTED_ENGINEERING`. It may build an
  outcome-free selection inventory. A frozen policy, historical execution and
  an accepted manifest all refuse it. Model bundle bytes are checksum-verified.
  Native probability replay is part of the later accepted-manifest run.
- **Full System.** Without an accepted controller generation, every row
  carries `FULL_SYSTEM: NOT_RUN / CONTROLLER_GENERATION_NOT_ACCEPTED`. Reports
  show the rung, its B→Full comparison and its agent metrics as status-only
  with null metrics. These are never zero-selected, withheld or zero-return.
  The PLAN.md adapter checkbox stays in progress until P5 supplies an accepted
  controller generation.
- **Prices.** Closes are the Yahoo adjusted close. The adjusted open is
  `open × adj_close / close` from the same capture row. Monitoring closes
  accept `OK` and `ZERO_VOLUME`, as the relationship engine does. Fills
  require `OK`, so a `ZERO_VOLUME` fill session is an explicit missing fill.
  Paths that would need sessions after 2023-12-31 are truncated, never
  constructed.
- **Execution gate.** `evaluate_historical_ladder` requires an accepted
  binding, a FROZEN ladder policy and a FROZEN `DEVELOPMENT` execution policy.
  The production execution policy remains DRAFT until the owner approves it
  separately.
- **Persistence.** Content-addressed files and a manifest come first. DuckDB
  registration (`ops.experiments`, `analytics.backtest_trades`) follows later
  for the Strategy Lab.

Fixture tests establish engineering behaviour only. Accepted-snapshot
verification, the production policy freeze, the accepted experiment manifest
and the Full-System controller adapter remain separate gates. The 2024–2025
final-test lock is unchanged.

## 35. Frozen Phase 6 production execution policy and trading threshold

Recorded 2026-10-16. The owner approved
`docs/proposals/P6_EXECUTION_POLICY.md` as drafted, with threshold option 2.

**Timing.** The approval came after the 2022–2023 assessment forecasts had
been observed in earlier development work. It also came after the P6
selection inventory showed that Model A and Model B select no assessment
event at 0.65. It came before any historical simulated return, path or
economic metric was computed. The values were chosen from cited literature
and from target-blind 2006–2021 diagnostics that never load labels. Results
under this policy for 2022–2023 are post-hoc development results.

**Frozen headline execution policy** (`configs/phase6_execution.json`,
`pair-execution-policy-v2`, `DEVELOPMENT/FROZEN`):

- 5 bps per entry and per exit gross turnover;
- 1.0 % annual borrow on entry short notional over open-to-open sessions / 252;
- execution eligibility 0 < β ≤ 3;
- minimum-leg 20-session mean dollar volume of at least $5 M. The 20 sessions
  are the exact XNYS sessions ending at the signal close, and any missing
  session makes liquidity unknown;
- no share-price floor;
- the 20-session horizon, with the unchanged 2.0 / 0.5 / 3.0 z rules.

**Frozen sensitivity set** (`configs/phase6_execution_sensitivities.json`).
Every variant is reported and none is selected:

- the 4 × 4 cost/borrow grid: 2.5 / 5 / 10 / 20 bps crossed with
  0 / 1 / 3 / 10 %;
- β ceilings of 2 and 5, and "none", encoded as the schema maximum of 100
  (the largest observed β is about 13);
- liquidity floors of none (encoded as 0), $1 M and $10 M;
- 10- and 30-session horizons.

**Trading threshold.** The common A/B trading threshold is **0.30**. It
supersedes Decision 34's equality with the 0.65 v2 reporting threshold for
the economic ladder only. Thresholds of 0.20, 0.40 and 0.65 are reported as
sensitivities. A and B still apply the same declared value independently. The
canonical v2 forecasting reports and their 0.65 coverage are unchanged.

**Other frozen conventions:**

- Prices use Yahoo retrospective adjusted closes, with adjusted open =
  open × adj_close / close from the same row (Decision 34).
- The economic uncertainty policy is 2,000 paired calendar-month draws with
  seed 5557, and intervals require at least 12 contributing months.
- The secondary portfolio policy is 25 % of NAV gross per entry, a gross
  admission cap of 1, one position per pair, zero cash yield and no
  financing.

**Disclosed limitations.** No rebate is earned on short proceeds. Borrow
availability and recalls are not modelled. Price data are retrospective, not
vintage.

**Data check.** The diagnostics must be re-run on the official snapshot. A
material difference requires a new, explicitly versioned policy rather than
silent re-selection. Freezing the execution policy does not complete the
P6 methodology freeze: the controller/prompt identities (P5) and the accepted
experiment manifest remain open. The 2024–2025 final-test lock is unchanged.

## 36. Accepted historical experiment manifest and persistence

Recorded 2026-10-16, after Decision 35 and before any historical return was
computed. This section records the reporting scope and persistence of the
historical ladder experiment. It changes no scientific rule.

- **Scope.** One experiment binds one accepted evaluation generation (one
  horizon). It runs only through `structural-break-backtest
  historical-experiment`, which derives the binding through `load_primary`.
  There is no unaccepted or provisional option.
- **Policies.** The experiment runs every Decision 35 frozen policy for its
  horizon. At h20 that is the headline plus 21 execution sensitivities; the
  10- and 30-session variants are separate experiments bound to their own
  evaluation generations.
- **Thresholds.** The 0.20, 0.40 and 0.65 trading thresholds are evaluated
  under the primary policy for the horizon.
- **Declared combinations.** These are the headline (0.30 × primary policy),
  the three threshold sensitivities and the execution sensitivities at 0.30.
  The two families are not crossed, and no combination is selected.
- **Computation.** Each fresh event is simulated once per frozen policy, and
  selection runs once per threshold. Freshness is checked to be independent of
  the threshold.
- **Persisted artifacts.** The content-addressed
  `historical-experiments/<id>/` directory holds:
  - inputs: binding, policy set, specs, event inventory, labels;
  - outputs: selections, full primary-policy trade results, compact
    sensitivity results bound to each full result's hash, reports and summary;
  - the manifest, written last.
- **Identity.** The experiment identity binds the accepted generation, input
  checksums, computational source and runtime.
- **Verification.** It rebuilds the events from the bound sources, checks that
  the current frozen configs reproduce the bound policy set, replays selection
  and simulation, and compares every artifact byte for byte. It never repairs
  bytes.
- **Reports.** Reports are post-hoc 2022–2023 development assessment, never
  final-test results. Full System is `NOT_RUN`. DuckDB registration remains
  deferred (Decision 34).

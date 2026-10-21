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

## 35. Phase 6 historical adapters and selection inventory

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

## 36. Frozen Phase 6 production execution policy and trading threshold

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
supersedes Decision 35's equality with the 0.65 v2 reporting threshold for
the economic ladder only. Thresholds of 0.20, 0.40 and 0.65 are reported as
sensitivities. A and B still apply the same declared value independently. The
canonical v2 forecasting reports and their 0.65 coverage are unchanged.

**Other frozen conventions:**

- Prices use Yahoo retrospective adjusted closes, with adjusted open =
  open × adj_close / close from the same row (Decision 35).
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

## 37. Accepted historical experiment manifest and persistence

Recorded 2026-10-16, after Decision 36 and before any historical return was
computed. This section records the reporting scope and persistence of the
historical ladder experiment. It changes no scientific rule.

- **Scope.** One experiment binds one accepted evaluation generation (one
  horizon). It runs only through `structural-break-backtest
  historical-experiment`, which derives the binding through `load_primary`.
  There is no unaccepted or provisional option.
- **Policies.** The experiment runs every Decision 36 frozen policy for its
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
  deferred (Decision 35).

## 38. Historical portfolio, robustness/cost and economic uncertainty analysis

Recorded 2026-10-16, before any historical return was computed. This section
extends the Decision 37 experiment with the secondary analyses that Decisions 32
and 35 define. Each analysis runs once, on the headline combination
(0.30 × primary policy).

**Cost grid.** `cost-grid.json` tabulates the frozen 4 × 4 cost/borrow
scenarios for every rung from the per-combination reports. The trade
selection is identical in every scenario and no scenario is selected.

**Economic uncertainty.** `uncertainty.json` applies the Decision 36 frozen
paired calendar-month bootstrap (`phase6-month-bootstrap-20261016`: 2,000
draws, seed 5557, intervals only with at least 12 contributing months) to the
headline rows. The B→Full comparison is `NOT_RUN`, never zero. This bootstrap
does not replace v2's paired-quarter forecast uncertainty.

**Portfolios.** `portfolios.json` runs the frozen secondary portfolio
(`phase6-portfolio-20261016`) separately for each run rung. Every fresh event
keeps a proposal row, and selection comes only from the stored rung decision.
Ticker sectors come from the bound security master. A position still open at
the last development session is `UNPRICED / DEVELOPMENT_END_TRUNCATION`: no
2024 session is constructed and no terminal NAV is claimed. Full System is
`NOT_RUN`.

**Robustness.** `robustness.json` uses point-in-time contexts from the bound
`h{h}_features` table:

- previous-session VIX (`vix_level`), observed at its 16:16 New York proxy
  clock;
- trailing annualized 20-session SPY volatility (`market_rv20`), observed at
  the signal close.

Events without either value stay UNKNOWN. Event type and materiality stay
UNKNOWN until an accepted controller generation exists. Year, pair, sector,
sign, coverage and stress slices, plus leave-one-pair-out and
leave-one-sector-out diagnostics, are all reported; none is selected.

**Pending approval.** The robustness slice boundaries in
`configs/phase6_analysis.json` (`phase6-robustness-20261016`) remain **DRAFT**:

- VIX buckets: elevated at 20, high at 30;
- volatility buckets: elevated at 0.20, high at 0.40;
- small-population flag below 20 events.

These values carry over the Decision 32 fixture boundaries unchanged, but were
not part of the Decision 36 approval. The experiment refuses to run until the
owner freezes them. Tests use a test-only frozen copy.

## 39. Frozen Phase 6 robustness slice policy

Recorded 2026-10-16. The owner approved the Decision 38 robustness slice policy
as proposed, and it is now **FROZEN** in `configs/phase6_analysis.json`
(`phase6-robustness-20261016`).

**Timing.** The approval came after the 2022–2023 assessment forecasts and the
empty 0.65 A/B inventory had been observed. No historical return, slice result
or stress-bucket count had been computed. The boundaries are the unchanged
Decision 32 fixture values, chosen without any historical outcome.

**Frozen values:**

- previous-session VIX buckets: LOW below 20, ELEVATED from 20, HIGH from 30;
- trailing annualized 20-session SPY volatility buckets: LOW below 0.20,
  ELEVATED from 0.20, HIGH from 0.40;
- a slice with fewer than 20 events is flagged as a small population;
- contexts (`phase6-feature-context-v1`) come from the bound `h{h}_features`
  table at their point-in-time clocks, and missing context stays UNKNOWN.

All slices and the leave-one-pair-out and leave-one-sector-out diagnostics are
reported; none is selected. Event type and materiality remain UNKNOWN until an
accepted controller generation exists.

**What this unblocks.** Every Phase 6 execution and analysis policy the
accepted experiment uses is now frozen. The acceptance run still requires the
official accepted snapshot. The Full System, the controller and prompt
identities (P5), and the 2024–2025 final-test lock are unchanged.

## 40. Full System deferred from the Phase 6 acceptance scope

Recorded 2026-10-16. The owner stated that the multi-agent layer (P5) may not be
completed.

- The Phase 6 historical acceptance scope is the four Baseline/Model rungs:
  Baseline 0, Baseline 1, Model A and Model B.
- Every historical experiment keeps the fifth rung in its rows, reports,
  bootstrap and portfolios as `FULL_SYSTEM: NOT_RUN /
  CONTROLLER_GENERATION_NOT_ACCEPTED`. It is never shown as zero-selected,
  withheld or zero-return.
- An experiment, report or summary must not be described as a five-variant
  result while that rung is not run.
- If the multi-agent layer is completed and accepted later, its controller
  adapter is added as a new, separately identified experiment version. That
  version binds the accepted controller, prompt and schedule identities, and it
  does not rewrite the four-rung artifacts.
- The rule that the Full System is a subset of Model B, its frozen policies and
  the final-test lock are unchanged.

## 41. Freeze manifest, final-test unlock gate and one-command acceptance

Recorded 2026-10-16. This section changes no scientific rule. It implements
the specification §2.1 freeze manifest and the final-test lock gate.

**One-command acceptance.** `structural-break-backtest p6-acceptance` derives
accepted bindings only through `load_primary`. For each of h20, h10 and h30 it:

1. runs the historical experiment;
2. verifies it by fresh replay;
3. writes the target-blind policy diagnostics.

It then writes a content-addressed freeze manifest.

**Freeze manifest.** The manifest binds:

- the primary version, protocol, registry, market capture and pair universe;
- per horizon: the experiment and its manifest checksum, verification status,
  feature schema, label policy, Model A/B bundles and calibrators, trading
  thresholds and execution-policy versions;
- the three frozen config files;
- the code and runtime identity;
- the execution convention;
- `controller: DEFERRED_NOT_RUN` (Decision 40).

All horizons must bind the same accepted generations. The checklist of
validation decisions covers execution, threshold, analysis policies, accepted
experiments and the Full System. Accepted experiments stay OPEN until all
three horizons are verified, and the Full System is DEFERRED. The manifest
always records `final_test_unlocked: false`.

**Unlock gate.** `final-test-gate` and `require_final_test_unlock` refuse
unless every decision is closed and an owner-authored unlock record is
supplied. The record must bind the exact manifest checksum and freeze ID and
contain the required authorization statement verbatim. The code never creates
that record.

Implementing the gate does not authorize, capture or run the 2024–2025 final
test. That run remains a later, separately authorized step.

## 42. Phase 6 development acceptance on the accepted v2 snapshot

Recorded 2026-10-17. `structural-break-backtest p6-acceptance` ran once, on one
thread in 135 minutes, against the official snapshot. That snapshot is
`group-v2.zip` (SHA-256 `8acc3af0…3def3f`), imported with `team.py setup`, and
its `team.py check` passed on 11,864 files. The run used primary
`research_primary_5c01ab3d29c74e3e9154d9e3`.

**Experiments.** All three passed `VERIFIED_HISTORICAL_REPLAY`:

| Horizon | Experiment | Events |
|---|---|---|
| h20 | `d828d7ac…69cab5` | 3,558 |
| h10 | `bea3126d…79e11a` | 4,305 |
| h30 | `02a2c5fa…3e82eb` | 3,179 |

**Freeze manifest.** `2266d696…72bf7de` records every decision as CLOSED,
except the Full System, which is DEFERRED (Decision 40).

**Policy check.** The official diagnostics reproduced the provisional ones
exactly: β ceiling counts, liquidity floor counts and calibration-period score
distributions. The Decision 36 data check therefore passes, and no policy was
changed.

**Status.** These are post-hoc 2022–2023 development results, recorded in
`docs/P6_DEVELOPMENT_RESULTS.md`; they are not final-test results. Phase 6
development acceptance passes for the four Baseline/Model rungs.

**What remains:**

- the owner's review of the freeze manifest;
- an explicit owner unlock record before any 2024–2025 capture or final run;
- the Full System, only if the multi-agent layer is completed (Decision 40).

The final-test gate reports locked.

## 43. Pre-registered P6 model and trading improvements (exploratory)

Recorded 2026-10-17, after the Decision 42 development results were observed and
before any variant in this section was evaluated on 2022–2023. The owner asked
for five improvements and delegated the decisions. The full plan is
`docs/proposals/P6_IMPROVEMENT_PLAN.md`, committed together with this section.

**The five improvements:**

1. **Exit rule.** Eight research-only variants (adverse stop × take-profit),
   chosen on 2006–2019 Baseline 0 economics, with a 2020–2021 guard.
2. **Economic target.** Positive net return of a COMPLETE trade.
3. **Veto rule.** Drop each model's bottom 20 % or 33 % by calibration-period
   quantile.
4. **Features and families.** Matched-budget feature sets and families (A;
   B_both, B_lean, B_plus), selected on four forward folds (2016–2019).
5. **Rank rule.** Each model's top 10 %, 20 % or 33 % by calibration-period
   quantile on a Baseline 0 or Baseline 1 gate.

The gate is chosen by 2006–2021 economics. Calibration uses 2020–2021.

**Primary contrast.** B − A mean net return per gated candidate under the
top-20 % rule, with a paired calendar-month bootstrap.

**Rules that hold throughout:**

- All results are post-hoc exploratory and every variant is reported.
- Nothing is re-selected after viewing 2022–2023.
- A and B stay matched.
- The Decision 36 frozen production policy and the Decision 42 accepted results
  are unchanged.
- The 2024–2025 final-test lock is unchanged; only that test can confirm an
  improvement.

### 43a. Development-stage choices, frozen before the 2022–2023 evaluation

Recorded 2026-10-17. The development stage of
`structural_break.experiments.p6_improvement` used only events with signals in
2006–2021: 22,111 fresh h20 events, simulated once under eight exit variants.
It wrote `outputs/p6_improvement/run1/frozen_choices.json`, SHA-256
`000953d667e5efbff560885ce31c6a40368883e4c90d91836574655129995e26`. No
2022–2023 outcome was simulated, scored or read before this record.

**Plan amendment, made before execution.** The mean-crossing take-profit
variant became a |z| ≤ 0.25 band, because a crossing exit would change engine
semantics. Exit variants run in the explicit `RESEARCH` execution mode, which
is always DRAFT. The ladder and experiment paths, which require a FROZEN
`DEVELOPMENT` policy, refuse it.

**Choices:**

- **Exit.** No adverse stop, with take-profit at |z| ≤ 0.25. It had the best
  2006–2019 Baseline 0 mean net per COMPLETE trade: −5.7 bps against −13.5
  bps for the frozen rule (n = 18,629). The 2020–2021 guard passed: +21.8 bps
  against −8.4 bps.
- **Gate.** Baseline 1 (ACTIVE): +20.2 bps (n = 2,035) against −1.4 bps for
  Baseline 0 (n = 22,111) over 2006–2021.
- **Economic-target models.** A and B both use XGBoost (depth 3, 100 trees,
  learning rate 0.05). B's forward folds selected the B_both feature set. Mean
  fold Brier was 0.24808 for A and 0.24780 for B.
- **Reversion-target models.** A uses logistic regression with C = 0.01 (fold
  Brier 0.06241). B uses XGBoost (depth 3, 400 trees, learning rate 0.03) on
  B_both (0.06199).
- **Thresholds.** The top-k (10/20/33 %) and veto (20/33 %) cut-offs come from
  2020–2021 calibrated scores for each gate.

**A bug fixed after this run.** After the run, a unit test found that an exactly
zero mean was ordered as missing in the exit and gate choosers. Recomputing
both choices from the stored tables with the fixed code gives the same
decisions, because no mean is exactly zero.

## 44. Results of the pre-registered P6 improvements (post-hoc exploratory)

Recorded 2026-10-17. The Decision 43/43a variants were evaluated on 2022–2023
(h20, 3,558 events, 3,430 scored) under the frozen choices `000953d6…`. The
full record is `docs/P6_IMPROVEMENT_RESULTS.md`.

**Primary contrast.** B − A per gated candidate (Baseline 1 gate,
trade-outcome target, top 20 %) is **−13.8 bps, 95 % interval [−34.9, +4.5]**.
No pre-registered improvement makes B better.

**Findings:**

- **Trading-outcome target.** Unpredictable: ROC-AUC 0.528 (A) and 0.526 (B).
- **Veto rule.** No benefit.
- **Baseline 1 gate.** It reversed out of sample: −20.2 bps against +2.6 bps
  for Baseline 0 when trading everything.
- **Research exit rule.** Its 2020–2021 advantage largely disappeared.
- **Reversion-target B (XGBoost, B_both).** ROC-AUC 0.760 against 0.736 for A,
  PR-AUC 0.168 against 0.158, and paired-quarter Brier B − A −0.00038
  [−0.00147, +0.00093]. It is better on every metric but not significantly,
  and A's family differs from B's.
- **An exploratory lead.** On the Baseline 0 gate, B − A is positive at every
  rank cut (+2.7 to +4.4 bps per candidate) with intervals that just include
  zero. This is a non-primary, post-hoc observation from a 20-cell grid.

**Implementation correction.** The plan specified the v2-style quarter Brier
bootstrap: 8 quarters, 2,000 draws, seed 42. The first evaluation output
wrongly applied the economic 12-block minimum to it, which suppressed those
intervals. After correcting that, the evaluation was re-run deterministically.
Every other section is byte-identical, and the first output is retained as
`evaluation-initial.json`.

**Nothing adopted.** The Decision 36–42 freeze and its manifest
`2266d696…` are unchanged. Any of these methods, including the Baseline 0
reversion-rank lead, could become the final-test method only through a new
pre-registration and freeze manifest and the owner's explicit unlock.

## 45. Pre-registered walk-forward replication of the Baseline 0 reversion-rank lead

Recorded 2026-10-17, before the test below was run. Decision 44 found a
post-hoc lead in 2022–2023: on the Baseline 0 gate, a top-20 % rank rule on
reversion-target B beat A. The owner asked for a proper test and for adoption
only if the lead holds.

The untouched 2024–2025 data remain locked, and opening them needs the owner's
explicit unlock and a new data capture. This test therefore replicates the lead
on the twelve earlier years in which it was not discovered.

**Design (h20, frozen Decision 36 headline execution policy and exit):**

1. **Rolling setup.** For each test year Y from 2010 to 2021:
   - train on supervised events whose full label window ends before 1 January
     of Y−1 (2006 onwards);
   - set each model's rank threshold to the 80th percentile of its scores on
     all Baseline 0 events with signals in Y−1, which are out of sample for
     that model;
   - trade every Baseline 0 event with a signal in Y whose score is at least
     that threshold.

   Scores rank events, so calibration does not affect selection.
2. **Primary models.** XGBoost with the same fixed parameters for A and B (the
   Decision 43a B reversion model: depth 3, 400 trees, learning rate 0.03,
   min_child_weight 20, lambda 10) on the reversion label. A uses the 36
   quantitative columns and B uses B_both. Using one family isolates B's
   information.
3. **Secondary models.** Logistic A (C = 0.01) against XGBoost B, the Decision
   43a pairing.
4. **Primary measure.** B − A mean net return per Baseline 0 candidate, pooled
   over 2010–2021. A selected COMPLETE trade contributes its net return, a
   withheld event contributes 0, and a selected unknown execution or a missing
   score is excluded and counted. The interval comes from 2,000 paired
   calendar-month bootstrap draws (seed 5557).
5. **Pass criterion, fixed in advance.** The lead passes only if **both**
   hold:
   - the 95 % interval of the pooled primary measure lies above zero;
   - B − A is positive in at least 8 of the 12 test years.

   Otherwise it fails and is not adopted.
6. **Reporting.** Every year, both model pairs, the selected counts and the
   mean net per COMPLETE trade are reported. 2022 and 2023 are recomputed
   under the same rolling protocol for reference only; they play no part in
   the pass/fail decision.

**If it passes,** the rule is implemented as a separately versioned
final-test candidate method, with a new freeze proposal. It replaces nothing
in the Decision 36–42 freeze without the owner's final-test unlock decision.
**If it fails,** it is recorded and not adopted.

## 46. Walk-forward replication result: the lead fails and is not adopted

Recorded 2026-10-17. The Decision 45 test ran once, as pre-registered: h20,
the frozen Decision 36 headline execution policy, and yearly rolling
retraining with prior-year out-of-sample top-20 % thresholds.

| Model pair | B − A per Baseline 0 candidate, 2010–2021 pooled | 95 % interval | Years B > A | Result |
|---|---|---|---|---|
| Primary: same XGBoost family for A and B | +1.11 bps | [−0.49, +2.79] | 8 of 12 | **Fails** (interval includes zero) |
| Secondary: logistic A, XGBoost B | +2.12 bps | [−0.26, +4.58] | 7 of 12 | Fails |

The primary pair pools 144 months and 18,294 candidates.

B's point estimate is positive and its sign is fairly consistent, but the
pre-registered pass criterion is not met. Under that rule, the Baseline 0
reversion-rank lead is **not adopted**. No final-test candidate method or new
freeze manifest is created.

Mean net returns of the selected trades are negative in many years for both
models, so the rule is not a profitable strategy on its own.

The 2022 and 2023 reference rows, which played no part in the decision, are
+1.0 and +2.1 bps per candidate for the primary pair.

The Decision 36–42 freeze and its manifest `2266d696…` are unchanged. The
2024–2025 final test stays locked.

## 47. Pre-registered SEC timing features and full-coverage catalyst extraction (exploratory)

Recorded 2026-10-17, before either walk-forward test below was run. The owner
asked for two SEC information blocks that stay clear of the deferred
multi-agent layer's job: narrow filing-timing features, and Gemma catalyst
extraction for every event rather than the 500-event pilot. Both are added to
v2's Model B. Neither changes the frozen Decision 36–42 policies, and the
2024–2025 final test stays locked.

**Why the v2 catalyst pilot produced 15 catalysts.** Diagnosed from the v2
coverage records and live probes on 2026-10-17:

1. The free tier allows **16,000 input tokens per minute per Gemma model**
   (`GenerateContentInputTokensPerModelPerMinute-FreeTier`, read from the
   API's own 429 response). v2 prompts were about 6,500 tokens and were sent
   every 8 seconds, roughly 45,000 tokens per minute. The first 429 latched
   the provider, so 455 of the 500 scheduled events were never sent.
2. Of the responses that did arrive, about one third failed validation. A
   diagnostic on 20 v2 packs produced no valid answer: quotations were not
   verbatim copies, 64-character chunk IDs were mis-copied, and NONE answers
   carried invented properties.
3. Half of those diagnostic calls returned HTTP 500, which v2 treated as a
   final failure. `gemma-4-31b-it` returns HTTP 500 for prompts above roughly
   1,500–4,000 tokens, which covers almost every pack, so it is excluded.

**Block 1: filing timing** (`structural_break.intelligence.timing`,
`sec-filing-timing-v1`). Ten features from SEC metadata only, no text or LLM:
for each leg, an 8-K in the last 1 and 3 NYSE sessions and an earnings filing
(8-K item 2.02, 10-Q or 10-K) in the last 3 sessions; whether exactly one leg
filed an 8-K in the last 1 and 3 sessions; and whether the leg with the larger
absolute 1-day abnormal return filed anything in the last 1 and 3 sessions.
A filing counts only when its conservative availability bound is at or before
the signal close; a window opens at the actual close of the session *k*
sessions earlier. A leg whose clock envelope straddles the cutoff, or whose
source inventory does not cover it, is null (UNKNOWN). Disclosed prior look:
while checking the computation I saw that, pooled over all years including
2022–2023, events where the moving leg filed in the last session reverted
6.4 % of the time against 8.7 % otherwise. The feature definitions were
written before that check and are not changed by it.

**Block 2: full-coverage catalysts** (`structural_break.intelligence.catalyst_v3`,
`gemma-sentence-cite-v3`). The v2 evidence packs, the catalyst response schema,
`validate_response` and the 31-column feature block stay unchanged. Changes:

- Chunks are split into numbered sentences and the model cites sentence IDs
  (for example `A1.3`); the citation quote is the exact source sentence,
  filled in locally. Provenance is therefore exact by construction, and leg,
  category-cue and NONE/UNKNOWN rules are still validated.
- A compact plain-text prompt (about 3,900 tokens instead of about 6,500).
  One JSON object, optionally inside a single markdown code fence, is
  accepted; the JSON itself is never repaired. One retry quotes the specific
  validation error.
- Pacing keeps each model under 14,500 input tokens per minute. A per-minute
  429 waits and retries; a daily 429 pauses that model until midnight
  Pacific. HTTP 5xx and timeouts back off and retry up to four times, then
  the pack stays UNKNOWN (`PROVIDER_UNAVAILABLE`) and may be retried in a
  later pass.
- Packs that differ only in event identity share one extraction: 33,321
  distinct packs cover the 37,421 events. Packs are processed in a fixed
  pseudo-random order (a hash of the pack key), h20 model-population packs
  first. Assignment to a model depends only on that order and on timing, and
  every record names its model.
- Model: `gemma-4-26b-a4b-it` only. Flash models stay reserved for the agent
  layer; adding Flash-Lite capacity would need an explicit owner amendment.
- Paid use stays disabled. The key is read from the environment per request
  and is never logged or stored.

**Evaluation** (`structural_break.experiments.p6_sec_features`,
`p6-sec-features-v1`). Each block is tested against v2's B itself, so the
contrast isolates the new information. The protocol is the Decision 45
walk-forward: for test year Y, fit on label windows that ended before Y−1,
take the top-20 % threshold from year Y−1 scores and score year Y.

- Variants: `B_timing` (B plus the ten timing features), `B_full_catalyst`
  (B with the 31 pilot catalyst columns replaced by full-coverage ones) and
  `B_full_catalyst_timing`.
- Target: h20 reversion success. Primary family: logistic, C = 0.01 (v2's
  tuned value for h20 B). Secondary: the fixed Decision 45 XGBoost.
- **Pass criterion** (primary family only): the pooled 2010–2021 paired
  Brier difference (variant minus B), with a calendar-month block bootstrap
  (2,000 draws, seed 5557), has a 95 % interval entirely below zero, and the
  variant has the lower Brier in at least 8 of the 12 years.
- Reported but not part of the verdict: the XGBoost family, the frozen-exit
  top-20 % trading difference per candidate, and 2022–2023 reference rows.
- The timing test runs now. The catalyst tests run once every h20-population
  pack has been attempted at least once; packs that still fail stay UNKNOWN.

A passing block becomes a candidate for a separately versioned Model B with a
new freeze proposal. It replaces nothing without the owner's final-test
unlock decision. A failing block is recorded and not adopted.

## 48. SEC timing result: the block fails and is not adopted; catalyst run started

Recorded 2026-10-17. The Decision 47 timing test ran once, as pre-registered
(`outputs/p6_sec_features/timing_walk_forward.json`, code `9db3f79`).

| Family | B_timing − B Brier, 2010–2021 pooled | 95 % interval | Years better | Top-20 % trading difference per candidate |
|---|---|---|---|---|
| Logistic (primary) | +0.000036 | [−0.000072, +0.000170] | 5 of 12 | +0.63 bps [−0.21, +1.52] |
| XGBoost (secondary) | +0.000062 | [−0.000032, +0.000155] | 6 of 12 | −0.20 bps [−0.91, +0.53] |

18,558 labelled events over 144 months. The 2022–2023 reference rows, which
played no part in the verdict, are −0.000050 (logistic) and −0.000177
(XGBoost).

The interval includes zero and the block is better in fewer than 8 years, so
**B_timing fails and is not adopted**. The pooled descriptive difference noted
in Decision 47 (6.4 % against 8.7 % reversion when the moving leg filed in the
last session) does not add forecasting value once B's 30-day filing metadata
and A's same-day abnormal returns and volume are in the model, which already
mark most news days.

The full-coverage catalyst batch started on 2026-10-17 with
`gemma-4-26b-a4b-it` over 33,322 distinct packs (27,910 in the h20 model
population, processed first). Its first packs return a valid answer about
85–90 % of the time. At the 16,000 tokens per minute free quota it needs
about five days for the h20 packs and six for all of them, provided the
daily request cap does not bind. The catalyst tests in Decision 47 run once
every h20 pack has been attempted. The Decision 36–42 freeze is unchanged and
the 2024–2025 final test stays locked.

## 49. Catalyst extraction amendment v3.1 (before any catalyst evaluation)

Recorded 2026-10-17, after the first 99 packs and before any catalyst feature
or outcome was built or read. The owner asked for the remaining failures to be
fixed and for the stronger Gemini Flash models to stay reserved for the agent
layer, so extraction stays on `gemma-4-26b-a4b-it`.

**Diagnosis of the first 99 v3 packs.** About 26 % ended UNKNOWN through
rejected answers: mostly the category-term check (the cited sentences contain
no term for the claimed category), plus NONE claimed where coverage is
incomplete and BOTH claimed with one leg's sentences only. Throughput was
about 90 packs per hour, half the token budget, because one request at a time
waited for Gemma's answer and 27 % of calls returned an immediate HTTP 500.
Replaying identical requests showed the 500s are random, not caused by the
request.

**Changes (`gemma-sentence-cite-v3.1`).** The evidence packs, response schema,
`validate_response` and the feature block are unchanged.

- The prompt states the validator's category-term rule with its exact term
  list, offers NONE (and affected leg NONE) only when both legs' coverage is
  COMPLETE, and spells out the BOTH rule.
- Up to two retries, each with a correction specific to the error hit. A
  retry stops when the model repeats an answer already rejected. Rejected
  answers (category labels and sentence IDs only) are kept in the record.
- Up to three requests per model in flight under the same 14,500-token
  minute budget. HTTP 5xx is retried after 2, 4, 8, 16, 32 and 60 seconds and
  does not consume the token budget.

**Check on 58 packs.** Of 28 packs rejected under v3, 13 now yield a valid
catalyst and 9 a valid model UNKNOWN; 5 are still rejected. Where traced,
those 5 cite financial-table boilerplate (share counts, column figures) as a
merger or lawsuit, so the validator is right to reject them and they stay
UNKNOWN. Of 30 packs valid under v3, 27 remain valid; categories differ in
about a fifth of them, mostly NONE becoming EARNINGS because v3.1 now cites the
earnings sentences v3 overlooked.

**Run.** Every pack is extracted under v3.1, including the 99 v3 packs, so
the catalyst block comes from one prompt version; v3 records are kept as
earlier attempts. The Decision 47 evaluation is unchanged.

## 50. Pre-registered recent-news catalysts per company (exploratory)

Recorded 2026-10-17, before any extraction for this block was run or any of its
features or outcomes were read. The owner approved replacing the Decision 47
full-coverage catalyst run.

**Why the Decision 47 design was dropped.** A sample of 400 v2 packs showed
that 82 % of their chunks come from 10-Q/10-K reports with a median age of
43–54 days at the divergence (2 % filed within three days); 8-K chunks were
18 % with a median age of 11 days, and the keyword ranking favoured financial
tables. The pack also gets one label for the pair, so it cannot say which
company had news. That design does not test whether a divergence was caused
by fresh news on one company. Its run was stopped after a few hundred packs;
its code (`catalyst_v3`) and records stay in place, and the Decision 47
`B_full_catalyst` test is recorded as not run.

**Block** (`structural_break.intelligence.recent_news`, `sec-recent-news-v1`,
adapter `gemma-leg-news-v1`). For each h20 model event and each company:

- Window: 8-K and 8-K/A filings whose conservative availability bound is
  after the close three NYSE sessions before the signal and at or before the
  signal close (the Decision 47 timing window). The latest two are used.
- Evidence: from each filing, the first chunk of the 8-K document that states
  an Item, and the opening (headline) chunk of its first EX-99 exhibit,
  parsed read-only from the stored SEC archive.
- A company with known filing coverage and no 8-K in the window has no news
  and needs no call. Unknown coverage, an unparseable filing or a rejected
  answer leaves that company UNKNOWN.
- One Gemma (`gemma-4-26b-a4b-it`) label per company: event type, direction,
  materiality and confidence, with sentence-ID citations resolved to exact
  text and the same category-term, NONE and UNKNOWN rules as v3.1. Distinct
  company/filing sets share one extraction: 9,209 packs cover 58,142 event
  legs (35 % of events have news on at least one company).

**Features** (13): for each company, material news (a catalyst of MEDIUM or
HIGH materiality), material negative news, material positive news, earnings or
guidance news, and other corporate news (M&A, regulatory, litigation,
management, product); whether exactly one company had material news; whether
the company with the larger absolute 1-day abnormal return had material news;
and whether that news explains the move (negative news and the stock fell, or
positive news and it rose).

**Evaluation.** Unchanged from Decision 47 (`p6-sec-features-v1`): the
Decision 45 walk-forward, logistic C = 0.01 primary, XGBoost secondary.
Primary variant `B_news` = v2's B plus the 13 features, tested against B.
`B_news_timing` is reported. Pass: the pooled 2010–2021 paired Brier
difference has a 95 % month-block interval entirely below zero and the
variant is better in at least 8 of 12 years. The test runs once every pack
has been attempted (including the automatic retry passes).

A passing block becomes a candidate for a separately versioned Model B with a
new freeze proposal and replaces nothing without the owner's final-test
unlock decision.

### 50a. Recent-news vocabulary amendment (before any feature or outcome was read)

Recorded 2026-10-18, after 73 of 9,209 packs and before any news feature or
outcome was built or read. 16 % of the first answers were rejected, almost
all by the category-term check. Their cited sentences showed that the model
was usually right and the v2 term list was too narrow for 8-K wording: "reports
first quarter results" or "net sales" did not count as EARNINGS, and "entry
into a material definitive agreement", note offerings, credit-agreement
prepayments and tender offers had no fitting category, so the model forced them
into PRODUCT_OTHER.

`gemma-leg-news-v1.1` gives the news block its own vocabulary: a FINANCING
category (offerings, credit agreements, loans, repayments, dividends,
buybacks, tender offers) and standard 8-K terms for each category (for example
"results", "sales" and "per share" for EARNINGS; "agreement" for
PRODUCT_OTHER; "president", "board" and "elect" for MANAGEMENT). Up to ten
citations are accepted. A cited sentence must still contain a term for the
claimed category, citations remain exact source sentences, and table
boilerplate such as "Other comprehensive income (loss)" still fails. The v2
catalyst schema and validator are unchanged. Re-checked offline, 10 of the 12
rejected answers pass the new rule. FINANCING counts as corporate news in the
features. All packs are extracted under v1.1, including the first 73.

## 51. Pre-registered FinBERT tone of recent 8-K news (exploratory)

Recorded 2026-10-18, before any tone was scored for this block or any of its
features or outcomes were read. The owner asked for FinBERT to be tried on the
recent-news evidence as well; v2's FinBERT block itself is unchanged and stays
inside Model B.

**Why.** v2's FinBERT features score the same evidence packs as the v2
catalysts, mostly quarterly-report text about two months old (Decision 50).

**Block** (`structural_break.intelligence.recent_tone`,
`sec-recent-news-tone-v1`). The pinned v2 model and settings
(`ProsusAI/finbert` at `4556d130…`, `sec-sentence-quality-wordpiece-v2`
preprocessing, up to 64 windows per chunk, local CPU, asset hashes checked)
score the Decision 50 recent-news packs: each company's 8-K Item chunk and
press-release headline from the three sessions before the signal. A company's
tone is the token-weighted mean of the positive, negative and neutral
probabilities over its scored windows.

**Features** (7): each company's net tone (positive minus negative) and
negative tone; the net-tone contrast (A minus B); the moving company's net
tone (larger absolute 1-day abnormal return); and that tone times the sign of
its move (positive when the tone agrees with the direction of the move). A
company with known coverage and no recent 8-K is coded zero; unknown coverage
or text with no scorable window is null.

**Evaluation.** As Decision 47: the Decision 45 walk-forward, logistic
C = 0.01 primary, XGBoost secondary, pass rule unchanged. Primary variant
`B_news_tone` = B plus the 7 tone features, tested against B. `B_news_text`
(B plus the 13 Gemma news features and the 7 tone features) is reported. The
test runs once all packs are scored.

**Runtime note.** This checkout's environment has no `torch`; the job runs
with the v2 workspace's environment, which was installed from the same
lockfile (identical pandas, numpy, scikit-learn and pydantic versions), with
this branch's code first on `PYTHONPATH`.

## 52. Pre-registered half-life timeout test (exploratory)

Recorded 2026-10-18, before this test was simulated or any of its outcomes
read. The owner asked for a trading test whose timeout depends on each pair's
half-life, between 1 and 120 sessions.

**Rationale.** The strategy trades mean reversion: a divergence is bet to close,
and a structural break is the case where it does not. The frozen Decision 36
policy times every trade out after 20 sessions, but the median event's
formation-window half-life is 30.4 sessions (10th–90th percentile 14–94). A
gap from |z| = 2 reaches the 0.5 exit band after a 75 % reduction, about two
half-lives, so most trades time out before reversion is expected; a divergence
still open after two half-lives is itself evidence of a break. Disclosed prior
information: the half-life distribution, and the accepted 2022–2023 horizon
sensitivity (Baseline 0 mean net −3.6 bps at 20 sessions, +11.4 bps at 30).

**Rule** (`structural_break.experiments.p6_halflife_exit`,
`p6-halflife-exit-v1`). Timeout = ceil(2 × half-life), bounded to 1–120
sessions, using the event's point-in-time half-life from the accepted h20
model table (20 sessions when unknown). The median timeout is 61 sessions; 20 %
of events reach the 120 cap. Entry, the 0.5 convergence band, the |z| = 3
adverse stop, 5 bps per side and 1 % annual borrow are the frozen headline
values.

**Implementation.** The frozen simulator and contracts are untouched: their
source hash binds the accepted backtests and the contract caps holding at 30
sessions. A research copy reuses the frozen simulator's own entry and runs the
identical exit loop on a longer path built by the frozen session builder from
the same price capture. Before any result is written, the copy must reproduce
the frozen simulator exactly at 20 sessions for every event, or the run stops.
No session after 2023-12-31 is built, so the locked final-test years are never
read; trades still open then are UNPRICED and counted.

**Evaluation.** Fresh h20 events. Primary population Baseline 0 (all priced
events); Baseline 1 (econometrically valid pairs) is secondary. The contrast is
the paired difference in net return per trade (half-life rule minus frozen
rule) over events both rules price.

- **Pass** (Baseline 0): the pooled 2010–2021 difference has a 95 %
  calendar-month block-bootstrap interval (2,000 draws, seed 5557) entirely
  above zero, the rule is better in at least 8 of the 12 years, **and** its net
  return per 20 holding sessions is not below the frozen rule's, so a gain
  that comes only from tying up capital longer does not pass.
- Reported: Baseline 1, exit reasons, mean holding, unpriced counts and
  2022–2023 reference rows.

A passing rule becomes a candidate for a separately versioned execution policy
with a new freeze proposal, and replaces nothing without the owner's
final-test unlock decision. A failing rule is recorded and not adopted.

## 53. Half-life timeout result: the rule fails and is not adopted

Recorded 2026-10-18. The Decision 52 test ran once, as pre-registered
(`outputs/p6_halflife_exit/halflife_exit.json`, code `43abeec`). The research
copy reproduced the frozen simulator exactly at 20 sessions for all 29,071
events (no status or net differences).

| Population, 2010–2021 | Frozen 20 sessions | Half-life timeout | Difference per trade | 95 % interval | Years better |
|---|---|---|---|---|---|
| Baseline 0 (primary), 16,569 trades | −15.9 bps | −24.7 bps | −8.8 bps | [−20.6, +3.0] | 4 of 12 |
| Baseline 1, 1,499 trades | −11.0 bps | −8.9 bps | +2.1 bps | [−6.2, +10.3] | 7 of 12 |

Net return per 20 holding sessions was less negative under the half-life
rule (Baseline 0 −12.6 against −19.5 bps), only because the same losses are
spread over 39.1 instead of 16.4 sessions on average. Per trade, the interval
includes zero and fewer than 8 years improve, so **the rule fails and is not
adopted**.

Under the longer timeout, 8,265 of the 16,569 Baseline 0 trades ended at the
|z| = 3 adverse stop, 3,651 converged and 4,653 timed out. Extra time mostly
let diverging spreads reach the stop rather than letting reversions finish,
consistent with many divergences being structural breaks rather than slow
mean reversion. The 2022–2023 reference rows favoured the rule (Baseline 0
+6.8 bps, n = 3,003), as the earlier 30-session sensitivity had; the twelve
decision years do not, which is why that sensitivity was not treated as
evidence. The Decision 36–42 freeze is unchanged and the 2024–2025 final test
stays locked.

## 54. Recent-news and tone results: both blocks fail and are not adopted

Recorded 2026-10-18. The Decision 50 extraction finished: 9,209 packs, 8,641
catalysts, 260 NONE, 24 model UNKNOWN, 281 rejected and 3 server failures
after the automatic retry passes. The Decision 51 FinBERT scoring finished for
all 9,209 packs. The evaluation watcher then ran the pre-registered walk-forward
once (`outputs/p6_sec_features/news_walk_forward.json`).

Coverage: each company's recent-news status is known for 91–93 % of event
legs. In 22 % of events the company with the larger 1-day abnormal return had
material news in the three sessions before the signal; in 10 % that news
matched the direction of its move.

| Variant (logistic, primary) | Brier vs B, 2010–2021 pooled | 95 % interval | Years better | Top-20 % trading difference per candidate |
|---|---|---|---|---|
| `B_news` (Decision 50 primary) | +0.000010 | [−0.000075, +0.000092] | 7 of 12 | +0.04 bps [−0.86, +0.93] |
| `B_news_tone` (Decision 51 primary) | +0.000078 | [−0.000005, +0.000168] | 6 of 12 | +0.53 bps [−0.18, +1.28] |
| `B_news_text` | +0.000051 | [−0.000058, +0.000154] | 5 of 12 | +0.19 bps [−0.65, +1.05] |
| `B_news_timing` | +0.000027 | [−0.000079, +0.000128] | 5 of 12 | +0.11 bps [−0.73, +0.98] |

The XGBoost family agrees (Brier differences +0.000006 to +0.000048, none with
an interval below zero). **Both blocks fail and are not adopted.** Fresh 8-K
news on the moving company does not improve the reversion forecast beyond
v2's Model B, which already holds the same-day abnormal returns and volume
spikes through which such news reaches prices. The Decision 36–42 freeze, the
accepted v2 snapshot and the 2024–2025 lock are unchanged.

## 55. Pre-registered explore-then-confirm search over the three SEC blocks

Recorded 2026-10-18, before any variant below was scored. The owner asked for
filing timing, recent news and recent-news tone each to be explored in many
ways, informed by the literature. To keep a positive finding interpretable
after many tries, exploration and confirmation use separate years and the
final selection is fixed before confirmation.

**Literature basis.** Pairs that diverge on value-relevant firm-specific news
are less profitable than those diverging on common or no news (Engelberg, Gao
and Jagannathan; Jacobs and Weber); large moves without news partly reverse
while bad news drifts (Chan 2003); a structured-news overlay that skips trades
whose divergence comes with negative sentiment and abnormal news volume
halved non-converging pairs (FactSet summary); 8-K text predicts returns
mostly over the next one to five days. The earlier tests (Decisions 47–54)
only added the blocks to a heavily regularised forecasting model; here they
are also tried as trade filters.

**Variants** (`structural_break.experiments.p6_sec_explore`, `p6-sec-explore-v1`).
The moving company is the leg with the larger absolute 1-day abnormal return;
a filter skips an event only when its condition is known to hold.

- Timing filters: T1 moving company filed an 8-K in the last session; T2
  filed anything in the last 3 sessions; T3 earnings filing in the last 3; T4
  one-sided 8-K in the last session; T5 either company had an earnings
  filing in the last 3; T6 T1 and the moving company fell.
- News filters: N1 moving company had material news; N2 that news explains
  its move; N3 material negative news; N4 N3 and it fell; N5 one-sided
  material news; N6 corporate (non-earnings) news; N7 earnings or guidance
  news; N8 material news on the moving company but not the other (common
  news kept).
- Tone filters (thresholds fixed from the feature distribution, no outcomes):
  S1 moving company's net tone below −0.1; S2 tone aligned with its move at
  least 0.2; S3 S1 and it fell; S4 absolute tone contrast at least 0.3; S5
  negative tone probability at least 0.2.
- Each filter on Baseline 0 (all events) and Baseline 1 (valid pairs).
- Model variants per block, Decision 45 walk-forward, top-20 % rule against
  the same specification without the block: M1 logistic C = 0.1; M2 logistic
  C = 1; M3 logistic C = 0.01 with each block feature split by whether the
  moving company fell or rose; M4 XGBoost; M5 Model A plus the block
  (against A).

That is 38 filter and 15 model variants. Every contrast is the paired
per-candidate difference in net return under the frozen Decision 36 policy
(a skipped trade earns zero), with a calendar-month block bootstrap (2,000
draws, seed 5557).

**Stage 1, explore.** Filters are scored on 2006–2015 and models on 2010–2015.
Per block, the chosen variant is the one with the largest bootstrap t-statistic
among variants with a positive estimate (the largest t overall if none is
positive). The choices are written to `choices.json` and recorded with their
checksum before stage 2.

**Stage 2, confirm.** Only the three chosen variants are evaluated on
2016–2021. A block passes when its estimate is positive, its one-sided
bootstrap p-value after a Holm correction across the three blocks is below
0.05, and it is positive in at least 4 of the 6 years.

**Disclosed prior information.** The pooled 2010–2021 model results and
per-year Brier differences of the Decision 47–54 variants have been seen; no
filter outcome has been seen. 2022–2023 are not used here, and the 2024–2025
final test stays locked. A passing block becomes a candidate for a separately
versioned policy or Model B and replaces nothing without the owner's
final-test unlock decision.

### 55a. Exploration choices, fixed before confirmation

Recorded 2026-10-18. Stage 1 ran once (`outputs/p6_sec_explore/exploration.json`);
41 of the 53 variants had a positive exploration estimate, and in every block
the skipped trades (where the moving company had fresh news) lost far more
than the average trade. The chosen variants, written to
`outputs/p6_sec_explore/choices.json` (SHA-256
`89969591ce56fbd4a716231063356f43d3093253d5f897fcf37cea9a05515265`), are:

| Block | Variant | Exploration estimate | t |
|---|---|---|---|
| Timing | T3 filter on Baseline 0: skip when the moving company filed an earnings report (8-K item 2.02, 10-Q or 10-K) in the last 3 sessions | +4.6 bps per candidate (2006–2015) | 2.37 |
| News | M2: Model B plus the 13 news features, logistic C = 1, top-20 % rule | +1.4 bps per candidate (2010–2015) | 2.54 |
| Tone | S5 filter on Baseline 0: skip when the moving company's recent-news FinBERT negative probability is at least 0.2 | +1.7 bps per candidate (2006–2015) | 1.99 |

No 2016–2021 outcome had been read for any filter, or for these model
variants, when this record was made.

## 56. Explore-then-confirm result: two news filters replicate but miss the corrected threshold

Recorded 2026-10-18. Stage 2 ran once on 2016–2021
(`outputs/p6_sec_explore/confirmation.json`, choices `89969591…`).

| Block | Variant | 2016–2021 per-candidate difference | 95 % interval | One-sided p | Holm p | Years positive | Result |
|---|---|---|---|---|---|---|---|
| Timing | T3 earnings-filing filter | +3.76 bps | [−0.59, +7.58] | 0.043 | 0.086 | 5 of 6 | Fails (Holm) |
| Tone | S5 negative-tone filter | +2.23 bps | [−0.02, +4.61] | 0.027 | 0.080 | 4 of 6 | Fails (Holm) |
| News | M2 logistic C = 1 | −0.92 bps | [−2.43, +0.46] | 0.898 | 0.898 | 3 of 6 | Fails |

**No block passes the pre-registered rule, so none is adopted.** The two filters
did replicate in direction and size: in 2016–2021 the trades T3 skips (15.8 %
of events) lost 23.7 bps each and those S5 skips (5.3 %) lost 41.7 bps, against
about −10 bps for the trades kept, matching the exploration years and the
literature on news-driven divergences. Their uncorrected one-sided p-values are
below 0.05, but the Holm correction for three blocks puts both at about 0.08.
The news-model variant, chosen narrowly over the news filters, did not
replicate. This is suggestive, not confirmatory, evidence that skipping
divergences where the moving company has fresh news helps. The Decision 36–42
freeze and the 2024–2025 lock are unchanged.

## 57. Pre-registered replication of a combined fresh-news filter on 2022–2023

Recorded 2026-10-18, before the test was run. The owner asked to keep
exploring. Decision 56 showed that the two filter blocks replicated in
direction on 2016–2021 but missed the Holm threshold. They express one idea:
do not bet on reversion when the moving company has just had value-relevant
news. This combined rule was chosen **after** seeing the Decision 56
confirmation, so it needs data on which no filter outcome has been read:
2022–2023 (other experiments used those years, but no filter was evaluated
there).

**Rule R1** (`p6_sec_explore replicate`): skip the event when the moving
company (larger absolute 1-day abnormal return) filed an earnings report
(8-K item 2.02, 10-Q or 10-K) in the last 3 sessions, **or** its recent-news
FinBERT negative probability is at least 0.2. Unknown conditions never skip.

**Test.** Baseline 0, all priced fresh h20 events signalled in 2022–2023,
paired per-candidate net-return difference against trading every event,
calendar-month block bootstrap (2,000 draws, seed 5557). **Pass:** a positive
estimate with a one-sided bootstrap p-value below 0.05; it is a single test,
so no further correction. T3 and S5 alone are reported alongside. With 24
months the test has limited power; an inconclusive result is reported as such.

## 58. Combined fresh-news filter replication: positive but inconclusive

Recorded 2026-10-18. The Decision 57 test ran once on 2022–2023
(`outputs/p6_sec_explore/replication.json`).

| Filter | 2022–2023 per-candidate difference | 95 % interval | One-sided p | Skipped share | Skipped / kept mean net |
|---|---|---|---|---|---|
| R1 combined (pre-registered test) | +1.41 bps | [−5.28, +9.07] | 0.347 | 17.5 % | −8.0 / −2.6 bps |
| S5 negative tone (reported) | +2.03 bps | [−1.22, +5.32] | 0.110 | 5.4 % | −37.9 / −1.6 bps |
| T3 earnings filing (reported) | +1.84 bps | [−4.51, +9.51] | 0.305 | 16.7 % | −11.0 / −2.1 bps |

R1 is positive in both years but **does not pass** (p = 0.35); with 24 months
the test is underpowered. Across the three disjoint periods the negative-tone
filter has behaved the same way each time: the trades it skips lost 34.7 bps
(2006–2015), 41.7 bps (2016–2021) and 37.9 bps (2022–2023) on average,
against −1.6 to −10.5 bps for the trades kept. That consistency is the
strongest evidence in this project that SEC news helps identify divergences
that are breaks rather than noise, but no pre-registered test has yet confirmed
it at the required level, so nothing is adopted. The 2024–2025 final test, the
only untouched data, stays locked.

## 59. Pre-registered second exploration round: news exits, graded sizing, sharper entry news

Recorded 2026-10-19, before any variant below was scored. The owner asked to
build the three proposed directions and to search for further improvements.

**Additional literature.** Closing pairs that have not converged within
10 days improved risk-adjusted returns in Engelberg, Gao and Jagannathan, who
also find that liquidity-driven divergences converge while fundamental news
does not; earnings news tends to continue and softer news to reverse; tone
relative to a firm's own history ("tone surprise") carries information beyond
raw tone; abnormal news volume marks attention shocks.

**New data** (`structural_break.experiments.headline_coverage`,
`sec-8k-headline-tone-v1`): every 8-K of the frozen issuers from 2005-11 to
2023-12 is parsed read-only from the stored archive, and the first three scored
sentences of its press-release headline (first EX-99 chunk, else the first Item
chunk) are scored with v2's pinned FinBERT. Availability is the conservative
acceptance bound.

**Variants** (`structural_break.experiments.p6_sec_explore2`,
`p6-sec-explore2-v1`), each on Baseline 0 and Baseline 1. The moving company
is the leg with the larger absolute 1-day abnormal return.

- **Family E, exits during the trade** (frozen entry, band, stop, costs and
  borrow; a qualifying item accepted after the signal close exits the trade at
  the next open after the session close at which it is available): E1 any 8-K
  by the moving company; E2 an earnings report by it (8-K item 2.02, 10-Q or
  10-K); E3 an adverse-toned headline on either leg (net ≤ −0.1 on the long
  leg, or ≥ +0.1 on the short leg); E4 a headline by the moving company with
  negative probability ≥ 0.2; E5 a 10-session timeout. The research exit loop
  (Decision 52 copy, extended with this trigger) must reproduce the frozen
  simulator exactly when no news trigger is supplied.
- **Family Z, graded sizing** (weight in [0, 1], unknown = 1): Z1
  1 − 2 × the moving company's recent-news FinBERT negative probability
  (Decision 51); Z3 0 for earnings or guidance news on the moving company,
  0.5 for its material corporate news, else 1 (Decision 50 labels); Z4
  1 − 2 × its highest headline negative probability in the last 3 sessions.
- **Family H, sharper entry evidence** (skip when known true): H1 moving
  company's headline negative probability ≥ 0.2 in the last session; H2 its
  headline net tone < −0.1 in the last session; H3 its lowest headline net
  tone in the last 3 sessions minus the mean of its headlines over the prior
  year (at least 3) < −0.2; H4 at least two 8-Ks by it in the last 5
  sessions; H5 headline negative probability ≥ 0.2 in the last 3 sessions.

That is 26 variants. Contrasts are paired per-candidate net-return differences
(variant minus the frozen rule) with the Decision 55 bootstrap.

**Stage 1** scores all variants on 2006–2015 (exits are simulated for those
years only) and picks, per family, the variant with the largest bootstrap t
among positive estimates (largest t overall if none). **Stage 2** evaluates
only the three choices on 2016–2021. A family passes with a positive estimate,
a Holm-corrected one-sided p below 0.05 across the three families, and at least
4 of 6 positive years.

**Disclosed prior information.** Z1, Z4, H5 and E4 are relatives of the
Decision 51/55 negative-tone filter, whose outcomes have been seen in every
period (Decisions 55–58), so their exploration results may look optimistic;
the 2016–2021 confirmation is the check. No outcome of any listed variant has
been read. 2022–2023 are not used, and 2024–2025 stay locked.

### 59a. Round-2 exploration choices, fixed before confirmation

Recorded 2026-10-19 automatically by `scripts/round2_watcher.ps1`
immediately after stage 1 and before stage 2 ran; the commit containing this
record precedes the confirmation run. Stage 1 explored 26 variants on 2006–2015, 25 with a positive estimate.
`outputs/p6_sec_explore2/choices.json` SHA-256 `3054926796749cfa5e9231b5928358930c5ec3a43ac4799105f6c4722b8710b5`.

| Family | Variant | Population | Exploration estimate | t |
|---|---|---|---|---|
| exit | E3_adverse_tone_either_leg | B0 | +4.86 bps per candidate | 2.51 |
| sizing | Z1_recent_tone_weight | B0 | +1.43 bps per candidate | 2.11 |
| entry | H2_mover_net_headline_1s | B0 | +1.61 bps per candidate | 2.92 |

## 60. Round-2 confirmation result

Recorded 2026-10-19 automatically by `scripts/round2_watcher.ps1`
after the one-time Decision 59 stage 2 on 2016–2021
(`outputs/p6_sec_explore2/confirmation.json`, choices `30549267…`).

| Family | Variant | Population | 2016–2021 difference | 95 % interval | One-sided p | Holm p | Years positive | Result |
|---|---|---|---|---|---|---|---|---|
| exit | E3_adverse_tone_either_leg | B0 | +6.11 bps | [+1.38, +11.25] | 0.004 | 0.012 | 6 of 6 | **Passes** |
| sizing | Z1_recent_tone_weight | B0 | +1.55 bps | [-0.20, +3.29] | 0.042 | 0.084 | 4 of 6 | Fails |
| entry | H2_mover_net_headline_1s | B0 | +1.01 bps | [-0.29, +2.28] | 0.059 | 0.084 | 4 of 6 | Fails |

**Passing:** exit. A passing family becomes a candidate for a separately versioned policy with a new freeze proposal and replaces nothing without the owner's final-test unlock decision.
The Decision 36–42 freeze and the 2024–2025 lock are unchanged.

## 61. Pre-registered 2022–2023 replication of the adverse-tone news exit

Recorded 2026-10-19, after Decision 60 and before this test was run. The E3
exit rule passed its 2016–2021 confirmation. 2022–2023 are fresh for exit
rules: no exit-variant outcome has been read for those years (the
Decision 52–53 half-life rows for 2022–2023 concern a different exit and were
reference rows). The owner asked to keep exploring; a second, independent
period is the strongest check available before the locked final test.

**Rule:** E3 exactly as fixed in Decision 59 (exit at the next open after an
8-K headline with net tone ≤ −0.1 on the long leg, or ≥ +0.1 on the short
leg, becomes available during the trade; frozen entry, band, stop, costs and
borrow). **Test:** Baseline 0, events signalled in 2022–2023, paired per-trade
net-return difference against the frozen exit over trades both price,
calendar-month block bootstrap (2,000 draws, seed 5557). **Pass:** a positive
estimate with a one-sided p below 0.05; a single test, so no correction. With
24 months the test has limited power, and an inconclusive result is reported
as such.

## 62. News-exit replication and status: confirmed once, positive in every period

Recorded 2026-10-19. The Decision 61 test ran once
(`outputs/p6_sec_explore2/replication.json`): on 2022–2023 the E3
adverse-tone news exit changed Baseline 0 net return per trade by **+2.20 bps,
95 % [−3.75, +8.52], one-sided p = 0.243** (3,153 trades, 24 months; 2022
+4.8, 2023 −1.3 bps), moving the mean from −3.6 to −1.4 bps. It does not pass
on its own; with two years the test is underpowered.

**Status of E3.** It is the first rule in this project to pass a
pre-registered, multiplicity-corrected confirmation (Decision 60: +6.11 bps
per trade, 95 % [+1.38, +11.25], Holm p = 0.012, positive in all six years
2016–2021), and its estimate is positive in all three disjoint periods
(2006–2015 exploration +4.86, 2016–2021 +6.11, 2022–2023 +2.20 bps). It closes
about a quarter of trades early, when an 8-K headline contradicts the position:
bad news on the stock held long or good news on the stock held short — the
case where the divergence is a fundamental break rather than noise.

Per Decision 59, E3 is now a **candidate** for a separately versioned
execution policy with its own freeze proposal. It is not adopted into the
Decision 36–42 freeze, and the 2024–2025 final test stays locked until the
owner explicitly decides on the methodology and authorises that run. The
improvement is per trade; Baseline 0's mean net return stays negative, so the
rule reduces losses rather than making the unfiltered strategy profitable on
its own.

## 63. Pre-registered round 3: news exit plus entry rules, and the news exit on model trades

Recorded 2026-10-19, before any part of this round was scored. The owner asked
to (1) combine the confirmed E3 news exit with the entry rules that were
positive but inconclusive (including the Z sizing and H headline rules), then
(2) check the news exit on model-selected trades, while the final test stays
locked.

**This round is post-hoc.** Every period through 2023 has already been used
for at least one component (E3 was confirmed on 2016–2021 and replicated on
2022–2023; the entry rules' outcomes were seen in rounds 1–2). Its results are
supporting evidence for the eventual final-test design, not independent
confirmation, and are reported as such.

**Part 1, combinations** (`structural_break.experiments.p6_sec_explore3`,
`p6-sec-explore3-v1`). Baseline 0, trades priced under both the frozen exit
and E3. Each combination applies one entry rule on top of E3; the contrast is
its gain over E3 alone (a skipped trade earns 0, a down-weighted trade earns
weight × its E3 net), also reported against the frozen policy. Entry rules:
C1 S5 negative recent-news tone; C2 T3 earnings filing; C3 R1 (T3 or S5); C4
N2 news explains the move; C5 H1 negative headline in the last session; C6 H2
net headline tone in the last session; C7 H4 abnormal 8-K volume; C8 Z1
recent-tone weight; C9 Z3 news-type weight; C10 Z4 headline-tone weight; C11
H2 and Z1; C12 T3 and H2. The combination with the largest bootstrap t among
positive gains on 2006–2015 is written to
`outputs/p6_sec_explore3/choices.json` and recorded before it is evaluated on
2016–2023. Rule: a positive gain over E3 with one-sided p below 0.05 and at
least 5 of 8 positive years; every combination's 2016–2023 result is reported.

**Part 2, model trades.** For Models A and B (logistic C = 0.01 and the
Decision 45 XGBoost), the Decision 45 walk-forward top-20 % selections for
2010–2023 are priced under the frozen exit and under E3; the paired
per-candidate difference is reported pooled and for 2010–2015, 2016–2021 and
2022–2023. This is a consistency check with no pass rule.

### 63a. Round-3 combination choice, fixed before evaluation

Recorded 2026-10-19 after the 2006–2015 combination scoring
(`outputs/p6_sec_explore3/combine_exploration.json`). All 12 combinations
improved on E3 alone there (+0.67 to +4.24 bps per candidate). The chosen
combination is **C3: E3 plus the R1 entry filter** (skip when the moving
company filed an earnings report in the last 3 sessions or its recent-news
FinBERT negative probability is at least 0.2): +4.24 bps over E3, t = 2.19,
+9.10 bps against the frozen policy; 16.4 % of trades skipped.
`outputs/p6_sec_explore3/choices.json` SHA-256
`a9a3a31ea88a7fef9ee25d58b2be8fcdb838e2faaddf3fb401e52751b870e74d`. No
2016–2023 combination outcome had been read when this was recorded.

## 64. Round-3 results (post-hoc): entry rules add to the news exit; it also helps model trades

Recorded 2026-10-19 (`outputs/p6_sec_explore3/combine_evaluation.json`,
`models.json`). As stated in Decision 63, these results use data whose
components were already seen and are supporting evidence, not confirmation.

**Part 1, combinations, 2016–2023.** The pre-chosen C3 (E3 plus the R1 filter)
gained **+2.44 bps per candidate over E3 alone, 95 % [−0.74, +5.58], one-sided
p = 0.070, positive in 7 of 8 years**, so it misses the pre-registered rule. It
gained +7.58 bps against the frozen policy (95 % [+2.02, +13.44], p = 0.004).
All 12 combinations were positive over E3 in 2016–2023, from +0.63 to
+3.10 bps; the largest were C7 abnormal 8-K volume (+3.10, p < 0.001), C12 T3
and H2 (+2.54), C2 T3 (+2.41) and C3 (+2.44). These were reported, not chosen
in advance, so they are not corrected for twelve looks.

**Part 2, model trades, 2010–2023.** Decision 45 walk-forward top-20 %
selections priced under the frozen exit and under E3:

| Model | Selected trades | Mean net per trade, frozen → E3 | Gain per candidate | 95 % interval | One-sided p | 2010–15 / 2016–21 / 2022–23 |
|---|---|---|---|---|---|---|
| Logistic A | 4,710 | −3.0 → +0.2 bps | +0.77 bps | [−0.24, +1.92] | 0.077 | +1.10 / +1.16 / −1.16 |
| Logistic B | 4,594 | −4.9 → 0.0 bps | +1.14 bps | [−0.01, +2.50] | 0.027 | +1.25 / +1.88 / −1.35 |
| XGBoost A | 4,604 | +2.6 → +4.5 bps | +0.42 bps | [−0.48, +1.38] | 0.187 | +1.21 / +0.44 / −1.38 |
| XGBoost B | 4,532 | +8.3 → +12.0 bps | +0.85 bps | [−0.25, +2.04] | 0.067 | +1.67 / +1.23 / −2.16 |

The news exit raises net return per selected trade for every model, and the
XGBoost Model B selection with the news exit (+12.0 bps per trade over
2010–2023) is the strongest combination observed in this project. The gain is
positive in 2010–2015 and 2016–2021 for every model but negative in 2022–2023,
where E3's Baseline 0 replication was also weaker.

**Implication for the final test** (still locked; for the owner's decision): a
candidate methodology is the frozen entry with the E3 news exit, optionally
with an R1- or H4-style entry filter, evaluated on Baseline 0 and on the Model B
selection. Choosing among these is a design decision to fix before the final
test, not something further 2006–2023 testing can settle.

## 65. Pre-registered boosting tuning, model families and cross-validation (workstream 1)

Recorded 2026-10-19 on branch `p6/boosting-tuning`, before any run below. The
owner asked whether tuning XGBoost, other boosting libraries or better
cross-validation could improve the forecasts and the returns. The 2024–2025
final test stays locked; nothing here changes the frozen Decision 36–42
policies or the accepted v2 snapshot.

**Reference (R0).** The Decision 45 walk-forward with its fixed XGBoost
(depth 3, 400 trees, learning rate 0.03, min_child_weight 20, lambda 10,
seed 42) on the reversion label, for Model B (B_both columns, primary) and
Model A (36 quantitative columns, secondary). R0 was checked to reproduce the
Decision 45 B selections exactly (2010: 90 trades, −45.4 bps; 2016: 304
trades, +5.7 bps).

**Variants.** For every test year Y (2010–2023) each variant is tuned only on
the Decision 45 training window (label windows ending before 1 January Y−1):

| Variant | Library | Inner cross-validation | Tuning objective |
|---|---|---|---|
| V1 | XGBoost | forward-chaining | log loss |
| V2 | XGBoost | purged K-fold with embargo | log loss |
| V3 | LightGBM | forward-chaining | log loss |
| V4 | CatBoost | forward-chaining | log loss |
| V5 | Equal-weight mean of the calibrated V1, V3 and V4 probabilities | — | — |
| V6 | XGBoost | forward-chaining | top-20 % precision |

- **Forward-chaining folds:** each of the last 4 signal years in the window
  (fewer when the window is short) is validated on a model fit to events
  whose label windows ended before that year, so the label horizon purges the
  boundary.
- **Purged K-fold:** 5 contiguous blocks in time; fit rows whose label window
  overlaps the validation block are removed, plus a 30-day embargo after it
  (López de Prado 2018).
- **Search:** Optuna TPE, 30 trials (10 random start-up), sampler seed 5557,
  fixed spaces in `p6_boosting.suggest` (learning rate 0.02–0.2, depth or
  leaves, child weight, row and column subsampling, L1/L2 penalties, and
  CatBoost's random strength and bagging temperature). Each fold uses early
  stopping (up to 1,500 trees, patience 100) on its validation log loss. The
  refit uses the mean best tree count. Fits are single-threaded with seed 42.
- **Scoring:** the refit model scores the Y−1 and Y events. Probabilities are
  recalibrated with the project's monotone Platt sigmoid fitted on Y−1 events
  whose label window ended before 1 January Y. Selection is the Decision 45
  top-20 % rule: a Y event is traded if its score is at least the 80th
  percentile of the Y−1 scores (V5 ranks by its mean calibrated probability).
  Every trade is priced with the frozen Decision 36 policy.

**Primary measures (Model B, pooled 2010–2021, paired against R0).**

1. **Forecast:** Brier score gain, R0 − variant squared error per labelled
   test event.
2. **Return:** net return per Baseline 0 candidate, variant − R0 (selected
   COMPLETE trade = its net return, withheld = 0, selected unknown execution
   excluded).

Intervals and one-sided p-values come from 2,000 calendar-month block
bootstrap draws (seed 5557). Within each measure, Holm's correction is applied
across the six variants. A variant **passes** a measure only if its gain is
positive, Holm-adjusted p < 0.05, and the gain is positive in at least 8 of
the 12 years.

**Reported without a pass rule:** log loss, ROC-AUC and PR-AUC; mean net per
selected trade; the same contrasts for Model A; the return contrast with the
E3 news exit (Decision 60) on events priced under both exits; 2022–2023
reference rows; the tuned parameters and inner-fold scores for every year.

**Adoption.** A passing variant becomes a candidate model for the final-test
design. Adopting it needs a separate freeze proposal and the owner's
decision.

Module: `structural_break.experiments.p6_boosting`, output
`outputs/p6_boosting/`.

## 66. Boosting tuning result: no variant beats the fixed XGBoost

Recorded 2026-10-19 (`outputs/p6_boosting/evaluation.json`, SHA-256
`742ef541…`). The Decision 65 run finished as pre-registered: 168 tasks,
38 CPU-hours. R0 reproduced the Decision 45 selections.

**Model B, 2010–2021 pooled, against R0 (fixed Decision 45 XGBoost):**

| Variant | Brier gain (×10⁻⁴), 95 % | Years better | Return gain per candidate, 95 % | Years better | Mean net per selected trade |
|---|---|---|---|---|---|
| R0 fixed XGBoost | — | — | — | — | +3.2 bps |
| V1 XGBoost, forward CV | +0.20 [−2.44, +2.80] | 5/12 | −1.60 bps [−3.53, +0.18] | 2/12 | −4.4 bps |
| V2 XGBoost, purged K-fold | +1.16 [−1.05, +3.30] | 8/12 | −1.06 bps [−3.23, +0.91] | 6/12 | −1.9 bps |
| V3 LightGBM | −2.22 [−4.86, +0.29] | 3/12 | −0.85 bps [−2.63, +0.76] | 4/12 | −0.8 bps |
| V4 CatBoost | −3.04 [−8.78, +1.58] | 6/12 | −1.69 bps [−3.69, +0.15] | 4/12 | −4.9 bps |
| V5 ensemble | +0.90 [−1.68, +3.33] | 8/12 | −1.98 bps [−3.62, −0.43] | 3/12 | −6.2 bps |
| V6 XGBoost tuned for top-20 % precision | −1.48 [−5.48, +2.36] | 4/12 | −2.59 bps [−4.34, −0.88] | 3/12 | −8.9 bps |

All Holm-adjusted p-values are at least 0.86, so **no variant passes either
primary measure** and none is adopted. ROC-AUC is 0.749–0.758 for every
variant against 0.757 for R0. The 2022–2023 reference rows agree: R0's
selected trades average +38.3 bps, and every tuned variant is lower
(+21.5 to +37.5 bps).

**Secondary results.**
- Model A: nothing passes. The ensemble has the best Brier gain,
  +2.38 × 10⁻⁴ [+0.20, +4.53] in 10 of 12 years, but its Holm p is 0.093.
  Return gains range from −0.40 to +0.30 bps.
- The E3 news exit raises every variant's per-trade return, but R0 with E3
  (+9.3 bps per trade) stays the best.

**Interpretation.**
- The fixed shallow, heavily regularised XGBoost (depth 3, min_child_weight 20,
  lambda 10, 400 trees at 0.03) is already about as good as the inner
  cross-validation can find.
- The tuned settings jump between years: for example, CatBoost B uses depth 4
  in 2010, 8 in 2016 and 4 in 2021, and the 2010 XGBoost uses 26 trees at a
  0.17 learning rate. This shows that hyperparameter selection mostly fits
  noise in the inner folds at this signal level (base rate about 8 %,
  AUC about 0.75).
- Tuning on the economic objective (V6) did worst on returns, which supports
  training and tuning on the reversion label with proper scoring rules.
- Purged K-fold (V2) was the most stable search scheme: best Brier gain for
  Model B and 10 of 12 years for Model A. It is not significant.

The Decision 36–42 freeze is unchanged, and the 2024–2025 final test stays
locked.

## 67. Pre-registered alternative cointegration features and gates

Recorded 2026-10-19, before any outcome below was computed. The owner asked
whether a better cointegration test or hedge ratio than Engle-Granger with OLS
would help. Redefining the spread would change every event, so this first
step keeps the events and asks whether the alternatives carry information.
The 2024–2025 final test stays locked.

**Features (21, `structural_break.experiments.p6_coint`).** For each event,
the formation window is rebuilt from the frozen prices: the last 504 sessions
with valid prices for both legs before the relationship became available.
OLS on the rebuilt windows reproduces the stored alpha and beta to within
1e-13 (checked on two pairs before registration; `build_check.json` records
every event). On that window:

- **Tests:** Engle-Granger t in the reverse direction and the larger of the
  two directional p-values; Johansen trace and max-eigenvalue statistics
  divided by their 5 % critical values; KPSS; Hurst exponent (lags 2–20);
  20-session variance ratio.
- **Alternative hedge ratios:**
  - Johansen;
  - total least squares;
  - minimum ADF t (fixed lag 1; data-snooped by design, so used as a feature
    with no critical value);
  - minimum half-life (positive ratios, grid plus refinement).

  For each ratio the features are its gap to the OLS beta, divided by
  max(|beta|, 0.1) and clipped to ±3. TLS also gets its ADF t, minimum-ADF
  its t, and minimum half-life its half-life.
- **Robustness of the divergence:** the event-day z-score of the spread under
  each alternative ratio, using that window's mean and standard deviation and
  aligned with the signal direction. Their minimum is also a feature.
- **Kalman filter:** a random-walk alpha and beta (delta 1e-4, observation
  variance 1e-3) run forward over the pair's prices. Its event-day beta gap
  and the event-day prediction error divided by the standard deviation of the
  previous 60 errors (aligned) are features. The filter uses past prices only.

**Test 1, model features (Decision 45 walk-forward).**
- **Comparison:** base model against base plus the 21 features, for
  logistic (C = 0.01) and the fixed XGBoost, Models B and A.
- **Primary:** Model B Brier gain (base minus with-features squared error),
  pooled 2010–2021, with 2,000 calendar-month block bootstrap draws
  (seed 5557) and Holm across the two families.
- **Pass rule:** positive gain, Holm p < 0.05, better in at least 8 of
  12 years.
- **Reported, no pass rule:** Model A, top-20 % returns and 2022–2023.

**Test 2, validity gates on Baseline 0 (frozen exit).** Each gate keeps an
event only if:

| Gate | Keep the event if |
|---|---|
| G1 | Johansen rejects no cointegration (trace ratio ≥ 1) |
| G2 | Engle-Granger rejects in both directions (larger p < 0.05) |
| G3 | KPSS does not reject stationarity (< 0.463) |
| G4 | the divergence holds under every alternative ratio (minimum aligned z ≥ 1.5) |
| G5 | Hurst < 0.5 |
| G6 | minimum half-life ≤ 20 sessions |

- **Measure:** gated minus trade-all per candidate, where a withheld trade
  earns 0.
- **Steps:** score all six on 2006–2015 and fix the best positive gate by t
  in `gate_choice.json`, recorded before 2016–2021 is scored. That gate
  passes if its 2016–2021 gain is positive with one-sided p < 0.05 and it is
  positive in at least 4 of 6 years.
- **Reported:** every gate's 2016–2021 and 2022–2023 results, plus the
  existing Engle-Granger gate (Baseline 1) for reference.

**Adoption.** A pass would justify a separately pre-registered redefinition
of the spread or of the pair-validity rule (a v3 event rebuild). It would not
be adopted directly.

### 67a. Gate choice, fixed before 2016–2021 was scored

Recorded 2026-10-19 after the 2006–2015 gate scoring
(`outputs/p6_coint/gate_exploration.json`). Trading every Baseline 0 event
lost money in 2006–2015, so every gate gained by withholding trades. The
table shows each gate's gain per candidate, the share of events kept, and
the mean net per trade of kept and withheld events.

| Gate | Gain | Kept | Kept trades | Withheld trades |
|---|---|---|---|---|
| G2 | +13.1 bps, t 3.37 | 8 % | +1.2 bps | −14.2 bps |
| G1 | +11.4 bps | 17 % | −9.6 bps | −13.7 bps |
| G6 | +10.4 bps | 36 % | −7.5 bps | −16.1 bps |
| G4 | +8.0 bps | 49 % | — | — |
| G3 | +7.3 bps | 28 % | — | — |
| G5 | +3.8 bps | 85 % | — | — |
| Existing B1 gate (reference) | +13.1 bps | 10 % | — | — |

Every gate raises the reversion rate of kept events; G2 keeps 15.4 %
against 7.4 % withheld.

**Choice: G2, Engle-Granger significant in both directions**
(`outputs/p6_coint/gate_choice.json`, SHA-256
`8d0060c46a0774715ace59e772af8a91ffc2359c2c14106f7537834b2aeebf9a`).

It is nearly a subset of the existing B1 gate, whose 2022–2023 result
reversed (Decision 44), so its confirmation is the informative test. No
2016–2023 gate outcome had been computed when this was recorded.

## 68. Pre-registered boosting round 2: return-aware improvements on the best model

Recorded 2026-10-19, before the Decision 67 model-feature result was read
and before any run below. The owner asked for a version built on the best
model so far that aims at long-run returns, with R0 kept as the comparison.

**Base.** The fixed Decision 45 XGBoost Model B (R0), traded with the E3
news exit (Decision 60). This was the best combination in Decision 64:
+12.0 bps per trade over 2010–2023.

**Why not re-tune.** Decision 66 showed that hyperparameter search mostly
fits noise here, and that tuning directly on the trading objective did worst
(V6). These variants keep the reversion label and R0's parameters, and change
how the model learns instead:

| Variant | Change |
|---|---|
| W1 seed bagging | R0 with 80 % row and column subsampling, averaged over 10 seeds (variance reduction) |
| W2 linear start | Boosting starts from the logistic Model B logit (C = 0.01), so the trees model what the linear model misses (the "linear start" used in the owner's earlier CatBoost project) |
| W3 return weighting | Each training event is weighted by the absolute frozen-policy net return of its trade (clipped at the 1st/99th percentiles, mean 1; unpriced events get the median). This is the return-attribution weighting of López de Prado (2018, ch. 4): events that matter more for P&L count more |
| W4 cointegration block | The 21 Decision 67 features added |
| W5 all four | W1–W4 together |

**Protocol.** Decision 45 walk-forward (2010–2021 decide, 2022–2023
reference) with the top-20 % rule on Y−1 scores.

**Primary measure.** Net return per Baseline 0 candidate under the E3 exit,
variant minus R0. It uses events priced under both the frozen and E3 exits,
with 2,000 calendar-month block bootstrap draws (seed 5557) and Holm across
the five variants.

**Pass rule.** Positive gain, Holm p < 0.05 and better in at least 8 of
12 years.

**Reported without a pass rule:**
- the same contrast under the frozen exit;
- mean net per selected trade;
- the annualised Sharpe of monthly per-candidate returns;
- the raw-probability Brier gain;
- 2022–2023.

Module: `structural_break.experiments.p6_boosting2`, output
`outputs/p6_boosting2/`.

## 69. Alternative cointegration result: informative about reversion, not adopted

Recorded 2026-10-19 (`outputs/p6_coint/models.json`,
`gate_confirmation.json`). Both Decision 67 tests ran as pre-registered.

**Test 1, model features, 2010–2021.**

| Model | Brier gain (×10⁻⁴), 95 % | Years better | Return gain per candidate, 95 % | Years better |
|---|---|---|---|---|
| B logistic | +0.73 [−1.56, +2.98], Holm p 0.46 | 8/12 | +1.89 bps [+0.33, +3.43], p 0.009 | 10/12 |
| B XGBoost | +0.80 [−1.47, +3.05], Holm p 0.46 | 8/12 | −0.55 bps [−1.77, +0.70] | 4/12 |
| A logistic | +0.97 [−1.30, +3.20] | 8/12 | +2.05 bps [+0.69, +3.39], p < 0.001 | 8/12 |
| A XGBoost | +1.16 [−0.59, +2.94] | 6/12 | +1.06 bps [−0.32, +2.37] | 9/12 |

**The primary Brier test fails.** Secondary returns:
- **Logistic models:** the block improves their returns (with an
  unadjusted p below 0.01).
- **XGBoost Model B:** no improvement for the best model.
- **2022–2023:** the Brier gains turn negative (−0.6 to −4.3 × 10⁻⁴) and
  return gains are between −0.95 and +0.82 bps.

**Test 2, gates.** The pre-chosen G2 gate (Engle-Granger significant in
both directions):
- **2016–2021:** +12.6 bps per candidate, 95 % [−6.4, +29.0], one-sided
  p = 0.085, positive in 5 of 6 years. **It fails.**
- **2022–2023:** +2.2 bps.

Johansen (G1) was positive in all three periods (+11.4, +12.3 and +4.2 bps)
and the existing Engle-Granger gate in 2016–2021 was +11.8 bps; neither was
pre-chosen.

Every gate roughly doubles the reversion rate of the events it keeps (G2:
19.6 % against 8.1 % in 2016–2021). The kept trades still earn little:
+5.3 bps in 2016–2021 and −19.0 bps in 2022–2023. Most of the gain comes
from withholding the losing majority.

**Conclusion.** Better cointegration diagnostics identify pairs that revert
more often, but they do not improve the best forecasting model or turn the
kept trades into reliable profits. A v3 rebuild of the events with a new
spread definition is not justified by this evidence. The features remain
available as W4 in Decision 68.

## 70. Boosting round 2 result: R0 with the news exit stays the best model

Recorded 2026-10-20 (`outputs/p6_boosting2/evaluation.json`, SHA-256
`88665657…`). Decision 68 ran as pre-registered.

**E3 exit, 2010–2021 pooled.**

| Variant | Mean net per selected trade | Per candidate | Sharpe (monthly, annualised) | Gain over R0, 95 % | Years better |
|---|---|---|---|---|---|
| R0 fixed XGBoost B | +9.3 bps | +2.16 bps | 0.31 | — | — |
| W1 seed bagging | +6.3 bps | +1.47 bps | 0.22 | −0.69 [−1.72, +0.28] | 5/12 |
| W2 linear start | +8.6 bps | +1.97 bps | 0.28 | −0.19 [−1.85, +1.45] | 6/12 |
| W3 return weighting | +5.2 bps | +1.25 bps | 0.16 | −0.91 [−2.87, +0.90] | 4/12 |
| W4 cointegration features | +6.2 bps | +1.44 bps | 0.21 | −0.72 [−1.97, +0.54] | 3/12 |
| W5 all four | +4.6 bps | +1.12 bps | 0.23 | −1.05 [−3.18, +0.98] | 4/12 |

**No variant passes** (every Holm p = 1.0).

- **Frozen exit:** the gains are negative as well.
- **2022–2023:** R0 averages +28.0 bps per trade under E3 (Sharpe 0.88).
  W4 is the only variant that is not worse there (+0.31 bps per candidate).
- **Calibration:** seed bagging and the cointegration block improve the raw
  Brier score slightly (+0.75 and +0.80 × 10⁻⁴). Return weighting distorts
  it heavily (−74 × 10⁻⁴), as expected for weighted training.

**Conclusion for workstream 1.** Across Decisions 65–70, sixteen pre-registered
model changes have been tested against the fixed Decision 45 XGBoost Model B:
- re-tuning in four libraries and two cross-validation schemes;
- an ensemble;
- a returns-oriented tuning objective;
- seed bagging, a linear start and return weighting;
- 21 cointegration features.

None improved its returns or its forecasts significantly. The best
candidate model for the final-test design remains R0 (the Decision 45
XGBoost Model B) with the E3 news exit. Choosing it is the owner's decision;
the 2024–2025 final test stays locked.

## 71. Pre-registered literature entry filters and volatility sizing

Recorded 2026-10-20, before any run below. The owner asked for entry
filters, and for ways to use volatility instead of tuning on returns.

**Population.** The best combination so far: the R0 walk-forward top-20 %
selections of Model B (Decision 45 XGBoost), traded with the E3 news exit.
Events must be priced under both the frozen and E3 exits. Baseline 0 (every
event, E3 exit) is reported alongside.

Every threshold is point-in-time: an event is compared with quantiles of
all events signalled in the previous calendar year. A skipped trade earns 0.

**Entry filters, from the literature (skip when):**

| Filter | Skip when | Source |
|---|---|---|
| F1 | The moving stock's volume shock is ≥ 2 SD and the other's < 1 SD (single-stock information) | Engelberg, Gao & Jagannathan; volume proxy |
| F2 | Both the absolute market and sector 1-day returns are below the prior-year median (no common news) | Engelberg et al.: common-news divergences converge |
| F3 | The moving stock rose (positive residual shocks reverse slowly) | Baldi-Lanfranchi, Collin-Dufresne & Daniel, "Asymmetric Reversals" |
| F4 | The day's number of divergence signals is below the prior-year median (little market-wide distraction) | Jacobs & Weber |
| F5 | The 1-day adverse z velocity is below the prior-year median (slow drift, more likely information) | — |
| F6 | The 20/60-day spread volatility ratio is ≥ 1.5 (volatility regime change) | — |
| F7 | VIX is below its prior-year 33rd percentile (liquidity provision pays less in calm markets) | Nagel (2012) |

**Volatility sizing** (weight per trade, clipped to [0.25, 4], divided by
the previous year's mean weight):

| Rule | Weight | Source |
|---|---|---|
| Z1v | Prior-year median spread volatility / the event's 20-day spread volatility (equal risk per trade) | — |
| Z2v | Prior-year median / the event's 20-day market realised volatility | Moreira & Muir (2017), volatility-managed portfolios |
| Z3v | The event's VIX / prior-year median (more exposure when liquidity provision pays) | Nagel |

Z2v and Z3v make opposite predictions for a reversal strategy, so they are
tested against each other.

**Protocol.**
- **Explore (2010–2015, model population):** choose the filter and the
  sizing rule with the highest t among those with positive gains. The two
  choices are written to `outputs/p6_entry_vol/choices.json` and recorded
  before 2016–2021 is scored.
- **Confirm (2016–2021):** each chosen rule passes if its gain per candidate
  is positive, its Holm-adjusted (over the two rules) one-sided p < 0.05
  from 2,000 calendar-month block draws (seed 5557), and it is positive in
  at least 4 of 6 years.
- **Reported:** 2022–2023, every rule's results, Baseline 0, and the Sharpe
  of monthly returns.

Module: `structural_break.experiments.p6_entry_vol`.

### 71a. Entry-filter and sizing choices, fixed before 2016–2021 was scored

Recorded 2026-10-20 (`outputs/p6_entry_vol/exploration.json`;
`choices.json` SHA-256
`9bc00632c2f85c8388fac4ae9fbd1e5037fdd21f07c7e50ba0eb69a1e2e210c6`).

**Model population, 2010–2015.** Only F1 (+0.7 bps), F6 (+1.2 bps, t 1.07),
Z2v (+1.5 bps, t 0.36) and Z3v (+1.6 bps, t 0.25) were positive. The other
filters lost 0.9–3.4 bps, and Z1v lost 5.9 bps.

**Baseline 0 is the opposite.** The same filters gained strongly there:
- F7 low VIX: +10.9 bps;
- F3 mover rose: +9.1 bps;
- F4 few signals: +7.5 bps;
- F5 slow drift: +7.1 bps;
- F1: +4.7 bps.

This suggests the XGBoost selection already captures these effects through
its VIX, volume and return features.

**Choices:** filter **F6** (skip when spread volatility is expanding) and
sizing **Z2v** (inverse market volatility). Both are weak in exploration.
No 2016–2023 outcome of this design had been computed.

## 72. Entry filter and volatility sizing result: both choices fail; VIX sizing is a post-hoc lead

Recorded 2026-10-20 (`outputs/p6_entry_vol/confirmation.json`). Decision 71
ran as pre-registered.

**Pre-chosen rules, model population (R0 top 20 % with the E3 exit),
2016–2021, 2,398 trades:**
- **F6 (skip expanding spread volatility):** −7.97 bps per candidate,
  95 % [−18.5, +0.3], positive in 2 of 6 years. **It fails.**
- **Z2v (inverse market volatility):** −8.23 bps, 95 % [−28.0, +11.1],
  positive in 2 of 6 years. **It fails.** In 2022–2023 it lost −36.0 bps.

**Reported, not pre-chosen.**

| Rule | Population | 2016–2021 gain per candidate | One-sided p | Years positive | Monthly Sharpe | 2022–2023 |
|---|---|---|---|---|---|---|
| Z3v VIX-proportional sizing | Model | +35.5 bps [−6.8, +80.4] | 0.055 | 3/6 | 0.25 → 0.40 | +38.7 bps (p 0.033), Sharpe 0.47 → 0.93 |
| F2 quiet common market | Baseline 0 | +7.5 bps [+2.0, +13.6] | 0.003 | 6/6 | −0.41 → +0.12 | — |
| F7 low VIX | Baseline 0 | +6.7 bps | 0.014 | 4/6 | — | — |
| F4 few same-day signals | Baseline 0 | +7.2 bps | 0.029 | — | — | — |
| F1 one-sided volume shock | Baseline 0 | +4.2 bps | 0.026 | — | — | — |
| F3 mover rose | Baseline 0 | +7.2 bps | 0.049 | — | — | +13.1 bps (p 0.023) |

- **Z3v in 2010–2015** was only +1.6 bps (t 0.25), so the lead comes from
  the later years.
- **The literature filters work on Baseline 0 but add nothing to the model's
  selections.** On Baseline 0 they skip divergences without common news,
  in calm markets, or where the mover rose. On the model selections they
  were negative or insignificant in 2016–2021, consistent with the XGBoost
  model already using VIX, volume and return features.

**Interpretation.**
- **The two volatility rules point in opposite directions, consistently
  with Nagel (2012).** Taking more exposure when VIX is high helped
  (liquidity provision earns more in turbulent markets). Moreira–Muir style
  de-risking hurt this reversal strategy, and so did equal risk per trade.
- **Z3v is post-hoc, and its per-candidate gain is mostly leverage.** It
  was not the pre-registered choice. Its mean weight on the model's trades
  was 1.43 in 2010–2015, 2.13 in 2016–2021 and 1.83 in 2022–2023, because
  the selections concentrate on high-VIX days and VIX rose. The fair measure
  is the Sharpe ratio:
  - 2010–2015: 0.45 → 0.43;
  - 2016–2021: 0.25 → 0.40;
  - 2022–2023: 0.47 → 0.93.

  Yearly gains swing widely (2020 +47.6 bps, 2021 −50.9 bps). The risk-adjusted
  improvement is therefore real in 2016–2023 but absent in 2010–2015.
- **Testing it further:** the only untouched data are the locked 2024–2025
  final test, so Z3v can only be tested there. It is a candidate for the
  final-test design, alongside R0 with the E3 exit, for the owner to decide
  on before the unlock.

## 73. Candidate final-test design fixed; pre-registered 2010–2023 portfolio evaluation

Recorded 2026-10-20, before any portfolio below was computed. The owner
framed the project's two goals and asked to fix the trading design (step 2)
and evaluate it as a portfolio (step 3).

**The two goals.**
- **Goal 1, forecasting mean reversion:** compare the methods by forecast
  quality. Decisions 44–70 settle this on development data: the fixed
  Decision 45 XGBoost Model B is the best forecaster found.
- **Goal 2, long-run portfolio returns:** use that forecaster with the best
  trading layer, judged as a portfolio.

**Step 2: the candidate design, fixed now.**
- **Primary candidate:** R0 (the fixed Decision 45 XGBoost Model B, retrained
  yearly) selects the top 20 % of divergences, using the 80th-percentile
  cutoff from the previous year's scores. Trades use the frozen Decision 36
  entry and costs with the **E3 adverse-tone news exit** (Decision 60, the
  only rule that passed confirmation).
- **Secondary candidate:** the same with **VIX-proportional sizing** (the
  Decision 72 post-hoc lead).
- **Not a candidate:** the entry filters. They added nothing on the model's
  selections (Decision 72), so none is included; R1 is reported as P4 only.

**Step 3: portfolio evaluation.**
- **Setup:** each design runs as one continuous portfolio from 2010 to the
  last development session (2023-12-29) under the frozen Decision 36
  portfolio policy:
  - start NAV 1;
  - 25 % of NAV per entry, gross capped at 100 % of NAV;
  - one position per pair, fixed shares;
  - frozen costs and borrow, no idle-cash yield.

  A 10 % target is a reported sensitivity.
- **Simulator:** `p6_portfolio.research_portfolio` copies the frozen
  `simulate_portfolio` with two additions: supplied trade results (for E3)
  and per-entry weights (VIX sizing). Before any result is used, the run
  checks that:
  - with frozen results and unit weights it reproduces the frozen portfolio
    NAV (on 2016–2017 model trades and on the synthetic fixture);
  - every frozen and E3 trade return equals the stored Decision 59–62
    simulation.

**Designs:**

| Design | Population | Exit | Sizing / filter |
|---|---|---|---|
| P0 | Baseline 0 (every divergence) | Frozen | — (the original strategy) |
| P1 | R0 selections | Frozen | — |
| **P2** | R0 selections | E3 | — (**primary candidate**) |
| **P3** | R0 selections | E3 | VIX-proportional sizing, normalised by the previous year's mean weight (**secondary candidate**) |
| P4 | R0 selections | E3 | Skip R1 events |

**Reported for 2010–2023 and for 2010–2015, 2016–2021 and 2022–2023:**
- total return, CAGR and annualised volatility;
- Sharpe ratio (daily, zero risk-free rate);
- maximum drawdown and Calmar ratio;
- mean gross exposure and open positions;
- trade counts by status;
- yearly returns.

There is **no pass rule**: every year here has been used before, so this
describes the candidates rather than testing them. The test of the fixed
design is the locked 2024–2025 final test, which needs the owner's
explicit unlock.

## 74. Portfolio evaluation result: the candidate designs are close to break-even

Recorded 2026-10-20 (`outputs/p6_portfolio/portfolios.json`, SHA-256
`2f9e92ba…`). Decision 73 ran as pre-registered.

**Checks passed.** Every frozen and E3 trade return equals the stored
simulation exactly (maximum difference 0). The research portfolio reproduces
the frozen portfolio NAV on the 2016–2017 model trades (396 proposals,
524 sessions, maximum difference 4 × 10⁻¹⁵).

**Results, frozen policy (25 % of NAV per entry), 2010-01-04 to the last
known close:**

| Design | CAGR | Volatility | Sharpe | Max drawdown | Final known NAV | Trades | 2010–15 / 2016–21 / 2022–23 Sharpe |
|---|---|---|---|---|---|---|---|
| P0 Baseline 0, frozen exit | −3.56 % | 4.1 % | −0.86 | −20.0 % | 0.835 (NAV unknown after 2014-12-31) | 4,941 | −0.86 / — / — |
| P1 R0, frozen exit | −0.90 % | 5.3 % | −0.14 | −28.4 % | 0.882 | 3,885 | −0.73 / +0.19 / +0.61 |
| **P2 R0 + E3 (primary)** | −0.45 % | 5.4 % | −0.06 | −18.7 % | 0.939 | 4,006 | −0.32 / +0.12 / +0.19 |
| **P3 P2 + VIX sizing (secondary)** | −0.69 % | 5.0 % | −0.11 | −20.9 % | 0.908 | 4,037 | −0.39 / −0.12 / +0.90 |
| P4 P2 skipping R1 events | **+0.90 %** | 5.7 % | **+0.19** | **−9.8 %** | **1.133** | 3,467 | +0.08 / +0.24 / +0.33 |

**10 % of NAV per entry (sensitivity), Sharpe:**
- P1: +0.09;
- P2: +0.07, with a −11.1 % maximum drawdown;
- P3: −0.02;
- P4: +0.31 (CAGR +1.24 %, maximum drawdown −9.2 %, final NAV 1.186).

The model portfolios lose NAV knowledge after 2023-12-08, when a held quote
is missing under the frozen rule. P0's NAV became unknown on 2014-12-31,
after which its new entries were blocked.

**Reading.**
1. **Selecting with the model is a large improvement on trading every
   divergence** (CAGR −3.6 % → about 0 %).
2. **The candidate designs are close to break-even after costs.**
   - P2's +9.3 bps per trade, at about 13 open positions and 0.8 gross,
     amounts to roughly +0.2 % a year. It is also negative in 2010–2015.
   - Per-trade edges of this size do not make a meaningful portfolio
     return; leverage would scale risk and return together.
3. **VIX sizing does not help at the portfolio level.** Its Sharpe is lower
   than P2's in 2010–2021 and higher only in 2022–2023. The Decision 72 lead
   does not survive capacity limits and compounding.
4. **The R1 entry filter is the best design here.** It is positive in all
   three periods and halves the drawdown, but it is not the pre-registered
   candidate, and these years have been used before.

**Implication for Goal 2.** The final-test candidate stays as fixed in
Decision 73 unless the owner changes it before the unlock. The main lever
for returns is per-trade edge after costs, not sizing.

## 75. Pre-registered quant research programme: forecasting and portfolio (workstream 1)

Recorded 2026-10-20 on branch `p6/quant-research`, before any result below.
The owner is away for two days and asked for autonomous research as a
quantitative trader. The aims are the best reversion forecast (ROC-AUC, log
loss, Brier) and the best long-run portfolio. New event definitions are
allowed, plausible non-significant improvements are acceptable, and
overfitting must be controlled. The 2024–2025 final test stays locked, and
nothing is merged without the owner.

**Overfitting control.** Every year 2010–2023 has been looked at in earlier
decisions, but none of the new features or designs here has been evaluated
on any year. The walk-forward test years are therefore split:
- **2010–2017 (selection):** every choice in this programme is made here.
- **2018–2023 (holdout):** opened once per stage, after the stage's choice
  is recorded. The harness only reports 2018–2023 when explicitly asked to
  (`--holdout`).

**Stage A: forecasting.**
- **New point-in-time feature blocks** (`p6_quant_features`):

  | Block | Contents | Source |
  |---|---|---|
  | peer | Each leg's mean z against its other peers, aligned with the divergence; the share of its other pairs diverging the same way; market-wide divergence breadth and fresh crossings | Chen, Chen, Chen & Li 2019; Avellaneda & Lee 2010 |
  | state | Zero crossings over 252 days, days since the last crossing, AR(1) rho, error-correction speed, relationship age | Daily pair state |
  | track | Each pair's and each stock's reversion rate on earlier events resolved before the signal date (shrunk with weight 10 towards the running base rate), the pair's stop rate, last outcome and days since it | — |
  | earnings | Days since each leg's last Item 2.02 8-K, estimated days to its next (median of its last four gaps), and whether it falls inside the holding window | — |
  | momentum | Each leg's 20- and 120-session return aligned with the divergence, and distance to its 252-session high | — |

- **Specs:** Model B alone and with each block; Model B with all blocks;
  all blocks plus the Decision 67 cointegration block; and Model A. All use
  the fixed Decision 45 XGBoost, which re-tuning did not beat (Decision 66).
- **Training schemes:**
  - `d45` (labels ending before Y−1);
  - `recent` (labels ending before Y; previous-year cutoff scores
    out-of-fold from a purged 5-fold or out-of-sample).

  Probabilities are Platt-calibrated on out-of-fold training scores from the
  last three years.
- **Metrics on 2010–2017:** ROC-AUC, PR-AUC, log loss, Brier; top-20 % and
  top-10 % selections under the frozen and E3 exits (per trade, per
  candidate, monthly Sharpe).
- **Choice rule:**
  1. Pick the scheme with the lower 2010–2017 log loss for Model B.
  2. Under that scheme, add each block whose own addition lowers Model B's
     2010–2017 log loss.
  3. If the combined set does not beat the best single addition, keep the
     best single addition.

  The chosen spec and Model B are then compared once on 2018–2023.

**Stage B: events and trading.** Once Stage A's choice is confirmed or
rejected, new event definitions and trading rules are explored with the same
selection/holdout split. Examples: entry on confirmed reversal, persistence-
dependent entry thresholds, selectivity, a shorter time stop with the news
exit, probability-scaled sizing. Each stage is recorded before its holdout
is opened.

**Stage C: portfolio.** The best Stage A/B design is run through the
verified research portfolio (Decision 73) for 2010–2023 and compared with
the Decision 73 candidates.

Modules: `p6_quant_features`, `p6_quant`; outputs in `outputs/p6_quant/`.

## 76. Pre-registered Stage B: exit-rule grid and selectivity

Recorded 2026-10-20, before any exit-grid result was read (the grid was
still being computed).

**Exit grid** (`p6_quant_trading`): each 2010–2023 Baseline 0 event is
entered by the frozen policy and exited under 36 variants:
- take profit at |z| ≤ 0.5 (frozen), 0.75 or 1.0;
- adverse stop at 3 (frozen), 3.5 or none;
- time stop at 20 (frozen) or 10 sessions;
- E3 news exit off or on.

The exit loop is the verified `simulate_long` loop with these four settings
as arguments. The build stops unless every event reproduces both the frozen
simulator and the stored E3 result.

**Rationale.**
- Pairs-trading profits decay within days (Engelberg, Gao & Jagannathan;
  Jacobs & Weber), so earlier profit-taking and shorter holds may help.
- Fixed stops often reduce pairs-trading profits.

**Choice rule.**
- **Population:** the R0 top-20 % walk-forward selections (Decision 45
  XGBoost Model B), 2010–2017, events priced under every variant.
- **Pick:** the variant with the highest annualised monthly Sharpe of
  per-candidate net returns (withheld events earn 0). Its per-candidate
  mean must be at least that of E3 (take profit 0.5, stop 3, time 20, news
  on); otherwise E3 is kept.
- **Also reported:** the chosen variant's neighbours (each setting changed
  by one step), as a stability check.
- **Holdout:** 2018–2023 is opened once to compare the chosen variant with
  E3 and the frozen exit.

**Selectivity.** Top 20 % versus top 10 % of the previous year's scores,
chosen by 2010–2017 monthly Sharpe under the chosen exit and the Stage A
model.

### 76a. Exit choice, fixed before 2018–2023 was opened

Recorded 2026-10-20 (`outputs/p6_quant/exit_exploration.csv`,
`exit_choice.json`). The build passed its checks on all 22,450 events.

On the R0 top-20 % selections, 2010–2017 (1,834 trades), the 36 variants
order consistently:
- the news exit helps in every comparison;
- taking profit at |z| ≤ 1.0 beats 0.75, which beats 0.5;
- no adverse stop beats 3.5, which beats 3;
- a 20-session time stop beats 10.

| Variant | Monthly Sharpe | Per trade | Per candidate |
|---|---|---|---|
| **Chosen: take profit 1.0, no stop, 20 sessions, news exit** | **0.50** | **+13.1 bps** | +2.45 bps |
| Neighbour: stop 3.5 | 0.46 | — | — |
| Neighbour: take profit 0.75 | 0.44 | — | — |
| Neighbour: stop 3 | 0.42 | — | — |
| E3 (Decision 60) | 0.26 | +6.0 bps | +1.13 bps |
| Frozen exit | −0.04 | −1.9 bps | — |

The neighbours are close to the chosen variant, so it is not an isolated
peak. No 2018–2023 exit result had been read.

## 77. Exit holdout result: take profit at |z| 1.0, no stop, with the news exit

Recorded 2026-10-20 (`outputs/p6_quant/exit_holdout.csv`). R0 top-20 %
selections, events priced under every variant.

| Period | Exit | Per trade | Per candidate | Monthly Sharpe | Median trade | Hit rate |
|---|---|---|---|---|---|---|
| 2010–2017 (selection) | Chosen | +13.1 bps | +2.45 bps | 0.50 | +14 bps | 52.7 % |
| 2010–2017 (selection) | E3 | +6.0 bps | +1.13 bps | 0.26 | −16 bps | 47.4 % |
| **2018–2023 (holdout)** | **Chosen** | **+45.9 bps** | **+12.5 bps** | **0.67** | **+50 bps** | **55.8 %** |
| 2018–2023 (holdout) | E3 | +16.1 bps | +4.4 bps | 0.53 | −28 bps | 47.4 % |
| 2018–2023 (holdout) | Frozen | +15.3 bps | +4.2 bps | 0.47 | — | — |

**Consistency.** The chosen exit beats E3 in 2018–2021 (Sharpe 0.56 against
0.39) and in 2022–2023 (1.30 against 0.90).

**Gain per trade over E3** (paired month-block bootstrap):

| Period | Gain | 95 % | One-sided p |
|---|---|---|---|
| 2010–2017 | +7.0 bps | [−4.2, +18.8] | 0.12 |
| 2018–2023 | +29.8 bps | [−13.8, +77.8] | 0.14 |

**Not outlier-driven.** Means trimmed by 1 % on each side are about the
same (+14.1 and +49.3 bps).

**Reading.** The improvement is consistent in direction, economically
plausible, and confirmed on the holdout, but not statistically significant:
trade returns are noisy, with a per-trade standard deviation of 3–5 %.
- **Why it works:** taking profit at |z| 1.0 locks in partial reversion
  early. Removing the stop avoids selling at the worst point, which the
  literature reports as the main cost of stops.
- **The cost is tail risk:** the worst holdout trade lost about 40 % of
  gross exposure, against about 9 % at the 1st percentile under E3.

Exit adopted for the programme (per Decision 75, plausible improvements are
acceptable). Its drawdown must be checked at the portfolio stage, where a
disaster stop is a risk overlay to evaluate.

### 75a. Stage A choice, fixed before 2018–2023 was opened

Recorded 2026-10-20 (`outputs/p6_quant/summary_select.json`, 2010–2017 test
years only).

**Step 1, scheme: `recent` wins clearly.**

| Spec | Scheme | Log loss | ROC-AUC |
|---|---|---|---|
| Model B | `recent` | 0.20600 | 0.700 |
| Model B | `d45` | 0.21105 | 0.692 |
| B + all blocks | `recent` | 0.20296 | 0.722 |
| B + all blocks | `d45` | 0.20701 | 0.716 |

**Step 2, single blocks** added to Model B under `recent` (Model B alone:
log loss 0.20600, AUC 0.700, PR-AUC 0.115):

| Block | Log loss | ROC-AUC | Lowers log loss? |
|---|---|---|---|
| earnings | 0.20463 | 0.711 | yes |
| peer | 0.20529 | 0.702 | yes |
| momentum | 0.20573 | 0.703 | yes |
| state | 0.20598 | 0.700 | yes |
| track | 0.20624 | 0.709 | no (AUC up, log loss worse) |

**Step 3, combined:** B + peer + state + earnings + momentum ("B+rule") has
log loss 0.20322, AUC 0.716, PR-AUC 0.122. That beats the best single block,
so **B+rule under `recent` is the chosen spec.**

Not chosen by the rule, reported only:
- B + all blocks: log loss 0.20296, AUC 0.722;
- B + all + cointegration: log loss 0.20253, AUC 0.725, PR-AUC 0.129;
- Model A: log loss 0.20850, AUC 0.684.

**Trading caution.** Better forecasts did not mean better top-20 % trades
in 2010–2017. Under E3, Model B's selections earned +8.9 bps per trade,
against +0.8 bps for B+rule. Selection for trading is revisited in Stage C
with the new exit.

No 2018–2023 Stage A result had been read.

## 78. Stage A holdout result: the new features significantly improve the reversion forecast

Recorded 2026-10-20 (`outputs/p6_quant/summary_holdout.json`). Compared
with the original Model B (Decision 45 XGBoost, `d45` scheme) on the same
labelled test events.

**Forecast metrics:**

| Spec | Period | ROC-AUC | PR-AUC | Log loss | Brier |
|---|---|---|---|---|---|
| Original Model B (`d45`) | 2010–2017 | 0.692 | 0.107 | 0.2111 | 0.0529 |
| **B+rule (`recent`)** | 2010–2017 | **0.716** | **0.122** | **0.2032** | **0.0517** |
| Original Model B (`d45`) | **2018–2023 holdout** | 0.718 | 0.207 | 0.2832 | 0.0790 |
| **B+rule (`recent`)** | **2018–2023 holdout** | **0.730** | **0.214** | **0.2799** | **0.0785** |
| B + all blocks (`recent`) | 2018–2023 holdout | 0.733 | 0.219 | 0.2783 | 0.0781 |
| Model B (`recent`) | 2018–2023 holdout | 0.717 | 0.206 | 0.2829 | 0.0790 |

**Paired gains over the original Model B** (log loss: month-block
bootstrap, 2,000 draws; AUC: 500 month-block draws):

| Spec | Period | Log-loss gain (×10⁻⁴), 95 %, p | AUC gain, 95 %, p |
|---|---|---|---|
| **B+rule** | 2018–2023 | **+33.6 [+5.3, +62.3], p 0.007** | **+0.012 [+0.003, +0.021], p 0.002** |
| B + all | 2018–2023 | +49.9 [+17.6, +81.5], p 0.001 | +0.015 [+0.005, +0.026], p 0.002 |
| Model B (`recent`) | 2018–2023 | +3.4 [−14.1, +21.6], p 0.36 | −0.001 |
| B+rule | 2010–2017 | +78.4 [+46.6, +109.0] | +0.025 |

**Reading.** This is the first significant out-of-sample improvement in the
reversion forecast in the project (Goal 1).
- **The gain comes from the new information:** peer displacement, the
  earnings calendar, leg momentum and relationship state. The training
  scheme alone does not help in 2018–2023.
- **The pre-registered spec is B+rule;** B + all blocks, not chosen by the
  rule, does slightly better.
- **Holdout trading, top 20 % under E3:** B+rule earns +15.0 bps per trade
  (Sharpe 0.55), against +16.1 bps (0.52) for the original Model B. Better
  forecasts do not by themselves change the trading result.

**Adopted** as the programme's forecasting model for Goal 1. The final test
stays locked.

### 76b. Selectivity choice: top 20 %

Recorded 2026-10-20. On 2010–2017, under the chosen exit, top 20 % beats
top 10 % for every model.

| Model | Top 20 %: Sharpe, per trade | Top 10 %: Sharpe, per trade |
|---|---|---|
| Original Model B | 0.50, +13.1 bps | 0.32, +9.6 bps |
| B+rule | 0.36, +7.0 bps | 0.07, −4.1 bps |
| B + all | 0.38 | 0.00 |

Top 20 % is kept. The most confident reversion forecasts are not the most
profitable trades, and the original Model B's selections trade better than
B+rule's in 2010–2017.

## 79. Pre-registered Stage C ranking: reversion probability against predicted trade return

Recorded 2026-10-20, before any result below. Decision 78 showed that the
best reversion forecaster is not the best trade selector. For Goal 2 the
ranking should target the trade's net return under the adopted exit
(take profit at |z| 1.0, no stop, 20 sessions, E3 news exit), not the
reversion label.

**Rankings compared** (top 20 %, previous-year cutoff, `recent` scheme
unless noted):

| Ranking | Model | Target |
|---|---|---|
| R-a | Original Model B (`d45`) | Reversion probability (reference, the Decision 73 candidate) |
| R-b | B+rule | Reversion probability (Decision 78) |
| R-c | XGBoost regressor, Decision 45 parameters, B+rule features | Realised net return under the adopted exit |

For R-c, the target is winsorised at the training window's 1st and 99th
percentiles, and training uses only trades whose 20-session window ended
before 1 January of the test year. The previous-year cutoff comes from
purged out-of-fold predictions.

**Choice rule.** Pick the ranking with the highest 2010–2017 monthly Sharpe
of per-candidate net returns under the adopted exit. Then open 2018–2023
once.

### 79a. Ranking choice, fixed before 2018–2023 was opened

Recorded 2026-10-20. The exit grid was extended to 2006–2023 so the return
model has a training history; the 2010–2023 rows equal the earlier grid
exactly.

On 2010–2017, top 20 % under the adopted exit:

| Ranking | Trades | Per trade | Median trade | Per candidate | Monthly Sharpe |
|---|---|---|---|---|---|
| **R-a, original Model B (`d45`)** | 1,834 | **+13.1 bps** | +14.5 bps | +2.45 bps | **0.50** |
| R-b, B+rule probability | 1,574 | +7.0 bps | — | — | 0.36 |
| R-c, return regression | 2,252 | −11.8 bps | — | — | −0.51 |

**Choice: R-a.** Direct return prediction is again noise (as in Decision
44), and the better reversion forecaster does not select better trades.

### 79b. Ranking holdout (2018–2023)

| Ranking | Trades | Per trade | Monthly Sharpe |
|---|---|---|---|
| **R-a (chosen)** | 2,698 | **+45.9 bps** | **0.66** |
| R-b | 2,873 | +39.7 bps | 0.59 |
| R-c | 1,750 | +51.3 bps | 0.87 |

R-c swings from −0.51 in 2010–2017 to +0.87 here, the instability that made
it untrustworthy. R-a stays the trading ranking.

## 80. Pre-registered Stage C portfolio evaluation of the programme design

Recorded 2026-10-20, before any portfolio below was computed. The verified
research portfolio (Decision 73: frozen portfolio policy, 25 % of NAV per
entry, 10 % sensitivity, gross capped at 100 %) runs 2010–2023 on:

| Design | Ranking | Exit | Role |
|---|---|---|---|
| D73 | R-a, top 20 % | E3 | Reference: the Decision 73 primary candidate |
| **D80** | R-a, top 20 % | Take profit \|z\| 1.0, no stop, 20 sessions, news exit (Decision 77) | **Programme design** |
| D80-risk | Same as D80 | Same plus a disaster stop at \|z\| ≥ 5 | Risk overlay against the no-stop tail found in Decision 77 |
| D80-B+rule | B+rule (the Goal 1 forecaster), top 20 % | As D80 | Reported |

**Reported for 2010–2023 and each sub-period:** CAGR, volatility, Sharpe,
maximum drawdown and Calmar. The holdout split stays visible: 2010–2017
picked every component, 2018–2023 confirmed them.

There is no pass rule; the 2024–2025 final test remains the test. D80-risk
is adopted over D80 if its 2010–2017 Sharpe is at least D80's or its
2010–2017 maximum drawdown is at least one third smaller.

## 81. Pre-registered Stage A2: a second forecasting feature block

Recorded 2026-10-20, before any Stage A2 result.

**Block `extra`** (`p6_quant_features.extra_features`):
- the share of the pair's sector diverging that day (sector rotation versus
  a stock-specific move);
- each leg's 5-session change in its mean displacement across all its pairs,
  aligned with the divergence (a sudden jump versus a gradual build-up);
- each leg's 60-session return volatility and their ratio.

**Specs** (`recent` scheme): B+rule+extra and B+all+extra.

**Choice rule.** Extra is adopted into the Goal 1 forecaster if
B+rule+extra has a lower 2010–2017 log loss than B+rule. 2018–2023 is then
opened once for B+rule, B+rule+extra and B+all+extra against the original
Model B.

### 80a. Stage C portfolio result: the adopted exit makes the portfolio positive; disaster stop adopted

Recorded 2026-10-20 (`outputs/p6_quant/portfolio/summary.json`).

**Results, 25 % of NAV per entry:**

| Design | 2010–2023 CAGR | Sharpe | Max drawdown | 2010–2017: Sharpe, CAGR, drawdown | 2018–2023: Sharpe, CAGR, drawdown |
|---|---|---|---|---|---|
| D73 (R-a + E3) | −0.45 % | −0.06 | −18.7 % | −0.33, −1.8 %, −18.2 % | +0.27, +1.4 %, −9.8 % |
| D80 (R-a + adopted exit) | +1.27 % | 0.25 | −15.5 % | −0.04, −0.3 %, −15.5 % | +0.56, +3.5 %, −14.0 % |
| **D80-risk (+ stop at \|z\| 5)** | **+1.58 %** | **0.30** | **−14.7 %** | −0.02, −0.2 %, −14.7 % | **+0.66, +4.1 %, −12.8 %** |
| D80-B+rule | +0.64 % | 0.15 | — | +0.12, +0.5 % | NAV unknown after 2018-06-07 (missing held quote) |

The 10 % sensitivity ranks the designs the same way (D80-risk Sharpe 0.25,
maximum drawdown −10.1 %).

**Disaster stop: adopted.** D80-risk's 2010–2017 Sharpe (−0.02) is at
least D80's (−0.04), meeting the Decision 80 rule.

**Reading.**
- The adopted exit improves on the Decision 73 candidate in every period
  (Sharpe −0.06 → 0.30).
- The edge is concentrated in 2018–2023, and the 2010–2017 portfolio is
  flat.
- Unlevered returns are small (CAGR 1.6 %) because the frozen policy holds
  at most 100 % gross. At this Sharpe, leverage scales return and drawdown
  together.

**The programme design for Goal 2:** R-a (the Decision 45 XGBoost Model B)
top 20 %, frozen entry, with these exits:
- take profit at |z| ≤ 1.0;
- the E3 news exit;
- a disaster stop at |z| ≥ 5;
- a 20-session time stop.

## 82. Pre-registered Stage C2: selection refinements on the programme design

Recorded 2026-10-20, before any result below. Each candidate keeps the
D80-risk exit (take profit at |z| 1.0, E3 news exit, disaster stop at
|z| 5, 20 sessions) and changes which events are traded:

| Candidate | Trades |
|---|---|
| C2-a | The R-a top 20 %, skipping R1 events (the moving company filed earnings in the last 3 sessions, or its recent-news negative tone is ≥ 0.2). This was the best design in Decision 74. |
| C2-b | Events in both the R-a and the B+rule top 20 % (higher conviction) |
| C2-c | Events in either top 20 % (more trades, more diversification) |

**Choice rule.** Pick the candidate with the highest 2010–2017 portfolio
Sharpe at 25 % of NAV per entry. It is adopted only if that Sharpe exceeds
D80-risk's (−0.02). 2018–2023 and the full period are reported.

### 82a. Stage C2 result: the R1 entry filter is adopted

Recorded 2026-10-20 (`outputs/p6_quant/portfolio_c2/`). 25 % of NAV per
entry.

| Candidate | Trades | 2010–2017 Sharpe, CAGR, drawdown | 2018–2023 Sharpe, CAGR, drawdown | 2010–2023 CAGR, Sharpe, drawdown |
|---|---|---|---|---|
| D80-risk (reference) | — | −0.02, −0.2 %, −14.7 % | +0.66, +4.1 %, −12.8 % | +1.6 %, 0.30, −14.7 % |
| **C2-a, R1 filter** | 4,430 | **+0.25, +1.2 %, −13.8 %** | +0.60, +3.7 %, −10.8 % | **+2.25 %, 0.41, −13.8 %** |
| C2-b, both models | 3,931 | −0.11 | +0.50 | — |
| C2-c, either model | 6,162 | −0.02 | NAV unknown after 2018-06-07 | — |

- **C2-a has the highest 2010–2017 Sharpe**, above D80-risk's, so it is
  adopted.
- **It is positive in every sub-period:** Sharpe +0.32 (2010–2015),
  +0.55 (2016–2021) and +0.24 (2022–2023).
- **At 10 % of NAV per entry:** Sharpe 0.48, CAGR +2.0 %, maximum
  drawdown −11.3 %.
- **Holdout:** it is slightly below D80-risk in 2018–2023 (0.60 against
  0.66), with a smaller drawdown.

**Programme design (Goal 2):**
- **Selection:** Decision 45 XGBoost Model B, retrained yearly; top 20 % of
  divergences by the previous year's cutoff.
- **Entry filter:** skip events where the moving company filed earnings in
  the last 3 sessions or has negative recent-news tone.
- **Entry and costs:** frozen.
- **Exits:** take profit at |z| ≤ 1.0, E3 adverse-tone news exit, disaster
  stop at |z| ≥ 5, 20-session time stop.

## 83. Pre-registered Stage B2: extending the take-profit grid past its edge

Recorded 2026-10-20, before any result below. The adopted take profit
(|z| ≤ 1.0) was the edge of the Decision 76 grid, so a wider level may be
better.

On the current design's events (the R-a top 20 % without R1 events), the
exit loop is re-run from the cached requests with the E3 news exit and a
20-session time stop:
- take profit at |z| ≤ 1.0, 1.25 or 1.5;
- disaster stop at |z| ≥ 5 or none.

**Choice rule.** Pick the variant with the highest 2010–2017 monthly Sharpe
of per-candidate returns. It replaces the current exit (1.0, stop 5) only
if its Sharpe is higher. 2018–2023 is opened once afterwards.

### 83a. Take-profit choice, fixed before 2018–2023 was opened

Recorded 2026-10-20 (`outputs/p6_quant/tp_extend.parquet`). On 2010–2017,
current design's events:

| Take profit | Disaster stop | Monthly Sharpe | Per trade |
|---|---|---|---|
| 1.0 (current) | 5 | 0.71 | +19.2 bps |
| 1.0 | none | 0.74 | — |
| 1.25 | 5 | 0.75 | — |
| 1.25 | none | 0.78 | — |
| 1.5 | 5 | 0.86 | — |
| **1.5** | **none** | **0.89** | **+21.3 bps** |

**Choice: take profit at |z| ≤ 1.5 with no disaster stop.**
- **Edge of the range:** the optimum is again at the boundary. This is not
  extended further, because each extension reuses the same selection years.
- **Risk overlay:** the disaster-stop version (1.5, stop 5) is also carried
  into the portfolio as a risk overlay.

### 83b. Take-profit extension does not hold out; the current exit is kept

Recorded 2026-10-20. On 2018–2023 the ordering reverses:

| Take profit | Stop | 2018–2023 Sharpe | Per trade | 2018–2021 Sharpe | 2022–2023 Sharpe |
|---|---|---|---|---|---|
| **1.0** | **5** | **0.78** | +38.8 bps | 0.67 | 1.17 |
| 1.0 | none | 0.69 | +48.8 bps | — | — |
| 1.25 | 5 | 0.67 | — | — | — |
| 1.5 | 5 | 0.61 | — | — | — |
| 1.5 | none | 0.55 | +33.0 bps | 0.42 | 1.12 |

**Portfolios over 2010–2023:**

| Design | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| Take profit 1.5, no stop | +2.32 % | 0.42 | −13.7 % |
| Take profit 1.5, stop 5 | +2.25 % | 0.41 | −12.9 % |
| C2-a (take profit 1.0, stop 5) | +2.25 % | 0.41 | −13.8 % |

The Decision 83a choice was an edge-of-grid artefact of 2010–2017. The
holdout prefers the current exit, and the portfolios are indistinguishable.
**The Decision 82a programme design is kept unchanged** (take profit
|z| 1.0, disaster stop 5). This is the selection/holdout discipline working
as intended.

### 81a. Stage A2 choice: the extra block is adopted

Recorded 2026-10-20, 2010–2017 only.

| Spec | Log loss | ROC-AUC | PR-AUC |
|---|---|---|---|
| B+rule | 0.20322 | 0.716 | 0.122 |
| **B+rule+extra** | **0.20261** | **0.721** | 0.122 |
| B+all+extra | 0.20265 | 0.726 | 0.124 |

B+rule+extra lowers log loss, so the extra block is adopted into the Goal 1
forecaster. No 2018–2023 Stage A2 result had been read.

### 81b. Stage A2 does not hold out; B+rule stays the Goal 1 forecaster

Recorded 2026-10-20. 2018–2023, against the original Model B
(AUC 0.718):

| Spec | ROC-AUC | PR-AUC | Log loss | Brier | Log-loss gain (×10⁻⁴), p | AUC gain, p |
|---|---|---|---|---|---|---|
| **B+rule** | **0.730** | 0.214 | **0.2799** | 0.0785 | +33.6, p 0.007 | +0.012, p 0.002 |
| B+rule+extra | 0.727 | 0.210 | 0.2805 | 0.0787 | +26.9, p 0.043 | +0.010, p 0.042 |
| B+all+extra | 0.732 | 0.215 | 0.2786 | 0.0782 | — | — |
| B+all | 0.733 | 0.219 | 0.2783 | 0.0781 | +49.9, p 0.001 | +0.015, p 0.002 |

The extra block helped in 2010–2017 but is slightly worse than B+rule out
of sample, so it is **not adopted**. **B+rule (Decision 78) remains the
pre-registered Goal 1 forecaster.** B+all, which adds the track-record
block, is the best spec on the holdout but was never chosen by a rule. It
is reported as the strongest observed forecaster.

## 84. Proposed final-test design from the quant programme (owner to decide)

Recorded 2026-10-20. This summarises Decisions 75–83 into a proposal. It is
not adopted: changing the final-test design requires the owner's decision
before the unlock.

**Goal 1, forecasting.**
- **Proposal:** report B+rule (the original Model B features plus the peer,
  state, earnings and momentum blocks, `recent` training scheme) against
  the original Model B on the final-test events.
- **Development evidence:** on the 2018–2023 holdout it improves ROC-AUC
  from 0.718 to 0.730 and log loss from 0.2832 to 0.2799 (both p < 0.01).

**Goal 2, portfolio.** The proposal replaces the Decision 73 primary
candidate with the programme design:

| Component | Setting |
|---|---|
| Selection | Original Model B top 20 % |
| Entry filter | R1 |
| Entry and costs | Frozen |
| Exits | Take profit at \|z\| ≤ 1.0, E3 news exit, disaster stop at \|z\| ≥ 5, 20-session time stop |
| Portfolio policy | Frozen (25 % of NAV per entry) |

On 2010–2023 this design has CAGR +2.25 %, Sharpe 0.41 and maximum drawdown
−13.8 %, against −0.45 %, −0.06 and −18.7 % for the Decision 73 candidate.

**The exit and filter changes alter the frozen Decision 36 execution
policy**, so adopting them needs a new freeze manifest. The 2024–2025 final
test stays locked until the owner decides and unlocks it. Full write-up:
`docs/P6_QUANT_RESEARCH.md`.

**Cost sensitivity of the proposed design** (2010–2023, 25 % per entry;
reported, not used for any choice):

| Scenario | CAGR | Sharpe |
|---|---|---|
| Costs 2.5 bps per side | +3.0 % | 0.54 |
| Frozen | +2.25 % | 0.41 |
| Costs 10 bps per side | +0.8 % | 0.16 |
| Borrow 2 % | +1.8 % | 0.34 |

The edge is thin relative to trading costs.

## 85. Pre-registered Stage D: structural Ornstein–Uhlenbeck features and ranking

Recorded 2026-10-20, before any model or trading result below. The owner
asked the programme to continue.

**Holdout reuse.** The 2018–2023 holdout has now been opened in seven
stages (Decisions 77, 78, 79b, 80a, 81b, 82a, 83b). Each further opening
weakens it, so Stage D results there are reported with that caveat.

**Features** (`p6_quant_ou`):
- **Model:** each event's z is simulated as an AR(1)/OU process. Persistence
  rho is the formation-window AR(1) coefficient. sigma is the realised
  standard deviation of daily z changes over the previous 60 sessions.
- **Simulation:** 2,000 paths with common random numbers (seed 5557),
  20 steps.
- **Six features** (`ou_` block):
  - the probability of the research label (|z| ≤ 0.5 before z ≥ 3);
  - the probability of the adopted take profit (|z| ≤ 1.0 before z ≥ 5);
  - the expected z captured under the adopted exit;
  - the implied expected net return, expected z captured × spread std /
    (1 + |beta|) − 10 bps;
  - rho and sigma.
- **Feature-construction check (2010–2017 only):** the untrained OU label
  probability alone has ROC-AUC 0.718, but it is over-optimistic (mean
  0.21 against a 0.056 base rate).

**Goal 1.**
- **Specs** (`recent` scheme): B+rule+ou, B+all+ou, and "OU alone" (a
  logistic calibration of logit(ou_p_label), fitted on each training window,
  as a pure econometric forecaster).
- **Rule:** the `ou` block is adopted if B+rule+ou has a lower 2010–2017
  log loss than B+rule. 2018–2023 is opened once.

**Goal 2.** Candidate selections, all under the D80-risk/C2-a exit and
excluding R1 events:

| Candidate | Selection |
|---|---|
| G-a | The current design (R-a top 20 %) |
| G-b | The top 20 % by OU expected net return (previous-year cutoff; no machine learning) |
| G-c | The current design, keeping only events whose OU take-profit probability is at least the previous year's median |

**Rule:** pick the candidate with the highest 2010–2017 monthly Sharpe of
per-candidate returns, then confirm once on 2018–2023 and in the portfolio.

### 85a. Stage D choices, fixed before 2018–2023 was opened

Recorded 2026-10-20, 2010–2017 only.

**Goal 1:**

| Spec | ROC-AUC | PR-AUC | Log loss | Brier |
|---|---|---|---|---|
| Original Model B (`d45`) | 0.692 | 0.107 | 0.21105 | — |
| OU alone (calibrated) | 0.716 | 0.112 | 0.20596 | — |
| B+rule | 0.716 | 0.122 | 0.20322 | — |
| **B+rule+ou** | **0.735** | **0.134** | **0.19989** | 0.0513 |
| B+all+ou | 0.738 | 0.136 | 0.19991 | — |

- **Adopted:** the `ou` block. **B+rule+ou is the new Goal 1 candidate.**
- **OU alone:** with only a yearly logistic calibration, the econometric
  model matches Model B under the same scheme (log loss 0.20596 against
  0.20600) and beats the original Model B.

**Goal 2** (adopted exit, R1 events excluded):

| Candidate | Monthly Sharpe | Per trade |
|---|---|---|
| **G-a, current design** | **0.71** | **+19.2 bps** |
| G-b, OU expected-value ranking | −0.87 | −42.5 bps |
| G-c, OU take-profit filter | 0.64 | +13.7 bps |

**G-a is kept.** The OU expected value is largest for wide, loosely tied
spreads, which are the ones that break down (as in the Decision 76
diagnostics).

### 85b. Stage D holdout: the OU block improves the forecast further

Recorded 2026-10-20 (2018–2023, opened for the eighth time, see the
Decision 85 caveat).

| Spec | ROC-AUC | PR-AUC | Log loss | Brier | Log-loss gain over the original Model B | Gain over B+rule |
|---|---|---|---|---|---|---|
| Original Model B | 0.718 | 0.207 | 0.2832 | 0.0790 | — | — |
| B+rule | 0.730 | 0.214 | 0.2799 | 0.0785 | +33.6 × 10⁻⁴, p 0.007 | — |
| **B+rule+ou** | **0.733** | **0.216** | **0.2784** | **0.0782** | **+48.5 × 10⁻⁴, p 0.007** | +14.8 × 10⁻⁴, p 0.14 |
| B+all+ou | 0.734 | 0.218 | 0.2778 | 0.0780 | +54.8 × 10⁻⁴ | — |
| OU alone | 0.700 | 0.176 | 0.2875 | 0.0802 | — | — |

**B+rule+ou is adopted as the Goal 1 forecaster.** It improves on B+rule
in both blocks; the extra step is positive but not significant on its own.

OU alone was competitive in 2010–2017 but weaker in 2018–2023. The
structural prior is useful as an input to the ML model rather than as a
forecaster on its own.

## 86. Pre-registered Stage E: model capacity for the larger feature set, and ranking

Recorded 2026-10-20, before any result below. B+rule+ou has about 170
inputs. Decision 66 found that re-tuning did not help with Model B's 99, but
feature subsampling and seed bagging are standard remedies for wide inputs.

**Goal 1 variants of B+rule+ou** (`recent` scheme; base = the Decision 45
XGBoost):

| Variant | Change from base |
|---|---|
| col05 | Columns subsampled to 50 % per tree |
| slow | 800 trees at learning rate 0.015 |
| bag5 | col05 plus 80 % row subsampling, averaged over 5 seeds |

**Goal 1 rule:** a variant replaces the base if it has a lower 2010–2017
log loss (the lowest wins). 2018–2023 is opened once.

**Goal 2 rule:** the top 20 % of B+rule+ou (or of the winning variant),
excluding R1 events, under the adopted exit, is compared with the current
design (G-a) on 2010–2017 monthly Sharpe. It replaces G-a only if higher.

## 87. Pre-registered Stage F: expected-value ranking from the best forecaster

Recorded 2026-10-20, before any result below.

**Diagnosis (2010–2017, adopted exit).** Net profit rises with predicted
reversion probability for both models, but differently at the top decile:

| Model, top decile | Reversion rate | Median spread scale, std / (1 + \|beta\|) | Net per trade |
|---|---|---|---|
| B+rule+ou | 16.3 % | 235 bps | +7.5 bps |
| Original Model B | 12.3 % | 296 bps | +9.7 bps |

The better forecaster concentrates on tight spreads, whose reversions are
small relative to fixed costs. Profit is roughly probability × payoff scale
minus costs.

**Ranking.** For test year Y, every 2010…Y−1 event priced under the
adopted exit (take profit |z| 1.0, E3 news exit, disaster stop |z| 5,
20 sessions) gives:
- its walk-forward out-of-sample probability p;
- its scale, spread std / (1 + |beta|);
- its realised net return.

1. Fit OLS of net / scale (winsorised at 1 %/99 %) on p, giving two
   coefficients a and b.
2. Score each event as EV = scale × (a + b × p).
3. Trade the top 20 % by EV, using the previous year's EV distribution as
   the cutoff, excluding R1 events.

**Candidates:**
- F-a: EV with p from B+rule+ou (the Goal 1 forecaster);
- F-b: EV with p from the original Model B;
- G-a: the current design.

Because the fit needs a year of history, the comparison runs on 2011–2017.

**Rule.** The highest 2011–2017 monthly Sharpe of per-candidate returns
wins; it replaces G-a only if higher. Then 2018–2023 once, and the
portfolio.

### 87a. Stage F result: the expected-value ranking does not beat the current design

Recorded 2026-10-20. 2011–2017, adopted exit, R1 events excluded.

| Candidate | Trades | Per trade | Monthly Sharpe |
|---|---|---|---|
| **G-a, current design** | 1,520 | **+20.0 bps** | **0.80** |
| F-b, EV with original Model B probability | 1,774 | +8.0 bps | 0.51 |
| F-a, EV with B+rule+ou probability | 1,859 | +6.6 bps | 0.35 |

**The mapping is stable:** a ≈ −0.055 and b ≈ +0.5 in every year, so
trades pay only when p is above about 0.11, and scale magnifies both
outcomes.

**G-a is kept.** Seven alternative selections have now failed to beat it
on the selection years (Decisions 79a, 85a, 86 Goal 2 and 87a):
- R-b, ranking by B+rule;
- R-c, the return regression;
- G-b, ranking by OU expected value;
- G-c, the OU take-profit filter;
- G-d, ranking by B+rule+ou;
- F-a and F-b, the expected-value rankings.

For trade selection, the simple original-Model-B top 20 % is the most
robust signal found.

### 86a. Stage E choices, fixed before 2018–2023 was opened

Recorded 2026-10-20, 2010–2017 only.

**Goal 1, B+rule+ou variants:**

| Variant | ROC-AUC | PR-AUC | Log loss | Brier |
|---|---|---|---|---|
| base | 0.735 | 0.134 | 0.19989 | 0.0513 |
| slow | 0.736 | — | 0.19965 | — |
| col05 | 0.740 | — | 0.19865 | — |
| **bag5** | **0.743** | **0.141** | **0.19802** | **0.0510** |

**bag5 is the chosen Goal 1 variant.**

**Goal 2:** the bag5 top 20 % without R1 events reaches Sharpe 0.47
(+9.5 bps per trade), against 0.71 (+19.2 bps) for G-a. **G-a is kept.**

### 86b. Stage E holdout: seed bagging adopted

Recorded 2026-10-20. 2018–2023 (opened for the ninth time):

| Variant | ROC-AUC | PR-AUC | Log loss | Brier | Gain over the original Model B | Gain over base |
|---|---|---|---|---|---|---|
| base | 0.733 | 0.216 | 0.27839 | 0.0782 | +48.5 × 10⁻⁴ | — |
| col05 | 0.736 | 0.220 | 0.27785 | 0.0780 | +53.9 × 10⁻⁴ | +5.4, p 0.065 |
| slow | 0.734 | — | 0.27820 | — | — | +1.9, p 0.079 |
| **bag5** | **0.735** | 0.217 | **0.27797** | 0.0781 | **+52.6 × 10⁻⁴, p 0.002** | +4.1, p 0.110 |

**bag5 (B+rule+ou, 50 % columns, 80 % rows, 5 seeds) is adopted as the
Goal 1 forecaster.** It improves on base in both blocks.

## 88. Pre-registered Stage G: track-record and cointegration blocks on the bagged model

Recorded 2026-10-20, before any result below. The two unused blocks with the
strongest earlier signal were:
- `track`: B+all beat B+rule on the 2018–2023 holdout;
- the Decision 67 cointegration block: B+all+coint had the best 2010–2017
  log loss in Stage A.

**Specs** (bag5): B+rule+ou+track and B+rule+ou+coint.

**Rule:** a block is added if its spec lowers the 2010–2017 log loss
below bag5's (0.19802). If both do, the combined spec is run and kept only
if it beats both. 2018–2023 is opened once.

## 89. Pre-registered Stage H: structural-break filters on the current design

Recorded 2026-10-20, before any result below. These are filters on the G-a
design (R-a top 20 %, R1 events excluded, adopted exit) that skip pairs
whose relationship shows signs of a break:

| Filter | Skip the event if |
|---|---|
| H-a | The pair's most recent earlier event, resolved before the signal date, was STOPPED (hit the adverse z of 3) within the last 60 calendar days |
| H-b | The spread has not crossed its mean for more than 120 sessions (`state_days_since_zero_cross` > 120) |

**Rule:** the filter with the higher 2010–2017 monthly Sharpe of
per-candidate returns is adopted if that Sharpe exceeds G-a's (0.71).
2018–2023 and the portfolio follow once.

### 89a. Stage H choice: H-b, by a small margin

Recorded 2026-10-20, 2010–2017:

| Design | Trades | Per trade | Monthly Sharpe |
|---|---|---|---|
| G-a | 1,583 | +19.2 bps | 0.71 |
| H-a | 1,393 | +17.5 bps | 0.62 |
| **H-b** | 1,537 | **+20.5 bps** | **0.73** |

H-b exceeds G-a and is chosen by the rule. The margin is small and within
noise. The 2018–2023 result and the portfolio decide whether it is kept.

### 89b. Stage H holdout and portfolio: H-b kept, with a small effect

Recorded 2026-10-20.

**Per candidate, 2018–2023:**

| Design | Monthly Sharpe | Per trade |
|---|---|---|
| **H-b** | **0.93** | **+43.0 bps** |
| G-a | 0.78 | +38.8 bps |
| H-a | 0.70 | — |

**Portfolio, 25 % per entry:**

| Design | 2010–2023 CAGR | Sharpe | Max drawdown | 2010–2017 Sharpe | 2018–2023 Sharpe |
|---|---|---|---|---|---|
| **H-b** | **+2.31 %** | **0.42** | **−13.2 %** | 0.18 | **0.70** |
| C2-a | +2.25 % | 0.41 | −13.8 % | 0.25 | 0.60 |

At 10 % per entry: Sharpe 0.52 against 0.48.

H-b is kept as part of the design: it is economically plausible (it skips
broken relationships) and confirmed per candidate in both blocks. Its
portfolio effect is small, worse in 2010–2017 and better in 2018–2023.

## 90. Pre-registered Stage I: recalibration on the previous year's out-of-sample predictions

Recorded 2026-10-20, before any result below.

**Motivation.** Log loss depends on calibration, and the label base rate
drifts (about 5.6 % in 2010–2017, about 10 % in 2018–2023).

**Variants,** applied to the Goal 1 forecaster's raw scores (bag5, or the
Stage G winner):

| Variant | Calibration |
|---|---|
| I-0 (current) | Platt on out-of-fold training scores from the last 3 years |
| I-1 | Platt on the previous year's walk-forward test predictions whose labels resolved before 1 January of the test year |
| I-2 | Platt on the previous two years' walk-forward test predictions, under the same condition |

Raw scores, and hence ranking and AUC, are unchanged. Only log loss and
Brier are affected.

**Rule.** A variant replaces I-0 if it has the lowest 2011–2017 log loss
(2010 has no previous-year predictions). 2018–2023 is opened once.

### 90a. Stage I result: the current calibration is kept

Recorded 2026-10-20, 2011–2017, bag5:

| Variant | Log loss | Brier |
|---|---|---|
| **I-0 (current)** | **0.20406** | 0.05300 |
| I-2 | 0.20430 | 0.05294 |
| I-1 | 0.20473 | 0.05295 |

I-0 has the lowest log loss, so nothing changes, and 2018–2023 was not
opened for this stage.

### 88a. Stage G choice: the cointegration block is added

Recorded 2026-10-21, 2010–2017, bag5:

| Spec | ROC-AUC | PR-AUC | Log loss | Brier |
|---|---|---|---|---|
| B+rule+ou | 0.743 | 0.141 | 0.19802 | 0.0510 |
| B+rule+ou+track | 0.745 | 0.142 | 0.19815 | 0.0511 |
| **B+rule+ou+coint** | **0.746** | **0.148** | **0.19741** | **0.0509** |

Only coint lowers log loss, so **B+rule+ou+coint (bag5)** is the Stage G
choice, and no combined spec is needed. 2018–2023 is opened once.

### 88b. Stage G holdout: coint does not hold out; track is the best observed model (post-hoc)

Recorded 2026-10-21. 2018–2023, bag5:

| Spec | ROC-AUC | PR-AUC | Log loss | Brier | Gain over bag5 |
|---|---|---|---|---|---|
| B+rule+ou | 0.735 | 0.217 | 0.27797 | 0.0781 | — |
| B+rule+ou+coint (rule choice) | 0.735 | 0.220 | 0.27794 | 0.0780 | +0.3 × 10⁻⁴, p 0.47 |
| B+rule+ou+track (rejected by the rule) | **0.739** | **0.222** | **0.27649** | **0.0777** | **+14.8 × 10⁻⁴, p 0.001** |

**Coint:** the rule's choice adds nothing out of sample, so it is **not
added**. The simpler B+rule+ou (bag5) stays the pre-registered Goal 1
forecaster.

**Track** has now beaten its comparator on the holdout twice (Decision 81b:
B+all over B+rule; here over bag5), while failing the selection-year rule
both times. A plausible reason is that track-record features need years of
resolved history: in 2010–2017 they are shrunk heavily towards the base
rate, so the selection years understate them.

**B+rule+ou+track (bag5) is reported as the best observed forecaster**
(holdout AUC 0.739 against 0.718 for the original Model B, log-loss gain
+67.4 × 10⁻⁴, p 0.001). It is post-hoc, so choosing it for the final test
is the owner's decision.

## 91. Updated final-test proposal (supersedes Decision 84; owner to decide)

Recorded 2026-10-21 after Stages D–I (Decisions 85–90).

**Goal 1, forecasting.** Pre-registered model: B+rule+ou with 50 % column
and 80 % row subsampling, averaged over 5 seeds (the `recent` scheme).
- **On 2018–2023:** ROC-AUC 0.735 and log loss 0.2780, against 0.718 and
  0.2832 for the original Model B (log-loss gain p = 0.002).
- **Best observed (post-hoc):** adding the track block gives AUC 0.739 and
  log loss 0.2765.

The proposal is to report both against the original Model B on the final
test.

**Goal 2, portfolio.**
- **Selection:** original Model B, top 20 %.
- **Entry filters:** skip R1 events, and skip pairs whose spread has not
  crossed its mean for more than 120 sessions.
- **Entry and costs:** frozen.
- **Exits:** take profit at |z| ≤ 1.0, E3 news exit, disaster stop at
  |z| ≥ 5, 20-session time stop.
- **Portfolio policy:** frozen.

On 2010–2023 this design has CAGR +2.31 %, Sharpe 0.42 and maximum
drawdown −13.2 %.

**Adoption.** The exit and filter changes alter the frozen Decision 36
execution policy, so adopting them needs a new freeze manifest and the
owner's explicit unlock of the 2024–2025 final test. Full write-up:
`docs/P6_QUANT_RESEARCH.md`; the method comparison is in
`outputs/p6_quant/goal1_table.csv`.

## 92. Pre-registered Stage J: LightGBM and an XGBoost–LightGBM blend on the wide feature set

Recorded 2026-10-21, before any result below. Decision 66 found no library
gain on Model B's narrower inputs. On the ~170 B+rule+ou inputs, model
diversity may help log loss.

**Specs on B+rule+ou** (`recent` scheme):

| Spec | Model |
|---|---|
| lgbm5 | LightGBM, 400 trees, learning rate 0.03, 8 leaves, min 100 per leaf, lambda 10, 50 % columns, 80 % rows, 5 seeds |
| blend | Equal-weight mean of the bag5 (XGBoost) and lgbm5 calibrated probabilities; the raw score is the mean of the two raw scores |

**Rule:** the spec with the lowest 2010–2017 log loss replaces bag5 if it
beats it (0.19802). 2018–2023 is opened once.

### 92a. Stage J result: bag5 is kept

Recorded 2026-10-21, 2010–2017:

| Spec | Log loss | ROC-AUC |
|---|---|---|
| **bag5 (XGBoost)** | **0.19802** | 0.743 |
| blend | 0.19837 | 0.742 |
| lgbm5 | 0.19887 | 0.741 |

Neither beats bag5, so nothing changes and 2018–2023 was not opened for
this stage. As in Decision 66, the library is not the lever.

## 93. Pre-registered Stage K: point-in-time sector track-record filter

Recorded 2026-10-21, before any result below.

**Motivation.** A 2010–2017 diagnostic of the H-b design's trades showed
Financials losing −26 bps per trade (301 trades). Excluding a sector chosen
from that table would be hindsight, so the rule is point-in-time instead.

**K-a.** Skip an event if the trades selected by the design in its sector,
with outcomes resolved within the previous 3 years and before the signal
date, have a negative mean net return under the adopted exit. The rule is
active only with at least 20 such trades. Everything else is the H-b
design.

**Rule:** K-a is adopted if its 2010–2017 monthly Sharpe of per-candidate
returns exceeds H-b's (0.73). 2018–2023 and the portfolio follow once.

### 93a. Stage K result: the sector track-record filter is not adopted

Recorded 2026-10-21, 2010–2017:

| Design | Trades | Per trade | Monthly Sharpe |
|---|---|---|---|
| **H-b** | 1,537 | +20.5 bps | **0.73** |
| K-a | 1,314 | +20.4 bps | 0.66 |

K-a skipped 1,056 of 4,291 selected events over 2010–2023, spread across
sectors and years. Sector-level strategy performance does not persist well
enough to filter on, so the Financials weakness of 2010–2017 was not
predictable point-in-time. **The design is unchanged**, and 2018–2023 was
not opened for this stage.

## 94. Pre-registered Stage L: overnight versus intraday decomposition

Recorded 2026-10-21, before any result below.

**Rationale.** News arrives mostly overnight and shows up as an opening
gap, while intraday moves carry more liquidity and demand pressure. Lou,
Polk & Skouras (2019) document a persistent overnight–intraday tug of war
with cross-period reversal. A divergence made of a gap should therefore
persist more than one built up intraday.

**Block `intraday`** (signal day, split-adjusted with each day's
adj_close/close factor), using only the signal day's open, high, low and
close:
- each leg's overnight log return and intraday log return, aligned with the
  divergence;
- the mover's gap share, |overnight| / (|overnight| + |intraday|);
- each leg's high–low range relative to its previous 20-day average;
- each leg's close location in the day's range, aligned.

**Goal 1 rule:** B+rule+ou+intraday (bag5) replaces bag5 if it has a lower
2010–2017 log loss (0.19802). 2018–2023 is opened once.

**Goal 2 rule:** a filter on H-b that skips events whose mover gap share
is ≥ 0.7 (a news-gap divergence) is adopted if its 2010–2017 monthly Sharpe
exceeds H-b's (0.73). 2018–2023 and the portfolio follow once.

### 94a. Stage L result: neither the intraday block nor the gap filter is adopted

Recorded 2026-10-21, 2010–2017:

| Rule | Candidate | Comparator |
|---|---|---|
| Goal 1 | B+rule+ou+intraday (bag5): log loss 0.19804, AUC 0.742 | bag5: 0.19802, AUC 0.743 |
| Goal 2 | News-gap filter on H-b: Sharpe 0.59, +17.4 bps per trade | H-b: Sharpe 0.73, +20.5 bps per trade |

- **Gap-driven divergences:** among the model's selections they are not
  worse trades.
- **Signal-day decomposition:** it adds no forecasting information beyond
  the existing 1-day abnormal returns and volume shocks.

Nothing changes, and 2018–2023 was not opened for this stage.

## 95. Pre-registered Stage M: per-stock trading costs and cost-aware selection

Recorded 2026-10-21, before any result below. The owner asked to lower
trading costs. The frozen policy charges a flat 5 bps per side.

**Cost model** (`p6_quant_costs`, point-in-time at the signal date), per
leg and per side:

| Component | Definition | Source |
|---|---|---|
| Half spread | Half of the Abdi–Ranaldo (2017) estimate, sqrt(max(4 × mean[(c_t − η_t)(c_t − η_{t+1})], 0)), with c the log close and η the mean of the log high and low, averaged over the previous 60 sessions | Abdi & Ranaldo (2017) |
| Impact | Y × σ × sqrt(Q / V), with Y = 0.7 (middle of the 0.5–1.0 range for large-cap equities), σ the 20-session return volatility, V the 20-session average dollar volume, and Q the leg's notional at an assumed $10m of capital and 25 % of NAV per entry | Square-root law |
| Commission | 0.5 bps | — |

- **Cap:** per-side costs are capped at 200 bps.
- **Per-trade rate:** each trade's cost rate is the leg-gross-weighted
  average, applied at entry and exit.
- **Sensitivities:** $1m and $100m of capital.

**Pricing.** Every event is re-priced under the adopted exit with these
costs, using the verified exit loop with the per-trade rates in place of
the flat 5 bps.

**Stage M selections:**

| Candidate | Selection |
|---|---|
| M-0 | The H-b design, priced with per-stock costs (reference) |
| M-1 | M-0, skipping events whose estimated round-trip cost is at least the previous year's 80th percentile over all events (avoid expensive names) |
| M-2 | M-0, skipping events whose estimated round-trip cost exceeds 20 bps |

**Rule:** M-1 or M-2 is adopted if its 2010–2017 monthly Sharpe of
per-candidate returns under per-stock costs is the highest and above
M-0's. 2018–2023 and the portfolio (with per-trade costs) follow once.

### 95a. Amendment before any return was computed: spread component replaced

Recorded 2026-10-21. Only cost levels had been inspected; no trade return
under the cost model had been read.

**Why.** The Abdi–Ranaldo estimate is unreliable for these large caps:

| Stock | Half-spread estimate (yearly medians, 2012/2016/2021) |
|---|---|
| KO | 11–19 bps, against a true half-spread of about 1 bp |
| PEP | 12–15 bps |
| JPM, AAL, ALK | Mostly floored at 0 |

With spreads this small, its noise dominates; the estimator is designed
for, and most accurate on, less liquid stocks. The per-side median at $1m
came out at 19 bps, which is not credible for S&P 500 names.

**Replacement half spread.** A tier by 20-session dollar ADV, matching
typical effective spreads of US large caps:

| 20-session dollar ADV | Half spread |
|---|---|
| ≥ $200m | 1 bp |
| $50–200m | 2 bps |
| $20–50m | 4 bps |
| < $20m | 8 bps |

Impact (Y = 0.7, square root) and the 0.5 bps commission are unchanged, as
are the Stage M candidates and rule.

**Limitation.** The tiers do not widen for 2006–2009, when spreads were
wider. The flat 5 bps remains the project's accepted cost, and the Stage M
results are reported alongside it.

### 95b. Stage M choice: M-1, avoiding the most expensive trades

Recorded 2026-10-21, 2010–2017.

**Amended cost levels** (median per side): $1m 5.5 bps, $10m 12.7 bps,
$100m 35 bps. Impact dominates at $10m because each entry is 25 % of NAV.

| Candidate | Trades | Flat 5 bps: per trade, Sharpe | Per-stock costs at $10m: per trade, Sharpe |
|---|---|---|---|
| M-0 (H-b) | 1,537 | +20.5 bps, 0.73 | +2.0 bps, 0.10 |
| **M-1** | 1,304 | +19.2 bps, 0.72 | **+6.6 bps, 0.27** |
| M-2 | 600 | +2.7 bps, 0.16 | −2.4 bps, 0.02 |

**Choice: M-1.** Under realistic costs at $10m the current design's edge
mostly disappears, and skipping the most expensive fifth of trades
recovers part of it.

The main cost driver is the position size relative to ADV, which is the
subject of the next stage (portfolio construction).

### 95c. Stage M holdout: M-1 helps under realistic costs; capacity is limited

Recorded 2026-10-21. 2018–2023, per candidate:

| Costs | H-b Sharpe | **M-1 Sharpe** | H-b per trade | M-1 per trade |
|---|---|---|---|---|
| Flat 5 bps | 0.93 | **1.04** | +43.0 bps | +30.0 bps |
| Per-stock at $1m | 0.88 | **1.07** | +39.1 bps | +30.9 bps |
| Per-stock at $10m | 0.37 | **0.68** | +17.8 bps | +19.0 bps |
| Per-stock at $100m | −1.50 | −0.65 | −45.4 bps | −18.7 bps |

**M-1 is adopted:** it confirms on the holdout under every cost
assumption.

**Capacity.** With 25 % of NAV per entry, impact makes the strategy
unprofitable at $100m and roughly halves its Sharpe at $10m. Position size
relative to liquidity is the binding constraint.

## 96. Pre-registered Stage N: portfolio construction under realistic costs

Recorded 2026-10-21, before any result below. The selection is M-1 (H-b
without the most expensive fifth). Every trade is priced with per-stock
costs at $10m of capital, where impact is recomputed for each design's
position size, so smaller positions cost less.

**Designs** (gross capped at 100 % of NAV, frozen exits and policy
otherwise):

| Design | Per entry | Sector cap |
|---|---|---|
| N-25 | 25 % of NAV | — |
| N-10 | 10 % | — |
| N-5 | 5 % | — |
| N-10s | 10 % | Each sector's gross at entry ≤ 30 % of NAV |
| N-5s | 5 % | Each sector's gross at entry ≤ 30 % of NAV |

**Rule:** the highest 2010–2017 daily-return portfolio Sharpe wins, then
2018–2023 once. The winner is also reported at $1m and $100m of capital.

### 96a. Stage N result: smaller positions win under realistic costs; capacity is the limit

Recorded 2026-10-21. **Disclosure:** the run script printed every period,
including 2018–2023, before this choice was written down. The rule
(highest 2010–2017 Sharpe) is mechanical and gives the same choice
regardless.

**Results at $10m, per-stock costs:**

| Design | 2010–2017 Sharpe | 2018–2023 Sharpe | 2010–2023 Sharpe | CAGR | Max drawdown |
|---|---|---|---|---|---|
| N-25 | −0.26 | 0.51 | 0.12 | +0.5 % | −19.2 % |
| N-10 | 0.27 | 0.64 | 0.46 | +1.8 % | −9.5 % |
| **N-5** | **0.46** | 0.61 | **0.52** | +1.7 % | **−8.4 %** |
| N-10s, N-5s | Identical to N-10 and N-5 | — | — | — | — |

The 30 % sector cap never binds at these sizes.

**Choice: N-5** (5 % of NAV per entry).

**Capacity (2010–2023):**

| Capital | N-5 Sharpe | N-5 CAGR | N-25 Sharpe |
|---|---|---|---|
| $1m | 0.66 | +2.1 % | 0.43 |
| $10m | 0.52 | +1.7 % | 0.12 |
| $100m | 0.11 | +0.3 % | −0.81 |

**Reading.** Smaller positions cut impact, so Sharpe roughly quadruples at
$10m. The portfolio then holds only about 10.5 positions at 44 % gross on
average, which is limited by the number of signals, not by capital. The
remaining lever is breadth: a larger universe.

# PLAN.md — Implementation Plan

**Project:** AI Structural-Break Detector for Statistical Arbitrage  
**Execution model:** coding agents implement the complete system; the user owns the final academic report and presentation/video.  
**Gate rule:** a phase is complete only when its acceptance criteria pass. Later phases must not be used to hide an earlier scientific/data defect.

## Status legend

- `[ ]` not started
- `[-]` in progress
- `[x]` complete and acceptance gate passed
- `[!]` blocked / decision required

---
## Phase completion protocol

Each phase is a hard implementation gate.

For every phase:

1. Read AGENTS.md, DECISIONS.md, this phase, and only the relevant specification files.
2. Inspect the existing repository before changing code.
3. Implement the complete phase scope.
4. Add or update automated tests for every acceptance criterion that can be tested.
5. Run the full relevant test/lint/type-check suite.
6. Exercise the actual pipeline on realistic fixture or project data where applicable.
7. Fix failures before declaring the phase complete.
8. Perform a final gap analysis against every acceptance criterion in this phase.
9. Record completion evidence in docs/STATUS.md.
10. Stop at the phase boundary. Do not begin the next phase unless explicitly requested.

A phase is NOT complete because:
- files/classes/functions exist;
- code imports successfully;
- mocked tests pass while the real pipeline is untested;
- placeholders/TODOs remain for required functionality;
- an acceptance criterion was skipped because it was difficult;
- downstream functionality was stubbed merely to make tests green.

If a criterion cannot be completed, record it as BLOCKED with the exact reason and stop rather than silently reducing scope.

---
## P0 — Repository, environment and storage foundation

Status: complete; all P0 acceptance gates passed. See `docs/archive/IMPLEMENTATION_HISTORY.md` for evidence.
Stopped at the P0 boundary; P1 requires a separate instruction.

### Build

- [x] Create the repository skeleton from the Software Engineering specification.
- [x] Add Python 3.11, `pyproject.toml`, `uv.lock`, `.python-version`, `.env.example`, `.gitignore`.
- [x] Keep the canonical agent-facing Markdown specifications under `docs/specs/`; PDFs remain under `docs/archive/pdfs/` as archival/human-readable copies.
- [x] Implement typed configuration loading for universe, data, econometrics, ML, agents, decision, backtest and app settings.
- [x] Implement structured logging and run IDs.
- [x] Implement the canonical directory resolver from `docs/DECISIONS.md`.
- [x] Create DuckDB SQL migrations and schema/version registry.
- [x] Implement DuckDB, Parquet, document, artifact and run-registry storage helpers.
- [x] Add deterministic tiny fixtures.
- [x] Configure Ruff, mypy, pytest and GitHub Actions.

### Acceptance gate P0

- [x] Fresh clone + `uv sync --frozen` succeeds.
- [x] Fresh `data/analytics/structural_break.duckdb` can be created entirely from migrations.
- [x] Read/write storage fixture test passes.
- [x] CI passes without network or LLM access (Windows, Linux and Colab bootstrap).
- [x] No scientific logic is trapped in Streamlit/notebooks.

---

## P1 — Data ingestion, reference data and lineage

Status: complete; all P1 acceptance gates passed on 2026-10-03. See `docs/archive/IMPLEMENTATION_HISTORY.md`
for live freeze, offline reproduction and hosted acceptance evidence. Stopped at P1.

### Build

- [x] Encode the fixed 28-pair universe and orientation from `docs/DECISIONS.md` in versioned reference/config data.
- [x] Build `security_master`, including ticker, CIK, issuer, sector/sub-industry, sector ETF, lifecycle fields and manual-review status.
- [x] Implement Yahoo/yfinance daily OHLCV/actions bootstrap beginning 2014-01-01.
- [x] Ingest SPY and required sector ETFs under the same market-data contract.
- [x] Ingest official Cboe VIX history.
- [x] Ingest SEC ticker-CIK mapping and company submissions metadata.
- [x] Normalize SEC filing index with acceptance timestamps.
- [x] Implement immutable raw snapshots, source manifests and SHA/hash lineage where specified.
- [x] Build canonical curated Parquet datasets.
- [x] Register DuckDB views/tables and data snapshot metadata.
- [x] Implement data-quality checks: keys, duplicates, monotonic dates, positive prices, missingness, calendar alignment, source freshness, timestamp validity.
- [x] Implement optional news adapter only as non-headline current/demo enrichment; it must remain disabled for headline historical experiments.

### Acceptance gate P1

- [x] One command/job sequence reproduces a frozen market + reference + SEC-index data snapshot.
- [x] Every curated row has source/data lineage.
- [x] No forward-filled missing equity prices across missing/non-trading observations.
- [x] SEC acceptance timestamps are stored and queryable.
- [x] Historical app/data queries can run without network access after ingestion.

---

## P2 — Econometric Relationship Engine and signal state

### Build

- [x] Align pair price histories and apply log-price transforms.
- [x] Implement ADF/KPSS integration diagnostics according to the econometric specification.
- [x] Implement fixed-orientation 504-day Engle-Granger estimation.
- [x] Use appropriate Engle-Granger/MacKinnon cointegration outputs.
- [x] Store alpha, beta/cointegration vector, formation spread moments and diagnostics.
- [x] Implement monthly point-in-time re-estimation with next-session effective timestamps.
- [x] Compute daily out-of-sample spread/z-score from frozen monthly parameters.
- [x] Compute half-life and relationship-stability diagnostics.
- [x] Implement `ACTIVE` / `WATCH` / `RETIRED` lifecycle logic.
- [x] Produce daily pair-state history.
- [x] Produce raw fresh threshold crossings for Baseline 0 where a current spread is estimable.
- [x] Produce econometrically valid fresh threshold crossings for downstream ML/Baseline 1.

### Acceptance gate P2

- [x] Synthetic known-stationary/cointegrated fixtures behave as expected.
- [x] Monthly snapshots never use future observations.
- [x] Daily signal rows always join to the latest effective historical snapshot, never a future snapshot.
- [x] Same frozen input/config regenerates identical snapshot/event IDs.
- [x] Several representative pairs are manually inspected against stored diagnostics/plots.

---

## P3 — Divergence dataset, Model A and minimal app shell

Status: complete; all P3 acceptance gates passed on 2026-10-03. See `docs/archive/IMPLEMENTATION_HISTORY.md`
for frozen-data counts, development metrics, reload/app checks and hosted CI.
Stopped at P3. Sparse one-class validation limits predictive conclusions.

### Build

- [x] Generate one divergence event per episode with de-duplication.
- [x] Construct binary labels using the frozen convergence/stop/horizon policy.
- [x] Implement censoring and 10-trading-day partition embargo.
- [x] Build point-in-time quantitative Model A features:
  - spread state;
  - relationship quality;
  - market context;
  - security state;
  - liquidity / implementation.
- [x] Build deterministic event/feature/target schemas and lineage.
- [x] Create chronological train/validation/final-test partitions.
- [x] Train the logistic benchmark.
- [x] Train/tune XGBoost Model A using training/validation only.
- [x] Calibrate Model A probabilities using validation data.
- [x] Freeze Model A candidate threshold using validation policy.
- [x] Save/load model bundle, calibrator, feature schema and SHAP reference data.
- [x] Implement Model A inference and SHAP outputs.
- [x] Create a minimal read-only Streamlit shell with Scanner and Pair Detail backed by services/fixtures or current quantitative outputs.

### Acceptance gate P3

- [x] Leakage tests pass for every quantitative feature.
- [x] Event counts and labels are reproducible.
- [x] Train/validation/embargo counts are documented.
- [x] Logistic and Model A metrics are available for training/validation without opening headline final-test results.
- [x] Saved Model A reproduces stored inference probabilities after reload.
- [x] Minimal Scanner/Pair Detail render without model training inside UI callbacks.

---

## P4 — Point-in-time SEC event intelligence and Model B

Status: complete; all P4 acceptance gates passed on 2026-10-05. See
`docs/archive/IMPLEMENTATION_HISTORY.md` for the genuine partial extraction pilot, stored-model replay,
paired validation limits and Windows/Linux/Colab evidence. Stopped at P4.
Final-test outcomes remain locked; current P5 work is tracked below.

### Build

- [x] Implement event-specific SEC evidence selection using only filings accepted at/before event cutoff.
- [x] Lazily download/cache required filing bodies and exhibits by accession number.
- [x] Parse/clean SEC documents while retaining provenance.
- [x] Chunk and index documents with stable chunk IDs.
- [x] Implement deterministic admissibility filtering before relevance ranking.
- [x] Implement local lexical retrieval; optional semantic reranking only if it does not become a dependency for correctness.
- [x] Build bounded evidence packs.
- [x] Implement schema-constrained catalyst extraction from admissible SEC evidence.
- [x] Persist structured event features and evidence IDs.
- [x] Create Model B feature schema = Model A + structured event block.
- [x] Train/tune/calibrate Model B under the same chronological protocol as Model A.
- [x] Freeze Model B threshold using validation data.
- [x] Save Model B artifacts and SHAP outputs.
- [x] Implement extraction/Model-B caches and mocked extraction fixtures for CI.

### Acceptance gate P4

- [x] Every non-`NONE` structured catalyst has admissible evidence IDs.
- [x] Every supporting SEC timestamp is `<= event_timestamp`.
- [x] `NONE` is distinguishable from retrieval/coverage `UNKNOWN`.
- [x] Model B can be rebuilt from stored structured event features without re-calling an LLM.
- [x] Model A vs Model B validation comparison is reproducible.
- [x] Missing event evidence cannot silently remove difficult observations from evaluation; coverage flags are explicit.

---

## Research v2 — authorized development redesign

Status: **ACCEPTED** 2026-10-17 (DECISIONS section 34). Current delivery gates are in `docs/STATUS.md`; the
scientific authority is `docs/RESEARCH_V2_PROTOCOL.md`. Detailed prior acceptance
and recovery records are archived, rather than repeated in this plan.

- [x] Freeze the 250-issuer, 40-group, 736-pair business-peer roster and original orientations.
- [x] Capture and verify 2004–2023 market sources and corrected SEC `source_v3`.
- [x] Complete the 10/20/30-session quantitative registries for all 736 pairs.
- [x] Implement free guarded Gemma, pinned FinBERT, metadata/tone/catalyst ablations and matched A/B evaluation.
- [x] Verify quality-v2 preprocessing, compact aggregation, operation-local parsing and native reporting with offline engineering checks.
- [x] Freeze detached source `a02aadf` and pass its exact Windows/Linux/Colab hosted CI.
- [x] Audit and copy 2,290 preserved checkpoints unchanged; launch the full 37,421-event `development_detached_v2` build with the frozen 500-event catalyst schedule.
- [x] Recover the interrupted 4,727-checkpoint attempt into `development_prefetch_v2` with bounded parallel source preparation, a fresh audit and a new source/CI freeze; retain unchanged scientific inputs.
- [x] Complete genuine SEC/metadata/FinBERT feature generation and disclose source/inference coverage.
- [x] Fit all thirty primary and sensitivity bundles and independently replay native inference, reports and matched A/B comparisons.
- [ ] Record actual denominators, positive outcomes, paired uncertainty and positive/negative comparison results.
- [x] Complete the current source/CI/app release gates and genuine six-stage pipeline receipt for the detached generation.
- [x] Publish verified readiness using `structural-break promote-primary --pipeline-receipt PIPELINE_RECEIPT --ci-gate CI_GATE` bound to the accepted generation.
- [x] Promote accepted v2 to GitHub `main` and the default app/run path, retaining original Git history and immutable reference artifacts.

The detached worker performs feature generation only. Model fits, independent
verification, publication and merge are separate gates. It does not open the
2024–2025 final test or establish Model B improvement. The old worker has exited;
cleanup and recovery are integrated before the next frozen launch. Commands are in
`docs/RESEARCH_V2_RUNBOOK.md`.

---

## P5 — Multi-agent structural-break investigation and decision controller

Status: **IN PROGRESS**, begun on 2026-10-11 following the user's authorization of
the bounded Week 4-inspired redesign. The first slice implements typed fixture
inputs, independent openings, one rebuttal exchange, separate synthesis and
validation, fail-safe caching and the Python controller. The current architecture
is in `docs/specs/04_MULTI_AGENT_PIPELINE.md` and DECISIONS section 28.

Work is isolated on `phase5/agents-controller-foundation`. Keep the live v2
checkout and its 37,421-event population, source-v3 inputs, quality-v2 FinBERT,
500-event catalyst schedule and A/B definitions frozen. Integrate only after all
v2 acceptance gates, including model/replay/CI/publication, have passed. Fixture
success does not complete P5, establish semantic quality or unlock 2024–2025.

### Build

Checked implementation items describe the verified fixture slice. They do not
complete accepted-generation integration or genuine semantic evaluation.

- [x] Implement immutable typed event contracts and LangGraph shared state.
- [x] Implement the deterministic controller with versioned categorical-risk policy and reason codes.
- [ ] Load accepted Model B quantitative state and reused SEC/FinBERT/catalyst inputs through a generation-bound historical adapter.
- [x] Implement the publication-gated historical adapter and source/native replay refusal checks; actual accepted v2 integration remains pending.
- [x] Feed both advocates the same immutable fixture evidence and structured reports; genuine adapter remains pending.
- [x] Implement Mean-Reversion Advocate role prompts and provider contract; genuine pilot remains pending.
- [x] Implement Structural-Break Advocate role prompts and provider contract; genuine pilot remains pending.
- [x] Run opening advocate nodes independently/in parallel, without seeing each other's drafts.
- [x] Implement exactly one independent rebuttal per advocate after both openings finish.
- [x] Implement a distinct synthesis/facilitator stage with cited interpretation and proposed categorical break risk.
- [x] Implement Python mechanical checks for exact quotes, identity, timestamps and quantitative references.
- [x] Implement separate semantic Risk/Validation for claim support, contradictions, coverage, mandate compliance and accepted break risk.
- [ ] Configure Gemma opening/rebuttal roles and Flash-Lite synthesis/validation with explicit model/prompt/graph versions; run a real pilot.
- [x] Implement explicit `CANDIDATE`, `REVIEW`, `NO TRADE`, `ABSTAIN` semantics.
- [x] Implement timeouts/retries/schema validation/fail-safe abstention and attempt budgets including retries.
- [x] Cache agent outputs by exact event/source/upstream-output/prompt/graph/model identity.
- [x] Implement durable total/model/day attempt reservations, exclusive leases and explicit audited recovery.
- [x] Implement frozen target-blind batch scheduling, complete denominator records and resumable immutable event checkpoints on mock inputs.
- [x] Implement checksum-checked lazy mock input inventories and blind source annotation export/validation; genuine adapter and quality evaluation remain pending.
- [ ] Count historically ACTIVE + frozen Model B threshold + hard-gate eligible events after genuine fitting.
- [ ] Persist statuses/reasons for deterministically skipped calls and declare optional REVIEW/audit schedules separately.
- [ ] If required by quota, freeze a target-blind agent schedule and matched B/Full-System denominator before evaluating that schedule.
- [ ] Build the fixed human-labelled evaluation workflow: at least 50 historical events, aim 100, source support/category/materiality/relevance and agent interpretation.
- [x] Implement genuine source-only review export/replay independently of fitted B, with a frozen raw capture and target-blind 50–100-event inventory.

### Acceptance gate P5

- [ ] No agent can alter stored econometric or ML values.
- [ ] Material claims resolve to valid evidence IDs and historical timestamps.
- [x] Opening independence, one-round topology and separate synthesis/semantic-validation roles pass deterministic integration checks.
- [x] Exact-quote checks are distinguished from semantic support, and failed mechanical checks cannot be overridden in the tested workflow.
- [ ] Invalid/failing LLM outputs end in safe retry/`ABSTAIN` behaviour.
- [x] Same frozen fixture input/provider/prompt/model configuration is cache-reproducible.
- [x] Controller output is deterministic for a fixed validated state.
- [x] Agent integration tests pass with mocked provider responses and blocked sockets (180 Phase 5 tests, including batch/budget/input/review checks).
- [ ] Accepted-generation inputs and genuine provider outputs pass an auditable historical pilot without exposing outcomes to agents.
- [ ] Human source-support and classification evaluation is completed with at least 50 annotations and honest error/coverage reporting.
- [ ] Scheduled and skipped denominators are retained; no subset result is represented as a whole-cohort Full-System result.
- [ ] Freeze the actual provider/prompt/graph/controller identities before later final-test authorization.

---

## P6 — Backtesting framework, experiment freeze and final evaluation

Status: **IN PROGRESS**, authorized on 2026-10-11 for an isolated, synthetic
event-level slice on `phase6/shared-simulator`, in parallel with Phase 5 batch
infrastructure. The next authorized fixture slice adds the capability ladder,
coverage-aware event reports and immutable manifest verification. See DECISIONS
sections 30-32 and `docs/BACKTEST_RUNBOOK.md`.
Implementation does not run genuine historical economics, integrate unfinished
v2 outputs or open 2024-2025 outcomes. Production execution policy remains
DRAFT; fixture scenarios are not an execution-cost freeze.

### Build before final-test unlock

- [x] Implement the common event execution engine on synthetic inputs.
- [x] Verify synthetic five-rung selection, with independent A/B filters and Full as a subset of B.
- [-] Implement accepted historical input/prediction/controller adapters for all five variants. Generation-bound input/prediction/label adapters, the outcome-free selection inventory and the frozen-only execution path are implemented and fixture-tested (Decision 34). Acceptance on the official snapshot is pending; Full System stays NOT_RUN until P5 supplies an accepted controller generation.
- [x] Implement beta-weighted entry construction with frozen share units until exit.
- [x] Implement close-signal / next-open execution convention.
- [x] Implement convergence, adverse-stop and timeout exits.
- [x] Implement twelve predeclared fixture transaction-cost/borrow scenarios; freeze production assumptions separately.
- [x] Implement explicit fixture turnover/borrow accounting and 10/20/30-session horizon support; production policy remains DRAFT.
- [x] Implement event-level MAE/MFE/holding/return metrics, with separate partial excursions for unpriced paths.
- [x] Implement secondary fixture fixed-share portfolio simulation, cash/NAV/exposure/turnover accounting and missing-valuation refusal.
- [x] Implement fixture predictive/calibration metrics on the fresh forecasting population.
- [x] Implement fixture agent/controller metrics with scheduled coverage and explicit veto/deferral distinctions.
- [x] Implement fixture common-data and coverage-aware adjacent-rung comparisons, separate from selected intersections.
- [ ] Verify accepted historical predictive, controller and common-data comparison outputs.
- [x] Implement fixture robustness slices by year, pair, sector, divergence sign, admissible stress context, event type/materiality and cost assumptions, retaining UNKNOWN.
- [x] Implement fixture paired-month economic bootstrap and leave-one-pair/sector-out diagnostics; intervals require twelve contributing months per estimand.
- [-] Verify accepted historical portfolio, robustness/cost and economic uncertainty outputs under frozen production policies. Implemented inside the accepted experiment and fixture-verified (Decision 37); the robustness slice boundaries await owner approval and the acceptance run waits for the official snapshot.
- [-] Implement accepted historical experiment manifest and immutable result persistence. Implemented and fixture-verified (Decision 36: accepted-only `historical-experiment`, content-addressed artifacts, independent replay via `verify-historical-experiment`); the acceptance run on the official snapshot is pending.
- [x] Verify the fixture-only ladder manifest, complete row inventory and fresh deterministic replay.
- [x] Implement the immutable fixture analysis bundle and independent replay of all eighteen bound artifacts.
- [-] Freeze methodology/config/model/prompt/policy/execution assumptions. The production execution policy, its 24-variant sensitivity set and the 0.30 common A/B trading threshold are frozen (Decision 35; `configs/phase6_execution.json`, `configs/phase6_execution_sensitivities.json`). Controller/prompt identities (P5), the official-snapshot diagnostics re-run and the accepted experiment manifest remain open.

The first slice covers the event engine and fixture artifacts. The second
slice adds synthetic five-rung selection, labeled event reporting, common-data
versus selected-intersection comparisons and explicit agent coverage. Actual
historical generation binding remains a separate gate. The third slice adds fixture
portfolio accounting, sensitivity grids, robustness and economic uncertainty.
Canonical v2 forecast chronology, logistic B-both primary
and paired quarter-block reports remain unchanged.
The previous combined Phase 5/6 slice passed 381 tests with sockets blocked:
180 Phase 5 and 201 Phase 6 (75 simulator, 57 ladder, 32 reporting and 37
experiment checks). The earlier simulator slice had 255 combined tests.
Repository lint/formatting, strict typing and lockfile checks pass. The console
ladder preserves all 14 synthetic rows, independently verifies its manifest and
replays with the same immutable identity. These are engineering checks;
genuine economic acceptance and hosted checks on the expanded branch commit
remain separate. The analysis adds 95 checks (36 portfolio, 37 robustness/uncertainty,
11 cost and 11 immutable analysis checks), bringing Phase 6 to 296.
After integration the current Phase 5/6 slice passes 514 checks with sockets
blocked (218 Phase 5 and 296 Phase 6). The console analysis independently verifies
all eighteen bound artifacts and repeats with the same immutable identity.

### Final-test lock gate

- [ ] Generate and review a freeze manifest.
- [ ] Confirm all validation-driven decisions are closed.
- [ ] Require explicit user approval / unlock flag before producing headline 2024-2025 outcome metrics.

### Final run after explicit unlock

- [ ] Run Baseline 0.
- [ ] Run Baseline 1.
- [ ] Run Model A.
- [ ] Run Model B.
- [ ] Run Full System.
- [ ] Persist headline metrics, event/trade rows, matched-subset comparisons and robustness artifacts immutably.
- [ ] Do not retune after viewing final-test results; any methodological change creates a new explicitly labelled experiment.

### Acceptance gate P6

- [ ] Every reported number traces to experiment/event/trade rows and a manifest.
- [ ] All variants share identical execution and cost assumptions except for the capability intentionally added at each rung.
- [ ] Predictive, agent-risk-control and simulated economic claims are clearly separable.
- [ ] Coverage/sample counts accompany metrics.

---

## P7 — Full Streamlit research application

### Build

- [ ] Complete Scanner page.
- [ ] Complete Pair Detail page with spread/relationship diagnostics.
- [ ] Add calibrated Model A/Model B probability context and SHAP explanations.
- [ ] Add evidence timeline, source provenance and expandable cited chunks.
- [ ] Add agent cases, validation state, break-risk and controller reason codes.
- [ ] Complete Strategy Lab with five-rung comparison, equity/drawdown curves, predictive diagnostics, rejected-trade analysis and robustness controls.
- [ ] Complete Model & Data Monitor with data/source health, model versions, coverage, feature distribution/time-slice diagnostics, agent failure and abstention rates.
- [ ] Complete Methodology / Model Card page.
- [ ] Implement presentation/service caching keyed by scientific version identifiers.
- [ ] Add controlled empty/loading/error states.
- [ ] Ensure ordinary app use does not mutate canonical analytics.

### Acceptance gate P7

- [ ] Five core pages render from a frozen demo snapshot without live network or LLM access.
- [ ] Selected showcase investigations may optionally run live but fail safely to cached/demo behaviour.
- [ ] No scientific/business logic is duplicated in Streamlit page code.
- [ ] All displayed model/decision/evaluation values expose data/model/policy as-of/version context.

---

## P8 — Hardening, reproducibility and deployment handoff

### Build

- [ ] Complete unit/integration/leakage/regression/app-smoke test suites.
- [ ] Ensure CI passes on a clean clone without external APIs.
- [ ] Finalise demo snapshot packaging.
- [-] Prepare the offline group snapshot and setup/app/prediction/backtest-input commands;
  tooling and fixture checks are on `collaboration/portable-research-snapshot`.
  Export and fresh-workspace checks with the real bundle await accepted v2 outputs.
- [ ] Finalise model card, data dictionary, README and technical runbook.
- [ ] Document all commands for bootstrap, migrations, data build, model training, agent batch, backtest, demo packaging and Streamlit launch.
- [ ] Add deployment config for Streamlit Community Cloud or approved equivalent.
- [ ] Verify secrets never enter Git/logs/fixtures/screenshots.
- [ ] Tag/version the reproducible submission build.

### Acceptance gate P8

- [ ] A new contributor can clone, install, initialise, load/rebuild the permitted project snapshot, run tests and launch the demo from documentation only.
- [ ] Demo works when live data and LLM providers are unavailable.
- [ ] No live brokerage/order execution exists.
- [ ] Repository contains everything needed for the user to prepare the final academic report/video from reproducible outputs.

---

## Suggested milestone tags

```text
v0.1-foundation
v0.2-data
v0.3-econometrics
v0.4-model-a
v0.5-model-b
v0.6-agents
v0.7-evaluation
v0.8-app
v1.0-submission
```

## Definition of implementation complete

Implementation is complete when P0-P8 have passed, the frozen five-stage evaluation is reproducible, the Streamlit demo operates from a frozen snapshot, every final decision is traceable to quantitative state and admissible evidence, and a clean environment can reproduce the submitted research state without relying on hidden notebooks/manual spreadsheet edits.

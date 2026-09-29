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

Status: verification in progress; see `docs/STATUS.md`.

### Build

- [x] Create the repository skeleton from the Software Engineering specification.
- [x] Add Python 3.11, `pyproject.toml`, `uv.lock`, `.python-version`, `.env.example`, `.gitignore`.
- [x] Keep the canonical agent-facing Markdown specifications under `docs/specs/`; PDFs may remain under `docs/PDFs/` as archival/human-readable copies.
- [x] Implement typed configuration loading for universe, data, econometrics, ML, agents, decision, backtest and app settings.
- [x] Implement structured logging and run IDs.
- [x] Implement the canonical directory resolver from `docs/DECISIONS.md`.
- [x] Create DuckDB SQL migrations and schema/version registry.
- [x] Implement DuckDB, Parquet, document, artifact and run-registry storage helpers.
- [x] Add deterministic tiny fixtures.
- [x] Configure Ruff, mypy, pytest and GitHub Actions.

### Acceptance gate P0

- [-] Fresh clone + `uv sync --frozen` succeeds.
- [x] Fresh `data/analytics/structural_break.duckdb` can be created entirely from migrations.
- [x] Read/write storage fixture test passes.
- [-] CI passes without network or LLM access.
- [x] No scientific logic is trapped in Streamlit/notebooks.

---

## P1 — Data ingestion, reference data and lineage

### Build

- [ ] Encode the fixed 28-pair universe and orientation from `docs/DECISIONS.md` in versioned reference/config data.
- [ ] Build `security_master`, including ticker, CIK, issuer, sector/sub-industry, sector ETF, lifecycle fields and manual-review status.
- [ ] Implement Yahoo/yfinance daily OHLCV/actions bootstrap beginning 2014-01-01.
- [ ] Ingest SPY and required sector ETFs under the same market-data contract.
- [ ] Ingest official Cboe VIX history.
- [ ] Ingest SEC ticker-CIK mapping and company submissions metadata.
- [ ] Normalize SEC filing index with acceptance timestamps.
- [ ] Implement immutable raw snapshots, source manifests and SHA/hash lineage where specified.
- [ ] Build canonical curated Parquet datasets.
- [ ] Register DuckDB views/tables and data snapshot metadata.
- [ ] Implement data-quality checks: keys, duplicates, monotonic dates, positive prices, missingness, calendar alignment, source freshness, timestamp validity.
- [ ] Implement optional news adapter only as non-headline current/demo enrichment; it must remain disabled for headline historical experiments.

### Acceptance gate P1

- [ ] One command/job sequence reproduces a frozen market + reference + SEC-index data snapshot.
- [ ] Every curated row has source/data lineage.
- [ ] No forward-filled missing equity prices across missing/non-trading observations.
- [ ] SEC acceptance timestamps are stored and queryable.
- [ ] Historical app/data queries can run without network access after ingestion.

---

## P2 — Econometric Relationship Engine and signal state

### Build

- [ ] Align pair price histories and apply log-price transforms.
- [ ] Implement ADF/KPSS integration diagnostics according to the econometric specification.
- [ ] Implement fixed-orientation 504-day Engle-Granger estimation.
- [ ] Use appropriate Engle-Granger/MacKinnon cointegration outputs.
- [ ] Store alpha, beta/cointegration vector, formation spread moments and diagnostics.
- [ ] Implement monthly point-in-time re-estimation with next-session effective timestamps.
- [ ] Compute daily out-of-sample spread/z-score from frozen monthly parameters.
- [ ] Compute half-life and relationship-stability diagnostics.
- [ ] Implement `ACTIVE` / `WATCH` / `RETIRED` lifecycle logic.
- [ ] Produce daily pair-state history.
- [ ] Produce raw fresh threshold crossings for Baseline 0 where a current spread is estimable.
- [ ] Produce econometrically valid fresh threshold crossings for downstream ML/Baseline 1.

### Acceptance gate P2

- [ ] Synthetic known-stationary/cointegrated fixtures behave as expected.
- [ ] Monthly snapshots never use future observations.
- [ ] Daily signal rows always join to the latest effective historical snapshot, never a future snapshot.
- [ ] Same frozen input/config regenerates identical snapshot/event IDs.
- [ ] Several representative pairs are manually inspected against stored diagnostics/plots.

---

## P3 — Divergence dataset, Model A and minimal app shell

### Build

- [ ] Generate one divergence event per episode with de-duplication.
- [ ] Construct binary labels using the frozen convergence/stop/horizon policy.
- [ ] Implement censoring and 10-trading-day partition embargo.
- [ ] Build point-in-time quantitative Model A features:
  - spread state;
  - relationship quality;
  - market context;
  - security state;
  - liquidity / implementation.
- [ ] Build deterministic event/feature/target schemas and lineage.
- [ ] Create chronological train/validation/final-test partitions.
- [ ] Train the logistic benchmark.
- [ ] Train/tune XGBoost Model A using training/validation only.
- [ ] Calibrate Model A probabilities using validation data.
- [ ] Freeze Model A candidate threshold using validation policy.
- [ ] Save/load model bundle, calibrator, feature schema and SHAP reference data.
- [ ] Implement Model A inference and SHAP outputs.
- [ ] Create a minimal read-only Streamlit shell with Scanner and Pair Detail backed by services/fixtures or current quantitative outputs.

### Acceptance gate P3

- [ ] Leakage tests pass for every quantitative feature.
- [ ] Event counts and labels are reproducible.
- [ ] Train/validation/embargo counts are documented.
- [ ] Logistic and Model A metrics are available for training/validation without opening headline final-test results.
- [ ] Saved Model A reproduces stored inference probabilities after reload.
- [ ] Minimal Scanner/Pair Detail render without model training inside UI callbacks.

---

## P4 — Point-in-time SEC event intelligence and Model B

### Build

- [ ] Implement event-specific SEC evidence selection using only filings accepted at/before event cutoff.
- [ ] Lazily download/cache required filing bodies and exhibits by accession number.
- [ ] Parse/clean SEC documents while retaining provenance.
- [ ] Chunk and index documents with stable chunk IDs.
- [ ] Implement deterministic admissibility filtering before relevance ranking.
- [ ] Implement local lexical retrieval; optional semantic reranking only if it does not become a dependency for correctness.
- [ ] Build bounded evidence packs.
- [ ] Implement schema-constrained catalyst extraction from admissible SEC evidence.
- [ ] Persist structured event features and evidence IDs.
- [ ] Create Model B feature schema = Model A + structured event block.
- [ ] Train/tune/calibrate Model B under the same chronological protocol as Model A.
- [ ] Freeze Model B threshold using validation data.
- [ ] Save Model B artifacts and SHAP outputs.
- [ ] Implement extraction/Model-B caches and mocked extraction fixtures for CI.

### Acceptance gate P4

- [ ] Every non-`NONE` structured catalyst has admissible evidence IDs.
- [ ] Every supporting SEC timestamp is `<= event_timestamp`.
- [ ] `NONE` is distinguishable from retrieval/coverage `UNKNOWN`.
- [ ] Model B can be rebuilt from stored structured event features without re-calling an LLM.
- [ ] Model A vs Model B validation comparison is reproducible.
- [ ] Missing event evidence cannot silently remove difficult observations from evaluation; coverage flags are explicit.

---

## P5 — Multi-agent structural-break investigation and decision controller

### Build

- [ ] Implement typed LangGraph/shared state.
- [ ] Load Model B quantitative state before advocate reasoning.
- [ ] Feed both advocates the same admissible evidence and structured extraction.
- [ ] Implement Mean-Reversion Advocate.
- [ ] Implement Structural-Break Advocate.
- [ ] Run advocate nodes independently/in parallel before synthesis where supported.
- [ ] Implement Risk/Validation Agent for citations, timestamps, contradictions, source support, coverage and mandate compliance.
- [ ] Implement validated break-risk synthesis.
- [ ] Implement deterministic decision controller and reason codes.
- [ ] Implement explicit `CANDIDATE`, `REVIEW`, `NO TRADE`, `ABSTAIN` semantics.
- [ ] Implement timeouts/retries/schema validation/fail-safe abstention.
- [ ] Cache agent outputs by event/source/prompt/graph/model version.
- [ ] Build human-labelled NLP/agent evaluation subset workflow.

### Acceptance gate P5

- [ ] No agent can alter stored econometric or ML values.
- [ ] Material claims resolve to valid evidence IDs and historical timestamps.
- [ ] Invalid/failing LLM outputs end in safe retry/`ABSTAIN` behaviour.
- [ ] Same frozen event/source/prompt/model configuration is cache-reproducible.
- [ ] Controller output is deterministic for a fixed validated state.
- [ ] Agent integration tests pass with mocked provider responses and no network.

---

## P6 — Backtesting framework, experiment freeze and final evaluation

### Build before final-test unlock

- [ ] Implement one execution engine shared by all five variants.
- [ ] Implement beta-weighted long/short pair construction.
- [ ] Implement close-signal / next-open execution convention.
- [ ] Implement convergence, adverse-stop and timeout exits.
- [ ] Implement transaction-cost and short-borrow assumptions and sensitivity grids.
- [ ] Implement event-level MAE/MFE/holding/return metrics.
- [ ] Implement secondary portfolio simulation and exposure/turnover accounting.
- [ ] Implement predictive/calibration metrics.
- [ ] Implement agent/controller metrics.
- [ ] Implement common-subset and coverage-aware adjacent-rung comparisons.
- [ ] Implement robustness slices by year, pair, sector, divergence sign, market-stress context, event type/materiality and cost assumptions.
- [ ] Implement block-bootstrap / pair-concentration uncertainty analyses specified in `docs/specs/05_BACKTESTING_EVALUATION.md`.
- [ ] Implement experiment manifest and immutable result persistence.
- [ ] Freeze methodology/config/model/prompt/policy/execution assumptions.

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

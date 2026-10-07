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

Status: complete; all P0 acceptance gates passed. See `docs/STATUS.md` for evidence.
Stopped at the P0 boundary; P1 requires a separate instruction.

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

- [x] Fresh clone + `uv sync --frozen` succeeds.
- [x] Fresh `data/analytics/structural_break.duckdb` can be created entirely from migrations.
- [x] Read/write storage fixture test passes.
- [x] CI passes without network or LLM access (Windows, Linux and Colab bootstrap).
- [x] No scientific logic is trapped in Streamlit/notebooks.

---

## P1 — Data ingestion, reference data and lineage

Status: complete; all P1 acceptance gates passed on 2026-10-03. See `docs/STATUS.md`
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

Status: complete; all P3 acceptance gates passed on 2026-10-03. See `docs/STATUS.md`
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
`docs/STATUS.md` for the genuine partial extraction pilot, stored-model replay,
paired validation limits and Windows/Linux/Colab evidence. Stopped at P4.
Final-test outcomes remain locked; P5 has not begun.

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

Status: implementation and source capture in progress; no expanded predictive
improvement result has been established. The original P4 acceptance remains valid.

- [x] Freeze the business-peer roster, orientations and development-only protocol.
- [x] Capture and independently reconstruct 2004–2023 market sources for 250 issuers.
- [x] Capture and independently reconstruct SEC metadata for the frozen issuers.
- [x] Implement resumable per-pair causal registries for 10/20/30-session horizons.
- [x] Implement guarded free Gemma and pinned local FinBERT adapters.
- [x] Implement metadata/tone/catalyst ablations on matched quantitative cohorts.
- [x] Implement forward tuning, independent calibration and paired assessment replay.
- [x] Pass the complete offline pipeline and original regression suite at frozen revision `2dd54bcb` (PR hosted run `37575503287` and branch run `37575496575` both green, including the quality/reporting/memory amendments).
- [x] Verify the SEC v3 envelope, canonical 250-inventory SGML gate, balanced catalyst schedule, zero-network source-v3 replay and genuine pinned FinBERT SEC-text smoke.
- [x] Generate the complete expanded development event registry (all 736 pairs completed successfully).
- [x] Complete research-only raw/calibrated log loss, balanced losses and descriptive subgroup reporting/replay (Ruff/mypy, 28 unit checks, four model integration checks and both new hosted runs passed).
- [x] Verify the separately versioned FIT-input FinBERT quality-v2 amendment (production tokenizer receipt, exact 19-record legacy replay and genuine CPU/cache smoke passed; policies/proofs/caches preserved and post-cohort timing disclosed).
- [x] Verify the science-identical compact evidence-union memory change (100 focused checks, whole Ruff/133-file format, mypy/66-source and final four-model integration checks passed).
- [x] Commit/freeze the amended code at `2dd54bcb`, launch the new immutable batch at 2026-10-07 05:17:15 UTC, freeze its inputs during guarded startup before event processing and pass fresh hosted CI.
- [ ] Generate genuine SEC text features and disclose inference/source coverage (legacy stop cause unknown; quality first attempt failed on the repaired orphan inventory; resume 1 deliberately stopped during old-prefix replay at 09:40:28 UTC, preserving all 1,494 files; new full 37,421-event `development_primary_v2` launch pending, Gemma capped at 500).
- [x] Implement and verify the operation-local parsed-frame cache (128 RAM entries plus private spill): 95 focused checks and all 18 actual source-only forced-eviction pack comparisons passed; a fresh verifier-style cache independently parsed eleven inputs. Four native integration checks (128.76 seconds), Ruff/142-file format and default mypy/77-source-script-app also passed; whole-job gain is unmeasured.
- [ ] Freeze the amended builder/new inputs and pass its exact-head CI, inventory/copy the 1,494 preserved checkpoints with an explicit receipt, independently reconstruct them, then launch `development_primary_v2`.
- [ ] Fit and independently replay primary and sensitivity A/B comparisons.
- [ ] Record actual sample counts, uncertainty and positive/negative comparison results.
- [ ] Complete whole-suite and hosted release gates for the primary readiness/app/CLI patch (49 focused readiness/CLI, 18 app and 54 SEC checks passed; default mypy for 77 source, script and app files passed; broad local pytest was cancelled, not passed; `98356bf` both hosted runs passed all six jobs; the later cache source needs its own exact-head CI).
- [ ] After all thirty actual models and native replays finish, publish checked readiness with `structural-break promote-primary --pipeline-receipt PIPELINE_RECEIPT --ci-gate CI_GATE` bound to the final completed generation, archiving the exact CI bytes.
- [ ] After actual v2 evaluation and required gates pass, promote v2 to GitHub `main` and the default app/run path, retaining v1 history and immutable artifacts for reference/reproduction.
- [x] Verify Windows/Linux/Colab compatibility for frozen revision `2dd54bcb` (both hosted runs green; full structured receipt `.acceptance/research_2dd54bc_hosted_ci.json`).

Commands and recovery rules are in `docs/RESEARCH_V2_RUNBOOK.md`.
The legacy job is confirmed stopped as of 2026-10-07 05:10 UTC. Its log ends
at 1,494 completed checkpoints at 03:33 UTC without traceback/terminal manifest;
the cause is unknown, not recorded as an intentional stop or confirmed failure.
Keep its partial directory and verified caches. The replacement used frozen
`2dd54bcb` code at process launch; its immutable inputs were published during
guarded startup before event processing, with SHA-256
`cf19099ac57ee7f5ba6ab3e37daa6d46dda49a7f4dc63893d6a06d1063f78fea`.
No actual research A/B assessment preceded the FIT-only amendment. The later
three-FIT-event source-only profile motivates the operation-local parsing
amendment in DECISIONS section 22. Its 95 focused checks and exact 18-pack
benchmark passed; full-job gain is unmeasured, and the final source/input
freeze, exact-head CI, checkpoint transition and new batch launch remain pending.

---

## P5 — Multi-agent structural-break investigation and decision controller

Research v2 is an authorized parallel experiment before P5. Its protocol and
implementation status are recorded in `docs/RESEARCH_V2_PROTOCOL.md` and above.
It does not mark any P5 gate complete or open final outcomes.

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

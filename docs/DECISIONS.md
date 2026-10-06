# AI Structural-Break Detector — Canonical Project Decisions

**Status:** implementation baseline  
**Date:** 2026-09-29  
**Purpose:** resolve cross-document ambiguity before coding begins. These decisions are intentionally concise; detailed methods remain in the agent-facing Markdown specifications under `docs/specs/`.

## 1. Authority and precedence

When implementation sources disagree, use this order:

1. Explicit user instruction in the current task.
2. `docs/DECISIONS.md`.
3. The most specific component specification in `docs/specs/` for the subsystem being implemented.
4. `docs/specs/06_SOFTWARE_ENGINEERING_ARCHITECTURE.md` for repository/runtime/integration questions.
5. `docs/specs/00_PROJECT_OVERVIEW.md` for broad product context.

Do not silently merge contradictory specifications. If a material conflict remains after applying the precedence above, stop at the affected gate and surface it.

The PDFs in `docs/PDFs/` are archival/human-readable copies and are not part of the normal coding-agent read path.

## 2. Product boundary

The deliverable is an **AI-assisted statistical-arbitrage research and decision-support application** for US-listed large-cap equity pairs.

The application:

- detects statistically unusual pair divergences;
- estimates a calibrated probability of successful mean reversion;
- extracts point-in-time company-event evidence;
- uses adversarial LLM agents to investigate structural-break risk;
- applies a deterministic controller returning `CANDIDATE`, `REVIEW`, `NO TRADE`, or `ABSTAIN`;
- simulates trades only for historical research and backtesting.

It does **not** place live orders or claim deployable alpha.

## 3. Canonical repository/runtime architecture

- Python 3.11.
- `uv` + `pyproject.toml` + committed `uv.lock`.
- Modular Python monolith.
- Streamlit frontend calling a thin Python service layer directly.
- No HTTP API boundary is required for the course build.
- Domain logic lives under `src/structural_break/`; Streamlit pages contain presentation logic only.
- Canonical analytics are written by explicit batch jobs. The app is read-oriented.
- DuckDB + Parquet are the local analytical storage stack.

## 4. Canonical physical storage layout

This is the single physical layout to implement across the repository.

```text
data/
  reference/
    security_master.parquet
    pair_universe.parquet
    sector_etf_map.parquet
  raw/
    yahoo/prices/{ticker}/{snapshot_id}.parquet
    yahoo/actions/{ticker}/{snapshot_id}.parquet
    cboe/vix/{snapshot_id}_VIX_History.csv
    sec/company_tickers/{snapshot_id}.json
    sec/submissions/{cik}/{snapshot_id}.json
    sec/filings/{cik}/{accession}/...
    gdelt/{YYYY}/{MM}/{DD}/...                 # optional current/demo enrichment
  curated/
    market/prices_daily.parquet
    market/corporate_actions.parquet
    market/market_context_daily.parquet
    evidence/sec_filing_index.parquet
    evidence/document_chunks.parquet
    evidence/news_index.parquet               # optional
  analytics/
    structural_break.duckdb
  snapshots/
    {data_snapshot_id}/manifest.json
  cache/
    dashboard/
    agent_runs/
  demo/
    structural_break_demo.duckdb
    prices_demo.parquet
    document_chunks_demo.parquet
    demo_manifest.json

artifacts/
  models/
  calibrators/
  shap/
  manifests/
  reports/
  mlflow/
```

Canonical DuckDB path:

```text
data/analytics/structural_break.duckdb
```

Cleaned external-source datasets live in `data/curated/`. Derived research entities such as relationship snapshots, divergence events, feature rows, predictions, extractions, decisions, backtest trades, and experiment metrics are canonical DuckDB analytics objects unless a component specification explicitly requires an auxiliary immutable artifact.

## 5. Fixed working pair universe

The first implementation uses **28 manually curated pairs**. Pair orientation is fixed **exactly as listed**: the first ticker is `leg_a` / the dependent `y` series in the Engle-Granger first-stage regression; the second ticker is `leg_b` / `x`. Do not run both orientations and choose the better result.

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

`pair_id` should preserve this listed orientation, e.g. `KO__PEP`. Pair inclusion does not assert cointegration; rolling econometric validity determines whether a pair is `ACTIVE` at a particular date.

## 6. Core time/data scope

- Daily end-of-day system; no intraday modelling.
- Raw market-data bootstrap begins 2014-01-01 to provide formation-window warm-up.
- Frozen research history runs through 2025-12-31.
- Training events: 2018-2021.
- Validation events: 2022-2023.
- Final test events: 2024-2025.
- Minimum embargo at partition boundaries: 10 trading days, matching the maximum label horizon.

## 7. Econometric relationship engine

- Two-variable Engle-Granger workflow on log adjusted closing prices.
- Formation window: 504 common trading days.
- Relationship re-estimation: monthly.
- Daily spread/z-score/event-state updates use the latest frozen monthly relationship snapshot.
- Initial cointegration eligibility threshold: 5%, frozen through training/validation governance.
- Pair lifecycle: `ACTIVE`, `WATCH`, `RETIRED` as specified in `docs/specs/02_ECONOMETRIC_RELATIONSHIP_ENGINE.md`.
- Event trigger working default: fresh `|z| >= 2.0` crossing.
- Success zone: `|z| <= 0.5`.
- Adverse boundary: same-side `|z| >= 3.0`.
- Maximum label horizon: 10 trading days.

## 8. Supervised ML definitions

### Model A — quantitative ML

XGBoost using only point-in-time structured quantitative features:

- spread state;
- relationship quality;
- observable market context (SPY/sector returns, VIX, realised volatility);
- security state;
- liquidity / implementation features.

Model A is calibrated on validation data and explained with SHAP.

### Model B — quantitative ML + structured event features

Model B uses the same architecture and training protocol as Model A, plus structured event features extracted from admissible historical SEC evidence, including fields such as:

- event type;
- affected leg;
- direction;
- materiality;
- relationship relevance;
- one-sided-event indicator;
- source/evidence count;
- document recency;
- extraction confidence.

The underlying raw text is **not** fed directly into XGBoost.

### Full System

The Full System uses:

1. Model B calibrated `P(revert)`;
2. the same admissible underlying SEC evidence and structured extraction;
3. the multi-agent structural-break investigation;
4. deterministic decision/risk gates.

This preserves the five-stage headline evaluation ladder:

```text
Baseline 0 -> Baseline 1 -> Model A -> Model B -> Full System
```

## 9. Historical event-evidence policy

For **headline historical Model B and Full-System evaluation**, SEC EDGAR is the canonical text source.

- Use SEC acceptance timestamps as the point-in-time availability rule.
- Recent 8-K filings and the latest admissible 10-Q/10-K provide the core evidence set according to the Data Architecture and Multi-Agent specifications.
- Historical/current news may be stored as optional enrichment, but it must not affect headline historical Model B or Full-System results unless a later explicit decision changes this policy after timestamp/coverage validation.
- Historical agent runs never browse the contemporary web.

## 10. Event extraction is shared by Model B and the agents

The point-in-time evidence pipeline branches after structured catalyst extraction:

```text
admissible SEC evidence
        -> structured catalyst extraction
             -> Model B event-feature block -> Model B P(revert)
             -> source chunks + structured extraction -> AI agents
```

The agents therefore reason over richer source text while Model B receives a compact tabular representation of the same admissible event information.

## 11. LLM provider decision

The code must remain provider-agnostic through the configured LLM abstraction layer.

- Do not hardcode a vendor or model in domain logic.
- Provider/model aliases belong in `configs/agents.yaml`.
- Credentials belong in `.env` / deployment secrets only.
- The likely initial credential is a Google/Gemma-family-compatible API key, but the exact provider/model is **not frozen yet**.
- The system must support deterministic mocked agent outputs for tests and demo fallback so development is not blocked by API availability.

## 12. Backtesting/evaluation ladder

Headline variants:

1. **Baseline 0:** fresh divergence threshold crossings in the curated pair universe, regardless of current relationship validity where an estimable spread exists.
2. **Baseline 1:** Baseline 0 plus current econometric eligibility / `ACTIVE` status.
3. **Model A:** Baseline 1 plus frozen calibrated Model A probability threshold.
4. **Model B:** Baseline 1 plus frozen calibrated Model B probability threshold.
5. **Full System:** Model B plus event intelligence, multi-agent investigation, and deterministic controller; only `CANDIDATE` is simulated as accepted.

All variants use the same execution/cost simulator. Predictive metrics, event-selection metrics, agent-specific metrics, and economic metrics are reported separately.

## 13. Final-test governance

The 2024-2025 final test is a one-time headline evaluation.

Before opening it, freeze at minimum:

- pair universe and orientation;
- label policy;
- feature schemas for Model A and Model B;
- model hyperparameters;
- calibration method;
- probability thresholds;
- evidence policy;
- agent prompts/schemas;
- decision-controller policy;
- backtest execution and cost assumptions;
- code/data/config versions.

The coding agent may build the final-test pipeline and generate final-test feature rows, but it must not inspect or optimise against headline 2024-2025 outcome/performance metrics until the project is explicitly unlocked for the final run.

## 14. Deliverable ownership

The coding agents are responsible for the complete implemented system: data ingestion, storage, econometrics, event construction, ML, NLP/event intelligence, multi-agent logic, decision control, backtesting/evaluation, tests, Streamlit application, deployment/demo packaging, technical README/runbook, and generated model/data documentation.

The user will prepare the final academic written report and presentation/video separately.

## 15. Phase 0 environment and storage implementation

- Google Colab is supported as a host for the same Python 3.11 package commands.
  `scripts/colab_bootstrap.py` uses uv to create the project environment independently
  of Colab's notebook kernel. No Jupyter packages are required by this project.
- The existing `Ai_in_Finance` Python 3.12 environment is independent and unchanged.
- Foundation dependencies install by default. The specified later-phase research,
  agent and app stacks are declared as locked optional extras. No later-phase
  implementation or model results are implied by installing these dependencies.
- Hatch's exact editable mode plus the explicit `editables` dependency avoids
  Python 3.11's locale-dependent `.pth` decoding in non-ASCII Windows paths.
- Storage paths are relative to an explicit workspace root (repository by default).
  `--workspace-root` takes precedence over `SB_WORKSPACE_ROOT`; changing deployment
  paths does not alter the normalized research configuration hash.
- Active files use a local filesystem supporting atomic replace/hard links. Colab
  uses `/content`; completed workspaces can be archived to Drive. Concurrent batch
  writers are outside the supported execution model.
- Phase 0 migrations create the four logical schemas, migration ledger and ops
  tables. Domain tables/views arrive with their owning phase and validated contracts;
  no empty downstream models or fake research outputs are introduced in Phase 0.
- SQL checksums normalize CRLF/LF only. An applied migration cannot otherwise change,
  disappear, or be reordered. New migration batches apply in one transaction.
- Source documents and versioned artifacts are immutable. Identical writes are
  idempotent; changed content under an existing identity is rejected. Replacing a
  curated Parquet file requires an explicit `replace=True` batch operation.
- Run records contain normalized settings and code/config/data identities; successful
  artifact/dataset registration and run completion share a transaction. Failed runs
  publish no registry entries. Unregistered files from interrupted jobs can be retried.
- Policy probability/break-risk thresholds and transaction/borrow assumptions remain
  explicitly unset draft values until their owning phases select and freeze them.
  P0 does not invent scientific defaults or unlock the final test.
- The archival PDF directory is currently named `docs/PDF's/`; prose references to
  `docs/PDFs/` refer to those same human-readable archives. The Markdown index lists
  `04_MULTI_AGENT_PIPELINE.md`, which was absent at P0 start. Recover/approve that
  specification before its owning implementation phase; P0 does not reconstruct it.

## 16. Phase 1 source and information-set decisions

- The user explicitly selected previous-session VIX for an equity-close signal
  cutoff on 2026-10-03. Join the exact prior XNYS session; do not include same-day
  VIX or carry forward an older missing observation. Preserve its source date and
  conservative 16:16 America/New_York observation proxy. Historical CSV publication
  times remain unknown.
- `configs/securities.yaml` implements the already approved fixed universe using
  static project sector/sub-industry proxies. This is not a vintage GICS database.
  WMT/TGT use XLP and V/MA use XLF throughout. Current exchange metadata and changes
  are audit fields; unspecified listing lifecycle dates remain null/UNKNOWN.
- Yahoo unadjusted OHLCV, adjusted close, dividends and splits are captured with
  explicit `auto_adjust=False`, `actions=True`, `repair=False`, daily interval and
  regular-session data. Retrospective vendor adjustments are a disclosed prototype
  limitation rather than a claim of historical adjustment-vintage availability.
- Frozen dataset/source identities and hashes govern reproduction. Replay preserves
  source retrieval metadata and requires matching research configuration plus a
  successfully registered, verified raw inventory. New captures use new identities.
- P1 adds source-backed `ref`/`market` views and ops ingestion/QA/active-snapshot
  tables through migration 003. The four canonical database schemas remain unchanged.
  Reader views point to immutable files; publication and registry completion share
  one transaction, with rollback of canonical latest copies on failure.
- Optional GDELT Article List timestamps have mixed/ambiguous provenance. Its
  adapter is constrained to current/demo use; publication time remains unknown,
  point-in-time eligibility is false and headline historical usage stays disabled.

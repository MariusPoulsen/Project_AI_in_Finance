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
- Training events: 2016-2021 (extended at P3 under the user's delegated decision).
- Validation events: 2022-2023.
- Final test events: 2024-2025.
- Minimum embargo at partition boundaries: 10 trading days, matching the maximum label horizon.
- 2014-2015 supply formation warm-up; the first usable frozen relationship is
  effective 2016-01-04. These warm-up years cannot independently provide events
  under the unchanged 504-session model. The former 2018 training start was a
  baseline design choice, not a source-data limitation.

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

## 17. Phase 2 estimation and publication details

- Monthly estimation uses the latest 504 valid common observations on/before the
  actual XNYS month-end. A missing estimation-day close does not create an extra
  eligibility rule; the actual formation endpoint is recorded. No filling occurs.
- ADF uses a constant and AIC; KPSS uses a constant and automatic lag selection.
  At the fixed 5% diagnostic level, I(1) compatibility requires non-rejection of
  level ADF, rejection of level KPSS and rejection of first-difference ADF.
  First-difference KPSS is stored as a cross-check, without an additional gate.
- Formation first differences omit missing-session transitions; half-life AR(1)
  uses only exact one-session lag/current pairs. Level/cointegration tests retain
  common-observation order, and difference-test lag dynamics use the retained
  available-observation order. Missing-transition diagnostics make this limitation
  explicit; it does not introduce a consecutive-history eligibility requirement.
- Engle–Granger uses the fixed A-on-B orientation and its MacKinnon outputs.
  Stability, beta drift, half-life and source zero-volume warnings remain exposed
  diagnostics. No unspecified liquidity/stability thresholds are introduced.
- The first invalid monthly attempt is WATCH, two consecutive invalid attempts
  are RETIRED. Statistical retirement can recover on a valid month. Permanent
  manual/lifecycle retirement requires a declared date; undated terminal flags
  are rejected to prevent retroactive historical eligibility changes.
- Every monthly attempt is an audit row. If the newest attempt has no usable fit,
  the next interval has no daily state; an older fit is not silently carried forward.
  Unexpected statistical errors fail the batch with pair/date context.
- Parameters become effective at the next XNYS open and remain frozen. At a refit
  boundary the previous and current close are compared under the same newly
  effective parameters. Fresh divergence/sign/velocity checks do not bridge missing
  sessions, and an exact zero touch alone is not counted as two sign crossings.
- P2 persists raw threshold crossings for any estimable spread (Baseline 0) and
  ACTIVE eligibility (Baseline 1). Episode deduplication, forward labels and trade
  outcomes belong to P3/P6. The final-test outcome lock remains closed.
- Canonical analytics are physical DuckDB tables with core SQL fields and complete
  JSON payloads, plus immutable full Parquet artifacts. Version/active-pointer/run
  publication is transactional. DuckDB does not support cross-schema foreign keys;
  same-schema relationship keys are enforced in SQL and publication owns the
  ops/analytics linkage within the transaction.
- Generation identity includes input/config/range, normalized installed Python
  source hashes and numerical library versions. Explicit version names cannot
  conceal changed computation. Scientific row IDs exclude run IDs/creation times;
  the version scopes generations. Failed unregistered files are archived for audit
  before retry; registered artifacts are verified and never overwritten.
- P2's added config defaults change the global normalized config hash. Frozen P1
  curated files remain usable directly; older raw captures require their recorded
  P1 code/config checkout for replay. This preserves the original source freeze.

## 18. Phase 3 earlier history and Model A protocol

- The user delegated the earlier-history choice on 2026-10-03. Prices cover
  2014–2025, but a 504-session formation window uses 2014–2015. Extend supervised
  training from the original 2018–2021 to **2016–2021**, when valid signals first
  exist. Keep validation 2022–2023 and the locked final test 2024–2025 unchanged.
  This choice preceded inspection of the additional labels or model scores.
- Preserve the three forward evaluation years 2019, 2020 and 2021; their fitting
  histories begin in 2016. Purge any full 10-XNYS-session label window that reaches
  the evaluation year or another partition. Early convergence does not waive the
  full-window requirement. Embargo counts are sessions, not event rows.
- An event freezes alpha, beta, spread mean and standard deviation at entry for
  its full target path. A later statistical WATCH/RETIRED state does not censor
  that path; declared lifecycle termination or unusable required prices does.
  Success is an observed close within |z| <= 0.5, adverse failure when entry-sign
  times z >= 3,
  otherwise failure at ten sessions. A sign-changing jump across equilibrium
  without an observed close in the success band is not convergence.
- Maintain one open episode per pair, then require an inside-entry-band reset
  before a fresh outward crossing. The same causal, session-by-session registry
  applies to development and final features. Final episode gating may use prices
  already observed at that session; final labels, resolution metadata, excursions,
  censor reasons and outcome metrics remain absent/NULL. No final outcomes are
  supplied to fitting or threshold decisions.
- Compute rolling spread predictors under the event's current frozen fit, so
  monthly coefficient changes do not introduce artificial velocity. Use exact
  trailing sessions and no gap filling. Undefined half-life, beta drift and time
  since an observed equilibrium are explicit optional NaNs; other undefined
  required predictors make the event ineligible. Each feature family records
  source availability and its cutoff; previous-session VIX remains mandatory.
- Model A and the logistic benchmark use the identical 36 quantitative columns.
  Identity and outcome fields remain metadata. Fit logistic imputation/scaling
  only within each fitting period; XGBoost retains permitted missing values.
  Search 30 seeded XGBoost configurations in the specified parameter ranges.
  Report undefined one-class/empty folds. Select by mean defined ROC AUC, then
  mean defined PR AUC, then lower Brier; all-undefined ranking falls back to Brier.
  Do not conceal unusable folds.
- Fit a monotone Platt sigmoid on all 2022–2023 eligible validation events,
  as specified. Smoothed targets and a nonnegative slope prevent inverted or
  separation-driven mappings. One-class/constant-score fits save an explicitly
  constant mapping. Calibrated validation metrics are **calibration-fit descriptive**;
  they are not an untouched assessment of probability generalisation.
- Freeze the specified **0.65** candidate probability threshold. The small
  validation sample does not justify optimising precision or adding an arbitrary
  minimum-coverage gate. Report the specified threshold grid descriptively, with
  counts/undefined metrics and uncertainty. This policy is predeclared, not
  empirically optimal. No positive-beta trading gate is added in P3.
- Tree SHAP explains raw XGBoost margins and verifies additive reconstruction.
  Calibrated probabilities have a separate mapping; SHAP is not presented as a
  calibrated-probability contribution or a causal explanation.
- Batch jobs publish immutable event/model artifacts and physical DuckDB core
  tables plus full JSON payloads. Registration, active pointers and run completion
  share a transaction. Verify manifests, every file and upstream version/checksum
  before reading. Frozen P2 outputs are reused when only downstream ML settings
  change; new ML source/config identities create new event/model versions.
- MLflow uses a local SQLite tracking database and local artifact directory,
  without an HTTP service. DuckDB remains the canonical analytical database.
  Research/app dependencies now install by default; the matching extra names are
  retained as compatible aliases. The lock constrains compatible Numba releases
  for the declared Python 3.11/NumPy stack.
- The P3 Streamlit shell browses Scanner and Pair Detail using read-only services,
  published scores and stored SHAP. It neither trains nor writes analytical rows.
  Historical probability replays display their fitting/evaluation role and the
  final outcome lock caps UI dates at 2023. P5 controller/trading status is absent.

## 19. Phase 4 evidence, extraction and Model B protocol

- Use the unchanged P3 event population, quantitative features, targets and splits.
  Model B adds 31 fixed event columns (67 total), using MEDIUM as the specified
  materiality category. Extraction schema, prompt and event-feature versions are
  v2. Missing/failed evidence remains explicit UNKNOWN on the original cohort.
- Select recent 8-K/8-K/A over 30 calendar days, most recent admissible periodic
  10-Q/10-K within 180 days with a 400-day extension, and associated admissible
  periodic amendments. Filter by issuer, type and SEC acceptance before lexical
  ranking. Eight chunks per leg and 32,000 characters bound each pack. PDF-only
  exhibits remain explicitly unsupported; a bounded pack is not exhaustive issuer
  knowledge. NONE requires complete selected coverage and means no supported
  catalyst in that evidence set, not proof that the company had no event.
- Preserve raw responses, source/cleaned-text hashes, stable chunks, complete
  original pack JSON, allowlisted extraction inputs and exact extraction JSON.
  The normalized extractor evidence hash and richer original pack hash have
  different contents and both are retained. Verified reads reparse raw files,
  regenerate selection/packs, validate responses/citations and rebuild features.
- Nonempty catalyst categories require exact quotes from admissible chunks, with
  leg/security, timestamp and category-cue checks. Qualitative direction,
  materiality and relevance still require human semantic evaluation. Self-reported
  confidence is uncalibrated extraction certainty, not measured correctness or
  reversion probability. Human-labelled evaluation belongs to P5.
- The user selected a free Gemini Flash API on 2026-10-03. Its locally verified
  working model alias is gemini-3.5-flash, after the initial stable 3.8 candidate
  returned repeated HTTP 503 capacity errors. Both support the free standard API;
  provider/model remain configurable. No billing
  is enabled by this implementation. Protect the pilot with 20 requests including
  retries, a 32-second interval and no hidden SDK retries. Quota/authentication
  failures stop additional requests for that batch; all remaining rows stay
  UNKNOWN. Request order is validation, training years in chronological round-
  robin, then final feature rows, without consulting labels or scores. Partial
  pilot coverage cannot establish a completed representative NLP study.
- Successful/NONE extraction caches are immutable. Explicit new jobs may retry
  UNKNOWN and publish a new generation when validated responses change. SEC
  response caches retain failed originals; an explicit retry-attempt identifier
  creates another accession response inventory. These operations never mutate
  old registered evidence or Model A artifacts.
- Recover historical XOM through reviewed predecessor CIK 0000034088 until
  2026-06-30, successor 0002115436 from 2026-07-01, and a supplemental source
  manifest/raw capture. Keep the P1 freeze intact. Administrative mapping recovery
  changes neither pair orientation nor the existing event population.
- Model B uses the identical logistic/XGBoost fitting/search/calibration/0.65
  threshold protocol as A and binds a fitted A from the same P3 parent. All
  eligible validation rows remain in the paired comparison; coverage slices are
  descriptive additions. Native reload, SHAP and stored A/B comparison are
  independently reproducible without LLM calls. Final outcomes remain locked.
- Each Model B verification command pins its model/evidence/event/A inputs and
  performs full SEC scientific reconstruction once, then reuses verified in-memory
  frames for reload and paired comparison. Fresh training loads frames from its
  already verified evidence manifest. This removes redundant full SEC audits
  within an operation; separate
  public reads still verify all hashes, source reconstruction and scientific
  content afresh. No persistent verification cache or public bypass is introduced.
- Calibration retains the same smoothed monotone Platt objective and constraints.
  A reproduced L-BFGS-B abnormal termination near a stationary solution justifies
  a numerical SLSQP retry on that identical objective. Accept only finite feasible
  solutions at least as good as the constant baseline and independently stationary
  under per-observation, unit-variance KKT checks. A solver failure never silently
  substitutes an empirical prior for an identifiable two-class fit.
- The sample adequacy proposal in RESEARCH_REDESIGN.md is a separate unimplemented
  protocol. Do not expand the universe, relax eligibility, lengthen labels or
  alter evaluation in this canonical experiment to manufacture more successes.

## 20. Delegated research v2 redesign

- On 2026-10-06 the user authorized implementation and scientific design of the
  redesign with the aim of improving Model B over matched Model A. The original
  Phase 4 experiment remains an immutable reference. The authorized new protocol
  is `configs/research_v2.yaml` and `docs/RESEARCH_V2_PROTOCOL.md`, frozen before
  computing added development labels. No 2024–2025 outcome unlock is granted.
- Freeze 250 current-survivor domestic issuer candidates in 40 documented peer
  groups, 736 fixed pairs including the original 28 orientations. Business-group
  selection precedes outcomes. Historical identity floors constrain admissibility;
  observed price start/end dates are source coverage, not legal listing dates.
  This free Yahoo/SEC study remains survivor-conditioned and uses retrospective
  vendor adjustments; it is not a delisting-complete investable universe.
- Capture 2004–2023 development prices. The primary population is deduplicated
  estimable crossings, with actual ACTIVE status retained for separate assessment.
  This forecasting population does not silently alter the canonical ACTIVE-only
  trading ladder or authorize trades in ineligible relationships.
- Predeclare a primary 20-session target and 10/30-session sensitivity registries.
  Entry/success/adverse boundaries remain 2/0.5/3; entry coefficients, episode
  reset, censoring and full-window embargo remain causal. Fit through 2019, tune
  on expanding 2018/2019 folds, calibrate on 2020–2021 and assess on 2022–2023.
  Purge both fitting and annual assessment tails using complete label windows.
- Use strongly regularized logistic A/B as the primary research estimators, plus
  identical-budget small-grid XGBoost comparisons. A uses quantitative features;
  B adds predeclared SEC metadata, local FinBERT tone and guarded Gemma catalysts.
  Report all ablations and failures on exactly the same quantitative registry,
  including UNKNOWN source/inference rows. No assessment-based choice of winner,
  horizon, universe, threshold, or favorable companies is permitted.
- Reserve Flash for later reasoning agents. FinBERT weights/revision and text
  window preprocessing are versioned; its 2020 release is a disclosed retrospective
  extractor limitation for earlier observations. SEC text acceptance/issuer/quote
  admissibility remain required independently of model training date. Gemma is
  free only, locally schema/quote validated, paced, budgeted and quota-stopped;
  failures stay UNKNOWN. Provider thought-channel metadata is excluded from the
  required sole final JSON answer, without coercing that answer.
- Use a separate `data/research_v2` workspace and DuckDB database with immutable
  source/pair/evidence/model generations. Preserve every attempted source/pair
  and disclose selection/coverage/exclusion funnels. Temporal-block paired loss
  intervals retain shared-issuer events; few blocks and cross-quarter dependence
  limit confidence. Forecast improvement is not a claim of economic profitability.
- Before actual research Model B fits, prepare `sec-json-clock-envelope-v3`:
  absent/zero-offset SEC JSON acceptance values retain UTC and New York
  wall-clock candidates plus the inverse UTC-to-New-York-wall-clock candidate
  observed from source lag; only the upper bound admits evidence. V3 widens
  the v2 lower bound while preserving its conservative upper bound. Explicit
  nonzero offsets stay exact. Missing times are UNKNOWN, never recovered from
  filing dates. Relevant intervals straddling the cutoff or 30/180/400-day
  evidence boundaries keep coverage UNKNOWN. Among 250 matched cached captures
  with hash-verified SGML source headers, 186 JSON values matched; 49 JSON `Z`
  values were themselves four hours later and 15 five hours later. This is
  source timestamp lag, not solely a naive parsing issue; none was premature
  in this sample. This is not a full audit of 89,657 source-v1 filings. Preserve
  source_v1 and original Phase 4. The successful metadata-only source-v2 replay
  remains immutable; its interval excluded those 64 SGML headers below its
  lower bound. It is not full evidence admissibility acceptance. Derive a
  separate source_v3 from the exact source-v1 raw response inventory, frozen
  code and zero HTTP requests; actual B fitting must bind the corrected,
  validated source and inference pipeline.
  Source-v3 metadata replay completed at frozen `100e1e48`, retaining all 735
  response identities, 250 complete issuers and 89,657 filings. Its upper bound
  is unchanged for every filing. The subsequent canonical replay passed for
  250 cached accession inventories: all sampled official SGML headers fall
  within the v3 envelope, with original body/retrieval identities preserved
  and zero HTTP calls. Genuine pinned CPU FinBERT inference on V/MA SEC text
  at 2016-01-08 also passed: six chunks, 210 windows, exact cache replay and
  no LLM/network/final-outcome access. These are engineering gates, not full
  historical feature coverage or evidence of predictive improvement.
- A separate `--catalyst-max-events 500` pilot balances declared year/business-
  group strata without outcomes or scores while metadata/FinBERT may cover the
  full registry. Unscheduled Gemma rows stay UNKNOWN; disclose coverage and all
  ablations. `--max-events` continues to identify a partial text-source batch.
  Hosted CI `3c01d262` passed the committed schedule/v2 guards on Windows,
  Linux and Colab. The subsequent v3 envelope/source replay, canonical
  250-inventory SGML gate and genuine FinBERT smoke passed separately at
  `100e1e48`. Hosted CI for `100e1e48` then passed the complete Windows/Linux
  regression jobs and Linux Colab bootstrap in
  [run 37451417275](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37451417275).
  Those checks cover their own committed revision; the quality/reporting/memory
  amendment subsequently froze at `2dd54bcb` and passed both new hosted runs.
  As of 2026-10-07 05:10 UTC, legacy batch `development_v3_100e1e4` is
  STOPPED and incomplete: its session/process are absent and its log ends at
  1,494 completed checkpoints at 03:33 UTC, without traceback or terminal
  manifest. The cause is unknown; this is not an intentional stop or a confirmed
  FAILED publication. Preserve the partial batch. New `development_quality_v2`
  first launched at 2026-10-07 05:17:15 UTC from frozen `2dd54bcb`; its distinct
  inputs froze during guarded startup before event work. That quality attempt
  exited 1 after 1,494 checkpoints with a verified `FileExistsError` from an
  unregistered SEC capture lacking its completion manifest. Complete only that
  inventory from three valid original response/sidecar pairs plus one absent
  exhibit, preserving all six original files and retrieval times. Recovery proof:
  `.acceptance/sec_orphan_recovery_000119312506199058.json`, SHA-256
  `65ab238448b5d055ca80ed771ed62cc0cc7cbe6063272eb20e8c553a874216d7`.
  Resume 1 launched at 08:58:15 UTC under identical code/inputs and is RUNNING;
  it replays the 1,494 preserved quality checkpoints. Do not attribute this
  known quality-attempt failure to the unknown legacy-stop cause. All actual
  A/B comparisons remain pending.
- Development amendment on 2026-10-06, after constructing the quantitative
  cohorts and observing their counts, but before any research model assessment:
  use separately versioned FinBERT `sec-sentence-quality-wordpiece-v2` in a new
  research evidence batch. This is not part of the initial pre-label freeze.
  The decision uses only input-quality diagnostics from 19 FIT source events
  dated 2006-01-03/04, with no outcome labels, model scores, calibration,
  assessment or final-test text read. The proof is
  `.acceptance/finbert_preprocessing_input_audit.json`, SHA-256
  `294c01de161c47ad16e06ad07ac89ae7fbf1f24ddf7c775b18b4ec97fc617855`.
  Legacy preprocessing scored 4,189 windows (median four WordPieces) and
  26,109 of 39,879 full-source tokens. The chosen exact-line quality guard plans
  1,259 windows (median 14) and retains 20,957 tokens, 52.6% of that unchanged
  raw denominator; both policies leave two of 38 issuer legs UNKNOWN. These are
  tokenizer/input diagnostics, not new neural scores, representative NLP
  validation, a measured speedup or evidence of predictive improvement.
  Production tokenizer acceptance confirms 8,292 raw physical-line windows,
  1,259 eligible/scored and 7,033 excluded; legacy has 8,720 raw newline-plus-
  punctuation windows. Both retain the same 39,879-token raw denominator.
  V2 excludes 18,922 tokens and has no budget omissions in this sample; all
  nineteen genuine legacy tone records replay exactly.
  A trimmed line qualifies with at least two alphabetic words of two or more
  characters and terminal `.`, `!` or `?` (optional closing quote/bracket), or
  at least six such words and alphabetic/(alphabetic+numeric) word ratio at
  least two thirds. Do not join lines or split punctuation within a line;
  score the first 64 eligible windows per chunk in source order.
  Preserve short sentences such as `Sales fell.` without merging table rows.
  Lexical eligibility does not establish
  narrative semantics; signature captions can remain. Preserve exact raw
  offsets, full-source token denominators and explicit partial coverage.
  Keep the domain's legacy default, prior proofs and caches immutable. Make the
  research CLI default quality-v2, with
  `--sentiment-preprocessing exact-sentence-nonoverlap-wordpiece-v1` for legacy
  reproduction; CLI choices use full version strings. Only after a new code/input
  freeze may a new batch process replacement events. Code froze at `2dd54bcb`
  before process launch; inputs froze during guarded startup before event work.
  Keep the legacy partial batch and reuse verified
  source/Gemma caches. Pair/label policies, model grids and catalyst schedule
  remain unchanged. No actual research-v2 Model B fits have occurred.
- The same amendment completes promised research reporting, without changing
  fitting or selection: all ten bundles per horizon have raw/calibrated log
  loss, pair/issuer-balanced losses and descriptive ACTIVE/year/observed-sector/
  frozen-business-group metrics, independently replayed from native models.
  Empty frozen business groups, assessment years and ACTIVE levels remain
  explicit; one-class ROC/AP stay null. Natural-log loss clips only its internal
  probability calculation at float64 machine epsilon, leaving stored scores,
  the 0.65 threshold and Brier-based tuning unchanged. Existing paired Brier
  delta slices describe observed groups.
- Optimize evidence aggregation by retaining compact per-event feature rows
  and immutable event records rather than all full source packs in the 37,421-
  event union. The FIT diagnostic extrapolates pack-only retention to 1.37 GB,
  assuming independent JSON-reloaded strings; this is not measured live RSS.
  This memory optimization must preserve the same source inventory, evidence,
  feature values, event order and matched cohort. The combined amendment passed
  100 focused sentiment/intelligence/CLI tests, whole Ruff/format checks for 133
  files, strict mypy for 66 source files and four final native-model integration
  tests in 83.74 seconds. Genuine quality-v2 CPU inference on the first ADBE/ADSK
  FIT event at 2006-01-03 passed in 31.766 seconds with exact cache replay, all
  five pinned asset hashes verified, 388 legacy cache files unchanged and no
  network/LLM/outcome access. Do not compare this timing with the different V/MA
  legacy smoke event. `development_quality_v2` launched from frozen `2dd54bcb`
  at 2026-10-07 05:17:15 UTC with all 37,421 events and a separate 500-event
  catalyst pilot; no `--max-events` or disabled inference was used. Its failed
  first attempt and preserving resume above do not alter this research scope. Its
  `inputs.json` SHA-256 is
  `cf19099ac57ee7f5ba6ab3e37daa6d46dda49a7f4dc63893d6a06d1063f78fea`.
  Both fresh hosted runs passed the amended commit. Full features and actual
  A/B fits remain incomplete; no predictive gain has been established.

## 21. Promote completed research v2 as the primary version

The user authorized completing research v2 and then replacing v1 as the primary
project version. After the full feature generation, all three predeclared model
fits, independent native replay and required acceptance gates are complete,
promote research v2 to GitHub `main` and the default app/run path. This promotion
is pending. Retain v1 history, immutable artifacts and original acceptance
results as reference/reproduction material; they will no longer be the default
research authority. Do not overwrite immutable v1 source or result generations.

This authorization changes the primary delivery path, not the frozen universe,
cohorts, model grids, evaluation protocol or final-test lock. Record measured
A/B results and their limitations, including negative or uncertain results;
Model B outperformance is not established or guaranteed by promotion.
Readiness publication uses `structural-break promote-primary --pipeline-receipt
PATH --ci-gate CI_PATH` only after the complete three-horizon pipeline receipt, source/CI gates
and fresh native verification of all thirty bundles. Publish immutable workspace
`manifest.json`/`verification_receipt.json`/`hosted_ci_gate.json` and show only accepted versions in
the read-only default app. Retain v1 at `app/reference_streamlit_app.py`.
Workspace readiness publication does not itself merge GitHub `main`.

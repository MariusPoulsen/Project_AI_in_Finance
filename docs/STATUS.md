# Implementation status

## Research v2 — authorized development redesign

Date: 2026-10-06. Branch: `research-v2`. Status: **IN PROGRESS**.
The user delegated scientific design and implementation. The expanded genuine
Model A/B comparison is pending; improvement has not yet been established.
The completed original Phase 4 artifacts and 2024–2025 outcome lock are preserved.

The frozen v2 roster contains 250 current-survivor domestic issuers, 40 business
groups and 736 fixed pairs, retaining all original 28 orientations. The primary
forecasting population is deduplicated estimable crossings with actual ACTIVE
status retained. Predeclared horizons are 20 sessions (primary) and 10/30
(sensitivities). Forward tuning is 2018/2019, independent calibration 2020–2021,
and development assessment 2022–2023. Full-window embargo applies throughout.

Observed source captures:

- Universe: `universe_880ba35c09b7997d8a7e322d`.
- Market: `market_0e7ddfd8382ca8a866f66bd1`; all 250 issuer requests and 11
  context tickers succeeded, with 1,222,930 price rows and 50,330 context rows.
  Curated equity history is 2004–2023, excluding final-test prices.
- SEC metadata: `research_sec_a26f07f21c33a8d662ab87b0`; 250 issuers and 89,657
  filing rows, with zero missing SEC acceptance timestamps. Current-CIK history
  is not proof of predecessor completeness; events before the first observed
  accepted filing retain UNKNOWN source coverage.

Implementation includes immutable/resumable pair and event generations, an
independent research database, matched logistic/XGBoost metadata/tone/catalyst/both
ablations, paired quarter-block assessment and native model/calibrator replay.
Guarded Gemma is configured for free `gemma-4-26b-a4b-it`; Flash is reserved for
P5. Local FinBERT uses the pinned ProsusAI revision and explicit token coverage.
The real CPU adapter smoke passed on synthetic SEC fixture text and exact cache
replay. A captured Gemma diagnostic final JSON passed offline validation after
excluding explicit thought-channel parts. These are adapter checks, not completed
historical NLP coverage or predictive results.

Observed local checks: Ruff lint passed; strict mypy passed for 70 source files;
all installed dependencies are compatible. The 32 focused pipeline checks passed
in 167.43 seconds, including causal two-pair registries for all three horizons,
full evidence-to-model flow, replay of ten native bundles, failed-publication
recovery, future-item exclusion and shared-cache/source tamper rejection.
The full original-plus-v2 regression run and clean hosted portability checks are
pending. See [the protocol](RESEARCH_V2_PROTOCOL.md) and
[runbook](RESEARCH_V2_RUNBOOK.md) for commands and scientific limitations.

## Phase 0 — foundation

Date: 2026-09-29. Branch: `phase-0-foundation`.

Status: **COMPLETE — all Phase 0 acceptance gates passed.**
Phase 1 is complete; its gate evidence is recorded below.

### Build evidence

- Python 3.11.16 environment, `pyproject.toml`, `uv.lock`, secrets template and Git
  exclusions. No changes to the separate course virtual environment.
- All specified domain package boundaries, source-only app directories, eight typed
  YAML configurations, canonical 28-pair orientations and normalized config identity.
- Structured JSON logging and run IDs; sensitive exception payloads are excluded.
- Canonical path resolver; DuckDB read-only reader/default and explicit writer.
- Transactional checksum-checked migrations create `ref`, `market`, `analytics`,
  `ops`, schema ledger, job runs, datasets, artifacts and source health.
- Actual Parquet/document/artifact persistence, immutable writes, run/version registry,
  fixture commands, Windows/Linux CI and Colab host bootstrap.

### Verification observed locally

- `uv sync --frozen`: passed; 179 packages resolved in the cross-platform lock,
  foundation/development dependencies installed without optional later-phase stacks.
- `uv run --frozen ruff check .`: passed.
- `uv run --frozen mypy`: passed, 26 source files.
- `uv run --frozen pytest`: **37 passed, 1 skipped**. The skipped test creates a
  directory symlink, which this Windows account cannot create; Linux CI runs it.
  Tests use `pytest-socket --disable-socket` and need no data/LLM credentials.
- Actual `init-db`: passed against a fresh canonical database.
- Actual `storage-smoke`, run twice: passed, four fixture rows per invocation;
  one immutable dataset version, separate successful run/artifact manifests.
- Tests cover rollback, migration drift/missing history, CRLF portability, read-only
  enforcement, schema/null checks, overwrite refusal, registry rollback, failed-job
  publication prevention, path confinement, config validation and log redaction.

### Clean-environment and hosted acceptance evidence

- Clean Git clone installation: passed at commit `be5f443`, in a separate directory
  and fresh virtual environment. Frozen sync, Ruff, formatting, mypy and the complete
  test suite passed (37 passed, one Windows symlink-permission skip).
- Host Python 3.12.10 → isolated Python 3.11 bootstrap: passed locally, including
  configuration validation, initialization and the four-row storage round trip.
- Hosted Windows/Linux CI and Linux Colab bootstrap: all passed on code commit
  `73378fd` in [PR CI run 36529431432](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/36529431432)
  and [branch CI run 36529428300](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/36529428300).
  Clean hosted environments perform frozen installation, configuration/migration
  checks, tests and actual repeated storage jobs. Linux also runs the symlink test.
- An actual browser-managed Colab session has not been launched from this workstation.
  The portable bootstrap and instructions are provided in `docs/COLAB.md`; hosted
  Linux CI exercises the same commands without needing Google account credentials.

### Final acceptance review

| P0 criterion | Evidence | Result |
| --- | --- | --- |
| Fresh clone + frozen sync | Independent local clone and clean hosted runners | PASS |
| Fresh database entirely from migrations | Local/CI init-db and transactional migration tests | PASS |
| Read/write fixture | Actual four-row Parquet/DuckDB/document/artifact job, rerun and failure tests | PASS |
| CI without data/LLM network access | Windows/Linux tests deny sockets; fixtures need no credentials | PASS |
| No scientific logic in UI/notebooks | Foundation logic in installed package; no notebooks or UI domain logic | PASS |
| Colab-compatible runtime | Linux Python 3.12 host bootstraps locked Python 3.11 and runs fixture job | PASS |

Python/package installation requires network access; runtime fixture tests do not.
The code is available for review in [PR #1](https://github.com/MariusPoulsen/Project_AI_in_Finance/pull/1).
No main-branch merge or Phase 1 execution is part of this completion.

### Scope and future prerequisites

No ingestion, econometrics, model fitting, LLM calls, final-test results or Streamlit
screens are claimed. Later-phase namespaces are intentional package boundaries.
The missing `docs/specs/04_MULTI_AGENT_PIPELINE.md` predates this work and must be
resolved before its owning phase. Draft policy/cost fields are explicitly unset.

## Phase 1 — ingestion, reference data and lineage

Date: 2026-10-03. Branch: `phase-1-data`.

Status: **COMPLETE — all Phase 1 acceptance gates passed. P2 is recorded below.**

### Implemented scope

- Governed 28 fixed orientations, 56 issuer identities and eight static sector proxies;
  all CIKs/issuer names joined to a frozen official SEC ticker map.
- Yahoo daily OHLCV, unadjusted/adjusted closes and corporate actions for all equities,
  SPY and required sector ETFs. No price repair, fill or missing-session return bridge.
- Official Cboe history with exact previous-XNYS-session VIX context, selected by the
  user. Market timestamps respect DST, holidays and early closes.
- SEC current submissions plus every overlapping older-history pointer. Relevant
  8-K, 10-Q, 10-K/amendment metadata preserve raw and exact UTC acceptance timestamps.
- Immutable raw files and adjacent source manifests; frozen seven-dataset Parquet
  releases with source/config/code identities, hashes, counts and actual date coverage.
- Migration 003 adds ingestion/QA/active-snapshot operations. All source-backed
  DuckDB views, active ID and successful registry completion publish transactionally;
  canonical latest copies roll back on failure.
- Offline verified replay and historical queries; tampered manifests, raw files and
  frozen Parquet reject before use. Copied workspaces rebind views through verified
  replay. Optional GDELT remains current/demo only and historically ineligible.

### Actual public-source freeze

Live capture: `snap_20261003_phase1`, 2026-10-03. Final active offline rebuild:
`snap_20261003_phase1_frozen`, curation commit `43c1851ee895c12e951eb1257ec00936a8dc3dfd`.
The captured window is 2014-01-01 through 2025-12-31, inclusive; observed price dates
are 2014-01-02 through 2025-12-31 across 3,018 XNYS sessions.

| Frozen dataset | Rows |
| --- | ---: |
| Security master | 56 |
| Pair universe | 28 |
| Sector ETF map | 8 |
| Daily prices, 65 market series | 196,170 |
| Corporate-action observations | 2,992 |
| Daily market context, eight sector ETFs | 24,144 |
| Relevant SEC filing index | 12,414 |

- The raw inventory contains 386 files: one governed reference file, official ticker
  map, 65 price files, 65 action files, one Cboe CSV and 253 SEC submission JSON files.
  Every raw file has a SHA256-bound source sidecar; generated source data stay out of Git.
- All 12,414 indexed filings have exact usable acceptance timestamps: **100%**
  timestamp coverage. Raw source values remain queryable alongside UTC normalization.
- Release QA has no failures. Its sole warning records 27 official Cboe weekday
  observations outside XNYS. They remain in raw history and never replace the exact
  previous equity-session VIX observation. Weekend/out-of-range rows still fail.
- The first live attempt rejected these calendar differences and published nothing.
  The corrected calendar rule is tested. Failed QA/run records and raw files are
  preserved; no source data were silently repaired to pass the gate.
- The live capture records `9c961d3+dirty` because coverage metadata changed while its
  long-running download was executing. The final seven-dataset rebuild ran from clean
  commit `43c1851`; future jobs pin code identity at start. Original source identities,
  times and hashes are preserved rather than rewritten.

### Reproduction and verification

- Actual `ingest-data`, `replay-data` and `verify-data` succeeded for the complete
  synthetic 65-series/recent-and-older-SEC fixture and the full live research history.
- With sockets disabled, all **seven** live datasets matched their original curated
  values exactly after excluding the new data-snapshot IDs. Their registered/frozen
  hashes verified. An offline KO/PEP query returned 76 rows for 38 sessions; an SEC
  as-of query returned 128 KO filings, all accepted by 2021-02-05 21:00 UTC.
- Tests cover incomplete/missing market sessions, actions, DST/early closes, exact
  prior-session VIX, forbidden provider redirects, bounded retries/rate limits,
  conflicting/missing SEC metadata, timestamp admissibility, hash tampering,
  raw-only replay, portable restoration and publication/QA rollback.
- Ruff checks, formatting, strict mypy (36 source files) and `uv lock --check` passed.
  Lockfile resolves 191 packages; default installation needs no later-phase extras.
- Local complete suite after the calendar correction: **265 passed, three skipped**
  for Windows symlink permissions. Three additional date-coverage cases passed in the
  focused snapshot suite. Clean hosted runners exercised all **271 tests with no skips**.
- Hosted Windows, Linux and Linux Colab bootstrap all passed on code commit `43c1851`
  in [P1 acceptance run 37093275671](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37093275671).
  Each installs frozen dependencies and runs the complete offline test suite; CI also
  exercises actual ingestion, replay and verification commands without data credentials.
- The Windows Colab launcher and hosted Linux Python 3.12 launcher both ran the same
  isolated Python 3.11 package commands. A browser-managed Colab session was not opened;
  instructions for public-source ingestion and workspace preservation are in `COLAB.md`.

### Final gate review

| P1 criterion | Evidence | Result |
| --- | --- | --- |
| Reproduce frozen market/reference/SEC index | Full live capture and exact seven-dataset offline rebuild; CI fixture commands | PASS |
| Every curated row has source/data lineage | Release QA, raw/frozen hash verification and multi-source context tests | PASS |
| No forward-filled equity prices | Native observations retained; actual missing-session fixture blocks release; gap-return tests | PASS |
| SEC acceptance timestamps stored/queryable | 12,414/12,414 usable timestamps; real and fixture UTC cutoff queries | PASS |
| Historical queries without network | Socket-denied full-live queries and integration replay/query tests | PASS |

Independent code/spec review found no missing P1 build item. Actual dataset ranges
are recorded in final frozen-file metadata. The runbook documents retrospective
Yahoo adjustments, static classifications and unknown lifecycle dates; these do
not become claims of vintage market/reference availability. No paid data/database
login or LLM credentials were needed. The SEC contact stays in ignored local settings.

Review: [draft PR #2](https://github.com/MariusPoulsen/Project_AI_in_Finance/pull/2),
stacked on the unmerged Phase 0 branch. No main-branch merge, P2 econometrics, model
training, filing-body extraction or headline final-test outcomes were performed.

## Phase 2 — econometric relationships and daily signal state

Date: 2026-10-03. Branch: `phase-2-econometrics`.

Status: **COMPLETE — all Phase 2 acceptance gates passed.**

### Implemented scope

- Fixed-orientation log-price alignment, 504-common-observation OLS,
  ADF/KPSS integration diagnostics and Engle–Granger/MacKinnon cointegration.
- Actual XNYS monthly refits, next-session open effectiveness and frozen formation
  coefficients/moments for historical daily spread, z-score and stability state.
- Nullable half-life with exact one-session AR(1) pairs; gap-safe daily increments,
  velocities, sign crossings and fresh divergence comparisons across refits.
- ACTIVE/WATCH/RETIRED lifecycle, dated manual retirement, raw Baseline 0 crossings
  and ACTIVE Baseline 1 eligibility. Episode deduplication and labels remain P3.
- Migration 004, transactional physical analytics tables, immutable complete
  Parquet/manifest artifacts, computation-aware versions and verified read-only APIs.
- Technical runbook, pre-final diagnostic export and offline CI/Colab fixture paths.
  No forward labels, model fits, trades or outcome metrics are produced.

### Frozen project-data acceptance

Input: `snap_20261003_phase1_frozen`. Active output:
`relationships_f2f4c804ec0388ecce9fc6fd`, generated with sockets disabled at clean
code commit `30ba728a47c08643669656389d84e58d4300a4ff`.
Run ID: `0f93823e1ef640adb2f9d4fb0d3f716d`.
Config SHA-256: `50df70b5830b49db50c10410cc3b371dcfb0030721098ae14d377ac9be265087`.
Source SHA-256: `4f37497f097edd79ae01c0a1b0efb78c973605547da1e30f7a6d942de0debb1d`.
The manifest records all numerical dependency versions, including statsmodels
0.15.0, NumPy 2.4.6, pandas 2.3.3 and SciPy 1.17.1.

| Output | Rows |
| --- | ---: |
| Monthly attempts, including incomplete warm-up audit rows | 4,032 |
| Daily states across all 28 pairs, 2016-01-04 through 2025-12-31 | 70,392 |
| Raw fresh crossings, Baseline 0 | 1,357 |
| ACTIVE eligible raw crossings, Baseline 1 subset | 116 |

These crossing counts precede P3 episode deduplication and are not trade results.
The earlier complete-data generation remains immutable. Both real generations have
identical monthly IDs/parameters, daily IDs/spread/z/status and crossing IDs/eligibility;
the gap correction leaves this complete input grid unchanged. Repeating the final
build offline verifies and returns the same version, adding no run or analytics rows.

Actual SQL/manifest audits found **zero** future formation observations, future
price availability, future/expired daily parameter joins, non-latest historical
joins, changed frozen coefficients, wrong estimable formation sizes or inactive
Baseline 1 crossings. Hash verification passed for the input and published artifacts.

### Representative manual inspection

KO/PEP, HD/LOW and TXN/ADI were selected before inspecting their diagnostics. Their
2021–2023 frozen z-score and monthly cointegration plots were inspected alongside
stored records. Latest pre-final estimates (2023-12-29):

| Pair | Beta | MacKinnon p-value | Half-life, days | Integration | Status |
| --- | ---: | ---: | ---: | --- | --- |
| KO/PEP | 0.39846 | 0.20451 | 25.75 | I0 | RETIRED |
| HD/LOW | 0.86192 | 0.20488 | 27.04 | I0 | RETIRED |
| TXN/ADI | 0.32895 | 0.06220 | 18.01 | I0 | RETIRED |

Plot excursions coexist with failed validity tests; the engine exposes raw signals
without treating economic similarity or a finite half-life as proof of eligibility.
No thresholds were retuned from this inspection. Nine daily samples on 2023-06-01,
2023-12-01 and 2023-12-29 matched direct log-price/coefficient z-score calculations
within 1e-10. December daily states correctly use the November 30 fit; the December
29 estimate becomes effective January 2, 2024.

The local PNG/JSON record is under
`artifacts/reports/relationships_f2f4c804ec0388ecce9fc6fd/inspection_2023-12-31.*`.
PNG SHA-256: `f3124eae16a815f0de00c75abd6eaa1e85cd0bb320cefe01af8842dd2170b112`.
The export command rejects inspection end dates from 2024 onward.

### Tests, hosted CI and portability

- Final local full suite: **340 passed, three Windows symlink-permission skips**.
  Ruff, formatting, strict mypy (42 source files) and frozen lock checks passed.
- Statistical fixtures cover known cointegration, I0, 20 preselected independent
  random-walk seeds, fixed orientation, MacKinnon critical values, degenerate scale,
  nullable half-life, gaps, lifecycle recovery and unexpected failure propagation.
- Chronology/integration tests cover future-prefix invariance, exact effective joins,
  refit-boundary/gap crossings, lineage, deterministic rebuilds, changed-computation
  identity rejection, real SQL publication, rollback/retry and tamper rejection.
- Complete synthetic build: 180 monthly attempts, 2,262 daily states and 56 raw
  crossings. Actual local Colab bootstraps succeeded from Python 3.11 and 3.12
  hosts into the same isolated project Python 3.11 environment.
- Windows/Linux and Linux Colab jobs all passed for `30ba728` in
  [PR CI run 37099219258](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37099219258).
  Linux exercises the symlink tests skipped on this host. Hosted jobs run synthetic
  ingestion/replay and econometric publication/verification/repetition without credentials.
- An actual Google-account browser Colab session was not required or launched.
  The same portable bootstrap is tested on hosted Linux. OneDrive installations
  that reject uv cache hard links can use command-scoped `UV_LINK_MODE=copy`.

| P2 acceptance criterion | Evidence | Result |
| --- | --- | --- |
| Known synthetic relationships | Statistical units and actual synthetic history | PASS |
| No future formation data | Prefix-invariance tests and full real-history SQL audit | PASS |
| Latest effective daily relationship | Boundary/gap tests and full real-history SQL audit | PASS |
| Reproducible scientific IDs | Synthetic rebuilds, real-generation comparison and immutable reuse | PASS |
| Several representative manual inspections | Three stored pre-final plots/diagnostic records and direct calculations | PASS |

The implementation is pushed in [draft PR #3](https://github.com/MariusPoulsen/Project_AI_in_Finance/pull/3),
stacked on unmerged Phase 1. No main-branch merge is implied. P1 source limitations
and the older-raw-capture replay requirement remain documented in the runbooks.
`final_test_outcomes_computed` remains false; the final-test outcome lock is closed.

## Phase 3 — divergence dataset, Model A and minimal app

Date: 2026-10-03. Branch: `phase-3-model-a`.

Status: **COMPLETE — all Phase 3 acceptance gates passed.** Stopped at P3.
The implementation is pushed in [draft PR #4](https://github.com/MariusPoulsen/Project_AI_in_Finance/pull/4),
stacked on unmerged Phase 2. Final-test outcomes remain locked.

### Earlier history and implemented scope

The frozen prices begin on 2014-01-02. The 504-common-session formation window
uses 2014–2015; the first usable daily relationship is 2016-01-04. The user
delegated the history decision before the additional labels/model scores were
inspected. Training now covers **2016–2021**, while validation stays **2022–2023**
and the locked final test stays **2024–2025**. The added 2016–2017 history supplies
23 ACTIVE raw crossings and 16 supervised eligible episodes. The original
2018–2021 range would supply only 44 eligible training episodes. Warm-up prices
are used in formation and trailing predictors rather than labelled as trades.

- Causal, per-pair episode deduplication, entry-frozen convergence/stop/horizon
  labels, explicit censoring and full 10-XNYS-session partition/fold purges.
- Thirty-six point-in-time quantitative predictors across all five required
  families, exact prior-session VIX and explicit optional missing values.
- Same-feature logistic benchmark and 30 seeded XGBoost configurations in purged
  forward folds; validation-only calibration and predeclared 0.65 threshold.
- Verified native model bundle, ordered schema, calibration/threshold policies,
  predictions, training SHAP reference, raw-margin Tree SHAP and local MLflow.
- Migration 005, immutable Parquet/native artifacts and transactional analytical
  publication. Readers verify hashes, parent generations and scientific versions;
  each model reads its own event generation even after a newer generation activates.
- Read-only Streamlit Scanner and Pair Detail with stored research scores/SHAP,
  model/evaluation context and an explicit constant-calibration notice. UI callbacks
  perform no fitting, ingestion or analytical writes. Replay dates stop at 2023.
- Documented CLI/Colab workflows in `docs/ML_RUNBOOK.md` and `docs/COLAB.md`.

### Frozen project-data acceptance

Input snapshot: `snap_20261003_phase1_frozen`. Relationship generation remains
`relationships_f2f4c804ec0388ecce9fc6fd`; no upstream source recapture occurred.
Final P3 outputs were generated with external sockets disabled at clean code commit
`b4ae764a4867d64d844e9eae6ed625af7dd49b10`:

| Identity | Value |
| --- | --- |
| Event generation | `events_6451711be4cb02d63a38d13b` |
| Model generation | `model_a_7d2b85c381abaefb98855e31` |
| Event run | `b09bbd7e91f745868c5d496a7b76e503` |
| Model run | `8b39d7e626b14caaa190f162aa0c8d4f` |
| Config SHA-256 | `b4b72b6d7eac7ed11d9ea03f07b1ab654b673cfd736427e5c2784e04171b0305` |
| Source SHA-256 | `d9e53bdc42fa93c85fc6bee4259967a600364e7ad767bd225f912c43babc519a` |

The manifests record Python 3.11 and installed numerical dependencies, including
scikit-learn 1.9.1, XGBoost 3.2.0, SHAP 0.51.0 and MLflow 3.16.1.

| Partition | Episodes / feature-complete | Supervised eligible | Successes | Failures |
| --- | ---: | ---: | ---: | ---: |
| Train, 2016–2021 | 61 | 60 | 9 | 51 |
| Validation, 2022–2023 | 7 | 7 | 0 | 7 |
| Final test, 2024–2025 | 15 | 0 | LOCKED | LOCKED |

All 83 episodes have feature/target/partition audit rows and stored predictions.
Exactly one training episode is excluded by `PARTITION_EMBARGO`; its inference
role is `EXCLUDED_FROM_SUPERVISION`, not a fitted observation. Final-test rows
are features-only: target, resolution, excursions and censor-reason fields are
NULL, outcome is LOCKED and supervision is disabled. The full SQL audit found
zero final-outcome leaks. Required quantitative features are complete on this freeze.

| Development year | Eligible episodes | Successes |
| --- | ---: | ---: |
| 2016 | 15 | 1 |
| 2017 | 1 | 0 |
| 2018 | 5 | 0 |
| 2019 | 3 | 0 |
| 2020 | 21 | 8 |
| 2021 | 15 | 0 |
| 2022 | 3 | 0 |
| 2023 | 4 | 0 |

### Development metrics and interpretation

The selected XGBoost forward-fold results are:

| Evaluation year | Fitting events | Evaluation events | Successes | ROC AUC | Brier |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2019 | 21 | 3 | 0 | Undefined | 0.002268 |
| 2020 | 24 | 21 | 8 | 0.500000 | 0.350942 |
| 2021 | 45 | 15 | 0 | Undefined | 0.003689 |

All three folds were evaluated, but only one supports ROC AUC/average precision.
Mean defined ROC AUC is 0.5 and mean Brier is 0.118966. Search ranks by mean defined
ROC AUC, then PR AUC, then lower Brier, and preserves undefined-fold counts.
All-undefined ranking falls back to Brier. Selected logistic
regularisation is C=0.1; the full XGBoost parameter selection is in the model bundle.

| Score / role | Events | ROC AUC | Average precision | Brier | Selected at 0.65 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic training resubstitution | 60 | 0.962963 | 0.839556 | 0.064438 | 3 |
| XGBoost raw training resubstitution | 60 | 1.000000 | 1.000000 | 0.019870 | 6 |
| Logistic raw validation holdout | 7 | Undefined | Undefined | 0.010765 | 0 |
| XGBoost raw validation holdout | 7 | Undefined | Undefined | 0.028566 | 0 |
| Model A calibrated validation-fit descriptive | 7 | Undefined | Undefined | 0.012346 | 0 |

Training scores are fitted-sample descriptions, not evidence of generalisation.
All seven validation events fail under the frozen target policy. The fitted
calibrator is explicitly `CONSTANT_UNIDENTIFIABLE`: slope 0, intercept
−2.0794415416798357 and calibrated probability **1/9 (11.1%)** for every event.
This is a smoothed-prior assumption; it supplies no ranking evidence. Calibrated
validation metrics describe the calibration-fitting sample, not an untouched test.
Precision and recall are undefined where no events are selected or no positives
exist; coverage is zero. The 0.65 policy remains predeclared, with the specified
threshold grid reported descriptively rather than optimised on seven failures.

The sample does **not** establish useful predictive performance or superiority to
logistic regression. Statistical eligibility/label rules were not weakened after
observing these results. Pair/date dependence and concentration of successes in
2020 further limit inference; counts and uncertainty notes accompany metrics.

### Reproduction, leakage, app and hosted checks

- Full local suite: **429 passed, three Windows symlink-permission skips**.
  Linux CI exercises those skipped cases. The final inference-role correction
  additionally passed all 16 P3 integration tests. Ruff lint/format (87 files),
  strict mypy (50 source files including the app) and frozen lock checks passed.
- Units/integration cover every quantitative feature's cutoff/future invariance,
  frozen label paths, episode reset, missing-price/lifecycle censoring, full-window
  embargo, training-only preprocessing and chronological selection/calibration.
- Actual frozen labels were checked directly from log prices and entry coefficients
  for six development examples: two each of CONVERGED, STOPPED and TIMEOUT.
  Saved native models reproduce both raw and calibrated probabilities with maximum
  error **0**. Tree SHAP reconstructs raw margins with maximum error
  **3.332021141222441e-06**, within the 1e-5 tolerance.
- Repeating both final batch jobs returns the same verified generations and adds
  **zero** jobs. Failure rollback, immutable tamper rejection and model-bound reads
  are exercised by integration tests. The final generation matches the preceding
  registered generation's scientific rows and mathematical predictions exactly;
  excluded-inference audit labels now correctly identify their supervision role.
- Actual browser inspection rendered all 28 Scanner pairs and CAT/DE Pair Detail
  charts, stored probability context and SHAP drivers. No browser errors occurred;
  transient chart-initialisation warnings did not prevent rendering. Final-generation
  Scanner/Pair Detail AppTest also passes and displays the constant-prior notice.
  Database SHA-256 is unchanged before/after app use:
  `6f175b505ed6ddd5c068fb79e97d1a948f69cdd0d010d2b462902be10d5206d0`.
- Windows, Linux and Colab jobs passed for the final computational source commit
  in [PR CI run 37117654777](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37117654777).
  Hosted jobs run actual synthetic ingestion/replay, relationship publication,
  event construction, model tuning/calibration/SHAP, reload and repeated builds
  without provider credentials. The Colab launcher runs from a Linux Python 3.12
  host into isolated project Python 3.11. No Google-account browser session was
  required or launched; that interactive runtime remains unverified.

Local immutable acceptance reports reside under
`artifacts/reports/model_a_7d2b85c381abaefb98855e31/`:
`phase3_acceptance.json` SHA-256
`6586aa410abcd447dd715f6e982e88b864b5d0bdffc78354b378846100dd3147` and
`lineage_acceptance.json` SHA-256
`f9c28e20641df732ce70124bd49440d3915ecb2471596da367eab518fa063b82`.
Local generated artifacts, databases and QA screenshots remain excluded from Git.

| P3 acceptance criterion | Evidence | Result |
| --- | --- | --- |
| Leakage tests for every quantitative feature | Cutoff, future-perturbation and exact-session tests | PASS |
| Reproducible event counts and labels | Frozen-data direct checks, immutable generation comparison and repeat jobs | PASS |
| Documented split/embargo counts | Partition/year tables and persisted exclusion audit | PASS |
| Development metrics without final outcomes | Logistic/XGBoost reports with explicit undefined/calibration-fit roles and SQL lock audit | PASS |
| Reloaded probabilities reproduce stored inference | Actual native bundle, zero maximum probability error | PASS |
| Scanner/Pair Detail without callback training | Actual browser inspection, AppTest and unchanged database hash | PASS |

P1's retrospective Yahoo adjustments, static sector proxies and unknown lifecycle
dates remain disclosed prototype limitations. At the P3 boundary, current XOM
mapped to the 2026 successor CIK 0002115436 while the historical issuer used
0000034088. P4's dated identity recovery and supplemental source capture address
that historical evidence gap without rewriting P1 or removing XOM/CVX.

## Phase 4 — point-in-time SEC intelligence and Model B

Implementation/evidence: 2026-10-04. Acceptance completion: 2026-10-05.
Branch: `phase-4-model-b`.

Status: **COMPLETE — all Phase 4 acceptance gates passed.** Stopped at P4.
Implementation is pushed in
[draft PR #5](https://github.com/MariusPoulsen/Project_AI_in_Finance/pull/5), stacked
on unmerged Phase 3. Final-test outcomes remain locked; Phase 5 has not begun.

### Published real evidence

The original P3 event population, labels and splits are unchanged. Parent dataset
`events_6451711be4cb02d63a38d13b` remains bound to P1 snapshot
`snap_20261003_phase1_frozen` and relationship generation
`relationships_f2f4c804ec0388ecce9fc6fd`.

The genuine Gemini Flash evidence generation is
`event_intelligence_f7007e7d5176f0f61e479e03`, published at clean source commit
`317733fd8392b23adf5fc9973dc9217529cb9512`. Its manifest records prompt/schema/
event-feature v2, Gemini `gemini-3.5-flash`, config SHA-256
`0051e9bd43ced3f10488ec481f48f64d5aeed3a9a25dec81cd0ff300db613249` and
source SHA-256 `03db6dba08dffaf869ab6af606e4bfe2aa5169eaa59f6df01f530b0709661678`.

- 308 selected filings and 1,067 downloaded raw responses, including 308
  accession indices and 759 submission/body/exhibit responses. The audit retains
  23,460 chunk rows and 23,450 usable cleaned chunks; ten PDF rows remain
  explicitly unsupported.
- All 83 events have evidence packs, extraction audit rows and the 67-column
  Model B feature schema: 36 unchanged quantitative columns plus 31 event columns.
- Eight real extractions succeeded: five EARNINGS, one GUIDANCE, one M&A and one
  MANAGEMENT. Seventeen exact supporting quotes have admissible source identity,
  company leg and acceptance time no later than the event cutoff.
- The free-tier pilot stopped on the Google rate limit. The remaining 75 rows
  stay UNKNOWN. One successful extraction also records an earlier
  invalid/ungrounded-response attempt. NONE is
  a separate complete-coverage outcome, with no real NONE rows in this generation.

| Partition | Original episodes | SUCCESS | UNKNOWN | NONE |
| --- | ---: | ---: | ---: | ---: |
| Train, 2016–2021 | 61 | 2 | 59 | 0 |
| Validation, 2022–2023 | 7 | 6 | 1 | 0 |
| Final features, 2024–2025 | 15 | 0 | 15 | 0 |

This is engineering acceptance with a genuine partial extraction pilot. It is
not a representative NLP accuracy study. Confidence, direction, materiality and
relationship relevance still need independent human semantic evaluation in P5.
Every UNKNOWN observation remains in the paired model cohort. Seven all-negative
validation observations cannot establish discrimination or Model B superiority.

### Published Model B and development comparison

Model B is `model_b_b3122de8fb28e7dd093905c4`, published from clean source
`565d15d23d29fca27db2c3c029b074b29640442e`, run
`50da6f4b04aa4299becd696a8ddb0d01`. Its computational source SHA-256 is
`8be5c6954afccf598c30506fd3c82bdc244cf1420350e532789b6b34202a2450`.
It binds the evidence generation above and original Model A
`model_a_7d2b85c381abaefb98855e31`. All 83 episodes receive stored predictions;
the supervised population remains 60 training events (nine successes), seven
validation events (zero successes) and 15 final features-only events.

| Paired validation score | Model A Brier | Model B Brier | Selected at 0.65 |
| --- | ---: | ---: | ---: |
| Raw XGBoost holdout | 0.028566 | 0.045191 | 0 / 0 |
| Calibrated validation-fit descriptive | 0.012346 | 0.012346 | 0 / 0 |

ROC AUC and average precision are undefined because all seven validation outcomes
are negative. Both smoothed calibrators are constant at 1/9, with no ranking
information. Raw Brier is worse by 0.016625 on this observed cohort; calibrated
scores are identical. Neither the small one-class sample nor the partial pilot
supports a claim of Model B superiority or useful probability generalisation.
UNKNOWN/NONE/available/supported paired slices remain additional descriptions;
they do not replace the full seven-event comparison. Final outcomes are absent.

### Reproduction, leakage and hosted checks

Lint/format (104 files), strict mypy (58 source files) and the tracked-file secret
scan pass. Final computational source passed **563 tests on each of Windows,
Linux and Colab**, plus the actual offline P1–P4 bootstrap/training/reload/repeat
workflows in
[CI run 37203256653](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37203256653).
The Colab launcher uses a Linux Python 3.12 host and an isolated Python 3.11
project environment; a signed-in interactive Colab notebook was not exercised.

Source commit `565d15d23d29fca27db2c3c029b074b29640442e` consolidates repeated
SEC scientific audits within Model B verification into one, using a pinned verified
input set and exact-byte frame checks. Independent public reads remain fresh;
native files are rechecked before loading and all bound files/manifests before
returning. It adds fresh-training audit-count and mid-operation source-tamper
regressions. The real Model B jobs completed with external sockets disabled.
Native raw/calibrated/logistic probabilities reproduce with maximum error **0**;
Tree SHAP raw-margin reconstruction error is **5.865883345279599e-06**, below
1e-5. The paired comparison reproduces exactly, and repeating Model B training
returns the identical registered generation without extraction or external calls.
P1's manifest is unchanged and final targets remain NULL. The initial overlapping
local retry hit a DuckDB lock and
registered no Model B or active pointer; the single-process retry preserved the
failed files in an unregistered archive and published successfully.

The local immutable acceptance report is
`artifacts/reports/model_b_b3122de8fb28e7dd093905c4/phase4_acceptance.json`,
SHA-256 `4a23150d919c9ef3943666f10a9dcdf9ce60bde2e3207b768d2b216fd07ad315`.
Evidence-manifest SHA-256 is
`2b41bbdfb95221d5d3262609c9fea1e9c1049e7f1f0c1fc912c88bf87fd47f45`;
Model B manifest SHA-256 is
`1563e56aa7dbf4cada97be685cf9309276c3c2a968dcf502eaa3df4d1e2c6cc0`.
Generated source caches, models, databases and reports remain excluded from Git.

| P4 acceptance criterion | Evidence | Result |
| --- | --- | --- |
| Known non-NONE catalysts have admissible evidence IDs | Eight genuine supported extractions, 17 exact citations and strict schema/source replay tests | PASS |
| Supporting SEC timestamps do not exceed the event cutoff | Actual citation audit plus future/security/timestamp rejection tests | PASS |
| NONE differs from retrieval/coverage UNKNOWN | Complete-coverage policy, mocked NONE fixtures and retained real UNKNOWN rows | PASS |
| Model B rebuilds from stored features without an LLM | Actual socket-disabled training and identical repeat generation | PASS |
| Model A/B validation comparison is reproducible | Native probability replay, exact paired comparison and stored JSON | PASS |
| Missing evidence preserves difficult observations | All 83 parent events and all seven validation events retained, explicit coverage slices | PASS |

### Separate research proposal

[RESEARCH_REDESIGN.md](RESEARCH_REDESIGN.md) records the development-only scarcity
audit and a proposed separate `research-v2` experiment. The main bottleneck is
relationship eligibility: only 17 of 672 validation pair-months are ACTIVE,
yielding seven deduplicated episodes. More rows from the same episode would add
dependence rather than independent information.

The recommended direction is 250–500 dated issuers / 500–1,000 economic peer
pairs with longer point-in-time history, regularised simple models, chronological
walk-forward predictions and separate calibration/evaluation. A predeclared
10/20/30-session horizon study tests target adequacy separately. These are
proposals; no universe, label, split, eligibility or threshold changes are applied,
and 2024–2025 outcomes remain locked.

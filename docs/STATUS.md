# Implementation status

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

Status: **IMPLEMENTED — frozen project-data build and final acceptance in progress.**

The batch engine now aligns fixed-orientation log prices, estimates 504-observation
monthly ADF/KPSS/Engle–Granger relationships, freezes next-session parameters and
publishes daily state plus raw Baseline 0/ACTIVE Baseline 1 crossings. SQL migration
004, immutable artifacts, read-only services and the technical runbook are included.
No forward labels, model fits, trades or outcome metrics are produced.

Initial local verification: 331 passed, three host symlink-permission skips;
subsequent edge-case and publication-validator tests passed. Ruff, formatting,
strict mypy and frozen lock checks passed. The synthetic pipeline published 180
monthly attempts and 2,262 daily rows. Both Python 3.11 and Python 3.12 host Colab
bootstraps ran the actual project Python 3.11 fixture path successfully.

Final acceptance will record the clean code revision, frozen project-data output,
representative diagnostics through 2023, hosted CI and the completed P2 gates.

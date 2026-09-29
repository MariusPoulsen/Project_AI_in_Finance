# Implementation status

## Phase 0 — foundation

Date: 2026-09-29. Branch: `phase-0-foundation`.

Status: implementation built; final clean-clone and hosted CI verification in progress.
Phase 1 has not begun.

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

### Remaining acceptance evidence

- Clean Git clone installation and checks: pending.
- Host Python 3.12 → isolated Python 3.11 bootstrap execution: pending.
- Hosted Windows/Linux CI and Linux Colab bootstrap: pending.
- An actual browser-managed Colab session has not been launched from this workstation.
  The portable bootstrap and instructions are provided in `docs/COLAB.md`; hosted
  Linux CI exercises the same commands without needing Google account credentials.

### Scope and future prerequisites

No ingestion, econometrics, model fitting, LLM calls, final-test results or Streamlit
screens are claimed. Later-phase namespaces are intentional package boundaries.
The missing `docs/specs/04_MULTI_AGENT_PIPELINE.md` predates this work and must be
resolved before its owning phase. Draft policy/cost fields are explicitly unset.

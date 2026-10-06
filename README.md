# Project_AI_in_Finance

AI Structural-Break Detector for Statistical Arbitrage: a research and decision-support
system. Phase 0 provides the package, validated settings, storage and repeatable jobs.
Phase 1 adds governed reference data, Yahoo prices/actions, official Cboe VIX,
SEC filing metadata, immutable source snapshots and offline historical queries.
Phase 2 adds monthly Engle-Granger relationships, integration/stability diagnostics,
frozen daily spread states and raw divergence crossings. Models, agents, backtesting
and Streamlit pages follow later phases.

## Local setup (Windows, Linux or macOS)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from
this repository:

```shell
uv python install 3.11
uv sync --frozen
uv run --frozen structural-break check-config
uv run --frozen structural-break init-db
uv run --frozen structural-break storage-smoke
```

This creates a separate `.venv` using Python 3.11. It does not use or modify the
Python 3.12 course environment in `../Ai_in_Finance`. No Jupyter installation is
required. Optional dependency sets `research`, `agents` and `app` are locked but
not needed for Phase 2; install them when needed with `uv sync --frozen --extra NAME`.
Statsmodels and Matplotlib are included in the default environment.

If uv encounters file-locking problems on Windows/OneDrive, set
`$env:UV_LINK_MODE = "copy"` in the current PowerShell session before syncing.
This changes the current process only and does not modify global settings.

`init-db` and `migrate-db` use the same transactional migration runner. They check
existing migration checksums and apply new numbered files. Normal readers open
DuckDB read-only. `storage-smoke` performs a real, offline fixture round trip across
Parquet, DuckDB, documents, artifacts and the run registry. It uses `data/demo/`,
synthetic filing identifiers and `foundation-fixture-v1`, never production prices.

Run from another working directory with `--project-root /path/to/repository`.
Set `--workspace-root /path/to/workspace` to relocate all generated data/artifacts;
relative workspace paths resolve against the repository, not the current directory.
`SB_WORKSPACE_ROOT` in the environment or a local `.env` provides the same override.
The default database is `data/analytics/structural_break.duckdb`.

## Build and verify data

Exercise the full Phase 1 ingestion pipeline with the committed synthetic fixture:

```shell
uv run --frozen structural-break ingest-data --fixture tests/fixtures/phase1 --snapshot-id fixture-p1 --workspace-root .acceptance/phase1
uv run --frozen structural-break replay-data --replay-from fixture-p1 --snapshot-id fixture-p1-replay --workspace-root .acceptance/phase1
uv run --frozen structural-break verify-data --workspace-root .acceptance/phase1
```

These commands need no source credentials or network access after installation.
Snapshot IDs are immutable; choose new IDs when running ingestion again. Replay
rebuilds the curated datasets from stored raw sources, and verification checks
the active local catalogue entry and snapshot hashes.

For public market and SEC sources, create a local `.env` with
`SB_SEC_USER_AGENT` set to your project name and real contact email, then run:

```shell
uv run --frozen structural-break ingest-data
uv run --frozen structural-break verify-data
```

No Yahoo, Cboe, SEC or database login is required. SEC requires the declared
contact identity for scripted access. Default frozen history spans 2014-01-01
through 2025-12-31. Source failures and blocking quality checks prevent publication.
See [the data runbook](docs/DATA_RUNBOOK.md) for replay, manifests and recovery.

Equity gaps remain missing. Returns and trailing volatility never bridge a missing
session. Market context uses the previous NYSE session's VIX value, preserving its
observation date and source lineage. Yahoo adjusted prices are retrospectively
adjusted vendor history; the frozen snapshot is reproducible, but is not a vintage
point-in-time feed. Reference classifications are fixed project assumptions and
unknown lifecycle dates remain explicit. Historical CSV publication times are not
verified. These limitations are recorded in the data runbook.

## Build and verify econometric history

Run the independent Phase 2 fixture without a data-provider login or Phase 1 fixture:

```shell
uv run --frozen structural-break build-relationships --relationship-fixture --workspace-root .acceptance/phase2 --relationship-version fixture-p2
uv run --frozen structural-break verify-relationships --workspace-root .acceptance/phase2
```

For project prices, run these commands in the workspace containing a successfully
published and verified Phase 1 snapshot:

```shell
uv run --frozen structural-break verify-data
uv run --frozen structural-break build-relationships
uv run --frozen structural-break verify-relationships
```

The default build uses the 2014 warm-up through 2025 source history. It fits the
fixed A-on-B orientation on 504 valid common sessions at each actual month-end,
then applies frozen parameters and spread moments from the next XNYS session.
Missing prices produce no daily state and never create a crossing across a gap.
Baseline 0 retains fresh crossings wherever the current spread is estimable;
Baseline 1 additionally requires an ACTIVE relationship. These raw observations
have no labels, trade outcomes or performance metrics. Final-test outcomes remain locked.

Read [the econometrics runbook](docs/ECONOMETRICS_RUNBOOK.md) for lifecycle rules,
immutable versions, offline queries, failure recovery and representative diagnostics.

## Verification

```shell
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen pytest
```

Tests block network sockets and need no credentials. CI runs on Windows and Linux,
including a Python 3.12 host launching the isolated Python 3.11 Colab bootstrap.
Package/Python installation requires internet; the installed checks and fixture
jobs run offline. CI also ingests/replays the full Phase 1 fixture and builds/verifies
the independent Phase 2 econometric fixture, including an idempotent repeated build.
No headline final-test metrics are computed by these jobs.

## Google Colab

See [the Colab runbook](docs/COLAB.md). Colab launches the same scripts in a locked
Python 3.11 environment; its notebook kernel version does not determine the project
runtime. Project logic stays in Python modules. There is no notebook dependency.

## Project documentation

- [Canonical decisions](docs/DECISIONS.md)
- [Implementation phases](docs/PLAN.md)
- [Completion evidence](docs/STATUS.md)
- [Specification index](docs/specs/README.md)

Only source, configuration, small fixtures and documentation belong in Git.
Generated data, database files, artifacts, virtual environments and secrets are ignored.

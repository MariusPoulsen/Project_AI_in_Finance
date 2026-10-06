# Project_AI_in_Finance

AI Structural-Break Detector for Statistical Arbitrage: a research and decision-support
system. Phase 0 provides the package, validated settings, storage and repeatable jobs.
Phase 1 adds governed reference data, Yahoo prices/actions, official Cboe VIX,
SEC filing metadata, immutable source snapshots and offline historical queries.
Phase 2 adds monthly Engle-Granger relationships, integration/stability diagnostics,
frozen daily spread states and raw divergence crossings. Phase 3 adds deduplicated
events, point-in-time quantitative features, chronological development labels,
logistic/XGBoost Model A, calibration, SHAP and a read-only Scanner/Pair Detail app.
Phase 4 adds cached point-in-time SEC evidence, validated catalyst extractions,
explicit coverage and Model B. Agents and backtesting follow later phases.

For SEC evidence, Gemini setup and Model B reproduction, see the
[intelligence runbook](docs/INTELLIGENCE_RUNBOOK.md). The authorized broader
research experiment uses [the frozen v2 protocol](docs/RESEARCH_V2_PROTOCOL.md)
and [the research runbook](docs/RESEARCH_V2_RUNBOOK.md). It preserves the original
Phase 4 results and the final-test lock.

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
required. Quantitative research dependencies and Streamlit install by default. The
`research` and `app` extra names remain supported aliases; `agents` is optional.

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

## Build Model A and open the research app

Run the complete independent Phase 3 fixture offline after dependency installation:

```shell
uv sync --frozen --extra app
uv run --frozen structural-break build-events --ml-fixture --workspace-root .acceptance/phase3 --event-version fixture-events-p3
uv run --frozen structural-break train-model-a --workspace-root .acceptance/phase3 --model-version fixture-model-a-p3
uv run --frozen structural-break verify-model-a --workspace-root .acceptance/phase3
```

For the already published real source/econometric workspace, omit `--ml-fixture`
and its fixture-specific workspace/version names. Training events span 2016–2021:
2014–2015 supply the 504-session relationship warm-up. Validation stays 2022–2023;
2024–2025 outcomes remain locked. Every event keeps the same fixed entry relationship
parameters throughout its target horizon and every predictor uses information
available by event close. Small ACTIVE-event counts limit model/calibration claims.

Launch the read-only app from a workspace containing frozen relationships:

```shell
uv run --frozen --extra app streamlit run app/streamlit_app.py
```

Use `SB_WORKSPACE_ROOT` to select the fixture or another research workspace. Scanner
and Pair Detail show quantitative history and published Model A research scores;
ordinary browsing does not train models or write analytical rows. The Phase 3 date
selector remains in development history. Read [the ML runbook](docs/ML_RUNBOOK.md)
for episode policy, splits, calibration uncertainty, versioned model bundles and
failure handling.

## Verification

```shell
uv run --frozen --extra app ruff check .
uv run --frozen --extra app ruff format --check .
uv run --frozen --extra app mypy
uv run --frozen --extra app pytest
```

Tests block network sockets and need no credentials. CI runs on Windows and Linux,
including a Python 3.12 host launching the isolated Python 3.11 Colab bootstrap.
Package/Python installation requires internet; the installed checks and fixture
jobs run offline. CI also ingests/replays the full Phase 1 fixture and builds/verifies
the independent Phase 2 econometric fixture, including an idempotent repeated build,
plus Phase 3 event/model publication, reload and read-only app smoke tests.
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

# Project_AI_in_Finance

AI Structural-Break Detector for Statistical Arbitrage: a research and decision-support
system. Phase 0 provides the package, validated settings, storage and repeatable jobs.
Data ingestion, models, agents, backtesting and Streamlit pages follow later phases.

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
not needed for Phase 0; install them when needed with `uv sync --frozen --extra NAME`.

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
jobs run offline. No headline final-test metrics are computed in Phase 0.

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

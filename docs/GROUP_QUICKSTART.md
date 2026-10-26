# Group quick start

Use this workflow for app development, results analysis, backtesting existing
A/B models, and predictions on the existing development events. The shared
snapshot includes all three horizons, both model families, every B ablation,
features, predictions, reports, market prices and frozen relationship history.
It excludes the large SEC filing archive, redundant raw market downloads and
per-event text checkpoints. Curated development prices and the original source
manifests are retained.

**Delivery status:**

- **v2 is accepted** (DECISIONS 34), and the official `group-v2.zip` is the
  snapshot to use. The earlier `group-v2-provisional.zip` is superseded; do
  not use it.
- **Phase 6 backtesting** (`src/structural_break/backtest/`,
  `structural-break-backtest`) runs on the imported accepted workspace under
  frozen execution policies. See [BACKTEST_RUNBOOK.md](BACKTEST_RUNBOOK.md) and
  [P6_DEVELOPMENT_RESULTS.md](P6_DEVELOPMENT_RESULTS.md).

Coding agents: give your agent [GROUP_AGENT_BRIEF.md](GROUP_AGENT_BRIEF.md) first.
Keep per-stream notes in [docs/team/](team/README.md).

## First setup

Install Git and Python if needed. Clone the repository:

```shell
git clone https://github.com/MariusPoulsen/Project_AI_in_Finance.git
cd Project_AI_in_Finance
```

Use `main`, which contains the accepted v2 release.

Download `group-v2.zip` and its `.sha256` file from the shared group folder. Use
the checksum provided with Marius's handoff:

```shell
python scripts/team.py setup --snapshot /path/to/group-v2.zip --sha256 OWNER_PROVIDED_SHA256
```

On Windows, use your ZIP's path, for example
`"C:\Users\yourname\Downloads\group-v2.zip"`. Setup installs `uv` if needed,
creates the locked Python 3.11 environment, verifies/imports the snapshot and
remembers the workspace. No API keys, Google AI Studio login, FinBERT downloads,
SEC archive or model fitting are needed. Imports never overwrite existing
research data. Repeating setup with the same bundle checks the existing copy
and restores local DuckDB views.

## Everyday commands

```shell
python scripts/team.py app
python scripts/team.py research-app
python scripts/team.py check
python scripts/team.py predict --pair KO__PEP
python scripts/team.py backtest-inputs --pair KO__PEP --horizon 20
```

The app browses accepted outputs and reports; `research-app` opens the full
seven-page application (see [app/README.md](../app/README.md)). `predict` reloads the actual saved
logistic A/B-both models, runs their original preprocessing and calibration, and
checks every returned probability against the published prediction within
`1e-12`. It writes a fresh CSV under `outputs/`. Omit `--pair` for all existing
events, or use `--horizon 10`/`30` for the predeclared sensitivities.

`backtest-inputs` writes pair prices, frozen monthly relationship snapshots,
daily pair state, raw crossings, events, quantitative features, development
targets/partitions and published predictions to a new directory. Feed them to the
shared simulator in `src/structural_break/backtest/` (see `docs/BACKTEST_RUNBOOK.md`);
these files alone are not a returns backtest. Keep actual ACTIVE flags and the broad registry's
episode construction intact.

For custom analysis, import `existing_predictions` or `backtest_inputs` from
`structural_break.collaboration.queries`, and construct `ProjectPaths` with the
workspace printed by setup. They return pandas DataFrames. SQL views are rebuilt
locally; their file paths never depend on Marius's computer.

## Working together

- Make code changes on your own Git branch and open a pull request.
- Use the same snapshot version so results refer to identical inputs.
- Keep imported data unchanged. CSVs, figures and experiments belong under
  `outputs/`, or another directory outside the imported workspace.
- `data/`, `outputs/`, `.team/`, environments and credentials stay out of Git.
- Development data ends in 2023; the 2024–2025 outcome lock remains in force.
  Import retains the original acceptance proofs and does not mint verification.
- Canonical retraining and full source verification require the owner's archive.

## Owner: export after acceptance

From the handoff checkout, export the exact accepted workspace:

```shell
python scripts/team.py export --workspace-root /path/to/accepted/data/research_v2 --output /path/to/group-v2.zip
```

Export reads accepted manifests and outputs, includes their required lineage
and the complete frozen pair history, checks dates/checksums, and writes
`group-v2.zip.sha256`. It performs no downloads, NLP inference, training, source
reconstruction or publication. An unfinished generation is rejected. Original
scientific manifests and model bytes are preserved.

The setup tooling can be completed before v2. Delivery still requires exporting
the real accepted artifacts and checking their import, app and native predictions
in a fresh workspace; fixture checks alone do not establish production readiness.

Import into a fresh directory and run `check`, `predict` and the app before
placing the ZIP plus checksum in the group's shared folder. Share the snapshot
version, accepted primary version and code revision. The exporter measures the
compressed size. Keep the full source archive separately for reproducibility.

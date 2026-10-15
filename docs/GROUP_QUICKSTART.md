# Group quick start

Use this workflow for app development, results analysis, backtesting existing
A/B models, and predictions on the existing development events. The shared
snapshot includes all three horizons, both model families, every B ablation,
features, predictions, reports, market prices and frozen relationship history.
It excludes the large SEC filing archive, redundant raw market downloads and
per-event text checkpoints. Curated development prices and the original source
manifests are retained.

**Delivery status:** tooling is prepared separately while v2 completes. The real
shared snapshot can be exported only after an accepted primary publication.
No production snapshot is available yet. The backtesting engine is separate
work; this handoff supplies its inputs and does not claim a completed simulator.

## First setup

Install Git and Python if needed. Clone the repository:

```shell
git clone https://github.com/MariusPoulsen/Project_AI_in_Finance.git
cd Project_AI_in_Finance
```

Use the released code containing `scripts/team.py`. Until this handoff is merged,
its review branch is `collaboration/portable-research-snapshot`; `main` does not
have these commands yet.

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
python scripts/team.py check
python scripts/team.py predict --pair KO__PEP
python scripts/team.py backtest-inputs --pair KO__PEP --horizon 20
```

The app browses accepted outputs and reports. `predict` reloads the actual saved
logistic A/B-both models, runs their original preprocessing and calibration, and
checks every returned probability against the published prediction within
`1e-12`. It writes a fresh CSV under `outputs/`. Omit `--pair` for all existing
events, or use `--horizon 10`/`30` for the predeclared sensitivities.

`backtest-inputs` writes pair prices, frozen monthly relationship snapshots,
daily pair state, raw crossings, events, quantitative features, development
targets/partitions and published predictions to a new directory. Use the shared
simulator's execution/cost rules when that branch is released; these files alone
are not a returns backtest. Keep actual ACTIVE flags and the broad registry's
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

## Google Colab

Clone the released repository and upload the ZIP or mount the shared Drive
folder. Run the same setup command with the host's `python`, optionally adding
`--workspace-root /content/group-v2`. Then run `predict`, `check` or
`backtest-inputs` with `python scripts/team.py ...`. The launcher uses a separate
Python 3.11 environment and does not replace Colab's kernel. Read its CSV/Parquet
outputs from notebook cells. The Streamlit app is easiest to run locally.

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

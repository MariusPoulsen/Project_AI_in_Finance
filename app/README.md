# Read-only research apps

The full app presents the current walk-forward research and the earlier accepted
study as separate views. Browsing never downloads sources, calls a language
model, fits a model, or writes analytical results. The committed presentation
snapshot excludes 2024–2025 outcomes and reports its final-test state as locked.

| Entry point | What it is |
|---|---|
| `research_app.py` | Dark research workspace: current forecasting and portfolio comparisons, investigation, evidence and clearly labelled reference-study tools. Use this for the deployed site. |
| `streamlit_app.py` | The minimal verified two-page view (model comparison, event scores). Unchanged. |
| `reference_streamlit_app.py` | The original Scanner/Pair Detail for the recorded v1 workspace. See the [reference archive](../docs/archive/README.md). |

## Full research application

```shell
python scripts/team.py research-app          # after `team.py setup` with group-v2.zip
# or
uv run --frozen streamlit run app/research_app.py
```

| Page | What it answers |
|---|---|
| Overview | All four forecasters and both book exit policies, with a shared period selector and fixed-rule tables. |
| Forecasting | Model A, R0, B+rule+ou bag5 and the post-hoc +track variant. Shared period/metric controls, point estimates, model roles, diagnostics, fixed rules and CSV export. |
| Portfolio | Adopted R0 + monitor versus the same book without the monitor. Period-aligned statistics, NAV/drawdown, return-basis labels, costs and exports. |
| Evidence and diagnostics | Export availability, agent coverage and abstentions, overfitting audit, news-source shift and presentation hashes. |
| Rules and definitions | Fixed forecasting/book rules, model registry, metric definitions and chronology. Interpretive conclusions belong in the report. |
| Scanner | Every scored divergence: filter by date, research period, business group, ACTIVE status, minimum Model B probability or pair; select a row to open it; download as CSV. |
| Pair detail | Rebased prices, the frozen z-score with bands and event markers, ACTIVE shading, monthly hedge-ratio history and diagnostics; per event, both models' probabilities, an exact feature-contribution chart (linear SHAP / TreeSHAP of the saved models) and the SEC evidence available at the close, with UNKNOWN kept explicit. |
| Accepted model study (reference) | Earlier ten-bundle A/B study: ablations, calibration, ROC/PR, SHAP, slices, folds and uncertainty. These are not current walk-forward predictions. |
| Plan-ladder benchmark (reference) | Earlier strategy ladder, costs, sensitivities and uncertainty. Its unrun Full System rung is distinct from the current separately evaluated desk. |
| Reference data health / protocol | Earlier study identities, coverage, drift and frozen model card. |

Scanner and Pair Detail are explicitly labelled as the earlier accepted study.
Current per-event predictions, calibration arrays and uncertainty have not been
exported; the app does not invent them or reuse earlier scores under new names.
Each data source has independent missing/failed verification states and provenance.

### Where the data comes from

Current pages load `demo/book/summary.json`, `book_daily.parquet` and their
versioned `presentation.json` manifest. `SB_RESEARCH_SUMMARY` can select another
directory (relative paths resolve from the repository, not the launch directory).
Both artifact hashes, dates, model identities and required measurements are
checked before display. Cache identity includes every file's bytes. These hashes
identify presentation bytes; they do not replace scientific acceptance checks.

To register an updated **development-only** book export explicitly:

```shell
python scripts/export_research_presentation.py
```

Review the cohort metadata and role/source mappings when changing the export.
The app never invokes this writer. Final-test publication needs its own authorized
presentation update; this manifest deliberately accepts only the locked state.

Reference-study pages load lazily and look, in order, for:

1. `SB_APP_BUNDLE`: a checksummed **app bundle** directory (see below).
2. `demo/app_bundle/`: a bundle committed for the deployed demo.
3. The accepted workspace (`SB_WORKSPACE_ROOT`, default `data/research_v2`),
   read in memory, plus any official Phase 6 experiments under
   `SB_EXPERIMENTS_ROOT` (default `.acceptance/`). Experiments from another
   generation are skipped.

An app bundle holds compact presentation tables derived only from accepted
outputs: published reports, stored predictions, saved native models (for exact
explanations) and verified Phase 6 experiment manifests. Every file is SHA-256
checked on read. Export never writes into the workspace and refuses rows after
`development_end`.

```shell
# From the workspace imported with team.py setup (+ the owner's .acceptance/ results):
python scripts/team.py app-bundle --output outputs/app-bundles/v2
# Equivalent explicit form; --pair keeps a pair among the showcase subset:
uv run --frozen structural-break-app export --workspace-root data/team \
  --experiments-root .acceptance --showcase-pairs 40 --pair KO__PEP \
  --output outputs/app-bundles/v2
uv run --frozen structural-break-app verify --bundle outputs/app-bundles/v2
SB_APP_BUNDLE=outputs/app-bundles/v2 uv run --frozen streamlit run app/research_app.py
```

A bundle carries daily pair history only for the showcase pairs (to stay around
10–20 MB); the other pairs still show their events and scores. Opening the app on
the full workspace shows every pair.

### Synthetic preview (no snapshot needed)

```shell
uv run --frozen structural-break-app synthetic --output outputs/app-bundles/synthetic
SB_APP_BUNDLE=outputs/app-bundles/synthetic uv run --frozen streamlit run app/research_app.py
```

Every ticker, price, label and result in that reference bundle is **invented**. It runs the
project's real matched evaluation on fake events so the interface can be built
and tested without the snapshot. Each page shows a red banner and the bundle is
marked `synthetic: true`. Never present it as a finding. This setting changes only
the reference study; it does not replace the separately loaded current summary.

## Deploying to Streamlit Community Cloud

1. Include the verified `demo/book/` presentation files for the current comparisons.
   Export a real reference bundle (above) and copy it to `demo/app_bundle/` on a branch.
   It is generated data, so whether it lives on `main` or a separate demo
   branch is the repository owner's decision.
2. On [share.streamlit.io](https://share.streamlit.io), create an app from the
   GitHub repository: branch with the bundle, main file `app/research_app.py`.
3. Under **Advanced settings**, choose **Python 3.11** (the project does not
   support 3.12). Dependencies install from `uv.lock` / `requirements.txt`.
4. No secrets are needed: the app makes no API calls. If you keep the bundle
   elsewhere in the repository, set `SB_APP_BUNDLE` to its path in the app's
   secrets (top-level secrets are exposed as environment variables).

Theme and fonts come from `.streamlit/config.toml` in the repository root.

## Minimal verified view

```shell
uv run --frozen --extra nlp streamlit run app/streamlit_app.py
```

The default workspace is `data/research_v2`. Set `SB_WORKSPACE_ROOT` in the
ignored `.env` or process environment to select a restored workspace. Results
appear only after a complete, independently verified generation is explicitly
published; missing outputs show a pending state and failed verification shows an
error.

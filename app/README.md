# Read-only research apps

Two Streamlit entry points read the same accepted outputs. Neither downloads
sources, calls a language model, fits a model or writes analytical results, and
neither can open the locked 2024–2025 final test.

| Entry point | What it is |
|---|---|
| `research_app.py` | The full research application (PLAN P7, work stream 2): seven pages, charts, explanations, backtest results. Use this for demos and the deployed site. |
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
| Overview | The question, the spread picture with entry/convergence/stop bands, and the predeclared primary A-vs-B result in plain words, with its interval and denominators. |
| Scanner | Every scored divergence: filter by date, research period, business group, ACTIVE status, minimum Model B probability or pair; select a row to open it; download as CSV. |
| Pair detail | Rebased prices, the frozen z-score with bands and event markers, ACTIVE shading, monthly hedge-ratio history and diagnostics; per event, both models' probabilities, an exact feature-contribution chart (linear SHAP / TreeSHAP of the saved models) and the SEC evidence available at the close, with UNKNOWN kept explicit. |
| Model Lab | All ten bundles per horizon: ablation ladder, B − A intervals, reliability, ROC and precision–recall curves, predeclared slices, global drivers, tuning folds and calibrators, full metrics table. |
| Strategy Lab | The Phase 6 four-rung ladder: selected/priced/unpriced counts, net bps, NAV and drawdown, threshold and cost/borrow sensitivity, paired calendar-month bootstrap, rejected-trade (counterfactual) analysis, limitations. Full System shown as not run. |
| Data and model monitor | Every data/model identity, samples per period, events per year, SEC coverage and UNKNOWN rates by year, feature drift, the saved-model inventory. |
| Methodology | Model card: target, chronology, features, models, evaluation, limitations, intended use, data/privacy/security. |

Every page has a "Data and model versions behind this page" expander, and every
loading, empty, pending and failed-verification state has its own message.

### Where the data comes from

The app looks, in order, for:

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

Every ticker, price, label and result in it is **invented**. It runs the
project's real matched evaluation on fake events so the interface can be built
and tested without the snapshot. Each page shows a red banner and the bundle is
marked `synthetic: true`. Never present it as a finding.

## Deploying to Streamlit Community Cloud

1. Export a real bundle (above) and copy it to `demo/app_bundle/` on a branch.
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

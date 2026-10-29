# Read-only research apps

Two Streamlit entry points read the same accepted outputs. Neither downloads
sources, calls a language model, fits a model or writes analytical results.

| Entry point | What it is |
|---|---|
| `research_app.py` | The full research application: nine pages with the headline forecasters (Goal 1), trading book (Goal 2), event investigations, agent desk and final test. Use this for demos and the deployed site. |
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
| Overview | The research question, spread picture, both goals and a compact pipeline diagram. |
| Scanner | Every divergence scored walk-forward from 2010: R0, bagged and +track probabilities (and the full model where the agents read the event), whether the adopted book traded it, its exit and gross return; filters and CSV download. Falls back to the research layer's A/B scanner when no results are deployed. |
| Event investigation | Click a Scanner row to compare probabilities, exported explanations, cached agent reports and cited evidence, input values, then the separate realised label and adopted-book trade. Back to Scanner preserves filters. |
| Pair detail | Rebased prices, the frozen z-score with bands, ACTIVE shading and hedge-ratio history; each event with the headline probabilities and its trade; the research layer's exact feature contributions where available; every trade of the adopted book on the pair. |
| Model Lab | Baselines and current forecasters by test period, discrimination, calibration, SHAP, yearly and business-group slices, the matched Full/base comparison, settings and metrics. |
| Strategy Lab | The book's design ladder from trading every divergence to the adopted book, the four books compared (adopted, without the monitor, the best forecaster's and the full model's selections), exits and the monitor, every trade. The original 2022–2023 plan ladder (Decisions 36–40) is superseded and no longer shown. |
| Adopted book | The design, results by period, the final-test section (filled once the 2024–2025 run is published), monthly returns, the overfitting audit, the agent desk and news coverage. |
| Data and model monitor | Current scored-event samples, complete input matching, SEC metadata/FinBERT coverage, quantitative and engineered feature drift, model inventory, agent/news health and provenance. |
| Methodology | Model card: goals, chronology, target, headline forecasters, agent desk, trading book, the research layer, limitations, intended use, data/privacy/security. |

Every page has a "Data and model versions behind this page" expander, and every
loading, empty, pending and failed-verification state has its own message.

### Where the data comes from

**Headline results** (`demo/results/`): the forecasters' walk-forward scores, curves and metrics, the four books' daily values and statistics, the adopted book's trades, news coverage and, once published, the final-test report. Written by `python scripts/export_results.py` from a checkout whose `outputs/` holds the development results (2010–2023) or the final-test results (2010–2025); every file is checked against `manifest.json` on each load. Without them the results pages say so and the Scanner shows the research layer.

**Research layer** (the frozen A/B study, spreads and explanations):

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

The base bundle carries daily pair history for showcase pairs. The committed
`demo/pair_history` supplement supplies history for all 736 development pairs,
verified against the same registry. Neither the SEC archive nor a database is
needed for browsing.

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

## Current monitoring and explanations

The monitor now follows the current scored-event population and the 2010–2017,
2018–2023 and 2024–2025 evaluation periods. Catalyst fields are hidden from SEC
coverage and drift, with all missing-input events retained in denominators.
Model Lab's SHAP tab reads verified annual-model attributions; it never reuses
frozen-study explanations. See [the export instructions](../docs/APP_DIAGNOSTICS.md).

Scanner filters, event ID, pair/window, Model Lab period/model/event/seed and
monitor feature selection are URL-backed. Copy the browser address to preserve
the selection. Event investigation is hidden from the sidebar and opens from a
Scanner row; saved event URLs still work. Teammates must use the same published export; links do not pin
an immutable data release. The investigation page keeps contemporaneous evidence
separate from later outcomes, and never computes a new forecast or agent answer.

# Read-only research applications

The deployed research workspace presents saved development outputs through 2023.
Browsing does not download, fit, call an LLM, write analytical results or unlock
final-test outcomes. Model-specific interpretation belongs in the academic report.

```shell
uv run --frozen streamlit run app/research_app.py
# On an imported team snapshot:
python scripts/team.py research-app
```

| View | Contents |
|---|---|
| Overview | Seven models/policies and four book variants, with shared period selection. |
| Forecasting | Four matched population forecasters; deterministic baseline outcomes; Full's matched desk comparison; saved ROC/calibration figures, definitions and CSV export. |
| Portfolio | R0 with/without monitor, bagged-forecaster and Full books; available NAV/drawdown; frozen policy benchmark, costs, thresholds, paired bootstrap and withheld trades. |
| Event explorer | Fixed-20 registry inputs, ACTIVE status and observed outcomes, filters and CSV export. |
| Pair detail | Saved prices, spread bands, monthly relationship diagnostics and point-in-time SEC evidence. |
| Evidence and diagnostics | Availability, source coverage, event counts, feature distributions, agent coverage, selection diagnostics and source identities. |
| Rules and definitions | Current model families/inputs, chronology, fixed forecast/book rules, metrics and limitations. |

Baseline 0/1 are deterministic policies, not calibrated probability models. Full
forecasting uses the selected top-40% desk region with its matched logistic base.
The four current books share development periods; two have daily curves exported.
The frozen policy benchmark uses 2022–2023, next-open execution and a fixed
20-session cap, separately identified from current book results.

There is no earlier-study menu or horizon switch. Underlying registry views never
show superseded fitted probabilities or explanations as current predictions.
Current per-event scores/SHAP and additional book curves remain explicitly absent
until a reviewed saved-output export supplies them.

## Presentation data

`demo/book/presentation.json` pins the summary, daily NAV, seven-model catalogue
and saved confirmation diagnostic figures by SHA-256. `SB_RESEARCH_SUMMARY`
selects an explicit alternative directory. All bytes participate in cache
identity; invalid data is withheld. These hashes identify presentation bytes,
not scientific acceptance. See [the export contract](../docs/FRONTEND_WORKSPACE.md).

```shell
python scripts/export_research_diagnostics.py --outputs-root PATH_TO_OUTPUTS
python scripts/export_research_presentation.py
```

These explicit writers export development results into this checkout. They never
fit a model or modify the source output directories. Without an outputs path,
only published rounded selection-period desk values are included. Final-test
publication requires a separate authorized export/schema update.

Registry and policy diagnostics use `SB_APP_BUNDLE`, then `demo/app_bundle`, then
an explicitly accepted workspace (`SB_WORKSPACE_ROOT`, default `data/research_v2`).
Those files are independently checked and load only when needed. Missing registry
files do not hide the current forecast/book summaries. Pair histories cover the
bundle's showcase subset; unavailable histories remain marked unavailable.

To export an existing accepted snapshot for registry/policy investigation:

```shell
python scripts/team.py app-bundle --output outputs/app-bundles/v2
uv run --frozen structural-break-app verify --bundle outputs/app-bundles/v2
```

The synthetic bundle command remains available for offline development. Its
invented registry data is labelled synthetic and cannot replace the separately
verified current summary. See [team setup](../docs/GROUP_QUICKSTART.md).

## Streamlit Community Cloud

Use the reviewed branch with `demo/book` and `demo/app_bundle`, main file
`app/research_app.py`, Python 3.11 and the committed requirements/lockfile. No
provider secrets are needed. Theme/fonts use `.streamlit/config.toml`. The
frontend PR targets `deploy`; publishing and final-test changes are separate.

## Minimal verified view

```shell
uv run --frozen --extra nlp streamlit run app/streamlit_app.py
```

The default workspace is `data/research_v2`. Set `SB_WORKSPACE_ROOT` in the
ignored `.env` or process environment to select a restored workspace. Results
appear only after a complete, independently verified generation is explicitly
published; missing outputs show a pending state and failed verification shows an
error.

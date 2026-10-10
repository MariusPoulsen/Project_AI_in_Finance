> **Original experiment reference.** These instructions describe the recorded
> 28-pair source/config generations. Use their original workspace and freeze;
> the active expanded workflow is in [the v2 runbook](../../RESEARCH_V2_RUNBOOK.md).
> Commands below use the explicit reference CLI.

# Divergence dataset, Model A and the read-only app

Phase 3 turns frozen quantitative relationships into one observation per divergence
episode, point-in-time Model A features, chronological development labels, a logistic
benchmark, calibrated XGBoost and stored SHAP explanations. Explicit batch jobs own
all analytical writes. The Streamlit shell reads the published generations.

## Install and run the offline acceptance fixture

Use the committed Python 3.11 environment and lockfile. Quantitative research and
Streamlit dependencies install by default; `--extra app` remains a supported alias:

```shell
uv sync --frozen --extra app
uv run --frozen structural-break-reference build-events --ml-fixture --workspace-root .acceptance/phase3 --event-version fixture-events-p3
uv run --frozen structural-break-reference train-model-a --workspace-root .acceptance/phase3 --model-version fixture-model-a-p3
uv run --frozen structural-break-reference verify-model-a --workspace-root .acceptance/phase3
```

The independent Phase 3 fixture provides known event paths, quantitative inputs and
enough synthetic development observations to exercise the actual publication,
training, reload and inference pipeline. It requires no provider credentials or
network after package installation. Synthetic metrics describe the fixture only.

For real research, first verify the active Phase 1 and Phase 2 generations, then run:

```shell
uv run --frozen structural-break-reference verify-data
uv run --frozen structural-break-reference verify-relationships
uv run --frozen structural-break-reference build-events
uv run --frozen structural-break-reference train-model-a
uv run --frozen structural-break-reference verify-model-a
```

These commands use the local frozen source and econometric history. Dataset/model
identities are immutable: a changed computation requires a new generation. Repeating
the same published identity verifies its existing outputs. `--workspace-root` selects
the storage workspace; it does not change the scientific configuration.

## Earlier history and the chronological split

The frozen market history begins on 2014-01-02. The first 504 common sessions supply
formation warm-up, so usable frozen daily relationship states begin on 2016-01-04.
Training now uses eligible events in 2016–2021. Validation stays 2022–2023 and the
locked final test stays 2024–2025. This adds observable early episodes without
shortening the formation window or moving the evaluation boundaries.

At every outer and forward-fold boundary, exclude events whose predeclared full
10-session label horizon/embargo reaches into the next partition. Early events must
meet the same ACTIVE eligibility and feature-completeness requirements as later
events. The split and label-policy versions expose this change. The original
2018–2021 training window can later be evaluated as a prespecified development
sensitivity; it is not selected by final-test performance.

Before deduplication and feature-quality filtering, the real source history has
23 ACTIVE fresh crossings in 2016–2017, 59 in 2018–2021 and 11 in 2022–2023.
SEC filing metadata covers the same 55 issuers in every year from 2014 through
2023. Filing-body retrieval and structured evidence quality remain Phase 4 work.
The uncovered issuer is XOM: the current ticker mapping uses successor registrant
CIK 0002115436 after its July 2026 reorganisation, while the historical issuer used
CIK 0000034088. The [SEC successor filing](https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm)
documents the transition. Phase 4 must resolve the dated historical mapping in a
new source generation and preserve explicit UNKNOWN coverage until then. This
does not affect quantitative Model A prices, and it does not justify dropping
XOM/CVX events or treating missing evidence as an absence of catalysts.

## Frozen episode and target policy

An event opens on an ACTIVE fresh outward crossing of `|z| >= 2`. Only one episode
may remain unresolved for a pair. After resolution, another event requires a return
inside the entry band and a subsequent fresh outward crossing. Daily state and entry
metadata preserve the fixed A-on-B orientation and exact relationship snapshot.

The future path uses the entry event's frozen alpha, beta, spread mean and standard
deviation. The target starts on the next XNYS session. Success means `|z| <= 0.5`
before the same-side `|z| >= 3` stop and within 10 sessions; stop or timeout is failure.
An unusable future price/lifecycle observation censors the target. Missing sessions
are never filled or skipped to create a valid outcome. Label resolution metadata
remains separate from the predictor table.

All quantitative windows end at event close. Predictors exclude pair/ticker identity
and all target/outcome fields. The feature schema fixes order, definitions and
permitted missingness; price, context and snapshot timestamps are checked against
the event cutoff. VIX uses the exact previous XNYS session. Log-price residual
features use the entry frozen coefficients throughout their trailing lookbacks.

Final-period feature/event paths are implemented while the final outcome lock stays
closed. Their labels and resolution/adverse metadata are not available to training,
calibration, metric generation or the Phase 3 presentation shell.

## Training, calibration and uncertainty

The logistic benchmark uses training-only preprocessing and the same quantitative
information as Model A. XGBoost hyperparameters are selected through chronological
forward folds inside training, with fold-level embargo. No random split or final-test
label influences preprocessing, fitting, tuning or SHAP reference selection.

The frozen XGBoost margins receive a validation-only monotone sigmoid calibration.
Its fitted slope cannot reverse model ranking. A single-class validation sample or
constant margin cannot identify a discrimination slope; the saved calibrator records
an explicit smoothed constant mapping and its status. The model card identifies
this prior assumption and the absence of validation evidence for discrimination.

The frozen project-data run has 60 eligible training events (nine successes) and
seven validation events (zero successes). Calibration therefore saves
`CONSTANT_UNIDENTIFIABLE`, with probability `1/9` for every event. The app exposes
this limitation. Raw scores and Tree SHAP remain available for research diagnostics,
but this validation sample cannot establish useful ranking or calibrated forecasts.
The 2016–2017 extension adds 16 eligible training episodes after deduplication.
See [the acceptance record](../IMPLEMENTATION_HISTORY.md) for partition counts and development metrics.

The real validation sample is too small to support reliable threshold optimisation.
The working candidate threshold remains the prespecified 0.65, with a development
sensitivity table. Calibrated validation metrics describe the sample used to fit the
calibrator; they are not an independent estimate of calibration performance. Report
sample/class/selected-event counts alongside every metric. Low sample size and pair
concentration limit conclusions regardless of the apparent ranking score.

The bundle contains the model, logistic preprocessing, calibrator, ordered feature
schema, threshold policy, split/lineage metadata, model card, training SHAP reference
sample and development predictions. Verification checks registered hashes before
loading. Reloaded probabilities must reproduce the stored inference results. Tree
SHAP explains the raw XGBoost margin; calibrated probability is a separate mapping.
SHAP contributions describe model associations, not causal financial mechanisms.

## Launch the app

From the repository containing a published relationship generation:

```shell
uv run --frozen --extra app streamlit run app/streamlit_app.py
```

For another workspace, set `SB_WORKSPACE_ROOT` in the process environment. For
example, in PowerShell:

```powershell
$env:SB_WORKSPACE_ROOT = ".acceptance/phase3"
uv run --frozen --extra app streamlit run app/streamlit_app.py
```

Scanner displays the selected research session's frozen pair states. Pair Detail
shows daily spread/z history, the effective monthly estimate, raw crossing history,
and any stored Model A event scores/explanations. The date selector stops at the
development boundary in Phase 3. Predictions are labelled research replay, with
model/calibrator/schema/policy versions; training-fit and validation-development
scores remain distinguishable. No target/outcome fields are sent to presentation.

No app callback ingests data, builds features, trains models, writes canonical rows
or makes provider calls. Missing state, missing predictions and corrupt/version-mismatched
outputs have explicit messages. A missing Model A generation leaves quantitative
history available; it does not fabricate a probability. Full controller decisions,
SEC evidence, agents and backtest performance arrive in their owning phases.

## Verification

```shell
uv run --frozen --extra app ruff check .
uv run --frozen --extra app ruff format --check .
uv run --frozen --extra app mypy
uv run --frozen --extra app pytest
```

Tests block external network access. Event/label fixtures verify convergence, stop,
timeout, censoring, episode reset and embargo. Feature checks perturb future inputs
and reject post-cutoff source timestamps. Model tests cover training-only fits,
chronological tuning, final-test lock, calibration, reload and SHAP additivity.
App query tests use published synthetic relationships and assert read-only
connections, exact session/snapshot selection and version checks. Streamlit's
[AppTest](https://docs.streamlit.io/develop/api-reference/app-testing) renders Scanner,
Pair Detail and empty/error states without starting batch jobs.

# Project_AI_in_Finance

Group members: see [GROUP_QUICKSTART.md](docs/GROUP_QUICKSTART.md) for the prepared
offline setup, app, existing-model inference and backtest-input handoff. The real
working snapshot will be exported after v2 acceptance.

AI Structural-Break Detector for Statistical Arbitrage: a reproducible research
system comparing quantitative Model A with SEC-augmented Model B. Research v2
uses 250 frozen issuers and 736 fixed business-peer pairs, with separate fitting,
calibration and assessment periods.

**Current delivery:** the 37,421-event feature build stopped at 4,727 preserved
checkpoints. Recovery uses a new audited batch, `development_prefetch_v2`, with
bounded parallel SEC preparation and one unchanged CPU FinBERT model. Saved
launch/progress/exit receipts establish its actual running state. This count
is the development union, not an assessment sample or a success count. Actual
model fits, independent verification, publication and GitHub `main` promotion
remain pending. Model B improvement has not been established. See
[STATUS.md](docs/STATUS.md) for the current gates and operational evidence.

`structural-break` is the research CLI in this checkout;
`structural-break-research` is its compatible research alias.
`structural-break-reference` reproduces the original experiment in a separate
workspace. GitHub `main` remains on the earlier release until v2 acceptance.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run from
the repository:

```shell
uv python install 3.11
uv sync --frozen --extra nlp
uv run --frozen --extra nlp structural-break --help
```

The project has its own Python 3.11 `.venv` and committed `uv.lock`; it needs no
Jupyter package. Retain `--extra nlp` on commands using FinBERT. Linux uses CPU
PyTorch. Gemma uses direct REST and does not need the optional `agents` extra.
On Windows/OneDrive, `$env:UV_LINK_MODE = "copy"` can avoid uv file-locking issues.

For source acquisition and Gemma extraction, set these in the ignored `.env` or
process environment:

- `SB_SEC_USER_AGENT`: project name and a real SEC contact email.
- `SB_LLM_API_KEY`: the free Google API key for guarded Gemma extraction.

No Yahoo, SEC or local database login is required. Never put credentials in Git,
YAML, command arguments or output. [Google Colab](docs/COLAB.md) uses the same
locked environment and supplies credentials through Colab Secrets.

The default workspace is `data/research_v2`. To relocate it, pass
`--workspace-root` or set `SB_WORKSPACE_ROOT` for both CLI and app; an explicit CLI
path takes precedence. Use `--project-root` when launching outside the repository.
Source clones contain no generated data or model weights.

## Run the study

Read the [protocol](docs/RESEARCH_V2_PROTOCOL.md) and
[runbook](docs/RESEARCH_V2_RUNBOOK.md) before launching jobs. Preserve the active
local build and its frozen source. Its detached-launch receipt supplies a manual
progress command; the runbook describes audited recovery.

For a **new workspace**, create its source and registry generations explicitly:

```shell
uv run --frozen --extra nlp structural-break freeze-universe --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break capture-market --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break collect-sec --sec-source source_v3 --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break build-registry --workers 2 --workspace-root NEW_WORKSPACE
```

Use the exact printed `research_version` as `REGISTRY_VERSION`, and choose a new
immutable `BATCH_NAME`. A new vendor capture is a different research generation.
Reproduction instead restores the verified workspace and exact recorded source.

```shell
uv run --frozen --extra nlp structural-break build-intelligence --registry-version REGISTRY_VERSION --batch-name BATCH_NAME --sec-source source_v3 --sentiment-preprocessing sec-sentence-quality-wordpiece-v2 --catalyst-max-events 500 --download-model --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break train-models --registry-version REGISTRY_VERSION --batch-name BATCH_NAME --horizon 20 --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break train-models --registry-version REGISTRY_VERSION --batch-name BATCH_NAME --horizon 10 --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break train-models --registry-version REGISTRY_VERSION --batch-name BATCH_NAME --horizon 30 --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break verify-models --model-version MODEL_VERSION --workspace-root NEW_WORKSPACE
```

Verify each printed model evaluation version. Remove `--download-model` once the
pinned FinBERT assets are cached. The frozen 500-event Gemma pilot is separate from
full SEC/metadata/FinBERT processing; unscheduled or invalid catalysts remain
UNKNOWN. Do not edit computational source while jobs run or overwrite registered
outputs. Changed inputs require a new immutable generation.

## Interpretation and acceptance

The primary comparison is calibrated logistic B-both versus matched A at 20
sessions. Report every predeclared ablation, both model families and 10/30-session
sensitivities, including unfavorable results, coverage and paired uncertainty.
Fit events begin in 2006 after a 504-session warm-up from 2004 sources: fit through
2019, tune on forward 2018/2019 folds, calibrate on 2020–2021 and assess on
2022–2023. **2024–2025 outcomes remain locked** until explicitly authorized.

Predictors must be available by event close, including previous-session VIX and
conservatively timed SEC evidence. UNKNOWN evidence is not neutral or confirmed
absence. The surviving-issuer roster, current classifications, retrospective
Yahoo adjustments and modern text models used on historical filings are disclosed
research limitations. Forecast quality does not establish trading profitability.

After all three genuine evaluations and independent checks pass, publish with the
completed pipeline receipt and its bound hosted-CI evidence:

```shell
uv run --frozen --extra nlp structural-break promote-primary --pipeline-receipt PIPELINE_RECEIPT --ci-gate CI_GATE_RECEIPT --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp streamlit run app/streamlit_app.py
```

Set `SB_WORKSPACE_ROOT` to the same workspace before opening the app.
Publication performs fresh source and native-model verification. The
[read-only app](app/README.md) displays only accepted generations and clearly
reports missing/incomplete outputs. Publication does not itself merge GitHub
`main`, establish B improvement or unlock final-test outcomes.

## Development and documentation

```shell
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen pytest
```

Tests use deterministic offline fixtures, with network sockets blocked. Genuine
source/model acceptance is a separate gate. Release checks include Windows/Linux
CI, the Colab Python 3.11 bootstrap and independent replay of all actual evaluations.

- Current research: [protocol](docs/RESEARCH_V2_PROTOCOL.md),
  [runbook](docs/RESEARCH_V2_RUNBOOK.md), [Colab](docs/COLAB.md),
  [status](docs/STATUS.md).
- Governance: [decisions](docs/DECISIONS.md), [plan](docs/PLAN.md),
  [specifications](docs/specs/README.md).
- [Archive](docs/archive/README.md): original reproduction runbooks for
  [data](docs/archive/reference/DATA_RUNBOOK.md),
  [econometrics](docs/archive/reference/ECONOMETRICS_RUNBOOK.md),
  [Model A](docs/archive/reference/ML_RUNBOOK.md) and
  [SEC/Model B](docs/archive/reference/INTELLIGENCE_RUNBOOK.md).

Original sources, configurations, artifacts and Git history remain reproducible;
use their recorded versions and separate workspace with the reference CLI/app.
Only source, configurations, small fixtures and technical documentation belong
in Git. Generated data, databases, artifacts, environments and secrets are ignored.
The user owns the academic report and presentation/video.

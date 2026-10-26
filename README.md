# Project_AI_in_Finance

Group members: see [GROUP_QUICKSTART.md](docs/GROUP_QUICKSTART.md). Set up from the
official accepted snapshot `group-v2.zip` with
`python scripts/team.py setup --snapshot PATH/TO/group-v2.zip --sha256 <CHECKSUM>`.
The checksum is shared with the snapshot, and the provisional pack is superseded.

AI Structural-Break Detector for Statistical Arbitrage: a reproducible research system
that forecasts whether a diverged stock pair reverts (Goal 1) and trades the best book on
top of the forecasts (Goal 2). The study uses 250 frozen issuers and 736 fixed
business-peer pairs; everything up to 2023 is built and evaluated, and the 2024–2025 final
test stays locked until the owner's unlock record.

| Part | Package | Status |
|---|---|---|
| Data, relationships, divergence events, Model A and SEC-augmented Model B | `research`, `econometrics`, `ml`, `intelligence` | Accepted (Decision 34) |
| Plan-ladder backtests (Baseline 0/1, Models A/B) on 2022–2023 | `backtest` | Accepted for development (Decisions 35–42) |
| Inputs for the forecasters and the book | `pipeline` | Reproducible (`pipeline.build_inputs`) |
| Forecasters: Model B (R0) and the bagged feature-set models | `forecast` | Holdout ROC-AUC 0.718 → 0.735 (pre-registered) |
| Trading book | `book` | Sharpe 0.713, +2.7 % CAGR (+3.5 % with cash), 2010–2023 (Decision 110d) |
| Agent desk: news analyst, debate, risk judge, position monitor | `agents` | Monitor exit adopted; entry agents add nothing (Decision 110d) |

The book's Sharpe does not survive a correction for the number of designs tried (deflated
Sharpe 0.86, PBO 0.54; Decision 113); the locked final test is the clean test. See
[PLAN.md](docs/PLAN.md) for status and open items,
[FORECASTING_AND_BOOK.md](docs/FORECASTING_AND_BOOK.md) and [AGENT_DESK.md](docs/AGENT_DESK.md)
for the design and results.

`structural-break` is the research CLI in this checkout;
`structural-break-research` is its compatible research alias.
`structural-break-reference` reproduces the original experiment in a separate
workspace. `structural-break-backtest` runs the plan-ladder backtests (below).

## Research application

`app/research_app.py` is the full read-only application (PLAN P7): Overview,
Scanner, Pair detail, Model Lab, Strategy Lab, Data and model monitor, and
Methodology. It shows the spread with its entry/convergence/stop bands, both
models' calibrated probabilities for every development event, exact feature
contributions of the saved models (linear SHAP for logistic, TreeSHAP for
XGBoost), the full A/B ablation ladder with paired intervals, the Phase 6
backtest ladder, SEC coverage and data/model provenance on every page.

```shell
python scripts/team.py research-app                       # on the imported snapshot
python scripts/team.py app-bundle --output outputs/app-bundles/v2   # small deployable bundle
uv run --frozen structural-break-app synthetic --output outputs/app-bundles/synthetic  # invented preview
```

Data sources, bundles, the synthetic preview and Streamlit Community Cloud
deployment are described in [app/README.md](app/README.md). `requirements.txt` is
exported from `uv.lock` for hosts that install with pip.

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
YAML, command arguments or output.

The default workspace is `data/research_v2`. To relocate it, pass
`--workspace-root` or set `SB_WORKSPACE_ROOT` for both CLI and app; an explicit CLI
path takes precedence. Use `--project-root` when launching outside the repository.
Source clones contain no generated data or model weights.

## Run the study

Read the [protocol](docs/RESEARCH_PROTOCOL.md) and
[runbook](docs/RESEARCH_RUNBOOK.md) before launching jobs. Preserve the active
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

## Plan-ladder backtests

One shared engine, governed by DECISIONS 30–45, applies the same execution
convention to every strategy rung:

- signal at the close, entry at the next open;
- frozen beta-weighted share units;
- convergence, adverse-stop and timeout exits;
- the frozen costs, borrow and eligibility rules.

The runbook is [BACKTEST_RUNBOOK.md](docs/BACKTEST_RUNBOOK.md). On an imported
accepted workspace:

```shell
uv run --frozen structural-break-backtest p6-acceptance --workspace-root data/team --output-dir .acceptance/p6-official
uv run --frozen structural-break-backtest final-test-gate --freeze-manifest FREEZE_MANIFEST
```

`p6-acceptance` does the following for h20, h10 and h30:

1. runs the accepted historical experiment;
2. replays it independently;
3. writes the target-blind policy diagnostics;
4. writes a freeze manifest.

The official run takes about 2 hours on one thread. Results are post-hoc
2022–2023 development results. Unknown executions are never counted as zero
returns.

`final-test-gate` refuses unless an owner-written unlock record binds the
freeze manifest. It never fetches or runs 2024–2025 data.

The forecasters, the trading book and the agent desk build on this engine; their inputs are
rebuilt and checked with `python -m structural_break.pipeline.build_inputs` and
`python scripts/verify_book.py` (see [FORECASTING_AND_BOOK.md](docs/FORECASTING_AND_BOOK.md)).

## Known issues and planned enhancements

- The deployed demo bundle carries daily history for a showcase subset of
  pairs; the full workspace view shows every pair.
- SEC filing text is not in the group snapshot, so the app shows SEC *feature*
  evidence per event rather than cited filing passages.
- The multi-agent Full System is deferred (DECISIONS 40); the app shows it as
  not run rather than inventing agent output.
- Planned: agent cases and controller reason codes once an accepted controller
  generation exists; cited filing chunks if a text-bearing demo snapshot is
  approved; final-test pages only after the owner's explicit unlock.

## Development and documentation

```shell
uv sync --frozen --extra agents
uv run --frozen --extra agents ruff check .
uv run --frozen --extra agents ruff format --check .
uv run --frozen --extra agents mypy
uv run --frozen --extra agents pytest
```

Tests use deterministic offline fixtures, with network sockets blocked. Genuine
source/model acceptance is a separate gate. Release checks include Windows/Linux
CI and independent replay of all actual evaluations.

The agent desk is documented in [AGENT_DESK.md](docs/AGENT_DESK.md). The plan ladder's Full
System rung needs a controller adapter under the frozen Decision 36 policy (Decision 40)
and is otherwise reported as not run.

- Research study: [protocol](docs/RESEARCH_PROTOCOL.md),
  [runbook](docs/RESEARCH_RUNBOOK.md).
- Forecasters, book and agents: [FORECASTING_AND_BOOK.md](docs/FORECASTING_AND_BOOK.md),
  [AGENT_DESK.md](docs/AGENT_DESK.md), [NEWS_2024_2025.md](docs/NEWS_2024_2025.md).
- Backtesting: [runbook](docs/BACKTEST_RUNBOOK.md); earlier results in the
  [archive](docs/archive/README.md) (development, improvement, SEC features, boosting).
- Governance: [decisions](docs/DECISIONS.md), [plan and status](docs/PLAN.md),
  [names](docs/NAMES.md), [specifications](docs/specs/README.md).
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

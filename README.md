# Project_AI_in_Finance

AI Structural-Break Detector for Statistical Arbitrage: a reproducible research
system comparing quantitative Model A with SEC-augmented Model B. Research v2
is the primary development workflow. It expands the frozen roster to 250 issuers
and 736 fixed pairs, uses earlier history, and separates fitting, calibration and
assessment. The completed original Phase 0–4 experiment remains a reproducible
reference; its artifacts are not overwritten.

**Release state:** the partial quality-v2 feature batch was intentionally stopped
with 1,494 checkpoints preserved. The replacement `development_primary_v2` awaits
the reviewed operational fix and source freeze. The full scheduled development
union contains 37,421 distinct pair/time events; this is not an assessment sample
size or a count of successes. Actual model fits, independent verification and
main-branch promotion are pending. No improvement of B over A has been established.
See [completion evidence](docs/STATUS.md) for the accepted revision and current gates.

The primary command in the promoted release is `structural-break`;
`structural-break-research` remains the compatible research alias. Until that
promotion is accepted, use `structural-break-research` for the v2 examples below.
The promoted release preserves original commands as `structural-break-reference`.

## Local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run from
the repository:

```shell
uv python install 3.11
uv sync --frozen --extra nlp
uv run --frozen --extra nlp structural-break --help
```

The project uses its own Python 3.11 `.venv` and committed lockfile. It does not
modify the course environment in `../Ai_in_Finance` and needs no Jupyter package.
The `nlp` extra supplies local FinBERT dependencies; retain it on subsequent
`uv run` commands that use those dependencies. Gemma uses direct REST and does not
require the optional `agents` extra. The Linux lock selects CPU PyTorch; the
documented pipeline does not require a GPU.

On Windows/OneDrive, `$env:UV_LINK_MODE = "copy"` can avoid uv file-locking issues
in the current PowerShell session.

V2 defaults to `data/research_v2`, with a separate local DuckDB database and immutable
source, evidence and model generations. Use `--project-root` when launching from
another directory and pass `--workspace-root` explicitly to use another workspace.
Relative workspace paths resolve against the repository. `SB_WORKSPACE_ROOT` also
sets the workspace for the CLI and read-only app; an explicit CLI path takes
precedence. Keep the original workspace separate. Source checkouts do not include
generated data or model weights.

For real source jobs, put the following in the ignored local `.env` or the process
environment:

- `SB_SEC_USER_AGENT`: project name and a real contact email for SEC downloads.
- `SB_LLM_API_KEY`: the free Google API key for guarded Gemma extraction.

No Yahoo, SEC or local database login is required. Never put credentials in YAML,
Git, command arguments or output. [Google Colab setup](docs/COLAB.md) uses the same
locked package, with credentials supplied through Colab Secrets.

## Run the primary study

Read [the frozen protocol](docs/RESEARCH_V2_PROTOCOL.md) and
[the batch runbook](docs/RESEARCH_V2_RUNBOOK.md) first. For a new workspace:

```shell
uv run --frozen --extra nlp structural-break freeze-universe
uv run --frozen --extra nlp structural-break capture-market
uv run --frozen --extra nlp structural-break collect-sec --sec-source source_v3
uv run --frozen --extra nlp structural-break build-registry --workers 2
```

The registry command prints `research_version`. Use that exact identity as
`REGISTRY_VERSION` below. Reuse a verified existing source/registry generation
when reproducing the accepted study; do not create a fresh vendor capture and
call it the same research run.

```shell
uv run --frozen --extra nlp structural-break build-intelligence --registry-version REGISTRY_VERSION --batch-name development_primary_v2 --sec-source source_v3 --sentiment-preprocessing sec-sentence-quality-wordpiece-v2 --catalyst-max-events 500 --download-model
uv run --frozen --extra nlp structural-break train-models --registry-version REGISTRY_VERSION --batch-name development_primary_v2 --horizon 20
uv run --frozen --extra nlp structural-break train-models --registry-version REGISTRY_VERSION --batch-name development_primary_v2 --horizon 10
uv run --frozen --extra nlp structural-break train-models --registry-version REGISTRY_VERSION --batch-name development_primary_v2 --horizon 30
uv run --frozen --extra nlp structural-break verify-models --model-version MODEL_VERSION
```

Each fitting command prints an evaluation version; verify every printed version.
The primary comparison is calibrated logistic B-both versus matched A at 20
sessions. Ten- and thirty-session results and the other model families/feature
ablations are predeclared sensitivities, not a menu for choosing a better headline.
Report sample sizes, successes, source coverage and paired uncertainty even when
results are negative or inconclusive. Forecast quality does not establish trading
profitability.

FinBERT processes admitted SEC text locally with pinned weights and exact cache
identities. The versioned quality guard retains source offsets and reports excluded
and unscored coverage. UNKNOWN text or metadata is not neutral sentiment or confirmed
absence. The 500-event Gemma pilot is separately balanced across year/business group
without reading labels; it leaves unscheduled catalysts UNKNOWN while full source,
metadata and FinBERT processing remain scheduled. Its 1,000-call ceiling per invocation
includes retries; resumptions do not reconstruct a durable quota counter for failed
calls. Flash is reserved for later source-grounded agents. Remove `--download-model`
after the pinned assets are cached. Changed policies require a new immutable batch.

Do not edit computational source files while a registry or model fit runs. Identical
inputs can reuse verified checkpoints; registered outputs and historical partial
batches are preserved. The runbook describes recovery and partial-pilot flags.

## Dates and research limits

Sources begin in 2004, supplying the 504-session formation warm-up. Eligible v2
fitting events begin in 2006: fit through 2019, tune with forward 2018/2019 folds,
calibrate on 2020–2021, and assess on 2022–2023. Full target horizons are purged at
partition boundaries. **2024–2025 outcomes remain locked** until the method is
frozen and the user explicitly authorizes the final run.

Every predictor and evidence item must be available by event close. Previous-session
VIX is used. SEC clock ambiguity uses conservative admission bounds, issuer
continuity checks and source provenance; uncertain boundary coverage stays UNKNOWN.
Yahoo adjusted history is a retrospective vendor snapshot. The roster uses surviving
issuers and current business classifications, so it is not a historically complete
investable universe. Modern FinBERT/Gemma extraction on historical text is a
retrospective research assumption; source timestamps do not make those models
available in earlier years. The earlier 28-pair assessment was already observed.
See the protocol for these limits and the eight-quarter assessment uncertainty.

## Read-only app and verification

After all three genuine model evaluations and independent verifications succeed,
publish readiness using their completed pipeline receipt and its bound hosted-CI
evidence:

```shell
uv run --frozen structural-break promote-primary --pipeline-receipt PIPELINE_RECEIPT --ci-gate CI_GATE_RECEIPT
```

This command prints `primary_version` and records the accepted publication only
after fresh source and native-model checks. Use exact receipts for the reviewed
generation; fixture success or an incomplete pipeline cannot publish readiness.
Publication does not establish B improvement or unlock final-test outcomes.

The promoted primary app is launched with:

```shell
uv run --frozen streamlit run app/streamlit_app.py
```

It requires a restored, independently verified v2 publication. Browsing does not
capture sources, call models, fit estimators or write analytical rows. Publication
selection and readiness are explicit; an incomplete job must not appear as a
successful A/B result. The accepted release instructions and publication identities
are recorded in [STATUS.md](docs/STATUS.md).

Standard development checks are:

```shell
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy
uv run --frozen pytest
```

Tests block network sockets and require neither credentials nor model weights.
Release gates include Windows/Linux CI, the Python 3.12-host to Python 3.11 Colab
bootstrap, and independent reload/reconstruction of all three actual model
evaluations. Offline fixture success is distinct from real-source/evaluation success.

## Original experiment and documentation

The original small Phase 0–4 study remains a reference, including its 2014 source
start, 2016–2021 training period and 2022–2023 validation. Use its historical
checkout/recorded versions, or the promoted `structural-break-reference` alias with
the original workspace. The archived app is `app/reference_streamlit_app.py`.
Do not reinterpret those artifacts under v2 settings.

- Primary: [protocol](docs/RESEARCH_V2_PROTOCOL.md), [runbook](docs/RESEARCH_V2_RUNBOOK.md),
  [Colab](docs/COLAB.md), [completion evidence](docs/STATUS.md).
- Governance: [decisions](docs/DECISIONS.md), [plan](docs/PLAN.md),
  [specification index](docs/specs/README.md).
- Original reproduction: [data](docs/DATA_RUNBOOK.md),
  [econometrics](docs/ECONOMETRICS_RUNBOOK.md), [Model A](docs/ML_RUNBOOK.md),
  [SEC/Model B](docs/INTELLIGENCE_RUNBOOK.md).

Only source, configurations, small fixtures and technical documentation belong in
Git. Generated data, databases, artifacts, virtual environments and secrets are
ignored. The user owns the final academic report and presentation/video.

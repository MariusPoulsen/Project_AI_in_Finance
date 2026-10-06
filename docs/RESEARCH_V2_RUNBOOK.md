# Research v2 batch runbook

This is the separately versioned experiment authorized on 2026-10-06. Read
[the frozen protocol](RESEARCH_V2_PROTOCOL.md) before interpreting its results.
The default workspace is `data/research_v2`, with its own DuckDB database,
immutable sources, pair caches, evidence batches and fitted models. The original
P4 workspace and its 2024–2025 outcome lock remain in place.

## Install and configure

```shell
uv sync --frozen --extra nlp
uv run --frozen --extra nlp structural-break-research --help
```

Python 3.11 and the committed lockfile apply on Windows and Linux/Colab.
The optional `nlp` extra adds CPU PyTorch and Transformers. Every subsequent
`uv run` performing FinBERT inference must retain `--extra nlp`. The standard
offline tests use mocked inference and require neither model weights nor API
credentials. Gemma uses the direct Google REST adapter; no `agents` extra is
needed for v2. Flash remains reserved for P5.

Put `SB_SEC_USER_AGENT` and `SB_LLM_API_KEY` in the ignored local `.env`, or the
equivalent process environment/Colab Secrets. Never paste keys in commands,
YAML, logs or notebook output. The contact identity is required for SEC public
downloads; no SEC, Yahoo or database login is needed.

## Source freezes

Run from the repository. An explicit `--workspace-root` relocates the complete
v2 workspace. The following source directories are immutable; use a new
workspace for a different roster or capture policy.

```shell
uv run --frozen --extra nlp structural-break-research freeze-universe
uv run --frozen --extra nlp structural-break-research capture-market
uv run --frozen --extra nlp structural-break-research collect-sec
uv run --frozen --extra nlp structural-break-research build-registry --workers 2
```

The roster freezes 250 issuers, 736 pairs and the original 28 orientations before
labels. Prices end in 2023. Source failures remain disclosed exclusions. An
explicit `--tickers` or `--max-issuers` creates a partial source dry run, not a
complete study. The registry writes its source/protocol/code freeze before any
added labels, then caches each pair separately. Keep computational source files
unchanged while it runs. A matching rerun verifies and reuses complete pairs.

The last registry command prints `research_version`. Supply that exact value in
subsequent commands; do not infer it from directory modification times.

The original `sec_metadata/source_v1` capture remains immutable. A cached-header
diagnostic matched 186 of 250 sampled acceptance times under the earlier JSON
normalizer; 49 were four hours later and 15 five hours later, with no premature
case in this sample. This is not a complete audit of its 89,657 filings. New
research evidence uses the conservative UTC/New York availability upper bound,
with boundary-straddling and missing times kept UNKNOWN. Derive
`sec_metadata/source_v2` by a frozen, zero-network replay of the verified v1 raw
responses, following [SEC_METADATA_RECAPTURE.md](SEC_METADATA_RECAPTURE.md).
Do not point a new-policy collection command at the completed v1 directory.
Pass `--sec-source source_v2` to source/evidence commands that accept it. Model
fitting must resolve the exact SEC source bound by the evidence parent manifest.

## SEC text, inference and fitting

Replace `REGISTRY_VERSION` below with the printed version. `development_v1` is
an explicit new batch name, not an instruction to replace an older batch.

```shell
uv run --frozen --extra nlp structural-break-research build-intelligence --registry-version REGISTRY_VERSION --batch-name development_v1 --download-model
uv run --frozen --extra nlp structural-break-research train-models --registry-version REGISTRY_VERSION --batch-name development_v1 --horizon 20
uv run --frozen --extra nlp structural-break-research train-models --registry-version REGISTRY_VERSION --batch-name development_v1 --horizon 10
uv run --frozen --extra nlp structural-break-research train-models --registry-version REGISTRY_VERSION --batch-name development_v1 --horizon 30
uv run --frozen --extra nlp structural-break-research verify-models --model-version MODEL_VERSION
```

The model command prints its evaluation version. Verification reloads every
native estimator/calibrator, reconstructs the paired comparison, and verifies
its source/evidence parents without API calls.

FinBERT weights are pinned to the protocol revision and checked locally. The
`--download-model` flag permits acquiring these public assets; omit it after the
cache exists. Inference uses bounded token windows and exact text/model caches.
Tone is a financial sentiment measurement, not a catalyst or reversion label.

Gemma requests are label blind, with 1,000 calls including
retries, eight-second pacing and an explicit quota/authentication stop. Strict
JSON, timestamps, issuer/leg, category cues and exact quote grounding are checked
locally. Invalid or unprocessed events retain UNKNOWN. A completed batch cannot
be overwritten; a new batch may reuse verified sources/inference and retry
missing extractions. `--no-gemma` explicitly requests a tone/metadata batch;
`--no-finbert` explicitly requests a catalyst-only batch. Both retain the same
quantitative cohort. A `--max-events` pilot limits text acquisition and inference,
but metadata features still cover every event; unscheduled text stays UNKNOWN.
Disclose that limitation with the resulting comparison.

Use `--catalyst-max-events 500` for the separately limited Gemma pilot, scheduling
across year/business-group strata without reading labels or scores. The frozen
schedule first covers available UTC years, then unrepresented business groups,
then balances year/group/cell counts with fixed hash tie-breaks. Its manifest
retains exact selected IDs and uncovered margins. The provider-call budget
reserves retries for every selected event, even with cached responses. This flag
limits catalyst inference while leaving full text-source and FinBERT processing
available; representative-NLP-study completeness stays false. Preserve the complete
quantitative cohort and report unscheduled catalysts as UNKNOWN; use a distinct
batch name for another schedule or budget. Keep `--max-events` for an explicit
partial text-source pilot, with its partial-batch completeness flag.
The v2 evidence artifact stores the full source pack and a separate catalyst
pack. An unselected catalyst remains UNKNOWN even when a successful extraction
exists in a shared cache; cache contents cannot silently expand the schedule.

## Recovery and results

Per-event checkpoints and per-pair manifests support ordinary interrupted-job
reruns under identical inputs. Changed code/configuration requires a new
generation. Registered outputs are immutable. A confirmed FAILED publication
archives its unregistered manifest before retrying registration; a RUNNING
record is never assumed dead automatically. Never delete or rewrite a registered
manifest to make a checksum failure disappear.

Each evaluation directory under `artifacts/research` contains `report.json`,
matched `model_inputs.parquet`, probabilities, native models and its manifest.
Report all predeclared feature blocks and all three horizons. The primary
comparison is calibrated logistic B-both versus matched A at 20 sessions;
negative or inconclusive results remain results. A gain selected after inspecting
assessment, a favorable company subset, or dropped UNKNOWN rows is not valid
evidence. Actual sample sizes, positive outcomes, ACTIVE slices, source coverage
and quarter-block uncertainty accompany the metrics.

## Colab

Clone the branch and run `scripts/colab_bootstrap.py --nlp` as shown in
[COLAB.md](COLAB.md), then run the same batch CLI commands with `--extra nlp`.
Keep the virtual environment and active database on `/content`, and archive the
closed workspace between sessions. A current-survivor Yahoo/SEC roster and
modern FinBERT extraction remain disclosed research limitations on either host.

## Acceptance state

Hosted CI for commit `8f10d18` was green before the latest SEC availability guards
and balanced catalyst schedule. That run verifies its own committed revision.
The new guards, schedule and zero-network source_v2 replay require their own
offline checks and capture verification before the first actual Model B fits;
those gates remain pending until their results are recorded.

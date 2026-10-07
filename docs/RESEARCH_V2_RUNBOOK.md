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
diagnostic matched 186 of 250 sampled JSON acceptance times; 49 JSON `Z` values
were themselves four hours later and 15 five hours later, with no premature
case in this sample. This is source clock lag, not solely a naive parser issue,
and not a complete audit of its 89,657 filings. The source-v2 zero-network replay
completed, but its constructed lower bound excluded those 64 earlier SGML
headers. Preserve it as an immutable capture; do not treat it as evidence
admissibility acceptance. Prepare the v3 envelope while preserving its
conservative upper bound, with boundary-straddling and missing times UNKNOWN.
`sec_metadata/source_v3` has now been derived by a frozen, zero-network replay of
the verified v1 raw responses, following
[SEC_METADATA_RECAPTURE.md](SEC_METADATA_RECAPTURE.md).
Do not point a new-policy collection command at the completed v1 directory.
Pass `--sec-source source_v3` to source/evidence commands after its acceptance.
Model fitting must resolve the exact SEC source bound by the evidence manifest.
The v3 guards passed their focused checks and the metadata replay completed;
canonical replay of 250 cached accession inventories also passed, with every
sampled official SGML header inside the envelope and all original raw/retrieval
identities unchanged. Genuine pinned CPU FinBERT inference on V/MA SEC text at
2016-01-08 passed with six chunks, 210 windows and exact cache replay. These
source/inference gates are complete; full feature generation and A/B fits are
still pending.

## SEC text, inference and fitting

Replace `REGISTRY_VERSION` below with the printed version. The proposed batch
`development_quality_v2` needs its own committed code/input freeze before launch.

Legacy batch `development_v3_100e1e4` used frozen main source
`100e1e48`, with 37,421 scheduled events, `--sec-source source_v3` and
`--catalyst-max-events 500`. Neither `--max-events` nor disabled inference was
used. Its progress log is `.acceptance/research_full_intelligence_v3.log`.
It is confirmed STOPPED and incomplete as of 2026-10-07 05:10 UTC: session and
process are absent, and the log ends at 1,494 completed checkpoints at 03:33 UTC
without traceback or terminal manifest. Its cause is unknown; do not label it
an intentional stop, successful completion or confirmed FAILED publication.
The tested quality-v2 replacement is a separate batch, not a resume of this
legacy-policy batch. Record a new code/input freeze before launch.
Preserve the old partial directory
and verified source/Gemma caches; do not overwrite its `inputs.json` or evidence.

```shell
uv run --frozen --extra nlp structural-break-research build-intelligence --registry-version REGISTRY_VERSION --batch-name development_quality_v2 --sec-source source_v3 --sentiment-preprocessing sec-sentence-quality-wordpiece-v2 --catalyst-max-events 500 --download-model
uv run --frozen --extra nlp structural-break-research train-models --registry-version REGISTRY_VERSION --batch-name development_quality_v2 --horizon 20
uv run --frozen --extra nlp structural-break-research train-models --registry-version REGISTRY_VERSION --batch-name development_quality_v2 --horizon 10
uv run --frozen --extra nlp structural-break-research train-models --registry-version REGISTRY_VERSION --batch-name development_quality_v2 --horizon 30
uv run --frozen --extra nlp structural-break-research verify-models --model-version MODEL_VERSION
```

The model command prints its evaluation version. Verification reloads every
native estimator/calibrator, reconstructs the paired comparison, and verifies
its source/evidence parents without API calls.

FinBERT weights are pinned to the protocol revision and checked locally. The
`--download-model` flag permits acquiring these public assets; omit it after the
cache exists. Inference uses bounded token windows and exact text/model caches.
Tone is a financial sentiment measurement, not a catalyst or reversion label.

The authorized preprocessing amendment is
`sec-sentence-quality-wordpiece-v2`. After its tested code freeze, research CLI
inference defaults to that policy; use
`--sentiment-preprocessing exact-sentence-nonoverlap-wordpiece-v1` to
explicitly reproduce `exact-sentence-nonoverlap-wordpiece-v1` in a separate
batch. The domain policy's legacy default and old caches/proofs stay unchanged.
Choose a new batch name for the amended policy and record its exact inputs hash;
never reuse `development_v3_100e1e4` for changed preprocessing.

The input-only audit uses nineteen FIT source events dated 2006-01-03/04,
after cohort labels/counts existed but before any research model assessment.
No labels, scores, calibration/assessment text or final data were inspected.
The legacy bounded scoring plan retains 4,189 windows with median four
WordPieces; the chosen exact-line guard plans 1,259 with median 14 and retains
20,957 of 39,879 raw tokens (52.6%). Both have two UNKNOWN issuer legs out of 38.
This diagnostic is not representative NLP validation or measured inference
speed. The guard preserves short sentences and word-rich lines without merging
table rows, but cannot certify narrative semantics. Record raw offsets,
full-source token denominators and discarded/unscored coverage; no eligible text
means UNKNOWN. The proof and limitations are in
[the protocol amendment](RESEARCH_V2_PROTOCOL.md#fit-input-preprocessing-amendment).
Production receipt `finbert_quality_v2_plan_acceptance.json` confirms these
counts: 8,292 raw physical-line windows, 1,259 eligible/scored and 7,033 excluded;
legacy has 8,720 raw newline-plus-punctuation windows. Both retain the same
39,879-token raw denominator. Quality-v2 excludes 18,922 tokens, with no budget
omissions in this sample, and exactly replays nineteen genuine legacy records.

The amended union builder retains compact feature rows while source packs remain
in immutable per-event records. The FIT audit's 1.37 GB pack-only extrapolation
motivates this memory change; exact output/source equivalence is required.
It is not a reduction in source evidence, event count or model information.

Gemma requests are label blind, with 1,000 calls per invocation including
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
The reporting completion adds natural-log loss with float64 epsilon clipping
for every raw/calibrated bundle, without modifying stored probabilities.
Pair/issuer-balanced losses and descriptive year/ACTIVE/frozen-business-group
metrics are reconstructed by native verification; observed-sector metrics are
also reported. Retain zero-row business groups and explicit small denominators,
with undefined ROC/AP as null. Reports use the same model/cohort rather than
fitting or selecting subgroup-specific models. Produce all ten bundles for each
of the three horizons and independently verify all thirty; only h20 calibrated
logistic B-both versus A is the predeclared primary comparison.

## Colab

Clone the branch and run `scripts/colab_bootstrap.py --nlp` as shown in
[COLAB.md](COLAB.md), then run the same batch CLI commands with `--extra nlp`.
Keep the virtual environment and active database on `/content`, and archive the
closed workspace between sessions. A current-survivor Yahoo/SEC roster and
modern FinBERT extraction remain disclosed research limitations on either host.

## Acceptance state

Hosted CI for `3c01d262` passed the committed offline pipeline, including the
balanced catalyst schedule and v2 metadata guards, on Windows, Linux and Colab.
That run verifies its own committed revision. The subsequent v3 envelope/header
guards passed focused checks at frozen `100e1e48`, and source-v3 metadata replay
completed. Hosted CI for `100e1e48` also passed all Windows/Linux regression
jobs and the Linux Colab bootstrap in
[run 37451417275](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37451417275).
This covers frozen `100e1e48`; the later isolated reporting, quality-v2
preprocessing and compact-union changes passed 100 focused tests, whole
Ruff/133-file format, strict mypy/66-source and four final native-model integration
checks in 83.74 seconds. Their fresh commit/input freeze and hosted CI are pending.
Canonical SGML admissibility and genuine FinBERT verification remain
separate proofs and have now passed on the 250-inventory sample and genuine
SEC-text smoke. Source-v2 is preserved as a completed metadata capture whose
lower-bound mismatch failed document admissibility. Full feature/fitting gates
remain open; the stopped legacy batch retains 1,494 partial checkpoints.
The reporting patch separately passed Ruff, strict mypy, 28 synthetic research
metric/evaluation tests and four focused native-model integration tests.
Production quality-v2 tokenizer acceptance and genuine pinned CPU inference on
the first ADBE/ADSK FIT event passed: 31.766 seconds, exact cache replay, all five
asset hashes verified and 388 legacy cache files unchanged, with no network,
LLM or outcomes. This timing is not compared with the different V/MA legacy
smoke. New batch `development_quality_v2` still awaits freeze/launch; no actual
research Model B fit or assessment result has been produced.

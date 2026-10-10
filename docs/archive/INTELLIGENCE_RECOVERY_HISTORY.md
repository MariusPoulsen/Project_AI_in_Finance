# Intelligence recovery history

This is the previous research runbook, preserved from source revision
`a02aadff17f4be98699780108292e51b95603361`. Its dated status statements,
commands, process IDs, benchmark limitations and acceptance records describe
prior attempts. They are historical records, not current launch instructions or
proof of completed features, fitted results or promotion.

Use the [current runbook](../RESEARCH_V2_RUNBOOK.md) for active commands,
[status](../STATUS.md) for remaining gates and [decisions](../DECISIONS.md) for
canonical amendments. All original narrative and immutable identities below
are retained; only Markdown link destinations are adjusted for this archive
directory and the corresponding historical snapshots. The original runbook byte SHA-256 is
`20ecb2b03566e65fb5bd4c017bc644aed45df543b724299a25b492f20268397d`.

---

# Research v2 batch runbook

This is the separately versioned experiment authorized on 2026-10-06. Read
[the frozen protocol](RESEARCH_V2_PROTOCOL_HISTORY.md) before interpreting its results.
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
[SEC_METADATA_RECAPTURE.md](SEC_METADATA_RECAPTURE_HISTORY.md).
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

### Detached audited recovery on Windows

The current engineering recovery uses `development_detached_v2`; preserve the
failed `development_primary_v2` directory. Freeze and test the changed source
before auditing. The baseline SHA below fixes all 2,290 completed original files.

```powershell
$baseline = '.acceptance/primary_v2_failed_attempt1_20261007T230523Z/receipt.json'
$baselineSha = 'b5c29ff2b0a9580fa2ab3c0a6ff7c5ed635c3ba2fb7f72bc3a19265ef1c26bbb'
$audit = '.acceptance/detached_v2_checkpoint_audit.json'
& .\.venv\Scripts\python.exe -u -m structural_break.research.cli audit-checkpoints `
  --registry-version research_registry_0bd415d2a5af1f4891dc1f0d `
  --batch-name development_detached_v2 --sec-source source_v3 `
  --sentiment-preprocessing sec-sentence-quality-wordpiece-v2 `
  --catalyst-max-events 500 `
  --checkpoint-source data/research_v2/intelligence/development_primary_v2 `
  --checkpoint-baseline $baseline --checkpoint-baseline-sha256 $baselineSha `
  --audit-output $audit
```

This command validates stored outputs and raw response integrity once, then copies
the same checkpoint bytes into the new batch. It makes no provider/neural calls
and does not replace independent raw-text verification. The new audit receipt is
immutable; use a new path for another audit. After it succeeds, supply the exact
new committed Git HEAD and audit SHA to the launcher:

```powershell
$auditSha = (Get-FileHash -LiteralPath $audit -Algorithm SHA256).Hash.ToLowerInvariant()
& .\scripts\start_research_intelligence.ps1 -ResumeAudit $audit `
  -ResumeAuditSha256 $auditSha -ExpectedHead EXACT_COMMITTED_HEAD `
  -CompletedCheckpointCount 2290
```

The launcher returns immediately with a unique receipt, stdout/stderr/progress
paths and its exact manual status command. It prevents duplicate live builds and
preserves the complete event population; no partial-event or disabled-inference
flags are used. Run the returned status command when needed, without an ongoing
chat monitor. `SUCCESS` and a complete feature manifest are feature-build outputs;
three-horizon model/native verification and primary/main promotion remain separate.
The audited builder defers its duplicate final raw replay and records independent
verification as pending. Training and publication still perform their mandatory
fresh raw replay of every event before accepting these features.
On Colab/Linux, use the same research CLI audit/recovery options in that runtime;
the Windows detached launcher is not a Colab process manager.

Replace `REGISTRY_VERSION` below with the printed version. The actual expanded
registry is `research_registry_0bd415d2a5af1f4891dc1f0d`. Immutable batch
`development_quality_v2` first launched at 2026-10-07 05:17:15 UTC from frozen
commit `2dd54bcb068eadd57212b809d1770a99c033b81d`. The first attempt failed as
described below; resume 1 launched at 08:58:15 UTC under identical code/inputs,
then was deliberately stopped at 09:40:28 UTC during old-prefix replay. New
`development_primary_v2` is planned after the completed focused cache checks
and a fresh code/input freeze with its own exact-head CI. Source/tone completion and actual A/B fits remain pending.

Legacy batch `development_v3_100e1e4` used frozen main source
`100e1e48`, with 37,421 scheduled events, `--sec-source source_v3` and
`--catalyst-max-events 500`. Neither `--max-events` nor disabled inference was
used. Its progress log is `.acceptance/research_full_intelligence_v3.log`.
It is confirmed STOPPED and incomplete as of 2026-10-07 05:10 UTC: session and
process are absent, and the log ends at 1,494 completed checkpoints at 03:33 UTC
without traceback or terminal manifest. Its cause is unknown; do not label it
an intentional stop, successful completion or confirmed FAILED publication.
The tested quality-v2 replacement is a separate batch, not a resume of this
legacy-policy batch. Its code froze before process launch; startup published the
new immutable inputs/schedule at 05:19:55 UTC before event processing.
Preserve the old partial directory
and verified source/Gemma caches; do not overwrite its `inputs.json` or evidence.

The new batch's immutable input file is
`data/research_v2/intelligence/development_quality_v2/inputs.json`, SHA-256
`cf19099ac57ee7f5ba6ab3e37daa6d46dda49a7f4dc63893d6a06d1063f78fea`.
It binds the original registry/universe, source_v3 manifest
`39a6e5e417a2c3e8ddfa75c04564453c0157a37ca43b46ad1b14a3e0935853a9`,
quality-v2 preprocessing, all 37,421 event identities and `max_events: null`.
The separate catalyst schedule still selects 500 events: canonical schedule
identity `b6b79744ea43cddd7926a66d521e2661734271dfd3f2aba0949588aa47cda551`,
file SHA-256
`0de5ee936b24997bf7ec86c239120711492943685613ef3a309481625ba5f07a`.
Original launch proof: `.acceptance/research_quality_v2_launch.json`; failed-attempt
logs: `.acceptance/research_full_intelligence_quality_v2.log` and
`.acceptance/research_full_intelligence_quality_v2.stderr.log`.

That quality attempt exited 1 after 1,494 completed checkpoints with
`FileExistsError`: accession `0001193125-06-199058` contained three valid raw
responses and their sidecars but lacked a completion manifest. The repair reused
all six original files and original retrieval times, fetched only the missing
EX-99.1, verified the SGML clock and completed this unregistered inventory.
Recovery receipt:
`.acceptance/sec_orphan_recovery_000119312506199058.json`, SHA-256
`65ab238448b5d055ca80ed771ed62cc0cc7cbe6063272eb20e8c553a874216d7`;
completed inventory SHA-256
`eaf379b638169a502f356d37f9e0ce98b959cb88c0c7d1192347c26f0d52eef2`.
There were no model/LLM calls or outcome reads in that repair. This known quality
failure does not establish the cause of the earlier legacy stop. Preserve both
attempt logs and both 1,494-checkpoint sets; they are different generations.

Resume 1 launched at 2026-10-07 08:58:15 UTC (launcher 16032, interpreter 33024),
reusing the same quality generation and exact inputs, source revision and runtime
hash. Its receipt is `.acceptance/research_quality_v2_resume_1_launch.json`,
SHA-256 `587e55d4ddc0f8d006a5b476d319c205a973055f27beed6c6dbe7a6a77447613`.
Progress: `.acceptance/research_full_intelligence_quality_v2_resume1.log` and
`.acceptance/research_full_intelligence_quality_v2_resume1.stderr.log`.
The resumed command replayed the preserved prefix. At 09:40:28 UTC it was
deliberately stopped with replay index 1,209 below the 1,494 preserved files,
before any new event acquisition/inference branch. Controlled-stop receipt:
`.acceptance/research_quality_v2_controlled_stop.json`, SHA-256
`53224184ed64f61c3db3c0d8167968de287634301926e246f7f72d1c818fa4e8`.
The supervisor recorded `STOPPED_AT_GATE` at 09:40:29 UTC, with zero model
stages and final data locked. Keep the generation and terminal receipts;
replayed checkpoint counts do not establish a full 37,421-event manifest.

An ignored operational supervisor,
`.acceptance/run_research_quality_pipeline.py`, SHA-256
`301df1bcb43ea19605f59d379fdce363f9d2ea40eee3e221d8c2a7a7b5cbbd05`,
uses the explicit resume-launch receipt and holds the exact Windows
feature-process handle. It requires a successful feature
CLI exit, the complete 37,421-event manifest and the explicit frozen gate
`.acceptance/research_quality_v2_ci_gate.json` before invoking the existing production CLI for h20/h10/h30 fits (ten bundles
per horizon) and independent native verification. The actual supervisor PID is
34252, with launcher PID 2428; state is recorded in
`.acceptance/research_quality_v2_pipeline_state.json`. That old supervisor is
now `STOPPED_AT_GATE` after the controlled interruption, with no fitting stages
recorded. This is an
operational continuation, not a scheduled automation or provider-call retry;
it cannot unlock final data. Launching it does not prove feature/model completion.

The main runtime computational source hash is
`834f66f8ec69f69ad2a283d0e2401651be5a0770863a79a55059142531bb116f`;
the isolated real-smoke hash is
`24f71761d9933172838458c6b698cc01b8fb8ed881925330a463f226e522e741`.
At the same clean `2dd54bcb` freeze, all 66 source files normalized identically;
only pre-existing CRLF/LF differences in `research/universe.py` and
`services/intelligence.py` change raw byte hashes. Source equivalence proof:
`.acceptance/research_quality_runtime_source_equivalence.json`, SHA-256
`ae0ac33d6b3dbe5e51409750576749e734fcb98c01297c859cb4d640d63b0a92`.
Main production source stayed frozen across the original quality launch and
resume. The input builder's own `code_sha256` field is a separate scope from this
all-source bytewise hash.

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
[the protocol amendment](RESEARCH_V2_PROTOCOL_HISTORY.md#fit-input-preprocessing-amendment).
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
[COLAB.md](../COLAB.md), then run the same batch CLI commands with `--extra nlp`.
Keep the virtual environment and active database on `/content`, and archive the
closed workspace between sessions. A current-survivor Yahoo/SEC roster and
modern FinBERT extraction remain disclosed research limitations on either host.

## Parsing profile and guarded batch transition

The old generation is preserved after a controlled stop, not completed.
`.acceptance/quality_v2_replay_stage_profile.json` (SHA-256
`fb2e345f1e872969fb2d7aa5a7dbf3d9defd4fb0af37307b383b5ca360a2a325`)
profiles only the first three existing FIT 2006 events at frozen source
`2dd54bcb`/`834f66f8...`. Exact pack/tone replay passed; their pack rebuilds
were 8.052 seconds with a cold process-local parsed-frame cache and 1.310 hot.
`parse_documents` used 6.602 of 8.050 cumulative seconds. The runner hash is
`8674c4ce76b1ce6833f5176b1d90552d8f76462f94ae5ea14c575d2c5be1a6ea`.
No APIs, neural inference or outcomes were used; OS caches were not flushed and
the host was concurrently active. Do not extrapolate a full-job ETA or speedup.

A bounded 128-entry RAM cache with private disk spill is implemented for one
operation at a time. Each builder and verifier must start empty, retain
raw-hash/SGML/cutoff checks and independently parse each distinct verified raw
inventory; verifier reuse of a builder-generated parser cache is forbidden.
The implementation passed 95 focused checks. The source-only forced-eviction
benchmark `.acceptance/quality_v2_operation_spill_benchmark.json`, SHA-256
`5c8e02a0b6500583d32bba763d1c93cb729d3b572db5218465e3904ea3f9834c`,
used the same three FIT 2006 inputs with only one hot frame: repeated parsing
fell from 22 baseline calls to 11 builder calls for eleven distinct inventories.
A fresh verifier-style operation made its own eleven parses and reused no
builder spill. All eighteen pack reconstructions matched their respective
original checkpoint bytes, with exact pandas-frame checks. The full independent
verifier/job was not invoked. Fixed operation order, unflushed OS caches and
artificial one-frame eviction prevent a full-production speedup or ETA claim.
The amended cache also passed four native model/evidence integration tests in
128.76 seconds, whole Ruff/142-file format checks and default mypy for 77 source, script and app
files. These are engineering/synthetic integration checks, not actual study
fits. The final amended source still requires its own exact-head hosted CI.
These checks cover the bounded cache and sample equivalence; the new source
freeze, exact-head CI and full guarded checkpoint transition remain pending.

Changed builder identity requires a new immutable batch, planned as
`development_primary_v2`. Preserve the old 1,494 files and source/inference
caches. Before launch, freeze the final code and its inputs, record a hash-
verified checkpoint inventory/copy receipt, and reconstruct each adopted prefix
record from verified raw sources. Reuse must reproduce the complete evidence
and feature values rather than merely accept the copied JSON. Do not overwrite
`development_quality_v2/inputs.json` or call it complete. Focused cache
acceptance has passed; transition receipt, final source/input freeze, exact-head
CI and new launch remain pending.
Only after the full 37,421-event manifest may the supervisor fit/replay all
thirty models and prepare the promotion receipt. Future commands must name the
new batch and its exact pipeline/CI receipts; none is a result of the old stop.

## Promote v2 as primary

The user authorized replacing v1 as the primary project after v2 evaluation and
required gates finish. Promotion is still pending. Once the operational
supervisor has completed all thirty models and their independent replay, run:

```shell
uv run --frozen --extra nlp structural-break promote-primary --pipeline-receipt .acceptance/research_quality_v2_pipeline_state.json --ci-gate .acceptance/research_quality_v2_ci_gate.json
```

The paths above are illustrative until the new generation finishes. Supply the
exact completed pipeline receipt and CI gate for that generation, not the
preserved stopped quality-v2 state. The explicit receipt must have status
`ALL_THREE_HORIZONS_FITTED_AND_INDEPENDENTLY_VERIFIED`. The release command
requires its frozen source and successful hosted-CI gate, six separate successful
production CLI stage receipts, the full all-events-retained quality-v2
intelligence manifest and three registered evaluation generations. It freshly
replays all ten native bundles per horizon before publishing readiness. An
incomplete pipeline or synthetic fixture result cannot establish readiness for
the actual study.

The printed primary version identifies
`data/research_v2/artifacts/research/PRIMARY_VERSION/manifest.json` and
`verification_receipt.json` and `hosted_ci_gate.json`. The publisher snapshots
the exact pipeline and CI-gate bytes before fresh native replay, binds the CI
checksum and parsed object, and archives the identical gate body. Read-only
loading checks the archived bytes/proof checksums and parent bindings. Keep
these artifacts immutable: they bind the input pipeline receipt, frozen source
parents, three evaluations and fresh native checks. The
primary app reads only accepted registered versions and their checked artifacts;
it does not fit models or silently display v1 as the v2 result. The retained v1
app is `app/reference_streamlit_app.py`. Workspace readiness publication and
GitHub `main`/default-app promotion are separate delivery steps; both actual
promotion and predictive results remain pending.

The primary-release patch has passed 49 focused synthetic readiness/CLI checks
(16 readiness, seven primary CLI and 26 research CLI), 18 app and 54 SEC checks;
default mypy for 77 source, script and app files passed. The broad local pytest
run was cancelled during host contention/source edits and is not a pass. Hosted
`98356bf` both release runs passed all six jobs. Full structured receipt:
`.acceptance/research_98356bf_hosted_ci.json`, SHA-256
`3536c28aaa383120be82983b0899e0aca152dd3308ed66fb844694dbadd1214a`.
The cache amendment needs a new exact-head CI after its freeze. The earlier green
`2dd54bcb` gate covers the frozen model code; future primary/cache-release CI
is separate. These tests do not establish actual fit results or B superiority.

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
checks in 83.74 seconds. The amendment froze at `2dd54bcb`, the batch inputs
were published before processing, and both new hosted runs passed.

Hosted CI for frozen `2dd54bcb` passed all Windows/Linux foundation jobs
and the Linux Colab/NLP bootstrap in
[PR run 37575503287](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37575503287)
and [branch run 37575496575](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37575496575).
The full structured result is `.acceptance/research_2dd54bc_hosted_ci.json`,
SHA-256 `4311287edfcd2aa8fc1f095ffae2b099ec549f9ee5207c1f74d9d26f8b2c111e`.
These checks cover the quality, reporting and compact-union amendments; they do
not establish complete historical feature coverage or predictive improvement.

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
smoke. Old `development_quality_v2` is deliberately stopped and preserved.
Cache implementation, 95 focused checks and the exact eighteen-pack benchmark
passed; final source/input freeze, exact-head CI, guarded transition and new
`development_primary_v2` launch remain pending; no actual research Model B fit or assessment result has
been produced.

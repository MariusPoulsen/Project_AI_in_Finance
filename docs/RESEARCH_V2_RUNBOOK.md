# Research v2 batch runbook

Research v2 uses `data/research_v2` with separate immutable sources, checkpoints,
models and DuckDB storage. Read [the protocol](RESEARCH_V2_PROTOCOL.md) and
[canonical decisions](DECISIONS.md) before changing a research input. The
2024–2025 final-test outcome lock remains in force. Model B improvement is an
objective; it has not yet been established.

## Current build

The prior `development_prefetch_v2` worker exited 1 at 6,835 checkpoints on
2026-10-10 because an official SEC acceptance field was explicitly empty.
Its logs, source and checkpoints are preserved. The replacement excludes that
accession's unavailable-clock text, retains selected-source/event denominators,
and uses bounded source prefetch and a fresh audit. It runs
independently of this chat after launch and does not start training or publication.
Keep the running checkout's computational source frozen; prepare later changes
in isolation. Do not duplicate a live build or restart older stopped controllers.

| Input | Frozen identity |
|---|---|
| Registry | `research_registry_0bd415d2a5af1f4891dc1f0d` |
| Recovery intelligence batch | `development_clockgap_v2` |
| Computational revision | Exact committed HEAD bound by its fresh audit/launch |
| Event population | 37,421; all events retained |
| SEC metadata | `source_v3` / `research_sec_5f856a4e440531e2742bf1d8` |
| SEC manifest SHA-256 | `39a6e5e417a2c3e8ddfa75c04564453c0157a37ca43b46ad1b14a3e0935853a9` |
| FinBERT preprocessing | `sec-sentence-quality-wordpiece-v2` |
| Catalyst schedule | 500 target-blind events |
| Preserved checkpoints | 6,835; copy unchanged after the fresh audit passes |
| Stopped-attempt baseline | `.acceptance/prefetch_v2_failed_attempt_20261010T124036Z_6a9612c44002/receipt.json` |
| Baseline SHA-256 | `135d100da726a98ba077babec0260c52bf899e18dfd84d41c3ab83541868c470` |
| Operational overlap | One next-event source task; one CPU model; `--source-prefetch 1` |

From the repository root, check progress manually:

```powershell
& .\scripts\check_research_intelligence.ps1 `
  -LaunchReceipt '.acceptance/EXACT_NEW_LAUNCH_DIRECTORY/launch.json'
```

The launch receipt contains the exact command, process/creation identity,
stdout, stderr, progress and exit-receipt paths. Counts in this document are
launch facts, not a live progress display. Do not keep the chat polling.

Build `SUCCESS` and the complete batch `manifest.json` establish feature
completion only. The audited builder records independent raw replay as pending;
training, native verification and publication still require fresh raw replay.
All thirty fits, their independent verification, accepted workspace publication
and GitHub `main` promotion remain pending. See [status](STATUS.md) for delivery
gates and [recovery history](archive/INTELLIGENCE_RECOVERY_HISTORY.md) for old
attempts, benchmarks and receipts.

## Environment

Run from the repository root using Python 3.11 and the committed lockfile:

```shell
uv sync --frozen --extra nlp
uv run --frozen --extra nlp structural-break-research --help
```

Configure `SB_SEC_USER_AGENT` and `SB_LLM_API_KEY` in the ignored `.env`, process
environment or Colab Secrets. Keep credentials out of commands and output.
SEC, Yahoo and the local database require no login. The NLP extra supplies CPU
PyTorch and Transformers; retain `--extra nlp` for inference. Pinned FinBERT
assets are already cached on the current Windows host. Use `--download-model`
only when explicitly acquiring those public assets on another host.

Gemma uses the direct Google adapter and the frozen call budget, including
retries; paid calls remain disabled. Invalid or unscheduled catalysts are
UNKNOWN. Flash is reserved for the later full-system agents. Do not change the
500-event schedule, FinBERT policy, event population or model definitions to
finish a run sooner.

For Colab, follow [COLAB.md](COLAB.md), run
`scripts/colab_bootstrap.py --nlp` and use the same research CLI. Keep the active
virtual environment and database on `/content`; archive the closed workspace
between sessions. The Windows detached launcher is not a Colab process manager.

## Reproduce sources in a separate workspace

The current universe, market, SEC metadata and registry are already frozen.
Do not recreate them in the active workspace. In a new workspace, the source
sequence is:

```shell
uv run --frozen --extra nlp structural-break-research freeze-universe --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break-research capture-market --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break-research collect-sec --sec-source source_v3 --workspace-root NEW_WORKSPACE
uv run --frozen --extra nlp structural-break-research build-registry --workers 2 --workspace-root NEW_WORKSPACE
```

The roster fixes 250 issuers, 736 pairs and the original 28 orientations. Market
sources end in 2023. Use the registry version printed by the command; never infer
an identity from directory modification times. Partial issuer/ticker captures
are dry runs, not the complete study. Preserve the existing `source_v1` and
`source_v2`; source-v3 lineage and its conservative clock envelope are recorded
in [SEC metadata recapture](SEC_METADATA_RECAPTURE.md).

## Interrupted-run recovery

Confirm a worker's terminal exit from its process identity and exit receipt;
a `RUNNING` record alone does not establish a dead process. Preserve logs,
checkpoints, source captures and manifests. Identical-input interrupted runs may
reuse valid checkpoints. Changed computational source or scientific inputs
require a new immutable generation. Never rewrite a registered checksum or
manifest to force acceptance.

For a separately prepared recovery batch, first freeze and test source, preserve
a SHA-bound stopped-attempt baseline, then audit the source/checkpoint identities.
The current stopped-attempt transition uses:

```powershell
$baseline = '.acceptance/prefetch_v2_failed_attempt_20261010T124036Z_6a9612c44002/receipt.json'
$baselineSha = '135d100da726a98ba077babec0260c52bf899e18dfd84d41c3ab83541868c470'
$audit = '.acceptance/NEW_AUDIT_RECEIPT.json'
& .\.venv\Scripts\python.exe -u -m structural_break.research.cli audit-checkpoints `
  --registry-version research_registry_0bd415d2a5af1f4891dc1f0d `
  --batch-name development_clockgap_v2 --sec-source source_v3 `
  --sentiment-preprocessing sec-sentence-quality-wordpiece-v2 `
  --catalyst-max-events 500 `
  --checkpoint-source data/research_v2/intelligence/development_prefetch_v2 `
  --checkpoint-baseline $baseline --checkpoint-baseline-sha256 $baselineSha `
  --audit-output $audit
```

This is a reference for preparing the new generation, not a command to repeat
after its launch. Use a unique audit path and the preserved stopped source.
The audit checks frozen inputs, event identities, schedule,
checkpoint bytes, raw SEC inventories/SGML clocks and stored extraction/tone
features, then copies the same checkpoint bytes. It makes no provider or neural
calls and does not replace independent raw-text acceptance.
An explicitly empty unique official acceptance field excludes that accession's
text without replacing dates or selecting an older source. Its selected filing
ID/count and failed-source gap remain explicit. The audit rejects old checkpoints
that used excluded text or omitted the gap; malformed, duplicate or contradictory
clocks still fail. Fresh independent replay applies the identical rule.

After the audit succeeds, supply its exact SHA, the tested committed source HEAD
and the verified target checkpoint count to the detached launcher:

```powershell
$auditSha = (Get-FileHash -LiteralPath $audit -Algorithm SHA256).Hash.ToLowerInvariant()
& .\scripts\start_research_intelligence.ps1 -BatchName development_clockgap_v2 `
  -ResumeAudit $audit -ResumeAuditSha256 $auditSha `
  -ExpectedHead EXACT_COMMITTED_HEAD -CompletedCheckpointCount 6835 -SourcePrefetch
```

The launcher rejects duplicate live builds and changed tracked source, writes a
unique launch receipt and returns a manual status command. Resume audits apply
only to their exact bound source, inputs and checkpoint bytes. Re-audit a changed
recovery plan; never modify the existing audit to make it pass.

`-SourcePrefetch` records `--source-prefetch 1` in the immutable launch plan.
The producer owns HTTP pacing and its parser cache; the coordinator alone makes
ordered Gemma calls, scores unchanged FinBERT batches and writes checkpoints.
At most one next event is outstanding. Default CLI mode remains serial. Preserve
prefetched raw captures after an interruption, even if their event checkpoint
has not yet been written. This overlap does not promise a whole-job speed gain.

## Fit and independently verify the completed batch

Wait for successful feature exit and the complete 37,421-event manifest. Under
the approved DECISIONS section 26 amendment, reconstruct the complete shared
source batch once before fitting:

```shell
uv run --frozen --extra nlp structural-break-research verify-source-inputs --registry-version research_registry_0bd415d2a5af1f4891dc1f0d --batch-name development_clockgap_v2 --source-proof-purpose fitting_input --progress-file .acceptance/source_1_progress.json
```

Use its printed `source_proof_path` and `source_proof_sha256` as `FIT_PROOF` and
`FIT_PROOF_SHA`. Both are mandatory; a partial build cannot mint a proof. Run
training and a separate verification for each horizon in the order 20, 10, 30.

For the separately frozen four-core execution profile, add `--event-workers 4`
to **both** `verify-source-inputs` commands. Four owned processes use independent
empty private parser caches and one numerical-library thread each. Complete
business groups stay together for parsing reuse; the coordinator restores the
original event order and performs the complete final inventory/feature checks.
Progress reports the aggregate verified count and each worker's PID/count.
Do not combine event workers with the separate parsing-worker pool. Model
stages stay sequential to bound memory. Both complete passes, all thirty models
and native/report checks, and the final-test lock remain unchanged.

Add `--source-proof FIT_PROOF --source-proof-sha256 FIT_PROOF_SHA` to every command
below. Each stage rehashes the complete bound raw/checkpoint/metadata inventory;
it does not repeat the same text reconstruction. Omitting the explicit proof
retains the legacy complete-replay path.

```shell
uv run --frozen --extra nlp structural-break-research train-models --registry-version research_registry_0bd415d2a5af1f4891dc1f0d --batch-name development_clockgap_v2 --horizon 20
uv run --frozen --extra nlp structural-break-research verify-models --model-version PRINTED_H20_EVALUATION_VERSION
uv run --frozen --extra nlp structural-break-research train-models --registry-version research_registry_0bd415d2a5af1f4891dc1f0d --batch-name development_clockgap_v2 --horizon 10
uv run --frozen --extra nlp structural-break-research verify-models --model-version PRINTED_H10_EVALUATION_VERSION
uv run --frozen --extra nlp structural-break-research train-models --registry-version research_registry_0bd415d2a5af1f4891dc1f0d --batch-name development_clockgap_v2 --horizon 30
uv run --frozen --extra nlp structural-break-research verify-models --model-version PRINTED_H30_EVALUATION_VERSION
```

Each fit prints its exact evaluation version. Capture the genuine exit status,
stdout/stderr and checksums for all six stages; verification reloads every native
estimator/calibrator, checks every bound source file and reconstructs the paired comparison without
API calls. Each horizon contains ten predeclared bundles. Report every variant,
coverage, denominators, positives and quarter-block uncertainty. The primary is
calibrated logistic B-both versus matched A at 20 sessions; preserve negative or
inconclusive results and keep UNKNOWN rows. Reports and native artifacts live
under `data/research_v2/artifacts/research/EVALUATION_VERSION`.

After all six model stages succeed, perform the second independent complete
reconstruction. It always starts with an empty private parser cache:

```shell
uv run --frozen --extra nlp structural-break-research verify-source-inputs --registry-version research_registry_0bd415d2a5af1f4891dc1f0d --batch-name development_clockgap_v2 --source-proof-purpose independent_publication --progress-file .acceptance/source_2_progress.json
```

Bind both actual source-stage commands/exits/logs in the completed pipeline
receipt with `verification_strategy: shared-source-two-full-replays-v1`. Its
`source_stages` list must contain fitting-input and independent-publication
observations in that order, bracketing the six model stages. Publication requires
the second proof's printed path and checksum via `--source-proof` and
`--source-proof-sha256`, and still independently replays all thirty native models.
Use source-event counts, checksum-file counts, tuning folds and native-model
counts in the progress files; source-pass estimates exclude later gates.

## Promote v2 as primary

Promotion requires a genuine completed receipt for the detached generation and
successful hosted CI bound to its frozen computational source. The earlier
quality/primary supervisors are stopped and their receipts cannot establish this
batch's completion. Before publication, prepare the new three-horizon receipt;
the detached feature worker does not create it automatically.

```shell
uv run --frozen --extra nlp structural-break-research promote-primary --pipeline-receipt COMPLETED_DETACHED_PIPELINE_RECEIPT --ci-gate MATCHING_HOSTED_CI_GATE
```

The receipt must have status
`ALL_THREE_HORIZONS_FITTED_AND_INDEPENDENTLY_VERIFIED`, six successful production
stage receipts, three registered evaluations, the complete quality-v2 feature
manifest, exact source/CI bindings and the final test locked. Publication freshly
replays all thirty native bundles and binds the actual pipeline and CI-gate
bytes. Synthetic checks and historical green CI are not actual study acceptance.

The printed primary version identifies the immutable `manifest.json`,
`verification_receipt.json` and `hosted_ci_gate.json` under
`data/research_v2/artifacts/research/PRIMARY_VERSION`. The app reads only accepted
registered versions. Workspace publication and GitHub `main`/default-workflow
promotion are separate remaining gates. The original implementation, sources,
artifacts and Git history stay available for reference reproduction.

# Run the bounded multi-agent investigation

Phase 5 is under implementation on `phase5/agents-controller-foundation`.
[Decision 26](../DECISIONS.md#26-phase-5-bounded-adversarial-investigation) and the
[specification](../specs/04_MULTI_AGENT_PIPELINE.md) define its current design.
Keep this checkout separate from the frozen live v2 build until all v2
feature/model/replay/CI/publication gates pass. These commands run synthetic
fixtures; they do not fit models, consume live quota or open final-test outcomes.

## Local fixture

From the isolated repository checkout, install the committed Python 3.11
environment with the optional agent dependencies:

```powershell
uv sync --frozen --extra agents
uv run --frozen --extra agents structural-break-agents --fixture --output-dir .acceptance/phase5-demo --mode mock
```

The fixture supplies invented securities, text, model values and a FIXTURE
controller policy. It exercises independent opening cases, one rebuttal exchange,
separate synthesis and semantic-validation responses, mechanical grounding
checks, and deterministic final status. A synthetic CANDIDATE proves only that
the accepted fixture state passes the programmed gates; it proves no financial
or language-model quality.

For explicitly supplied mock inputs and responses:

```powershell
uv run --frozen --extra agents structural-break-agents --input tests/fixtures/phase5/input.json --policy tests/fixtures/phase5/policy.json --responses tests/fixtures/phase5/responses.json --output-dir .acceptance/phase5-custom --mode mock
```

Inputs bind the event, historical pair lifecycle, model/calibrator/relationship
versions and exact admissible chunk identities, hashes, offsets and clocks.
Outcome fields and extra JSON properties are rejected. Development events cannot
open the locked 2024–2025 period. Explicit file input is not yet independent
verification that a historical record matches the accepted v2 model/source
generation; that adapter remains an acceptance gate.

## Policy and cached runs

`configs/phase5_decision.json` is deliberately DRAFT with unset thresholds. It
fails closed with ABSTAIN. The separate fixture policy's numeric thresholds are
for engineering tests and must not be promoted as validated research policy.
Freeze the actual Model B trading threshold and controller rules from permitted
development evidence before live historical evaluation.

A stored HIGH-materiality A/B catalyst with DIRECT relationship relevance must
retain an unresolved-risk warning until independently confirmed. A validator
that reports LOW risk without confirming that catalyst cannot clear CANDIDATE:
the controller returns REVIEW with `UNRESOLVED_CATALYST_RISK`. Confirmed HIGH
break risk or the confirmed one-sided veto produces NO TRADE; quotation alone
does not supply that semantic confirmation.

Role-output caches and the terminal run receipt retain checksums and exact
input/provider/model/prompt/graph/schema identities. An identical rerun reuses
valid immutable outputs. A changed input or upstream response requires a new
cache identity; corruption is an error, not permission to overwrite the old
object. Failed runs retain their denominator record. Retrying a failed run
requires an explicit new attempt identity; preserve the failed receipt and do
not silently relabel it successful.

Use `--attempt-id` for that deliberate retry, for example:

```powershell
uv run --frozen --extra agents structural-break-agents --fixture --output-dir .acceptance/phase5-demo --mode mock --attempt-id retry-01
```

Preflight records deterministic ineligibility or insufficient data without
spending LLM calls. Historically ACTIVE, frozen Model B candidate threshold and
all hard gates are necessary for automatic Full-System candidates. REVIEW,
NO TRADE, ABSTAIN and skipped rows remain visible in coverage and strategy
denominators. The broad 37,421-event A/B population and v2's separate 500-event
catalyst schedule remain unchanged.

## Google Colab fixture

Restore or clone this reviewed branch/commit using the
[Colab source instructions](COLAB.md#get-the-source). No Jupyter package is
required. In notebook cells:

```python
%pip install uv==0.12.20
```

```python
import subprocess
import sys

repository = "/content/Project_AI_in_Finance"
subprocess.run(
    [
        sys.executable,
        repository + "/scripts/colab_bootstrap.py",
        "--agents",
        "--agent-fixture",
        "--workspace-root",
        "/content/phase5-bootstrap-checks",
    ],
    check=True,
)
```

The bootstrap uses a locked project Python 3.11 environment, retains the
`agents` extra and executes the mock fixture. Dependency installation needs
internet; the fixture itself uses no API key, downloaded FinBERT weights or
live-source/model calls. Hosted Colab verification is recorded separately from
local command checks; availability of these flags alone does not establish it.

## Genuine pilot and completion gates

The CLI initially exposes mock execution only. The separate live provider
adapter can be tested with an injected transport without consuming quota.
Historical accepted-generation integration, genuine provider outputs and human
quality evaluation remain pending. Do not bypass those gates by substituting
mock responses for measured agent performance.

The approved live role allocation is Gemma for two openings and two rebuttals,
and Flash-Lite for separate synthesis and semantic validation: four Gemma and
two Flash-Lite calls per complete uncached event before retries. Configure exact
models, settings, pacing, timeouts and shared attempt caps. Free-tier limits may
change; budget omissions and quota/provider failures are explicit, with no paid
fallback. Store keys only in ignored environment files or Colab Secrets and
never pass them in command arguments, fixtures or logs.

Attach `DurableAttemptJournal` to the live provider for restart-safe accounting.
It reserves attempts before transport, including retries, and never refunds a
reservation with an unknown outcome. Its fixed total/model/day allocation and
checksum chain survive restarts. The provider's own counters remain invocation
local; the journal is the shared allocation boundary. It cannot measure quota
spent by other applications. Starting a fresh process or creating another key
does not reset the provider project's quota. Invalid schemas are rejected and
required-stage failures abstain, without repeated generation to obtain a preferred answer.

After genuine Model B fitting, count historically eligible candidates. Freeze
any quota-driven target-blind investigation schedule before evaluating its agent
outputs; optional REVIEW/audit selection is declared separately. A scheduled
subset's B/Full-System comparison uses the same scheduled denominator and is
reported separately from the broad A/B forecast study.

Complete a fixed human annotation set of at least 50 historical events, aiming
for 100, covering source support, category, affected leg, materiality and
relationship relevance plus advocate/synthesis interpretation. Python exact
quotes establish provenance; semantic validation and human checks establish
whether the interpretation is supported. Record failures, unsupported claims,
UNKNOWNs and abstentions. Mocks, cache replay and safe controller behavior are
engineering evidence only. The final 2024–2025 outcomes remain locked until a
later explicit user authorization after methodology freeze.

## Resumable mock batches

The batch CLI prepares an immutable, file-backed four-event fixture inventory:
one eligible investigation plus WATCH, low-probability and missing-data cases.
It freezes hash order and eligibility before any calls and keeps all four rows.
These commands intentionally pause, resume and replay the same batch:

```powershell
uv run --frozen --extra agents structural-break-agents batch --fixture --output-dir .acceptance/phase5-batch --max-events 2
uv run --frozen --extra agents structural-break-agents batch --fixture --output-dir .acceptance/phase5-batch
uv run --frozen --extra agents structural-break-agents batch --fixture --output-dir .acceptance/phase5-batch
```

The first command processes two new rows without a complete manifest. The next
finishes the remaining rows; together they spend six mock role attempts. An
identical completed replay makes zero new calls. Output includes counts,
dispositions and the complete manifest path. `batches/<batch_id>/progress.json`
is replaceable operational state; immutable envelopes and checkpoint identities
govern resumability. Evidence packs load one at a time from `prepared/manifest.json`.

Use `--max-investigations N` to freeze an optional target-blind investigation cap.
This is distinct from `--max-events N`, which pauses after N new checkpoints.
The default mock `--call-budget 60` is persisted in `attempt-journal`; changing
that allocation in the same directory is rejected. A zero budget preserves an
explicit budget-exhausted ABSTAIN, never a missing denominator. Failed events
remain terminal; `--attempt-id retry-01` deliberately creates a new batch while
retaining shared attempt accounting. Completed valid role caches may be reused.

For other prepared mock inventories, use `batch --bundle MANIFEST --policy POLICY
--responses RESPONSES --output-dir DIRECTORY`. The inventory declares mock mode
and binds every exact event/source/model projection. Genuine accepted-generation
loading and live CLI execution remain pending; supplied names or fixture outputs
do not certify historical provenance.

If an interrupted process leaves a lease, first establish that its owner has
stopped and inspect its JSON. Then use its exact token, explicit attestation and
a reason; never delete a lease based only on an unknown or missing PID:

```powershell
uv run --frozen --extra agents structural-break-agents recover-lock --lock LOCK_PATH --token EXACT_TOKEN --reason "Verified owner stopped after interruption" --owner-confirmed-stopped
```

The recovery receipt is written before removing the lease. Recovery never erases
attempts or rewrites registered results. Both the batch and attempt journal have
their own lease; recover only the particular abandoned lease after verification.

## Blind human source review preparation

Export all four synthetic source cases without model probabilities, suggested
catalyst labels or outcomes:

```powershell
uv run --frozen --extra agents structural-break-agents review-export --bundle .acceptance/phase5-batch/prepared/manifest.json --count 4 --output-dir .acceptance/phase5-review
```

Read the export README and each exact source JSON. Copy `annotations.blank.json`
to a separate completed JSON and fill the reviewer ID, timezone-aware timestamp,
human attestation and every source completeness/catalyst/support annotation.
The untouched blank file deliberately fails validation. Once completed:

```powershell
uv run --frozen --extra agents structural-break-agents review-validate --bundle .acceptance/phase5-batch/prepared/manifest.json --review-dir .acceptance/phase5-review --annotations .acceptance/phase5-review/annotations.completed.json
```

Validation checks exact selection, denominators, hashes, categories, citation legs,
quotes and incomplete-source constraints. It reports format/provenance validity
and explicitly leaves measured semantic accuracy and genuine acceptance false.
The default export size is 50 (maximum 100); insufficient populations are rejected
without silent downsampling. This workflow prepares source annotation only.
Real historical annotations and a separate evaluation of agent interpretations
are still needed for Phase 5 completion.

## Registered historical sources and model bridge

[Decision 30](../DECISIONS.md#30-historical-bridges-and-economic-analysis-before-v2-completion)
adds two explicit offline adapters. They do not download, fit, call a provider or
change the running v2 checkout. `--research-workspace` names the existing research
workspace itself (normally `PROJECT/data/research_v2`), while `--cache-workspace`
names the workspace whose `data/raw/sec/filings` contains the stored captures.
Always provide the exact registered version and SEC source-v3 manifest checksum;
never choose a directory by modification time.

Source-only review needs a verified registry/universe/SEC capture, independently
of Model B. Export 50–100 identity-selected historical events:

```powershell
uv run --frozen --extra agents structural-break-agents historical-review-export --research-workspace RESEARCH_WORKSPACE --registry-version REGISTRY_VERSION --sec-directory SOURCE_V3_DIRECTORY --sec-manifest-sha256 SEC_SHA256 --cache-workspace CACHE_WORKSPACE --count 50 --seed phase5-genuine-source-review-v1 --output-dir .acceptance/genuine-source-review
```

The returned manifest identifies a frozen sample directory with selection, source
packets, a local copy of the selected raw receipts/documents, an annotation template
and README. Missing/failing captures remain UNKNOWN/PARTIAL. The packets omit model
probabilities, targets and suggested catalyst labels. Offsets address stored cleaned
chunks; raw document hashes/parser chunk order remain in the source pack.

Reconstruct the sample from its frozen raw copy, preserving later live-cache growth:

```powershell
uv run --frozen --extra agents structural-break-agents historical-review-verify --research-workspace RESEARCH_WORKSPACE --registry-version REGISTRY_VERSION --sec-directory SOURCE_V3_DIRECTORY --sec-manifest-sha256 SEC_SHA256 --cache-workspace CACHE_WORKSPACE --review-dir REVIEW_DIRECTORY
```

After human completion, supply `--annotations ANNOTATIONS_COMPLETED.json` to the
same verification command. Do not edit the frozen template or manifest. Validation
checks provenance and response format; it does not establish semantic accuracy or
agent usefulness. At least 50 genuine annotations and separate agent-interpretation
evaluation remain completion gates.

The scored bridge additionally requires the explicit registered primary publication.
It checks its accepted generation/CI evidence and replays each requested H20 primary
logistic B-both native score, calibration, quantitative clock and stored SEC/tone/
catalyst inputs. Only 2022–2023 assessment inputs are admitted; final-bundle fit
and calibration predictions are not vintage out-of-sample scores. Missing publication
or a disagreement fails closed. Current liquidity and implementation eligibility
remain UNKNOWN until a separate point-in-time execution policy is frozen, producing
ABSTAIN rather than a known hard-failure veto. Export selected inputs without
spending provider quota:

```powershell
uv run --frozen --extra agents structural-break-agents historical-input-export --research-workspace RESEARCH_WORKSPACE --primary-version PRIMARY_VERSION --sec-directory SOURCE_V3_DIRECTORY --sec-manifest-sha256 SEC_SHA256 --cache-workspace CACHE_WORKSPACE --event-id REGISTERED_EVENT_ID --output-dir .acceptance/accepted-agent-inputs
uv run --frozen --extra agents structural-break-agents historical-input-verify --research-workspace RESEARCH_WORKSPACE --primary-version PRIMARY_VERSION --sec-directory SOURCE_V3_DIRECTORY --sec-manifest-sha256 SEC_SHA256 --cache-workspace CACHE_WORKSPACE --manifest .acceptance/accepted-agent-inputs/manifest.json
```

The accepted historical schema is distinct from the mock batch manifest and cannot
be passed to the mock loader to bypass its gate. Exporting a genuine projection is
not a provider pilot or a Full-System assessment. Historically eligible investigation
scheduling and genuine agent interpretation still require accepted B inputs, frozen
controller/eligibility policy and the later explicit pilot.

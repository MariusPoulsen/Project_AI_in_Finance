# Run the bounded multi-agent investigation

Phase 5 is under implementation on `phase5/agents-controller-foundation`.
[Decision 26](DECISIONS.md#26-phase-5-bounded-adversarial-investigation) and the
[specification](specs/04_MULTI_AGENT_PIPELINE.md) define its current design.
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

Provider attempt counters cover one invocation and all its transport retries;
they are not durable accounting for unsaved failures before a restart. Preserve
receipts and respect the provider project's remaining quota when deliberately
retrying. Starting a fresh process or creating another key does not reset that
quota. Invalid schemas are rejected and required-stage failures abstain, without
repeated generation to obtain a preferred answer.

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

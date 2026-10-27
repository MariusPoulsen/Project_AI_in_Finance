> **Original experiment reference.** These instructions describe the recorded
> 28-pair source/config generations. Use their original workspace and freeze;
> the active expanded workflow is in [the v2 runbook](../../RESEARCH_RUNBOOK.md).
> Commands below use the explicit reference CLI.

# SEC intelligence and Model B

Phase 4 uses the frozen Phase 3 event population and Model A features. The event
block adds 31 columns to the 36 quantitative columns. No event is dropped because
its documents or extraction are unavailable. `UNKNOWN` and `NONE` have separate
indicators. The final 2024–2025 outcome lock remains closed.

## Offline fixture

These commands require no credentials, source network or LLM requests:

```shell
uv run --frozen structural-break-reference build-events --ml-fixture --workspace-root .acceptance/phase4
uv run --frozen structural-break-reference train-model-a --workspace-root .acceptance/phase4
uv run --frozen structural-break-reference build-intelligence --intelligence-fixture --workspace-root .acceptance/phase4
uv run --frozen structural-break-reference verify-intelligence --workspace-root .acceptance/phase4
uv run --frozen structural-break-reference train-model-b --workspace-root .acceptance/phase4
uv run --frozen structural-break-reference verify-model-b --workspace-root .acceptance/phase4
```

Fixture documents and provider responses are explicitly synthetic. Their metrics
test the implementation and are not evidence of historical predictive performance.

## Real SEC/Gemini run

Use an already registered P1 snapshot, P2 relationship generation and P3 event
dataset, with a fitted Model A on that exact event dataset. Do not rebuild the
earlier phases just to pick up downstream configuration changes. Keep credentials
in the ignored repository `.env`:

```dotenv
SB_SEC_USER_AGENT=Project_AI_in_Finance your-contact@example.com
SB_LLM_API_KEY=your-local-key
```

Provider and model defaults are in `configs/agents.yaml`; optional
`SB_LLM_PROVIDER` and `SB_LLM_MODEL` override them. The user's free-tier Gemini
choice is `gemini` / `gemini-3.5-flash`. The initial 3.8 candidate returned HTTP 503
capacity errors; 3.5 passed the same structured API probe. Creating a key does not require enabling
billing. Actual project quotas vary; the configured limit is a protective budget,
not a claim that Google grants that many calls.

```shell
uv sync --frozen --extra agents
uv run --frozen --extra agents structural-break-reference build-intelligence --event-version events_6451711be4cb02d63a38d13b
uv run --frozen --extra agents structural-break-reference verify-intelligence
uv run --frozen --extra agents structural-break-reference train-model-b
uv run --frozen --extra agents structural-break-reference verify-model-b
```

Keep `--extra agents` on live commands because default uv synchronization may
remove optional SDK dependencies. Verification and model fitting themselves need
no LLM. `--event-feature-version` pins an immutable evidence generation for
verification or Model B fitting; omitted means the active generation.

One batch permits at most 20 requests, including retries, with a 32-second interval
and SDK retries disabled. A quota/authentication error stops additional requests
in that batch. The remaining rows stay `UNKNOWN`. Requests visit validation first,
then training years in round-robin chronological order, then locked final feature
events. This schedule does not inspect targets, scores or convergence outcomes.
The subset covered by a small pilot is not a representative completed extraction
study. Coverage accompanies every model comparison.

Successful and `NONE` extractions reuse their exact cache identities. Explicitly
rerunning `build-intelligence` retries `UNKNOWN`; a changed validated response
creates a new immutable evidence generation. Refit Model B against that new
generation if required. Old evidence and models remain readable.

```shell
uv run --frozen --extra agents structural-break-reference build-intelligence --offline --event-version events_6451711be4cb02d63a38d13b
```

Literal offline mode never calls a provider, including an injected one. Uncached
documents/extractions become `UNKNOWN`. It can therefore produce a different
generation when the cache is incomplete. Use `verify-intelligence` to verify an
existing frozen generation without starting a new extraction job.

Failed accession downloads are retained for audit. An explicit new attempt can
recover them without replacing the first response inventory:

```shell
uv run --frozen --extra agents structural-break-reference build-intelligence --sec-retry-attempt retry-20261004 --event-version events_6451711be4cb02d63a38d13b
```

The attempt identifier must be new for a fresh capture. It recaptures the selected
accession inventories, including already downloaded documents. Ordinary repeats
reuse the accession cache. Network failures do not justify treating absent text as
`NONE` or filtering those events out of evaluation.

## Evidence and interpretation

Select all admissible 8-K/8-K/A filings in the previous 30 calendar days and the
most recent 10-Q/10-K within 180 days, extending periodic context to 400 days when
necessary. Acceptance timestamps, rather than reporting dates, determine
availability. Relevant periodic amendments remain linked to their selected base.
Download primary documents, complete submissions and EX-99 exhibits by accession.
Retain raw bytes, hashes, source URLs and failed/unsupported document records.

HTML/TXT parsing removes scripts/styles, preserves text sections, and creates
stable chunks with raw and cleaned-text hashes. PDF exhibits remain unsupported
with explicit coverage status. Filter security/time/type before lexical ranking;
bound packs to eight chunks per leg and 32,000 total characters. Bounded retrieval
cannot prove that an issuer has no catalyst. `NONE` means no supported catalyst in
the selected complete pack; it is not a global claim about the company.

Strict categories, exact quotes, cited leg/security, acceptance cutoffs and
category cues are verified. Nonempty catalyst claims require admissible supporting
chunks. Materiality, direction and relationship relevance still need human
semantic assessment; automated quote validity alone does not prove them correct.
Provider confidence is uncalibrated extraction certainty, not probability of
reversion or independently measured extraction accuracy. Human-labelled NLP
evaluation belongs to Phase 5.

Historical XOM evidence uses reviewed predecessor CIK 0000034088 through
2026-06-30 and successor CIK 0002115436 from 2026-07-01. Recovery is a supplemental
source generation with its own raw submissions and manifest. It does not rewrite
the frozen P1 snapshot or change the event population.

## Reproduction and stored outputs

`artifacts/intelligence/{event_feature_version}/` contains the full evidence-pack
JSON, exact extraction JSON, immutable Parquet tables and a manifest binding its
P3 parent, policy/provider/prompt/schema, computation/config identities and raw
SEC sources. DuckDB stores canonical extraction/feature rows and active pointers.
Usable cleaned chunks are published to `data/curated/evidence/document_chunks.parquet`
and `ref.document_chunks` points at the immutable generation. Failed/sentinel rows
remain in the full auxiliary chunk inventory. Both aliases roll back if publication
fails; frozen repositories always read the versioned inventory.
The extractor's allowlisted normalized evidence hash differs deliberately from
the richer original pack hash; both are retained for their respective identities.

Verified reads check every inventory hash and parent, reparse raw documents,
rebuild source selection/packs, validate citations, and reconstruct the 31 event
features including their availability metadata. This uses no LLM. A failed job
publishes no analytical generation; retrieval and extraction failures are audited
as job records and explicit coverage/reason codes.

Model B fits the same chronological logistic/XGBoost protocol, 30-configuration
search, embargo, calibration and fixed 0.65 threshold as Model A. Its manifest
binds the evidence generation and matched Model A parent. Native model reload,
raw-margin SHAP reconstruction and `model_a_b_comparison.json` are verified without
extraction. Repeated Model B fitting reuses unchanged registered outputs.

The paired comparison retains the full eligible validation cohort and reports
additional UNKNOWN/NONE/available/supported slices. Raw validation scores are
holdout diagnostics. Calibrated validation scores are calibration-fit descriptive.
Seven all-negative validation events cannot establish discrimination, calibration
generalisation or Model B superiority. See [the historical redesign proposal](../RESEARCH_REDESIGN.md) for a separate
protocol proposal; the current phase does not change the canonical research rules.

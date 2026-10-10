# Point-in-Time Event Intelligence, Multi-Agent Investigation & Decision Control

> **Agent-use specification.** Canonical implementation decisions are in [`../DECISIONS.md`](../DECISIONS.md). This Markdown is the coding-agent source of truth for this subsystem. The PDF in `docs/PDFs/` is archival/human-readable only.

# 1. Role, system boundary, and end-to-end workflow

The quantitative stack answers “is this a statistically unusual, historically promising divergence?” The language-AI stack answers a different question: “is there contemporaneous public evidence that makes the historical relationship economically unreliable?”

| **Stage**            | **Input**                                                                               | **Output**                                                                 |
|----------------------|-----------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| Event intelligence   | event timestamp + both securities + stored SEC filing corpus                            | Small, admissible evidence set with provenance.                            |
| Catalyst extraction  | retrieved chunks                                                                        | Structured event schema for each leg; persisted as Model B event features. |
| Adversarial analysis | Model B quantitative state + same evidence + extracted events                           | Independent mean-reversion and structural-break cases.                     |
| Validation           | agent cases + citations + deterministic inputs                                          | Source/consistency checks and break-risk recommendation.                   |
| Controller           | pair validity + calibrated P(revert) + break risk + data/liquidity/market-context state | CANDIDATE / REVIEW / NO TRADE / ABSTAIN.                                   |

**No free-form Decision Agent**

The final status is produced by deterministic rules, not by asking an LLM whether to trade. This is essential for reproducibility, bounded behaviour, and historical evaluation.

# 2. Inputs from earlier layers and typed event state

| **Input group** | **Required fields**                                                                                                                |
|-----------------|------------------------------------------------------------------------------------------------------------------------------------|
| Event identity  | event_id, pair_id, event_timestamp, leg_A security_id, leg_B security_id, divergence_sign.                                         |
| Econometrics    | pair lifecycle status, alpha/beta snapshot, z-score, cointegration statistic/p-value, half-life, beta drift, relationship version. |
| ML              | raw score, calibrated P(revert), probability bucket, top SHAP drivers, model/calibrator/version IDs.                               |
| Market context  | market/sector/VIX state and realised volatility; all are observable point-in-time covariates.                                      |
| Implementation  | liquidity proxy, daily range/cost proxy, any hard short-side flag available.                                                       |
| Data quality    | source freshness, missing features, filing-index status, document retrieval status.                                                |

## 2.1 Typed shared state

LangGraph passes a typed state object rather than an unconstrained chat transcript. Each node may read only the fields required for its mandate and writes schema-validated outputs. This makes agent runs auditable and reduces accidental contamination between roles.

| **State block**  | **Examples**                                                                |
|------------------|-----------------------------------------------------------------------------|
| quant_state      | z, P(revert), SHAP drivers, relationship diagnostics, market-context state  |
| evidence_state   | retrieved chunk IDs, source timestamps, filing IDs, source leg              |
| catalyst_state   | event_type, affected_leg, direction, materiality, relevance, evidence IDs   |
| advocate_state   | claim list, evidence links, counterpoints, evidence strength                |
| validation_state | citation validity, contradiction flags, coverage, break-risk recommendation |
| decision_state   | final status, deterministic reason codes, policy version                    |

# 3. Point-in-time evidence admissibility

The admissibility cutoff is the event timestamp. A source is historical evidence only if its publication/acceptance timestamp is known and is no later than the cutoff. Retrieval time is not a substitute for publication time.

$$
\operatorname{admissible}(d,E_i)=\mathbf{1}[t_d^{source}\le t_i^{event}].
$$

| **Evidence**                                  | **Primary timestamp**           | **Historical use**                                                                                  |
|-----------------------------------------------|---------------------------------|-----------------------------------------------------------------------------------------------------|
| SEC 8-K / 10-Q / 10-K                         | SEC acceptanceDateTime          | Core admissible evidence.                                                                           |
| SEC amendment                                 | Its own acceptanceDateTime      | Admissible only after amendment acceptance.                                                         |
| Optional news                                 | Original publication timestamp  | Current/demo enrichment only; excluded from headline historical Model B and Full-System evaluation. |
| Current web page without historical timestamp | None / retrieval timestamp only | Not admissible for historical evaluation.                                                           |
| Later retrospective article explaining event  | After event                     | Never admissible as pre-event evidence.                                                             |

**Empty evidence is information**

If no material filing is found in the lookback window and the source index is complete, the extractor may return event_type=NONE. If the source system itself failed or coverage is unknown, the correct state is UNKNOWN/ABSTAIN, not NONE.

# 4. SEC filing retrieval policy

SEC EDGAR is the canonical historical text source because it provides reproducible accession numbers and official acceptance timestamps. The retrieval policy selects a small, relevant filing set for both legs before any LLM call.

| **Document class** | **Selection rule at event time t**                                                                              |
|--------------------|-----------------------------------------------------------------------------------------------------------------|
| 8-K                | All 8-K filings accepted during the 30 calendar days ending at t.                                               |
| 10-Q / 10-K        | Most recent periodic filing accepted on/before t, normally <=180 days old; extend to <=400 days if necessary. |
| Amendments         | Include only if the amendment itself was accepted before t; retain amendment flag.                              |
| EX-99.x exhibits   | Include when attached to selected filings, especially earnings releases/guidance.                               |
| Foreign forms      | Outside MVP domestic-US scope; if later added, apply identical timestamp rules.                                 |

## 4.1 Retrieval query

The evidence selector first filters the SEC filing index by security_id, acceptance timestamp, and permitted form. It then resolves local cached filing bodies/chunks. Network retrieval occurs only for missing selected accession numbers and is cached immediately.

## 4.2 Evidence window provenance

- Store event_id, security_id, filing_id/accession, document_type, chunk_id, acceptance_datetime_utc, source_url, raw_file_path, and SHA-256 hash.
- Every agent claim cites one or more chunk IDs; UI citations resolve through these IDs.
- The same event/source snapshot must reproduce the same admissible-document set.

# 5. Document parsing, chunking, and evidence indexing

| **Stage**         | **Implementation rule**                                                                                                     |
|-------------------|-----------------------------------------------------------------------------------------------------------------------------|
| HTML/TXT clean    | Remove navigation/boilerplate while preserving headings, item labels, tables-as-text where meaningful, and source metadata. |
| Section detection | Prefer SEC item/section headings (e.g. Item 2.02, MD&A, Risk Factors) and exhibit boundaries.                               |
| Chunking          | Keep coherent sections; split oversized text into ~800-1,200-word chunks with ~100-word overlap.                            |
| Chunk ID          | Stable hash from filing ID + document type + section label + chunk order/content hash.                                      |
| Index fields      | security_id, form, acceptance time, section, document type, chunk text, token estimate, source URL/hash.                    |
| Persistence       | Write document_chunks Parquet and expose it through DuckDB curated schema.                                                  |

**Raw documents stay immutable**

Original SEC files remain in data/raw/sec/filings/... . Parsed chunks are derived objects and can be rebuilt under a parser version. This preserves a defensible audit path from agent claim to original filing.

# 6. Evidence retrieval and ranking

Retrieval is intentionally two-stage: deterministic admissibility filtering first, then relevance ranking. The language model never receives the entire filing corpus.

| **Step**                     | **Operation**                                                                                                                                                                                         |
|------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1\. Metadata filter          | Select chunks for leg A/B whose acceptance time <= event time and whose filings are in the evidence policy.                                                                                          |
| 2\. Query construction       | Build queries from company name/ticker, known event types, “earnings”, “guidance”, “acquisition”, “regulatory”, “litigation”, “management”, “product”, “financing”, and relationship-change concepts. |
| 3\. Core lexical rank        | TF-IDF/cosine or BM25-style ranking over the admissible chunk subset; fully local and reproducible.                                                                                                   |
| 4\. Optional semantic rerank | If time permits, a local embedding model may rerank the top lexical candidates; this is not required for core correctness.                                                                            |
| 5\. Diversity rule           | Limit repeated near-duplicate chunks from one exhibit and retain evidence from both legs when available.                                                                                              |
| 6\. Evidence pack            | Default max 12 chunks total, normally <=6 per leg, ordered with provenance and timestamps.                                                                                                           |

## 6.1 Why retrieval is bounded

- Reduces hallucination surface by giving the LLM fewer irrelevant documents.
- Keeps token/API cost predictable.
- Makes human verification feasible because every conclusion points to a small evidence set.
- Prevents a company with a huge filing history from dominating simply because it has more text.

# 7. Structured catalyst extraction

The Catalyst Extraction Agent converts the evidence pack into machine-readable event objects. It does not decide whether the pair should be traded and does not output a reversion probability.

| **Field**              | **Allowed values / contract**                                                                               |
|------------------------|-------------------------------------------------------------------------------------------------------------|
| event_type             | EARNINGS, GUIDANCE, M&A, REGULATORY, LITIGATION, MANAGEMENT, PRODUCT, FINANCING, MACRO, SECTOR, NONE, OTHER |
| affected_leg           | A, B, BOTH, UNKNOWN                                                                                         |
| direction              | POSITIVE, NEGATIVE, MIXED, NEUTRAL, UNKNOWN                                                                 |
| materiality            | LOW, MEDIUM, HIGH, UNKNOWN                                                                                  |
| relationship_relevance | LOW, MEDIUM, HIGH, UNKNOWN                                                                                  |
| confidence             | 0-1 confidence in extraction/classification only; not a trading probability                                 |
| evidence_ids           | Non-empty chunk IDs for every material non-NONE claim                                                       |
| source_timestamp       | Latest source timestamp supporting the event; must be <= event cutoff                                      |
| summary                | Short source-bounded explanation; no unsupported external knowledge                                         |

## 7.1 Multiple events

The extractor may return multiple catalyst records. A high-materiality one-sided event must not be diluted by averaging it with unrelated low-materiality items. The downstream validator receives the full list and an explicit dominant-event flag when justified by evidence.

## 7.2 NONE versus UNKNOWN

| **State** | **Meaning**                                                                                     |
|-----------|-------------------------------------------------------------------------------------------------|
| NONE      | Evidence retrieval succeeded and no material catalyst was found in the admissible evidence set. |
| UNKNOWN   | Evidence coverage/retrieval/validation is insufficient to make a defensible statement.          |

# 8. Multi-agent roles and mandates

| **Agent**                 | **Mandate**                                                                                                 | **Forbidden behaviour**                                              |
|---------------------------|-------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| Catalyst Extraction       | Classify source-grounded events into the fixed schema.                                                      | No trade recommendation; no invented catalyst; no market statistics. |
| Mean-Reversion Advocate   | Build the strongest evidence-based case that the relation remains economically valid.                       | Cannot ignore adverse evidence; must cite sources/quant state.       |
| Structural-Break Advocate | Build the strongest evidence-based case that new information justifies persistent repricing.                | Cannot turn speculation into a fact; must cite sources.              |
| Risk / Validation         | Audit both cases, provenance, timestamp validity, contradictions, missing evidence, and mandate compliance. | Cannot change deterministic market/ML inputs or invent citations.    |
| Decision Controller       | Deterministic software rules combine validated state.                                                       | Not an LLM agent; never free-form.                                   |

**Adversarial design purpose**

The two advocate agents are not votes. They are structured falsification tools: each must construct the strongest defensible case for a competing explanation using the same evidence and quantitative state.

# 9. LangGraph orchestration and shared state

| **Node**                  | **Reads**                                  | **Writes**                                   |
|---------------------------|--------------------------------------------|----------------------------------------------|
| load_event                | event_id                                   | quant_state + version IDs                    |
| select_evidence           | event + source index                       | admissible document/chunk IDs                |
| rank_evidence             | admissible chunks                          | bounded evidence_pack                        |
| extract_catalysts         | evidence_pack                              | catalyst_state                               |
| mean_reversion_advocate   | quant_state + catalyst_state + evidence    | mean_reversion_case                          |
| structural_break_advocate | same shared evidence/state                 | structural_break_case                        |
| validate                  | both cases + sources + deterministic state | validation_state + break-risk recommendation |
| controller                | validated state + policy                   | decision_state                               |
| persist                   | all validated outputs                      | DuckDB rows + cache manifest                 |

## 9.1 Execution topology

After catalyst extraction, the two advocates run in parallel because neither should see the other agent's draft before producing its own case. Their outputs then converge at the Risk / Validation node. This preserves genuine competing hypotheses rather than sequential anchoring.

**Bounded execution**

Each node has a timeout, retry limit, maximum evidence size, schema validator, and explicit failure state. If a node repeatedly fails, the workflow terminates safely with ABSTAIN rather than hanging the demo.

# 10. Mean-Reversion Advocate

## 10.1 Inputs

- Current z-score and direction, relationship validity, half-life, beta stability, recent crossing history.
- Calibrated P(revert) and selected SHAP drivers, clearly marked as model outputs rather than facts about causality.
- Market context/market/sector state.
- Identical catalyst records and evidence pack used by the opposing advocate.

## 10.2 Required output

| **Field**                    | **Meaning**                                                                      |
|------------------------------|----------------------------------------------------------------------------------|
| thesis                       | Short statement of why the historical relation may remain economically valid.    |
| supporting_claims            | List of evidence-backed claims; each has evidence_ids or quant field references. |
| counterevidence_acknowledged | Material facts that weaken the mean-reversion case.                              |
| evidence_strength            | LOW/MEDIUM/HIGH based on source support, not rhetorical confidence.              |
| uncertainties                | Missing/ambiguous evidence.                                                      |
| source_ids                   | All cited chunk IDs.                                                             |

## 10.3 Appropriate evidence

- Sector-wide movement affecting both firms.
- No material one-sided filings despite complete source coverage.
- Stable rolling pair diagnostics and modest beta drift.
- Prior similar divergences, only if analogue retrieval is explicitly implemented point-in-time; otherwise omit.
- Quantitative score/SHAP as supporting state, never as proof that the structural-break hypothesis is false.

# 11. Structural-Break Advocate

## 11.1 Required output

| **Field**                    | **Meaning**                                                                 |
|------------------------------|-----------------------------------------------------------------------------|
| thesis                       | Why current public information may justify a persistent relative repricing. |
| candidate_break_events       | Referenced structured events ranked by materiality/relevance.               |
| economic_link                | How each event plausibly changes one leg relative to the other.             |
| counterevidence_acknowledged | Facts that make the break interpretation less certain.                      |
| evidence_strength            | LOW/MEDIUM/HIGH based on validated support.                                 |
| uncertainties                | Missing context or ambiguous source language.                               |
| source_ids                   | All cited chunk IDs.                                                        |

## 11.2 High-value structural-break evidence

- One-sided earnings/guidance shock.
- M&A or divestiture that changes business mix or capital structure.
- Regulatory ruling, litigation, patent/product event, or material financing stress.
- Management change only when the filing/evidence gives a plausible relationship-relevant consequence.
- Business-model change or company-specific exposure change.

**Materiality is relative, not merely dramatic**

A newsworthy event is not automatically a structural break. The agent must explain why it changes the economics of one leg relative to its historical peer relationship.

# 12. Risk / Validation Agent

The validator is the control point between generative reasoning and the deterministic decision policy. It verifies source use and consistency; it is not a third investment opinion.

| **Check**                 | **Validation rule**                                                                                          |
|---------------------------|--------------------------------------------------------------------------------------------------------------|
| Citation existence        | Every cited evidence_id must exist in the evidence pack.                                                     |
| Timestamp                 | All source timestamps <= event cutoff.                                                                      |
| Claim support             | Material claims must be directly supported or explicitly marked as inference.                                |
| Deterministic consistency | Agents may not alter z, P(revert), pair status, market-context state, or other system values.                |
| Contradictions            | Surface conflicts between advocates or among sources; do not resolve by rhetorical preference.               |
| Coverage                  | Distinguish complete “no event found” from failed/incomplete retrieval.                                      |
| Mandate                   | Reject outputs containing unauthorised trade instructions, fabricated prices, or unsupported external facts. |
| Schema                    | All required fields/types/enums pass Pydantic validation.                                                    |

## 12.1 Validation output

| **Field**                 | **Values**                           |
|---------------------------|--------------------------------------|
| validation_status         | PASS / PASS_WITH_WARNINGS / FAIL     |
| source_completeness       | COMPLETE / PARTIAL / UNKNOWN         |
| contradiction_flag        | true / false                         |
| invalid_claim_count       | integer                              |
| break_risk_recommendation | LOW / MEDIUM / HIGH / UNKNOWN        |
| abstain_recommended       | true / false                         |
| reason_codes              | fixed list of machine-readable flags |

# 13. Break-risk synthesis

Break risk is a structured categorical assessment derived from validated event materiality, one-sidedness, relationship relevance, and the adversarial cases. It is deliberately distinct from the XGBoost reversion probability.

| **Break risk** | **Working interpretation**                                                                                                      |
|----------------|---------------------------------------------------------------------------------------------------------------------------------|
| LOW            | No validated high/medium relationship-relevant one-sided catalyst; source coverage adequate; structural-break case weak.        |
| MEDIUM         | Materiality/relevance is moderate, evidence is conflicting, or a one-sided event is plausible but not decisive.                 |
| HIGH           | Validated high-materiality, high-relevance one-sided event with strong source support, or multiple consistent break indicators. |
| UNKNOWN        | Evidence coverage/validation insufficient; retrieval failure; unresolved contradictions that prevent defensible classification. |

**No arithmetic pseudo-probability**

Do not convert LLM confidence into a fake “83% break probability”. LOW/MEDIUM/HIGH/UNKNOWN is easier to validate and avoids confusing language-model confidence with calibrated financial probability.

# 14. Deterministic decision controller

The controller is ordinary deterministic Python. It evaluates hard data/risk gates first, then probability and break-risk policy. Every status includes reason codes and a policy version.

| **Input class** | **Examples**                                                                                       |
|-----------------|----------------------------------------------------------------------------------------------------|
| Pair validity   | ACTIVE/WATCH/RETIRED, current cointegration validity, beta stability.                              |
| ML output       | Calibrated P(revert), probability bucket, model/calibrator/version, missing-feature flags.         |
| Agent output    | Validated break risk, event materiality/relevance, affected leg, source completeness, uncertainty. |
| Market context  | Observable market/sector/VIX stress context.                                                       |
| Implementation  | Liquidity/cost/short-side flags.                                                                   |
| Data quality    | Stale/missing market data, source retrieval failure, invalid agent output.                         |

## 14.1 Evaluation order

| **Priority** | **Gate**                                                                                                                   |
|--------------|----------------------------------------------------------------------------------------------------------------------------|
| 1            | Critical data/source failure -> ABSTAIN.                                                                                  |
| 2            | Pair RETIRED/invalid or hard liquidity/implementation failure -> NO TRADE.                                                |
| 3            | Validated HIGH break risk or HIGH-materiality one-sided relationship-relevant catalyst -> NO TRADE.                       |
| 4            | LOW model probability -> NO TRADE.                                                                                        |
| 5            | Intermediate probability, MEDIUM break risk, stressed market conditions, soft warning, or conflicting evidence -> REVIEW. |
| 6            | Only if all hard gates pass, P(revert) is high and break risk LOW -> CANDIDATE.                                           |

# 15. Decision rules and risk gates

| **Status** | **Working default conditions**                                                                                                                                                                      |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CANDIDATE  | Pair ACTIVE; data/source and liquidity gates pass; calibrated P(revert) >= 0.65; break risk LOW; no HIGH-materiality one-sided relationship-relevant event; no unresolved hard warning.            |
| REVIEW     | 0.45 <= P(revert) < 0.65, or break risk MEDIUM, or unusual/stressed market conditions, conflicting evidence, partial source coverage that is still interpretable, or soft implementation warning. |
| NO TRADE   | P(revert) < 0.45, pair invalid/retired, HIGH break risk, validated HIGH-materiality one-sided break event, or hard implementation/risk failure.                                                    |
| ABSTAIN    | Critical evidence/data unavailable, source timestamps unreliable, agent validation FAIL, missing critical model input, or system cannot make a defensible classification.                           |

**Policy thresholds are validation choices**

0.45 and 0.65 are working starting values. They must be selected/frozen using training/validation evidence before final-test evaluation. The test set cannot be used to make the policy look better.

## 15.1 Full-system backtest convention

For automated historical strategy evaluation, only CANDIDATE events enter a simulated position. REVIEW, NO TRADE, and ABSTAIN are treated as withheld opportunities, while their separate counts/reasons are still reported.

# 16. Abstention and failure handling

| **Failure**                               | **System response**                                                                                          |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| No admissible filing found, index healthy | Extractor may return NONE; not automatically an abstention.                                                  |
| SEC index/download unavailable            | ABSTAIN if evidence is required for the full-system decision.                                                |
| Chunk parser fails for one document       | Use remaining evidence only if completeness remains acceptable; otherwise ABSTAIN.                           |
| LLM timeout                               | Retry within limit; on repeated failure -> ABSTAIN.                                                         |
| Malformed JSON/schema                     | One repair/retry path; repeated failure -> validation FAIL / ABSTAIN.                                       |
| Invalid citation                          | Validator removes/rejects unsupported claim; high-impact invalidity -> ABSTAIN.                             |
| Agents disagree                           | Not a failure. Validator records contradiction; usually REVIEW unless evidence clearly supports a hard veto. |
| SHAP unavailable                          | Does not invalidate P(revert); agent prompt omits SHAP and controller notes explanation unavailable.         |

## 16.1 Why abstention is a product feature

The system is explicitly allowed to decline to classify when evidence is not trustworthy. This makes missing historical text, API failures, and LLM uncertainty visible rather than converting them into silent false confidence.

# 17. Prompting, hallucination, and prompt-injection controls

| **Control**                        | **Implementation**                                                                                          |
|------------------------------------|-------------------------------------------------------------------------------------------------------------|
| Role / task / format / constraints | Each agent has a fixed role, bounded task, explicit JSON schema, and forbidden outputs.                     |
| Source grounding                   | Every material textual claim requires an evidence ID from the supplied pack.                                |
| Document isolation                 | Retrieved filing text is delimited as untrusted evidence; instructions inside documents are never followed. |
| No unrestricted browsing           | Historical agents cannot call arbitrary web search.                                                         |
| Deterministic numeric state        | Prices/statistics/model scores injected as typed fields; LLM cannot recompute/override them.                |
| Schema validation                  | Pydantic rejects missing enums/types/invalid evidence references.                                           |
| Abstention                         | Unknown/missing evidence is an allowed output.                                                              |
| Audit log                          | Model, prompt version, evidence IDs, token/cost metadata, retries, and result hash stored.                  |

## 17.1 Prompt content principle

Prompts should ask for concise reasoning summaries and cited structured conclusions, not hidden chain-of-thought. The stored audit object contains claims, evidence links, counterevidence, and reason codes sufficient to evaluate the result without requiring private reasoning traces.

# 18. Caching, reproducibility, and cost control

Agent results are expensive relative to deterministic calculations, so every successful node output is cacheable. Historical reruns should reuse identical results when the event, evidence set, prompt, and model configuration are unchanged.

| **Cache key component**            | **Why it matters**                                |
|------------------------------------|---------------------------------------------------|
| event_id                           | Identifies the financial decision point.          |
| source_snapshot_id / evidence_hash | Invalidates cache if admissible evidence changes. |
| retrieval_version                  | Invalidates if chunk/ranking policy changes.      |
| prompt_version                     | Separates prompt experiments.                     |
| llm_model_id + temperature/config  | Separates provider/model behaviour.               |
| agent_schema_version               | Separates output contracts.                       |

## 18.1 Inference settings

- Use low temperature / deterministic mode where supported.
- Cap evidence count and output tokens.
- Retry only deterministic operational failures; do not endlessly resample for a preferred answer.
- Cache final validated outputs for demo mode.
- Record token counts and estimated API cost per event when provider metadata is available.

# 19. Storage schemas and artefacts

| **Object**                 | **Grain**                  | **Required fields**                                                                                                  |
|----------------------------|----------------------------|----------------------------------------------------------------------------------------------------------------------|
| analytics.event_evidence   | event x chunk              | event_id, chunk_id, rank, leg, relevance_score, source timestamp, retrieval_version                                  |
| analytics.catalyst_events  | event x extracted catalyst | event_id, catalyst_id, type, leg, direction, materiality, relevance, confidence, evidence_ids, model/prompt versions |
| analytics.agent_findings   | event x agent role         | event_id, role, thesis, claims JSON, evidence_ids, strength, uncertainty, validation flags, versions                 |
| analytics.agent_validation | event                      | validation_status, completeness, contradiction, invalid claims, break risk, abstain flag, reason codes               |
| analytics.decisions        | event x policy version     | event_id, final_status, P(revert), break_risk, gate flags, reason_codes, model/policy/source versions                |
| ops.agent_runs             | one orchestration run      | run_id, event_id, start/end, node statuses, retries, token/cost, cache hits, errors                                  |

## 19.1 Artefacts

- Versioned prompt templates and schema definitions.
- Retrieval configuration and optional embedding artefact if used.
- Cached JSON outputs keyed by event/evidence/model/prompt versions.
- Human-labelled evaluation subset and annotation guide.

# 20. UI integration

| **Pair Detail region** | **Displayed content**                                                                                                  |
|------------------------|------------------------------------------------------------------------------------------------------------------------|
| Catalyst timeline      | Chronological admissible events with affected leg, type, materiality, source timestamp and source link/ID.             |
| Evidence panel         | Top source snippets, filing form/accession, section label, acceptance time.                                            |
| Adversarial analysis   | Side-by-side Mean-Reversion and Structural-Break cases with cited claims and acknowledged counterevidence.             |
| Validation             | Source completeness, contradiction/invalid-claim flags, break risk, abstention warning.                                |
| Final status card      | CANDIDATE / REVIEW / NO TRADE / ABSTAIN, calibrated P(revert), break risk, deterministic reason codes, policy version. |
| Audit expander         | Model/prompt/source/retrieval versions, cache status, run timestamp, evidence IDs.                                     |

**UI principle**

The user should be able to move from every agent statement to the underlying stored evidence. The agent prose is not the audit trail; the evidence IDs and deterministic system state are.

# 21. Agent-specific evaluation hooks

Detailed evaluation belongs in the Backtesting & Evaluation specification, but this pipeline must emit the fields required to measure its contribution.

| **Metric**                        | **Required stored output**                             |
|-----------------------------------|--------------------------------------------------------|
| Failed-opportunity rejection rate | Final status for every baseline failure.               |
| False-veto rate                   | Final status for every baseline success.               |
| Event extraction accuracy         | Structured catalyst fields on a human-labelled subset. |
| Evidence validity rate            | Claim-to-evidence validation result / manual check.    |
| Abstention rate                   | ABSTAIN count and reason codes.                        |
| Agent disagreement rate           | Whether advocates materially conflict.                 |
| Source coverage                   | COMPLETE/PARTIAL/UNKNOWN by event and leg.             |

## 21.1 Human-labelled subset

Create a stratified evaluation subset of at least 50 historical events (aim for ~100 if feasible), spanning sectors, successes/failures, and event types. Human reviewers label event_type, affected_leg, materiality, relationship relevance, and whether each selected source genuinely supports the extracted claim.

# 22. Functions, repository modules, and jobs

| **Module / function**                                          | **Responsibility**                                                  |
|----------------------------------------------------------------|---------------------------------------------------------------------|
| evidence/select.py::select_admissible_documents                | Apply timestamp/form/lookback policy for both legs.                 |
| evidence/chunk.py::parse_and_chunk_filing                      | Convert cached SEC body/exhibits into versioned chunks.             |
| evidence/retrieve.py::rank_event_evidence                      | Metadata filter + lexical rank + optional semantic rerank.          |
| agents/extract.py::extract_catalysts                           | Structured event extraction.                                        |
| agents/advocates.py::run_mean_reversion / run_structural_break | Parallel hypothesis construction.                                   |
| agents/validate.py::validate_agent_findings                    | Citations, timestamps, consistency, schema, break risk.             |
| controller/policy.py::apply_decision_policy                    | Deterministic final status and reason codes.                        |
| agents/graph.py::run_agent_pipeline                            | LangGraph orchestration, retries, cache, persistence.               |
| jobs/run_event_intelligence.py                                 | Batch historical events or current candidates through the pipeline. |

## 22.1 Dependencies

Core dependencies remain Python 3.11, pandas/NumPy, DuckDB/Parquet, Pydantic, LiteLLM, LangGraph, and scikit-learn for deterministic TF-IDF retrieval. An optional local sentence-transformers dependency may be added only if semantic reranking is implemented and versioned.

# 23. Build sequence and acceptance criteria

| **Order** | **Deliverable**       | **Acceptance condition**                                                       |
|-----------|-----------------------|--------------------------------------------------------------------------------|
| 1         | SEC evidence selector | Given historical event, returns only pre-event eligible filings for both legs. |
| 2         | Parser/chunker/index  | Stored chunk reproduces to raw filing/hash and section metadata.               |
| 3         | Retrieval             | Top evidence pack deterministic for fixed inputs/config.                       |
| 4         | Catalyst extraction   | Schema-valid output with valid evidence IDs; NONE/UNKNOWN distinction works.   |
| 5         | Advocates             | Parallel cases use identical evidence and acknowledge counterevidence.         |
| 6         | Validator             | Detects invalid citations/timestamps/contradictions and can recommend ABSTAIN. |
| 7         | Controller            | Deterministic unit tests cover all CANDIDATE/REVIEW/NO TRADE/ABSTAIN branches. |
| 8         | Caching/persistence   | Rerun hits cache and reproduces stored output/version lineage.                 |
| 9         | UI                    | Pair Detail displays citations, cases, validation and final reason codes.      |
| 10        | Human subset          | Extraction/evidence metrics can be computed on labelled events.                |

- No material agent claim without valid source provenance.
- No historical source timestamp after the event cutoff.
- No LLM-generated market statistics or model probabilities.
- Repeated LLM/tool failure terminates safely.
- Final status is exactly reproducible from persisted validated state + policy version.

# Appendix A. Working configuration defaults

| **Parameter**           | **Working default**                                                                                          |
|-------------------------|--------------------------------------------------------------------------------------------------------------|
| Canonical text source   | SEC EDGAR                                                                                                    |
| Recent event lookback   | 8-Ks accepted in prior 30 calendar days                                                                      |
| Periodic context        | Latest 10-Q/10-K <=180 days; extend <=400 days if required                                                 |
| News                    | Optional current/demo GDELT enrichment; excluded from headline historical Model B and Full-System evaluation |
| Chunk size              | ~800-1,200 words, ~100-word overlap when splitting                                                           |
| Evidence pack           | Max ~12 chunks, normally <=6 per leg                                                                        |
| Core ranker             | Metadata filtering + TF-IDF/cosine ranking                                                                   |
| Semantic rerank         | Optional local embeddings only                                                                               |
| LLM abstraction         | LiteLLM; configured model must support reliable structured output                                            |
| Orchestration           | LangGraph typed state                                                                                        |
| Temperature             | Low/deterministic where supported                                                                            |
| Candidate P(revert)     | >=0.65 starting threshold                                                                                   |
| Review probability band | 0.45-0.65 starting band                                                                                      |
| High break risk         | Hard NO TRADE                                                                                                |
| Unknown/failed evidence | ABSTAIN when classification is not defensible                                                                |

# Appendix B. JSON-style field reference

## B.1 Catalyst object

| **Field**              | **Type**       |
|------------------------|----------------|
| catalyst_id            | string         |
| event_type             | enum           |
| affected_leg           | enum           |
| direction              | enum           |
| materiality            | enum           |
| relationship_relevance | enum           |
| confidence             | float 0-1      |
| evidence_ids           | list\[string\] |
| source_timestamp       | datetime       |
| summary                | string         |

## B.2 Advocate object

| **Field**                    | **Type**                     |
|------------------------------|------------------------------|
| role                         | enum                         |
| thesis                       | string                       |
| supporting_claims            | list\[{claim,evidence_ids}\] |
| counterevidence_acknowledged | list\[string\]               |
| evidence_strength            | LOW/MEDIUM/HIGH              |
| uncertainties                | list\[string\]               |
| source_ids                   | list\[string\]               |

## B.3 Controller output

| **Field**              | **Type**                          |
|------------------------|-----------------------------------|
| event_id               | string                            |
| final_status           | CANDIDATE/REVIEW/NO TRADE/ABSTAIN |
| reason_codes           | list\[enum\]                      |
| calibrated_probability | float                             |
| break_risk             | LOW/MEDIUM/HIGH/UNKNOWN           |
| policy_version         | string                            |
| model_version          | string                            |
| source_snapshot_id     | string                            |
| decision_timestamp     | datetime                          |

# Point-in-Time Event Intelligence, Multi-Agent Investigation & Decision Control

> **Agent-use specification.** Canonical implementation decisions are in [`../DECISIONS.md`](../DECISIONS.md). This Markdown is the coding-agent source of truth for this subsystem. The PDF in `docs/archive/pdfs/` is archival/human-readable only. Current decisions and the frozen v2 protocol override older working defaults here.

The Phase 5 architecture was amended on 2026-10-11 under the user's explicit
authorization. It adapts the Week 4 TradingAgents researcher/trader/risk/manager
flow to pair relationships: independent opening cases, one rebuttal exchange,
separate synthesis and validation, then a deterministic controller. Existing
quantitative, Model B, SEC and FinBERT outputs provide the analyst inputs. This
does not add live orders, contemporary historical browsing or new data sources.
See [decision 26](../DECISIONS.md#26-phase-5-bounded-adversarial-investigation).

# 1. Role, system boundary, and end-to-end workflow

The quantitative stack answers “is this a statistically unusual, historically promising divergence?” The language-AI stack answers a different question: “is there contemporaneous public evidence that makes the historical relationship economically unreliable?”

| **Stage**            | **Input**                                                                               | **Output**                                                                 |
|----------------------|-----------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| Event intelligence   | event timestamp + both securities + stored SEC filing corpus                            | Small, admissible evidence set with provenance.                            |
| Catalyst extraction  | retrieved chunks                                                                        | Structured event schema for each leg; persisted as Model B event features. |
| Adversarial analysis | Model B quantitative state + same evidence + extracted events                           | Independent mean-reversion and structural-break openings, then one rebuttal each. |
| Synthesis            | openings + rebuttals + unchanged analyst inputs                                         | Cited research interpretation, unresolved questions and proposed break risk. |
| Validation           | synthesis + all cases + citations + deterministic inputs                                | Mechanical and semantic source checks; validated categorical break risk.   |
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
| rebuttal_state   | each role's response to the opposing opening, with source/quant references |
| synthesis_state  | supported interpretation, counterevidence, unresolved issues, proposed risk |
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
| Chunking          | Reuse the existing versioned SEC parser and frozen source-pack policy; Phase 5 must not rechunk historical evidence.      |
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
| 6\. Evidence pack            | Reuse the registered bounded source pack: at most eight chunks per leg and 32,000 characters total, with exact provenance and timestamps.                                                             |

## 6.1 Why retrieval is bounded

- Reduces hallucination surface by giving the LLM fewer irrelevant documents.
- Keeps token/API cost predictable.
- Makes human verification feasible because every conclusion points to a small evidence set.
- Prevents a company with a huge filing history from dominating simply because it has more text.

# 7. Structured catalyst extraction

The Catalyst Extraction Agent converts the evidence pack into machine-readable event objects. It does not decide whether the pair should be traded and does not output a reversion probability.

For primary v2, the implemented extraction schema and its stored UNKNOWN/NONE
semantics govern the reused inputs. The broader field reference below is an
original design reference, not authorization to expand v2 categories, rerun its
extractions or change its frozen schedule. Any future schema expansion requires
a separate generation; Phase 5 consumes the existing compact catalyst contract.

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
| Synthesis / Facilitator   | Reconcile the openings and rebuttals into a concise cited research interpretation and proposed break risk. | Cannot authorize a trade, resolve uncertainty by voting, or invent evidence. |
| Risk / Validation         | Audit all cases and synthesis for semantic support, contradictions, coverage, break risk and mandate compliance. | Cannot change deterministic market/ML inputs or override failed mechanical checks. |
| Decision Controller       | Deterministic software rules combine validated state.                                                       | Not an LLM agent; never free-form.                                   |

**Adversarial design purpose**

The two advocate agents are not votes. They are structured falsification tools: each must construct the strongest defensible case for a competing explanation using the same evidence and quantitative state.

Gemma serves both advocate roles, including their rebuttals. Flash-Lite serves
the distinct synthesis and semantic-validation roles. Each role has its own
versioned prompt/schema and output identity even when two roles use the same
model. Model identifiers are configurable and frozen in each run manifest;
there is no silent model fallback. The v2 catalyst-only Gemma adapter and its
frozen 500-event extraction schedule remain a separate contract.

# 9. LangGraph orchestration and shared state

| **Node**                  | **Reads**                                  | **Writes**                                   |
|---------------------------|--------------------------------------------|----------------------------------------------|
| load_event                | frozen event/model/evidence identities     | immutable analyst inputs + version IDs       |
| deterministic_preflight   | event-time lifecycle + model + hard gates | eligibility, skip reasons or graph admission |
| mean_reversion_advocate   | quant_state + catalyst_state + evidence    | independent mean_reversion_case              |
| structural_break_advocate | same shared evidence/state                 | independent structural_break_case            |
| mean_reversion_rebuttal   | both openings + unchanged analyst inputs   | one mean-reversion rebuttal                  |
| structural_break_rebuttal | both openings + unchanged analyst inputs   | one structural-break rebuttal                |
| synthesize                | both openings/rebuttals + analyst inputs   | cited synthesis + proposed categorical risk  |
| mechanical_checks         | all claims + source/quantitative records   | exact-quote, identity, time and schema checks |
| validate                  | all cases/synthesis + mechanical results  | semantic checks + validated categorical risk |
| controller                | validated state + policy                   | decision_state                               |
| persist                   | all validated outputs                      | DuckDB rows + cache manifest                 |

## 9.1 Execution topology

The two opening advocates run independently in parallel; neither receives the
other's draft. Their completed openings then feed two independent rebuttal nodes.
Each rebuttal sees both openings and the original analyst inputs, but not the
other rebuttal. This is exactly one bounded exchange. A separate synthesis node
then reads both openings and rebuttals. Risk/Validation assesses that synthesis
and the full cited record before the Python controller runs. Additional rounds
require a new graph/prompt version and an explicitly recorded amendment.

Historical runs reuse versioned admissible SEC packs, structured catalysts and
FinBERT features from earlier layers; they do not regenerate them inside the
debate. The first engineering slice accepts an explicit typed input file and
mock responses. An accepted-generation adapter, live pilot and human quality
evaluation remain separate gates. Agents never receive realized target outcomes.

**Bounded execution**

Each provider node has a timeout, retry limit, maximum evidence/output size,
schema validator and explicit failure state. Every attempt, including retries,
counts against the shared configured budget. If a required node fails, the
workflow records an explicit failure and terminates safely with ABSTAIN.
Paid API use, hidden SDK retries and automatic model fallbacks are disabled.

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

# 12. Bounded rebuttals, synthesis and Risk / Validation

## 12.1 Rebuttals

Each advocate responds once to the opposing opening, identifies its strongest
source-supported point, and explains which conclusions remain uncertain or
unsupported. New claims must use the same admissible pack or exact quantitative
field references. A rebuttal may revise a hypothesis; it may not introduce
external facts, request more rounds, alter model values or recommend a final
controller status.

## 12.2 Synthesis / Facilitator

The facilitator produces a short research interpretation with supporting claims,
counterevidence, unresolved issues and a proposed LOW/MEDIUM/HIGH/UNKNOWN break
risk. Its role resembles the lecture's trader proposal, but it does not produce
order instructions. It does not average advocate confidence or treat agreement
as correctness. Proposed risk is untrusted until the separate validator accepts
its source support and coverage.

## 12.3 Mechanical and semantic validation

The validator is the control point between generative reasoning and the deterministic decision policy. It verifies source use and consistency; it is not a third investment opinion.

Python checks schema, exact quote matching, cited chunk and issuer identity,
historical timestamps and quantitative-field references. Flash-Lite separately
checks whether those valid quotes actually support each material claim, whether
facts are distinguished from inference, and whether synthesis acknowledges
contradictions and coverage gaps. Exact matching proves a quote exists; it does
not prove the model's interpretation is correct. A semantic PASS cannot override
a failed mechanical check. Human source-support evaluation remains mandatory.

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

## 12.4 Validation output

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

Break risk is a structured categorical assessment proposed by synthesis and
accepted or rejected by the separate validator using event materiality,
one-sidedness, relationship relevance, the cited adversarial cases and source
coverage. It is deliberately distinct from calibrated Model B P(revert).

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
| 2            | Pair RETIRED or hard liquidity/implementation failure -> NO TRADE; WATCH cannot be an automatic candidate.                  |
| 3            | Validated HIGH break risk or HIGH-materiality one-sided relationship-relevant catalyst -> NO TRADE.                       |
| 4            | LOW model probability -> NO TRADE.                                                                                        |
| 5            | Intermediate probability, MEDIUM break risk, stressed market conditions, soft warning, or conflicting evidence -> REVIEW. |
| 6            | Only if all hard gates pass, P(revert) is high and break risk LOW -> CANDIDATE.                                           |

# 15. Decision rules and risk gates

| **Status** | **Working default conditions**                                                                                                                                                                      |
|------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| CANDIDATE  | Pair ACTIVE; data/source and liquidity gates pass; calibrated P(revert) >= 0.65; break risk LOW; no HIGH-materiality one-sided relationship-relevant event; no unresolved hard warning.            |
| REVIEW     | 0.45 <= P(revert) < 0.65, or break risk MEDIUM, or unusual/stressed market conditions, conflicting evidence, partial source coverage that is still interpretable, or soft implementation warning. |
| NO TRADE   | P(revert) below the frozen lower band, pair RETIRED, HIGH break risk, validated HIGH-materiality one-sided break event, or hard implementation/risk failure.                                     |
| ABSTAIN    | Critical evidence/data unavailable, source timestamps unreliable, agent validation FAIL, missing critical model input, or system cannot make a defensible classification.                           |

**Policy thresholds are validation choices**

0.45 and 0.65 are working starting values. They must be selected/frozen using training/validation evidence before final-test evaluation. The test set cannot be used to make the policy look better.

The Phase 5 production-policy template starts DRAFT with unset thresholds and
fails closed. The synthetic fixture uses explicit FIXTURE policy to exercise
branches; it is never a validated policy. WATCH or interpretable warnings may
produce REVIEW, while unknown required inputs remain ABSTAIN. Do not silently
adopt a fixture threshold as the accepted Model B trading threshold.

A stored HIGH-materiality, one-sided A/B catalyst with DIRECT relationship
relevance is source-grounded extraction, not automatic semantic confirmation.
If the separate validator neither confirms HIGH break risk nor confirms the
high-materiality one-sided veto, the controller retains REVIEW with
`UNRESOLVED_CATALYST_RISK`. It cannot silently downgrade that existing warning
to CANDIDATE. Unconfirmed extraction alone does not impose NO TRADE; confirmed
risk or a deterministic hard veto is required for that status.

## 15.1 Full-system backtest convention

For automated historical strategy evaluation, only CANDIDATE events enter a simulated position. REVIEW, NO TRADE, and ABSTAIN are treated as withheld opportunities, while their separate counts/reasons are still reported.

## 15.2 Investigation eligibility and denominator accounting

Full-System automatic candidates require an ACTIVE relationship at the event
timestamp and the frozen Model B candidate threshold, as well as all hard
data/risk/liquidity gates. Preflight may skip expensive agent calls when those
deterministic gates already make CANDIDATE impossible. Persist the event's
explicit status, skip reason and eligibility flags; no-call rows must not vanish
from the strategy denominator or masquerade as LOW risk.

Count eligible events after the actual accepted Model B fit. If quotas require a
subset, freeze a target-blind investigation schedule before those agent outputs
are evaluated, record its inclusion rule, and compare B versus Full System on
that same eligible scheduled population. Any optional REVIEW investigation or
quality-audit schedule is declared separately. Do not assume an arbitrary
500-event agent cap: the v2 500-event schedule concerns catalyst extraction.

This trading eligibility does not replace the broad 37,421-event matched A/B
forecasting population. Retain its UNKNOWN rows and broad-cohort comparisons.
Agent results from a scheduled subset do not establish Full-System performance
over all 37,421 events. Do not derive eligibility from future relationship state
or realized reversion outcomes.

# 16. Abstention and failure handling

| **Failure**                               | **System response**                                                                                          |
|-------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| No admissible filing found, index healthy | Extractor may return NONE; not automatically an abstention.                                                  |
| SEC index/download unavailable            | ABSTAIN if evidence is required for the full-system decision.                                                |
| Chunk parser fails for one document       | Use remaining evidence only if completeness remains acceptable; otherwise ABSTAIN.                           |
| LLM timeout                               | Retry within limit; on repeated failure -> ABSTAIN.                                                         |
| Malformed JSON/schema                     | Reject the output; required-stage failure -> ABSTAIN. Do not resample until a preferred valid answer appears. |
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
| graph_version + role/round         | Separates openings, rebuttals, synthesis and validation. |
| input/model/policy identities      | Binds exact analyst inputs, calibration and deterministic controller rules. |

## 18.1 Inference settings

- Use low temperature / deterministic mode where supported.
- Cap evidence count and output tokens.
- Retry only deterministic operational failures; do not endlessly resample for a preferred answer.
- Cache final validated outputs for demo mode.
- Record token counts and estimated API cost per event when provider metadata is available.
- Budget four Gemma calls and two Flash-Lite calls per complete uncached event
  before retries: two openings, two rebuttals, synthesis and validation.
- The first provider counter is shared within one invocation, including transport
  retries; it does not reconstruct unsaved failed-call history across restarts.
  Preserve terminal receipts and do not claim that a fresh instance resets the
  provider project's actual quota. Durable batch scheduling remains a later gate.
- Treat free-tier quotas as provider/project/model-specific limits that may
  change; configured pacing and per-run attempt caps are mandatory. A second
  API key for the same project does not create additional quota.
- Never spend live quota in fixture CI. A cache hit requires the complete input,
  schema, prompt, graph and model identity; reusing one stage cannot hide changed
  upstream outputs. Corrupt or mismatched cached objects are rejected.

# 19. Storage schemas and artefacts

| **Object**                 | **Grain**                  | **Required fields**                                                                                                  |
|----------------------------|----------------------------|----------------------------------------------------------------------------------------------------------------------|
| analytics.event_evidence   | event x chunk              | event_id, chunk_id, rank, leg, relevance_score, source timestamp, retrieval_version                                  |
| analytics.catalyst_events  | event x extracted catalyst | event_id, catalyst_id, type, leg, direction, materiality, relevance, confidence, evidence_ids, model/prompt versions |
| analytics.agent_findings   | event x agent role         | event_id, role, thesis, claims JSON, evidence_ids, strength, uncertainty, validation flags, versions                 |
| analytics.agent_rebuttals  | event x advocate role      | event_id, role, opening references, rebuttal claims, evidence/quant references, versions                             |
| analytics.agent_synthesis | event                      | interpretation, supported claims, counterevidence, unresolved issues, proposed break risk, versions                 |
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
| Debate and synthesis   | One rebuttal per role, facilitator interpretation and unresolved questions, with cited support.                        |
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

Create a fixed development annotation subset of at least 50 historical events
(aim for 100), spanning sectors, successes/failures and event types. Record the
selection timing and protocol before interpreting the agent evaluation; any
outcome stratification is an evaluation design and never enters agent prompts or
the target-blind production investigation schedule. Human reviewers label
event_type, affected_leg, materiality, relationship relevance and whether each
selected source genuinely supports the extraction, advocate and synthesis
claims. Include unsupported inferences, contradictions and appropriate UNKNOWN
or abstention as errors/coverage outcomes rather than dropping them.

Mock responses test orchestration, contracts, cache identity and safe controller
behavior only. They are not evidence that Gemma/Flash-Lite produce useful or
correct financial interpretations. Complete the real pilot and human gate before
claiming Phase 5 acceptance or a Full-System benefit.

# 22. Functions, repository modules, and jobs

| **Module / function**                                          | **Responsibility**                                                  |
|----------------------------------------------------------------|---------------------------------------------------------------------|
| intelligence/evidence.py                                      | Existing SEC selection, parsing and bounded evidence construction; reused by Phase 5. |
| intelligence/extraction.py + intelligence/gemma.py             | Existing catalyst-only contract; preserve frozen v2 outputs.        |
| agents/contracts.py                                           | Immutable explicit inputs, role schemas and mechanical grounding checks. |
| agents/providers.py                                           | Separate Phase 5 mock/live adapters, role prompts, pacing and attempt budgets. |
| decision/agent_policy.py                                       | Deterministic preflight, statuses and fixed reason codes.            |
| agents/pipeline.py                                             | `phase5-bounded-debate-v1` LangGraph topology, retries and immutable cache/receipt. |
| structural-break-agents                                        | Explicit fixture/input batch entry point; no analytical writes from app browsing. |

## 22.1 Dependencies

Core dependencies remain Python 3.11, pandas/NumPy, DuckDB/Parquet, Pydantic, LiteLLM, LangGraph, and scikit-learn for deterministic TF-IDF retrieval. An optional local sentence-transformers dependency may be added only if semantic reranking is implemented and versioned.

# 23. Build sequence and acceptance criteria

| **Order** | **Deliverable**       | **Acceptance condition**                                                       |
|-----------|-----------------------|--------------------------------------------------------------------------------|
| 1         | SEC evidence selector | Given historical event, returns only pre-event eligible filings for both legs. |
| 2         | Parser/chunker/index  | Stored chunk reproduces to raw filing/hash and section metadata.               |
| 3         | Retrieval             | Top evidence pack deterministic for fixed inputs/config.                       |
| 4         | Catalyst extraction   | Schema-valid output with valid evidence IDs; NONE/UNKNOWN distinction works.   |
| 5         | Advocates and debate  | Independent openings use identical inputs; exactly one rebuttal exchange.       |
| 6         | Synthesis/validator   | Separate stages check semantic support; mechanical checks cannot be overridden. |
| 7         | Controller            | Deterministic unit tests cover all CANDIDATE/REVIEW/NO TRADE/ABSTAIN branches. |
| 8         | Caching/persistence   | Rerun hits cache and reproduces stored output/version lineage.                 |
| 9         | UI                    | Pair Detail displays citations, cases, validation and final reason codes.      |
| 10        | Human subset          | Extraction/evidence metrics can be computed on labelled events.                |

- No material agent claim without valid source provenance.
- No historical source timestamp after the event cutoff.
- No LLM-generated market statistics or model probabilities.
- Repeated LLM/tool failure terminates safely.
- Final status is exactly reproducible from persisted validated state + policy version.
- Every investigated or skipped event retains its denominator record and reason.
- Genuine accepted-input integration and the human-labelled quality gate pass;
  mocked acceptance remains engineering evidence only.
- Prepare Phase 5 changes on its isolated branch while v2 is running; synchronize
  only after the full v2 feature/model/replay/CI/publication acceptance gates.

# Appendix A. Working configuration defaults

| **Parameter**           | **Working default**                                                                                          |
|-------------------------|--------------------------------------------------------------------------------------------------------------|
| Canonical text source   | SEC EDGAR                                                                                                    |
| Recent event lookback   | 8-Ks accepted in prior 30 calendar days                                                                      |
| Periodic context        | Latest 10-Q/10-K <=180 days; extend <=400 days if required                                                 |
| News                    | Optional current/demo GDELT enrichment; excluded from headline historical Model B and Full-System evaluation |
| Chunk policy            | Existing frozen versioned SEC parser; no Phase 5 rechunking                                                  |
| Evidence pack           | Reused registered source pack, max eight chunks per leg and 32,000 characters total                          |
| Core ranker             | Metadata filtering + TF-IDF/cosine ranking                                                                   |
| Semantic rerank         | Optional local embeddings only                                                                               |
| LLM abstraction         | Separate Phase 5 provider protocol; explicit structured schemas and no silent fallback                       |
| Orchestration           | LangGraph typed state                                                                                        |
| Advocate model          | Configured free Gemma; distinct role prompts, two openings and two rebuttals                                 |
| Synthesis/validation    | Configured free Flash-Lite; separate roles, two calls per complete event before retries                      |
| Debate rounds           | One bounded rebuttal exchange after independent openings                                                    |
| Temperature             | Low/deterministic where supported                                                                            |
| Candidate P(revert)     | >=0.65 starting threshold                                                                                   |
| Review probability band | 0.45-0.65 starting band                                                                                      |
| High break risk         | Hard NO TRADE                                                                                                |
| Unknown/failed evidence | ABSTAIN when classification is not defensible                                                                |

# Appendix B. First-slice JSON field reference

These names match `agents/contracts.py`. The human-facing output descriptions
above express the intended research content; they are not alternative JSON keys.
All objects reject extra properties. Evidence/model/event lineage is retained
in the enclosing investigation input and receipt rather than copied into every
role report.

## B.1 Catalyst object

| **Field**              | **Type**       |
|------------------------|----------------|
| event_type             | enum           |
| affected_leg           | enum           |
| direction              | enum           |
| materiality            | enum           |
| relationship_relevance | enum           |
| citations              | list of `{chunk_id, leg, quote}` objects |

This is the projection of a stored extraction used by the agents. It does not
rerun extraction or reinterpret stored confidence as correctness. Source clocks,
issuer, hash and offsets resolve through the supplied chunk records. UNKNOWN
and NONE retain their existing constrained categories and citation rules.

## B.2 Advocate object

| **Field**                    | **Type**                     |
|------------------------------|------------------------------|
| role                         | enum                         |
| stage                        | OPENING/REBUTTAL             |
| thesis                       | string                       |
| claims                       | list of claim objects        |
| counterevidence              | list of claim objects        |
| evidence_strength            | LOW/MEDIUM/HIGH/UNKNOWN      |
| uncertainties                | list\[string\]               |

## B.3 Controller output

| **Field**              | **Type**                          |
|------------------------|-----------------------------------|
| status                 | CANDIDATE/REVIEW/NO TRADE/ABSTAIN |
| reason_codes           | list\[enum\]                      |
| model_b_probability    | float or null                     |
| break_risk             | LOW/MEDIUM/HIGH/UNKNOWN           |
| policy_version         | string                            |

## B.4 Grounded claim

| **Field** | **Type** |
| --- | --- |
| claim_id | string |
| text | bounded concise string |
| kind | FACT/INFERENCE |
| citations | list of `{chunk_id, leg, quote}` objects |
| quant_refs | list of `{field, value}` objects |

Each claim requires a citation or an exact allowed quantitative reference.
Allowed references include the supplied model/relationship fields and per-leg
FinBERT probability/net/coverage values. Missing or changed values fail
mechanical validation. This proves grounding, not semantic truth.

## B.5 Synthesis

| **Field** | **Type** |
| --- | --- |
| summary | bounded concise string |
| proposed_break_risk | LOW/MEDIUM/HIGH/UNKNOWN |
| claims | list of claim objects |
| unresolved_conflicts | list of bounded strings |
| uncertainties | list of bounded strings |

## B.6 Semantic validation

| **Field** | **Type** |
| --- | --- |
| validation_status | PASS/PASS_WITH_WARNINGS/FAIL |
| source_completeness | COMPLETE/PARTIAL/UNKNOWN |
| contradiction_flag | boolean |
| invalid_claim_count | nonnegative integer |
| break_risk | LOW/MEDIUM/HIGH/UNKNOWN |
| abstain_recommended | boolean |
| high_materiality_one_sided_catalyst | boolean |
| reason_codes | list of fixed enums |
| claims | list of grounded claim objects |

Known non-failed semantic risk requires grounded validation claims. PASS cannot
hide invalid claims, abstention, incomplete coverage or a contradiction flag.
The controller independently checks mechanical support and retains unresolved
stored catalyst warnings; it does not treat validator prose as final authority.

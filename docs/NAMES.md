# Names: old and current

The repository was reorganised in Decision 115. Earlier decisions, archived documents and
the tag `archive/pre-cleanup` use the old names below. Nothing listed as *removed* changed a
result; every removed experiment keeps its entry in [DECISIONS.md](DECISIONS.md).

## Modules (`src/structural_break/`)

| Old | Current |
|---|---|
| `experiments/p6_improvement.py` | `pipeline/sources.py` (data binding; the Decision 43 experiment removed) |
| `experiments/p6_walkforward.py` | `pipeline/walkforward.py` |
| `experiments/p6_sec_features.py` | `pipeline/sec_timing.py` |
| `experiments/news_coverage.py` | `pipeline/news_features.py` |
| `experiments/catalyst_coverage.py` | `pipeline/catalysts.py` (the full-coverage catalyst run removed) |
| `experiments/headline_coverage.py` | `pipeline/headline_tone.py` |
| `experiments/p6_sec_explore.py` | `pipeline/news_filters.py` (R1 and the other filters; the exploration removed) |
| `experiments/p6_sec_explore2.py` | `pipeline/news_exit.py` (now also `EXIT` and `load_exits`) |
| `experiments/p6_sec_explore3.py` | removed (`EXIT`, `load_exits` moved to `pipeline/news_exit.py`) |
| `experiments/p6_quant_features.py` | `pipeline/features.py` |
| `experiments/p6_quant_ou.py` | `pipeline/ou_features.py` |
| — | `pipeline/build_inputs.py` (new: features, OU, R1, costs, residual targets, long paths) |
| `experiments/p6_boosting.py` | `forecast/model_b.py` (tuning removed) |
| `experiments/p6_boosting2.py` | `forecast/model_b_scores.py` (R0 only; round-2 variants removed) |
| `experiments/p6_coint.py` | removed |
| `experiments/p6_quant.py` | `forecast/harness.py` |
| `experiments/p6_quant_trading.py` | `book/trades.py` |
| `experiments/p6_quant_portfolio.py` | `book/portfolio.py` |
| `experiments/p6_portfolio.py` | `book/policy_portfolio.py` |
| `experiments/p6_quant_costs.py` | `book/costs.py` |
| `experiments/p6_resid.py` | `book/residual_sleeve.py` |
| `experiments/p6_halflife_exit.py` | `book/long_exit.py` (`simulate_long` only) |
| `experiments/p6_entry_vol.py` | removed |
| `experiments/p6_agents.py` | removed; `design_candidates` moved to `book/selection.py` |
| `experiments/p6_desk.py` | `agents/desk_runner.py` |
| `agents/debate_v2.py` | `agents/debate.py` (shared case format and advocate turns; the v2 graph removed) |
| `agents/desk_v3.py` | `agents/desk.py` |
| `agents/batch.py`, `cli.py`, `historical.py`, `historical_review.py`, `inputs.py`, `pipeline.py`, `prompts.py`, `providers.py`, `review.py` | removed (the original agent pipeline and the `structural-break-agents` command) |
| `intelligence/catalyst_v3.py` | `intelligence/catalysts.py` |

Tests follow their modules (`tests/test_p6_*.py` → `tests/test_pipeline_*`, `test_forecast_*`,
`test_book_*`; `test_agent_debate_v2.py` → `test_agent_debate.py`; `test_agent_desk_v3.py` →
`test_agent_desk.py`; `test_catalyst_v3.py` → `test_catalysts.py`).

## Scripts

| Old | Current |
|---|---|
| `scripts/quant_research/audit_final.py` | `scripts/overfitting_audit.py` |
| `scripts/quant_research/freeze_manifest.py` | `scripts/freeze_manifest.py` |
| `scripts/quant_research/figures.py` | `scripts/make_figures.py` |
| `scripts/quant_research/stage_m.py`, `stage_q.py`, `long_requests.py` | `python -m structural_break.pipeline.build_inputs costs / residual-targets / long-paths` |
| `scripts/quant_research/stage_*.py` and analysis scripts, `scripts/*.ps1` watchers, `probe_gemma.py` | removed (in the tag) |
| `scripts/agents/review_export_v3.py` | `scripts/agents/review_export.py` |
| `scripts/agents/fnspid_coverage.py` | `scripts/agents/ingest_fnspid.py` |
| — | `scripts/verify_book.py` (new: reproduction fingerprint of the adopted book) |

## Documents

| Old | Current |
|---|---|
| `docs/P6_QUANT_RESEARCH.md` | `docs/FORECASTING_AND_BOOK.md` |
| `docs/P6_AGENT_LAYER_V3.md` | `docs/AGENT_DESK.md` |
| `docs/P6_AGENT_LAYER.md` | `docs/archive/DEBATE_LAYER.md` |
| `docs/RESEARCH_V2_PROTOCOL.md`, `RESEARCH_V2_RUNBOOK.md` | `docs/RESEARCH_PROTOCOL.md`, `RESEARCH_RUNBOOK.md` |
| `docs/PLAN.md` (phases P0–P8), `docs/STATUS.md` | `docs/PLAN.md` (components); old versions in `docs/archive/PHASE_PLAN.md`, `PHASE_STATUS.md` |
| `docs/P6_BOOSTING.md`, `P6_DEVELOPMENT_RESULTS.md`, `P6_IMPROVEMENT_RESULTS.md`, `P6_SEC_FEATURES.md`, `PHASE5_RUNBOOK.md`, `proposals/P6_*.md` | `docs/archive/` (topic names) |

## Output folders (`outputs/`, git-ignored)

| Old | Current |
|---|---|
| `p6_quant/` (book inputs and scores) | `book/` |
| `p6_quant/stage_q/targets_pca_continuous.npy` | `book/residual_targets_pca.npy` |
| `p6_quant/stage_w/monthly_excess.parquet`, `audit_final.json` | `book/audit/` |
| `p6_desk/` | `agent_desk/` |
| `p6_boosting2/` | `model_b/` |
| `p6_improvement/walkforward/` | `walkforward/` |
| `p6_sec_features/` | `sec_timing/` |
| `p6_sec_explore2/` | `news_exit/` |
| `news_v1/` | `news_8k/` |
| `headline_v1/` | `headline_tone/` |
| every other earlier folder | `archive/` (kept locally, not deleted) |

## Names kept on purpose

These names look like phases or versions but are **identities** recorded inside frozen
artefacts, hashes or cached results. Renaming them would break verification or force
re-running work, so they stay:

- **Data generations:** `data/research_v2`, `source_v1`, `source_v2`, `source_v3`,
  `group-v2.zip`, and "research v2" as the name of the accepted research study.
- **Config files:** `configs/research_v2.yaml`, `research_v2_universe.yaml`,
  `phase6_execution.json`, `phase6_execution_sensitivities.json`, `phase6_analysis.json`.
  The research receipt and the Decision 42 freeze store these names with their hashes.
- **Version strings inside code and results:** for example `pairs-desk-prompts-v3.1`,
  `pairs-desk-monitor-v3.3`, `phase5-durable-attempt-budget-v1`,
  `pair-execution-policy-v2`, `p6-quant-v1`, plan and schema versions. Cached agent results,
  journals and manifests are keyed by them.
- **Test fixtures:** `tests/fixtures/phase1/` (fixture identities are fixed for reproducible
  tests).
- **The branch** `p6/agent-layer`.

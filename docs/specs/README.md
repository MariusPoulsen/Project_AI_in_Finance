# Coding-Agent Specification Index

These Markdown files are the canonical agent-facing project specifications. Read `../DECISIONS.md` first, then `../PLAN.md`, then the subsystem specification relevant to the current phase.

| File | Scope |
|---|---|
| `00_PROJECT_OVERVIEW.md` | Product scope, end-to-end architecture, UI, technical stack, governance, overall build sequence. |
| `01_DATA_ARCHITECTURE.md` | Sources, retrieval contracts, immutable raw data, curated Parquet, DuckDB, point-in-time joins, lineage. |
| `02_ECONOMETRIC_RELATIONSHIP_ENGINE.md` | Engle-Granger workflow, rolling estimation, spread/z-score, diagnostics, lifecycle, event trigger. |
| `03_SUPERVISED_ML_PIPELINE.md` | Event dataset, labels, Model A/Model B features, XGBoost, calibration, SHAP, inference and ML evaluation. |
| `04_MULTI_AGENT_PIPELINE.md` | SEC evidence retrieval, catalyst extraction, adversarial agents, validation and deterministic controller. |
| `05_BACKTESTING_EVALUATION.md` | Five-stage ladder, execution simulator, costs, predictive/economic/agent metrics, robustness and freeze rules. |
| `06_SOFTWARE_ENGINEERING_ARCHITECTURE.md` | Repository/runtime boundaries, storage access, config, jobs, services, Streamlit, testing, CI and deployment. |

The PDFs in `docs/PDFs/` may be retained for human reading but are not required for coding-agent implementation.

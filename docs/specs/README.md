# Component specification index

Read [current decisions](../DECISIONS.md), [the plan](../PLAN.md) and the relevant
component contract. The [v2 protocol](../RESEARCH_V2_PROTOCOL.md) governs the
expanded study where older specification defaults differ. These files remain
stable reference contracts; their presence does not imply every subsystem is implemented.

| Specification | Scope |
| --- | --- |
| [Project overview](00_PROJECT_OVERVIEW.md) | Product, architecture, UI, governance and build scope |
| [Data architecture](01_DATA_ARCHITECTURE.md) | Retrieval, provenance, Parquet/DuckDB and point-in-time joins |
| [Relationship engine](02_ECONOMETRIC_RELATIONSHIP_ENGINE.md) | Estimation, diagnostics, lifecycle and divergence signals |
| [Supervised ML](03_SUPERVISED_ML_PIPELINE.md) | Event labels, A/B features, calibration, explanations and inference |
| [Backtesting/evaluation](05_BACKTESTING_EVALUATION.md) | Shared simulator, ladder, robustness and final-test governance |
| [Software architecture](06_SOFTWARE_ENGINEERING_ARCHITECTURE.md) | Runtime boundaries, configuration, storage, services and testing |

`04_MULTI_AGENT_PIPELINE.md` is not present. Its original
[multi-agent PDF](../archive/pdfs/AI_Structural_Break_Detector_Multi_Agent_Pipeline_FINAL.pdf)
is retained; recover and review the Markdown contract before implementing that
subsystem. Do not treat the missing file as an existing specification.

All seven original source PDFs are in [the archive](../archive/README.md#source-pdfs).
Use the existing Markdown equivalents during ordinary implementation.

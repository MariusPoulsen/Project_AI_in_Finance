# Presentation layer

Phase 3 provides Scanner and Pair Detail in `streamlit_app.py`. They call the typed
read-only `ResearchQueryService`, displaying frozen relationship history and any
published Model A predictions. App callbacks do not run analytical batch jobs.

```shell
uv run --frozen --extra app streamlit run app/streamlit_app.py
```

Set `SB_WORKSPACE_ROOT` to select another published workspace. Missing outputs have
explicit empty states; the app does not invent data or model probabilities. Phase 3
limits the research date selector to development history through 2023. Full pages,
event evidence, agents and strategy evaluation are delivered in their owning phases.
See [the ML runbook](../docs/ML_RUNBOOK.md) for fixture/research builds and limitations.


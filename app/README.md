# Read-only research app

`streamlit_app.py` displays accepted research-v2 model comparisons and stored
event scores through `PrimaryResearchService`. It exposes the primary
20-session comparison, predeclared 10/30-session sensitivities, source coverage,
uncertainty and descriptive subsets. Development dates end in 2023; final-test
outcomes remain locked.

```shell
uv run --frozen --extra nlp streamlit run app/streamlit_app.py
```

The default workspace is `data/research_v2`. Set `SB_WORKSPACE_ROOT` in the
ignored `.env` or process environment to select a restored workspace.

Results appear only after a complete, independently verified generation is
explicitly published. Missing outputs show a pending state; failed verification
shows an error. Browsing does not download sources, call providers, fit models
or write analytical results. The current actual study is still awaiting feature
completion, model fitting and acceptance: see [status](../docs/STATUS.md) and
the [publication runbook](../docs/RESEARCH_RUNBOOK.md).

`reference_streamlit_app.py` preserves the original Scanner and Pair Detail
interface for its recorded workspace. Reproduction instructions live in the
[reference archive](../docs/archive/README.md).

# Research workspace presentation

The frontend branch presents saved development outputs through 2023. Browsing
does not fit, download, call an LLM, write analytical results or unlock a final
test. Claude's development output/data directories remain read-only.

Run `uv run streamlit run app/research_app.py` from this checkout.

## Saved presentation

`demo/book/presentation.json` binds the summary, two daily NAV series, study
catalogue and saved confirmation ROC/calibration figures by SHA-256.
`SB_RESEARCH_SUMMARY` can point at another explicitly exported presentation.
Changed bytes invalidate the resource cache and fail closed.

To update from already saved development desk results:

```powershell
uv run python scripts/export_research_diagnostics.py --outputs-root PATH_TO_OUTPUTS
uv run python scripts/export_research_presentation.py
```

The first command reads `agent_desk/evaluation_holdout.json`, exports only the
2011–2017 and 2018–2023 matched regional metrics, and never invokes fitting.
Without that source it records only rounded published 2011–2017 figures and
keeps missing periods/counts explicit. Source hashes accompany exact exports.
It writes presentation files in this checkout, never source outputs.

Current per-event scores/SHAP and the additional books' daily NAV/cash-growth
series are not available in the committed source export. They remain absent;
there is no reconstruction or substitution of an older model.

## Page map

- Forecasting: four matched population forecasters, two deterministic baselines,
  Full matched-region comparison, saved ROC/calibration, rules and model metadata.
- Portfolio: four current books; R0 monitor ablation curves; frozen policy ladder,
  threshold/cost sensitivities, bootstrap and withheld-trade diagnostics.
- Event explorer and Pair detail: fixed-20 registry inputs, outcomes, pair history
  and point-in-time SEC evidence. Superseded fitted scores are excluded.
- Evidence and diagnostics: source coverage, counts/distributions, model catalogue,
  agent coverage, selection diagnostics and byte identities.
- Rules and definitions: forecast/book rules, chronology, model families and inputs,
  metric definitions. No interactive 10/20/30-session selector.

The frozen policy benchmark uses 2022–2023, next-open entry and a fixed 20-session
cap. Its older model A/B selections are explicitly identified and never mixed
with annual walk-forward forecasts or current book statistics.

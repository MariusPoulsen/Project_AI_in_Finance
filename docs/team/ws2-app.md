# WS2 — Full Streamlit research application (PLAN P7, deployment part of P8)

Owner: group member (WS2). Branch: `ws2/research-app`. Status: draft PR.

## Goal

Turn the minimal read-only app into the full research application described in
PLAN P7, and make a frozen demo deployable to Streamlit Community Cloud (P8
"deployment config"), without changing any scientific result.

## Design

The change is additive. `app/streamlit_app.py` (the verified two-page view) is
unchanged; the full app is a new entry point, `app/research_app.py`.

```
accepted workspace ──► app_bundle.build (read-only, verified) ──► AppBundle ──► services.research_app_v2 ──► app_ui pages
P6 experiment dirs ──┘          │                                  ▲
                                └──► app_bundle.io.write ──► frozen bundle dir ──┘  (Streamlit Cloud)
```

- `structural_break.app_bundle` reads only accepted generations through the
  existing `load_primary` / `registered_manifest` / `checked_file` chain and
  verified P6 experiment manifests. It never trains, downloads, calls an LLM or
  writes into the workspace. It computes descriptive presentation tables only:
  ROC/PR/reliability curves on stored predictions, exact additive feature
  contributions of the saved native models (logistic: coefficient × standardised
  value; XGBoost: native TreeSHAP), and compact strategy tables.
- A *bundle* is a small checksummed directory (parquet + JSON + manifest).
  `structural-break-app export` writes one from the accepted workspace; the app
  reads it back and re-verifies every checksum. The full workspace can also be
  read directly, in memory, without exporting.
- `services/research_app_v2.py` holds all filtering/aggregation; page code in
  `structural_break.app_ui` only lays out widgets and charts.
- A clearly bannered `SYNTHETIC PREVIEW` bundle (invented numbers) lets the UI
  and the smoke tests run without the snapshot. It can never be mistaken for a
  research result: every page shows a red banner and the bundle manifest says
  `synthetic: true`.

## Pages against the P7 checklist

| P7 item | Page / status |
|---|---|
| Scanner | **Scanner**: development events with calibrated A/B probabilities, filters, row → Pair Detail |
| Pair Detail with spread/relationship diagnostics | **Pair Detail**: normalised prices, z-score with ±2 / ±0.5 / ±3 bands, ACTIVE shading, event markers, monthly relationship table |
| A/B probability context and SHAP explanations | Pair Detail + Model Lab: per-event contribution waterfall; global importance |
| Evidence timeline / cited chunks | Partial: SEC *feature* evidence per event (recency, tone, catalyst, UNKNOWN). Filing text is not in the group snapshot, so chunks cannot be shown |
| Agent cases / controller | Shown as **NOT RUN** (Decision 40); no invented agent output |
| Strategy Lab | **Strategy Lab**: four-rung ladder, NAV/drawdown, threshold and cost/borrow sensitivity, paired bootstrap, not-selected (rejected) trade economics |
| Model & Data Monitor | **Data & Model Monitor**: versions, cohorts, source coverage/UNKNOWN by year, feature drift by partition, 30-bundle inventory |
| Methodology / Model Card | **Methodology**: target, chronology, features, models, evaluation, limitations, intended use |
| Version-keyed caching | `st.cache_resource` keyed by bundle/primary identity |
| Empty / loading / error states | Shared helpers; pending, failed verification and empty selections are explicit |
| No mutation | Bundle reads only; export writes only to a new directory outside the workspace |

## Data used / exploratory status

Only accepted outputs already published in the snapshot and the official P6
experiment directories. No new model, threshold, grid or strategy rule is
evaluated, so nothing here is a new post-hoc result. The 2024–2025 final test
stays locked: export refuses any row after `development_end`.

## Deployment

`structural-break-app export --workspace-root data/team --experiment
.acceptance/p6-official/... --output demo/app_bundle --showcase-pairs 40`
then point Streamlit Community Cloud at `app/research_app.py`. Committing the
small demo bundle is a decision for the repository owner (it is generated
data, ~10 MB); the alternative is a separate demo branch.

## Validation

- `tests/unit/test_app_bundle.py`: explanations reproduce each saved model's
  margin; curves use assessment rows only; UNKNOWN catalysts stay UNKNOWN; bundle
  round trip, tamper, final-test and overwrite refusals; the workspace export
  writes nothing into the workspace; experiments from another generation or with
  a changed artifact are refused.
- `tests/unit/test_research_application_app.py`: every page renders at two
  horizons from the synthetic bundle; pending and failed states show no results;
  empty filters show an empty state.
- Launcher: `research-app` and `app-bundle` commands (`test_team_launcher.py`).
- Visual review of every page and tab in a headless browser at 1440 px and
  390 px widths (synthetic bundle).
- **Still required:** export from the real `group-v2.zip` + official P6
  experiments, open the app on it, and check the numbers against
  `P6_DEVELOPMENT_RESULTS.md` before deploying.

## Log

- 2026-10-26: plan written; baseline suite green (1,839 tests).
- 2026-10-26: app bundle package, service, seven pages, synthetic preview,
  launcher commands, Streamlit Cloud notes and tests. Ruff, format and strict
  mypy clean.

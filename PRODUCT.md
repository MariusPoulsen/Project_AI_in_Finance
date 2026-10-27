# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Project teammates and academic assessors need visible comparisons, diagnostics
and drill-downs. Model-specific conclusions and interpretation belong in the
report. The app presents measurements and fixed forecasting/book rules. Updated
by the owner on 2026-10-27.

## Product Purpose

Present two distinct research goals: forecasting mean reversion and constructing
a realistic trading book. Help a reader compare the retained models, understand
what the evidence supports, and investigate an individual pair or result.

## Operating Context

This is the FINS5557 AI Structural-Break Detector research application. It runs
on Streamlit Community Cloud and locally from the same Python modular monolith.
The owner maintains the academic report. The application presents research;
it does not execute orders.

## Capabilities and Constraints

- Preserve Streamlit and typed, read-only services; no live fitting, downloads,
  provider calls or analytical writes when browsing.
- Goal 1 compares Model A, original fixed-XGBoost Model B/R0, the pre-registered
  bagged B+rule+ou, the post-hoc best-observed B+rule+ou+track, and the Full model
  where comparable published data actually exists.
- Baseline 0 and Baseline 1 remain plan-ladder trading benchmarks, not invented
  probabilistic forecasts.
- Goal 2 presents the adopted R0-selected book, its no-monitor comparator, and
  clearly distinguished plan-ladder and reported model-selection comparisons.
- Retain event scanning, pair diagnostics, source evidence, agent explanations,
  coverage, methodology, and export of displayed results as the underlying data
  allows. Never imply a legacy event score belongs to a newer model.
- Keep selection (2010–2017), development confirmation (2018–2023), the earlier
  accepted 2022–2023 study, and final-test results in their own named cohorts.
- Final-test publication follows the owner's exact freeze and unlock process.
  Missing or locked results are explicit, never synthesized from documentation.
- Preserve registered artifacts, all scientific definitions, and Claude's
  concurrent final-test work on deploy. Frontend work has its own branch/worktree.

## Evidence on Hand

Canonical sources are docs/DECISIONS.md, docs/PLAN.md,
docs/FORECASTING_AND_BOOK.md, docs/AGENT_DESK.md and docs/FINAL_TEST_RUNBOOK.md.
The deploy branch carries the checksummed demo/app_bundle presentation export
and demo/book summary and daily curves. The former represents the earlier
accepted study, not the full current walk-forward model set. The original
application checklist is docs/archive/PHASE_PLAN.md, P7.

## Product Principles

1. A better forecast and a better trading book answer different questions.
2. Lead with charts, comparison tables and diagnostics; keep conclusions in the report.
3. Show model role, cohort, period and provenance wherever comparisons need them.
4. Expose diagnostic measurements, UNKNOWN evidence and missing artifacts honestly.
5. Make a useful investigation possible without learning the repository layout.

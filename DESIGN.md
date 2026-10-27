# Structural Break research workspace

The owner selected the second displayed revised concept, Signal Catalogue, on
2026-10-27: a dark background, with further UX refinement and purposeful motion.
The refined comparison image is the implementation reference. Code-first remains
the agreed path. Mode: Operate, for teammates and assessors reading research.

Use matte charcoal #171719, surface #1D1E22, white #F2F3F5, readable secondary
text #ABB1BD and one comparison accent #58A6FF. Quiet one-pixel rules divide open
planes; avoid grids of metric cards. IBM Plex Sans is the existing product face;
IBM Plex Sans Condensed gives app-sized headings a distinct, readable voice.
Tabular numerals align measurements. No invented chart observations or intervals.

Navigation follows the reader's questions: comparisons, forecasting, portfolio,
investigation, evidence. Current walk-forward results lead each goal. The frozen policy benchmark is
inside Portfolio with its distinct cohort and execution assumptions. Metric and period selection apply to the whole
comparison. Model role accompanies the name; post-hoc stays post-hoc. Reading a
summary must work even when the earlier bundle is absent. Missing data has an
explicit explanation rather than an invented result or an empty plot.

The signature is a shared measurement axis beside model records, followed by
diagnostics and fixed rule tables. Interpretive conclusions stay in the report;
model names and roles stay in comparisons, legends and the registry. The portfolio page
uses the same period for its statistics and curves. Source identity and the
snapshot's final-test lock are always accessible.

## Motion thesis

Motion serves active selection and disclosure. The focal interaction is selecting
a model record: its rule, text and control feedback change together. Buttons,
navigation and table rows acknowledge hover/focus in 140–180 ms. Disclosure
chevrons use the native Streamlit interaction. No chart values count up, no
autoplay, no scrolling choreography or entrance delays. Reduced-motion users
receive immediate state changes; content is visible on the first frame. Add no
JavaScript or motion dependency. This budget fits Streamlit's rerun model.

## Responsive and accessible behavior

Use Streamlit's native collapsible sidebar, keyboard controls and stacked columns
on small screens. Keep tables bounded with their own scroll where necessary;
important labels also appear as plain text. Preserve native focus and tooltips,
add a visible accent focus outline, and use color together with labels/markers.
Minimum body size 14 px; page title about 30 px. One theme across every page,
including policy-benchmark charts, empty states and diagnostics.

## Consolidated comparison workspace

Use full-width overview tables so metric columns remain visible on laptops.
Forecasting lists seven models/policies beside the shared axis for the four
probabilistic population models. Policy and Regional cells are explicit scope
labels, never invented scores. Full has a matched-region disclosure; baseline
outcomes and saved ROC/reliability figures are adjacent diagnostics. Portfolio
compares four saved books, with daily curves shown only where exported.
Monitoring belongs to Evidence; model cards and fixed methodology belong to
Rules. No historical-study navigation or obsolete horizon selector.

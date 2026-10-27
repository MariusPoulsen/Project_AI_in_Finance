# Research workspace design QA — 2026-10-27

final result: passed

## Visual truth and comparison setup

The owner selected the second displayed revised image (Signal Catalogue), a dark
research workspace, and asked for improved UX and purposeful motion. A single
refinement was generated before the code-first implementation.

- Source: `.impeccable/mocks/decision/signal-catalogue-refined.png`, 1487 × 1058 px
  (the generator returned this size for the requested 1440 × 1024 concept).
- Implementation: `.design/qa/forecast-desktop-final.png`, 1487 × 1058 px.
- CSS viewport: 1487 × 1058, screenshot density 1. No density normalization needed.
- State: Forecasting, 2018–2023 confirmation, ROC AUC, preregistered OU model selected.
- Both source and implementation images were opened together for comparison.
- Focused model-record evidence: `.design/qa/forecast-records-final.png`; checked
  values, roles, selected row, wrapping and numeric alignment against the source.
- Additional evidence: `.design/qa/portfolio-desktop-final.png`,
  `.design/qa/forecast-mobile-final.png`, `.design/qa/mobile-navigation-final.png`.
  Mobile viewport and pixels: 390 × 844, density 1.

Generated concepts and browser captures are ignored local working artifacts.
The committed code and `DESIGN.md` are the durable deliverables.

## Findings and bounded comparison history

The first desktop/mobile inspection used 1440 × 1024 / 390 × 844 captures
(`forecast-desktop-before.png` and `forecast-mobile-before.png`).

- [P2, resolved] Project identity appeared below an overlong navigation list.
  The shell now renders the identity first, keeps both research goals prominent,
  and groups older model/protocol tools in an explicit disclosure. The final
  desktop and mobile-drawer screenshots confirm the change.
- [P2, resolved] Default Markdown table styling added vertical boxed cells.
  The model records now use quiet horizontal rules and one selected-row rule,
  matching the chosen open-plane direction. Focused capture confirms alignment.

One batched fix pass and one confirmation pass. No unresolved actionable
P0/P1/P2 findings in the tested views.

## Required fidelity surfaces

- **Typography:** existing sourced IBM Plex Sans and Condensed are intentional
  app-scale adaptations of the generated serif mock. Computed title is 32 px
  on desktop; body/captions use readable product sizes. No cropped model names;
  roles remain visible under names and measurements use tabular numerals.
- **Layout:** dark chart plane beside aligned model records. Real period/metric
  controls occupy more space than the mock's static labels. Model explanation
  and portfolio bridge continue below the evidence, with both goals always in
  navigation. This is an intentional functional code-first adaptation, not a
  pixel clone. Mobile stacks the columns and uses the native navigation drawer.
- **Colors:** charcoal #171719, blue #58A6FF, white #F2F3F5, secondary #ABB1BD.
  Computed base surface matches. Calculated text contrast against the base is
  16.12:1 for white, 8.32:1 for secondary text and 7.09:1 for the blue accent.
  Selection also uses shape, role labels and a row rule, not color alone.
- **Images and charts:** the source contains no photographic or custom raster
  asset to reproduce. Scientific point plots and NAV traces use verified data;
  native Streamlit/Plotly iconography is retained. No invented ROC curves,
  confidence whiskers, illustrations or decorative asset substitutes.
- **Copy:** the four retained model names, preregistered/post-hoc distinction,
  cohorts, date scopes and metrics match the saved export. Current Full-model
  subset and older accepted-study results are not conflated. Development reuse,
  missing diagnostics and the snapshot's final-test lock are explicit.

## Functional and accessibility evidence

- Browser-tested overview/forecast/portfolio navigation, metric switching,
  post-hoc model inspection, the mobile drawer and portfolio NAV/drawdown control.
- Streamlit tests cover all five current views, model selection, cohort count,
  period-specific book statistics and the missing-current-export state. Legacy
  views retain their existing smoke coverage and scoped horizon control.
- Integrity tests cover changed bytes invalidating cache, relabelled model rows,
  missing measurements and 2024 rows rejected even after rehashing.
- Both desktop and mobile document widths equal their viewports; tables have
  bounded internal scrolling. Controls have native semantics and labels;
  focus feedback is visible and captions/role labels retain strong contrast.
- Motion is limited to 160 ms state/color feedback and native disclosures. No
  autoplay or hidden entrance state; reduced-motion CSS removes transitions and
  press travel. OS preference switching was not emulated in this browser.
- Fresh final-preview browser console: no error entries. Earlier preview-tab
  connection errors came from the intentional local server restart; the fresh
  session and server log show no application error.
- Impeccable detector: no findings. Ruff check and format pass; mypy passes for
  the app and new service/export script; 33 focused tests pass.
- This is not a complete assistive-technology audit. No performance or final-test
  result has been generated by browsing or by these checks.

## Follow-up polish and data availability

- [P3] A future reviewed export can supply current-model calibration/ROC arrays,
  per-event predictions, SHAP and matched uncertainty. Until then the interface
  explicitly reports them unavailable; it must not borrow older scores.
- Final-test publication requires its own authorized export/schema update. The
  development manifest deliberately accepts only the locked snapshot state.

## Implementation checklist

- [x] Two distinct research goals, matched periods and explicit model roles.
- [x] Dark theme, compact navigation, responsive layout and purposeful motion.
- [x] Independent data availability, byte identities and fail-closed states.
- [x] Working controls, saved-result exports, diagnostics and reference views.
- [x] Bounded visual comparison and relevant local validation.

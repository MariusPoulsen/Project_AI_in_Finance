# Research application redesign

Owner request and brief confirmed 2026-10-27. Branch:
`frontend/research-workspace`, based on deploy commit
`1ee139e`. Claude's final-test work remains on `deploy`; this worktree does not
change its code, data, freeze or unlock record.

## Purpose

Serve teammates and assessors with findings, explanations and drill-downs;
provide diagnostic depth on demand. Retain Streamlit and the modular Python
monolith. Code-first implementation was explicitly selected by the owner.

## Current product truth

- Goal 1 is mean-reversion forecasting. Retain A, R0, bagged B+rule+ou,
  bagged B+rule+ou+track and the Full model, with their actual roles and cohorts.
- Goal 2 is the realistic trading book. R0 selects the adopted book; the
  pre-registered Goal 1 forecaster is not its selector. The agent position
  monitor contributes exits; entry agents did not improve forecasting.
- The earlier accepted research and its plan-ladder backtests remain valid
  references. They are not the newer walk-forward programme's results.
- Decisions 110d, 113–118 and the role-name cleanup supersede older app copy.
  Keep artifact-generation identities that NAMES.md deliberately preserves.
- Final-test preparation is not an unlock. Publish no 2024–2025 metric until
  an explicitly authorized, verified presentation export supplies it.

## Live-app audit

Screenshots captured and inspected in this session from
https://aiinfinance-mkt.streamlit.app/ at a 1280 × 720 viewport. Local evidence:
`.design/research-app-audit/` (generated, not source assets).

| Step | Screen | Health and evidence |
| --- | --- | --- |
| 1 | Overview | Loads, but leads with a long A/B description and example spread; the current two goals and retained models are absent from the first screen. |
| 2 | Model Lab | Loads, but the main comparison is the earlier ten-bundle study. Six horizontally overflowing tabs, tiny chart labels and legacy primary/secondary terminology obscure the current programme. |
| 3 | Adopted book | Current book curves and statistics load. Forecast results are buried below book details; headline metrics mix periods, making an at-a-glance comparison difficult. |
| 4 | Strategy Lab | Loads the earlier 2022–2023 execution-policy ladder, including the legitimately unrun old Full System rung. This needs a clear reference label so it cannot be confused with the evaluated current agent desk. |

Visible accessibility risks: small chart annotations, muted text contrast, sidebar
scrolling and a horizontally overflowing tab strip. No claim of complete
accessibility testing is made; mobile, keyboard and screen-reader interaction
will be checked on the implemented app.

## Data and service gaps confirmed from code

- `demo/app_bundle` and `ResearchApplicationService` describe the earlier accepted
  study. Scanner, attributions, curves and model identities must retain that
  context until a current-model export supplies their replacements.
- `demo/book/summary.json` includes four current headline forecasters and the
  adopted/no-monitor book summaries, but no Full-model population forecast
  row, per-event new-model predictions, matched uncertainty or current-model
  calibration curves. Do not create these from a rounded documentation table.
- The current book summary reads JSON/Parquet without an integrity manifest and
  resolves its path from cwd. Add explicit, versioned presentation inputs and
  validation rather than relying on whichever directory happens to be open.
- The global 10/20/30 horizon control belongs to the earlier study. The newer
  walk-forward programme has a 20-session forecast target and a different
  adaptive trading time stop; these must not share a misleading control.
- Book metrics distinguish return with cash from excess return. Sharpe is excess
  of cash. Drawdown, NAV and CAGR labels must use their actual return basis.
- Preserve independent availability: a missing legacy bundle should not make
  verified current forecast/book summaries inaccessible.

## Proposed information architecture

1. **Research overview:** two equal destinations, one finding and one honest
   limitation for each; dates, population and final-test state visible.
2. **Forecasting:** retained model roster, common period/metric controls, role
   labels (pre-registered, post-hoc, reference), matched comparison table,
   calibration/ROC/PR and uncertainty only where actually available; diagnostic
   views disclose unavailable exports.
3. **Portfolio:** adopted book versus no-monitor comparator, aligned NAV and
   drawdown, period-consistent return/risk/cost metrics, design and execution
   assumptions; historical plan ladder in a separate reference view.
4. **Investigate:** Scanner and Pair Detail, with the source model/cohort explicit,
   pair history, event explanations, source timeline and cached agent reports.
5. **Evidence and methodology:** data/model health, UNKNOWN and abstention
   denominators, provenance, study design and limitations.

Use goal-specific controls and short explanations. Keep selected period/model
stable when opening detail; make filters, exports and chart legends explicit.
Missing, invalid, synthetic, reference and locked data have distinct states.

## Visual direction exploration

Impeccable Operate mode; code-first. Grounded systems considered in order:
1. Scientific journal result tables: conclusions, aligned numbers and notes.
2. Exchange auction ledger: precise ranked rows and explainable trade states.
3. Clinical-trial comparison: matched populations and parallel evidence panels.
4. Research atlas: indexed sections, shared chart scales and linked detail.
5. Lab notebook: a concise finding followed by reproducible evidence.
6. Air-traffic strips: priority rows, clear state and investigation handoffs.
7. Competition results book: common metric, period and model-role columns.

The concept seed assigned research atlas (4); seed `4be07542`. Present it as a
committed direction, with scientific result tables as the grounded alternate.

Catalog challengers were judged on audience identification and product clarity:
- Variable-font specimen: declined; one shared control remaps the comparison,
  but a giant specimen subject obscures the two research tasks. Keep disciplined
  parameter alignment, not typographic spectacle.
- Metro tiles: declined; cropped headings, panorama navigation and saturated
  tiles weaken both assessor comprehension and comparative reading. Keep the
  clarity of a selected state, not its colors or motion.
- Star atlas: declined; a spatial star field adds navigation work without a
  scientifically meaningful coordinate system. Keep consistent plotted scales.
- Botanical folio: declined; literal growth-stage states misrepresent model
  roles. Keep parallel, equally weighted evidence and stable ordering.
- Transit map: declined; a route network makes pipeline structure compete with
  the actual forecast and portfolio findings. Keep persistent wayfinding.
- Departure board: competitive on product clarity; aligned, selectable model
  rows translate well. Present a restrained comparison-desk alternate, with
  less narrative depth as its honest risk.

Raises to the research atlas: a shared period/metric control (specimen), explicit
selected state (metro), fixed chart scales (atlas), matched evidence layout
(folio), persistent location (transit). These are interaction disciplines, not
borrowed decorative motifs.

Three independent concept images will ground the visual choice. They illustrate
layout, not a working application or computed new research results. The selected
direction will then be implemented in real Streamlit widgets and Plotly charts.

The three concepts were generated and displayed independently in the order above.
They are saved with their exact prompts under `.impeccable/mocks/decision/`.
Generated chart shapes are illustrative, not exported observations; implementation
must draw charts from verified data rather than copy those plotted shapes.
The owner's direction selection is pending. No application code has changed.

### Revised directions after owner feedback

The owner preferred the editorial and comparison concepts (displayed 2 and 3),
but found them too generic. They requested taste-skill as additional guidance.
Installed `taste-skill@taste-skill` version 2.1.5 from Leonxlnx/taste-skill and
read its app-screen workflow. The existing Streamlit stack and code-first path
remain the implementation constraints. Generated tool sessions stay ignored.

Taste's analytics/light achromatic-ledger direction (seed 1801923934) supplies
readable comparison rows and restrained measurement typography; its markets/dark
data-terminal direction (seed 1332665716) supplies a quiet dark plot surface.
These are supporting constraints, not a substitute for a product-specific layout.

The Impeccable bolder reroll retains seed `4be07542` and suspends the original
assigned direction. All six new challengers were assessed for product clarity:

- Cassette j-card leads as **Duplex Record**: two research halves joined by a
  common spine, with explicit forecast and portfolio identities. The literal
  cassette motif is excluded. Risk: keep the two halves readable on narrow screens.
- Saville catalogue becomes **Signal Catalogue**: a dominant scientific plot and
  aligned, fully named model records. No cryptic catalogue codes or album props.
  Risk: dark plotting and closely spaced curves require strong contrast.
- Darkroom exposure sheets become **Exposure Desk**: shared measurement axes,
  point estimates and a side-by-side explanation of target and book rules.
  Risk: avoid dense instrument-like diagrams that misrepresent the research.
- Timetable slide rack declined: raked text and lateral scanning reduce readability.
- Convention thumbnail catalogue declined: tiny dense labels obstruct assessor use.
- Airport yellow wayfinding declined: saturated signage overwhelms the evidence.

The three revised images were generated and displayed independently in the order
Duplex Record, Signal Catalogue, Exposure Desk. Each exact prompt and its local
PNG are saved under `.impeccable/mocks/decision/`; this folder is not committed.
No direction has yet been approved. No application code has changed.

Generated drawings are layout references, not analytical evidence. Before coding,
remove invented confidence whiskers and Gaussian drawings in Duplex Record;
do not label the post-hoc ROC curve preregistered in Signal Catalogue; and omit
Exposure Desk's misleading z-axis placements of time/news exits. Plot exact
verified observations and point estimates only, and keep titles at app scale.
Unavailable curve/uncertainty exports remain explicitly unavailable.

## Implementation and acceptance after direction selection

- Isolate current presentation contracts/services from the earlier bundle;
  version and validate the compact export, model roles, cohorts and periods.
- Replace the visual shell and navigation; implement both primary comparison
  paths before adapting investigation and trust pages.
- Preserve underlying research, prediction, execution and freeze definitions.
- Add meaningful service tests for cohort comparability, unavailable results,
  changed hashes, UNKNOWN and locked periods. Add Streamlit smoke tests for
  both goals, filters, diagnostics and failure states.
- Run relevant Ruff, mypy and pytest checks. Verify desktop and narrow-screen
  flows in one bounded visual pass, fix defects together, then confirm once.
- Supply local preview and a draft PR to deploy. Publishing to the existing
  public app is a separate final step after the concrete implementation.

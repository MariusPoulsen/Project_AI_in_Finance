# Agent brief: joining the AI Structural-Break Detector project

Paste or attach this file in your coding agent's first message (Claude Code,
Codex, Cursor, etc.), followed by one line saying which work stream you own, for
example: `I own work stream 1 (gradient boosting / tuning / CV).`

---

## 0. Who you are working for and what already exists

You are helping a student in a FINS5557 group project. The repository is
`https://github.com/MariusPoulsen/Project_AI_in_Finance`. Marius (repository owner)
built the research pipeline and is away for about a week. He holds the large SEC
filing archive locally; you do **not** have it and do not need it.

The project predicts whether a pairs-trading divergence (|z| >= 2) between two
business-peer stocks reverts (|z| <= 0.5) before an adverse move (|z| = 3) within
20 trading sessions (10 and 30 are sensitivities). Two matched models are compared:

- **Model A**: quantitative features only (spread state, relationship quality,
  market context, security state, liquidity).
- **Model B**: Model A's columns plus SEC-filing features. Ablations: `B_metadata`
  (8-K/item recency), `B_tone` (FinBERT tone), `B_catalyst` (Gemma-extracted
  catalysts for a frozen 500-event schedule), `B_both` (all). **Primary result:
  calibrated logistic `B_both` versus `A` at 20 sessions.**
- Each horizon has 10 saved model bundles: {logistic, XGBoost} x {A, B_metadata,
  B_tone, B_catalyst, B_both}. Three horizons = 30 bundles.

Research v2 data: 250 issuers, 40 business groups, 736 fixed pairs, 37,421
development events, 2004-2023.

| Period | Use |
|---|---|
| 2004-2005 | formation warm-up only |
| 2006-2019 | fit (forward tuning folds 2018 and 2019, logistic C in {0.01, 0.1, 1}, small fixed XGBoost grid, selected by mean forward Brier) |
| 2020-2021 | calibration (sigmoid) |
| 2022-2023 | assessment (already observed; 8 calendar-quarter blocks, paired block bootstrap) |
| 2024-2025 | **final test: LOCKED. Not in the snapshot. Never fetch or construct it.** |

You work from a **portable snapshot** (`group-v2.zip`) that contains all accepted
outputs: the 30 model bundles and calibrators, per-horizon model-input feature
tables, predictions, reports, curated prices and frozen pair-relationship history.
It excludes SEC filing bodies, text checkpoints and raw downloads.

**Status check first.** Research v2 was being re-run to acceptance when the group
started (see `docs/DECISIONS.md` section 33). Check which data you have:

- `group-v2.zip`: the official, accepted snapshot. Use it with `scripts/team.py`
  (below), the app and `team.py predict/check`.
- `group-v2-provisional.zip`: an earlier, **unaccepted** export of the same trained
  models, for exploratory work only. It does not work with `team.py` or the app;
  load it with pandas/joblib as described in its `README_PROVISIONAL.md`. Switch to
  `group-v2.zip` as soon as it is available.

If `main` does not yet contain `scripts/team.py`, the accepted release has not been
merged; use the `research-v2` branch until it is.

## 1. First-time setup (do this before anything else)

1. Clone and enter the repo:
   `git clone https://github.com/MariusPoulsen/Project_AI_in_Finance.git`
2. Get `group-v2.zip`, its `.sha256` file, and the checksum from the group's
   shared folder or chat. Do not invent the checksum. (Only the provisional pack
   available? Skip to its README and come back here when the official one arrives.)
3. Run (Python 3 on PATH is enough; the launcher installs `uv` and Python 3.11):
   `python scripts/team.py setup --snapshot PATH/TO/group-v2.zip --sha256 <CHECKSUM>`
4. Verify: `python scripts/team.py check`, then
   `python scripts/team.py predict --pair KO__PEP` (reproduces saved predictions to
   1e-12), then `python scripts/team.py app` (Streamlit).
5. If any step fails, stop and report the exact error to the human. Do not
   "fix" the snapshot, rewrite manifests, or re-download data.

Full instructions: `docs/GROUP_QUICKSTART.md`.

## 2. Read these, in this order, and only these at first

1. `AGENTS.md`: binding rules for every agent in this repo.
2. `docs/DECISIONS.md`: canonical decisions. These override any other document.
3. `docs/RESEARCH_PROTOCOL.md`: the scientific protocol.
4. `docs/GROUP_QUICKSTART.md`: snapshot workflow.
5. Your work stream's specification (section 5 below).

Then inspect the code you will touch before proposing changes.

## 3. Non-negotiable rules

These protect the validity of the study. If a task seems to need breaking one,
stop and ask the human.

1. **Final test stays locked.** No 2024-2025 prices, labels, outcomes or metrics.
   Do not download new market or SEC data.
2. **The 2022-2023 assessment has already been looked at.** Any new model, grid,
   calibration or strategy rule you evaluate on 2022-2023 is *post-hoc
   exploratory*, and must be labelled that way in outputs and notes. Make choices
   using the fit/tuning folds (2018-2019) and calibration window (2020-2021) only.
   Write the plan down (config + short note) **before** computing assessment
   numbers, then report every variant you ran, not just the best.
3. **A and B stay matched.** Same rows, targets, folds, purging, tuning budget,
   preprocessing and calibration. Never drop rows because SEC evidence is missing.
4. **UNKNOWN is not zero.** Missing evidence/coverage stays explicit; it is not
   "no catalyst" or "neutral tone".
5. **Point-in-time.** A predictor may only use information available at the
   event's close (previous-session VIX, SEC filings accepted before the cutoff).
   Future data is only allowed for constructing labels.
6. **Purge across time boundaries.** Any new CV scheme must purge the full target
   horizon at every fold/partition boundary (an event's label window must not
   straddle train and validation).
7. **Do not modify the imported workspace** (`data/...` from the snapshot) or the
   canonical published artifacts. Put everything you produce under
   `outputs/<work-stream>/...`. `data/`, `outputs/`, `.team/`, `.env` and
   credentials never go into Git.
8. **No canonical re-publication.** You cannot mint new accepted generations
   (that needs Marius's SEC archive and full verification). Your results are
   exploratory proposals; if one should become canonical, write it up as a
   proposal for Marius.
9. **Forecast improvement is not profitability.** Do not claim trading profits
   from AUC/Brier, and do not claim Model B is better unless the paired interval
   says so.
10. **The Streamlit app is read-only.** Logic belongs in `src/structural_break/...`
    services, never in page code. Browsing must not download, fit or write.
11. **Do not write the academic report or presentation** unless your human
    explicitly asks. You may produce figures, tables and technical notes.

## 4. Git workflow

- Branch from up-to-date `main`: `git switch -c <stream>/<short-topic>`.
- Small, focused commits; open a **draft PR** early; describe what changed, how it
  was validated, and whether any result is exploratory.
- `main` is protected: PR + passing GitHub Actions + resolved conversations.
- Install once with `uv sync --frozen --extra agents` (the agent tests need it).
  Before every push run: `uv run --frozen --extra agents ruff check .`,
  `uv run --frozen --extra agents ruff format --check .`,
  `uv run --frozen --extra agents mypy`, and
  `uv run --frozen --extra agents pytest -n auto --dist loadfile` (focused tests
  first, then the full suite). These match CI, which also runs a separate
  `acceptance` job; both are required to merge into `main`.
- New dependencies: `uv add <pkg>` (updates `uv.lock`; mention it in the PR).
  CI runs without network; tests must use small deterministic fixtures, never the
  snapshot or paid/LLM APIs.
- Avoid editing `docs/DECISIONS.md`, `docs/RESEARCH_PROTOCOL.md`,
  `docs/STATUS.md` and `docs/PLAN.md` (merge-conflict hotspots and Marius's
  canonical record). Put your notes in `docs/team/<stream>.md` instead; Marius
  folds accepted decisions into the canonical docs.

## 5. Work streams

Your human will tell you which one is theirs. `docs/PLAN.md` is the authoritative
checklist: each stream below maps onto a PLAN phase, and its open checkboxes and
acceptance gate define "done". Start by producing a short written plan against
those checkboxes (in `docs/team/<stream>.md`) and confirm it with your human before
large changes. PLAN status and checkboxes are updated only when a gate truly passes.

### WS1: Gradient boosting, tuning and cross-validation
PLAN phase: none yet (exploratory research on top of the frozen v2 protocol; a
methodology change needs a new authorized experiment).

Goal: find out whether better-tuned tree models, or better validation and
calibration, change the A-versus-B conclusion, without breaking the matched design.

Starting points: `src/structural_break/research/evaluation.py`
(`_estimator`, `evaluate_matched_models`), `configs/research_v2.yaml`
(`logistic_c`, `xgb_candidates`, tuning years), snapshot feature tables via
`structural_break.collaboration.queries.existing_predictions`.

First task: **build an exploratory experiment harness** (for example
`src/structural_break/experiments/`) that loads the snapshot's per-horizon
model-input table, runs a configured estimator/grid/CV scheme for A and every B
ablation with identical budgets, and writes config + metrics + predictions to
`outputs/ws1/<experiment_id>/`. It must refuse 2024-2025 rows and must not write
into the workspace. Reproduce the canonical logistic/XGBoost numbers first as a
sanity check.

Ideas: larger but equal-budget XGBoost grids, early stopping on forward folds;
LightGBM / CatBoost / HistGradientBoosting; monotone constraints; more
walk-forward folds (e.g. 2014-2019) with horizon purging; isotonic vs sigmoid
vs no calibration; class-imbalance handling; stability of chosen hyperparameters
across folds; SHAP/permutation importance of B's SEC features; learning curves.

### WS2: Frontend / Streamlit app
PLAN phase: **P7** (full Streamlit research application).

Goal: turn the minimal read-only app (`app/streamlit_app.py`, currently "Model
comparison" and "Event scores") into the full research application (PLAN.md P7).

Starting points: `app/streamlit_app.py`, `app/reference_streamlit_app.py`
(older Scanner/Pair Detail), `src/structural_break/services/research_app.py`,
`app_queries.py`, `docs/specs/06_SOFTWARE_ENGINEERING_ARCHITECTURE.md`.

Ideas: Scanner (current divergences with A/B probabilities); Pair Detail
(prices, spread/z-score with entry/exit bands, monthly relationship diagnostics,
events and outcomes); Model comparison with reliability diagrams, ROC/PR, B-A
paired bootstrap interval, ablation ladder; slice explorer (year, business group,
sector, ACTIVE); source-coverage monitor (UNKNOWN rates); methodology/model card
page; Strategy Lab page that will read WS3's outputs. Every displayed number
shows its model/data version. Cache by version identifier; handle
empty/pending/error states; add app smoke tests. Optional later: Streamlit
Community Cloud deployment from a small demo snapshot.

### WS3: Backtesting framework
PLAN phase: **P6** (backtesting framework, experiment freeze, final evaluation).

Goal: one shared execution engine that turns events and model selections into
simulated trades and returns, for all strategy rungs, on development data only.

Starting points: the merged Phase 6 foundation in `src/structural_break/backtest/`
(fixed-share event engine, five-rung ladder, 12 cost/borrow scenarios, robustness
slices, calendar-month bootstrap, portfolio fixture; CLI `structural-break-backtest`,
runbook `docs/BACKTEST_RUNBOOK.md`, DECISIONS sections 30-31). It is tested only on
synthetic fixtures and its production policies are still DRAFT. Also
`docs/specs/05_BACKTESTING_EVALUATION.md`, `configs/backtest.yaml` (costs are still
`null`) and `python scripts/team.py backtest-inputs --pair X --horizon 20`.
Extend this code rather than starting over.

Ideas: connect the engine to real snapshot inputs for all 736 pairs (the export
command is currently per-pair; add an all-pairs path); beta-weighted long/short
legs; close-signal / next-open execution; convergence, adverse-stop and timeout
exits consistent with the labels; transaction cost and borrow assumptions with a
sensitivity grid (document sources); event-level return/MAE/MFE/holding period;
portfolio simulation with exposure and turnover; rungs Baseline 0 (all raw
crossings), Baseline 1 (econometrically valid), Model A selected (p >= 0.65),
Model B selected; Full System waits for the agents. Freeze execution
assumptions in writing before looking at 2022-2023 returns.

### WS4: Predictions and results analysis
PLAN phase: supports the v2 reporting gates and P6 predictive metrics; no own phase.

Goal: understand where and why B differs from A, and produce clean, traceable
tables and figures for the group.

Starting points: `python scripts/team.py predict` (omit `--pair` for all events;
`--horizon 10/30`), `existing_predictions(...)`, the published reports.

Ideas: error analysis by business group, year, ACTIVE status, coverage level;
calibration/reliability plots; where B helps/hurts and whether that tracks SEC
coverage; logistic coefficients for B's SEC block; case studies of individual
events with their SEC evidence metadata; denominators and positive counts for
every table; all ten bundles and all three horizons reported (no cherry-picking).

### WS5 (optional): Agents and human annotation
PLAN phase: **P5** (multi-agent investigation and decision controller).

The merged Phase 5 foundation in `src/structural_break/agents/` (CLI
`structural-break-agents`, runbook `docs/archive/AGENT_PIPELINE_RUNBOOK.md`, DECISIONS sections
28-29) has bounded LLM agents and a deterministic controller plus a 50-case blinded
SEC review export with zero human annotations so far. Whether the multi-agent
layer is completed is still undecided. A group member can complete the blind
annotations (no coding needed). Live LLM work needs a personal free Google AI Studio key in
`.env` (never committed); paid APIs stay disabled.

## 6. When you are unsure

Prefer asking your human over guessing on anything touching data periods,
labels, the event population, model comparison rules or the final test. For
engineering details that do not change scientific meaning, choose a conventional
approach and note it in your PR.

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
  `docs/PLAN.md` (merge-conflict hotspots and Marius's
  canonical record). Put your notes in `docs/team/<stream>.md` instead; Marius
  folds accepted decisions into the canonical docs.

## 5. Work streams

Your human will tell you which one is theirs. [PLAN.md](PLAN.md) lists every component with
its status and the open items. Start by producing a short written plan (in
`docs/team/<stream>.md`) and confirm it with your human before large changes. The detailed
original checklists (for example the full app, P7, and hardening, P8) are in
[archive/PHASE_PLAN.md](archive/PHASE_PLAN.md).

**Finished streams** (results in [FORECASTING_AND_BOOK.md](FORECASTING_AND_BOOK.md) and
[AGENT_DESK.md](AGENT_DESK.md)):
- *Gradient boosting, tuning and cross-validation:* the fixed XGBoost Model B (R0) stays the
  selection model; tuned families did not beat it (Decision 66); the bagged B+rule+ou is the
  pre-registered Goal 1 forecaster (Decisions 75–94).
- *Backtesting framework:* the plan-ladder engine (`backtest`) and the adopted trading book
  (`book`, Decision 110d).
- *Predictions and results analysis:* the Goal 1 and Goal 2 tables and figures in
  `docs/figures/quant/`.
- *Agents:* the agent desk (`agents`), evaluated in Decision 110d.

**Open for the group:**
- the blind human review of 50 agent cases: fill in
  [agent_review/review_answers.csv](agent_review/review_answers.csv) (no coding needed);
- the Streamlit app (below).

### WS2: Frontend / Streamlit app
Status: **open** (the group).

Goal: turn the minimal read-only app (`app/streamlit_app.py`, currently "Model
comparison" and "Event scores") into the full research application (the Streamlit app in PLAN.md).

Starting points: `app/streamlit_app.py`, `app/reference_streamlit_app.py`
(older Scanner/Pair Detail), `src/structural_break/services/research_app.py`,
`app_queries.py`, `docs/specs/06_SOFTWARE_ENGINEERING_ARCHITECTURE.md`.

Ideas: Scanner (current divergences with A/B probabilities); Pair Detail
(prices, spread/z-score with entry/exit bands, monthly relationship diagnostics,
events and outcomes); Model comparison with reliability diagrams, ROC/PR, B-A
paired bootstrap interval, ablation ladder; slice explorer (year, business group,
sector, ACTIVE); source-coverage monitor (UNKNOWN rates); methodology/model card
page; Strategy Lab page that reads the book's outputs (`outputs/book/`, `outputs/agent_desk/`). Every displayed number
shows its model/data version. Cache by version identifier; handle
empty/pending/error states; add app smoke tests. Optional later: Streamlit
Community Cloud deployment from a small demo snapshot.

## 6. When you are unsure

Prefer asking your human over guessing on anything touching data periods,
labels, the event population, model comparison rules or the final test. For
engineering details that do not change scientific meaning, choose a conventional
approach and note it in your PR.

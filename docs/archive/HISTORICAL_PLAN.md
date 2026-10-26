# P6 historical adapters, execution policy and experiment manifest: plan

Status: **Q1–Q7 APPROVED by the owner on 2026-10-16** (recorded as DECISIONS section 35).
Step A is implemented; step B (production policy proposal) is next, and step C waits
for its approval. Two implementation refinements of step A were made:

- Omitted raw crossings carry the factual reason `NOT_IN_HORIZON_EVENT_REGISTRY`
  rather than `EPISODE_OPEN`.
- No `PARTITION_NOT_ADMITTED` reason exists. The population is defined by signal
  date, and a stored score from a non-admitted partition stops the build.
Branch: `p6/historical-adapters` (from `research-v2` @ `5007809`).
Authority: `docs/PLAN.md` P6 is the checklist. DECISIONS 12, 30–33 and
`docs/specs/05_BACKTESTING_EVALUATION.md` govern. This file maps the work onto the
open P6 checkboxes, so it can be folded into PLAN.md/DECISIONS once approved.

## 0. Ground truth established while planning (structure only, no returns)

All facts below come from schemas, row counts and join checks on the provisional
pack. No price path was simulated and no label or return was aggregated.

| Fact | Consequence |
|---|---|
| `raw_crossings` (per pair) = 54,760 fresh, estimable crossings 2006-01-03…2023-12-29; it carries `pair_status`, `baseline1_eligible`, `previous_z_score` under the **same current snapshot**, as Decision 31 requires (`econometrics/engine.py:255-360`). | Baseline 0/1 can be built from stored rows. The previous z is reconciled from prices rather than recomputed from a different fit. |
| `h20_events` = 29,071 rows, an exact 1:1 subset of raw crossings on `(pair_id, event_date, relationship_snapshot_id)`. The difference is the v2 **non-overlapping episode/reset** rule (protocol §Target), which depends on the horizon (h10/h20/h30 counts differ). | **Open question Q1**: which inventory the trading ladder uses. |
| Evaluation `predictions.parquet` (h20) = 28,329 rows (fit 21,137 / calibration 3,762 / assessment 3,430), all inside `h20_events`; 354 model-ready events have no stored prediction. | Missing predictions remain `UNAVAILABLE` rows and are never dropped. |
| Signal `event_timestamp` equals the exact XNYS close, and snapshot `effective_start_at` lies between the next open after `window_end` and the signal. Checked on 2,695 crossings (40 pairs) against the existing `PairTradeRequest` validators: 0 violations. | Existing contracts can accept historical requests without loosening any clock rule. |
| Relationship z uses `log(adj_close)` with leg A = y and leg B = x. `prices.parquet` has raw `open`/`close` plus `adj_close`, and no adjusted open. Price quality flags: `OK` 1,222,840, `ZERO_VOLUME` 90. There are no null or non-positive prices. | Adjusted open = `open × adj_close / close` from the same row (same capture). The close basis is `adj_close`, so it matches the z used for signals. |
| The fitted `ResearchModel` bundle serializes its calibrator (`research/evaluation.py:25`). | The model identity is the bundle file SHA-256 from the evaluation manifest. The calibrator identity is derived from the same bound bytes. |
| The provisional pack has **no** primary publication, verification receipt or DuckDB registry. `registered_manifest()` reads `ops.artifact_registry`. | Accepted mode must go through `load_primary()`. Engineering runs on the provisional pack need an explicit, refusable unaccepted mode (**Q4**). |
| Every pair has `active_to = null` (surviving roster). Engine-level `_terminal()` marks RETIRED-by-termination. | Lifecycle termination is mapped from registry fields only. Survivorship stays a disclosed limitation. |
| The run had to locate `uv` at `%LOCALAPPDATA%\CodexRepoTools\uv\Scripts\uv.exe` (not on PATH). PR #17 (`docs/brief-plan-phases`) is not merged yet. | Environment notes only. |
| `BACKTEST_RUNBOOK.md` links "Decision 28/29/30" for what DECISIONS now numbers 30/31/32. | Fix in passing (docs only). |

## 1. Open P6 checkboxes and what each needs

| PLAN.md P6 item | This session | Can be ticked when |
|---|---|---|
| Implement accepted historical input/prediction/controller adapters for all five variants | **Build (step A)** | The adapters bind the **official** accepted snapshot through `load_primary` and pass the acceptance run there. Full System is explicitly NOT RUN, so the box stays `[-]` with a note until P5 supplies a controller generation (**Q5**). |
| Verify accepted historical predictive, controller and common-data comparison outputs | Inventory/selection verification only (no returns) | Official snapshot, frozen policy, owner approval. The controller part waits for P5. |
| Verify accepted historical portfolio, robustness/cost and economic uncertainty outputs under frozen production policies | Not this session | Requires the frozen policy from step B plus the step C manifest. |
| Implement accepted historical experiment manifest and immutable result persistence | **Build (step C)**, only after step B is approved | First accepted manifest written and independently re-verified on the official snapshot. |
| Freeze methodology/config/model/prompt/policy/execution assumptions | **Propose (step B)**, DRAFT | Owner approval recorded in DECISIONS; the prompt/controller part waits for P5. |
| Final-test lock gate / final run | Untouched | Explicit owner unlock only. |

## 2. Step A: historical adapters (code)

New modules `backtest/historical_contracts.py` and `backtest/historical.py`. The
fixture path (`ladder.py`, `experiment.py`, `analysis.py`) stays byte-compatible
apart from the small, additive contract changes listed under A6.

**A1. Generation binding (`HistoricalGenerations`)**
- *Accepted mode*: `load_primary(paths, version)` is the only entry point. It
  supplies the registry version, the per-horizon evaluation versions, the market
  input and the protocol `development_end`. Every file is read via
  `checked_file`/`checked_json` against its manifest SHA-256. The caller cannot
  substitute a generation, and nothing is selected by directory listing or
  modification time.
- *Unaccepted engineering mode* (Q4): the caller passes explicit paths **and**
  manifest SHA-256s (taken from `provisional_manifest.json`). The binding carries
  `acceptance="UNACCEPTED_ENGINEERING"`, which every downstream contract refuses
  for FROZEN policies, accepted manifests and anything beyond inventory/selection.
- Both modes refuse any row dated after 2023-12-31 and any manifest without
  `final_test_read is False`.

**A2. Price book (`HistoricalPriceBook`)**
- Source: `market/source_v1/prices.parquet`, checksum-bound to the market manifest.
- `close = adj_close`; `open = open × adj_close / close`, computed within one row,
  with `source_snapshot_id` and the row SHA-256 retained. Adjustment policy id:
  `yahoo-retrospective-adjclose-ratio-v1`. Retrospective adjustment is disclosed as
  not being a vintage feed.
- Quality: monitoring closes accept `{OK, ZERO_VOLUME}`, mirroring the
  relationship engine. **Fills (entry/exit opens) require `OK`.** A `ZERO_VOLUME`
  fill session becomes an explicit `MISSING_ENTRY_OPEN`/`MISSING_EXIT_OPEN` (Q6).
- Sessions come from `canonical_sessions`: the signal close through
  `horizon + 1` sessions, plus the exit open. Paths that would need 2024 sessions
  are truncated, giving `UNPRICED / INCOMPLETE_SESSION_PATH`. Nothing past the
  lock is read or constructed.

**A3. Signal/state adapter**
- One `LadderEvent` per inventory row (Q1). It contains:
  - the `RelationshipSnapshot`: id, alpha, beta, mean, std, `formation_end = window_end`, `available_at = effective_start_at`;
  - `signal_z`, reconciled to 1e-9 against the stored `z_entry`;
  - `PreviousClose`, recomputed from the previous session's adjusted closes under the same snapshot and reconciled against the stored `previous_z_score`;
  - `pair_status` as stored at signal time;
  - the sector from the pair universe;
  - lifecycle termination from registry fields.
- Any reconciliation failure stops the run. It is never patched.

**A4. Prediction adapter**
- Reads the stored `*_calibrated` columns for the declared policy's A and B
  bundles (default: logistic A, logistic B-both). Each value is bound to the
  bundle SHA-256 and the horizon, with `information_cutoff =
  feature_cutoff_timestamp`, which must equal the signal close.
- Partition admission is set by the ladder policy (Q2). Scores outside the
  admitted partitions become `UNAVAILABLE / PARTITION_NOT_ADMITTED`, keeping the
  row.
- Optional native replay check through the existing
  `collaboration.queries.existing_predictions` (1e-12) is mandatory in accepted
  mode and off in tests.

**A5. Controller adapter / Full System**
- With no accepted controller generation (P5 unfinished), the adapter emits
  `FULL_SYSTEM: NOT_RUN / CONTROLLER_GENERATION_NOT_ACCEPTED` for **every** row.
  The rung is not run. It is never treated as withheld, as zero selected or as
  a zero return.
- The binding slot is typed for the P5 historical scored inputs:
  `agents/historical.py::AcceptedHistoricalInputs`, the frozen schedule id and
  the controller policy version. Wiring it is a later, separate gate.

**A6. Engine changes (additive)**
- Add the `NOT_RUN` disposition and the `CONTROLLER_GENERATION_NOT_ACCEPTED` and
  `PARTITION_NOT_ADMITTED` reasons.
- Reporting renders a NOT_RUN rung as status-only, with null metrics and null
  adjacent B→Full comparisons.
- Add a historical `evaluate_ladder` path. It requires `data_kind =
  DEVELOPMENT_CAPTURE`, an accepted binding and an `ExecutionConfig(mode=
  DEVELOPMENT, status=FROZEN)`. While the policy is DRAFT, only
  `select_inventory()` runs: selection plus row inventory, with **no simulator
  call and no returns**.

**A7. Labels**
- A separate reporting input built from `h{h}_targets`: `y_revert_success`,
  `label_eligible`, `label_policy_version`, the manifest SHA-256, and
  `complete_window_end = horizon_end_date`.
- Censored and ineligible rows have no label, and labels never reach selection
  (an existing invariant).

**A8. Tests** (pytest, sockets blocked, small deterministic fixtures written
under `tmp_path` and never the provisional data)
- Binding refusals: SHA mismatch, unaccepted binding used for FROZEN or accepted
  work, a missing `final_test_read`, rows from 2024 or later.
- Adjusted-open arithmetic, plus a `ZERO_VOLUME` fill counted as missing.
- Truncation at 2023-12-29 producing UNPRICED.
- Reconciliation failures for previous z, signal z and snapshot clocks.
- A missing prediction, a prediction cutoff mismatch and partition admission.
- Full System NOT_RUN propagating to reports.
- Labels isolated from selection.
- The DRAFT policy blocking simulation of historical rows.
- Gates: Ruff, format, strict mypy and the full suite.

**A9. Engineering smoke run (local, provisional, single thread)**
- Inventory and selection only, to confirm that all inputs bind and reconcile at
  full scale.
- Reported as counts and reconciliation status, **never as returns**. Output goes
  under the scratch `.acceptance/`, which stays out of Git.

## 3. Step B: production execution policy proposal (DRAFT, needs your approval)

Deliverables:
- `docs/archive/EXECUTION_POLICY_PROPOSAL.md`;
- `configs/phase6_execution_proposed.json` (`status: DRAFT`);
- a target-blind diagnostics script.

Sources are cited after verifying each one when drafting; nothing is cited from
memory alone. No return is computed before the freeze.

| Assumption | Draft direction (to be argued with sources) | Sensitivity |
|---|---|---|
| Trading cost per entry/exit turnover | Headline from the literature on large-cap US effective spreads and implementation shortfall, 2006–2023. Candidate sources to verify: Frazzini–Israel–Moskowitz "Trading Costs"; Do & Faff on pairs-trading costs; Novy-Marx & Velikov. Optionally a target-blind, per-stock Abdi–Ranaldo/Corwin–Schultz spread estimate from our own OHLC data, using fit-period data only. | The existing predeclared grid of 2.5 / 5 / 10 / 20 bps |
| Short borrow | General-collateral fee level from the securities-lending literature (D'Avolio 2002; later lending-fee studies). All 250 issuers are large caps, so a "hard-to-borrow" flag is a disclosed limitation. | The existing 0 / 3 / 10 % p.a. |
| Positive-beta ceiling | An economic leg-ratio bound: w_B/w_A = β, so β ≤ c caps notional imbalance at c:1. The ceiling is chosen from that argument and the fit-period (2006–2019) **snapshot** beta distribution only, never from outcomes. | {2, 3, 5, none} as a labelled sensitivity |
| Price adjustment | Yahoo retrospective adjusted close. Adjusted open = open × adj_close/close, from the same row. Dividends are carried in the total-return basis on both legs (an implicit manufactured dividend on the short leg). | none; this is a disclosed limitation |
| Eligibility (applied to all rungs as one shared gate) | Positive beta ≤ ceiling; `OK` fills; candidate floors on price and dollar volume using trailing data only (e.g. `log_min_adv20`). | ± one floor level |
| Economic bootstrap / portfolio | Freeze the existing fixture policies (month blocks, seed 5557, ≥12 months; 25 % NAV per entry, one position per pair), or amend them before use. | Not applicable |

All rungs share one engine and one policy; only the capability filter differs.
2022–2023 has already been observed, so every economic number from it is labelled
**post-hoc development**, never a final-test result.

## 4. Step C: accepted historical experiment manifest (after step B is approved)

- Extend `experiment.py` with `HistoricalExperimentManifest`. It binds:
  - the primary version and the registry/evaluation/market manifest SHA-256s;
  - the adapter and engine source SHA-256;
  - the FROZEN execution-policy SHA-256;
  - the ladder policy (threshold, model bundle ids, admitted partitions, horizon);
  - the label identity;
  - the controller binding, or `NOT_RUN`;
  - the Python/package runtime.
- Content-addressed, write-once directory with
  `input/policy/execution-config/labels/rows/report/summary/manifest`.
- `verify-historical` rebuilds from the bound sources and reruns the simulator.
  Mismatched bytes fail and are never rewritten.
- Refuses a DRAFT policy, an unaccepted binding, 2024 or later rows and runtime
  drift.
- DuckDB registration (`ops.experiments`, `analytics.backtest_trades`): **Q7**.

## 5. Questions for you

1. **Q1, trading inventory.** Should B0/B1 use (a) the horizon's
   **non-overlapping episode events** (h20: 29,071), with raw crossings
   suppressed by an open episode retained as `EPISODE_OPEN` rows, or (b) all
   54,760 raw crossings?
   - *Recommendation: (a).* A/B can only score episode events, so (b) would
     confound B1→A with deduplication. One change per rung.
2. **Q2, period.** Stored fit (2006–19) and calibration (2020–21) scores are
   in-sample for the model or the calibrator.
   - *Recommendation:* the headline development ladder covers **2022–2023
     assessment only, for all five rungs**, labelled post-hoc. B0/B1 over
     2006–2021 is an optional, separately labelled descriptive history without
     A/B rungs.
3. **Q3, selection policy.** Calibrated logistic A and B-both at h20, threshold
   0.65 (the matched v2 reporting threshold), as the headline. XGBoost,
   B-ablations and h10/h30 are all reported as labelled sensitivities. Agree?
4. **Q4, unaccepted engineering mode.** May the adapters accept explicit
   path+SHA bindings to the provisional pack for **inventory/selection-only**
   smoke runs? No returns; refused by everything accepted or frozen.
5. **Q5, checkbox handling.** Should "adapters for all five variants" stay `[-]`
   with "Full System NOT RUN pending P5"? The alternative is splitting it into
   "four rungs" plus "Full System controller adapter".
6. **Q6, ZERO_VOLUME fills.** Should a fill on a ZERO_VOLUME session be treated
   as missing (unfilled)? Recommended yes; it affects 90 rows.
7. **Q7, persistence.** Files plus manifest now and DuckDB registration later
   (for the WS2 Strategy Lab), or both now?
8. **Order.** I'll build step A and its tests, then draft step B for your
   review. Step C starts only after you approve step B. Commits stay local until
   you say push.

## 6. Step A engineering record (2026-10-16)

- **Tests.** 18 new blocked-socket fixture checks in `tests/test_backtest_historical.py`.
  The Phase 6 suite passes at 314 (previously 296). Ruff, format and strict mypy
  pass repository-wide. The full cross-phase suite is left to hosted CI: run on
  one thread it takes hours, and only the backtest tests import the changed
  package.
- **Provisional smoke run** (`UNACCEPTED_ENGINEERING`, h20, inventory only, no
  prices simulated, no labels read). It ran in about 70 s on one thread.
  - Every one of the 3,558 assessment-window episode events bound and
    reconciled: the previous z, the signal z, the snapshot clocks and the
    relationship parameters.
  - 3,018 raw crossings were recorded as `NOT_IN_HORIZON_EVENT_REGISTRY`.
  - 128 events have no stored prediction.
  - Baseline 1 (ACTIVE) selects 266 events.
  - At the matched 0.65 threshold, Model A and Model B each select 0 of the 260
    scored ACTIVE events; 6 ACTIVE events have no score.
  - These are unaccepted engineering counts, not findings. The empty A/B rungs
    are an **open design question for the owner** (see the chat record). The
    threshold is not changed here.

# Shared event simulator runbook

Phase 6 starts with a synthetic, event-level execution engine and capability
comparison reports. It is prepared on isolated branch
`phase6/shared-simulator` while v2's live source and
checkpoints remain frozen. [Decision 30](DECISIONS.md#30-phase-6-fixed-share-development-simulator)
and [the specification](specs/05_BACKTESTING_EVALUATION.md) govern execution.
[Decision 31](DECISIONS.md#31-phase-6-fixture-ladder-and-coverage-reporting)
governs fixture selection and coverage reporting.
It does not download prices, fit models, call an LLM or unlock 2024-2025 outcomes.
Its separate portfolio accounting example is synthetic. Historical economic
assessment remains pending.

## Run the deterministic example

From the repository root with Python 3.11 and the committed environment:

```powershell
uv sync --frozen
uv run --frozen structural-break-backtest --fixture --output-dir .acceptance/phase6-demo
```

The equivalent module entry point is:

```powershell
uv run --frozen python -m structural_break.backtest.cli --fixture --output-dir .acceptance/phase6-demo
```

The fixture explicitly identifies its synthetic price basis and scenario.
Its prices are not captured market history and its completed return is not
evidence of investment performance. Output persistence is explicit; ordinary
app browsing must not run this command. Use a new output directory for a
changed input or execution policy. Matching immutable output may be replayed,
but existing bytes must never be overwritten to repair a checksum.

## Execution contract

`PairTradeRequest` binds signal identity/time, the point-in-time frozen
relationship snapshot, an explicit ordered XNYS session list, the source
identity/price basis and the two legs' opens/closes. `ExecutionConfig` supplies
the versioned scenario; `simulate_pair_trade` returns `PairTradeResult`.
The supplied sessions and event cutoff are checked against the actual XNYS
calendar, including close times. Historical captured input integration is a
separate gate; typing a source name does not establish source acceptance.

Snapshot `available_at` is the first usable timestamp for execution inputs.
It must be at or after the exact next XNYS open after the formation endpoint
and at or before the signal close. A fit formed at the signal day's close
cannot be used for that same signal.

Signal sign, alpha, beta, spread mean and standard deviation stay fixed.
Positive z shorts A and buys B; negative z reverses the signs. Initial gross
notional is split with the frozen beta weights and converted to share units
using entry prices. Units remain fixed until exit. Positive beta is a trading
eligibility requirement, not a new condition on v2's forecast cohort.

Entry uses the exact following XNYS open. Beginning with that session's close,
monitor the frozen z path for an observed |z| <= 0.5 convergence or signal-sign
times z >= 3 same-side adverse stop. An opposite-side overshoot outside the
success band is neither event. Absent a trigger, exit follows the close of
session 20 after the signal; 10/30-session sensitivity policies are separate.
Every exit uses the exact following XNYS open. Missing fills are explicit
unknown execution, without carrying to a later open or filling prices.

Gross return is fixed-share P&L divided by entry gross notional. The fixture
charges 5 bps on actual gross entry turnover and 5 bps on actual gross exit
turnover. Borrow is 3% annualized on entry short notional times held open-to-open
XNYS session intervals / 252. The fixture's beta ceiling of 10 is a synthetic
policy parameter, not a new research-universe restriction. Completed MAE/MFE
sample entry zero, monitored closes and executed exit open before costs;
intraday extrema cannot be observed from daily bars.

`COMPLETE` identifies a fully priced executed trade. `NOT_ENTERED` identifies
an execution-ineligible signal or unavailable entry. `UNPRICED` retains an
entered trade whose required monitoring/exit price, full path or lifecycle
settlement is unavailable. Final return/cost/full-path fields are null for
unknown execution. Report these counts and reasons alongside completed
outcomes; do not assign zero return or drop their denominator. Separately
named `partial_mae` and `partial_mfe` describe only the observed prefix of an
UNPRICED path, including entry zero, while final `mae`/`mfe` stay null. Exclude
these prefixes from completed-event excursion statistics.

## Run and verify the synthetic capability comparison

The ladder command runs the synthetic event inventory through Baseline 0,
Baseline 1, Model A, Model B and Full System. It uses stored fixture scores and
controller decisions; it does not fit models, invoke agents or access v2 data.

```powershell
uv run --frozen structural-break-backtest ladder --fixture --output-dir .acceptance/phase6-ladder
```

The command reports the immutable manifest path. Verify that exact manifest
explicitly, replacing the placeholder below with its returned path:

```powershell
uv run --frozen structural-break-backtest verify --manifest MANIFEST.json
```

Verification checks bound input/config/code/output identities, reconstructs the
selection and reporting, and reruns synthetic execution. A changed checksum
fails; verification cannot rewrite it. Matching replay is idempotent. A changed
scenario, inventory, implementation or declared Python/package runtime receives
a different content identity. Verification requires the manifest's exact bound
source and runtime versions; path relocation alone does not change the identity.

The content-addressed `experiments/<experiment_id>/` directory contains
`input.json`, `policy.json`, `execution-config.json`, separate `labels.json`,
`rows.json`, `report.json`, `summary.md` and the SHA-bound `manifest.json`.
`rows.json` is the complete event/selection/execution inventory. Read the
summary beside the machine-readable report and manifest, rather than treating
a summary file alone as accepted research output. Supplied `--input`,
`--policy`, `--config` and optional `--labels` files are fixture contracts;
they cannot declare themselves genuine accepted market/model data.

Baseline 0 selects a fresh estimable crossing using the same admissible current
relationship parameters for the previous and signal-close z-scores. Baseline 1
adds historical ACTIVE. A and B independently add their own frozen calibrated
probability at the shared fixture threshold; B need not pass A. Full adds a
stored CANDIDATE to B. All rungs share the event engine and its execution gates.
The engine simulates each fresh raw event once, including counterfactuals for
events rejected by higher filters. Nonfresh and unavailable signals retain rows.

Read coverage before returns: each variant reports input/eligible/selected,
available labels and COMPLETE/NOT_ENTERED/UNPRICED execution counts. Mean and
median returns use only COMPLETE selected trades; missing execution is not zero.
Supervised success comes from the separate bound label input and cannot be
inferred from net return or an exit reason. The same counterfactual result
supplies rejected-event summaries, with its own denominator.

Descriptive predictive/calibration metrics use only estimable fresh divergences,
regardless of historical ACTIVE status or later selection. The report counts
nonfresh/unknown crossings excluded from that forecast population, missing
scores and missing labels. Common-score A/B metrics use the same available
score-and-label rows. These fixture tables do not replace canonical v2's broad
matched forecasting reports or paired calendar-quarter uncertainty.

Adjacent comparisons name the common required-data population and the actual
selected intersection separately. On common data, A/B selection still runs
independently. B/Full reporting retains all scheduled B candidates, including
missing, failed and stored ABSTAIN results. Unscheduled rows are separate. Only
an explicit NO TRADE counts as a veto; REVIEW, ABSTAIN and unavailable decisions
have distinct withholding counts. Empty denominators yield null rates.

These ladder artifacts are synthetic engineering examples. They cannot demonstrate
model improvement, agent evidence quality or investable performance. The separate
analysis command below adds fixture portfolio accounting and uncertainty mechanics.

## Run and independently verify the analysis bundle

```powershell
uv run --frozen structural-break-backtest analysis --fixture --output-dir .acceptance/phase6-analysis
uv run --frozen structural-break-backtest verify-analysis --manifest RETURNED_MANIFEST_PATH
```

Repeat the first command to confirm immutable reuse. The `analyses/<analysis_id>/`
directory contains eleven bound input/policy/context files, seven output reports
and a manifest binding their bytes, computational source and Python/package runtime.
Verification freshly rebuilds every output; replacing a report and rehashing it
cannot bypass replay. Source/runtime changes receive a different identity.

The analysis keeps all fourteen ladder events and all five strategy records. It
reports all twelve predeclared turnover/borrow scenarios, without selecting a
winner or changing event selection. Robustness includes year, pair, sector, sign,
coverage, previous-session VIX/trailing volatility, event category/materiality,
small-population flags and leave-one-pair/sector-out diagnostics. Missing context
remains UNKNOWN. Context values bind event identity and admissible evidence clocks.

The economic month bootstrap uses 2,000 seeded paired draws (5557) from the complete
calendar-month range. It names natural COMPLETE-only event means, common known
allocation per raw candidate and both-selected COMPLETE intersections separately.
WITHHELD is explicit zero allocation; selected unknown execution is not zero.
Intervals require at least twelve contributing months for each estimand, including
both sides for natural means. The one-month fixture therefore has no intervals.
This does not change v2's existing paired-quarter forecast bootstrap.

A separate two-proposal portfolio fixture starts at NAV 1, targets 25% NAV gross
at entry, clips simultaneous allocations equally and reserves entry costs.
Fixed entry shares, previous-close-triggered exits before new entries and one
position per pair determine chronological open/close cash, NAV, exposure, turnover,
borrow and drawdown. The gross limit is an entry admission cap: passive price drift
may breach it and is reported. There is no automatic rebalancing, financing/margin
or idle-cash return model. Missing held quotes make later NAV unknown and block new
allocations; future COMPLETE status cannot determine entry eligibility. These two
proposals are an accounting check, not a five-strategy portfolio assessment.

[Decision 32](DECISIONS.md#32-historical-bridges-and-economic-analysis-before-v2-completion)
records these fixture choices and their timing. Actual execution, portfolio and
historical-data assumptions remain unfrozen. All scientific acceptance flags are
false and final-test outcomes remain locked.

## Historical selection inventory (generation-bound, no returns)

[Decision 34](DECISIONS.md#34-phase-6-historical-adapters-and-selection-inventory)
governs the historical adapters. They read registered v2 outputs only through
manifest checksums, starting from one evaluation manifest and following its
registry and market parents. The inventory selects the five rungs over the
horizon's non-overlapping episode events in the 2022-2023 assessment window.
It never simulates a price path or reads a label, so it runs while the
production execution policy is DRAFT. Full System is `NOT_RUN` for every row
until an accepted controller generation exists.

Accepted binding (official snapshot; derives every identity from the published
primary readiness record):

```powershell
uv run --frozen structural-break-backtest historical-inventory --workspace-root WORKSPACE --accepted --horizon 20 --output-dir .acceptance/p6-inventory
```

Unaccepted engineering binding (for example the provisional pack). This needs an
explicit workspace-relative evaluation manifest and its exact checksum. The
result is marked `UNACCEPTED_ENGINEERING` and cannot reach a frozen policy,
execution or an accepted manifest:

```powershell
uv run --frozen structural-break-backtest historical-inventory --workspace-root WORKSPACE --evaluation-manifest artifacts/research/EVALUATION/manifest.json --evaluation-sha256 SHA256 --horizon 20 --output-dir .acceptance/p6-inventory
```

The content-addressed `inventories/<id>/` directory holds `spec.json`,
`inventory.json` (one row per episode event, with five rung selections) and
`summary.json` (counts and reasons only). Raw crossings in the window that the
episode registry omits are listed as `NOT_IN_HORIZON_EVENT_REGISTRY`; they are
not trading rows. Each event is rebuilt from bound data in this order:

- the frozen relationship snapshot is joined;
- the signal close and the previous z are reconciled from adjusted prices
  (1e-9), and any mismatch stops the run;
- adjusted opens are `open * adj_close / close` from the same capture row;
- `ZERO_VOLUME` sessions supply monitoring closes but not fills;
- paths that would need 2024 sessions are truncated, never constructed.

Historical execution (`evaluate_historical_ladder`) additionally requires an
accepted binding, a FROZEN ladder policy and a FROZEN `DEVELOPMENT` execution
policy. Decision 35 froze that policy in `configs/phase6_execution.json`, so on
the provisional pack it still refuses because the binding is unaccepted.

### Accepted historical experiment (official snapshot only)

[Decision 36](DECISIONS.md#36-accepted-historical-experiment-manifest-and-persistence)
governs the experiment. It accepts only a binding derived from the published
primary readiness record; the provisional pack is refused before anything is
computed. Run one experiment per horizon and verify it independently:

```powershell
uv run --frozen structural-break-backtest historical-experiment --workspace-root WORKSPACE --horizon 20 --output-dir .acceptance/p6-experiment
uv run --frozen structural-break-backtest verify-historical-experiment --workspace-root WORKSPACE --manifest RETURNED_MANIFEST_PATH
```

At h20 the experiment runs the 22 frozen h20 policies and the four trading
thresholds as 25 declared combinations. `summary.md` labels the results as
post-hoc 2022-2023 development assessment. Full System is shown as not run.
Read `reports.json` for every denominator, unknown execution and label count.
Verification rebuilds the events from the bound sources and replays
everything. A changed config, source, runtime or artifact fails verification;
nothing is rewritten.

### Target-blind execution-policy diagnostics

The proposal in `docs/proposals/P6_EXECUTION_POLICY.md` is supported by a
diagnostics command. It reads only fit- and calibration-period data (dates
before the bound assessment start) and summarizes three things:

- relationship betas against candidate ceilings;
- minimum-leg 20-session dollar volume against candidate floors;
- calibration-period calibrated score distributions.

It never loads a supervised target column and computes no return:

```powershell
uv run --frozen structural-break-backtest policy-diagnostics --workspace-root WORKSPACE --accepted --horizon 20 --output-dir .acceptance/p6-diagnostics
```

The same explicit unaccepted binding flags as `historical-inventory` are
accepted. Re-run it on the official snapshot before any policy freeze.

## Production policy and future data adapter

[Decision 35](DECISIONS.md#35-frozen-phase-6-production-execution-policy-and-trading-threshold)
froze the production policy. `configs/phase6_execution.json` is the
`pair-execution-policy-v2` DEVELOPMENT/FROZEN headline:

- 5 bps per entry and exit turnover;
- 1 % annual borrow;
- 0 < β ≤ 3;
- a minimum-leg 20-session mean dollar volume of at least $5 M, measured over
  exact XNYS sessions ending at the signal close.

Missing leg liquidity is `NOT_ENTERED / MISSING_LEG_LIQUIDITY`; a thin leg is
`ILLIQUID_LEG`. `configs/phase6_execution_sensitivities.json` declares the
frozen sensitivity set. `structural_break.backtest.production_policy` expands
it deterministically into 24 identified policies:

- the 4 × 4 cost/borrow grid;
- β ceilings of 2, 5 and none (encoded as 100);
- liquidity floors of 0, $1 M and $10 M;
- 10- and 30-session horizons.

Every variant is reported and none is selected. The common A/B trading
threshold is 0.30, with 0.20, 0.40 and 0.65 reported.

The engine still refuses captured input under a DRAFT policy, and fixture mode
cannot admit a captured market request. Legacy `configs/backtest.yaml` remains
an original reference contract. The cited rationale is in
`docs/proposals/P6_EXECUTION_POLICY.md`.

Typed input/config files can be submitted explicitly:

```powershell
uv run --frozen structural-break-backtest --input REQUEST.json --config configs/phase6_execution.json --output-dir .acceptance/phase6-policy-check
```

This is a contract/refusal check, not permission to construct arbitrary
historical returns. A real adapter must bind accepted registry/model/source
identities and use opens/closes on the same declared adjustment basis. For
the future Yahoo adapter, adjusted open must equal raw open multiplied by
adjusted close / raw close from the same capture. Retrospective adjustments
are a disclosed limitation, not vintage historical prices. Delisting/corporate
action settlement and actual borrow availability are not implemented here.

Execution, cost, borrow, price-adjustment and eligibility assumptions are
frozen (Decision 35). Genuine economic assessment still requires the accepted
experiment manifest (step C) on the official snapshot, bound to accepted
generation signals and frozen stored predictions. Full System waits for
accepted controller decisions. All five variants must share this engine
and cost policy; only their declared capability filters differ. Model A/B
forecast evaluation still uses the broad matched v2 cohort and its canonical
paired calendar-quarter bootstrap. Decision 35 also freezes the economic
month-block uncertainty and the secondary portfolio policies for production use.

## Verification and remaining gates

The synthetic acceptance boundary checks direction/units, exact entry/exit
timing, convergence versus an equilibrium overshoot, same-side stops,
timeouts, gaps, turnover costs, borrow duration, missing/truncated/lifecycle
paths, final-test refusal and immutable artifacts with network sockets blocked.
The current Phase 6 suite contains 296 blocked-socket checks: 75 simulator,
57 ladder, 32 reporting, 37 experiment and 95 analysis/cost/portfolio/robustness
checks. The integrated Phase 5/6 suite is checked after branch integration.
Earlier slices passed 381 and 255 combined tests. Local repository
Ruff, formatting, full strict mypy and lockfile checks pass. The single-event
console fixture repeats with an identical immutable result identity. The
14-row ladder publishes its manifest, independently verifies as
`VERIFIED_SYNTHETIC_REPLAY` and repeats with the same immutable experiment
identity. The initial simulator commit
`7a954f0` passed the full hosted Linux regression in
[CI run 38109378392](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/38109378392).
The fixture ladder/reporting commit `292a12f` passed
[CI run 38120892852](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/38120892852).
The expanded analysis commit requires fresh hosted checks.
That new slice has its own engineering checks; it does not complete genuine historical
execution or accepted v2/controller integration. Portfolio allocation and economic
uncertainty are implemented on fixtures; their genuine historical assessment and
the production assumption freeze remain pending.

The final-test lock is separate: no 2024-2025 outcome/performance run is
authorized by this implementation, a DRAFT-policy check, v2 promotion or
synthetic success. Require an immutable freeze manifest and explicit user
authorization before that later run.

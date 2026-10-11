# Shared event simulator runbook

Phase 6 starts with a synthetic, event-level execution engine. It is prepared
on isolated branch `phase6/shared-simulator` while v2's live source and
checkpoints remain frozen. [Decision 28](DECISIONS.md#28-phase-6-fixed-share-development-simulator)
and [the specification](specs/05_BACKTESTING_EVALUATION.md) govern this slice.
It does not download prices, fit models, call an LLM, run a portfolio backtest
or unlock 2024-2025 outcomes. Historical economic assessment remains pending.

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

## Production policy and future data adapter

`configs/phase6_execution.json` is deliberately DEVELOPMENT/DRAFT. Costs,
annual borrow and the economically sensible beta ceiling are unresolved.
The engine refuses captured development input with an unfrozen policy.
The fixture mode cannot admit a captured market request. Legacy
`configs/backtest.yaml` remains an original reference contract.

Typed input/config files can be submitted explicitly:

```powershell
uv run --frozen structural-break-backtest --input REQUEST.json --config configs/phase6_execution.json --output-dir .acceptance/phase6-draft-check
```

This is a contract/refusal check, not permission to construct arbitrary
historical returns. A real adapter must bind accepted registry/model/source
identities and use opens/closes on the same declared adjustment basis. For
the future Yahoo adapter, adjusted open must equal raw open multiplied by
adjusted close / raw close from the same capture. Retrospective adjustments
are a disclosed limitation, not vintage historical prices. Delisting/corporate
action settlement and actual borrow availability are not implemented here.

Before genuine economic assessment, freeze the actual cost/sensitivity,
borrow, price-adjustment, execution/eligibility and experiment assumptions.
Then integrate accepted generation-bound signals and frozen stored
predictions/controller decisions. All five variants must share this engine
and cost policy; only their declared capability filters differ. Model A/B
forecast evaluation still uses the broad matched v2 cohort and its canonical
paired calendar-quarter bootstrap. Economic month-block uncertainty remains
a separate proposal to specify before assessment.

## Verification and remaining gates

The synthetic acceptance boundary checks direction/units, exact entry/exit
timing, convergence versus an equilibrium overshoot, same-side stops,
timeouts, gaps, turnover costs, borrow duration, missing/truncated/lifecycle
paths, final-test refusal and immutable artifacts with network sockets blocked.
All 75 focused simulator tests pass with sockets blocked, and the combined
Phase 5/6 suite passes 255 tests after integration. Local repository Ruff,
formatting, strict mypy and lockfile checks pass; the console fixture repeats
with an identical immutable result identity. Hosted full regression remains a
separate check on the branch commit. Genuine historical execution, the five-rung filters,
common-subset/coverage reporting, portfolio allocation and economic metrics
remain pending after fixture acceptance.

The final-test lock is separate: no 2024-2025 outcome/performance run is
authorized by this implementation, a DRAFT-policy check, v2 promotion or
synthetic success. Require an immutable freeze manifest and explicit user
authorization before that later run.

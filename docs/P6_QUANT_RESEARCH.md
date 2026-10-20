# Quant research programme (workstream 1)

Branch `p6/quant-research`. Pre-registrations and results:
[DECISIONS 75–84](DECISIONS.md). The 2024–2025 final test stays locked, and
nothing here changes the frozen Decision 36–42 policies or the accepted v2
snapshot.

**Overfitting control.** Every choice was made on the 2010–2017 walk-forward
test years. 2018–2023 was opened once per stage, only after the choice was
committed. Two choices that looked good on 2010–2017 did **not** hold out
(the extra feature block and a wider take profit), and both were rejected.

## Goal 1: forecasting mean reversion

The target is whether a divergence (|z| ≥ 2) reverts to |z| ≤ 0.5 within 20
sessions before |z| ≥ 3. The base rate is 8–10 %.

New point-in-time feature blocks (`p6_quant_features`):

| Block | Contents |
|---|---|
| peer | Each stock's displacement against all its other peers; share of its other pairs diverging; market-wide divergence breadth (Chen et al. 2019; Avellaneda & Lee 2010) |
| state | Zero crossings over 252 days, AR(1) rho, error-correction speed, relationship age |
| earnings | Days since and estimated days to each leg's next earnings 8-K; next earnings inside the holding window |
| momentum | Each leg's 20/120-session return aligned with the divergence; distance to the 252-session high |
| track | Pair and stock reversion record on earlier resolved events (reported only) |

**Holdout result, 2018–2023** (the same labelled events for every model):

| Model | ROC-AUC | PR-AUC | Log loss | Brier |
|---|---|---|---|---|
| Original Model B (Decision 45 XGBoost) | 0.718 | 0.207 | 0.2832 | 0.0790 |
| **B+rule (pre-registered choice)** | **0.730** | **0.214** | **0.2799** | **0.0785** |
| B + all blocks incl. track (best observed, not rule-chosen) | 0.733 | 0.219 | 0.2783 | 0.0781 |

- **B+rule against the original Model B:** log loss gain +0.0034, 95 %
  [+0.0005, +0.0062], p = 0.007; AUC +0.012, p = 0.002 (month-block
  bootstrap).
- **First significant result:** this is the first significant out-of-sample
  forecast improvement in the project.
- **Where the gain comes from:** the new information, not the training
  scheme or tuning.

## Goal 2: the best portfolio

Better reversion forecasts did **not** select better trades: the most
confident reversions are often small, tight-spread moves that costs eat.
The trading design was therefore built separately.

| Component | Choice | Evidence |
|---|---|---|
| Selection | Original Model B, top 20 % by previous-year cutoff | Beat B+rule and a return-regression ranking for trading (Decisions 79a/b) |
| Entry filter | Skip if the moving company filed earnings in the last 3 sessions or has negative recent news | Best 2010–2017 portfolio Sharpe (Decision 82a) |
| Take profit | \|z\| ≤ 1.0 (frozen: 0.5) | 36-variant exit grid; confirmed on 2018–2023 (Decision 77) |
| Adverse stop | Disaster stop at \|z\| ≥ 5 (frozen: 3) | Stops at 3 cut profits; the disaster stop limits the tail (Decision 80a) |
| News exit | E3 adverse-tone exit | Decision 60 |
| Time stop | 20 sessions | 10 was worse in every comparison |

**Portfolio, 2010–2023** (frozen portfolio policy: start NAV 1, 25 % of NAV
per entry, gross ≤ 100 % of NAV, frozen costs and borrow):

| Design | CAGR | Volatility | Sharpe | Max drawdown | Total return |
|---|---|---|---|---|---|
| Trade every divergence, frozen exit (original) | −3.6 % | 4.1 % | −0.86 | −20.0 % | NAV 0.84 by 2014 |
| Model B, news exit (Decision 73 candidate) | −0.5 % | 5.4 % | −0.06 | −18.7 % | −6 % |
| **Programme design** | **+2.25 %** | 5.8 % | **0.41** | **−13.8 %** | **+36 %** |
| Programme design, 10 % per entry | +2.0 % | 4.4 % | 0.48 | −11.3 % | +32 % |

The programme design's Sharpe is +0.32 in 2010–2015, +0.55 in 2016–2021 and
+0.24 in 2022–2023. It is positive in 11 of 14 years; the worst year is
2015 at −6.1 %.

**Cost and borrow sensitivity** (programme design, 25 % per entry,
2010–2023):

| Scenario | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| Costs 2.5 bps per side | +3.0 % | 0.54 | −12.5 % |
| Frozen (5 bps per side, 1 % borrow) | +2.25 % | 0.41 | −13.8 % |
| Costs 10 bps per side | +0.8 % | 0.16 | −16.3 % |
| Borrow 2 % | +1.8 % | 0.34 | −14.5 % |

**Caveats.**
- **Costs:** the edge is thin relative to costs. At double the frozen costs
  the design is only marginally positive, and execution quality would
  decide whether it pays.
- **Unlevered returns are modest** because the frozen policy caps gross
  exposure at 100 %. At Sharpe 0.4–0.5, leverage scales return and drawdown
  together.
- **These years were all used during development,** so the portfolio
  numbers describe the design rather than test it. The 2024–2025 final test
  is the test.

## Running

```powershell
# features, forecast specs and summaries (selection years; add --holdout to confirm)
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant run --specs B B+rule --schemes recent d45
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant summary
# exit grid (all events, 36 exits, checked against the frozen simulator) and exploration
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant_trading build
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant_trading explore-exits
# portfolios from a designs JSON
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant_portfolio --designs outputs\p6_quant\designs.json
```

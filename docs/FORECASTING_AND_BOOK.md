# Quant research programme (workstream 1)

Branch `p6/quant-research`. Pre-registrations and results:
[DECISIONS 75–100](DECISIONS.md). The 2024–2025 final test stays locked, and
nothing here changes the frozen Decision 36–42 policies or the accepted v2
snapshot.

**Overfitting control.**
- **Choices:** every choice was made on the 2010–2017 walk-forward test years.
- **Confirmation:** 2018–2023 was opened once per stage, only after the
  choice was committed.
- **Rejected after the holdout:** three choices that looked good on
  2010–2017 did **not** hold out: the extra feature block, a wider take
  profit, and the cointegration block on the final model.
- **Rejected on selection years:**
  - LightGBM and an XGBoost–LightGBM blend;
  - recalibration on recent predictions;
  - seven alternative trade selections;
  - a sector track-record filter;
  - overnight-versus-intraday features and a news-gap filter.

  (Decisions 86–94.)
- **Holdout reuse:** the holdout has been opened in about ten stages, so its
  later results are less clean than its first. The 2024–2025 final test is
  the clean test.

## Goal 1: forecasting mean reversion

The target is whether a divergence (|z| ≥ 2) reverts to |z| ≤ 0.5 within 20
sessions before |z| ≥ 3. The base rate is 5.6 % in 2010–2017 and about 10 %
in 2018–2023.

New point-in-time inputs (`p6_quant_features`, `p6_quant_ou`):

| Block | Contents |
|---|---|
| peer | Each stock's displacement against all its other peers; share of its other pairs diverging; market-wide divergence breadth (Chen et al. 2019; Avellaneda & Lee 2010) |
| state | Zero crossings over 252 days, AR(1) rho, error-correction speed, relationship age |
| earnings | Days since and estimated days to each leg's next earnings 8-K; next earnings inside the holding window |
| momentum | Each leg's 20/120-session return aligned with the divergence; distance to the 252-session high |
| ou | Structural Ornstein–Uhlenbeck Monte Carlo from the pair's AR(1) persistence and realised z volatility: probability of the label, probability of the take profit, expected z captured, implied expected return |
| track | Pair and stock reversion record on earlier resolved events (best observed out of sample; not chosen by the rules) |

**Method comparison** (the same 11,048 and 10,940 labelled events in every
row):

| Model | AUC 2010–17 | AUC 2018–23 | PR-AUC 2018–23 | Log loss 2018–23 | Brier 2018–23 |
|---|---|---|---|---|---|
| Model A (prices only) | 0.684 | 0.711 | 0.204 | 0.2836 | 0.0791 |
| Original Model B (Decision 45 XGBoost) | 0.692 | 0.718 | 0.207 | 0.2832 | 0.0790 |
| **B+rule+ou, bagged (pre-registered Goal 1 model)** | **0.743** | **0.735** | **0.217** | **0.2780** | **0.0781** |
| B+rule+ou+track, bagged (best observed, post-hoc) | 0.745 | 0.739 | 0.222 | 0.2765 | 0.0777 |

Only the headline models are kept (Decision 114). The intermediate steps (OU theory
alone, the recent-scheme Model B, B+rule and the single-fit B+rule+ou) and the failed
versions were erased; their results stay in Decisions 75a–94a.

**Against the original Model B on 2018–2023** (month-block bootstrap):

| Model | Log-loss gain | 95 % | p | AUC gain | p |
|---|---|---|---|---|---|
| Pre-registered Goal 1 model | +0.0053 | — | 0.002 | +0.017 | — |

![ROC curves, holdout](figures/quant/goal1_roc_holdout.png)
![Calibration, holdout](figures/quant/goal1_calibration_holdout.png)

**Findings for the report.**
1. **New information is what helps.** Peer displacement, the earnings
   calendar, momentum and the structural OU prior improve the forecast.
   Tuning, other boosting libraries and the training scheme do not
   (Decisions 66, 70).
2. **A pure econometric model is competitive.** The OU model alone matches
   the original ML model on 2010–2017 but is weaker on 2018–2023. It is most
   useful as an input to the ML model.
3. **Feature subsampling and seed bagging help** once the input set is
   wide (about 170 features).

## Goal 2: the best portfolio

**Better reversion forecasts did not select better trades.** Profit is
roughly probability × payoff scale − costs. The best forecasters
concentrate on tight spreads, whose reversions are small relative to fixed
costs (Decision 87).
- **Tried and failed:** seven alternative selections, including expected-
  value rankings, return regression, OU ranking and the better forecasters.
- **What worked:** the simple original-Model-B top 20 % stayed the most
  robust selection. The gains came from how trades are run.

| Component | Choice | Evidence |
|---|---|---|
| Selection | Original Model B, top 20 % by previous-year cutoff | Seven alternatives failed (Decisions 79a, 85a, 86a, 87a) |
| Entry filter 1 | Skip if the moving company filed earnings in the last 3 sessions or has negative recent news (R1) | Best 2010–2017 portfolio Sharpe (Decision 82a) |
| Entry filter 2 | Skip if the spread has not crossed its mean for more than 120 sessions (a broken relationship) | Decision 89 |
| Take profit | \|z\| ≤ 1.0 (frozen: 0.5) | 36-variant exit grid, confirmed on 2018–2023 (Decision 77); a wider 1.5 failed its holdout (Decision 83b) |
| Adverse stop | Disaster stop at \|z\| ≥ 5 (frozen: 3) | Stops at 3 cut profits; the disaster stop limits the tail (Decision 80a) |
| News exit | E3 adverse-tone exit | Decision 60 |
| Time stop | 20 sessions | 10 was worse in every comparison |

**Portfolio, 2010–2023** (frozen portfolio policy: start NAV 1, 25 % of NAV
per entry, gross ≤ 100 % of NAV, frozen costs and borrow):

| Design | CAGR | Volatility | Sharpe | Max drawdown | Total return |
|---|---|---|---|---|---|
| Trade every divergence, frozen exit (original) | −3.6 % | 4.1 % | −0.86 | −20.0 % | NAV 0.84 by 2014 |
| Model B, news exit (Decision 73 candidate) | −0.5 % | 5.4 % | −0.06 | −18.7 % | −6 % |
| Programme design without the broken-relationship filter | +2.25 % | 5.8 % | 0.41 | −13.8 % | +36 % |
| **Programme design** | **+2.31 %** | 5.8 % | **0.42** | **−13.2 %** | **+37 %** |
| Programme design, 10 % per entry | +2.2 % | 4.4 % | 0.52 | −11.3 % | — |

![Portfolio value](figures/quant/goal2_equity_curves.png)

**Uncertainty.**
- **Sharpe:** the programme design's monthly Sharpe over 2010–2023 is 0.46,
  95 % [−0.06, 1.00] from 5,000 month resamples; P(Sharpe ≤ 0) = 0.048.
- **Months:** 57 % of its 168 months are positive.

**Sensitivities** (the design without the second filter, 25 % per entry,
2010–2023; reported, not used for any choice):

| Scenario | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| Costs 2.5 bps per side | +3.0 % | 0.54 | −12.5 % |
| Frozen (5 bps per side, 1 % borrow) | +2.25 % | 0.41 | −13.8 % |
| Costs 10 bps per side | +0.8 % | 0.16 | −16.3 % |
| Borrow 2 % | +1.8 % | 0.34 | −14.5 % |
| Gross cap 150 % (37.5 % per entry) | +3.2 % | 0.41 | −20.4 % |
| Gross cap 200 % (50 % per entry, no financing cost) | +4.1 % | 0.41 | −26.9 % |

**Caveats.**
- **Costs:** the edge is thin relative to costs. At double the frozen costs
  the design is only marginally positive.
- **Leverage:** the Sharpe of about 0.4–0.5 is modest. Leverage scales
  return and drawdown together.
- **Concentration in time:** most of the profit comes from 2018–2023. In
  the portfolio, 2010–2017 is only mildly positive.
- **Reuse of years:** every year here has been used during development.
  The 2024–2025 final test is the test.

## Realistic costs, portfolio construction and the overfitting audit (Decisions 95–97)

**Costs.**
- **Model:** per stock, a half spread tiered by liquidity (1–8 bps), plus
  square-root market impact (Y = 0.7), plus a 0.5 bps commission.
- **Levels:** at $10m of capital and 25 % of NAV per entry, the median cost
  is 12.7 bps per side against the flat 5 bps.
- **Effect:** under these costs the design's edge mostly disappears.
  Skipping the most expensive fifth of trades (M-1) recovers part of it:
  2018–2023 Sharpe 0.68 against 0.37.

**Portfolio construction.** Smaller positions cut impact.

| Capital | 5 % per entry: Sharpe | CAGR | Max drawdown | 25 % per entry: Sharpe |
|---|---|---|---|---|
| $1m | 0.66 | +2.1 % | — | 0.43 |
| $10m | **0.52** | +1.7 % | −8.4 % | 0.12 |
| $100m | 0.11 | — | — | −0.81 |

The sector cap never binds. The portfolio holds only about 10 positions at
a time because signals, not capital, are scarce, so breadth (a larger
universe) is the remaining lever.

**Selection share and position size (Decisions 98–99).** Under the full
design with realistic costs at $10m:

| Choice | Result |
|---|---|
| Selection share | **Top 20 %** beats 10, 15, 30, 40 and 50 % in both blocks. Narrower shares leave capital idle, and wider shares add trades that do not cover their costs. |
| Position size | 2.5–7.5 % per entry is a plateau (2010–2023 Sharpe 0.51–0.52). **7.5 %** gives the most return there (CAGR +1.9 %, maximum drawdown −8.7 %); 10 % is worse. |
| Liquidity-scaled sizing | Smaller positions in volatile or illiquid pairs is **worse** (Sharpe 0.22–0.37), because those pairs carry the strongest reversals |

**Overfitting audit.**
- **PBO 0.02:** the design choices are stable across splits of the data.
- **Deflated Sharpe ratio** (about 150 trials):
  - 0.72 for the per-candidate design at flat costs;
  - 0.43 for the realistic $10m portfolio.

  Neither reaches 0.95, so the edge is not established beyond the search
  that found it. The final test decides.

## Practitioner-style extensions (Decisions 101–104)

Professional stat-arb desks trade each stock's residual against factors,
net all signals per stock before trading, and earn interest on their
collateral. Each idea was tested here (`p6_resid`, with a daily
open-to-open stock-level engine that reproduces the pairs portfolio within
0.02 Sharpe).

**Residual reversal (Avellaneda & Lee 2010).** Each stock is measured
against its sector ETF or 15 PCA factors and the book bets on the residual
returning, neutral to sectors and market beta.

| Version | Sharpe before costs | Sharpe after costs | Turnover |
|---|---|---|---|
| Daily trading (four variants) | 0.40 to 0.74 | −0.90 to −1.35 | 51–75× a year |
| PCA, trading a tenth of the gap each day (chosen) | 0.57 | +0.08 | 17× |
| The same on 2018–2023 | 0.72 | +0.44 | 17× |

The signal is real before costs, but on 250 large caps it only roughly
breaks even after them. The literature's high residual-reversal Sharpe
ratios come from much larger universes and cheaper execution.

**One netted book.** Adding the residual sleeve to the pairs book raises
the 2010–2017 Sharpe by only +0.01 (0.48 to 0.49), below the
pre-registered +0.05, so the pairs-only design stays. Netting saved
nothing measurable, because the two sleeves rarely trade the same stock on
the same day.

**Cash interest.** Crediting T-bill interest (less 0.25 %) on NAV lifts the
design's 2010–2023 CAGR from +1.8 % to +2.6 %, about US inflation (≈ 2.5 %
a year). Sharpe ratios are unchanged because they are measured in excess
of cash.

**Owner decision: keep every 2010–2017 Sharpe gain (Decisions 105–107).**
Below the pre-registered +0.05 margin, the changes are still kept if they
raised the 2010–2017 Sharpe.

| Step | 2010–2017 Sharpe | 2018–2023 Sharpe | 2010–2023 Sharpe | 2010–2023 CAGR (+ cash) | Max drawdown |
|---|---|---|---|---|---|
| Pairs design (engine) | 0.482 | 0.53 | 0.50 | +1.8 % (+2.6 %) | −9.2 % |
| + residual sleeve, lambda 0.25 | 0.489 | 0.54 | 0.51 | +1.8 % (+2.6 %) | −9.7 % |
| + constant-risk targeting (4 %, 60 days) | 0.491 | 0.50 | 0.49 | +1.8 % (+2.6 %) | −8.4 % |
| + trading at the signal close | 0.613 | 0.52 | 0.57 | +2.1 % (+2.9 %) | −8.0 % |
| **+ hard 200 % gross cap (Decision 108)** | **0.612** | **0.52** | **0.565** | **+2.1 % (+2.9 %)** | **−8.2 %** |

- **Risk targeting** mainly lowers drawdowns; its Sharpe gain did not hold
  on 2018–2023.
- **Close execution** is the largest gain and held on 2018–2023, but it
  breaks even against next-open trading at about 1.5–1.8 bps of extra cost
  per side. The backtest also trades at the closing price that produced the
  signal.
- **The gross cap** is a risk rule: it binds on 14 sessions and costs
  0.003 Sharpe. A half-close, half-open split hedges the look-ahead
  assumption, but on monthly returns it lands between its two halves (0.62
  against 0.65 and 0.55), so it is not adopted.
- **Against inflation:** with cash interest the final book earns about
  2.9 % a year against inflation of about 2.5 %.

**Lesson for the report.** The industry's advantages are breadth and cheap
execution. Without a larger universe, these methods do not add a
measurable edge here. The decisive cost lever was trading speed:
Gârleanu–Pedersen partial trading cut costs by about 85 %.

## Running

```powershell
# features and forecast specs (selection years; add --holdout to confirm)
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant run --specs B+rule+ou --schemes recent:bag5
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant summary
# exit grid (all events, 36 exits, checked against the frozen simulator)
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant_trading build
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant_trading explore-exits
# portfolios from a designs JSON
.venv\Scripts\python.exe -m structural_break.experiments.p6_quant_portfolio --designs outputs\p6_quant\designs_h.json
```
